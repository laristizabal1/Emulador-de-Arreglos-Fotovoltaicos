"""
config/
=======
Constantes globales del proyecto pv-emulator.

Importar así:
    from config.hardware  import V_MAX, I_MAX, DT_MIN, C
    from config.locations import LOCATIONS, CUSTOM_IDX, get_coords
"""
from config.hardware  import V_MAX, I_MAX, P_MAX, DT_MIN, C
from config.locations import LOCATIONS, CUSTOM_IDX, get, get_coords

__all__ = [
    "V_MAX", "I_MAX", "P_MAX", "DT_MIN", "C",
    "LOCATIONS", "CUSTOM_IDX", "get", "get_coords",
]
