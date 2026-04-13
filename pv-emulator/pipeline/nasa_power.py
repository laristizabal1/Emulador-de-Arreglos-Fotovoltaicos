"""
pipeline/nasa_power.py
======================
Descarga y parseo de datos horarios desde la API de NASA POWER.
Migrado de build_nasa_url(), fetch_nasa() y parseNasaData() en app.py.

Uso básico:
    from pipeline.nasa_power import fetch

    datos = fetch(lat=4.71, lon=-74.07, start="20240315", end="20240317")
    # → lista de dicts con: key, year, month, day, hour, label,
    #                        ghi, dni, dhi, T2M, WS

Uso con caché (evita re-descargar el mismo rango):
    datos = fetch(4.71, -74.07, "20240315", "20240317",
                  cache_dir="data/nasa_cache")
"""

import json
import requests
from pathlib import Path

# Parámetros que se descargan de NASA POWER en cada petición
_PARAMS = ",".join([
    "ALLSKY_SFC_SW_DWN",   # GHI — irradiancia global horizontal  [W/m²]
    "ALLSKY_SFC_SW_DIFF",  # DHI — componente difusa horizontal    [W/m²]
    "ALLSKY_SFC_SW_DNI",   # DNI — irradiancia directa normal      [W/m²]
    "T2M",                 # temperatura del aire a 2 m            [°C]
    "WS2M",                # velocidad del viento a 2 m            [m/s]
])

_BASE_URL = (
    "https://power.larc.nasa.gov/api/temporal/hourly/point"
    "?parameters={params}"
    "&community=RE"
    "&longitude={lon}"
    "&latitude={lat}"
    "&start={start}"
    "&end={end}"
    "&format=JSON"
    "&time-standard=LST"
)


# ── Interfaz pública ──────────────────────────────────────────────────────────

def build_url(lat: float, lon: float, start: str, end: str) -> str:
    """
    Construye la URL completa de la API de NASA POWER.

    Parámetros
    ----------
    lat, lon : coordenadas decimales
    start, end : fechas en formato YYYYMMDD (ej. "20240315")
    """
    return _BASE_URL.format(
        params=_PARAMS, lon=lon, lat=lat, start=start, end=end
    )


def fetch(lat: float, lon: float, start: str, end: str,
          cache_dir: str | Path = None,
          timeout: int = 30) -> list[dict]:
    """
    Descarga datos horarios de NASA POWER para las coordenadas y fechas dadas.

    Si se especifica cache_dir, guarda el JSON crudo en disco y lo
    reutiliza en llamadas posteriores con los mismos parámetros,
    evitando peticiones redundantes a la API.

    Retorna
    -------
    Lista de dicts con los campos:
        key, year, month, day, hour, label,
        ghi, dni, dhi, T2M, WS

    Lanza
    -----
    ValueError  — si la API devuelve mensajes de error
    requests.HTTPError — si la respuesta HTTP no es 2xx
    """
    # ── Caché ─────────────────────────────────────────────────────────────────
    cache_file = None
    if cache_dir:
        cache_path = Path(cache_dir)
        cache_path.mkdir(parents=True, exist_ok=True)
        # Nombre de archivo único por coordenadas y rango de fechas
        fname = f"nasa_{lat}_{lon}_{start}_{end}.json"
        cache_file = cache_path / fname
        if cache_file.exists():
            raw = json.loads(cache_file.read_text(encoding="utf-8"))
            return _parse(raw)

    # ── Petición a la API ─────────────────────────────────────────────────────
    url = build_url(lat, lon, start, end)
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    raw = response.json()

    # La API devuelve errores en "messages" cuando los parámetros son inválidos
    if "properties" not in raw:
        msgs = raw.get("messages", ["Sin datos de NASA POWER"])
        raise ValueError("; ".join(str(m) for m in msgs))

    # ── Guardar en caché ──────────────────────────────────────────────────────
    if cache_file:
        cache_file.write_text(
            json.dumps(raw, ensure_ascii=False), encoding="utf-8"
        )

    return _parse(raw)


# ── Parseo interno ────────────────────────────────────────────────────────────

def _parse(json_data: dict) -> list[dict]:
    """
    Convierte la respuesta JSON de NASA POWER en lista de dicts normalizados.
    Filtra registros inválidos (T2M < -100, valores fill de la NASA).

    La clave temporal tiene formato YYYYMMDDHH (10 dígitos), por ejemplo
    "2024031514" = 14h del 15 de marzo de 2024.
    """
    p       = json_data["properties"]["parameter"]
    t2m_map = p.get("T2M", {})

    records = []
    for key, t2m in t2m_map.items():
        # NASA usa -999 como valor de relleno cuando no hay dato
        if t2m < -100:
            continue

        ghi = max(0.0, p.get("ALLSKY_SFC_SW_DWN",  {}).get(key, 0))
        dni = max(0.0, p.get("ALLSKY_SFC_SW_DNI",   {}).get(key, 0))
        dhi = max(0.0, p.get("ALLSKY_SFC_SW_DIFF",  {}).get(key, 0))
        ws  = p.get("WS2M", {}).get(key, 1.0)

        records.append({
            "key":   key,
            "year":  int(key[0:4]),
            "month": int(key[4:6]),
            "day":   int(key[6:8]),
            "hour":  int(key[8:10]),
            # Etiqueta legible para los ejes X de las gráficas Plotly
            "label": f"{key[4:6]}/{key[6:8]} {key[8:10]}h",
            "ghi":   ghi,
            "dni":   dni,
            "dhi":   dhi,
            "T2M":   t2m,
            "WS":    ws,
        })

    return records
