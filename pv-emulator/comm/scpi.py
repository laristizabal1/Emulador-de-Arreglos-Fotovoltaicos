# comm/scpi.py
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
    """Lista los puertos COM disponibles — usada por el dropdown de la HMI."""
    if not SERIAL_AVAILABLE:
        return [{"label": "pyserial no disponible", "value": "NONE"}]
    ports = serial.tools.list_ports.comports()
    if not ports:
        return [{"label": "Sin puertos COM detectados", "value": "NONE"}]
    return [{"label": f"{p.device} — {p.description[:30]}", "value": p.device}
            for p in ports]


class SCPIController:
    """
    Controlador de la fuente EA-PS 10060-170 por USB/COM usando SCPI ASCII.
    Migrado de app.py — ahora vive en comm/scpi.py.

    Uso:
        ctrl = SCPIController(port="COM3")
        idn  = ctrl.connect()         # verifica comunicación con *IDN?
        ctrl.set_output(40.0, 10.0)   # VOLT 40.000, CURR 10.000, OUTP ON
        ctrl.run_profile(profile, dt_ms=200)
        ctrl.disconnect()
    """

    def __init__(self, port: str, baud: int = 115200, timeout: float = 2.0):
        self.port     = port
        self.baud     = baud
        self.timeout  = timeout
        self.ser      = None
        self._running = False
        self._lock    = threading.Lock()

    # ── Conexión ─────────────────────────────────────────────────────────────
    def connect(self) -> str:
        if not SERIAL_AVAILABLE:
            raise RuntimeError("pyserial no instalado: pip install pyserial")
        self.ser = serial.Serial(self.port, self.baud, timeout=self.timeout)
        time.sleep(0.3)
        return self.query("*IDN?").strip()

    def disconnect(self):
        if self.ser and self.ser.is_open:
            self.send("OUTP OFF")
            self.ser.close()

    @property
    def connected(self) -> bool:
        return bool(self.ser and self.ser.is_open)

    # ── Comunicación primitiva ────────────────────────────────────────────────
    def send(self, cmd: str):
        """Envía un comando SCPI ASCII. Thread-safe."""
        with self._lock:
            if self.connected:
                self.ser.write((cmd + "\n").encode())
                time.sleep(0.05)

    def query(self, cmd: str) -> str:
        """Envía un comando y lee la respuesta. Thread-safe."""
        with self._lock:
            if self.connected:
                self.ser.write((cmd + "\n").encode())
                time.sleep(0.05)
                return self.ser.readline().decode(errors="replace")
        return ""

    # ── Control de salida ─────────────────────────────────────────────────────
    def set_output(self, V: float, I: float, on: bool = True):
        """
        Envía consigna de voltaje y corriente.
        Aplica clipping automático a los límites del hardware.
        """
        V_safe = min(max(V, 0.0), V_MAX)
        I_safe = min(max(I, 0.0), I_MAX)
        self.send(f"VOLT {V_safe:.3f}")
        self.send(f"CURR {I_safe:.3f}")
        if on:
            self.send("OUTP ON")

    def output_off(self):
        self.send("OUTP OFF")

    # ── Ejecución de perfil completo ──────────────────────────────────────────
    def run_profile(self, profile: list[dict], dt_ms: int,
                    progress_cb=None):
        """
        Ejecuta el perfil completo en la fuente paso a paso.

        progress_cb(i: int, total: int, step: dict) se llama en cada paso.
        Úsalo para actualizar la barra de progreso de Dash vía un store.
        """
        if not profile:
            return
        self._running = True
        dt_s  = max(dt_ms, DT_MIN) / 1000.0
        total = len(profile)

        self.send("SYST:REM:TRAN ON")
        self.set_output(profile[0]["V_set"], profile[0]["I_set"], on=True)

        for i, step in enumerate(profile):
            if not self._running:
                break
            self.set_output(step["V_set"], step["I_set"],
                            on=(step["P_set"] > 0))
            if progress_cb:
                progress_cb(i, total, step)
            time.sleep(dt_s)

        self.output_off()
        self._running = False

    def stop(self):
        """Detiene la ejecución en curso e inhabilita la salida DC."""
        self._running = False
        self.output_off()