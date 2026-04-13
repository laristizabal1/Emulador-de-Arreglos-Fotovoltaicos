"""
hmi/layout/
===========
Funciones que construyen el layout de cada tab de la HMI.
No contienen lógica ni callbacks — solo estructura Dash.

    components    — card(), stat_box(), divider(), badge(), slider_row()
    tab_ubicacion — Tab 0: selección de ciudad + descarga NASA POWER
    tab_arreglo   — Tab 1: parámetros del módulo, modelo eléctrico
    tab_perfiles  — Tab 2: consignas V/I/P, estrategia, exportar CSV
    tab_scpi      — Tab 3: control SCPI en tiempo real
    tab_resumen   — Tab 4: métricas finales y configuración completa
"""
from hmi.layout.tab_ubicacion import tab_ubicacion
from hmi.layout.tab_arreglo   import tab_arreglo
from hmi.layout.tab_perfiles  import tab_perfiles
from hmi.layout.tab_scpi      import tab_scpi
from hmi.layout.tab_resumen   import tab_resumen

TAB_RENDERERS: dict = {
    "tab-0": tab_ubicacion,
    "tab-1": tab_arreglo,
    "tab-2": tab_perfiles,
    "tab-3": tab_scpi,
    "tab-4": tab_resumen,
}

__all__ = [
    "tab_ubicacion", "tab_arreglo", "tab_perfiles",
    "tab_scpi", "tab_resumen", "TAB_RENDERERS",
]
