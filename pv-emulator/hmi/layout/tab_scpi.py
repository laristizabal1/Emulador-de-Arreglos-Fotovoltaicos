"""
hmi/layout/tab_scpi.py
=======================
Layout del Tab 3 — SCPI / Control en tiempo real.
Migrado de tab_scpi() en app.py.

Columna izquierda : selección de puerto, control manual OUTP ON/OFF,
                    botones EJECUTAR / DETENER perfil, barra de progreso.
Columna derecha   : live readout (V, I, P actuales), terminal SCPI oscura.

Todos los outputs los llenan los callbacks de scpi_cb.py.
"""

from dash import dcc, html
from comm.scpi import list_ports
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
        _section_label("Ejecución del perfil"),
        html.Div(id="exec-step-info",
                 style={"fontSize": 11, "color": C["dim"], "marginBottom": 8}),

        html.Div([
            html.Button("EJECUTAR PERFIL", id="btn-exec-start", n_clicks=0,
                        style=_btn_style(C["accent"], "#fff", "none",
                                         font_size=12, padding="10px")),
            html.Button("DETENER",         id="btn-exec-stop",  n_clicks=0,
                        style=_btn_style(C["red"],    "#fff", "none",
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

        # Interval para polling de progreso (activado por toggle_exec)
        dcc.Interval(id="interval-exec", interval=300, disabled=True),

    ], title="Control SCPI — EA-PS 10060-170")


def _panel_monitor() -> html.Div:
    """Columna derecha: live readout y terminal de comandos SCPI."""
    return card([

        # Live readout: V, I, P actuales (relleno por update_exec_progress)
        html.Div(
            id="live-readout",
            style={
                "display":             "grid",
                "gridTemplateColumns": "1fr 1fr 1fr",
                "gap":                 10,
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

        dcc.Interval(id="interval-live", interval=500, disabled=True),

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
