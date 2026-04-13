"""
config/modules_catalog.py
==========================
Catálogo de módulos PV disponibles en la HMI.

Para añadir un módulo nuevo: agregar una entrada al dict CATALOG
con los 8 campos requeridos por ModuleParams.

Nota sobre Ns en módulos half-cell:
    Los modelos single_diode y two_diode detectan automáticamente
    módulos half-cell (Voc/Ns < 0.50 V) y calculan un Ns_eff interno
    mediante búsqueda binaria. No es necesario ajustar Ns manualmente.

Campos:
    label    — nombre para mostrar en el Dropdown de la HMI
    Isc_n    [A]    — corriente de cortocircuito STC
    Voc_n    [V]    — voltaje de circuito abierto STC
    Imp_n    [A]    — corriente en MPP STC
    Vmp_n    [V]    — voltaje en MPP STC
    KI       [A/°C] — coef. temperatura de corriente (absoluto)
    KV       [V/°C] — coef. temperatura de voltaje (negativo)
    Ns       [—]    — celdas en serie reportadas en datasheet
    noct     [°C]   — temperatura nominal de operación
"""

# ── Catálogo ──────────────────────────────────────────────────────────────────
# Cada clave es el identificador interno usado por el Dropdown.
CATALOG: dict[str, dict] = {

    "perc_550w": {
        "label":  "PERC 550 W (half-cell, 144 células) — referencia Colombia",
        "Isc_n":  13.50,
        "Voc_n":  49.80,
        "Imp_n":  13.35,
        "Vmp_n":  41.20,
        "KI":     0.00675,    # A/°C  (0.05 %/°C × Isc)
        "KV":    -0.14442,    # V/°C  (−0.29 %/°C × Voc)
        "Ns":    144,
        "noct":   45.0,
    },

    "kyocera_kc200gt": {
        "label":  "Kyocera KC200GT — 200 W multi-Si (referencia Villalva 2009)",
        "Isc_n":  8.21,
        "Voc_n":  32.90,
        "Imp_n":  7.61,
        "Vmp_n":  26.30,
        "KI":     0.00318,    # A/°C
        "KV":    -0.12300,    # V/°C
        "Ns":    54,
        "noct":   47.0,
    },

    "canadian_cs6k_300": {
        "label":  "Canadian Solar CS6K-300MS — 300 W mono-Si",
        "Isc_n":  8.93,
        "Voc_n":  38.20,
        "Imp_n":  8.41,
        "Vmp_n":  31.00,      # Pmp = 260.7 W (≈300 W STC)
        "KI":     0.00446,    # A/°C
        "KV":    -0.11460,    # V/°C
        "Ns":    60,
        "noct":   45.0,
    },

    "jinko_eagle_400": {
        "label":  "Jinko Eagle 400 W mono PERC (half-cell)",
        "Isc_n":  10.46,
        "Voc_n":  49.52,
        "Imp_n":   9.89,
        "Vmp_n":  40.46,
        "KI":     0.00418,    # A/°C
        "KV":    -0.14856,    # V/°C
        "Ns":    120,
        "noct":   45.0,
    },

    "custom": {
        "label":  "Personalizado — ingresar parámetros manualmente",
        "Isc_n":  13.50,
        "Voc_n":  47.00,
        "Imp_n":  13.35,
        "Vmp_n":  39.00,
        "KI":     0.00500,
        "KV":    -0.13000,
        "Ns":    144,
        "noct":   45.0,
    },
}

# Índice del módulo personalizado — usado en callbacks para mostrar/ocultar sliders
CUSTOM_MODULE_KEY: str = "custom"

# Módulo por defecto al arrancar la HMI
DEFAULT_MODULE_KEY: str = "perc_550w"


def get_dropdown_options() -> list[dict]:
    """Retorna la lista de opciones para el dcc.Dropdown de módulos."""
    return [
        {"label": v["label"], "value": k}
        for k, v in CATALOG.items()
    ]


def get_params(key: str) -> dict:
    """
    Retorna el dict de parámetros del módulo dado su clave.
    Si la clave no existe, retorna el módulo por defecto.
    """
    return CATALOG.get(key, CATALOG[DEFAULT_MODULE_KEY])


def to_module_params(key: str):
    """
    Convierte la entrada del catálogo en una instancia de ModuleParams.
    Importa ModuleParams aquí para evitar dependencias circulares.
    """
    from models.base import ModuleParams
    d = get_params(key)
    return ModuleParams(
        Isc_n = d["Isc_n"],
        Voc_n = d["Voc_n"],
        Imp_n = d["Imp_n"],
        Vmp_n = d["Vmp_n"],
        KI    = d["KI"],
        KV    = d["KV"],
        Ns    = d["Ns"],
        noct  = d["noct"],
    )
