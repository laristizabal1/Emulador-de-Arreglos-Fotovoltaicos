"""
config/locations.py
===================
Ciudades colombianas preconfiguradas para la HMI.
Migradas directamente de la constante LOCATIONS en app.py.

Cada entrada tiene:
    name  — nombre para mostrar en la UI
    lat   — latitud decimal (positivo = norte)
    lon   — longitud decimal (negativo = oeste)
    tamb  — temperatura ambiente representativa °C (referencia, NASA POWER
            entrega T2M horaria real en la descarga)
"""

LOCATIONS: list[dict] = [
    {"name": "Bogotá",         "lat":  4.71,  "lon": -74.07, "tamb": 14},
    {"name": "Medellín",       "lat":  6.25,  "lon": -75.56, "tamb": 22},
    {"name": "Barranquilla",   "lat": 10.96,  "lon": -74.78, "tamb": 28},
    {"name": "Cali",           "lat":  3.45,  "lon": -76.53, "tamb": 24},
    {"name": "Bucaramanga",    "lat":  7.12,  "lon": -73.12, "tamb": 23},
    {"name": "Leticia",        "lat": -4.21,  "lon": -69.94, "tamb": 27},
    {"name": "Riohacha",       "lat": 11.54,  "lon": -72.91, "tamb": 29},
    {"name": "Villa de Leyva", "lat":  5.63,  "lon": -73.52, "tamb": 17},
    {"name": "Personalizado",  "lat":  4.71,  "lon": -74.07, "tamb": 20},
]

# Índice de "Personalizado" — usado en callbacks para decidir si mostrar
# los inputs de lat/lon manuales
CUSTOM_IDX: int = 8


def get(idx: int) -> dict:
    """Devuelve la localización por índice. Lanza IndexError si fuera de rango."""
    return LOCATIONS[idx]


def get_coords(idx: int, custom_lat: float = None,
               custom_lon: float = None) -> tuple[float, float]:
    """
    Devuelve (lat, lon) para el índice dado.
    Si idx == CUSTOM_IDX y se pasan custom_lat/lon, usa esos valores.
    """
    if idx == CUSTOM_IDX and custom_lat is not None and custom_lon is not None:
        return float(custom_lat), float(custom_lon)
    loc = LOCATIONS[idx]
    return loc["lat"], loc["lon"]
