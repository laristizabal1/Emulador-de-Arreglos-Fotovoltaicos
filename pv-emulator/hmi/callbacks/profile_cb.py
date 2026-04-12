"""
hmi/callbacks/profile_cb.py
============================
Callbacks del Tab 2 — Perfiles de consignas.

Callbacks registrados aquí (2):
    - update_profile  → calcula Vset/Iset/Pset y actualiza gráficas + stats
    - export_csv      → genera y descarga el CSV SeqLog
"""

import plotly.graph_objects as go
from dash import Input, Output, State, html, dcc, no_update

from config.hardware   import C, DT_MIN
from config.locations  import LOCATIONS
from models.simplified import SimplifiedModel
from models.base       import ModuleParams
from pipeline.profile  import build as build_profile, apply_strategy
from pipeline.seqlog   import to_csv_string
from hmi.layout.components import stat_box


# Mapa de nombre de modelo a clase — se expande cuando se añadan 1d/2d
_MODEL_MAP = {
    "simplified":   SimplifiedModel,
    # "single_diode": SingleDiodeModel,   # descomentar cuando esté listo
    # "two_diode":    TwoDiodeModel,
}


def _make_empty_fig(height: int = 180) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(height=height,
                      paper_bgcolor="white",
                      plot_bgcolor="white")
    return fig


def register(app):
    """
    Registra los callbacks de perfiles en la instancia `app` de Dash.
    Se llama desde app.py: profile_cb.register(app)
    """

    # ─── 1. Calcular perfil completo ─────────────────────────────────────────
    @app.callback(
        Output("store-profile",    "data"),
        Output("profile-stats",    "children"),
        Output("chart-vi",         "figure"),
        Output("chart-pt",         "figure"),
        Output("perfiles-warning", "children"),
        Input("store-nasa",    "data"),
        Input("sl-Ns",         "value"),
        Input("sl-Np",         "value"),
        Input("sl-Voc",        "value"),
        Input("sl-Isc",        "value"),
        Input("sl-betaVoc",    "value"),
        Input("sl-alphaIsc",   "value"),
        Input("sl-noct",       "value"),
        Input("sl-tilt",       "value"),
        Input("dd-model",      "value"),
        Input("dd-strategy",   "value"),
        Input("inp-dt",        "value"),
    )
    def update_profile(nasa_data, Ns, Np, Voc, Isc,
                       beta, alpha, noct, tilt,
                       model_key, strategy, dt):
        """
        Punto central del pipeline de emulación en la HMI.

        Flujo:
          1. Instancia el modelo PV seleccionado con los parámetros del slider
          2. Llama a pipeline/profile.build() → lista de dicts con V_set, I_set, P_set
          3. Aplica la estrategia (full / day / average)
          4. Calcula métricas de resumen (peak_P, total_E, lab_dur)
          5. Construye las dos figuras Plotly (V/I y P/Tcell)
          6. Devuelve todo al store y a los componentes de la tab

        Se dispara ante cualquier cambio de slider, modelo, estrategia o datos NASA.
        """
        # Sin datos ambientales → aviso y figuras vacías
        if not nasa_data:
            warn = html.Div(
                "⚠  Descarga datos ambientales en 'Ubicación & Datos' primero.",
                style={"padding": "16px 20px",
                       "background": C["redLight"],
                       "border": "1px solid #fecaca",
                       "borderRadius": 10,
                       "color": C["red"],
                       "marginBottom": 12,
                       "fontWeight": 600,
                       "fontSize": 13},
            )
            return no_update, [], _make_empty_fig(190), _make_empty_fig(170), warn

        # ── Construir parámetros del módulo desde los sliders ────────────────
        params = ModuleParams(
            Isc_n = Isc  or 13.5,
            Voc_n = Voc  or 49.8,
            Imp_n = (Isc or 13.5) * 0.99,    # aproximación para simplified
            Vmp_n = (Voc or 49.8) * 0.83,
            KI    = alpha or 0.0005,
            KV    = beta  or -0.13,
            Ns    = 144,                       # celdas por módulo (fijo por ahora)
            noct  = noct  or 45.0,
        )

        # ── Instanciar modelo y ajustar a STC ────────────────────────────────
        ModelClass = _MODEL_MAP.get(model_key, SimplifiedModel)
        model = ModelClass(params)
        model.fit()

        # ── Pipeline: datos ambientales → consignas V/I ───────────────────────
        full_profile = build_profile(
            nasa_data,
            model    = model,
            Ns_arr   = Ns   or 1,
            Np_arr   = Np   or 1,
            tilt     = tilt or 10.0,
        )
        profile = apply_strategy(full_profile, strategy or "day")
        dt_ms   = max(dt or 1000, DT_MIN)

        if not profile:
            return [], [], _make_empty_fig(190), _make_empty_fig(170), html.Div()

        # ── Métricas de resumen ───────────────────────────────────────────────
        peak_P  = max(d["P_set"] for d in profile)
        peak_V  = max(d["V_set"] for d in profile)
        peak_I  = max(d["I_set"] for d in profile)
        total_E = sum(d["P_set"] for d in profile) / 1000.0
        lab_s   = len(profile) * dt_ms / 1000.0

        stats = [
            stat_box("Potencia pico",  f"{peak_P:.0f}",  "W",   C["accent"]),
            stat_box("Voltaje pico",   f"{peak_V:.1f}",  "V",   C["red"]),
            stat_box("Corriente pico", f"{peak_I:.1f}",  "A",   C["blue"]),
            stat_box("Energía",        f"{total_E:.2f}", "kWh", C["accentDark"]),
            stat_box("Duración lab",   f"{lab_s:.1f}",   "seg", C["purple"]),
        ]

        labels  = [d["label"] for d in profile]
        n_ticks = max(1, len(profile) // 24)

        # ── Figura V_set · I_set ──────────────────────────────────────────────
        fig_vi = go.Figure()
        fig_vi.add_trace(go.Scatter(
            x=labels, y=[d["V_set"] for d in profile],
            name="V (V)",
            line=dict(color=C["red"], width=2, shape="hv"),
        ))
        fig_vi.add_trace(go.Scatter(
            x=labels, y=[d["I_set"] for d in profile],
            name="I (A)",
            line=dict(color=C["blue"], width=2, shape="hv"),
            yaxis="y2",
        ))
        fig_vi.update_layout(
            height=190,
            margin=dict(t=10, b=20, l=30, r=40),
            paper_bgcolor="white", plot_bgcolor="white",
            legend=dict(font=dict(size=9)),
            xaxis=dict(tickfont=dict(size=8), dtick=n_ticks),
            yaxis=dict(tickfont=dict(size=9), range=[0, 65]),
            yaxis2=dict(overlaying="y", side="right", tickfont=dict(size=9)),
        )

        # ── Figura P_set · Tcell ──────────────────────────────────────────────
        fig_pt = go.Figure()
        fig_pt.add_trace(go.Scatter(
            x=labels, y=[d["P_set"] for d in profile],
            name="P (W)",
            fill="tozeroy",
            line=dict(color=C["accent"], width=2),
            fillcolor="rgba(22,163,74,0.12)",
        ))
        fig_pt.add_trace(go.Scatter(
            x=labels, y=[d["Tcell"] for d in profile],
            name="T_cell (°C)",
            line=dict(color=C["cyan"], width=1.5),
            yaxis="y2",
        ))
        fig_pt.update_layout(
            height=170,
            margin=dict(t=10, b=20, l=30, r=40),
            paper_bgcolor="white", plot_bgcolor="white",
            legend=dict(font=dict(size=9)),
            xaxis=dict(tickfont=dict(size=8), dtick=n_ticks),
            yaxis=dict(tickfont=dict(size=9)),
            yaxis2=dict(overlaying="y", side="right", tickfont=dict(size=9)),
        )

        return profile, stats, fig_vi, fig_pt, html.Div()

    # ─── 2. Exportar CSV SeqLog ───────────────────────────────────────────────
    @app.callback(
        Output("download-csv", "data"),
        Input("btn-export-csv", "n_clicks"),
        State("store-profile", "data"),
        State("inp-dt",        "value"),
        prevent_initial_call=True,
    )
    def export_csv(_n, profile, dt):
        """
        Genera el CSV compatible con SeqLog de EA Power Control
        y lo entrega al componente dcc.Download para descarga inmediata.

        Formato SeqLog (separador ;):
            Time [ms] ; Voltage [V] ; Current [A] ; Power [W] ; DC Output
        """
        if not profile:
            return no_update

        csv_str = to_csv_string(profile, dt or 1000)
        return {
            "content":  csv_str,
            "filename": "perfil_seqlog.csv",
            "type":     "text/csv",
        }
