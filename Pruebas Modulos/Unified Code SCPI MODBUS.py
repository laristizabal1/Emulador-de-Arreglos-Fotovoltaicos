"""
=============================================================================
  SCPI ➜ Modbus TCP Bridge  |  EA PS 10060-170 EA  —  VERSIÓN UNIFICADA
=============================================================================
  Combina:
    • Driver SCPI optimizado (delays mínimos, caché de comandos, batch setup)
    • Generador de rampas y escalones (ramp / step)
    • Servidor Modbus TCP (exposición de datos por Ethernet)

  Arquitectura:
    [EA PS 10060-170]
          │  SCPI / RS232 (COM)
          ▼
    ┌─────────────────────┐
    │  EAPowerSupply      │  ← driver optimizado (<200ms/cmd)
    │  (ramp / step)      │
    └────────┬────────────┘
             │  polling cada POLL_INTERVAL s
             ▼
    ┌─────────────────────┐
    │  Modbus TCP Server  │  ← escucha en MODBUS_PORT
    │  Holding Registers  │
    └─────────────────────┘
             │  Ethernet
             ▼
       PLC / SCADA / HMI

  Mapa de Holding Registers (Float32 = 2 HR, big-endian high-word first):
  ┌────────┬──────────────────────────┬───────────┐
  │  HR    │  Variable                │  Tipo     │
  ├────────┼──────────────────────────┼───────────┤
  │  0-1   │  Tensión medida (V)      │  Float32  │
  │  2-3   │  Corriente medida (A)    │  Float32  │
  │  4-5   │  Potencia medida (W)     │  Float32  │
  │  6-7   │  Tensión setpoint (V)    │  Float32  │
  │  8-9   │  Corriente setpoint (A)  │  Float32  │
  │  10    │  Estado salida (0/1)     │  UInt16   │
  │  11    │  Modo remoto activo      │  UInt16   │
  │  12    │  Código de error         │  UInt16   │
  └────────┴──────────────────────────┴───────────┘

  Coil 0 (escritura Modbus): 1 = Output ON, 0 = Output OFF

  Dependencias:
    pip install pyserial "pymodbus==3.7.4"
=============================================================================
"""

from __future__ import annotations

import struct
import threading
import time
import logging
from dataclasses import dataclass
from typing import Optional, Tuple

import serial
from pymodbus.server import StartTcpServer
from pymodbus.datastore import (
    ModbusSequentialDataBlock,
    ModbusSlaveContext,
    ModbusServerContext,
)
from pymodbus.device import ModbusDeviceIdentification

# ═════════════════════════════════════════════════
#  CONFIGURACIÓN GLOBAL  ←  Ajusta estos valores
# ═════════════════════════════════════════════════

# ── Puerto serie ──────────────────────────────────
SERIAL_PORT     = "COM7"       # Puerto COM de la fuente
SERIAL_BAUD     = 115200       # Baud rate optimizado (verifica en la fuente)
SERIAL_TIMEOUT  = 0.2          # Timeout reducido para detección rápida de fallos

# ── Modbus TCP ────────────────────────────────────
MODBUS_HOST     = "0.0.0.0"   # Escucha en todas las interfaces
MODBUS_PORT     = 502          # Puerto Modbus TCP estándar (usa 5020 sin admin)
MODBUS_UNIT     = 1            # ID de esclavo Modbus
POLL_INTERVAL   = 0.5          # Segundos entre lecturas SCPI → Modbus

# ── Modo de operación ─────────────────────────────
#   "ramp"  → rampa continua entre V_MIN y V_MAX
#   "step"  → escalón único V_LOW → V_HIGH → V_LOW
#   "none"  → solo monitoreo sin modificar voltaje
OPERATION_MODE  = "ramp"

# ── Parámetros de la rampa (OPERATION_MODE = "ramp") ──
RAMP_V_MIN      = 5.0          # Voltaje mínimo (V)
RAMP_V_MAX      = 10.0         # Voltaje máximo (V)
RAMP_V_STEP     = 0.5          # Paso de voltaje (V)
RAMP_DT_MS      = 1000         # Tiempo entre pasos (ms)
RAMP_I_LIMIT    = 2.0          # Límite de corriente (A)
RAMP_P_LIMIT    = 100.0        # Límite de potencia (W)
RAMP_READBACK   = True         # Leer V/I tras cada paso

# ── Parámetros del escalón (OPERATION_MODE = "step") ──
STEP_V_LOW      = 5.0          # Voltaje bajo (V)
STEP_V_HIGH     = 10.0         # Voltaje alto (V)
STEP_DT_MS      = 500          # Duración de cada nivel (ms)
STEP_I_LIMIT    = 2.0          # Límite de corriente (A)
STEP_P_LIMIT    = 100.0        # Límite de potencia (W)
STEP_N_PRE_UP   = 2            # Ciclos en V_LOW antes de subir
STEP_N_PRE_DOWN = 2            # Ciclos en V_HIGH antes de bajar
STEP_READBACK   = True         # Leer V/I tras cada paso

# ═════════════════════════════════════════════════
#  LOGGING
# ═════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("SCPI-Modbus")

# ═════════════════════════════════════════════════
#  HELPERS: Float32 ↔ Registros Modbus
# ═════════════════════════════════════════════════

def float_to_registers(value: float) -> list:
    """Float32 → [high_word, low_word]  (big-endian)"""
    raw  = struct.pack(">f", float(value))
    high = struct.unpack(">H", raw[0:2])[0]
    low  = struct.unpack(">H", raw[2:4])[0]
    return [high, low]

def registers_to_float(regs: list) -> float:
    """[high_word, low_word] → Float32"""
    raw = struct.pack(">HH", regs[0], regs[1])
    return struct.unpack(">f", raw)[0]

def parse_scpi_float(raw: str) -> float:
    """Limpia respuesta SCPI como '10.00 V' o '2.500 A' y retorna float."""
    # Toma solo la primera palabra (el número) e ignora la unidad
    return float(raw.strip().split()[0])
# ═════════════════════════════════════════════════
#  DRIVER SCPI OPTIMIZADO  (EA PS 10060-170)
# ═════════════════════════════════════════════════

@dataclass
class EAConfig:
    port:           str   = SERIAL_PORT
    baudrate:       int   = SERIAL_BAUD
    timeout_s:      float = SERIAL_TIMEOUT
    write_delay_s:  float = 0.002   # 2ms — la fuente EA lo tolera
    query_delay_s:  float = 0.003   # 3ms — tiempo mínimo de respuesta
    newline:        str   = "\n"
    use_readline:   bool  = True    # readline() es más eficiente que read(4096)


class EAPowerSupply:
    def __init__(self, cfg: EAConfig):
        self.cfg  = cfg
        self.ser: Optional[serial.Serial] = None
        self._lock = threading.Lock()

        # Caché de comandos exitosos para evitar reintentos
        self._power_cmd:        Optional[str] = None
        self._voltage_meas_cmd: str = "MEAS:VOLT?"
        self._current_meas_cmd: str = "MEAS:CURR?"

    # ── Conexión ──────────────────────────────────
    def open(self) -> bool:
        try:
            self.ser = serial.Serial(
                self.cfg.port,
                self.cfg.baudrate,
                timeout=self.cfg.timeout_s,
                write_timeout=self.cfg.timeout_s,
            )
            time.sleep(0.05)
            idn = self.idn()
            log.info(f"Fuente conectada: {idn}")
            return True
        except Exception as e:
            log.error(f"No se pudo abrir {self.cfg.port}: {e}")
            return False

    def close(self) -> None:
        if self.ser and self.ser.is_open:
            self.ser.close()
            log.info("Puerto serie cerrado.")

    def _ensure_open(self) -> serial.Serial:
        if self.ser is None or not self.ser.is_open:
            raise RuntimeError("Puerto no abierto. Llama a open() primero.")
        return self.ser

    # ── Comunicación base ─────────────────────────
    def write(self, cmd: str) -> None:
        with self._lock:
            ser = self._ensure_open()
            ser.write((cmd.strip() + self.cfg.newline).encode("ascii"))
            time.sleep(self.cfg.write_delay_s)

    def query(self, cmd: str) -> str:
        with self._lock:
            ser = self._ensure_open()
            ser.write((cmd.strip() + self.cfg.newline).encode("ascii"))
            time.sleep(self.cfg.query_delay_s)
            if self.cfg.use_readline:
                resp = ser.readline().decode("ascii", errors="ignore").strip()
            else:
                resp = ser.read(256).decode("ascii", errors="ignore").strip()
            return resp

    def write_batch(self, commands: list) -> None:
        """Envía múltiples comandos con delay mínimo entre ellos."""
        with self._lock:
            ser = self._ensure_open()
            for cmd in commands:
                ser.write((cmd.strip() + self.cfg.newline).encode("ascii"))
                time.sleep(0.001)

    # ── Comandos de alto nivel ────────────────────
    def idn(self) -> str:
        return self.query("*IDN?")

    def output(self, on: bool) -> None:
        self.write(f"OUTP {'ON' if on else 'OFF'}")
        log.info(f"Salida → {'ON' if on else 'OFF'}")

    def set_voltage(self, v: float) -> None:
        self.write(f"VOLT {v:.4g}")

    def set_current_limit(self, a: float) -> None:
        self.write(f"CURR {a:.4g}")

    def try_set_power_limit(self, w: float) -> bool:
        """Intenta poner límite de potencia; usa caché si ya sabe qué comando funciona."""
        if self._power_cmd is not None:
            try:
                self.write(self._power_cmd.format(w=w))
                return True
            except Exception:
                self._power_cmd = None

        for candidate in [f"POW {w}", f"SOUR:POW {w}", f"POWer {w}"]:
            try:
                self.write(candidate)
                self._power_cmd = candidate.replace(str(w), "{w}")
                return True
            except Exception:
                pass
        return False

    def setup_batch(self, voltage: float, current: float, power: Optional[float] = None) -> None:
        """Configura V/I/P en un solo batch para inicialización rápida."""
        cmds = [f"VOLT {voltage:.4g}", f"CURR {current:.4g}"]
        if power is not None and self._power_cmd:
            cmds.append(self._power_cmd.format(w=power))
        self.write_batch(cmds)

    # ── Mediciones con fallback y caché ───────────
    def try_read_meas(self) -> Tuple[Optional[float], Optional[float]]:
        """Lee V e I medidos; usa comandos cacheados y prueba alternativos si fallan."""
        v = i = None

        for attr, fallbacks in [
            ("_voltage_meas_cmd", ["VOLT?", "MEAS:SCAL:VOLT?"]),
            ("_current_meas_cmd", ["CURR?", "MEAS:SCAL:CURR?"]),
        ]:
            primary = getattr(self, attr)
            try:
                r = self.query(primary)
                val = parse_scpi_float(r.split(",")[0]) if r else None
            except Exception:
                val = None
                for fb in fallbacks:
                    try:
                        r = self.query(fb)
                        val = float(r.split(",")[0]) if r else None
                        if val is not None:
                            setattr(self, attr, fb)
                            break
                    except Exception:
                        pass

            if attr == "_voltage_meas_cmd":
                v = val
            else:
                i = val

        return v, i

    def get_output_state(self) -> int:
        resp = self.query("OUTP:STAT?")
        return 1 if resp in ("1", "ON") else 0

    def get_error_code(self) -> int:
        try:
            return int(self.query("SYST:ERR?").split(",")[0])
        except Exception:
            return 0

# ═════════════════════════════════════════════════
#  GENERADORES DE FORMA DE ONDA
# ═════════════════════════════════════════════════

def _frange(a: float, b: float, step: float) -> list:
    """Genera valores de a a b con paso step (incluye extremos)."""
    if a == b:
        return [a]
    s = step if b > a else -step
    vals, x = [], a
    while (x < b if s > 0 else x > b):
        vals.append(round(x, 6))
        x += s
    vals.append(b)
    return vals


def ramp_continuous(
    ps: EAPowerSupply,
    v_min: float,
    v_max: float,
    v_step: float,
    dt_ms: int,
    i_limit: float,
    p_limit: float,
    stop_event: threading.Event,
    readback: bool = True,
) -> None:
    """
    Rampa continua v_min → v_max → v_min en loop hasta que stop_event se active.
    Compensa el tiempo de ejecución del comando para mantener dt_ms exacto.
    """
    ps.setup_batch(v_min, i_limit, p_limit)
    ps.output(True)

    up   = _frange(v_min, v_max, v_step)
    down = _frange(v_max, v_min, v_step)
    dt_s = dt_ms / 1000.0

    log.info(f"Rampa continua: {v_min}V → {v_max}V  paso={v_step}V  dt={dt_ms}ms")

    while not stop_event.is_set():
        for direction, steps in [("▲", up), ("▼", down)]:
            for v in steps:
                if stop_event.is_set():
                    break
                t0 = time.perf_counter()
                ps.set_voltage(v)

                if readback:
                    vm, im = ps.try_read_meas()
                    log.info(f"  {direction} Vset={v:.2f}V  Vmeas={vm}  Imeas={im}")
                else:
                    log.info(f"  {direction} Vset={v:.2f}V")

                elapsed = time.perf_counter() - t0
                wait    = max(0.0, dt_s - elapsed)
                if wait > 0:
                    stop_event.wait(timeout=wait)   # interruptible con stop_event


def step_once(
    ps: EAPowerSupply,
    v_low: float,
    v_high: float,
    dt_ms: int,
    i_limit: float,
    p_limit: float,
    n_pre_up: int,
    n_pre_down: int,
    stop_event: threading.Event,
    readback: bool = True,
) -> None:
    """
    Escalón único: V_LOW (n_pre_up ciclos) → V_HIGH (n_pre_down ciclos) → V_LOW.
    """
    ps.setup_batch(v_low, i_limit, p_limit)
    ps.output(True)
    dt_s = dt_ms / 1000.0

    log.info(f"Escalón: {v_low}V → {v_high}V  dt={dt_ms}ms")

    def do_step(v: float, label: str):
        if stop_event.is_set():
            return
        t0 = time.perf_counter()
        ps.set_voltage(v)
        if readback:
            vm, im = ps.try_read_meas()
            log.info(f"  {label} Vset={v:.2f}V  Vmeas={vm}  Imeas={im}")
        elapsed = time.perf_counter() - t0
        stop_event.wait(timeout=max(0.0, dt_s - elapsed))

    for _ in range(n_pre_up):
        do_step(v_low, "LOW (pre)  →")
    do_step(v_low,  "LOW        →")
    do_step(v_high, "HIGH       →")
    for _ in range(n_pre_down):
        do_step(v_high, "HIGH (hold)→")
    do_step(v_low, "LOW (back) →")

# ═════════════════════════════════════════════════
#  BRIDGE PRINCIPAL: une SCPI + Modbus TCP
# ═════════════════════════════════════════════════

class ScpiModbusBridge:
    def __init__(self):
        cfg   = EAConfig()
        self.ps = EAPowerSupply(cfg)

        # Datastore Modbus
        slave = ModbusSlaveContext(
            di=ModbusSequentialDataBlock(0, [0] * 10),
            co=ModbusSequentialDataBlock(0, [0] * 10),
            hr=ModbusSequentialDataBlock(0, [0] * 20),
            ir=ModbusSequentialDataBlock(0, [0] * 20),
        )
        self.ctx = ModbusServerContext(slaves={MODBUS_UNIT: slave}, single=False)

        self._stop       = threading.Event()
        self._prev_coil0 = 0

    # ── Helpers Modbus datastore ──────────────────
    def _wr(self, addr: int, values: list):
        self.ctx[MODBUS_UNIT].setValues(3, addr, values)

    def _rd_coil(self, addr: int) -> int:
        return int(self.ctx[MODBUS_UNIT].getValues(1, addr, 1)[0])

    # ── Loop de polling: SCPI → Modbus ───────────
    def _poll_loop(self):
        log.info("Polling SCPI → Modbus iniciado.")
        while not self._stop.is_set():
            try:
                v,  i   = self.ps.try_read_meas()
                v   = v or 0.0
                i   = i or 0.0
                p   = v * i
                vs  = parse_scpi_float(self.ps.query("VOLT?") or "0")
                is_ = parse_scpi_float(self.ps.query("CURR?") or "0")
                out = self.ps.get_output_state()
                err = self.ps.get_error_code()

                self._wr(0,  float_to_registers(v))    # V medida
                self._wr(2,  float_to_registers(i))    # I medida
                self._wr(4,  float_to_registers(p))    # P medida
                self._wr(6,  float_to_registers(vs))   # V setpoint
                self._wr(8,  float_to_registers(is_))  # I setpoint
                self._wr(10, [out])                     # Estado salida
                self._wr(11, [1])                       # Remoto activo
                self._wr(12, [err & 0xFFFF])            # Código error

                log.info(
                    f"[Modbus] V={v:.3f}V  I={i:.4f}A  P={p:.2f}W  "
                    f"Vset={vs:.3f}V  Iset={is_:.4f}A  OUT={'ON' if out else 'OFF'}"
                )

                # Comando desde cliente Modbus → Coil 0 controla la salida
                c0 = self._rd_coil(0)
                if c0 != self._prev_coil0:
                    self.ps.output(bool(c0))
                    self._prev_coil0 = c0

            except Exception as e:
                log.error(f"Error en poll: {e}")

            self._stop.wait(timeout=POLL_INTERVAL)

    # ── Loop de forma de onda (rampa / escalón) ───
    def _waveform_loop(self):
        time.sleep(0.5)   # Espera que el servidor Modbus arranque

        if OPERATION_MODE == "ramp":
            while not self._stop.is_set():
                ramp_continuous(
                    ps         = self.ps,
                    v_min      = RAMP_V_MIN,
                    v_max      = RAMP_V_MAX,
                    v_step     = RAMP_V_STEP,
                    dt_ms      = RAMP_DT_MS,
                    i_limit    = RAMP_I_LIMIT,
                    p_limit    = RAMP_P_LIMIT,
                    stop_event = self._stop,
                    readback   = RAMP_READBACK,
                )

        elif OPERATION_MODE == "step":
            step_once(
                ps         = self.ps,
                v_low      = STEP_V_LOW,
                v_high     = STEP_V_HIGH,
                dt_ms      = STEP_DT_MS,
                i_limit    = STEP_I_LIMIT,
                p_limit    = STEP_P_LIMIT,
                n_pre_up   = STEP_N_PRE_UP,
                n_pre_down = STEP_N_PRE_DOWN,
                stop_event = self._stop,
                readback   = STEP_READBACK,
            )
            log.info("Escalón completado.")

        elif OPERATION_MODE == "none":
            log.info("Modo 'none': solo monitoreo, sin modificar voltaje.")
        else:
            log.warning(f"OPERATION_MODE='{OPERATION_MODE}' no reconocido. Usa 'ramp', 'step' o 'none'.")

    # ── Arranque del sistema completo ─────────────
    def start(self):
        if not self.ps.open():
            log.error("Conexión SCPI fallida. Verifica el puerto COM y el baud rate.")
            return

        identity = ModbusDeviceIdentification()
        identity.VendorName         = "EA Elektro-Automatik"
        identity.ProductCode        = "PS10060-170"
        identity.ProductName        = "SCPI-Modbus Bridge"
        identity.MajorMinorRevision = "3.0"

        # Hilo de polling SCPI → Modbus
        threading.Thread(target=self._poll_loop,    daemon=True, name="Poll").start()
        # Hilo de forma de onda
        threading.Thread(target=self._waveform_loop, daemon=True, name="Waveform").start()

        log.info(f"Servidor Modbus TCP en {MODBUS_HOST}:{MODBUS_PORT}  (Unit={MODBUS_UNIT})")
        log.info(f"Modo de operación: {OPERATION_MODE.upper()}")
        log.info("Presiona Ctrl+C para detener.")

        try:
            StartTcpServer(
                context=self.ctx,
                identity=identity,
                address=(MODBUS_HOST, MODBUS_PORT),
            )
        except KeyboardInterrupt:
            log.info("Detenido por usuario.")
        finally:
            self._stop.set()
            self.ps.output(False)
            self.ps.set_voltage(0.0)
            self.ps.close()
            log.info("Bridge cerrado. Salida apagada, voltaje → 0V.")

# ═════════════════════════════════════════════════
#  MAIN
# ═════════════════════════════════════════════════

if __name__ == "__main__":
    log.info("=" * 60)
    log.info("  SCPI → Modbus TCP  |  EA PS 10060-170  |  v3.0")
    log.info(f"  Puerto: {SERIAL_PORT}  Baud: {SERIAL_BAUD}")
    log.info(f"  Modbus: {MODBUS_HOST}:{MODBUS_PORT}  Unit={MODBUS_UNIT}")
    log.info(f"  Modo:   {OPERATION_MODE.upper()}")
    if OPERATION_MODE == "ramp":
        log.info(f"  Rampa:  {RAMP_V_MIN}V → {RAMP_V_MAX}V  paso={RAMP_V_STEP}V  dt={RAMP_DT_MS}ms")
    elif OPERATION_MODE == "step":
        log.info(f"  Escalón: {STEP_V_LOW}V ↔ {STEP_V_HIGH}V  dt={STEP_DT_MS}ms")
    log.info("=" * 60)
    ScpiModbusBridge().start()