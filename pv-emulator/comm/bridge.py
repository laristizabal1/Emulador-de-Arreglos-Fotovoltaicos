"""
comm/bridge.py
==============
Puente SCPI <-> Modbus TCP  |  EA-PS 10060-170
Compatibilidad: pymodbus >= 3.12

Arquitectura:
    [EA-PS 10060-170]
          | SCPI / USB-COM  (2-3 ms/query)
          v
    EAPowerSupply  (driver optimizado)
          | polling cada POLL_INTERVAL ms
          v
    ModbusDeviceContext  (registros en memoria)
          | TCP/IP Ethernet
          v
    PLC / SCADA / Microrred DC

Mapa de Holding Registers (Float32 = 2 HR, big-endian high-word first):
  HR  0-1  : Tension medida (V)         Float32
  HR  2-3  : Corriente medida (A)       Float32
  HR  4-5  : Potencia medida (W)        Float32
  HR  6-7  : Tension setpoint (V)       Float32  [cache local]
  HR  8-9  : Corriente setpoint (A)     Float32  [cache local]
  HR  10   : Estado salida (0=OFF/1=ON) UInt16
  HR  11   : Remoto activo              UInt16   [siempre 1]
  HR  12   : Codigo de error SCPI       UInt16

Coil 0 (escritura desde cliente Modbus): 1 = Output ON, 0 = Output OFF

Dependencias:
    pip install pyserial pymodbus>=3.12

Diseño para 20 ms:
    - Una sola query SCPI por ciclo (MEAS:ALL? -> V,I,P en una respuesta)
    - Setpoints V/I cacheados localmente (no se consultan a la fuente)
    - Escritura en bloque de todos los registros en un solo setValues()
    - Delays serie minimos: 2 ms write / 3 ms query
    - asyncio para el servidor Modbus (no bloquea el polling)
    - threading.Event.wait() en vez de time.sleep() para interrupcion limpia
"""

from __future__ import annotations

import asyncio
import struct
import threading
import time
import logging
from dataclasses import dataclass, field
from typing import Optional, Tuple

from config.hardware import V_MAX, I_MAX, DT_MIN

# pyserial
try:
    import serial
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False

# pymodbus 3.12
try:
    from pymodbus import ModbusDeviceIdentification
    from pymodbus.server import ModbusTcpServer
    from pymodbus.datastore import (
        ModbusSequentialDataBlock,
        ModbusServerContext,
        ModbusDeviceContext,
    )
    MODBUS_AVAILABLE = True
except ImportError:
    MODBUS_AVAILABLE = False

log = logging.getLogger("Bridge")


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURACION
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class BridgeConfig:
    # Conexion SCPI a la fuente EA
    serial_port:    str   = "COM7"
    serial_baud:    int   = 115200
    serial_timeout: float = 0.05     # 50 ms — reducido al maximo tolerable

    # Delays minimos de comunicacion SCPI (ms)
    write_delay_ms: float = 2.0      # delay tras write
    query_delay_ms: float = 3.0      # delay entre write y readline

    # Servidor Modbus TCP
    modbus_host:    str   = "0.0.0.0"
    modbus_port:    int   = 502
    modbus_unit:    int   = 1

    # Frecuencia de actualizacion de registros
    # 20 ms = 50 Hz — limite practico con SCPI serie a 115200 baud
    poll_interval_ms: float = 20.0


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS: Float32 <-> Holding Registers Modbus
# ─────────────────────────────────────────────────────────────────────────────

def _f2r(value: float) -> Tuple[int, int]:
    """Float32 -> (high_word, low_word) big-endian."""
    raw = struct.pack(">f", float(value))
    return struct.unpack(">HH", raw)


def _r2f(high: int, low: int) -> float:
    """(high_word, low_word) -> Float32."""
    return struct.unpack(">f", struct.pack(">HH", high, low))[0]


def _parse_float(raw: str) -> Optional[float]:
    """Parsea respuesta SCPI '10.00 V' o '2.5' -> float. None si falla."""
    try:
        return float(raw.strip().split()[0])
    except (ValueError, IndexError):
        return None


# ─────────────────────────────────────────────────────────────────────────────
# DRIVER SCPI OPTIMIZADO
# Diseñado para minima latencia: delays de 2-3 ms, query combinada, cache
# ─────────────────────────────────────────────────────────────────────────────

class EAPowerSupply:
    """
    Driver SCPI de baja latencia para EA-PS 10060-170.

    Estrategia de 20 ms:
      1. _read_meas_fast(): intenta MEAS:ALL? -> V,I,P en una sola query.
         Si la fuente no lo soporta, cae en MEAS:VOLT? + MEAS:CURR? por
         separado (16 ms worst-case, aun dentro del budget de 20 ms con
         baud 115200 y cable USB de baja latencia).
      2. Setpoints V/I NO se consultan a la fuente — se cachean localmente
         cada vez que se envian desde el pipeline o el control manual.
      3. write_batch() envia multiples comandos sin delay entre ellos
         (solo 1 ms de separacion) para la inicializacion.
    """

    def __init__(self, cfg: BridgeConfig):
        self.cfg   = cfg
        self.ser: Optional[object] = None
        self._lock = threading.Lock()

        # Delays convertidos a segundos para usar en time.sleep
        self._wd = cfg.write_delay_ms / 1000.0
        self._qd = cfg.query_delay_ms / 1000.0

        # Cache de setpoints (actualizados al enviar comandos, no consultados)
        self._cache_v:   float = 0.0
        self._cache_i:   float = 0.0
        self._cache_out: int   = 0

        # Modo de lectura: "all" usa MEAS:ALL?, "separate" usa dos queries
        self._meas_mode: str = "all"

    # -- Conexion -------------------------------------------------------------
    def open(self) -> str:
        if not SERIAL_AVAILABLE:
            raise RuntimeError("pyserial no instalado: pip install pyserial")
        self.ser = serial.Serial(
            port      = self.cfg.serial_port,
            baudrate  = self.cfg.serial_baud,
            timeout   = self.cfg.serial_timeout,
            write_timeout = self.cfg.serial_timeout,
        )
        time.sleep(0.1)
        return self._query_raw("*IDN?")

    def close(self) -> None:
        if self.ser and self.ser.is_open:
            self.ser.close()

    # -- Comunicacion base ----------------------------------------------------
    def _write_raw(self, cmd: str) -> None:
        """Escribe un comando SCPI. NO usa el lock — llamar desde metodos que ya lo tienen."""
        self.ser.write((cmd.strip() + "\n").encode("ascii"))
        time.sleep(self._wd)

    def _readline_raw(self) -> str:
        """Lee una linea de respuesta SCPI."""
        time.sleep(self._qd)
        return self.ser.readline().decode("ascii", errors="ignore").strip()

    def _query_raw(self, cmd: str) -> str:
        """Write + readline sin lock."""
        self.ser.write((cmd.strip() + "\n").encode("ascii"))
        time.sleep(self._qd)
        return self.ser.readline().decode("ascii", errors="ignore").strip()

    def write(self, cmd: str) -> None:
        with self._lock:
            self._write_raw(cmd)

    def query(self, cmd: str) -> str:
        with self._lock:
            return self._query_raw(cmd)

    def write_batch(self, commands: list[str]) -> None:
        """Envia multiples comandos con 1 ms entre ellos (inicializacion rapida)."""
        with self._lock:
            for cmd in commands:
                self.ser.write((cmd.strip() + "\n").encode("ascii"))
                time.sleep(0.001)

    # -- Lectura de mediciones OPTIMIZADA para 20 ms --------------------------
    def read_meas_fast(self) -> Tuple[float, float, float]:
        """
        Lee V, I, P medidos en el menor tiempo posible.

        Intenta primero MEAS:ALL? (una sola query, ~8 ms con baud 115200).
        Si la fuente devuelve error o formato inesperado, cae en modo
        separado MEAS:VOLT? + MEAS:CURR? (~16 ms).

        La potencia se calcula como V*I si MEAS:ALL? no la incluye.

        Returns: (V_meas, I_meas, P_meas) — (0.0, 0.0, 0.0) si falla.
        """
        with self._lock:
            if self._meas_mode == "all":
                try:
                    resp = self._query_raw("MEAS:ALL?")
                    parts = [p.strip() for p in resp.split(",")]
                    if len(parts) >= 2:
                        v = _parse_float(parts[0]) or 0.0
                        i = _parse_float(parts[1]) or 0.0
                        p = _parse_float(parts[2]) if len(parts) >= 3 else v * i
                        return v, i, (p or v * i)
                    # Respuesta invalida -> cambiar a modo separado
                    self._meas_mode = "separate"
                    log.warning("Bridge: MEAS:ALL? no soportado, usando queries separadas (~16ms)")
                except Exception:
                    self._meas_mode = "separate"

            # Modo separado: dos queries independientes
            v = 0.0
            i = 0.0
            for cmd, store in [("MEAS:VOLT?", "v"), ("MEAS:CURR?", "i")]:
                try:
                    raw = self._query_raw(cmd)
                    val = _parse_float(raw) or 0.0
                    if store == "v":
                        v = val
                    else:
                        i = val
                except Exception:
                    pass
            return v, i, v * i

    def get_output_state(self) -> int:
        """Lee el estado de la salida DC (0 o 1). Usa el cache si la lectura falla."""
        try:
            resp = self.query("OUTP:STAT?")
            state = 1 if resp.strip() in ("1", "ON") else 0
            self._cache_out = state
            return state
        except Exception:
            return self._cache_out

    def get_error_code(self) -> int:
        """Lee el codigo de error SCPI. Retorna 0 si falla."""
        try:
            raw = self.query("SYST:ERR?")
            return int(raw.split(",")[0])
        except Exception:
            return 0

    # -- Comandos de control --------------------------------------------------
    def output(self, on: bool) -> None:
        self.write(f"OUTP {'ON' if on else 'OFF'}")
        self._cache_out = 1 if on else 0

    def set_voltage(self, v: float) -> None:
        v_safe = min(max(float(v), 0.0), V_MAX)
        self.write(f"VOLT {v_safe:.4g}")
        self._cache_v = v_safe

    def set_current_limit(self, a: float) -> None:
        a_safe = min(max(float(a), 0.0), I_MAX)
        self.write(f"CURR {a_safe:.4g}")
        self._cache_i = a_safe

    def setup_batch(self, voltage: float, current: float) -> None:
        """Configura V e I en un solo batch (2 comandos, ~3 ms total)."""
        v_safe = min(max(float(voltage), 0.0), V_MAX)
        a_safe = min(max(float(current), 0.0), I_MAX)
        self.write_batch([f"VOLT {v_safe:.4g}", f"CURR {a_safe:.4g}"])
        self._cache_v = v_safe
        self._cache_i = a_safe

    @property
    def cached_vset(self) -> float:
        return self._cache_v

    @property
    def cached_iset(self) -> float:
        return self._cache_i


# ─────────────────────────────────────────────────────────────────────────────
# BRIDGE PRINCIPAL: SCPI <-> Modbus TCP
# ─────────────────────────────────────────────────────────────────────────────

class ScpiModbusBridge:
    """
    Puente SCPI <-> Modbus TCP con actualizacion de registros a 20 ms.

    Dos componentes en threads separados:
      - _poll_loop (thread daemon): lee SCPI y actualiza los HR Modbus
      - Servidor Modbus TCP (asyncio en thread daemon): atiende clientes

    El pipeline PV (SCPIController en comm/scpi.py) usa el mismo puerto COM
    para enviar consignas del perfil. Para evitar colision:
      - Durante la ejecucion del perfil, el bridge sigue poliando mediciones
        pero NO envia comandos de voltaje/corriente.
      - El Coil 0 de Modbus (control remoto desde SCADA) queda deshabilitado
        automaticamente mientras el pipeline esta activo.

    Atributos publicos:
      running        : True si el bridge esta activo
      last_readings  : dict con las ultimas mediciones (para la HMI)
    """

    def __init__(self, cfg: BridgeConfig):
        self.cfg  = cfg
        self.ps   = EAPowerSupply(cfg)

        self._stop       = threading.Event()
        self._prev_coil0 = 0
        self.running     = False

        # Bloqueo externo: si True, el bridge no responde al Coil 0
        # (el pipeline lo activa mientras corre un perfil)
        self.profile_running = False

        # Cache de lecturas para la HMI (sin overhead de lock en la UI)
        self.last_readings: dict = {
            "V": 0.0, "I": 0.0, "P": 0.0,
            "Vset": 0.0, "Iset": 0.0,
            "output": 0, "error": 0,
            "meas_mode": "all",
            "poll_ms": 0.0,
        }

        # Datastore Modbus — se construye en start()
        self._device: Optional[object] = None   # ModbusDeviceContext
        self._ctx:    Optional[object] = None   # ModbusServerContext

    # -- Datastore Modbus -----------------------------------------------------
    def _build_datastore(self):
        di = ModbusSequentialDataBlock(0, [0] * 10)
        co = ModbusSequentialDataBlock(0, [0] * 10)
        hr = ModbusSequentialDataBlock(0, [0] * 20)
        ir = ModbusSequentialDataBlock(0, [0] * 20)
        self._device = ModbusDeviceContext(di=di, co=co, hr=hr, ir=ir)
        self._ctx    = ModbusServerContext(
            devices={self.cfg.modbus_unit: self._device}, single=False
        )

    def _write_registers(self, v: float, i: float, p: float,
                         vset: float, iset: float,
                         out: int, err: int) -> None:
        """
        Escribe todos los Holding Registers en una sola llamada por tipo.
        Agrupa los 13 registros (0-12) en dos setValues para minimizar overhead.
        """
        # HR 0-9: mediciones y setpoints como Float32
        hv,  lv  = _f2r(v)
        hi,  li  = _f2r(i)
        hp,  lp  = _f2r(p)
        hvs, lvs = _f2r(vset)
        his, lis = _f2r(iset)

        # Escritura en bloque: HR 0 al 9 (10 registros, 1 llamada)
        self._device.setValues(
            3, 0, [hv, lv, hi, li, hp, lp, hvs, lvs, his, lis]
        )
        # HR 10, 11, 12 (3 registros, 1 llamada)
        self._device.setValues(3, 10, [out, 1, err & 0xFFFF])

    def _read_coil0(self) -> int:
        return int(self._device.getValues(1, 0, 1)[0])

    # -- Loop de polling (thread daemon) --------------------------------------
    def _poll_loop(self) -> None:
        """
        Ciclo principal: SCPI -> Modbus a la frecuencia configurada.

        Compensacion de tiempo: mide el tiempo real de cada ciclo y
        ajusta el wait para mantener el intervalo estable a 20 ms.
        """
        dt_s = self.cfg.poll_interval_ms / 1000.0
        log.info(
            f"Bridge: polling iniciado — intervalo {self.cfg.poll_interval_ms} ms"
        )

        while not self._stop.is_set():
            t_start = time.perf_counter()

            try:
                # --- Lectura SCPI (parte mas costosa: 8-16 ms) ---------------
                v, i, p = self.ps.read_meas_fast()
                vset    = self.ps.cached_vset
                iset    = self.ps.cached_iset

                # Output state: solo cada 10 ciclos (200 ms) para no saturar
                # el bus serie con consultas que rara vez cambian
                if not hasattr(self, "_out_cycle"):
                    self._out_cycle = 0
                self._out_cycle = (self._out_cycle + 1) % 10
                if self._out_cycle == 0:
                    out = self.ps.get_output_state()
                    err = self.ps.get_error_code()
                else:
                    out = self.ps.cached_vset >= 0   # aproximacion desde cache
                    out = self.last_readings.get("output", 0)
                    err = 0

                # --- Escritura en registros Modbus (< 0.1 ms) ----------------
                self._write_registers(v, i, p, vset, iset, int(out), int(err))

                # --- Cache para la HMI ---------------------------------------
                elapsed_ms = (time.perf_counter() - t_start) * 1000.0
                self.last_readings = {
                    "V":        round(v,    3),
                    "I":        round(i,    4),
                    "P":        round(p,    2),
                    "Vset":     round(vset, 3),
                    "Iset":     round(iset, 4),
                    "output":   int(out),
                    "error":    int(err),
                    "meas_mode": self.ps._meas_mode,
                    "poll_ms":  round(elapsed_ms, 2),
                }

                # --- Coil 0: control remoto desde SCADA ----------------------
                # Solo actua si el pipeline NO esta corriendo un perfil
                if not self.profile_running:
                    c0 = self._read_coil0()
                    if c0 != self._prev_coil0:
                        self.ps.output(bool(c0))
                        self._prev_coil0 = c0
                        log.info(
                            f"Bridge: Coil0 -> OUTP {'ON' if c0 else 'OFF'}"
                        )

            except Exception as exc:
                log.error(f"Bridge poll error: {exc}")

            # Compensacion de tiempo para mantener dt estable
            elapsed = time.perf_counter() - t_start
            wait    = max(0.0, dt_s - elapsed)
            if wait > 0:
                self._stop.wait(timeout=wait)   # interruptible

        log.info("Bridge: polling detenido.")

    # -- Servidor Modbus TCP (asyncio) ----------------------------------------
    def _run_modbus_server(self) -> None:
        """
        Corre el servidor Modbus TCP en un loop asyncio propio.
        Se lanza en un thread daemon para no bloquear la HMI.
        """
        async def _serve():
            identity = ModbusDeviceIdentification(
                info_name={
                    "VendorName":   "EA Elektro-Automatik",
                    "ProductCode":  "PS10060-170",
                    "ProductName":  "PV Emulator Bridge",
                    "ModelName":    "ScpiModbusBridge 1.0",
                }
            )
            server = ModbusTcpServer(
                context  = self._ctx,
                identity = identity,
                address  = (self.cfg.modbus_host, self.cfg.modbus_port),
            )
            log.info(
                f"Bridge: Modbus TCP en "
                f"{self.cfg.modbus_host}:{self.cfg.modbus_port} "
                f"Unit={self.cfg.modbus_unit}"
            )
            await server.serve_forever()

        # Loop asyncio propio (no comparte el de Dash/Flask)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_serve())
        except Exception as exc:
            log.error(f"Bridge Modbus server error: {exc}")
        finally:
            loop.close()

    def start_shared(self, ser) -> None:
        """
        Inicia el bridge reutilizando un serial.Serial ya abierto por
        SCPIController — evita PermissionError por doble apertura de COM.

        Usar en scpi_cb.py:
            bridge.start_shared(_controller._ser)
        """
        self.ps.ser = ser
        self._build_datastore()
        self._stop.clear()
        self.running = True

        threading.Thread(
            target=self._poll_loop,
            daemon=True,
            name='BridgePoll',
        ).start()

        threading.Thread(
            target=self._run_modbus_server,
            daemon=True,
            name='BridgeTCP',
        ).start()

        log.info(
            f'Bridge activo (serial compartido) — '
            f'poll {self.cfg.poll_interval_ms} ms'
        )

    # -- start() original (abre su propio COM) --------------------------------
    # -- API publica ----------------------------------------------------------
    def start(self) -> None:
        """
        Abre el puerto COM, construye el datastore Modbus, lanza el polling
        y arranca el servidor TCP. NO bloquea.
        """
        idn = self.ps.open()
        log.info(f"Bridge conectado: {idn}")

        self._build_datastore()
        self._stop.clear()
        self.running = True

        # Thread de polling SCPI -> Modbus
        threading.Thread(
            target=self._poll_loop,
            daemon=True,
            name="BridgePoll",
        ).start()

        # Thread del servidor Modbus TCP (asyncio)
        threading.Thread(
            target=self._run_modbus_server,
            daemon=True,
            name="BridgeTCP",
        ).start()

        log.info(
            f"Bridge activo — poll {self.cfg.poll_interval_ms} ms, "
            f"modo MEAS: {self.ps._meas_mode}"
        )

    def stop(self) -> None:
        """Detiene el polling, apaga la salida y cierra el puerto."""
        self._stop.set()
        self.running = False
        try:
            self.ps.output(False)
            self.ps.set_voltage(0.0)
        except Exception:
            pass
        self.ps.close()
        log.info("Bridge detenido. Salida apagada.")

    def get_readings(self) -> dict:
        """Copia de las ultimas mediciones para mostrar en la HMI."""
        return dict(self.last_readings)