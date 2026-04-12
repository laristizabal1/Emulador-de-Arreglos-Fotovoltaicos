"""
hmi/callbacks/arreglo_cb.py
============================
Callbacks del Tab 1 — Arreglo PV.

Callbacks registrados aquí (2):
    - update_slider_labels  → actualiza el valor numérico de cada slider (×8)
    - update_arreglo        → redibuja el diagrama de módulos y verifica límites
"""

from dash import Input, Output, html
from config.hardware import C, V_MAX, I_MAX


# Mapa: id del slider → unidad que se muestra al lado del valor
_SLIDERS = [
    ("sl-Ns",       ""),
    ("sl-Np",       ""),
    ("sl-Voc",      " V"),
    ("sl-Isc",      " A"),
    ("sl-betaVoc",  " V/°C"),
    ("sl-alphaIsc", " A/°C"),
    ("sl-noct",     " °C"),
    ("sl-tilt",     "°"),
]


def register(app):
    """
    Registra los callbacks de arreglo en la instancia `app` de Dash.
    Se llama desde app.py: arreglo_cb.register(app)
    """

    # ─── 1. Labels de sliders (un callback por slider) ────────────────────────
    for sl_id, unit in _SLIDERS:

        @app.callback(
            Output(f"val-{sl_id}", "children"),
            Input(sl_id, "value"),
            prevent_initial_call=False,
        )
        def _label(v, _unit=unit):
            """
            Muestra el valor actual del slider con la unidad correspondiente.
            Para valores muy pequeños (ej. alphaIsc = 0.0005) usa 4 decimales.
            """
            if isinstance(v, float) and v != 0 and abs(v) < 0.01:
                return f"{v:.4f}{_unit}"
            return f"{v}{_unit}"

    # ─── 2. Diagrama del arreglo + verificación de límites ───────────────────
    @app.callback(
        Output("arreglo-diagram", "children"),
        Output("limites-check",   "children"),
        Input("sl-Ns",  "value"),
        Input("sl-Np",  "value"),
        Input("sl-Voc", "value"),
        Input("sl-Isc", "value"),
    )
    def update_arreglo(Ns, Np, Voc, Isc):
        """
        Se dispara cada vez que cambia Ns, Np, Voc o Isc.

        Diagrama:
            Grilla de celdas Ns×Np con etiqueta fila,columna.
            Escala el tamaño de cada celda para que quepan en 240px.

        Límites:
            Compara Voc*Ns contra V_MAX y Isc*Np contra I_MAX.
            Verde = OK, Rojo = clipping activo.
        """
        Ns  = Ns  or 1
        Np  = Np  or 1
        Voc = Voc or 0.0
        Isc = Isc or 0.0

        # ── Diagrama ─────────────────────────────────────────────────────────
        cell_w = min(48, 200 // Ns)
        cell_h = min(28, 120 // Np)

        cells = [
            html.Div(
                f"{i // Ns + 1},{i % Ns + 1}",
                style={
                    "width":           cell_w,
                    "height":          cell_h,
                    "background":      f"linear-gradient(135deg, {C['accentLight']}, #d1fae5)",
                    "border":          f"1.5px solid {C['accent']}44",
                    "borderRadius":    4,
                    "display":         "flex",
                    "alignItems":      "center",
                    "justifyContent":  "center",
                    "fontSize":        8,
                    "color":           C["accentDark"],
                    "fontWeight":      600,
                },
            )
            for i in range(Ns * Np)
        ]

        diagram = html.Div([
            html.Div(
                f"{Ns}s × {Np}p = {Ns * Np} módulos",
                style={"fontSize": 11, "color": C["dim"],
                       "fontWeight": 600, "marginBottom": 8},
            ),
            html.Div(
                cells,
                style={
                    "display":             "grid",
                    "gridTemplateColumns": f"repeat({Ns}, 1fr)",
                    "gap":                 4,
                    "maxWidth":            240,
                    "margin":              "0 auto",
                },
            ),
            html.Div([
                html.Span("V_oc = ", style={"fontSize": 11, "color": C["dim"]}),
                html.Span(f"{Voc * Ns:.1f} V",
                          style={"color": C["red"], "fontFamily": "monospace",
                                 "fontWeight": 700}),
                html.Span("   I_sc = ", style={"fontSize": 11, "color": C["dim"]}),
                html.Span(f"{Isc * Np:.1f} A",
                          style={"color": C["blue"], "fontFamily": "monospace",
                                 "fontWeight": 700}),
            ], style={"marginTop": 8, "textAlign": "center"}),
        ], style={"textAlign": "center", "padding": "12px 0"})

        # ── Verificación de límites ───────────────────────────────────────────
        checks = []
        for val, lim, unit, label in [
            (Voc * Ns, V_MAX, "V", "Voltaje"),
            (Isc * Np, I_MAX, "A", "Corriente"),
        ]:
            ok = val <= lim
            checks.append(html.Div([
                html.Div(f"{label} máx equipo",
                         style={"fontSize": 10, "color": C["dim"]}),
                html.Div(f"{lim}{unit}",
                         style={"fontSize": 18, "fontWeight": 900,
                                "fontFamily": "monospace",
                                "color": C["accent"] if ok else C["red"]}),
                html.Div(
                    f"{'✓ OK' if ok else '⚠ CLIPPING'} ({val:.1f}{unit})",
                    style={"fontSize": 10, "fontWeight": 600,
                           "color": C["accentDark"] if ok else C["red"]},
                ),
            ], style={
                "padding":      12,
                "borderRadius": 10,
                "background":   C["accentLight"] if ok else C["redLight"],
                "border":       f"1px solid {'#bbf7d0' if ok else '#fecaca'}",
            }))

        limites = html.Div([
            html.Div(checks,
                     style={"display": "grid",
                            "gridTemplateColumns": "1fr 1fr",
                            "gap": 10}),
            html.Div(
                "EA-PS 10060-170: 5000 W · Autoranging · Δt mín: 200 ms",
                style={"marginTop": 10, "padding": 10,
                       "background": C["accentBg"],
                       "borderRadius": 8,
                       "fontSize": 10, "color": C["textMed"]},
            ),
        ])

        return diagram, limites
