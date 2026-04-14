"""
hmi/callbacks/profile_cb.py
============================
Callbacks del Tab 2 — Perfiles de consignas.

Callbacks registrados (2):
    - update_profile  -> calcula Vset/Iset/Pset con el modelo y modulo elegidos
    - export_csv      -> genera y descarga el CSV SeqLog
"""

import plotly.graph_objects as go
from dash import Input, Output, State, html, no_update

from config.hardware        import C, DT_MIN
from config.modules_catalog import CUSTOM_MODULE_KEY, get_params, to_module_params
from models.simplified      import SimplifiedModel
from models.single_diode    import SingleDiodeModel
from models.two_diode       import TwoDiodeModel
from models.base            import ModuleParams
from models.panel_factory   import panel_from_datasheet
from pipeline.profile       import build as build_profile, apply_strategy
from pipeline.seqlog        import to_csv_string
from hmi.layout.components  import stat_box

_MODEL_MAP = {
    "simplified":   SimplifiedModel,
    "single_diode": SingleDiodeModel,
    "two_diode":    TwoDiodeModel,
}


def _make_empty_fig(height=180):
    fig = go.Figure()
    fig.update_layout(height=height, paper_bgcolor="white",
                      plot_bgcolor="white")
    return fig


def register(app):

    @app.callback(
        Output("store-profile",    "data"),
        Output("profile-stats",    "children"),
        Output("chart-vi",         "figure"),
        Output("chart-pt",         "figure"),
        Output("perfiles-warning", "children"),
        Input("store-nasa",    "data"),
        Input("dd-module",     "value"),
        Input("sl-Ns",         "value"),
        Input("sl-Np",         "value"),
        Input("sl-Voc",        "value"),
        Input("sl-Isc",        "value"),
        Input("sl-Vmp",        "value"),
        Input("sl-Imp",        "value"),
        Input("sl-betaVoc",    "value"),
        Input("sl-alphaIsc",   "value"),
        Input("sl-Ns-cells",   "value"),
        Input("sl-noct",       "value"),
        Input("sl-tilt",       "value"),
        Input("dd-model",      "value"),
        Input("dd-strategy",   "value"),
        Input("inp-dt",        "value"),
    )
    def update_profile(nasa_data, module_key, Ns, Np,
                       Voc, Isc, Vmp, Imp, beta, alpha, Ns_cells, noct,
                       tilt, model_key, strategy, dt):

        if not nasa_data:
            warn = html.Div(
                "Descarga datos ambientales en Ubicacion & Datos primero.",
                style={"padding": "16px 20px", "background": C["redLight"],
                       "border": "1px solid #fecaca", "borderRadius": 10,
                       "color": C["red"], "marginBottom": 12,
                       "fontWeight": 600, "fontSize": 13},
            )
            return no_update, [], _make_empty_fig(190), _make_empty_fig(170), warn

        # ── Construir ModuleParams ───────────────────────────────────────────
        # Catalogo: usa panel_from_datasheet con auto-deteccion de convencion
        # Custom: usa los sliders directamente (ya en valores absolutos)
        if module_key and module_key != CUSTOM_MODULE_KEY:
            params = to_module_params(module_key)
        else:
            # Modo custom: los sliders siempre estan en valores absolutos
            params = panel_from_datasheet(
                Isc  = Isc   or 13.5,
                Voc  = Voc   or 47.0,
                Imp  = Imp   or 13.0,
                Vmp  = Vmp   or 39.0,
                KI   = alpha or 0.0005,
                KV   = beta  or -0.13,
                Ns   = int(Ns_cells or 144),
                noct = noct  or 45.0,
                coefficients_in_percent=False,  # sliders siempre absolutos
            )

        # ── Instanciar y ajustar modelo ──────────────────────────────────────
        ModelClass = _MODEL_MAP.get(model_key or "simplified", SimplifiedModel)
        model = ModelClass(params)
        model.fit()

        # ── Pipeline ─────────────────────────────────────────────────────────
        full_profile = build_profile(
            nasa_data, model=model,
            Ns_arr=Ns or 1, Np_arr=Np or 1,
            tilt=tilt or 10.0,
        )
        profile = apply_strategy(full_profile, strategy or "day")
        dt_ms   = max(dt or 1000, DT_MIN)

        if not profile:
            return [], [], _make_empty_fig(190), _make_empty_fig(170), html.Div()

        # ── Metricas ─────────────────────────────────────────────────────────
        peak_P  = max(d["P_set"] for d in profile)
        peak_V  = max(d["V_set"] for d in profile)
        peak_I  = max(d["I_set"] for d in profile)
        total_E = sum(d["P_set"] for d in profile) / 1000.0
        lab_s   = len(profile) * dt_ms / 1000.0

        stats = [
            stat_box("Potencia pico",  f"{peak_P:.0f}",  "W",   C["accent"]),
            stat_box("Voltaje pico",   f"{peak_V:.1f}",  "V",   C["red"]),
            stat_box("Corriente pico", f"{peak_I:.1f}",  "A",   C["blue"]),
            stat_box("Energia",        f"{total_E:.2f}", "kWh", C["accentDark"]),
            stat_box("Duracion lab",   f"{lab_s:.1f}",   "seg", C["purple"]),
        ]

        labels  = [d["label"] for d in profile]
        n_ticks = max(1, len(profile) // 24)

        fig_vi = go.Figure()
        fig_vi.add_trace(go.Scatter(
            x=labels, y=[d["V_set"] for d in profile],
            name="V (V)", line=dict(color=C["red"], width=2, shape="hv")))
        fig_vi.add_trace(go.Scatter(
            x=labels, y=[d["I_set"] for d in profile],
            name="I (A)", line=dict(color=C["blue"], width=2, shape="hv"),
            yaxis="y2"))
        fig_vi.update_layout(
            height=190, margin=dict(t=10, b=20, l=30, r=40),
            paper_bgcolor="white", plot_bgcolor="white",
            legend=dict(font=dict(size=9)),
            xaxis=dict(tickfont=dict(size=8), dtick=n_ticks),
            yaxis=dict(tickfont=dict(size=9), range=[0, 65]),
            yaxis2=dict(overlaying="y", side="right", tickfont=dict(size=9)))

        fig_pt = go.Figure()
        fig_pt.add_trace(go.Scatter(
            x=labels, y=[d["P_set"] for d in profile],
            name="P (W)", fill="tozeroy",
            line=dict(color=C["accent"], width=2),
            fillcolor="rgba(22,163,74,0.12)"))
        fig_pt.add_trace(go.Scatter(
            x=labels, y=[d["Tcell"] for d in profile],
            name="T_cell (C)", line=dict(color=C["cyan"], width=1.5),
            yaxis="y2"))
        fig_pt.update_layout(
            height=170, margin=dict(t=10, b=20, l=30, r=40),
            paper_bgcolor="white", plot_bgcolor="white",
            legend=dict(font=dict(size=9)),
            xaxis=dict(tickfont=dict(size=8), dtick=n_ticks),
            yaxis=dict(tickfont=dict(size=9)),
            yaxis2=dict(overlaying="y", side="right", tickfont=dict(size=9)))

        return profile, stats, fig_vi, fig_pt, html.Div()

    @app.callback(
        Output("download-csv", "data"),
        Input("btn-export-csv", "n_clicks"),
        State("store-profile", "data"),
        State("inp-dt",        "value"),
        prevent_initial_call=True,
    )
    def export_csv(_n, profile, dt):
        if not profile:
            return no_update
        return {"content": to_csv_string(profile, dt or 1000),
                "filename": "perfil_seqlog.csv", "type": "text/csv"}