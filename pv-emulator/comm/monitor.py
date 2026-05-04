"""
comm/monitor.py
================
Monitor de mediciones reales en tiempo real desde la fuente EA-PS.

POR QUÉ thread de fondo y NO lectura desde el callback de Dash
---------------------------------------------------------------
Llamar query() desde un callback de Dash bloquea el worker de Flask:
  - query() normal tiene timeout=2.0 s → si la fuente no responde,
    el callback queda bloqueado 2 s, Dash lo marca como fallido y
    ningún output se actualiza (live-readout y live-measured vacíos).

Solución: thread daemon dedicado que usa query_fast() (timeout=150 ms).
El callback solo lee _latest desde memoria — nunca toca el puerto serie.

Sincronización aproximada
--------------------------
  POLL_MS = 300 ms  ==  interval-exec de Dash
  → monitor actualiza _latest cada ~300 ms
  → callback lee _latest cada ~300 ms
  → desfase máximo: un ciclo (~300 ms), imperceptible en la HMI

Persistencia
------------
  start() → limpia buffer, registra t_inicio
  stop()  → guarda data/persistencia_mediciones/sesion_YYYYMMDD_HHMMSS.json

  {
    "sesion": {"inicio": "...", "fin": "...", "n_muestras": N, "intervalo_ms": 300},
    "mediciones": [{"timestamp": …, "V_dc": …, "I_dc": …, "P_dc": …}, …]
  }
"""

import json
import time
import threading
import collections
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from comm.scpi import SCPIController

# Intervalo del thread de polling — debe coincidir con interval-exec de Dash
POLL_MS = 300

_SAVE_DIR = (
    Path(__file__).resolve().parent.parent / "data" / "persistencia_mediciones"
)


class EAMonitor:
    """
    Lee V, I, P reales en un thread daemon usando query_fast() (150 ms timeout).
    El callback de Dash solo lee _latest desde memoria — sin bloqueos.
    """

    def __init__(self, controller: "SCPIController"):
        self._ctrl     = controller
        self._running  = False
        self._thread: threading.Thread | None = None
        self._t_inicio = ""
        self._meta: dict = {}   # metadata del perfil activo

        # Buffer circular: ~30 min a 300 ms
        self._buf: collections.deque[dict] = collections.deque(maxlen=6000)
        self._latest: dict = {}
        self._rlock = threading.Lock()   # protege _buf y _latest

    # ── Ciclo de vida ─────────────────────────────────────────────────────────

    def start(self, meta: dict | None = None):
        """Lanza el thread de polling. Idempotente.

        meta: dict con metadata del perfil (ciudad, modelo, estrategia, etc.)
              Viene de store-profile-meta y se embebe en el JSON final.
        """
        if self._running:
            return
        self._running  = True
        self._t_inicio = datetime.now().isoformat(timespec="seconds")
        self._meta     = meta or {}
        with self._rlock:
            self._buf.clear()
            self._latest = {}
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="EAMonitor"
        )
        self._thread.start()
        print(f"[EAMonitor] Iniciado — poll {POLL_MS} ms, timeout query 150 ms")

    def stop(self):
        """Detiene el thread y guarda JSON."""
        if not self._running:
            return
        self._running = False
        self._save_json()
        print("[EAMonitor] Detenido")

    @property
    def active(self) -> bool:
        return self._running

    # ── Acceso a datos (desde el callback — sin bloqueo) ─────────────────────

    def get_latest(self) -> dict:
        """
        Última lectura disponible. Claves: timestamp, V_dc, I_dc, P_dc.
        Retorna {} si aún no hay lecturas.
        """
        with self._rlock:
            return dict(self._latest)

    def get_buffer(self) -> list[dict]:
        """Historial completo del buffer."""
        with self._rlock:
            return list(self._buf)

    # ── Loop del thread ───────────────────────────────────────────────────────

    def _loop(self):
        while self._running:
            t0 = time.perf_counter()

            if self._ctrl.connected:
                try:
                    reading = self._read_once()

                    # Adjuntar consigna teórica del paso actual
                    # _get_current_step() importa _exec_progress del módulo scpi_cb
                    # sin crear dependencia circular — usa importación diferida.
                    step = self._get_step()
                    if step:
                        reading["V_set"]         = step.get("V_set", None)
                        reading["I_set"]         = step.get("I_set", None)
                        reading["P_set"]         = step.get("P_set", None)
                        reading["hora_emulada"]  = step.get("label", "")
                        reading["Tcell"]         = step.get("Tcell", None)
                        reading["Gpoa"]          = step.get("Gpoa",  None)

                    with self._rlock:
                        self._latest = reading
                        self._buf.append(reading)
                except Exception as exc:
                    print(f"[EAMonitor] Error lectura: {exc}")

            elapsed = time.perf_counter() - t0
            wait = POLL_MS / 1000.0 - elapsed
            if wait > 0:
                time.sleep(wait)

    def _get_step(self) -> dict:
        """
        Lee el paso actual desde _exec_progress en scpi_cb.
        Importación diferida para evitar dependencia circular en el import.
        Retorna {} si no está disponible.
        """
        try:
            import hmi.callbacks.scpi_cb as _scpi
            return dict(_scpi._exec_progress.get("step") or {})
        except Exception:
            return {}

    def _read_once(self) -> dict:
        """
        Usa query_fast() (timeout 150 ms) para no bloquear el thread más
        allá de 150 ms si la fuente no responde.

        Estrategia igual al bridge.py:
          1. MEAS:ALL? → CSV "V, I, P" (una sola query)
          2. Fallback:  MEAS:VOLT? + MEAS:CURR?
        Parser: split()[0] descarta la unidad ("10.00 V" → 10.0).
        """
        # Intento 1 — query única
        try:
            raw   = self._ctrl.query_fast("MEAS:ALL?")
            parts = [p.strip() for p in raw.split(",")]
            if len(parts) >= 2:
                v = _parse_float(parts[0])
                i = _parse_float(parts[1])
                p = _parse_float(parts[2]) if len(parts) >= 3 else None
                if v is not None and i is not None:
                    return {
                        "timestamp": round(time.time(), 3),
                        "V_dc":      round(v, 4),
                        "I_dc":      round(i, 4),
                        "P_dc":      round(p if p is not None else v * i, 4),
                    }
        except Exception:
            pass

        # Fallback — dos queries separadas
        v = _parse_float(self._ctrl.query_fast("MEAS:VOLT?")) or 0.0
        i = _parse_float(self._ctrl.query_fast("MEAS:CURR?")) or 0.0
        return {
            "timestamp": round(time.time(), 3),
            "V_dc":      round(v, 4),
            "I_dc":      round(i, 4),
            "P_dc":      round(v * i, 4),
        }

    # ── Persistencia ──────────────────────────────────────────────────────────

    def _save_json(self):
        with self._rlock:
            mediciones = list(self._buf)

        if not mediciones:
            print("[EAMonitor] Buffer vacío — no se genera JSON.")
            return

        payload = {
            "sesion": {
                "inicio":       self._t_inicio,
                "fin":          datetime.now().isoformat(timespec="seconds"),
                "n_muestras":   len(mediciones),
                "intervalo_ms": POLL_MS,
            },
            "perfil": self._meta,   # ciudad, modelo, estrategia, módulo, Ns, Np…
            "mediciones": mediciones,
        }

        _SAVE_DIR.mkdir(parents=True, exist_ok=True)
        ts      = datetime.now().strftime("%Y%m%d_%H%M%S")
        archivo = _SAVE_DIR / f"sesion_{ts}.json"

        try:
            with open(archivo, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            print(f"[EAMonitor] JSON → {archivo.name} ({len(mediciones)} muestras)")
        except OSError as exc:
            print(f"[EAMonitor] Error al guardar JSON: {exc}")


# ── Helper ────────────────────────────────────────────────────────────────────

def _parse_float(raw: str) -> float | None:
    """'10.00 V' o '2.5' → float. None si falla."""
    try:
        return float(raw.strip().split()[0])
    except (ValueError, IndexError, AttributeError):
        return None