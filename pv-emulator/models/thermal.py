# models/thermal.py

def noct_cell_temp(G_poa: float, T_amb: float, noct: float) -> float:
    """
    Modelo NOCT (Normal Operating Cell Temperature).
    Estima la temperatura de la celda a partir de la irradiancia
    en el plano del arreglo y la temperatura ambiente.

    Ecuación (8) del documento del proyecto.

    Parámetros
    ----------
    G_poa : irradiancia efectiva en POA [W/m²]
    T_amb : temperatura ambiente [°C]
    noct  : temperatura nominal de operación del módulo [°C]
             (provista por el fabricante, típicamente 42–48°C)

    Retorna
    -------
    Tcell : temperatura estimada de la celda [°C]
    """
    return T_amb + G_poa * ((noct - 20.0) / 800.0)


def faiman_cell_temp(G_poa: float, T_amb: float,
                     wind: float,
                     u0: float = 25.0,
                     u1: float = 6.84) -> float:
    """
    Modelo de Faiman — más preciso que NOCT porque incorpora velocidad del viento.
    Requiere parámetros u0, u1 de calibración (no siempre en el datasheet).

    Trabajo futuro: usar cuando WS2M esté disponible de NASA POWER.
    """
    return T_amb + G_poa / (u0 + u1 * wind)