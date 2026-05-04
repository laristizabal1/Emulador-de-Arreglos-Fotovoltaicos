"""
hmi/layout/tab_scpi.py
=======================
Layout del Tab 3 — SCPI / Control en tiempo real.

Columna izquierda : selección de puerto, control manual OUTP ON/OFF,
                    botones EJECUTAR / DETENER perfil, barra de progreso.
Columna derecha   : live readout (V, I, P actuales), terminal SCPI oscura.

Todos los outputs los llenan los callbacks de scpi_cb.py.

CORRECCIONES:
    - Eliminado bloque duplicado de Δt/Pasos/Duración/botones que generaba
      dos secciones "Ejecución del perfil" y dos instancias del id "inp-dt".
    - Los ids exec-n-steps, exec-duration e inp-dt aparecen una sola vez.
"""

from dash import dcc, html
from config.hardware import C
from hmi.layout.components import card


def tab_scpi() -> html.Div:
    """Devuelve el layout completo del Tab 3."""
    return html.Div([
        html.Div([
            _panel_control(),
            _panel_monitor(),
        ], style={"display": "grid", "gridTemplateColumns": "340px 1fr", "gap": 14}),
    ])


def _panel_control() -> html.Div:
    """Columna izquierda: conexión, control manual y ejecución de perfil."""
    from comm.scpi import list_ports   # importacion local
    ports = list_ports()
    return card([

        # ── Selección de puerto ───────────────────────────────────────────────
        html.Div("Puerto COM / USB",
                 style={"fontSize": 11, "color": C["dim"], "marginBottom": 4}),
        dcc.Dropdown(
            id="dd-port",
            options=ports,
            value=ports[0]["value"] if ports else "NONE",
            clearable=False,
            style={"fontSize": 12, "marginBottom": 12},
        ),
        html.Button(
            "Conectar / verificar (*IDN?)",
            id="btn-connect",
            n_clicks=0,
            style=_btn_style(C["accentBg"], C["accentDark"], C["border"]),
        ),
        html.Div(id="connect-status", style={"fontSize": 11, "marginBottom": 14}),

        html.Hr(style={"borderColor": C["border"]}),

        # ── Control manual ────────────────────────────────────────────────────
        _section_label("Control manual"),
        html.Div([
            html.Div([
                html.Div("Voltaje (V)",
                         style={"fontSize": 11, "color": C["dim"], "marginBottom": 3}),
                dcc.Input(id="inp-manual-v", type="number",
                          value=10.0, min=0, max=60, step=0.1,
                          style=_input_style()),
            ], style={"flex": 1}),
            html.Div([
                html.Div("Corriente (A)",
                         style={"fontSize": 11, "color": C["dim"], "marginBottom": 3}),
                dcc.Input(id="inp-manual-i", type="number",
                          value=5.0, min=0, max=170, step=0.1,
                          style=_input_style()),
            ], style={"flex": 1}),
        ], style={"display": "flex", "gap": 8, "marginBottom": 10}),

        html.Div([
            html.Button("OUTP ON",  id="btn-outp-on",  n_clicks=0,
                        style=_btn_style(C["accent"], "#fff", "none")),
            html.Button("OUTP OFF", id="btn-outp-off", n_clicks=0,
                        style=_btn_style(C["red"],    "#fff", "none")),
        ], style={"display": "flex", "gap": 8, "marginBottom": 14}),

        html.Div(id="manual-status", style={"fontSize": 11}),

        html.Hr(style={"borderColor": C["border"]}),

        # ── Ejecución de perfil ───────────────────────────────────────────────
        # FIX: bloque único — eliminada la segunda instancia duplicada que
        # causaba dos secciones visibles y conflicto de ids en Dash.
        _section_label("Ejecucion del perfil PV"),
        html.Div(id="exec-step-info",
                 style={"fontSize": 11, "color": C["dim"], "marginBottom": 8}),

        # Control de delta de tiempo + info de pasos y duración
        html.Div([
            html.Div([
                html.Div("Δt por paso (ms)",
                         style={"fontSize": 11, "color": C["dim"],
                                "marginBottom": 3}),
                dcc.Input(
                    id="inp-dt",
                    type="number",
                    value=1000,
                    min=200,
                    max=60000,
                    step=100,
                    style=_input_style(),
                ),
            ], style={"flex": 1}),
            html.Div([
                html.Div("Pasos totales",
                         style={"fontSize": 11, "color": C["dim"],
                                "marginBottom": 3}),
                html.Div(id="exec-n-steps",
                         style={"fontSize": 13, "fontWeight": 700,
                                "fontFamily": "monospace",
                                "color": C["textMed"], "padding": "6px 0"}),
            ], style={"flex": 1}),
            html.Div([
                html.Div("Duración total",
                         style={"fontSize": 11, "color": C["dim"],
                                "marginBottom": 3}),
                html.Div(id="exec-duration",
                         style={"fontSize": 13, "fontWeight": 700,
                                "fontFamily": "monospace",
                                "color": C["textMed"], "padding": "6px 0"}),
            ], style={"flex": 1}),
        ], style={"display": "flex", "gap": 10, "marginBottom": 10}),

        html.Div([
            html.Button("EJECUTAR PERFIL", id="btn-exec-start", n_clicks=0,
                        style=_btn_style(C["accent"], "#fff", "none",
                                         font_size=12, padding="10px")),
            html.Button("DETENER",         id="btn-exec-stop",  n_clicks=0,
                        style=_btn_style(C["red"],   "#fff", "none",
                                         font_size=12, padding="10px")),
        ], style={"display": "flex", "gap": 8, "marginBottom": 10}),

        # Barra de progreso
        html.Div(
            style={
                "width":        "100%",
                "height":       6,
                "background":   C["borderLight"],
                "borderRadius": 4,
                "overflow":     "hidden",
            },
            children=[
                html.Div(
                    id="progress-bar",
                    style={
                        "width":        "0%",
                        "height":       "100%",
                        "background":   C["accent"],
                        "borderRadius": 4,
                        "transition":   "width 0.3s",
                    },
                )
            ],
        ),

        html.Hr(style={"borderColor": C["border"]}),

        # ── Bridge Modbus TCP ─────────────────────────────────────────────────
        _section_label("Bridge Modbus TCP"),

        # Host y puerto Modbus
        html.Div([
            html.Div([
                html.Div("Host (escuchar en)",
                         style={"fontSize": 11, "color": C["dim"], "marginBottom": 3}),
                dcc.Input(
                    id="inp-modbus-host",
                    type="text",
                    value="0.0.0.0",
                    debounce=True,
                    style=_input_style(),
                ),
            ], style={"flex": 2}),
            html.Div([
                html.Div("Puerto TCP",
                         style={"fontSize": 11, "color": C["dim"], "marginBottom": 3}),
                dcc.Input(
                    id="inp-modbus-port",
                    type="number",
                    value=502,
                    min=1,
                    max=65535,
                    style=_input_style(),
                ),
            ], style={"flex": 1}),
            html.Div([
                html.Div("Poll (ms)",
                         style={"fontSize": 11, "color": C["dim"], "marginBottom": 3}),
                dcc.Input(
                    id="inp-bridge-poll",
                    type="number",
                    value=20,
                    min=20,
                    max=5000,
                    step=10,
                    style=_input_style(),
                ),
            ], style={"flex": 1}),
        ], style={"display": "flex", "gap": 8, "marginBottom": 10}),

        html.Div([
            html.Button("Iniciar Bridge", id="btn-bridge-start", n_clicks=0,
                        style=_btn_style(C["accent"], "#fff", "none",
                                         font_size=11, padding="8px")),
            html.Button("Detener Bridge", id="btn-bridge-stop",  n_clicks=0,
                        style=_btn_style(C["red"],   "#fff", "none",
                                         font_size=11, padding="8px")),
        ], style={"display": "flex", "gap": 8, "marginBottom": 8}),

        html.Div(id="bridge-status",
                 style={"fontSize": 11, "marginBottom": 10}),

    ], title="Control SCPI — EA-PS 10060-170")


def _panel_monitor() -> html.Div:
    """Columna derecha: live readout y terminal de comandos SCPI."""
    return card([

        # Live readout: consignas V_set, I_set, P_set (relleno por update_exec_progress)
        html.Div("Consignas enviadas (set)", style={
            "fontSize": 10, "fontWeight": 800, "color": C["dim"],
            "textTransform": "uppercase", "letterSpacing": 1, "marginBottom": 6,
        }),
        html.Div(
            id="live-readout",
            style={
                "display":             "grid",
                "gridTemplateColumns": "1fr 1fr 1fr",
                "gap":                 10,
                "marginBottom":        14,
            },
        ),

        # Mediciones reales: V_meas, I_meas, P_meas desde MEAS:VOLT?/CURR?/POW?
        html.Div("Mediciones reales (MEAS)", style={
            "fontSize": 10, "fontWeight": 800, "color": C["dim"],
            "textTransform": "uppercase", "letterSpacing": 1, "marginBottom": 6,
        }),
        html.Div(
            id="live-measured",
            style={
                "display":             "grid",
                "gridTemplateColumns": "1fr 1fr 1fr",
                "gap":                 10,
                "marginBottom":        14,
            },
        ),

        # Bridge Modbus readout (relleno por update_bridge_status)
        html.Div("Mediciones Bridge Modbus", style={
            "fontSize":      10,
            "fontWeight":    800,
            "color":         C["dim"],
            "textTransform": "uppercase",
            "letterSpacing": 1,
            "marginBottom":  6,
        }),
        html.Div(
            id="bridge-modbus-readout",
            style={
                "display":             "grid",
                "gridTemplateColumns": "1fr 1fr 1fr",
                "gap":                 8,
                "marginBottom":        14,
            },
        ),

        # Terminal SCPI
        html.Div("Comandos enviados", style={
            "fontSize":      10,
            "fontWeight":    800,
            "color":         C["dim"],
            "textTransform": "uppercase",
            "letterSpacing": 1,
            "marginBottom":  6,
        }),
        html.Div(
            id="scpi-terminal",
            style={
                "background":  "#1a2e1a",
                "borderRadius": 10,
                "padding":     12,
                "maxHeight":   340,
                "overflowY":   "auto",
                "fontFamily":  "monospace",
                "fontSize":    10,
                "lineHeight":  1.8,
            },
        ),
        html.Div(
            id="scpi-summary",
            style={"marginTop": 8, "fontSize": 10, "color": C["dim"]},
        ),

    ], title="Monitor en tiempo real")


# ── Helpers privados ──────────────────────────────────────────────────────────

def _section_label(text: str) -> html.Div:
    return html.Div(text, style={
        "fontSize":      10,
        "fontWeight":    800,
        "color":         C["dim"],
        "textTransform": "uppercase",
        "letterSpacing": 1,
        "marginBottom":  8,
    })


def _btn_style(bg: str, color: str, border: str,
               font_size: int = 11, padding: str = "8px") -> dict:
    return {
        "flex":         1,
        "padding":      padding,
        "borderRadius": 10,
        "border":       f"1px solid {border}" if border != "none" else "none",
        "background":   bg,
        "color":        color,
        "fontWeight":   800,
        "fontSize":     font_size,
        "cursor":       "pointer",
    }


def _input_style() -> dict:
    return {
        "width":        "100%",
        "padding":      "6px 8px",
        "borderRadius": 8,
        "border":       f"1px solid {C['border']}",
        "fontSize":     12,
        "fontFamily":   "monospace",
        "color":        C["text"],
        "background":   C["white"],
        "boxSizing":    "border-box",
    }