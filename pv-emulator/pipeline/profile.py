# pipeline/profile.py
from models.base import PVModel, MPPResult
from models.thermal import noct_cell_temp
import math

def build(nasa_data: list[dict],
          model: PVModel,
          Ns_arr: int   = 1,
          Np_arr: int   = 1,
          tilt:   float = 10.0,
          V_max:  float = 60.0,
          I_max:  float = 170.0) -> list[dict]:
    """
    Aplica el modelo PV a cada punto ambiental de NASA POWER.
    Calcula Gpoa (simplificado), Tcell (NOCT) y llama a model.get_mpp().

    Retorna lista de dicts con los campos de nasa_data más:
    Gpoa, Tcell, V_set, I_set, P_set
    """
    result = []
    for d in nasa_data:
        Gpoa = max(0.0, d["ghi"] + d["dni"] * 0.1
                   * (1 - math.cos(math.radians(tilt))))
        Tcell = noct_cell_temp(Gpoa, d["T2M"], model.p.noct)

        mpp = model.get_mpp(Gpoa, Tcell, Ns_arr, Np_arr, V_max, I_max)
        result.append({
            **d,
            "Gpoa":  round(Gpoa,     0),
            "Tcell": round(Tcell,    1),
            "V_set": mpp.Vmp,
            "I_set": mpp.Imp,
            "P_set": mpp.Pmp,
        })
    return result


def apply_strategy(profile: list[dict], strategy: str) -> list[dict]:
    """
    Filtra o promedia el perfil según la estrategia elegida en la HMI.
    Migrada directamente de apply_strategy() en app.py.

    strategy: "full" | "day" | "average"
    """
    if strategy == "day":
        return [d for d in profile if 6 <= d["hour"] <= 18]

    if strategy == "average":
        by_h: dict = {}
        keys = ["V_set", "I_set", "P_set", "Gpoa", "Tcell", "ghi"]
        for d in profile:
            h = d["hour"]
            if h not in by_h:
                by_h[h] = {k: 0.0 for k in keys}
                by_h[h]["n"] = 0
                by_h[h]["hour"] = h
            for k in keys:
                by_h[h][k] += d.get(k, 0)
            by_h[h]["n"] += 1

        out = []
        for h, v in sorted(by_h.items()):
            if 5 <= h <= 19:
                n = v["n"]
                out.append({
                    "hour":  h,
                    "label": f"{h}h",
                    **{k: round(v[k] / n, 3 if k in ("V_set","I_set") else 1)
                       for k in keys},
                })
        return out

    return profile   # "full" — sin filtro