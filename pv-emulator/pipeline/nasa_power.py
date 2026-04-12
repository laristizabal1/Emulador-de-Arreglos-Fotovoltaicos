# pipeline/nasa_power.py
import requests
from pathlib import Path
import json

NASA_BASE = (
    "https://power.larc.nasa.gov/api/temporal/hourly/point"
    "?parameters=ALLSKY_SFC_SW_DWN,ALLSKY_SFC_SW_DIFF,ALLSKY_SFC_SW_DNI,T2M,WS2M"
    "&community=RE&longitude={lon}&latitude={lat}"
    "&start={start}&end={end}&format=JSON&time-standard=LST"
)

def build_url(lat: float, lon: float, start: str, end: str) -> str:
    return NASA_BASE.format(lat=lat, lon=lon, start=start, end=end)


def fetch(lat: float, lon: float, start: str, end: str,
          cache_dir: Path = None) -> list[dict]:
    """
    Descarga datos horarios de NASA POWER para las coordenadas y fechas dadas.
    Si cache_dir se especifica, guarda y reutiliza el JSON para no re-descargar.

    Retorna lista de dicts con: key, year, month, day, hour, label,
                                ghi, dni, dhi, T2M, WS
    """
    cache_file = None
    if cache_dir:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f"nasa_{lat}_{lon}_{start}_{end}.json"
        if cache_file.exists():
            raw = json.loads(cache_file.read_text())
            return _parse(raw)

    url = build_url(lat, lon, start, end)
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    raw = r.json()

    if "properties" not in raw:
        msgs = raw.get("messages", ["Sin datos de NASA POWER"])
        raise ValueError("; ".join(msgs))

    if cache_file:
        cache_file.write_text(json.dumps(raw))

    return _parse(raw)


def _parse(json_data: dict) -> list[dict]:
    """Convierte la respuesta JSON de NASA POWER en lista de dicts normalizados."""
    p = json_data["properties"]["parameter"]
    records = []
    for k in p.get("T2M", {}):
        t2m = p["T2M"].get(k, 20)
        if t2m < -100:         # filtrar registros inválidos
            continue
        records.append({
            "key":   k,
            "year":  int(k[0:4]),
            "month": int(k[4:6]),
            "day":   int(k[6:8]),
            "hour":  int(k[8:10]),
            "label": f"{k[4:6]}/{k[6:8]} {k[8:10]}h",
            "ghi":   max(0.0, p["ALLSKY_SFC_SW_DWN"].get(k,  0)),
            "dni":   max(0.0, p["ALLSKY_SFC_SW_DNI"].get(k,  0)),
            "dhi":   max(0.0, p["ALLSKY_SFC_SW_DIFF"].get(k, 0)),
            "T2M":   t2m,
            "WS":    p.get("WS2M", {}).get(k, 1.0),
        })
    return records