"""
comm/scpi.py
============
Controlador de la fuente EA-PS 10060-170 mediante SCPI ASCII por USB/COM.
Migrado de la clase SCPIController y list_serial_ports() en app.py.

Protocolo: SCPI (Standard Commands for Programmable Instruments)
           Texto ASCII, puerto serie USB/COM, baud 115200
           Puerto 5025 TCP/IP (pendiente — ver comm/ethernet.py)

Referencia: Manual EA-PS 10000 3U (06230820_EN)
            Programming ModBus & SCPI Rev. 24

Uso básico:
    from comm.scpi import SCPIController, list_ports

    puertos = list_ports()       # → [{"label": "COM3 — ...", "value": "COM3"}, ...]

    ctrl = SCPIController(port="COM3")
    idn  = ctrl.connect()        # *IDN? — verifica comunicación
    ctrl.set_output(40.0, 10.0)  # VOLT 40.000, CURR 10.000, OUTP ON
    ctrl.run_profile(profile, dt_ms=200)
    ctrl.disconnect()
"""

import time
import threading
from config.hardware import V_MAX, I_MAX, DT_MIN, DEFAULT_PORT, DEFAULT_BAUD, DEFAULT_TIMEOUT

# pyserial es opcional — la HMI funciona en modo demo sin él
try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False


# ── Utilidades ────────────────────────────────────────────────────────────────

def list_ports() -> list[dict]:
    """
    Enumera los puertos COM disponibles en el sistema.
    Retorna lista de dicts con "label" y "value" para el dcc.Dropdown de Dash.
    """
    if not SERIAL_AVAILABLE:
        return [{"label": "pyserial no disponible — pip install pyserial",
                 "value": "NONE"}]

    ports = list(serial.tools.list_ports.comports())
    if not ports:
        return [{"label": "Sin puertos COM detectados", "value": "NONE"}]

    return [
        {
            "label": f"{p.device}  —  {p.description[:40]}",
            "value": p.device,
        }
        for p in sorted(ports, key=lambda p: p.device)
    ]


# ── Clase principal ───────────────────────────────────────────────────────────

class SCPIController:
    """
    Controlador de la fuente EA-PS 10060-170 por puerto serie USB/COM.

    Thread-safety: send() y query() usan un Lock interno, lo que permite
    llamarlos desde el thread de ejecución de perfiles y desde los
    callbacks de Dash simultáneamente sin corrupción de mensajes.

    Atributos públicos
    ------------------
    port      : nombre del puerto COM (ej. "COM3", "/dev/ttyUSB0")
    connected : True si el puerto está abierto y respondió a *IDN?
    """

    def __init__(self,
                 port:    str   = DEFAULT_PORT,
                 baud:    int   = DEFAULT_BAUD,
                 timeout: float = DEFAULT_TIMEOUT):
        self.port    = port
        self.baud    = baud
        self.timeout = timeout

        self._ser:     object         = None   # serial.Serial | None
        self._running: bool           = False
        self._lock:    threading.Lock = threading.Lock()

    # ── Conexión ──────────────────────────────────────────────────────────────

    def connect(self) -> str:
        """
        Abre el puerto serie y envía *IDN? para verificar que la fuente
        responde en modo SCPI ASCII.

        Retorna la respuesta de *IDN? (fabricante, modelo, firmware).
        Lanza RuntimeError si pyserial no está instalado.
        Lanza serial.SerialException si el puerto no existe o está ocupado.
        """
        if not SERIAL_AVAILABLE:
            raise RuntimeError(
                "pyserial no está instalado.\n"
                "Ejecutar: pip install pyserial"
            )
        self._ser = serial.Serial(
            self.port, self.baud, timeout=self.timeout
        )
        time.sleep(0.3)   # esperar que el puerto estabilice
        return self.query("*IDN?").strip()

    def disconnect(self):
        """Apaga la salida DC y cierra el puerto serie."""
        if self.connected:
            self.send("OUTP OFF")
            self._ser.close()

    @property
    def connected(self) -> bool:
        """True si el puerto está abierto."""
        return bool(self._ser and self._ser.is_open)

    # ── Comunicación primitiva ────────────────────────────────────────────────

    def send(self, cmd: str):
        """
        Envía un comando SCPI ASCII seguido de \\n.
        Thread-safe mediante Lock interno.
        Sin efecto si el puerto no está abierto.
        """
        with self._lock:
            if self.connected:
                self._ser.write((cmd + "\n").encode("ascii"))
                time.sleep(0.05)   # pausa mínima entre comandos

    def query(self, cmd: str) -> str:
        """
        Envía un comando SCPI y lee la respuesta en la misma operación atómica.
        Thread-safe. Devuelve "" si el puerto no está abierto.
        """
        with self._lock:
            if self.connected:
                self._ser.write((cmd + "\n").encode("ascii"))
                time.sleep(0.05)
                return self._ser.readline().decode("ascii", errors="replace")
        return ""

    # ── Control de salida ─────────────────────────────────────────────────────

    def set_output(self, V: float, I: float, on: bool = True):
        """
        Fija voltaje y corriente de salida con clipping automático
        a los límites del hardware (V_MAX = 60 V, I_MAX = 170 A).

        Comandos enviados: VOLT {V:.3f} → CURR {I:.3f} → OUTP ON (si on=True)
        """
        V_safe = min(max(float(V), 0.0), V_MAX)
        I_safe = min(max(float(I), 0.0), I_MAX)
        self.send(f"VOLT {V_safe:.3f}")
        self.send(f"CURR {I_safe:.3f}")
        if on:
            self.send("OUTP ON")

    def output_off(self):
        """Apaga la salida DC. Equivale a OUTP OFF."""
        self.send("OUTP OFF")

    def set_protections(self, ovp: float = None, ocp: float = None,
                        opp: float = None):
        """
        Configura las protecciones ajustables de la fuente.
        Solo envía el comando si el valor se especifica.

        Rangos válidos (0–110 % del nominal):
            OVP — sobretensión  [V]
            OCP — sobrecorriente [A]
            OPP — sobrepotencia  [W]
        """
        if ovp is not None:
            self.send(f"VOLT:PROT {min(ovp, V_MAX * 1.1):.2f}")
        if ocp is not None:
            self.send(f"CURR:PROT {min(ocp, I_MAX * 1.1):.2f}")
        if opp is not None:
            self.send(f"POW:PROT {opp:.1f}")

    # ── Ejecución de perfil completo ──────────────────────────────────────────

    def run_profile(self,
                    profile:     list[dict],
                    dt_ms:       int,
                    progress_cb: callable = None):
        """
        Ejecuta el perfil completo paso a paso en la fuente.
        Diseñado para correr en un thread daemon desde toggle_exec() en scpi_cb.py.

        Flujo:
            SYST:REM:TRAN ON
            VOLT/CURR del primer paso → OUTP ON
            loop: VOLT/CURR por paso → espera dt_s
            OUTP OFF al finalizar o al llamar stop()

        Parámetros
        ----------
        profile     : lista de dicts con V_set, I_set, P_set
        dt_ms       : milisegundos por paso (mínimo DT_MIN = 200 ms)
        progress_cb : función opcional(i, total, step) para actualizar la UI
        """
        if not profile:
            return

        self._running = True
        dt_s  = max(int(dt_ms), DT_MIN) / 1000.0
        total = len(profile)

        # Habilitar control remoto y fijar primer paso
        self.send("SYST:REM:TRAN ON")
        self.set_output(
            profile[0]["V_set"],
            profile[0]["I_set"],
            on=True,
        )

        for i, step in enumerate(profile):
            if not self._running:
                break

            on = step["P_set"] > 0  # apagar salida en pasos nocturnos
            self.set_output(step["V_set"], step["I_set"], on=on)

            if progress_cb:
                try:
                    progress_cb(i, total, step)
                except Exception:
                    pass   # no dejar que un error de UI rompa la ejecución

            time.sleep(dt_s)

        self.output_off()
        self._running = False

    def stop(self):
        """
        Interrumpe run_profile() en el siguiente paso y apaga la salida DC.
        Thread-safe: puede llamarse desde cualquier callback de Dash.
        """
        self._running = False
        self.output_off()
