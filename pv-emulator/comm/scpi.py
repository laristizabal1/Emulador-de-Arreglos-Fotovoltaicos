"""
comm/scpi.py
============
Controlador de la fuente EA-PS 10060-170 mediante SCPI ASCII por USB/COM.

Uso:
    from comm.scpi import SCPIController, list_ports

    puertos = list_ports()
    ctrl    = SCPIController(port="COM3")
    idn     = ctrl.connect()
    ctrl.set_output(40.0, 10.0)
    ctrl.run_profile(profile, dt_ms=200)
    ctrl.disconnect()
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
    Thread-safe mediante Lock interno.
    """

    def __init__(self, port: str = "COM3", baud: int = 115200,
                 timeout: float = 2.0):
        self.port    = port
        self.baud    = baud
        self.timeout = timeout
        self._ser      = None
        self._running  = False
        self._lock     = threading.Lock()

    # ── Conexión ──────────────────────────────────────────────────────────────

    def connect(self) -> str:
        if not SERIAL_AVAILABLE:
            raise RuntimeError("pyserial no instalado: pip install pyserial")
        self._ser = serial.Serial(self.port, self.baud, timeout=self.timeout)
        time.sleep(0.3)
        return self.query("*IDN?").strip()

    def disconnect(self):
        if self.connected:
            self.send("OUTP OFF")
            self._ser.close()

    @property
    def connected(self) -> bool:
        return bool(self._ser and self._ser.is_open)

    # ── Comunicación ──────────────────────────────────────────────────────────

    def send(self, cmd: str):
        with self._lock:
            if self.connected:
                self._ser.write((cmd + "\n").encode("ascii"))
                time.sleep(0.05)

    def query(self, cmd: str) -> str:
        with self._lock:
            if self.connected:
                self._ser.write((cmd + "\n").encode("ascii"))
                time.sleep(0.05)
                return self._ser.readline().decode("ascii", errors="replace")
        return ""

    # ── Control de salida ─────────────────────────────────────────────────────

    def set_output(self, V: float, I: float, on: bool = True):
        V_safe = min(max(float(V), 0.0), V_MAX)
        I_safe = min(max(float(I), 0.0), I_MAX)
        self.send(f"VOLT {V_safe:.3f}")
        self.send(f"CURR {I_safe:.3f}")
        if on:
            self.send("OUTP ON")

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

    def run_profile(self, profile: list[dict], dt_ms: int,
                    progress_cb=None):
        if not profile:
            return
        self._running = True
        dt_s  = max(int(dt_ms), DT_MIN) / 1000.0
        total = len(profile)

        self.send("SYST:REM:TRAN ON")
        self.set_output(profile[0]["V_set"], profile[0]["I_set"], on=True)

        for i, step in enumerate(profile):
            if not self._running:
                break
            self.set_output(step["V_set"], step["I_set"],
                            on=(step["P_set"] > 0))
            if progress_cb:
                try:
                    progress_cb(i, total, step)
                except Exception:
                    pass
            time.sleep(dt_s)

        self.output_off()
        self._running = False

    def stop(self):
        self._running = False
        self.output_off()