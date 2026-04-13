"""
hmi/layout/components.py
========================
Componentes reutilizables de la HMI.
Migrados de card() y stat_box() en app.py.

Importar en cualquier tab:
    from hmi.layout.components import card, stat_box
"""

from dash import html
from config.hardware import C


def card(children, title: str = None, style: dict = None) -> html.Div:
    """
    Contenedor con fondo blanco, borde suave y título opcional con acento verde.

    Parámetros
    ----------
    children : componente Dash o lista de componentes a renderizar dentro
    title    : texto del encabezado en mayúsculas con barra verde (opcional)
    style    : dict de estilos adicionales que sobreescriben los por defecto
    """
    base_style = {
        "background":   C["white"],
        "border":       f"1px solid {C['border']}",
        "borderRadius": 12,
        "padding":      "16px 20px",
        "marginBottom": 0,
    }
    if style:
        base_style.update(style)

    inner = []

    if title:
        inner.append(html.Div([
            html.Div(style={
                "width":         4,
                "height":        14,
                "background":    C["accent"],
                "borderRadius":  2,
                "display":       "inline-block",
                "marginRight":   8,
                "verticalAlign": "middle",
            }),
            html.Span(title, style={
                "fontSize":      10,
                "fontWeight":    800,
                "textTransform": "uppercase",
                "letterSpacing": 1.6,
                "color":         C["accentDark"],
                "verticalAlign": "middle",
            }),
        ], style={"marginBottom": 12}))

    if isinstance(children, list):
        inner.extend(children)
    else:
        inner.append(children)

    return html.Div(inner, style=base_style)


def stat_box(label: str, value: str, unit: str,
             color: str = None, bg: str = None,
             small: bool = False) -> html.Div:
    """
    Tarjeta de métrica: número grande centrado con unidad y etiqueta.

    Parámetros
    ----------
    label : texto descriptivo en la parte inferior (ej. "Potencia pico")
    value : valor numérico como string ya formateado (ej. "412")
    unit  : unidad de medida (ej. "W", "kWh", "seg")
    color : color del número (por defecto C["text"])
    bg    : color de fondo (por defecto C["white"])
    small : True = fuente más pequeña (para grillas de 5+ tarjetas)
    """
    font_size = 20 if small else 26

    return html.Div([
        html.Div(
            value,
            style={
                "fontSize":   font_size,
                "fontWeight": 900,
                "color":      color or C["text"],
                "fontFamily": "monospace",
                "lineHeight": 1.1,
            },
        ),
        html.Div(
            unit,
            style={"fontSize": 10, "color": C["dim"], "marginTop": 2},
        ),
        html.Div(
            label,
            style={
                "fontSize":      9,
                "color":         C["dim"],
                "textTransform": "uppercase",
                "letterSpacing": 1,
                "marginTop":     1,
            },
        ),
    ], style={
        "textAlign":    "center",
        "padding":      "8px 4px",
        "background":   bg or C["white"],
        "border":       f"1px solid {C['border']}",
        "borderRadius": 12,
    })


def divider() -> html.Hr:
    """Línea divisoria suave dentro de una card."""
    return html.Hr(style={"borderColor": C["borderLight"], "margin": "10px 0"})


def badge(text: str, ok: bool = True) -> html.Div:
    """
    Etiqueta de estado pequeña: verde = OK, rojo = error/clipping.
    Usada en la verificación de límites del Tab 1.
    """
    return html.Div(
        text,
        style={
            "display":      "inline-block",
            "padding":      "3px 10px",
            "borderRadius": 6,
            "fontSize":     10,
            "fontWeight":   600,
            "background":   C["accentLight"] if ok else C["redLight"],
            "color":        C["accentDark"]  if ok else C["red"],
            "border":       f"1px solid {'#bbf7d0' if ok else '#fecaca'}",
        },
    )


def slider_row(label: str, sl_id: str,
               min_: float, max_: float, step_: float,
               value: float, unit: str,
               color: str = None) -> html.Div:
    """
    Fila de slider con etiqueta a la izquierda y valor actual a la derecha.
    El valor mostrado (id="val-{sl_id}") se actualiza vía callback en arreglo_cb.py.
    """
    from dash import dcc

    return html.Div([
        html.Div([
            html.Span(label, style={"fontSize": 12, "color": C["textMed"]}),
            html.Span(
                id=f"val-{sl_id}",
                style={
                    "fontSize":   12,
                    "fontWeight": 700,
                    "color":      color or C["accentDark"],
                    "fontFamily": "monospace",
                },
            ),
        ], style={"display": "flex", "justifyContent": "space-between",
                  "marginBottom": 3}),
        dcc.Slider(
            id=sl_id,
            min=min_, max=max_, step=step_, value=value,
            marks=None,
            tooltip={"always_visible": False},
        ),
        # Almacena la unidad como dato oculto para el callback
        html.Div(unit, id=f"unit-{sl_id}", style={"display": "none"}),
    ], style={"marginBottom": 12})
