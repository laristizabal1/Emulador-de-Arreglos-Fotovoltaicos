"""
comm/scpi.py
============
Controlador de la fuente EA-PS 10060-170 mediante SCPI ASCII por USB/COM.

Uso:
    from comm.scpi import SCPIController, list_ports

    puertos = list_ports()
    ctrl    = SCPIController(port="COM3")
    idn     = ctrl.connect()
    ctrl.set_output_fast(40.0, 10.0)
    ctrl.run_profile(profile, dt_ms=200)
    ctrl.disconnect()

CORRECCIONES APLICADAS:
    1. SYST:REM:TRAN ON -> SYST:LOCK ON (comando correcto para EA-PS 10060-170)
    2. threading.Lock() -> threading.RLock() para evitar deadlock entre threads
    3. SYST:LOCK ON enviado en connect() para activar remoto desde el inicio
    4. SYST:LOCK OFF enviado en disconnect() para liberar correctamente
    5. SYST:LOCK ON eliminado del loop run_profile() (ya activo desde connect)
"""

import time
import threading

from config.hardware import V_MAX, I_MAX, DT_MIN

try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False


def list_ports() -> list[dict]:
    """Enumera puertos COM disponibles. Retorna lista para dcc.Dropdown."""
    if not SERIAL_AVAILABLE:
        return [{"label": "pyserial no disponible — pip install pyserial",
                 "value": "NONE"}]
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        return [{"label": "Sin puertos COM detectados", "value": "NONE"}]
    return [
        {"label": f"{p.device}  —  {p.description[:40]}", "value": p.device}
        for p in sorted(ports, key=lambda p: p.device)
    ]


class SCPIController:
    """
    Controlador de la fuente EA-PS 10060-170 por USB/COM usando SCPI ASCII.
    Thread-safe mediante RLock interno (reentrant — evita deadlock).
    """

    def __init__(self, port: str = "COM3", baud: int = 115200,
                 timeout: float = 2.0):
        self.port    = port
        self.baud    = baud
        self.timeout = timeout
        self._ser      = None
        self._running  = False
        # FIX #2: RLock (reentrant) en lugar de Lock para evitar deadlock
        # cuando output_off() y set_output_fast() se llaman desde el mismo thread
        self._lock     = threading.RLock()

    # ── Conexión ──────────────────────────────────────────────────────────────

    def connect(self) -> str:
        if not SERIAL_AVAILABLE:
            raise RuntimeError("pyserial no instalado: pip install pyserial")
        self._ser = serial.Serial(self.port, self.baud, timeout=self.timeout)
        time.sleep(0.3)
        idn = self.query("*IDN?").strip()
        time.sleep(0.1)
        # FIX #1 y #4: SYST:LOCK ON es el comando correcto para activar
        # control remoto digital en la EA-PS 10060-170 (no SYST:REM:TRAN ON).
        # Al enviarlo aquí, queda activo para toda la sesión.
        # El display de la fuente debe mostrar "Remote: USB" al recibirlo.
        self.send("SYST:LOCK ON")
        return idn

    def disconnect(self):
        if self.connected:
            # FIX: liberar control remoto antes de cerrar para que la fuente
            # vuelva a modo local y los knobs físicos recuperen el control
            self.send("OUTP OFF")
            self.send("SYST:LOCK OFF")
            self._ser.close()

    @property
    def connected(self) -> bool:
        return bool(self._ser and self._ser.is_open)

    # ── Comunicación ──────────────────────────────────────────────────────────

    def send(self, cmd: str):
        with self._lock:
            if not self.connected:
                raise RuntimeError(
                    f"Puerto {self.port} no está abierto. "
                    "Conecta primero con el botón '*IDN?'."
                )
            self._ser.write((cmd + "\n").encode("ascii"))
            time.sleep(0.05)

    def query(self, cmd: str) -> str:
        with self._lock:
            if self.connected:
                self._ser.write((cmd + "\n").encode("ascii"))
                time.sleep(0.05)
                return self._ser.readline().decode("ascii", errors="replace")
        return ""

    def query_fast(self, cmd: str, timeout: float = 0.15) -> str:
        """
        Query con timeout corto — exclusivo para lecturas MEAS del monitor.

        El query() normal usa self.timeout = 2.0 s. Si la fuente no responde
        (p.ej. MEAS:ALL? no soportado), readline() bloquea 2 s completos,
        paralizando el thread del monitor y, si se llama desde un callback
        de Dash, bloqueando el worker de Flask.

        query_fast() reduce el timeout a 150 ms dentro del RLock:
          - Respuesta normal (~50 ms)  → readline retorna inmediatamente.
          - Sin respuesta              → readline retorna "" en 150 ms.
        El timeout original se restaura siempre (bloque finally).
        """
        with self._lock:
            if not self.connected:
                return ""
            old_timeout      = self._ser.timeout
            self._ser.timeout = timeout
            try:
                self._ser.write((cmd + "\n").encode("ascii"))
                time.sleep(0.05)
                return self._ser.readline().decode("ascii", errors="replace")
            finally:
                self._ser.timeout = old_timeout

    # ── Control de salida ─────────────────────────────────────────────────────

    def set_output_fast(self, V: float, I: float, on: bool = True):
        """
        Versión optimizada de set_output para perfiles en tiempo real.
        Envía VOLT y CURR con delay mínimo (2ms) en lugar de 50ms.
        Requiere que SYST:LOCK ON haya sido enviado previamente (lo hace connect()).
        """
        V_safe = min(max(float(V), 0.0), V_MAX)
        I_safe = min(max(float(I), 0.0), I_MAX)

        with self._lock:
            if self.connected:
                self._ser.write(f"VOLT {V_safe:.3f}\n".encode("ascii"))
                time.sleep(0.002)
                self._ser.write(f"CURR {I_safe:.3f}\n".encode("ascii"))
                time.sleep(0.002)
                if on:
                    self._ser.write(b"OUTP ON\n")
                    time.sleep(0.002)

    def output_off(self):
        self.send("OUTP OFF")

    def set_protections(self, ovp: float = None, ocp: float = None,
                        opp: float = None):
        if ovp is not None:
            self.send(f"VOLT:PROT {min(ovp, V_MAX * 1.1):.2f}")
        if ocp is not None:
            self.send(f"CURR:PROT {min(ocp, I_MAX * 1.1):.2f}")
        if opp is not None:
            self.send(f"POW:PROT {opp:.1f}")

    # ── Ejecución de perfil ───────────────────────────────────────────────────

    def run_profile(self,
                    profile:     list[dict],
                    dt_ms:       int,
                    progress_cb: callable = None):
        """
        Ejecuta el perfil compensando el tiempo real de cada comando SCPI.

        En lugar de:
            enviar_comandos()  →  sleep(dt_s)      ← dt REAL = overhead + dt_s

        Hace:
            t0 = perf_counter()
            enviar_comandos()
            elapsed = perf_counter() - t0
            time.sleep(max(0, dt_s - elapsed))     ← dt REAL ≈ dt_s exacto

        NOTA: SYST:LOCK ON ya fue enviado en connect() — no se repite aquí.
        """
        if not profile:
            return

        self._running = True
        dt_s  = max(int(dt_ms), DT_MIN) / 1000.0
        total = len(profile)

        # FIX #1: eliminado "SYST:REM:TRAN ON" que no existe en este equipo.
        # El control remoto ya está activo desde connect() con "SYST:LOCK ON".
        # Solo activar salida con el primer punto del perfil.
        self.set_output_fast(profile[0]["V_set"], profile[0]["I_set"], on=True)

        for i, step in enumerate(profile):
            if not self._running:
                break

            t0 = time.perf_counter()              # medir inicio del paso

            on = step["P_set"] > 0
            self.set_output_fast(step["V_set"], step["I_set"], on=on)

            if progress_cb:
                try:
                    progress_cb(i, total, step)
                except Exception:
                    pass

            # Compensar el tiempo que tomaron los comandos SCPI
            elapsed = time.perf_counter() - t0
            wait    = dt_s - elapsed
            if wait > 0:
                time.sleep(wait)
            # Si elapsed > dt_s la fuente es más lenta que dt_ms
            # → continuar sin sleep (avanzar lo más rápido posible)

        self.output_off()
        self._running = False

    def stop(self):
        self._running = False
        self.output_off()