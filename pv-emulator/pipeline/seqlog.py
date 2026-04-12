# pipeline/seqlog.py
from pathlib import Path
from config.hardware import DT_MIN
import pandas as pd

def to_dataframe(profile: list[dict], dt_ms: int) -> pd.DataFrame:
    """Convierte el perfil en el DataFrame con el formato SeqLog de EA Power Control."""
    rows = [{
        "Time [ms]":   max(dt_ms, DT_MIN),
        "Voltage [V]": step["V_set"],
        "Current [A]": step["I_set"],
        "Power [W]":   step["P_set"],
        "DC Output":   1 if step["P_set"] > 0 else 0,
    } for step in profile]
    return pd.DataFrame(rows)


def to_csv_string(profile: list[dict], dt_ms: int) -> str:
    """Devuelve el CSV como string — lo usa el callback de descarga de Dash."""
    return to_dataframe(profile, dt_ms).to_csv(index=False, sep=";")


def save(profile: list[dict], dt_ms: int, path: str | Path) -> Path:
    """Guarda el CSV en disco — lo usa el orquestador CLI (run.py)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    to_dataframe(profile, dt_ms).to_csv(p, index=False, sep=";")
    return p