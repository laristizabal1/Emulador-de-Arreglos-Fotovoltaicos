# hmi/layout/components.py
from dash import html
from config.hardware import C

def card(children, title: str = None, style: dict = None) -> html.Div:
    """Contenedor estilizado con borde y título opcional."""
    s = {
        "background": C["white"],
        "border":     f'1px solid {C["border"]}',
        "borderRadius": 12,
        "padding":    "16px 20px",
    }
    if style:
        s.update(style)
    inner = []
    if title:
        inner.append(html.Div([
            html.Div(style={"width": 4, "height": 14,
                            "background": C["accent"],
                            "borderRadius": 2,
                            "display": "inline-block",
                            "marginRight": 8,
                            "verticalAlign": "middle"}),
            html.Span(title, style={"fontSize": 10, "fontWeight": 800,
                                    "textTransform": "uppercase",
                                    "letterSpacing": 1.6,
                                    "color": C["accentDark"],
                                    "verticalAlign": "middle"}),
        ], style={"marginBottom": 12}))
    inner.extend(children if isinstance(children, list) else [children])
    return html.Div(inner, style=s)


def stat_box(label: str, value: str, unit: str,
             color: str = None, bg: str = None) -> html.Div:
    """Tarjeta numérica para métricas: valor grande + etiqueta + unidad."""
    return html.Div([
        html.Div(value, style={"fontSize": 26, "fontWeight": 900,
                               "color": color or C["text"],
                               "fontFamily": "monospace",
                               "lineHeight": 1.1}),
        html.Div(unit,  style={"fontSize": 10, "color": C["dim"], "marginTop": 2}),
        html.Div(label, style={"fontSize": 9,  "color": C["dim"],
                               "textTransform": "uppercase", "letterSpacing": 1}),
    ], style={"textAlign": "center", "padding": "8px 4px",
              "background": bg or C["white"],
              "border":     f'1px solid {C["border"]}',
              "borderRadius": 12})