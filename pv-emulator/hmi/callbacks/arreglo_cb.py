"""
hmi/callbacks/arreglo_cb.py
============================
Callbacks del Tab 1 — Arreglo PV.

Callbacks registrados (4):
    - labels de sliders     -> un callback por slider
    - load_module           -> carga params del catalogo al seleccionar modulo
    - toggle_custom_sliders -> muestra/oculta sliders en modo custom
    - update_arreglo        -> diagrama + tabla de params + limites
"""

from dash import Input, Output, State, html, ctx, no_update
from config.hardware        import C, V_MAX, I_MAX
from config.modules_catalog import CATALOG, CUSTOM_MODULE_KEY, get_params

_SLIDERS_MODULO = [
    ("sl-Voc",       " V"),
    ("sl-Isc",       " A"),
    ("sl-Vmp",       " V"),
    ("sl-Imp",       " A"),
    ("sl-betaVoc",   " V/C"),
    ("sl-alphaIsc",  " A/C"),
    ("sl-Ns-cells",  ""),
    ("sl-noct",      " C"),
]
_SLIDERS_ARREGLO = [
    ("sl-Ns",   ""),
    ("sl-Np",   ""),
    ("sl-tilt", ""),
]
_ALL_SLIDERS = _SLIDERS_MODULO + _SLIDERS_ARREGLO


def register(app):

    # 1. Labels de sliders
    for sl_id, unit in _ALL_SLIDERS:
        @app.callback(
            Output(f"val-{sl_id}", "children"),
            Input(sl_id, "value"),
            prevent_initial_call=False,
        )
        def _label(v, _unit=unit):
            if v is None:
                return f"--{_unit}"
            if isinstance(v, float) and v != 0 and abs(v) < 0.01:
                return f"{v:.4f}{_unit}"
            return f"{v}{_unit}"

    # 2. Cargar modulo del catalogo
    @app.callback(
        Output("sl-Voc",       "value"),
        Output("sl-Isc",       "value"),
        Output("sl-Vmp",       "value"),
        Output("sl-Imp",       "value"),
        Output("sl-betaVoc",   "value"),
        Output("sl-alphaIsc",  "value"),
        Output("sl-Ns-cells",  "value"),
        Output("sl-noct",      "value"),
        Output("module-pmax-badge", "children"),
        Input("dd-module", "value"),
        prevent_initial_call=False,
    )
    def load_module(module_key):
        if not module_key or module_key == CUSTOM_MODULE_KEY:
            return [no_update] * 8 + [
                html.Span("Ingresa los parametros del datasheet manualmente.",
                          style={"color": C["dim"]})
            ]
        d = get_params(module_key)
        # Calcular Pmax usando las claves nuevas del catalogo (Vmp, Imp)
        Pmax = round(d["Vmp"] * d["Imp"], 1)
        badge = html.Span(
            f"Pmax STC = {Pmax} W  |  Voc {d['Voc']} V  |  Isc {d['Isc']} A",
            style={"color": C["accentDark"], "fontWeight": 600},
        )
        return (d["Voc"], d["Isc"], d["Vmp"], d["Imp"],
                d["KV"], d["KI"], d["Ns"], d["noct"], badge)

    # 3. Mostrar/ocultar sliders custom
    @app.callback(
        Output("custom-module-sliders", "style"),
        Input("dd-module", "value"),
    )
    def toggle_custom_sliders(module_key):
        if module_key == CUSTOM_MODULE_KEY:
            return {"display": "block"}
        return {"display": "none"}

    # 4. Diagrama + tabla + limites
    @app.callback(
        Output("arreglo-diagram",     "children"),
        Output("limites-check",       "children"),
        Output("module-params-table", "children"),
        Input("dd-module",    "value"),
        Input("sl-Ns",        "value"),
        Input("sl-Np",        "value"),
        Input("sl-Voc",       "value"),
        Input("sl-Isc",       "value"),
        Input("sl-Vmp",       "value"),
        Input("sl-Imp",       "value"),
        Input("sl-betaVoc",   "value"),
        Input("sl-alphaIsc",  "value"),
        Input("sl-Ns-cells",  "value"),
        Input("sl-noct",      "value"),
    )
    def update_arreglo(module_key, Ns, Np, Voc, Isc, Vmp, Imp,
                       betaVoc, alphaIsc, Ns_cells, noct):
        Ns  = Ns  or 1
        Np  = Np  or 1
        Voc = Voc or 47.0
        Isc = Isc or 13.5
        Vmp = Vmp or 39.0
        Imp = Imp or 13.0

        # Diagrama
        cell_w = min(48, 200 // Ns)
        cell_h = min(28, 120 // Np)
        cells = [
            html.Div(
                f"{i // Ns + 1},{i % Ns + 1}",
                style={
                    "width": cell_w, "height": cell_h,
                    "background": f"linear-gradient(135deg, {C['accentLight']}, #d1fae5)",
                    "border": f"1.5px solid {C['accent']}44",
                    "borderRadius": 4,
                    "display": "flex", "alignItems": "center",
                    "justifyContent": "center",
                    "fontSize": 8, "color": C["accentDark"], "fontWeight": 600,
                }
            )
            for i in range(Ns * Np)
        ]
        diagram = html.Div([
            html.Div(f"{Ns}s x {Np}p = {Ns*Np} modulos",
                     style={"fontSize": 11, "color": C["dim"],
                            "fontWeight": 600, "marginBottom": 8}),
            html.Div(cells, style={
                "display": "grid",
                "gridTemplateColumns": f"repeat({Ns}, 1fr)",
                "gap": 4, "maxWidth": 240, "margin": "0 auto",
            }),
            html.Div([
                html.Span("V_oc = ", style={"fontSize": 11, "color": C["dim"]}),
                html.Span(f"{Voc*Ns:.1f} V",
                          style={"color": C["red"], "fontFamily": "monospace", "fontWeight": 700}),
                html.Span("   I_sc = ", style={"fontSize": 11, "color": C["dim"]}),
                html.Span(f"{Isc*Np:.1f} A",
                          style={"color": C["blue"], "fontFamily": "monospace", "fontWeight": 700}),
            ], style={"marginTop": 8, "textAlign": "center"}),
        ], style={"textAlign": "center", "padding": "12px 0"})

        # Tabla de parametros
        if module_key and module_key != CUSTOM_MODULE_KEY:
            d = get_params(module_key)
            # Calcular KI/KV absolutos via panel_from_datasheet para mostrar
            from models.panel_factory import panel_from_datasheet
            mp = panel_from_datasheet(
                Isc=d["Isc"], Voc=d["Voc"], Imp=d["Imp"], Vmp=d["Vmp"],
                KI=d["KI"], KV=d["KV"], Ns=d["Ns"], noct=d["noct"]
            )
            d_show = {"Voc": d["Voc"], "Isc": d["Isc"],
                      "Vmp": d["Vmp"], "Imp": d["Imp"],
                      "KV": round(mp.KV, 5), "KI": round(mp.KI, 6),
                      "Ns": d["Ns"], "noct": d["noct"]}
        else:
            d_show = {"Voc": Voc or 47.0, "Isc": Isc or 13.5,
                      "Vmp": Vmp or 39.0, "Imp": Imp or 13.0,
                      "KV": betaVoc or -0.13, "KI": alphaIsc or 0.0005,
                      "Ns": Ns_cells or 144, "noct": noct or 45}
            d = d_show

        Pmax_mod = round(d_show["Vmp"] * d_show["Imp"], 1)
        FF = round(Pmax_mod / max(d_show["Voc"] * d_show["Isc"], 0.001), 3)

        filas = [
            ("Voc STC",    f"{d_show['Voc']} V"),
            ("Isc STC",    f"{d_show['Isc']} A"),
            ("Vmp STC",    f"{d_show['Vmp']} V"),
            ("Imp STC",    f"{d_show['Imp']} A"),
            ("Pmax STC",   f"{Pmax_mod} W"),
            ("FF",         f"{FF}"),
            ("beta Voc",   f"{d_show['KV']} V/C"),
            ("alpha Isc",  f"{d_show['KI']} A/C"),
            ("Ns (celdas)",f"{d_show['Ns']}"),
            ("NOCT",       f"{d_show['noct']} C"),
        ]
        params_table = html.Table([
            html.Tbody([
                html.Tr([
                    html.Td(k, style={"fontSize": 11, "color": C["dim"],
                                      "paddingRight": 12, "paddingBottom": 4}),
                    html.Td(v, style={"fontSize": 11, "fontWeight": 700,
                                      "fontFamily": "monospace",
                                      "color": C["textMed"], "paddingBottom": 4}),
                ]) for k, v in filas
            ])
        ], style={"width": "100%", "borderCollapse": "collapse"})

        # Limites
        checks = []
        for val, lim, unit, lbl in [
            (Voc*Ns, V_MAX, "V", "Voltaje"),
            (Isc*Np, I_MAX, "A", "Corriente"),
        ]:
            ok = val <= lim
            checks.append(html.Div([
                html.Div(f"{lbl} max equipo",
                         style={"fontSize": 10, "color": C["dim"]}),
                html.Div(f"{lim}{unit}",
                         style={"fontSize": 18, "fontWeight": 900,
                                "fontFamily": "monospace",
                                "color": C["accent"] if ok else C["red"]}),
                html.Div(f"OK ({val:.1f}{unit})" if ok else f"CLIPPING ({val:.1f}{unit})",
                         style={"fontSize": 10, "fontWeight": 600,
                                "color": C["accentDark"] if ok else C["red"]}),
            ], style={
                "padding": 12, "borderRadius": 10,
                "background": C["accentLight"] if ok else C["redLight"],
                "border": f"1px solid {'#bbf7d0' if ok else '#fecaca'}",
            }))

        limites = html.Div([
            html.Div(checks, style={"display": "grid",
                                    "gridTemplateColumns": "1fr 1fr", "gap": 10}),
            html.Div("EA-PS 10060-170: 5000W · Autoranging · Dt min: 200ms",
                     style={"marginTop": 10, "padding": 10,
                            "background": C["accentBg"], "borderRadius": 8,
                            "fontSize": 10, "color": C["textMed"]}),
        ])

        return diagram, limites, params_table