"""
hmi/layout/tab_resumen.py
==========================
Layout del Tab 4 — Resumen.
Migrado de tab_resumen() en app.py.

Contiene la grilla de 4 stat_box, la tabla de configuración completa
y la gráfica de operación final. Los outputs los llena resumen_cb.py.
"""

from dash import dcc, html
from config.hardware import C
from hmi.layout.components import card


def tab_resumen() -> html.Div:
    """Devuelve el layout completo del Tab 4."""
    return html.Div([

        # ── 4 tarjetas de métricas ────────────────────────────────────────────
        html.Div(
            id="resumen-stats",
            style={
                "display":             "grid",
                "gridTemplateColumns": "repeat(4, 1fr)",
                "gap":                 10,
                "marginBottom":        12,
            },
        ),

        # ── Tabla de configuración completa ───────────────────────────────────
        card(
            [html.Div(id="resumen-config")],
            title="Configuración completa",
        ),

        # ── Gráfica de operación ──────────────────────────────────────────────
        card(
            [dcc.Graph(
                id="chart-resumen",
                config={"displayModeBar": False},
                style={"height": 200},
            )],
            title="Perfil de operación",
            style={"marginTop": 12},
        ),

    ], style={"display": "flex", "flexDirection": "column", "gap": 0})
