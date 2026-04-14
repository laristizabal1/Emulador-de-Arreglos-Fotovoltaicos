"""
config/modules_catalog.py
==========================
Catalogo de modulos PV disponibles en la HMI.

Todos los modulos usan panel_from_datasheet() de models/panel_factory.py,
que detecta automaticamente si los coeficientes KI/KV estan en:
  - Convencion relativa (%/C)  e.g. KI=0.04, KV=-0.25
  - Convencion absoluta (A/C)  e.g. KI=0.00675, KV=-0.14442

Para anadir un modulo nuevo: agregar una entrada a CATALOG con los
valores directos del datasheet. No es necesario convertir los coeficientes.

Campos requeridos:
    label    — nombre para mostrar en el Dropdown
    Isc      [A]    — corriente de cortocircuito STC
    Voc      [V]    — voltaje de circuito abierto STC
    Imp      [A]    — corriente en MPP STC
    Vmp      [V]    — voltaje en MPP STC
    KI       [%/C o A/C] — coef. temperatura corriente (auto-detectado)
    KV       [%/C o V/C] — coef. temperatura voltaje  (auto-detectado, negativo)
    Ns       [—]    — celdas en serie (total fisico del datasheet)
    noct     [C]    — temperatura nominal de operacion

Nota sobre Ns en modulos half-cell:
    Los modelos single_diode y two_diode detectan automaticamente
    modulos half-cell (Voc/Ns < 0.50 V) y calculan Ns_eff internamente.
    Usar siempre el Ns total del datasheet.
"""

# ── Catalogo ──────────────────────────────────────────────────────────────────
CATALOG: dict[str, dict] = {

    "perc_550w": {
        "label": "PERC 550 W (half-cell, 144 celulas) — referencia Colombia",
        "Isc":   13.50,
        "Voc":   49.80,
        "Imp":   13.35,
        "Vmp":   41.20,
        "KI":     0.00675,   # A/C — convencion absoluta
        "KV":    -0.14442,   # V/C — convencion absoluta
        "Ns":   144,
        "noct":  45.0,
    },

    "kyocera_kc200gt": {
        "label": "Kyocera KC200GT — 200 W multi-Si (referencia Villalva 2009)",
        "Isc":   8.21,
        "Voc":   32.90,
        "Imp":   7.61,
        "Vmp":   26.30,
        "KI":    0.00318,    # A/C — convencion absoluta
        "KV":   -0.12300,    # V/C — convencion absoluta
        "Ns":   54,
        "noct":  47.0,
    },

    "canadian_cs6k_300": {
        "label": "Canadian Solar CS6K-300MS — 300 W mono-Si",
        "Isc":   8.93,
        "Voc":   38.20,
        "Imp":   8.41,
        "Vmp":   31.00,
        "KI":    0.00446,    # A/C — convencion absoluta
        "KV":   -0.11460,    # V/C — convencion absoluta
        "Ns":   60,
        "noct":  45.0,
    },

    "jinko_eagle_400": {
        "label": "Jinko Eagle 400 W mono PERC (half-cell)",
        "Isc":   10.46,
        "Voc":   49.52,
        "Imp":    9.89,
        "Vmp":   40.46,
        "KI":    0.00418,    # A/C — convencion absoluta
        "KV":   -0.14856,    # V/C — convencion absoluta
        "Ns":  120,
        "noct":  45.0,
    },

    "trina_vertex_510": {
        "label": "Trina Vertex 510 W (half-cell, 132 celulas)",
        "Isc":   12.42,
        "Voc":   52.10,
        "Imp":   11.72,
        "Vmp":   43.50,
        "KI":     0.04,      # %/C — convencion relativa (auto-detectado)
        "KV":    -0.25,      # %/C — convencion relativa (auto-detectado)
        "Ns":   132,
        "noct":  45.0,
    },

    "custom": {
        "label": "Personalizado — ingresar parametros manualmente",
        "Isc":   13.50,
        "Voc":   47.00,
        "Imp":   13.00,
        "Vmp":   39.00,
        "KI":     0.00500,   # A/C — convencion absoluta
        "KV":    -0.13000,   # V/C — convencion absoluta
        "Ns":   144,
        "noct":  45.0,
    },
}

CUSTOM_MODULE_KEY:  str = "custom"
DEFAULT_MODULE_KEY: str = "perc_550w"


def get_dropdown_options() -> list[dict]:
    """Lista de opciones para dcc.Dropdown de modulos."""
    return [{"label": v["label"], "value": k} for k, v in CATALOG.items()]


def get_params(key: str) -> dict:
    """Dict raw del catalogo para el modulo dado."""
    return CATALOG.get(key, CATALOG[DEFAULT_MODULE_KEY])


def to_module_params(key: str):
    """
    Convierte la entrada del catalogo en ModuleParams usando panel_from_datasheet.
    Detecta automaticamente la convencion de los coeficientes KI/KV.
    """
    from models.panel_factory import panel_from_datasheet
    d = get_params(key)
    return panel_from_datasheet(
        Isc  = d["Isc"],
        Voc  = d["Voc"],
        Imp  = d["Imp"],
        Vmp  = d["Vmp"],
        KI   = d["KI"],
        KV   = d["KV"],
        Ns   = d["Ns"],
        noct = d["noct"],
        # coefficients_in_percent=None -> auto-deteccion
    )