"""
hmi/layout/tab_ubicacion.py
============================
Layout del Tab 0 — Ubicación & Datos.
Migrado de tab_ubicacion() en app.py.

Contiene la selección de ciudad colombiana, el rango de fechas,
el botón de descarga de NASA POWER y los contenedores de gráficas
(se llenan dinámicamente por nasa_cb.update_irradiance_charts).
"""

from dash import dcc, html
from config.locations import LOCATIONS
from config.hardware  import C
from hmi.layout.components import card


def tab_ubicacion() -> html.Div:
    """
    Devuelve el layout completo del Tab 0.
    Se llama cada vez que el usuario navega a esta pestaña (render_tab en app.py).
    """
    # ── Botones de ciudades (grid 2 columnas) ─────────────────────────────────
    loc_buttons = [
        html.Button(
            loc["name"],
            id={"type": "btn-loc", "index": i},
            n_clicks=0,
            style={
                "padding":      "6px 10px",
                "borderRadius": 8,
                "fontSize":     11,
                "border":       f"1px solid {C['border']}",
                "background":   C["white"],
                "color":        C["textMed"],
                "cursor":       "pointer",
                "width":        "100%",
                "textAlign":    "left",
            },
        )
        for i, loc in enumerate(LOCATIONS)
    ]

    panel_izquierdo = html.Div([

        card([
            html.Div(
                loc_buttons,
                style={
                    "display":             "grid",
                    "gridTemplateColumns": "1fr 1fr",
                    "gap":                 5,
                    "marginBottom":        12,
                },
            ),
            # Inputs de coordenadas personalizadas (ocultos por defecto)
            html.Div(
                id="custom-coords-container",
                style={"display": "none"},
                children=[
                    html.Div("Latitud", style={"fontSize": 11, "color": C["dim"],
                                               "marginBottom": 3}),
                    dcc.Input(
                        id="inp-lat", type="number", value=4.71, step=0.01,
                        style=_input_style(),
                    ),
                    html.Div("Longitud", style={"fontSize": 11, "color": C["dim"],
                                                "marginTop": 8, "marginBottom": 3}),
                    dcc.Input(
                        id="inp-lon", type="number", value=-74.07, step=0.01,
                        style=_input_style(),
                    ),
                ],
            ),
        ], title="Ubicación"),

        card([
            html.Div("Fecha inicio (YYYYMMDD)",
                     style={"fontSize": 11, "color": C["dim"], "marginBottom": 3}),
            dcc.Input(
                id="inp-start", type="text", value="20240315",
                style={**_input_style(), "marginBottom": 10},
            ),
            html.Div("Fecha fin (YYYYMMDD)",
                     style={"fontSize": 11, "color": C["dim"], "marginBottom": 3}),
            dcc.Input(
                id="inp-end", type="text", value="20240317",
                style={**_input_style(), "marginBottom": 12},
            ),
            html.Button(
                "Descargar datos NASA POWER",
                id="btn-fetch-nasa",
                n_clicks=0,
                style={
                    "width":        "100%",
                    "padding":      "10px",
                    "borderRadius": 10,
                    "border":       "none",
                    "background":   C["accent"],
                    "color":        "#fff",
                    "fontWeight":   800,
                    "fontSize":     12,
                    "cursor":       "pointer",
                },
            ),
            # Estado de la descarga (OK / error) — actualizado por nasa_cb
            html.Div(id="nasa-status", style={"marginTop": 8}),
            html.Div([
                "Parámetros: GHI · DNI · DHI · T2M · WS2M", html.Br(),
                "Fuente: NASA POWER (CERES + MERRA-2)",      html.Br(),
                "Datos horarios disponibles desde 2001",
            ], style={"marginTop": 10, "fontSize": 9,
                      "color": C["dim"], "lineHeight": 1.6}),
        ], title="Rango de fechas"),

    ], style={
        "width":         290,
        "flexShrink":    0,
        "display":       "flex",
        "flexDirection": "column",
        "gap":           12,
    })

    # ── Panel derecho: gráficas (rellenas por callback) ───────────────────────
    panel_derecho = html.Div(
        id="irradiance-chart-container",
        children=[
            html.Div(
                "Selecciona una ubicación y descarga datos para ver las gráficas.",
                style={
                    "textAlign":  "center",
                    "color":      C["dim"],
                    "padding":    "80px 0",
                    "fontSize":   13,
                },
            )
        ],
        style={"flex": 1, "display": "flex", "flexDirection": "column", "gap": 12},
    )

    return html.Div([
        panel_izquierdo,
        panel_derecho,
    ], style={"display": "flex", "gap": 14})


def _input_style() -> dict:
    return {
        "width":        "100%",
        "padding":      "6px 10px",
        "borderRadius": 8,
        "border":       f"1px solid {C['border']}",
        "fontSize":     12,
        "fontFamily":   "monospace",
        "color":        C["text"],
        "background":   C["white"],
        "boxSizing":    "border-box",
    }
