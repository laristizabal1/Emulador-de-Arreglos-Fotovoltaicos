"""
hmi/layout/tab_perfiles.py
===========================
Layout del Tab 2 — Perfiles de consignas.
Migrado de tab_perfiles() en app.py.

Contiene la barra de controles (estrategia, ms/paso, exportar CSV),
los stat_box de métricas y los dos gráficos de Plotly.
Los outputs los llena profile_cb.update_profile y profile_cb.export_csv.
"""

from dash import dcc, html
from config.hardware import C
from hmi.layout.components import card


def tab_perfiles() -> html.Div:
    """Devuelve el layout completo del Tab 2."""
    return html.Div([

        # Aviso si no hay datos (relleno por profile_cb)
        html.Div(id="perfiles-warning"),

        # ── Barra de controles ────────────────────────────────────────────────
        html.Div([
            # Selector de estrategia
            html.Div([
                html.Span("Estrategia:", style={"fontSize": 11, "color": C["dim"]}),
                dcc.RadioItems(
                    id="dd-strategy",
                    options=[
                        {"label": "  Completa",        "value": "full"},
                        {"label": "  Diurna (6–18h)",  "value": "day"},
                        {"label": "  Promedio",        "value": "average"},
                    ],
                    value="day",
                    inline=True,
                    labelStyle={
                        "marginLeft": 10,
                        "fontSize":   11,
                        "color":      C["textMed"],
                        "cursor":     "pointer",
                    },
                ),
            ], style={"display": "flex", "alignItems": "center", "gap": 8}),

            # ms/paso + botón exportar
            html.Div([
                html.Span("ms/paso:", style={"fontSize": 11, "color": C["dim"]}),
                dcc.Input(
                    id="inp-dt",
                    type="number", value=1000, min=200, step=100,
                    style={
                        "width":        80,
                        "padding":      "5px 8px",
                        "borderRadius": 8,
                        "border":       f"1px solid {C['border']}",
                        "fontSize":     12,
                        "fontFamily":   "monospace",
                    },
                ),
                html.Button(
                    "Exportar SeqLog CSV",
                    id="btn-export-csv",
                    n_clicks=0,
                    style={
                        "padding":      "7px 16px",
                        "borderRadius": 8,
                        "border":       f"1px solid {C['accent']}",
                        "background":   C["accentLight"],
                        "color":        C["accentDark"],
                        "fontWeight":   700,
                        "fontSize":     11,
                        "cursor":       "pointer",
                    },
                ),
                dcc.Download(id="download-csv"),
            ], style={"display": "flex", "alignItems": "center", "gap": 10}),
        ], style={
            "display":        "flex",
            "justifyContent": "space-between",
            "alignItems":     "center",
            "marginBottom":   12,
        }),

        # ── Tarjetas de métricas (rellenas por profile_cb) ───────────────────
        html.Div(
            id="profile-stats",
            style={
                "display":             "grid",
                "gridTemplateColumns": "repeat(5, 1fr)",
                "gap":                 10,
                "marginBottom":        12,
            },
        ),

        # ── Gráfica V_set · I_set ────────────────────────────────────────────
        card(
            [dcc.Graph(
                id="chart-vi",
                config={"displayModeBar": False},
                style={"height": 200},
            )],
            title="Consignas V_set · I_set",
        ),

        # ── Gráfica P_set · Tcell ────────────────────────────────────────────
        card(
            [dcc.Graph(
                id="chart-pt",
                config={"displayModeBar": False},
                style={"height": 180},
            )],
            title="Potencia y temperatura de celda",
            style={"marginTop": 12},
        ),

    ], style={"display": "flex", "flexDirection": "column", "gap": 0})
