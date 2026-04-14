"""
hmi/callbacks/scpi_cb.py
=========================
Callbacks del Tab 3 — Control SCPI + Bridge Modbus TCP.

Callbacks registrados (7):
    - connect_scpi          -> abre puerto COM y verifica *IDN?
    - bridge_control        -> inicia / detiene ScpiModbusBridge en thread
    - update_bridge_status  -> polling del estado del bridge (interval-live)
    - manual_control        -> OUTP ON/OFF con V e I manuales
    - toggle_exec           -> arranca / detiene perfil PV en thread
    - update_exec_progress  -> progreso del perfil (interval-exec)
    - update_terminal       -> terminal SCPI con comandos enviados
"""

import threading
from dash import Input, Output, State, html, ctx, no_update

from config.hardware import C, DT_MIN
from comm.scpi       import SCPIController

# Bridge — importacion defensiva
try:
    from comm.bridge import ScpiModbusBridge, BridgeConfig
    BRIDGE_AVAILABLE = True
except ImportError:
    BRIDGE_AVAILABLE = False


# ── Estado global compartido entre callbacks ──────────────────────────────────
_controller:    SCPIController              = SCPIController(port="COM3")
_exec_thread:   threading.Thread           = None
_bridge:        "ScpiModbusBridge | None"  = None
_bridge_thread: threading.Thread           = None


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
            idn = _controller.connect()
            return html.Div(
                f"Conectado: {idn[:60]}",
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

        try:
            cfg = BridgeConfig(
                serial_port   = port,
                modbus_host   = host  or "0.0.0.0",
                modbus_port   = int(mb_port or 502),
                poll_interval = float(poll or 0.5),
            )
            _bridge = ScpiModbusBridge(cfg)

            # El bridge bloquea en StartTcpServer — lanzar en daemon thread
            _bridge_thread = threading.Thread(
                target=_bridge.start, daemon=True, name="ModbusBridge"
            )
            _bridge_thread.start()

            return html.Div(
                f"Bridge activo: {host or '0.0.0.0'}:{mb_port or 502} "
                f"(poll {poll or 0.5}s)",
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
                V = V or 0.0
                I = I or 0.0
                _controller.set_output(V, I, on=True)
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
        State("inp-dt",            "value"),
        State("dd-port",           "value"),
        State("store-exec-state",  "data"),
        prevent_initial_call=True,
    )
    def toggle_exec(_n_start, _n_stop, profile, dt, port, state):
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

            def _run():
                try:
                    _controller.connect()
                    _controller.run_profile(profile, dt_ms)
                except Exception as exc:
                    import logging
                    logging.getLogger("scpi_cb").error(f"Perfil error: {exc}")

            _exec_thread = threading.Thread(target=_run, daemon=True,
                                             name="ProfileExec")
            _exec_thread.start()
            return False, {"running": True, "step": 0}

        return True, state

    # ─── 6. Progreso del perfil ───────────────────────────────────────────────
    @app.callback(
        Output("progress-bar",   "style"),
        Output("exec-step-info", "children"),
        Output("live-readout",   "children"),
        Input("interval-exec",   "n_intervals"),
        State("store-profile",   "data"),
        State("store-exec-state","data"),
    )
    def update_exec_progress(n_intervals, profile, state):
        bar_base = {"height": "100%", "background": C["accent"],
                    "borderRadius": 4, "transition": "width 0.3s"}

        if not profile or not state.get("running"):
            return {**bar_base, "width": "0%"}, "Sin perfil en ejecucion.", []

        total = len(profile)
        idx   = min(n_intervals % total, total - 1)
        pct   = round(idx / max(total - 1, 1) * 100, 1)
        step  = profile[idx]
        info  = f"Paso {idx + 1} de {total} — Dt {DT_MIN} ms min."

        readout = [
            html.Div([
                html.Div(f"{step.get(k, 0)}", style={
                    "fontSize": 22, "fontWeight": 900,
                    "color": color, "fontFamily": "monospace"}),
                html.Div(f"{lbl} ({unit})",
                         style={"fontSize": 9, "color": C["dim"],
                                "fontWeight": 600}),
            ], style={"padding": 12, "background": bg,
                      "borderRadius": 10, "textAlign": "center",
                      "border": f"1px solid {color}22"})
            for k, lbl, unit, color, bg in [
                ("V_set", "VOLT", "V",  C["red"],    C["redLight"]),
                ("I_set", "CURR", "A",  C["blue"],   C["blueLight"]),
                ("P_set", "POWER","W",  C["accent"], C["accentLight"]),
            ]
        ]
        return {**bar_base, "width": f"{pct}%"}, info, readout

    # ─── 7. Terminal SCPI ─────────────────────────────────────────────────────
    @app.callback(
        Output("scpi-terminal", "children"),
        Output("scpi-summary",  "children"),
        Input("store-scpi-log", "data"),
        Input("store-profile",  "data"),
    )
    def update_terminal(log, profile):
        preview = []
        if profile:
            for step in profile[:8]:
                preview += [
                    f"VOLT {step['V_set']:.3f}",
                    f"CURR {step['I_set']:.3f}",
                    f"# wait {DT_MIN}ms",
                ]
            if len(profile) > 8:
                preview.append(f"# ... {len(profile) - 8} pasos mas")

        all_cmds = (
            ["SYST:REM:TRAN ON", "OUTP ON"]
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
            f"USB/COM · Dt {DT_MIN} ms/paso"
        )
        return lines, summary