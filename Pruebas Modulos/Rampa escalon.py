import csv
import os
from typing import List, Dict

CSV_PATH = r"C:\Users\Public\Documents\EAPowerControl\seqlog\Ejemplo_1.csv"

# Estructura EXACTA del archivo
FIELDNAMES = [
    "Step",
    "Description",
    "U set (V)",
    "I set (A)",
    "P set (W)",
    "Output/Input",
    "Hour",
    "Minute",
    "Second",
    "Millisecond",
    "R mode",
    "R set",
]


def _write_rows(path: str, rows: List[Dict[str, str]]) -> None:
    """Sobrescribe el CSV con el encabezado y las filas dadas, usando separador ';'."""
    folder = os.path.dirname(path)
    if folder and not os.path.exists(folder):
        raise FileNotFoundError(f"No existe la carpeta destino: {folder}")

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, delimiter=";", lineterminator="\n")
        writer.writeheader()
        for r in rows:
            writer.writerow({k: str(r.get(k, "")) for k in FIELDNAMES})


def _base_row(step: int, desc: str, u: float, i: float, p: float, tiempo_ms: int) -> Dict[str, str]:
    return {
        "Step": str(step),
        "Description": desc,
        "U set (V)": str(u),
        "I set (A)": str(i),
        "P set (W)": str(p),
        "Output/Input": "ON",
        "Hour": "0",
        "Minute": "0",
        "Second": "0",
        "Millisecond": str(int(tiempo_ms)),
        "R mode": "OFF",
        "R set": "1",
    }


def rampa(voltaje_inicial: float, voltaje_final: float, tiempo_ms: int, potencia_w: float, corriente_a: float) -> None:
    """
    Rampa con pasos de 1V (incluye extremos) y sobrescribe el CSV.
    """
    if tiempo_ms < 0:
        raise ValueError("tiempo_ms debe ser >= 0")

    step_v = 1.0
    rows: List[Dict[str, str]] = []
    step = 1

    if voltaje_final >= voltaje_inicial:
        v = voltaje_inicial
        while v <= voltaje_final + 1e-9:
            desc = f"Ramp up PS U set= {v}V Iset= {corriente_a}A output/input= on"
            rows.append(_base_row(step, desc, v, corriente_a, potencia_w, tiempo_ms))
            step += 1
            v += step_v
    else:
        v = voltaje_inicial
        while v >= voltaje_final - 1e-9:
            desc = f"Ramp down PS U set= {v}V Iset= {corriente_a}A output/input= on"
            rows.append(_base_row(step, desc, v, corriente_a, potencia_w, tiempo_ms))
            step += 1
            v -= step_v

    _write_rows(CSV_PATH, rows)


def escalon(
    voltaje_inicial: float,
    voltaje_final: float,
    tiempo_ms: int,
    potencia_w: float,
    corriente_a: float,
    n_pasosi_antes_subir: int,
    n_pasosi_antes_bajar: int,
) -> None:
    """
    Escalón con permanencia:
      - Mantiene V_inicial por n_pasosi_antes_subir pasos
      - Sube a V_final (1 paso)
      - Mantiene V_final por n_pasosi_antes_bajar pasos
      - Baja a V_inicial (1 paso)
    Sobrescribe el CSV.
    """
    if tiempo_ms < 0:
        raise ValueError("tiempo_ms debe ser >= 0")
    if n_pasosi_antes_subir < 0 or n_pasosi_antes_bajar < 0:
        raise ValueError("Los N pasos deben ser >= 0")

    rows: List[Dict[str, str]] = []
    step = 1

    # 1) Mantener V_inicial N pasos
    for _ in range(n_pasosi_antes_subir):
        desc = f"Hold low PS U set= {voltaje_inicial}V Iset= {corriente_a}A output/input= on"
        rows.append(_base_row(step, desc, voltaje_inicial, corriente_a, potencia_w, tiempo_ms))
        step += 1

    # 2) Subir a V_final (1 paso)
    desc = f"Step up PS U set= {voltaje_final}V Iset= {corriente_a}A output/input= on"
    rows.append(_base_row(step, desc, voltaje_final, corriente_a, potencia_w, tiempo_ms))
    step += 1

    # 3) Mantener V_final N pasos
    for _ in range(n_pasosi_antes_bajar):
        desc = f"Hold high PS U set= {voltaje_final}V Iset= {corriente_a}A output/input= on"
        rows.append(_base_row(step, desc, voltaje_final, corriente_a, potencia_w, tiempo_ms))
        step += 1

    # 4) Bajar a V_inicial (1 paso)
    desc = f"Step down PS U set= {voltaje_inicial}V Iset= {corriente_a}A output/input= on"
    rows.append(_base_row(step, desc, voltaje_inicial, corriente_a, potencia_w, tiempo_ms))

    _write_rows(CSV_PATH, rows)


# Ejemplos de uso
if __name__ == "__main__":
    # Escalón tipo pulso:
    # V_inicial=5V, V_final=20V, 200ms por paso, 100W, 2A,
    # 10 pasos antes de subir, 15 pasos antes de bajar
    #escalon(5, 20, 200, 100, 2, 10, 15)

    # Rampa 0->12V
    rampa(0, 12, 200, 100, 2)
