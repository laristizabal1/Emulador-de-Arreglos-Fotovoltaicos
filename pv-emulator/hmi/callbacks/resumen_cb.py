"""
hmi/callbacks/resumen_cb.py
============================
Callbacks del Tab 4 (Resumen) y del header superior de la HMI.

Callbacks registrados aquí (2):
    - update_resumen  → stats finales, tabla de configuración y gráfica de operación
    - update_header   → barra superior con ubicación, estado NASA y config del arreglo
"""

import plotly.graph_objects as go
from dash import Input, Output, State, html

from config.hardware  import C, DT_MIN
from config.locations import LOCATIONS
from hmi.layout.components import stat_box


def register(app):
    """
    Registra los 2 callbacks de resumen en la instancia `app` de Dash.
    Se llama desde app.py: resumen_cb.register(app)
    """

    # ─── 1. Tab Resumen ───────────────────────────────────────────────────────
    @app.callback(
        Output("resumen-stats",  "children"),
        Output("resumen-config", "children"),
        Output("chart-resumen",  "figure"),
        Input("store-profile",  "data"),
        State("store-loc-idx",  "data"),
        State("sl-Ns",          "value"),
        State("sl-Np",          "value"),
        State("sl-Voc",         "value"),
        State("sl-Isc",         "value"),
        State("sl-noct",        "value"),
        State("sl-tilt",        "value"),
        State("dd-model",       "value"),
        State("dd-strategy",    "value"),
        State("inp-dt",         "value"),
        State("inp-start",      "value"),
        State("inp-end",        "value"),
    )
    def update_resumen(profile, loc_idx, Ns, Np, Voc, Isc,
                       noct, tilt, model, strategy, dt, start, end):
        """
        Se dispara cada vez que el perfil cambia (cualquier slider o descarga nueva).

        Devuelve:
          - resumen-stats : 4 tarjetas (potencia pico, energía, módulos, duración)
          - resumen-config: tabla de configuración completa en 4 columnas
          - chart-resumen : gráfica P_set y V_set superpuestas con eje Y dual
        """
        if not profile:
            return (
                [],
                html.Div("Sin datos. Completa los pasos anteriores.",
                         style={"color": C["dim"], "fontSize": 13, "padding": 20}),
                go.Figure(),
            )

        # ── Métricas ──────────────────────────────────────────────────────────
        Ns      = Ns  or 1
        Np      = Np  or 1
        dt_ms   = max(dt or 1000, DT_MIN)
        peak_P  = max(d["P_set"] for d in profile)
        total_E = sum(d["P_set"] for d in profile) / 1000.0
        lab_s   = len(profile) * dt_ms / 1000.0
        loc     = LOCATIONS[loc_idx or 0]

        stats = [
            stat_box("Potencia pico", f"{peak_P:.0f}",       "W",   C["accent"]),
            stat_box("Energía",       f"{total_E:.2f}",      "kWh", C["accentDark"]),
            stat_box("Módulos",       f"{Ns * Np}",
                                      f"{Ns}s × {Np}p",      C["blue"]),
            stat_box("Duración lab",  f"{lab_s:.0f}",        "seg", C["purple"]),
        ]

        # ── Tabla de configuración ────────────────────────────────────────────
        s_fmt = (f"{start[:4]}-{start[4:6]}-{start[6:]}"
                 if start and len(start) == 8 else start or "—")
        e_fmt = (f"{end[:4]}-{end[4:6]}-{end[6:]}"
                 if end and len(end) == 8 else end or "—")

        config_sections = [
            ("Ubicación", [
                loc["name"],
                f"{loc['lat']}°, {loc['lon']}°",
                f"{s_fmt} → {e_fmt}",
                "Fuente: NASA POWER",
            ]),
            ("Arreglo PV", [
                f"{Ns}s × {Np}p  ({Ns * Np} módulos)",
                f"Voc: {Voc} V · Isc: {Isc} A",
                f"NOCT: {noct} °C · Tilt: {tilt}°",
                f"Modelo: {model or 'simplified'}",
            ]),
            ("Emulación", [
                f"Estrategia: {strategy or 'day'}",
                f"{dt_ms} ms/paso",
                f"{len(profile)} pasos",
                f"Δt mín: {DT_MIN} ms",
            ]),
            ("Equipo", [
                "EA-PS 10060-170",
                "60 V / 170 A / 5 kW",
                "SCPI (ASCII) · USB/COM",
                "OVP / OCP / OPP / OT",
            ]),
        ]

        cfg_div = html.Div([
            html.Div([
                html.Div(
                    section_title,
                    style={
                        "fontWeight":      800,
                        "color":           C["accentDark"],
                        "fontSize":        10,
                        "textTransform":   "uppercase",
                        "letterSpacing":   1.2,
                        "marginBottom":    8,
                    },
                ),
                html.Div([
                    html.Div(
                        line,
                        style={"color": C["textMed"], "lineHeight": 1.8, "fontSize": 11},
                    )
                    for line in lines
                ]),
            ])
            for section_title, lines in config_sections
        ], style={
            "display":             "grid",
            "gridTemplateColumns": "repeat(4, 1fr)",
            "gap":                 20,
        })

        # ── Gráfica de operación ──────────────────────────────────────────────
        labels  = [d["label"] for d in profile]
        n_ticks = max(1, len(profile) // 20)

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=labels,
            y=[d["P_set"] for d in profile],
            fill="tozeroy",
            name="P (W)",
            line=dict(color=C["accent"], width=2),
            fillcolor="rgba(22,163,74,0.10)",
        ))
        fig.add_trace(go.Scatter(
            x=labels,
            y=[d["V_set"] for d in profile],
            name="V (V)",
            line=dict(color=C["red"], width=1.5, shape="hv"),
            yaxis="y2",
        ))
        fig.update_layout(
            height=190,
            margin=dict(t=10, b=20, l=30, r=40),
            paper_bgcolor="white",
            plot_bgcolor="white",
            legend=dict(font=dict(size=9)),
            xaxis=dict(tickfont=dict(size=8), dtick=n_ticks),
            yaxis=dict(tickfont=dict(size=9)),
            yaxis2=dict(overlaying="y", side="right", tickfont=dict(size=9)),
        )

        return stats, cfg_div, fig

    # ─── 2. Header superior ───────────────────────────────────────────────────
    @app.callback(
        Output("header-live", "children"),
        Input("store-nasa",    "data"),
        Input("store-loc-idx", "data"),
        State("sl-Ns", "value"),
        State("sl-Np", "value"),
    )
    def update_header(nasa_data, loc_idx, Ns, Np):
        """
        Actualiza la barra de estado en el header cada vez que:
          - Cambia la ubicación seleccionada
          - Se descargan nuevos datos de NASA POWER

        Muestra: nombre de ciudad · configuración Ns/Np · badge NASA ✓ Nh
        """
        loc = LOCATIONS[loc_idx or 0]
        Ns  = Ns or 1
        Np  = Np or 1

        loc_badge = html.Div(
            f"📍 {loc['name']} · {Ns}s{Np}p",
            style={"fontSize": 10, "color": "rgba(255,255,255,0.7)"},
        )

        nasa_badge = html.Div()   # vacío si no hay datos
        if nasa_data:
            nasa_badge = html.Div(
                f"NASA ✓  {len(nasa_data)} h",
                style={
                    "fontSize":   9,
                    "padding":    "3px 10px",
                    "background": "rgba(255,255,255,0.15)",
                    "borderRadius": 6,
                    "color":      "#bbf7d0",
                    "fontWeight": 600,
                },
            )

        return [loc_badge, nasa_badge]
