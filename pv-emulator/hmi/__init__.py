"""
hmi/
====
Interfaz gráfica HMI construida con Dash (Plotly).

    layout/    — funciones que devuelven el layout de cada tab
    callbacks/ — callbacks de Dash agrupados por dominio funcional

Cada módulo de callbacks expone register(app) que debe llamarse
desde app.py después de crear la instancia dash.Dash:

    from hmi.callbacks import nasa_cb, arreglo_cb, profile_cb, scpi_cb, resumen_cb
    nasa_cb.register(app)
    arreglo_cb.register(app)
    profile_cb.register(app)
    scpi_cb.register(app)
    resumen_cb.register(app)
"""
