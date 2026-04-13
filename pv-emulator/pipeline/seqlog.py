"""
pipeline/seqlog.py
==================
Exportación del perfil de consignas al formato CSV SeqLog de
EA Power Control (software del fabricante EA Elektro-Automatik).
Migrado de export_seqlog_csv() en app.py.

Formato SeqLog (separador punto y coma):
    Time [ms] ; Voltage [V] ; Current [A] ; Power [W] ; DC Output

Referencia: Manual EA Power Control (ID Doc: PCES), sección 8.6.1

Uso:
    from pipeline.seqlog import to_csv_string, save

    # Para el callback de descarga en Dash:
    csv_str = to_csv_string(profile, dt_ms=1000)

    # Para guardar en disco desde el CLI:
    path = save(profile, dt_ms=200, path="outputs/perfil.csv")
"""

from pathlib import Path
import pandas as pd

from config.hardware import DT_MIN


def to_dataframe(profile: list[dict], dt_ms: int) -> pd.DataFrame:
    """
    Convierte el perfil en un DataFrame con el formato exacto
    que espera SeqLog de EA Power Control.

    Aplica el límite mínimo de DT_MIN = 200 ms por paso.

    Columnas:
        Time [ms]   — duración del paso en milisegundos
        Voltage [V] — consigna de voltaje
        Current [A] — consigna de corriente
        Power [W]   — potencia calculada (referencia visual en SeqLog)
        DC Output   — 1 = salida activa, 0 = salida apagada (noche)
    """
    dt_safe = max(int(dt_ms), DT_MIN)

    rows = [
        {
            "Time [ms]":   dt_safe,
            "Voltage [V]": step["V_set"],
            "Current [A]": step["I_set"],
            "Power [W]":   step["P_set"],
            "DC Output":   1 if step["P_set"] > 0 else 0,
        }
        for step in profile
    ]
    return pd.DataFrame(rows)


def to_csv_string(profile: list[dict], dt_ms: int) -> str:
    """
    Devuelve el CSV como string para el componente dcc.Download de Dash.

    El separador es punto y coma (;) porque SeqLog lo requiere así
    según la sección 8.6.1 del manual de EA Power Control.
    """
    return to_dataframe(profile, dt_ms).to_csv(index=False, sep=";")


def save(profile: list[dict], dt_ms: int,
         path: str | Path) -> Path:
    """
    Guarda el CSV en disco.
    Crea los directorios intermedios si no existen.
    Retorna el Path del archivo guardado.

    Uso desde el orquestador CLI (run.py):
        saved = seqlog.save(profile, dt_ms=200, path="outputs/bogota_day.csv")
        print(f"Guardado en {saved}")
    """
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    to_dataframe(profile, dt_ms).to_csv(out, index=False, sep=";")
    return out


def preview(profile: list[dict], dt_ms: int, n: int = 5) -> str:
    """
    Devuelve las primeras `n` filas como string para depuración.
    Útil en notebooks y en el REPL para verificar el formato.
    """
    df = to_dataframe(profile, dt_ms)
    return df.head(n).to_string(index=False)
