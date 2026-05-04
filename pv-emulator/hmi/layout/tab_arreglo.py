"""
hmi/layout/tab_arreglo.py
==========================
Layout del Tab 1 — Arreglo PV.

Cambios respecto a la versión anterior:
    - Añadido selector de módulo del catálogo (dcc.Dropdown id="dd-module")
    - Sliders muestran/ocultan según si el módulo es "custom" o predefinido
    - Los valores de los sliders se actualizan automáticamente al seleccionar
      un módulo del catálogo (via callback en arreglo_cb.py)

Los outputs (val-*, arreglo-diagram, limites-check) los llena arreglo_cb.py.
"""

from dash import dcc, html
from config.hardware        import C
from config.modules_catalog import get_dropdown_options, DEFAULT_MODULE_KEY
from hmi.layout.components  import card, divider

# Sliders de parámetros eléctricos del módulo (solo visibles en modo custom)
_SLIDERS_MODULO = [
    ("Voc STC",    "sl-Voc",      0,   60,  0.1,   49.8,  " V",    C["red"]),
    ("Isc STC",    "sl-Isc",       0,   20,  0.1,   13.5,  " A",    C["blue"]),
    ("Vmp STC",    "sl-Vmp",      0,   55,  0.1,   41.2,  " V",    C["red"]),
    ("Imp STC",    "sl-Imp",       0,   18,  0.1,   13.35, " A",    C["blue"]),
    ("beta Voc",   "sl-betaVoc", -0.3,   0,  0.001,  -0.13, " V/C",  C["dim"]),
    ("alpha Isc",  "sl-alphaIsc",  0, 1, 0.0001, 0.0005," A/C", C["dim"]),
    ("Ns (celdas)","sl-Ns-cells", 0, 200,   1,    144,   "",      C["dim"]),
    ("NOCT",       "sl-noct",     0,   50,   1,     45,   " C",    C["accent"]),
]

# Sliders de configuración del arreglo (siempre visibles)
_SLIDERS_ARREGLO = [
    ("Paneles en serie (Ns)",  "sl-Ns",   1, 4, 1, 1,  "", C["red"]),
    ("Ramas en paralelo (Np)", "sl-Np",   1, 8, 1, 1,  "", C["blue"]),
    ("Inclinacion",            "sl-tilt", 0,45, 1, 10, "", C["dim"]),
]


def tab_arreglo() -> html.Div:
    return html.Div([
        _panel_parametros(),
        _panel_diagrama(),
    ], style={"display": "flex", "gap": 14})


def _panel_parametros() -> html.Div:
    catalogo = html.Div([
        html.Div("Modulo fotovoltaico", style={
            "fontSize": 10, "fontWeight": 800, "color": C["dim"],
            "textTransform": "uppercase", "letterSpacing": 1, "marginBottom": 6,
        }),
        dcc.Dropdown(
            id="dd-module",
            options=get_dropdown_options(),
            value=DEFAULT_MODULE_KEY,
            clearable=False,
            style={"fontSize": 11, "marginBottom": 4},
        ),
        html.Div(id="module-pmax-badge",
                 style={"fontSize": 10, "color": C["dim"], "marginBottom": 2}),
    ])

    sliders_modulo = html.Div(
        id="custom-module-sliders",
        style={"display": "none"},
        children=[
            divider(),
            html.Div("Parametros del modulo (manual)", style={
                "fontSize": 10, "fontWeight": 800, "color": C["dim"],
                "textTransform": "uppercase", "letterSpacing": 1, "marginBottom": 6,
            }),
            *[_slider_row(label, sl_id, min_, max_, step_, val, color)
              for label, sl_id, min_, max_, step_, val, _unit, color
              in _SLIDERS_MODULO],
        ],
    )

    sliders_arreglo = html.Div([
        divider(),
        html.Div("Configuracion del arreglo", style={
            "fontSize": 10, "fontWeight": 800, "color": C["dim"],
            "textTransform": "uppercase", "letterSpacing": 1, "marginBottom": 6,
        }),
        *[_slider_row(label, sl_id, min_, max_, step_, val, color)
          for label, sl_id, min_, max_, step_, val, _unit, color
          in _SLIDERS_ARREGLO],
    ])

    modelo_selector = html.Div([
        divider(),
        html.Div("Modelo electrico", style={
            "fontSize": 10, "fontWeight": 800, "color": C["dim"],
            "textTransform": "uppercase", "letterSpacing": 1, "marginBottom": 6,
        }),
        dcc.RadioItems(
            id="dd-model",
            options=[
                {"label": "  Simplificado (ec. 4-5 del doc.)", "value": "simplified"},
                {"label": "  1 diodo - Villalva 2009",          "value": "single_diode"},
                {"label": "  2 diodos - Ishaque 2011",          "value": "two_diode"},
            ],
            value="simplified",
            labelStyle={
                "display": "block", "fontSize": 11,
                "color": C["textMed"], "marginBottom": 5, "cursor": "pointer",
            },
        ),
    ])

    return html.Div([
        card([catalogo, sliders_modulo, sliders_arreglo, modelo_selector],
             title="Modulo y arreglo PV"),
    ], style={"width": "48%"})


def _panel_diagrama() -> html.Div:
    return html.Div([
        card([html.Div(id="module-params-table")],
             title="Parametros del modulo activo"),
        card([html.Div(id="arreglo-diagram")],
             title="Diagrama del arreglo", style={"marginTop": 12}),
        card([html.Div(id="limites-check")],
             title="Verificacion de limites  EA-PS 10060-170",
             style={"marginTop": 12}),
    ], style={"width": "48%", "display": "flex",
              "flexDirection": "column", "gap": 12})


def _slider_row(label, sl_id, min_, max_, step_, value, color):
    return html.Div([
        html.Div([
            html.Span(label, style={"fontSize": 12, "color": C["textMed"]}),
            html.Span(id=f"val-{sl_id}",
                      style={"fontSize": 12, "fontWeight": 700,
                             "color": color, "fontFamily": "monospace"}),
        ], style={"display": "flex", "justifyContent": "space-between",
                  "marginBottom": 3}),
        dcc.Slider(id=sl_id, min=min_, max=max_, step=step_, value=value,
                   marks=None, tooltip={"always_visible": False}),
    ], style={"marginBottom": 12})