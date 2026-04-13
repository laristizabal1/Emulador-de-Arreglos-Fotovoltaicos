"""
comm/ethernet.py
================
Control de la fuente EA-PS 10060-170 mediante TCP/IP (Ethernet/LAN).
Protocolo: SCPI ASCII sobre socket TCP, puerto 5025.

Estado actual: TRABAJO FUTURO — Fase 3 del proyecto.
La comunicación Ethernet no pudo establecerse durante la entrega actual
(ver Sección VII del documento Emulacion_de_Arreglo_Fotovoltaicos_1).
Pendiente contactar soporte técnico de EA para validar el procedimiento
de configuración de red.

Cuando esté resuelto, esta clase es un reemplazo directo de SCPIController
(misma interfaz pública) sin necesidad de modificar callbacks ni pipeline.

Configuración de red documentada:
    Fuente:     IP 192.168.1.20  Máscara 255.255.255.0  DHCP OFF
    Computador: IP 192.168.1.10  Máscara 255.255.255.0  Wi-Fi deshabilitado
    Puerto SCPI: 5025
"""

import socket
import time
import threading
from config.hardware import V_MAX, I_MAX, DT_MIN, DEFAULT_TIMEOUT

_DEFAULT_HOST = "192.168.1.20"
_DEFAULT_PORT = 5025


class EthernetSCPIController:
    """
    Controlador idéntico a SCPIController pero usando TCP/IP en lugar de
    puerto serie USB/COM.

    La misma interfaz pública (connect, send, query, set_output,
    run_profile, stop) permite sustituirlo en scpi_cb.py sin
    modificar ningún callback.

    Uso (cuando Ethernet esté operativo):
        from comm.ethernet import EthernetSCPIController

        ctrl = EthernetSCPIController(host="192.168.1.20", port=5025)
        idn  = ctrl.connect()
        ctrl.set_output(40.0, 10.0)
        ctrl.run_profile(profile, dt_ms=200)
        ctrl.disconnect()
    """

    def __init__(self,
                 host:    str   = _DEFAULT_HOST,
                 port:    int   = _DEFAULT_PORT,
                 timeout: float = DEFAULT_TIMEOUT):
        self.host    = host
        self.port    = port
        self.timeout = timeout

        self._sock:    socket.socket  = None
        self._running: bool           = False
        self._lock:    threading.Lock = threading.Lock()

    # ── Conexión ──────────────────────────────────────────────────────────────

    def connect(self) -> str:
        """
        Abre el socket TCP y envía *IDN? para verificar comunicación.
        Lanza ConnectionRefusedError si la fuente no está en la red.
        """
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(self.timeout)
        self._sock.connect((self.host, self.port))
        time.sleep(0.2)
        return self.query("*IDN?").strip()

    def disconnect(self):
        """Apaga la salida DC y cierra el socket."""
        if self.connected:
            self.send("OUTP OFF")
            self._sock.close()

    @property
    def connected(self) -> bool:
        return bool(self._sock and self._sock.fileno() != -1)

    # ── Comunicación ──────────────────────────────────────────────────────────

    def send(self, cmd: str):
        """Envía un comando SCPI ASCII por TCP. Thread-safe."""
        with self._lock:
            if self.connected:
                self._sock.sendall((cmd + "\n").encode("ascii"))
                time.sleep(0.05)

    def query(self, cmd: str) -> str:
        """Envía un comando y lee la respuesta. Thread-safe."""
        with self._lock:
            if self.connected:
                self._sock.sendall((cmd + "\n").encode("ascii"))
                time.sleep(0.05)
                try:
                    return self._sock.recv(4096).decode("ascii", errors="replace")
                except socket.timeout:
                    return ""
        return ""

    # ── Control de salida (idéntico a SCPIController) ─────────────────────────

    def set_output(self, V: float, I: float, on: bool = True):
        V_safe = min(max(float(V), 0.0), V_MAX)
        I_safe = min(max(float(I), 0.0), I_MAX)
        self.send(f"VOLT {V_safe:.3f}")
        self.send(f"CURR {I_safe:.3f}")
        if on:
            self.send("OUTP ON")

    def output_off(self):
        self.send("OUTP OFF")

    def run_profile(self, profile: list[dict], dt_ms: int,
                    progress_cb: callable = None):
        """Idéntico a SCPIController.run_profile() — ver comm/scpi.py."""
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
