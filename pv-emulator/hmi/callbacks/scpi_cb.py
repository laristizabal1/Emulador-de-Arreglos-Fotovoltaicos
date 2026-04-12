"""
hmi/callbacks/scpi_cb.py
=========================
Callbacks del Tab 3 — Control SCPI en tiempo real.
Es el módulo más crítico: conecta la HMI directamente con la
fuente EA-PS 10060-170 a través del puerto USB/COM.

Callbacks registrados aquí (5):
    - connect_scpi          → abre el puerto y verifica con *IDN?
    - manual_control        → OUTP ON/OFF con V e I manuales
    - toggle_exec           → arranca / detiene la ejecución del perfil en thread
    - update_exec_progress  → polling del progreso (dcc.Interval cada 300 ms)
    - update_terminal       → renderiza la terminal SCPI con comandos enviados
"""

import threading
from dash import Input, Output, State, html, ctx, no_update

from config.hardware import C, DT_MIN
from comm.scpi       import SCPIController


# ── Estado global del controlador ────────────────────────────────────────────
# Se comparte entre callbacks porque Dash corre en el mismo proceso Python.
# En producción con múltiples workers usar Redis o dcc.Store con ID de sesión.
_controller  = SCPIController(port="COM3")
_exec_thread: threading.Thread = None


def register(app):
    """
    Registra los 5 callbacks SCPI en la instancia `app` de Dash.
    Se llama desde app.py: scpi_cb.register(app)
    """

    # ─── 1. Conectar / verificar ──────────────────────────────────────────────
    @app.callback(
        Output("connect-status", "children"),
        Input("btn-connect", "n_clicks"),
        State("dd-port",     "value"),
        prevent_initial_call=True,
    )
    def connect_scpi(_n, port):
        """
        Abre el puerto COM seleccionado y envía *IDN? para confirmar
        que la fuente EA responde en modo SCPI ASCII.

        Actualiza _controller.port antes de conectar para que los
        callbacks posteriores (manual, exec) usen el puerto correcto.
        """
        from comm.scpi import SERIAL_AVAILABLE
        if not SERIAL_AVAILABLE:
            return html.Div(
                "⚠  pyserial no instalado — ejecutar: pip install pyserial",
                style={"color": C["red"], "fontSize": 11},
            )
        if not port or port == "NONE":
            return html.Div(
                "Selecciona un puerto COM primero.",
                style={"color": C["red"], "fontSize": 11},
            )
        try:
            _controller.port = port
            idn = _controller.connect()
            return html.Div(
                f"✓  Conectado: {idn[:60]}",
                style={"color": C["accentDark"], "fontWeight": 600, "fontSize": 11},
            )
        except Exception as exc:
            return html.Div(
                f"❌  {exc}",
                style={"color": C["red"], "fontSize": 11},
            )

    # ─── 2. Control manual ────────────────────────────────────────────────────
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
        """
        Envía comandos SCPI individuales para pruebas manuales.

        OUTP ON:  VOLT {V:.3f} → CURR {I:.3f} → OUTP ON
        OUTP OFF: OUTP OFF

        Cada comando enviado se agrega a store-scpi-log para
        mostrarlo en la terminal de la HMI (máximo 60 líneas).
        """
        triggered = ctx.triggered_id
        log       = log or []

        try:
            if triggered == "btn-outp-on":
                V = V or 0.0
                I = I or 0.0
                _controller.set_output(V, I, on=True)
                nuevos = [f"VOLT {V:.3f}", f"CURR {I:.3f}", "OUTP ON"]
                log.extend(nuevos)
                status = html.Div(
                    f"✓  Salida ON  —  {V} V · {I} A",
                    style={"color": C["accentDark"], "fontWeight": 600},
                )
            else:
                _controller.output_off()
                log.append("OUTP OFF")
                status = html.Div(
                    "■  Salida OFF",
                    style={"color": C["red"], "fontWeight": 600},
                )

        except Exception as exc:
            status = html.Div(f"❌  {exc}", style={"color": C["red"]})

        return status, log[-60:]  # conservar las últimas 60 líneas

    # ─── 3. Ejecutar / detener perfil completo ────────────────────────────────
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
        """
        EJECUTAR: lanza SCPIController.run_profile() en un thread daemon
                  para no bloquear la UI de Dash.
                  Habilita dcc.Interval para el polling de progreso.

        DETENER:  llama a _controller.stop() que pone _running=False
                  y envía OUTP OFF inmediatamente.
                  Deshabilita el Interval.

        store-exec-state = {"running": bool, "step": int}
        El campo "step" se actualiza desde update_exec_progress.
        """
        global _exec_thread

        triggered = ctx.triggered_id

        if triggered == "btn-exec-stop":
            _controller.stop()
            return True, {"running": False, "step": 0}

        if triggered == "btn-exec-start":
            if not profile:
                return True, state   # nada que ejecutar

            _controller.port = port or "COM3"
            dt_ms = max(dt or 1000, DT_MIN)

            def _run():
                try:
                    _controller.connect()
                    _controller.run_profile(profile, dt_ms)
                except Exception as exc:
                    print(f"[SCPI ERROR] {exc}")

            _exec_thread = threading.Thread(target=_run, daemon=True)
            _exec_thread.start()
            return False, {"running": True, "step": 0}

        return True, state

    # ─── 4. Progreso en tiempo real (polling con dcc.Interval) ───────────────
    @app.callback(
        Output("progress-bar",   "style"),
        Output("exec-step-info", "children"),
        Output("live-readout",   "children"),
        Input("interval-exec",   "n_intervals"),
        State("store-profile",   "data"),
        State("store-exec-state","data"),
    )
    def update_exec_progress(n_intervals, profile, state):
        """
        Se ejecuta cada 300 ms mientras dcc.Interval está activo.
        Aproxima el paso actual por el número de intervalos transcurridos
        (no requiere comunicación adicional con la fuente).

        Barra de progreso: ancho = (paso_actual / total) × 100%
        Live readout: V_set, I_set, P_set del paso estimado.
        """
        bar_base = {
            "height":       "100%",
            "background":   C["accent"],
            "borderRadius": 4,
            "transition":   "width 0.3s",
        }

        if not profile or not state.get("running"):
            return {**bar_base, "width": "0%"}, "Sin perfil en ejecución.", []

        total = len(profile)
        # Aproximación: cada intervalo de 300 ms avanza ~1 tick
        idx   = min(n_intervals % total, total - 1)
        pct   = round(idx / max(total - 1, 1) * 100, 1)
        step  = profile[idx]

        info = f"Ejecutando — paso {idx + 1} de {total} · Δt {DT_MIN} ms mín."

        readout = []
        for label, val, unit, color, bg in [
            ("VOLT",  step.get("V_set", 0), "V",  C["red"],    C["redLight"]),
            ("CURR",  step.get("I_set", 0), "A",  C["blue"],   C["blueLight"]),
            ("POWER", step.get("P_set", 0), "W",  C["accent"], C["accentLight"]),
        ]:
            readout.append(html.Div([
                html.Div(
                    f"{val}",
                    style={"fontSize": 22, "fontWeight": 900,
                           "color": color, "fontFamily": "monospace"},
                ),
                html.Div(
                    f"{label} ({unit})",
                    style={"fontSize": 9, "color": C["dim"], "fontWeight": 600},
                ),
            ], style={
                "padding":      12,
                "background":   bg,
                "borderRadius": 10,
                "textAlign":    "center",
                "border":       f"1px solid {color}22",
            }))

        return {**bar_base, "width": f"{pct}%"}, info, readout

    # ─── 5. Terminal SCPI ─────────────────────────────────────────────────────
    @app.callback(
        Output("scpi-terminal", "children"),
        Output("scpi-summary",  "children"),
        Input("store-scpi-log", "data"),
        Input("store-profile",  "data"),
    )
    def update_terminal(log, profile):
        """
        Renderiza un visor de comandos SCPI estilo terminal oscura.

        Combina:
          - Cabecera fija: SYST:REM:TRAN ON, OUTP ON
          - Vista previa del perfil (primeros 10 pasos × 3 comandos)
          - Comandos manuales enviados (store-scpi-log)
          - Pie: OUTP OFF

        Comentarios (#) en verde oscuro, comandos activos en verde brillante.
        Máximo 60 líneas visibles para no saturar el DOM.
        """
        preview = []
        if profile:
            for step in profile[:10]:
                preview += [
                    f"VOLT {step['V_set']:.3f}",
                    f"CURR {step['I_set']:.3f}",
                    f"# wait {DT_MIN}ms",
                ]
            if len(profile) > 10:
                preview.append(f"# ... {len(profile) - 10} pasos más")

        all_cmds = (
            ["SYST:REM:TRAN ON", "OUTP ON"]
            + preview
            + ["OUTP OFF"]
            + (log or [])
        )[:60]

        lines = []
        for i, cmd in enumerate(all_cmds):
            is_comment = cmd.startswith("#") or cmd == "..."
            color = "#6b8a6b" if is_comment else "#4ade80"
            lines.append(html.Div([
                html.Span(f"{i + 1:03d}",
                          style={"color": "#4a6a4a", "marginRight": 10}),
                html.Span(cmd, style={"color": color}),
            ]))

        total_cmds = len(profile) * 3 + 4 if profile else 0
        summary = (
            f"Total estimado: {total_cmds} comandos · "
            f"SCPI ASCII · USB/COM · Δt {DT_MIN} ms/paso"
        )
        return lines, summary
