"""
app.py — PV Array Emulator
==========================
Punto de entrada de la HMI. Solo ensambla:
  - instancia Dash
  - layout (header + tabs + stores)
  - registro de callbacks (delegado a hmi/callbacks/)
  - modo de arranque (navegador o escritorio con pywebview)

Toda la lógica vive en los módulos:
    config/        — constantes y paleta
    models/        — modelos eléctricos PV
    pipeline/      — NASA POWER, perfil, SeqLog
    comm/          — SCPI, Ethernet
    hmi/layout/    — layouts de cada tab
    hmi/callbacks/ — callbacks de Dash

Instalar dependencias:
    pip install -r requirements.txt

Correr:
    python app.py            # modo navegador  → http://localhost:8050
    python app.py --desktop  # modo escritorio (requiere: pip install pywebview)
"""

import sys
import time
import threading

import dash
from dash import dcc, html, Input, Output, State
import dash_bootstrap_components as dbc
from config.hardware  import C
from hmi.layout       import TAB_RENDERERS
import hmi.callbacks  as cb


# ── Instancia Dash ────────────────────────────────────────────────────────────
app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    suppress_callback_exceptions=True,
    title="PV Array Emulator",
)
server = app.server   # expuesto para despliegue con gunicorn (futuro)


# ── Registrar todos los callbacks ─────────────────────────────────────────────
cb.register_all(app)


# ── Layout ────────────────────────────────────────────────────────────────────
app.layout = html.Div([

    # Stores — memoria del cliente
    dcc.Store(id="store-nasa",       storage_type="memory"),
    dcc.Store(id="store-profile",    storage_type="memory"),
    dcc.Store(id="store-loc-idx",    data=0),
    dcc.Store(id="store-scpi-log",   data=[]),
    dcc.Store(id="store-exec-state", data={"running": False, "step": 0}),

    # Intervals — polling
    dcc.Interval(id="interval-exec", interval=300, disabled=True),
    dcc.Interval(id="interval-live", interval=500, disabled=True),

    # Header
    html.Div([
        html.Div([
            html.Div("PV", style={
                "width": 38, "height": 38, "borderRadius": 10,
                "background": "rgba(255,255,255,0.2)",
                "display": "flex", "alignItems": "center",
                "justifyContent": "center",
                "fontSize": 14, "fontWeight": 900, "color": "#fff",
            }),
            html.Div([
                html.Div("PV Array Emulator", style={
                    "fontSize": 16, "fontWeight": 800,
                    "color": "#fff", "letterSpacing": -0.3,
                }),
                html.Div(
                    "EA-PS 10060-170  ·  NASA POWER  ·  Microrred DC Uniandes",
                    style={"fontSize": 10, "color": "rgba(255,255,255,0.7)"},
                ),
            ]),
        ], style={"display": "flex", "alignItems": "center", "gap": 14}),
        html.Div(id="header-live",
                 style={"display": "flex", "alignItems": "center", "gap": 14}),
    ], style={
        "background":     f"linear-gradient(135deg, {C['header']}, #166534)",
        "padding":        "12px 24px",
        "display":        "flex",
        "alignItems":     "center",
        "justifyContent": "space-between",
    }),

    # Tabs
    # Tabs — contenido estático (todos renderizados al inicio, visibilidad por CSS)
    dcc.Tabs(
        id="main-tabs", value="tab-0",
        children=[
            dcc.Tab(label="Ubicación & Datos", value="tab-0"),
            dcc.Tab(label="Arreglo PV",        value="tab-1"),
            dcc.Tab(label="Perfiles",          value="tab-2"),
            dcc.Tab(label="SCPI / Control",    value="tab-3"),
            dcc.Tab(label="Resumen",           value="tab-4"),
        ],
        colors={"border": C["border"], "primary": C["accent"],
                "background": C["white"]},
    ),

    # Paneles de cada tab — todos en el DOM desde el inicio
    # El callback switch_tab muestra/oculta con display block/none
    html.Div([
        html.Div(TAB_RENDERERS["tab-0"](), id="panel-tab-0",
                 style={"padding": "16px 20px"}),
        html.Div(TAB_RENDERERS["tab-1"](), id="panel-tab-1",
                 style={"padding": "16px 20px", "display": "none"}),
        html.Div(TAB_RENDERERS["tab-2"](), id="panel-tab-2",
                 style={"padding": "16px 20px", "display": "none"}),
        html.Div(TAB_RENDERERS["tab-3"](), id="panel-tab-3",
                 style={"padding": "16px 20px", "display": "none"}),
        html.Div(TAB_RENDERERS["tab-4"](), id="panel-tab-4",
                 style={"padding": "16px 20px", "display": "none"}),
    ], style={"background": C["bg"], "minHeight": "calc(100vh - 110px)"}),

], style={"fontFamily": "'Segoe UI', 'DM Sans', sans-serif",
          "background": C["bg"], "color": C["text"]})


# ── Callback de navegación — muestra/oculta paneles por CSS ──────────────────
@app.callback(
    [Output(f"panel-tab-{i}", "style") for i in range(5)],
    Input("main-tabs", "value"),
)
def switch_tab(tab: str):
    base = {"padding": "16px 20px"}
    oculto = {**base, "display": "none"}
    estilos = [oculto] * 5
    try:
        idx = int(tab.split("-")[1])
        estilos[idx] = base
    except (IndexError, ValueError):
        estilos[0] = base
    return estilos


# ── Punto de entrada ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    if "--desktop" in sys.argv:
        try:
            import webview
            t = threading.Thread(
                target=lambda: app.run(debug=False, port=8050), daemon=True)
            t.start()
            time.sleep(1.5)
            webview.create_window("PV Array Emulator",
                                  "http://localhost:8050",
                                  width=1280, height=800, resizable=True)
            webview.start()
        except ImportError:
            print("pywebview no instalado — abriendo en navegador.")
            app.run(debug=False, port=8050)
    else:
        print("\n  PV Array Emulator  →  http://localhost:8050\n")
        app.run(debug=True, port=8050)
