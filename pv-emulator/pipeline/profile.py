"""
pipeline/profile.py
===================
Orquesta el cálculo del perfil de consignas V_set / I_set / P_set.
Migrado de compute_pv() y apply_strategy() en app.py.

Flujo:
    datos NASA → build() → apply_strategy() → lista de pasos listos
                                               para SeqLog o SCPI

Uso:
    from pipeline.profile import build, apply_strategy
    from models.simplified import SimplifiedModel
    from models.base import ModuleParams

    params  = ModuleParams(Isc_n=13.5, Voc_n=49.8, ...)
    model   = SimplifiedModel(params)
    model.fit()

    full    = build(nasa_data, model, Ns_arr=1, Np_arr=1, tilt=10)
    profile = apply_strategy(full, strategy="day")
"""

import math
from models.base import PVModel


def build(nasa_data: list[dict],
          model:   PVModel,
          Ns_arr:  int   = 1,
          Np_arr:  int   = 1,
          tilt:    float = 10.0,
          V_max:   float = 60.0,
          I_max:   float = 170.0) -> list[dict]:
    """
    Calcula Gpoa, Tcell y las consignas eléctricas para cada punto horario.

    Parámetros
    ----------
    nasa_data : salida de pipeline/nasa_power.fetch()
    model     : instancia de PVModel ya ajustada con model.fit()
    Ns_arr    : número de módulos en serie en el arreglo
    Np_arr    : número de strings en paralelo en el arreglo
    tilt      : inclinación del módulo respecto a la horizontal [°]
    V_max     : límite máximo de voltaje del hardware [V]
    I_max     : límite máximo de corriente del hardware [A]

    Retorna
    -------
    Lista de dicts con los campos de nasa_data más:
        Gpoa  — irradiancia efectiva en el plano del arreglo [W/m²]
        Tcell — temperatura estimada de la celda [°C]
        V_set — consigna de voltaje para la fuente [V]
        I_set — consigna de corriente para la fuente [A]
        P_set — potencia resultante [W]
    """
    # Importar aquí para evitar ciclo de importación con models/
    from models.thermal import noct_cell_temp

    result = []
    for d in nasa_data:
        # ── Irradiancia en el plano del arreglo (POA) ────────────────────────
        # Modelo simplificado de transposición.
        # Para mayor precisión usar pipeline/irradiance.py con Hay-Davies
        # cuando pvlib esté integrado (Fase 2 del proyecto).
        cos_tilt = math.cos(math.radians(tilt))
        Gpoa = max(0.0, d["ghi"] + d["dni"] * 0.1 * (1.0 - cos_tilt))

        # ── Temperatura de la celda (modelo NOCT) ────────────────────────────
        Tcell = noct_cell_temp(Gpoa, d["T2M"], model.p.noct)

        # ── MPP del arreglo vía el modelo seleccionado ───────────────────────
        mpp = model.get_mpp(
            G_poa    = Gpoa,
            T_cell   = Tcell,
            Ns_arr   = Ns_arr,
            Np_arr   = Np_arr,
            V_max_hw = V_max,
            I_max_hw = I_max,
        )

        result.append({
            **d,                          # conserva todos los campos de NASA
            "Gpoa":  round(Gpoa,    0),
            "Tcell": round(Tcell,   1),
            "V_set": mpp.Vmp,
            "I_set": mpp.Imp,
            "P_set": mpp.Pmp,
        })

    return result


def apply_strategy(profile: list[dict], strategy: str) -> list[dict]:
    """
    Filtra o promedia el perfil completo según la estrategia de emulación.
    Migrado de apply_strategy() en app.py.

    Estrategias
    -----------
    "full"    : devuelve el perfil completo sin modificar
    "day"     : filtra horas 6–18 (ventana diurna)
    "average" : construye un perfil de 24 h con el promedio estadístico
                por hora del día (útil para emular un día tipo)
    """
    if strategy == "full":
        return profile

    if strategy == "day":
        return [d for d in profile if 6 <= d["hour"] <= 18]

    if strategy == "average":
        # Acumular sumas por hora del día
        buckets: dict[int, dict] = {}
        num_keys = ["V_set", "I_set", "P_set", "Gpoa", "Tcell", "ghi"]

        for d in profile:
            h = d["hour"]
            if h not in buckets:
                buckets[h] = {k: 0.0 for k in num_keys}
                buckets[h]["n"] = 0
                buckets[h]["hour"] = h
            for k in num_keys:
                buckets[h][k] += d.get(k, 0.0)
            buckets[h]["n"] += 1

        # Promediar y filtrar horas con luz (5–19)
        averaged = []
        for h, b in sorted(buckets.items()):
            if not (5 <= h <= 19):
                continue
            n = b["n"]
            averaged.append({
                "hour":  h,
                "label": f"{h}h",
                "V_set": round(b["V_set"] / n, 3),
                "I_set": round(b["I_set"] / n, 3),
                "P_set": round(b["P_set"] / n, 1),
                "Gpoa":  round(b["Gpoa"]  / n, 0),
                "Tcell": round(b["Tcell"] / n, 1),
                "ghi":   round(b["ghi"]   / n, 0),
            })
        return averaged

    # Fallback: devolver perfil sin cambios
    return profile


def summary(profile: list[dict], dt_ms: int) -> dict:
    """
    Calcula métricas de resumen del perfil para mostrar en la HMI.

    Retorna dict con:
        peak_P   — potencia pico [W]
        peak_V   — voltaje pico [V]
        peak_I   — corriente pico [A]
        total_E  — energía total estimada [kWh]
        lab_s    — duración del perfil en laboratorio [s]
        n_steps  — número de pasos
    """
    if not profile:
        return {
            "peak_P": 0, "peak_V": 0, "peak_I": 0,
            "total_E": 0, "lab_s": 0, "n_steps": 0,
        }

    return {
        "peak_P":  max(d["P_set"] for d in profile),
        "peak_V":  max(d["V_set"] for d in profile),
        "peak_I":  max(d["I_set"] for d in profile),
        "total_E": round(sum(d["P_set"] for d in profile) / 1000.0, 3),
        "lab_s":   round(len(profile) * dt_ms / 1000.0, 1),
        "n_steps": len(profile),
    }
