"""
hmi/callbacks/
==============
Callbacks de Dash agrupados por dominio funcional.
Cada módulo expone una función register(app).

    nasa_cb     — ubicación + descarga NASA POWER          (4 callbacks)
    arreglo_cb  — sliders del arreglo PV + verificación    (2 callbacks)
    profile_cb  — cálculo del perfil + exportar CSV        (2 callbacks)
    scpi_cb     — control real de la fuente EA-PS 10060-170 (5 callbacks)
    resumen_cb  — tab resumen + header superior            (2 callbacks)
"""
from hmi.callbacks import nasa_cb, arreglo_cb, profile_cb, scpi_cb, resumen_cb


def register_all(app) -> None:
    """
    Registra todos los callbacks en la app Dash.
    Llamar una sola vez desde app.py tras crear la instancia:

        import hmi.callbacks as cb
        cb.register_all(app)
    """
    nasa_cb.register(app)
    arreglo_cb.register(app)
    profile_cb.register(app)
    scpi_cb.register(app)
    resumen_cb.register(app)


__all__ = [
    "nasa_cb", "arreglo_cb", "profile_cb", "scpi_cb", "resumen_cb",
    "register_all",
]
