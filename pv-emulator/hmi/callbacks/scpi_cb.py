"""
hmi/callbacks/scpi_cb.py
=========================
Callbacks del Tab 3 — Control SCPI + Bridge Modbus TCP.

Callbacks registrados (8):
    - connect_scpi          -> abre puerto COM y verifica *IDN? + activa SYST:LOCK ON
    - bridge_control        -> inicia / detiene ScpiModbusBridge en thread
    - update_bridge_status  -> polling del estado del bridge (interval-live)
    - manual_control        -> OUTP ON/OFF con V e I manuales
    - toggle_exec           -> arranca / detiene perfil PV en thread
    - update_exec_progress  -> progreso del perfil (interval-exec)
    - update_terminal       -> terminal SCPI con comandos enviados
    - update_exec_info      -> muestra n° de pasos y duración estimada

CORRECCIONES APLICADAS:
    - set_output() -> set_output_fast() en manual_control (método correcto)
    - Terminal SCPI muestra SYST:LOCK ON en lugar de SYST:REM:TRAN ON
    - Terminal ahora recibe inp-dt como State y muestra el wait real del usuario
      en lugar del DT_MIN hardcodeado (bug: siempre mostraba 200ms)
    - update_exec_progress recibe inp-dt como State para mostrar Δt correcto
"""

import threading
from dash import Input, Output, State, html, ctx, no_update

from config.hardware import C, DT_MIN
from comm.scpi       import SCPIController
from comm.monitor    import EAMonitor

# Bridge — importacion defensiva
try:
    from comm.bridge import ScpiModbusBridge, BridgeConfig
    BRIDGE_AVAILABLE = True
except ImportError:
    BRIDGE_AVAILABLE = False


# ── Estado global compartido entre callbacks ──────────────────────────────────
_controller:    SCPIController              = SCPIController(port="COM3")
_monitor:       EAMonitor                  = EAMonitor(_controller)   # comparte COM3
_exec_thread:   threading.Thread           = None
_bridge:        "ScpiModbusBridge | None"  = None
_bridge_thread: threading.Thread           = None

# Progreso real del perfil — actualizado por progress_cb en run_profile()
# El callback lee de aquí en lugar de estimar con n_intervals
_exec_progress: dict = {"idx": 0, "total": 0, "step": {}}


def register(app):

    # ─── 1. Conectar SCPI ────────────────────────────────────────────────────
    @app.callback(
        Output("connect-status", "children"),
        Input("btn-connect", "n_clicks"),
        State("dd-port",     "value"),
        prevent_initial_call=True,
    )
    def connect_scpi(_n, port):
        from comm.scpi import SERIAL_AVAILABLE
        if not SERIAL_AVAILABLE:
            return html.Div(
                "pyserial no instalado: pip install pyserial",
                style={"color": C["red"], "fontSize": 11},
            )
        if not port or port == "NONE":
            return html.Div("Selecciona un puerto COM primero.",
                            style={"color": C["red"], "fontSize": 11})
        try:
            _controller.port = port
            # connect() ya envía SYST:LOCK ON internamente — la fuente
            # mostrará "Remote: USB" en el display al conectar correctamente
            idn = _controller.connect()
            return html.Div(
                f"Conectado: {idn[:60]}  |  Remoto: SYST:LOCK ON ✓",
                style={"color": C["accentDark"], "fontWeight": 600,
                       "fontSize": 11},
            )
        except Exception as exc:
            return html.Div(f"Error: {exc}",
                            style={"color": C["red"], "fontSize": 11})

    # ─── 2. Iniciar / detener Bridge Modbus ──────────────────────────────────
    @app.callback(
        Output("bridge-status", "children"),
        Input("btn-bridge-start", "n_clicks"),
        Input("btn-bridge-stop",  "n_clicks"),
        State("dd-port",          "value"),
        State("inp-modbus-host",  "value"),
        State("inp-modbus-port",  "value"),
        State("inp-bridge-poll",  "value"),
        prevent_initial_call=True,
    )
    def bridge_control(_start, _stop, port, host, mb_port, poll):
        global _bridge, _bridge_thread

        triggered = ctx.triggered_id

        # DETENER
        if triggered == "btn-bridge-stop":
            if _bridge:
                _bridge.stop()
                _bridge = None
            return html.Div("Bridge detenido.",
                            style={"color": C["red"], "fontWeight": 600,
                                   "fontSize": 11})

        # INICIAR
        if not BRIDGE_AVAILABLE:
            return html.Div(
                "pymodbus no instalado: pip install 'pymodbus==3.7.4'",
                style={"color": C["red"], "fontSize": 11},
            )
        if not port or port == "NONE":
            return html.Div("Selecciona un puerto COM primero.",
                            style={"color": C["red"], "fontSize": 11})

        if _bridge and _bridge.running:
            return html.Div("Bridge ya en ejecucion.",
                            style={"color": C["dim"], "fontSize": 11})

        # Verificar que el SCPIController ya está conectado
        if not _controller.connected:
            return html.Div(
                "Conecta primero la fuente EA (botón Conectar/verificar).",
                style={"color": C["red"], "fontSize": 11},
            )

        try:
            cfg = BridgeConfig(
                serial_port      = port,
                modbus_host      = host  or "0.0.0.0",
                modbus_port      = int(mb_port or 502),
                poll_interval_ms = float(poll or 20),
            )
            _bridge = ScpiModbusBridge(cfg)

            # start_shared() reutiliza el serial abierto por SCPIController
            # evita PermissionError por doble apertura del mismo puerto COM
            _bridge_thread = threading.Thread(
                target=lambda: _bridge.start_shared(_controller._ser),
                daemon=True, name="ModbusBridge"
            )
            _bridge_thread.start()

            return html.Div(
                f"Bridge activo: {host or '0.0.0.0'}:{mb_port or 502} "
                f"(poll {int(poll or 20)} ms)",
                style={"color": C["accentDark"], "fontWeight": 600,
                       "fontSize": 11},
            )
        except Exception as exc:
            return html.Div(f"Error al iniciar bridge: {exc}",
                            style={"color": C["red"], "fontSize": 11})

    # ─── 3. Estado del bridge en la HMI (polling con interval-live) ──────────
    @app.callback(
        Output("bridge-modbus-readout", "children"),
        Input("interval-live", "n_intervals"),
    )
    def update_bridge_status(_n):
        if not _bridge or not _bridge.running:
            return html.Div("Bridge inactivo.",
                            style={"color": C["dim"], "fontSize": 11,
                                   "gridColumn": "1 / -1"})

        r = _bridge.get_readings()
        items = [
            ("V meas",  f"{r['V']:.3f} V",   C["red"]),
            ("I meas",  f"{r['I']:.4f} A",   C["blue"]),
            ("P meas",  f"{r['P']:.2f} W",   C["accent"]),
            ("V set",   f"{r['Vset']:.3f} V", C["dim"]),
            ("I set",   f"{r['Iset']:.4f} A", C["dim"]),
            ("OUT",     "ON" if r["output"] else "OFF",
             C["accentDark"] if r["output"] else C["red"]),
        ]
        return [
            html.Div([
                html.Div(val, style={"fontSize": 15, "fontWeight": 900,
                                     "color": color, "fontFamily": "monospace"}),
                html.Div(lbl, style={"fontSize": 9, "color": C["dim"]}),
            ], style={"textAlign": "center", "padding": "6px 4px",
                      "background": C["accentBg"], "borderRadius": 8})
            for lbl, val, color in items
        ]

    # ─── 4. Control manual ────────────────────────────────────────────────────
    @app.callback(
        Output("manual-status",  "children"),
        Output("store-scpi-log", "data"),
        Input("btn-outp-on",     "n_clicks"),
        Input("btn-outp-off",    "n_clicks"),
        State("inp-manual-v",    "value"),
        State("inp-manual-i",    "value"),
        State("store-scpi-log",  "data"),
        prevent_initial_call=True,
    )
    def manual_control(_n_on, _n_off, V, I, log):
        triggered = ctx.triggered_id
        log = log or []
        try:
            if triggered == "btn-outp-on":
                V = float(V or 0.0)
                I = float(I or 0.0)
                # FIX: set_output() no existe — usar set_output_fast()
                _controller.set_output_fast(V, I, on=True)
                log.extend([f"VOLT {V:.3f}", f"CURR {I:.3f}", "OUTP ON"])
                status = html.Div(
                    f"Salida ON — {V} V / {I} A",
                    style={"color": C["accentDark"], "fontWeight": 600},
                )
            else:
                _controller.output_off()
                log.append("OUTP OFF")
                status = html.Div("Salida OFF",
                                  style={"color": C["red"], "fontWeight": 600})
        except Exception as exc:
            status = html.Div(f"Error: {exc}", style={"color": C["red"]})

        return status, log[-60:]

    # ─── 5. Ejecutar / detener perfil completo ────────────────────────────────
    @app.callback(
        Output("interval-exec",    "disabled"),
        Output("store-exec-state", "data"),
        Input("btn-exec-start",    "n_clicks"),
        Input("btn-exec-stop",     "n_clicks"),
        State("store-profile",     "data"),
        State("store-profile-meta","data"),
        State("inp-dt",            "value"),
        State("dd-port",           "value"),
        State("store-exec-state",  "data"),
        prevent_initial_call=True,
    )
    def toggle_exec(_n_start, _n_stop, profile, profile_meta, dt, port, state):
        global _exec_thread

        triggered = ctx.triggered_id

        if triggered == "btn-exec-stop":
            _controller.stop()
            return True, {"running": False, "step": 0}

        if triggered == "btn-exec-start":
            if not profile:
                return True, state

            _controller.port = port or "COM3"
            dt_ms = max(dt or 1000, DT_MIN)

            def _progress_cb(i, total, step):
                """Actualiza el paso real — leído por update_exec_progress."""
                _exec_progress["idx"]   = i
                _exec_progress["total"] = total
                _exec_progress["step"]  = step

            def _run():
                global _exec_progress
                _exec_progress = {"idx": 0, "total": len(profile), "step": profile[0] if profile else {}}
                try:
                    if not _controller.connected:
                        _controller.connect()
                    _monitor.start(meta=profile_meta or {})
                    _controller.run_profile(profile, dt_ms,
                                            progress_cb=_progress_cb)
                except Exception as exc:
                    _controller._last_error = str(exc)
                    print(f"[SCPI ERROR] {exc}")
                finally:
                    _monitor.stop()

            _exec_thread = threading.Thread(target=_run, daemon=True,
                                             name="ProfileExec")
            _exec_thread.start()
            return False, {"running": True, "step": 0}

        return True, state

    # ─── 6. Progreso del perfil + mediciones reales ──────────────────────────
    @app.callback(
        Output("progress-bar",    "style"),
        Output("exec-step-info",  "children"),
        Output("live-readout",    "children"),   # consignas
        Output("live-measured",   "children"),   # mediciones MEAS reales
        Input("interval-exec",    "n_intervals"),
        State("store-profile",    "data"),
        State("store-exec-state", "data"),
        State("inp-dt",           "value"),
    )
    def update_exec_progress(n_intervals, profile, state, dt):
        bar_base = {
            "height":       "100%",
            "background":   C["accent"],
            "borderRadius": 4,
            "transition":   "width 0.3s",
        }

        # ── Error en el thread ────────────────────────────────────────────────
        last_err = getattr(_controller, "_last_error", None)
        if last_err:
            _controller._last_error = None
            bar_rojo = {**bar_base, "width": "100%", "background": C["red"]}
            msg = html.Div(
                f"❌  Error en perfil: {last_err}",
                style={"color": C["red"], "fontWeight": 600, "fontSize": 12},
            )
            return bar_rojo, msg, [], []

        # ── Sin perfil o detenido ─────────────────────────────────────────────
        if not profile or not state.get("running"):
            return {**bar_base, "width": "0%"}, "Sin perfil en ejecución.", [], []

        # ── Progreso normal ───────────────────────────────────────────────────
        dt_ms = max(dt or 1000, DT_MIN)
        total = len(profile)

        # Leer el paso real reportado por el thread del perfil (progress_cb)
        # Antes usaba n_intervals % total → avanzaba al ritmo de 300 ms
        # sin importar el Δt configurado. Ahora refleja el paso exacto.
        idx  = min(_exec_progress.get("idx", 0), total - 1)
        step = _exec_progress.get("step") or profile[idx]
        pct  = round(idx / max(total - 1, 1) * 100, 1)

        info = f"Ejecutando — paso {idx + 1} de {total} · Δt {dt_ms} ms/paso"

        # ── Consignas (V_set, I_set, P_set) ──────────────────────────────────
        def _card(val, label, unit, color, bg):
            return html.Div([
                html.Div(f"{val}", style={
                    "fontSize": 22, "fontWeight": 900,
                    "color": color, "fontFamily": "monospace",
                }),
                html.Div(f"{label} ({unit})", style={
                    "fontSize": 9, "color": C["dim"], "fontWeight": 600,
                }),
            ], style={
                "padding": 12, "background": bg, "borderRadius": 10,
                "textAlign": "center", "border": f"1px solid {color}22",
            })

        readout = [
            _card(step.get("V_set", 0), "VOLT set", "V",  C["red"],    C["redLight"]),
            _card(step.get("I_set", 0), "CURR set", "A",  C["blue"],   C["blueLight"]),
            _card(step.get("P_set", 0), "POW  set", "W",  C["accent"], C["accentLight"]),
        ]

        # ── Mediciones reales del EAMonitor (lee caché, sin bloqueo) ─────────
        meas = _monitor.get_latest()
        if meas:
            measured = [
                _card(f"{meas['V_dc']:.3f}", "VOLT meas", "V",  C["red"],    C["redLight"]),
                _card(f"{meas['I_dc']:.4f}", "CURR meas", "A",  C["blue"],   C["blueLight"]),
                _card(f"{meas['P_dc']:.2f}", "POW  meas", "W",  C["accent"], C["accentLight"]),
            ]
        else:
            measured = [html.Div(
                "Monitor inactivo — arrancará al ejecutar el perfil",
                style={"color": C["dim"], "fontSize": 11,
                       "gridColumn": "1 / -1", "padding": 8},
            )]

        return {**bar_base, "width": f"{pct}%"}, info, readout, measured

    # ─── 7. Terminal SCPI ─────────────────────────────────────────────────────
    @app.callback(
        Output("scpi-terminal", "children"),
        Output("scpi-summary",  "children"),
        Input("store-scpi-log", "data"),
        Input("store-profile",  "data"),
        State("inp-dt",         "value"),   # FIX: Δt real del input del usuario
    )
    def update_terminal(log, profile, dt):
        # FIX: usar el Δt configurado por el usuario, no DT_MIN fijo
        dt_ms = max(dt or 1000, DT_MIN)

        preview = []
        if profile:
            for step in profile[:8]:
                preview += [
                    f"VOLT {step['V_set']:.3f}",
                    f"CURR {step['I_set']:.3f}",
                    f"# wait {dt_ms}ms",   # ← ahora refleja el valor real
                ]
            if len(profile) > 8:
                preview.append(f"# ... {len(profile) - 8} pasos mas")

        all_cmds = (
            ["SYST:LOCK ON", "OUTP ON"]
            + preview
            + ["OUTP OFF"]
            + (log or [])
        )[:60]

        lines = [
            html.Div([
                html.Span(f"{i+1:03d}",
                          style={"color": "#4a6a4a", "marginRight": 10}),
                html.Span(cmd, style={
                    "color": "#6b8a6b" if cmd.startswith("#") else "#4ade80"
                }),
            ])
            for i, cmd in enumerate(all_cmds)
        ]

        total = len(profile) * 3 + 4 if profile else 0
        summary = (
            f"Total estimado: {total} cmds · SCPI ASCII · "
            f"USB/COM · Dt {dt_ms} ms/paso"
        )
        return lines, summary

    # ─── 8. Pasos y duración del perfil ──────────────────────────────────────
    @app.callback(
        Output("exec-n-steps",  "children"),
        Output("exec-duration", "children"),
        Input("inp-dt",         "value"),
        Input("store-profile",  "data"),
    )
    def update_exec_info(dt, profile):
        if not profile:
            return "—", "—"
        n       = len(profile)
        dt_ms   = max(dt or 1000, DT_MIN)
        total_s = n * dt_ms / 1000.0
        if total_s < 60:
            dur = f"{total_s:.0f} s"
        elif total_s < 3600:
            dur = f"{total_s/60:.1f} min"
        else:
            dur = f"{total_s/3600:.2f} h"
        return str(n), dur