"""
hmi/callbacks/nasa_cb.py
========================
Callbacks relacionados con la selección de ubicación y la descarga
de datos ambientales desde NASA POWER.

Callbacks registrados aquí (4):
    - set_location        → guarda el índice de ciudad seleccionada
    - toggle_custom       → muestra / oculta lat/lon personalizados
    - fetch_nasa_cb       → descarga y parsea datos de NASA POWER
    - update_irradiance_charts → dibuja gráficas GHI/DNI/DHI y Tamb
"""

import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, html, dcc, ctx, no_update

# Importaciones internas — se resuelven correctamente porque app.py
# está en la raíz del proyecto y Python lo encuentra en sys.path
from config.locations  import LOCATIONS
from config.hardware   import C
from pipeline.nasa_power import fetch as nasa_fetch
from hmi.layout.components import card


def register(app):
    """
    Registra los 4 callbacks de este módulo en la instancia `app` de Dash.
    Se llama desde app.py: nasa_cb.register(app)
    """

    # ─── 1. Guardar índice de ubicación ──────────────────────────────────────
    @app.callback(
        Output("store-loc-idx", "data"),
        [Input({"type": "btn-loc", "index": i}, "n_clicks") for i in range(9)],
        prevent_initial_call=True,
    )
    def set_location(*_args):
        """
        Cada botón de ciudad tiene id {"type":"btn-loc","index":i}.
        ctx.triggered_id devuelve el dict del botón presionado,
        del cual extraemos el índice.
        """
        triggered = ctx.triggered_id
        if triggered and "index" in triggered:
            return triggered["index"]
        return 0

    # ─── 2. Mostrar / ocultar coordenadas personalizadas ─────────────────────
    @app.callback(
        Output("custom-coords-container", "style"),
        Input("store-loc-idx", "data"),
    )
    def toggle_custom(idx):
        """
        Solo muestra los inputs de lat/lon cuando el usuario selecciona
        "Personalizado" (índice 8 en LOCATIONS).
        """
        return {"display": "block"} if idx == 8 else {"display": "none"}

    # ─── 3. Descarga datos NASA POWER ────────────────────────────────────────
    @app.callback(
        Output("store-nasa",  "data"),
        Output("nasa-status", "children"),
        Input("btn-fetch-nasa", "n_clicks"),
        State("store-loc-idx", "data"),
        State("inp-lat",   "value"),
        State("inp-lon",   "value"),
        State("inp-start", "value"),
        State("inp-end",   "value"),
        prevent_initial_call=True,
        running=[(Output("btn-fetch-nasa", "disabled"), True, False)],
    )
    def fetch_nasa_cb(_n, loc_idx, lat, lon, start, end):
        """
        Llama a pipeline/nasa_power.fetch() con las coordenadas
        y fechas seleccionadas. Guarda el resultado en store-nasa.

        running=[(btn, True, False)] deshabilita el botón mientras
        carga y lo reactiva al terminar — sin estado adicional.
        """
        loc     = LOCATIONS[loc_idx or 0]
        use_lat = lat if loc_idx == 8 else loc["lat"]
        use_lon = lon if loc_idx == 8 else loc["lon"]

        try:
            data  = nasa_fetch(use_lat, use_lon, start, end,
                               cache_dir="data/nasa_cache")
            label = (f"✓  {len(data)} registros horarios  "
                     f"({start[:4]}-{start[4:6]}-{start[6:]} → "
                     f"{end[:4]}-{end[4:6]}-{end[6:]})")
            badge = html.Div(label,
                             style={"padding": "8px 12px",
                                    "background": C["accentLight"],
                                    "border": "1px solid #bbf7d0",
                                    "borderRadius": 8,
                                    "color": C["accentDark"],
                                    "fontWeight": 600})
            return data, badge

        except Exception as exc:
            badge = html.Div(f"❌  {exc}",
                             style={"padding": "8px 12px",
                                    "background": C["redLight"],
                                    "border": "1px solid #fecaca",
                                    "borderRadius": 8,
                                    "color": C["red"]})
            return no_update, badge

    # ─── 4. Gráficas de irradiancia y temperatura ─────────────────────────────
    @app.callback(
        Output("irradiance-chart-container", "children"),
        Input("store-nasa", "data"),
        State("store-loc-idx", "data"),
    )
    def update_irradiance_charts(data, loc_idx):
        """
        Dibuja dos gráficas apiladas:
          - Área: GHI, DNI, DHI en W/m²
          - Líneas: T2M (°C) y velocidad de viento (m/s) con eje Y derecho
        Se dispara automáticamente cada vez que store-nasa cambia.
        """
        if not data:
            return html.Div(
                "Selecciona una ubicación y descarga datos para ver las gráficas.",
                style={"textAlign": "center", "color": C["dim"],
                       "padding": "80px 0", "fontSize": 13},
            )

        df       = pd.DataFrame(data)
        loc_name = LOCATIONS[loc_idx or 0]["name"]
        n_ticks  = max(1, len(df) // 20)

        # ── Gráfica de irradiancia ──────────────────────────────────────────
        fig_irr = go.Figure()
        fig_irr.add_trace(go.Scatter(
            x=df["label"], y=df["ghi"],
            fill="tozeroy", name="GHI (W/m²)",
            line=dict(color=C["accent"], width=2),
        ))
        fig_irr.add_trace(go.Scatter(
            x=df["label"], y=df["dni"],
            fill="tozeroy", name="DNI",
            line=dict(color=C["orange"], width=1.5),
            fillcolor="rgba(234,88,12,0.08)",
        ))
        fig_irr.add_trace(go.Scatter(
            x=df["label"], y=df["dhi"],
            fill="tozeroy", name="DHI",
            line=dict(color=C["blue"], width=1),
            fillcolor="rgba(37,99,235,0.06)",
        ))
        fig_irr.update_layout(
            height=210,
            margin=dict(t=30, b=20, l=30, r=10),
            paper_bgcolor="white", plot_bgcolor="white",
            legend=dict(font=dict(size=9)),
            xaxis=dict(tickfont=dict(size=8), dtick=n_ticks),
            yaxis=dict(tickfont=dict(size=9)),
        )

        # ── Gráfica de temperatura y viento ────────────────────────────────
        fig_t = go.Figure()
        fig_t.add_trace(go.Scatter(
            x=df["label"], y=df["T2M"],
            name="T2M (°C)",
            line=dict(color=C["cyan"], width=1.5),
        ))
        fig_t.add_trace(go.Scatter(
            x=df["label"], y=df["WS"],
            name="Viento (m/s)",
            line=dict(color=C["purple"], width=1),
            yaxis="y2",
        ))
        fig_t.update_layout(
            height=150,
            margin=dict(t=10, b=20, l=30, r=30),
            paper_bgcolor="white", plot_bgcolor="white",
            legend=dict(font=dict(size=9)),
            xaxis=dict(tickfont=dict(size=8), dtick=n_ticks),
            yaxis=dict(tickfont=dict(size=9)),
            yaxis2=dict(overlaying="y", side="right", tickfont=dict(size=9)),
        )

        return [
            card([dcc.Graph(figure=fig_irr, config={"displayModeBar": False})],
                 title=f"Irradiancia — {loc_name}"),
            card([dcc.Graph(figure=fig_t, config={"displayModeBar": False})],
                 title="Temperatura y viento",
                 style={"marginTop": 12}),
        ]
