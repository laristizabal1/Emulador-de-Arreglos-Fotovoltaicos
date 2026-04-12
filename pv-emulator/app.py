"""
PV Array Emulator — HMI completa en Dash
Laptop conectada a EA-PS 10060-170 por USB/COM

Instalar:
    pip install dash dash-bootstrap-components plotly pandas requests pyserial scipy pvlib

Correr:
    python app.py
    → abre en http://localhost:8050

Para modo escritorio sin navegador:
    pip install pywebview
    python app.py --desktop
"""

import sys
import math
import time
import threading
import requests

import numpy as np
import pandas as pd
import plotly.graph_objects as go

import dash
from dash import dcc, html, Input, Output, State, callback, ctx, no_update
import dash_bootstrap_components as dbc

# ── Intentar importar pyserial (opcional en modo demo) ────────────────────────
try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTES DE HARDWARE
# ─────────────────────────────────────────────────────────────────────────────
V_MAX   = 60.0
I_MAX   = 170.0
P_MAX   = 5000.0
DT_MIN  = 200       # ms — mínimo estable validado EA-PS 10060-170

# ─────────────────────────────────────────────────────────────────────────────
# DATOS DE REFERENCIA
# ─────────────────────────────────────────────────────────────────────────────
LOCATIONS = [
    {"name": "Bogotá",        "lat":  4.71, "lon": -74.07, "tamb": 14},
    {"name": "Medellín",      "lat":  6.25, "lon": -75.56, "tamb": 22},
    {"name": "Barranquilla",  "lat": 10.96, "lon": -74.78, "tamb": 28},
    {"name": "Cali",          "lat":  3.45, "lon": -76.53, "tamb": 24},
    {"name": "Bucaramanga",   "lat":  7.12, "lon": -73.12, "tamb": 23},
    {"name": "Leticia",       "lat": -4.21, "lon": -69.94, "tamb": 27},
    {"name": "Riohacha",      "lat": 11.54, "lon": -72.91, "tamb": 29},
    {"name": "Villa de Leyva","lat":  5.63, "lon": -73.52, "tamb": 17},
    {"name": "Personalizado", "lat":  4.71, "lon": -74.07, "tamb": 20},
]

# ─────────────────────────────────────────────────────────────────────────────
# LÓGICA PV (migrada directamente desde App.jsx)
# ─────────────────────────────────────────────────────────────────────────────
def build_nasa_url(lat, lon, start, end):
    return (
        f"https://power.larc.nasa.gov/api/temporal/hourly/point"
        f"?parameters=ALLSKY_SFC_SW_DWN,ALLSKY_SFC_SW_DIFF,ALLSKY_SFC_SW_DNI,T2M,WS2M"
        f"&community=RE&longitude={lon}&latitude={lat}"
        f"&start={start}&end={end}&format=JSON&time-standard=LST"
    )


def fetch_nasa(lat, lon, start, end):
    """Descarga datos horarios de NASA POWER. Devuelve lista de dicts."""
    url = build_nasa_url(lat, lon, start, end)
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    json = r.json()
    if "properties" not in json:
        msgs = json.get("messages", ["Sin datos"])
        raise ValueError("; ".join(msgs))
    p = json["properties"]["parameter"]
    records = []
    for k in p.get("T2M", {}):
        ghi = max(0, p["ALLSKY_SFC_SW_DWN"].get(k, 0))
        dni = max(0, p["ALLSKY_SFC_SW_DNI"].get(k,  0))
        dhi = max(0, p["ALLSKY_SFC_SW_DIFF"].get(k, 0))
        t2m = p["T2M"].get(k, 20)
        if t2m < -100:
            continue
        records.append({
            "key":   k,
            "year":  int(k[0:4]),
            "month": int(k[4:6]),
            "day":   int(k[6:8]),
            "hour":  int(k[8:10]),
            "label": f"{k[4:6]}/{k[6:8]} {k[8:10]}h",
            "ghi":   ghi,
            "dni":   dni,
            "dhi":   dhi,
            "T2M":   t2m,
            "WS":    p.get("WS2M", {}).get(k, 1),
        })
    return records


def compute_pv(data, Ns, Np, Voc, Isc, beta_Voc, alpha_Isc, noct, tilt, model="simplified"):
    """
    Calcula Vset / Iset / Pset para cada punto ambiental.
    model: "simplified" | "single_diode" | "two_diode"
    """
    result = []
    for d in data:
        Gpoa = max(0, d["ghi"] + d["dni"] * 0.1 * (1 - math.cos(math.radians(tilt))))
        Tcell = d["T2M"] + Gpoa * ((noct - 20) / 800)

        if Gpoa < 5:
            result.append({**d, "Gpoa": 0, "Tcell": round(Tcell, 1),
                           "V_set": 0.0, "I_set": 0.0, "P_set": 0.0})
            continue

        if model == "simplified":
            I_set = (Isc * Np) * (Gpoa / 1000) * (1 + alpha_Isc * (Tcell - 25))
            V_set = (Voc * Ns) + beta_Voc * (Tcell - 25) + 0.026 * Ns * math.log(max(Gpoa, 1) / 1000)
        else:
            # Placeholder — aquí se enchufan single_diode.py / two_diode.py
            # cuando estén listos en models/
            I_set = (Isc * Np) * (Gpoa / 1000) * (1 + alpha_Isc * (Tcell - 25))
            V_set = (Voc * Ns) + beta_Voc * (Tcell - 25) + 0.026 * Ns * math.log(max(Gpoa, 1) / 1000)

        V_set = float(np.clip(V_set, 0, V_MAX))
        I_set = float(np.clip(I_set, 0, I_MAX))
        result.append({
            **d,
            "Gpoa":  round(Gpoa, 0),
            "Tcell": round(Tcell, 1),
            "V_set": round(V_set, 2),
            "I_set": round(I_set, 2),
            "P_set": round(V_set * I_set, 1),
        })
    return result


def apply_strategy(profile, strategy):
    if strategy == "day":
        return [d for d in profile if 6 <= d["hour"] <= 18]
    if strategy == "average":
        by_h = {}
        for d in profile:
            h = d["hour"]
            if h not in by_h:
                by_h[h] = {k: 0 for k in ["V_set","I_set","P_set","Gpoa","Tcell","ghi"]}
                by_h[h]["n"] = 0
                by_h[h]["hour"] = h
            for k in ["V_set","I_set","P_set","Gpoa","Tcell","ghi"]:
                by_h[h][k] += d[k]
            by_h[h]["n"] += 1
        out = []
        for h, v in sorted(by_h.items()):
            if 5 <= h <= 19:
                n = v["n"]
                out.append({
                    "hour":  h, "label": f"{h}h",
                    "V_set": round(v["V_set"]/n, 2),
                    "I_set": round(v["I_set"]/n, 2),
                    "P_set": round(v["P_set"]/n, 1),
                    "Gpoa":  round(v["Gpoa"]/n, 0),
                    "Tcell": round(v["Tcell"]/n, 1),
                    "ghi":   round(v["ghi"]/n, 0),
                })
        return out
    return profile   # "full"


def export_seqlog_csv(profile, dt_ms):
    """Genera el CSV compatible con SeqLog de EA Power Control."""
    rows = []
    for step in profile:
        rows.append({
            "Time [ms]":   max(dt_ms, DT_MIN),
            "Voltage [V]": step["V_set"],
            "Current [A]": step["I_set"],
            "Power [W]":   step["P_set"],
            "DC Output":   1 if step["P_set"] > 0 else 0,
        })
    return pd.DataFrame(rows).to_csv(index=False, sep=";")


# ─────────────────────────────────────────────────────────────────────────────
# COMUNICACIÓN SCPI REAL (EA-PS 10060-170)
# ─────────────────────────────────────────────────────────────────────────────
class SCPIController:
    """Controlador real de la fuente por USB/COM usando SCPI ASCII."""

    def __init__(self, port, baud=115200, timeout=2.0):
        self.port    = port
        self.baud    = baud
        self.timeout = timeout
        self.ser     = None
        self._running = False
        self._lock    = threading.Lock()

    def connect(self):
        if not SERIAL_AVAILABLE:
            raise RuntimeError("pyserial no instalado. Ejecutar: pip install pyserial")
        self.ser = serial.Serial(self.port, self.baud, timeout=self.timeout)
        time.sleep(0.3)
        idn = self.query("*IDN?")
        return idn.strip()

    def disconnect(self):
        if self.ser and self.ser.is_open:
            self.send("OUTP OFF")
            self.ser.close()

    def send(self, cmd: str):
        with self._lock:
            if self.ser and self.ser.is_open:
                self.ser.write((cmd + "\n").encode())
                time.sleep(0.05)

    def query(self, cmd: str) -> str:
        with self._lock:
            if self.ser and self.ser.is_open:
                self.ser.write((cmd + "\n").encode())
                time.sleep(0.05)
                return self.ser.readline().decode(errors="replace")
        return ""

    def set_output(self, V: float, I: float, on: bool = True):
        """Envía consigna de voltaje y corriente. Núcleo del control en tiempo real."""
        V_safe = min(max(V, 0), V_MAX)
        I_safe = min(max(I, 0), I_MAX)
        self.send(f"VOLT {V_safe:.3f}")
        self.send(f"CURR {I_safe:.3f}")
        if on:
            self.send("OUTP ON")

    def run_profile(self, profile, dt_ms, progress_cb=None):
        """
        Ejecuta el perfil completo en la fuente.
        progress_cb(i, total, step) se llama en cada paso para actualizar la UI.
        """
        self._running = True
        dt_s = max(dt_ms, DT_MIN) / 1000.0
        n = len(profile)

        self.send("SYST:REM:TRAN ON")
        self.send(f"VOLT {profile[0]['V_set']:.3f}")
        self.send(f"CURR {profile[0]['I_set']:.3f}")
        self.send("OUTP ON")

        for i, step in enumerate(profile):
            if not self._running:
                break
            self.set_output(step["V_set"], step["I_set"], on=(step["P_set"] > 0))
            if progress_cb:
                progress_cb(i, n, step)
            time.sleep(dt_s)

        self.send("OUTP OFF")
        self._running = False

    def stop(self):
        self._running = False
        self.send("OUTP OFF")


# Instancia global del controlador (compartida entre callbacks)
_controller = SCPIController(port="COM3")
_exec_thread: threading.Thread = None


def list_serial_ports():
    if not SERIAL_AVAILABLE:
        return [{"label": "pyserial no disponible", "value": "NONE"}]
    ports = serial.tools.list_ports.comports()
    if not ports:
        return [{"label": "Sin puertos COM detectados", "value": "NONE"}]
    return [{"label": f"{p.device} — {p.description[:30]}", "value": p.device}
            for p in ports]


# ─────────────────────────────────────────────────────────────────────────────
# PALETA DE COLORES (idéntica al App.jsx original)
# ─────────────────────────────────────────────────────────────────────────────
C = {
    "bg":         "#f0f5f1",
    "white":      "#ffffff",
    "border":     "#d4e2d4",
    "accent":     "#16a34a",
    "accentDark": "#15803d",
    "accentLight":"#dcfce7",
    "accentBg":   "#f0fdf4",
    "text":       "#1a2e1a",
    "textMed":    "#3d5a3d",
    "dim":        "#6b8a6b",
    "red":        "#dc2626",
    "redLight":   "#fef2f2",
    "blue":       "#2563eb",
    "blueLight":  "#eff6ff",
    "purple":     "#7c3aed",
    "cyan":       "#0891b2",
    "orange":     "#ea580c",
    "header":     "#15803d",
}


def card(children, title=None, style=None):
    s = {
        "background": C["white"],
        "border": f'1px solid {C["border"]}',
        "borderRadius": 12,
        "padding": "16px 20px",
        "marginBottom": 0,
    }
    if style:
        s.update(style)
    inner = []
    if title:
        inner.append(html.Div([
            html.Div(style={"width": 4, "height": 14, "background": C["accent"],
                            "borderRadius": 2, "display": "inline-block",
                            "marginRight": 8, "verticalAlign": "middle"}),
            html.Span(title, style={"fontSize": 10, "fontWeight": 800,
                                    "textTransform": "uppercase", "letterSpacing": 1.6,
                                    "color": C["accentDark"], "verticalAlign": "middle"}),
        ], style={"marginBottom": 12}))
    inner.extend(children if isinstance(children, list) else [children])
    return html.Div(inner, style=s)


def stat_box(label, value, unit, color=None, bg=None):
    return html.Div([
        html.Div(value, style={"fontSize": 26, "fontWeight": 900,
                               "color": color or C["text"],
                               "fontFamily": "monospace", "lineHeight": 1.1}),
        html.Div(unit,  style={"fontSize": 10, "color": C["dim"], "marginTop": 2}),
        html.Div(label, style={"fontSize": 9,  "color": C["dim"],
                               "textTransform": "uppercase", "letterSpacing": 1}),
    ], style={"textAlign": "center", "padding": "8px 4px",
              "background": bg or C["white"],
              "border": f'1px solid {C["border"]}',
              "borderRadius": 12})


# ─────────────────────────────────────────────────────────────────────────────
# LAYOUT DE CADA TAB
# ─────────────────────────────────────────────────────────────────────────────
def tab_ubicacion():
    loc_buttons = []
    for i, loc in enumerate(LOCATIONS):
        loc_buttons.append(
            html.Button(loc["name"], id={"type": "btn-loc", "index": i},
                        n_clicks=0,
                        style={"padding": "6px 10px", "borderRadius": 8, "fontSize": 11,
                               "border": f'1px solid {C["border"]}',
                               "background": C["white"], "color": C["textMed"],
                               "cursor": "pointer", "width": "100%"})
        )
    return html.Div([
        html.Div([
            # Panel izquierdo
            html.Div([
                card([
                    html.Div(loc_buttons,
                             style={"display": "grid", "gridTemplateColumns": "1fr 1fr",
                                    "gap": 5, "marginBottom": 12}),
                    html.Div(id="custom-coords-container", children=[
                        html.Div("Latitud", style={"fontSize": 11, "color": C["dim"], "marginBottom": 3}),
                        dcc.Input(id="inp-lat", type="number", value=4.71, step=0.01,
                                  style={"width": "100%", "marginBottom": 8,
                                         "padding": "6px 10px", "borderRadius": 8,
                                         "border": f'1px solid {C["border"]}',
                                         "fontSize": 12, "fontFamily": "monospace"}),
                        html.Div("Longitud", style={"fontSize": 11, "color": C["dim"], "marginBottom": 3}),
                        dcc.Input(id="inp-lon", type="number", value=-74.07, step=0.01,
                                  style={"width": "100%", "marginBottom": 8,
                                         "padding": "6px 10px", "borderRadius": 8,
                                         "border": f'1px solid {C["border"]}',
                                         "fontSize": 12, "fontFamily": "monospace"}),
                    ], style={"display": "none"}),
                ], title="Ubicación"),

                card([
                    html.Div("Fecha inicio (YYYYMMDD)", style={"fontSize": 11, "color": C["dim"], "marginBottom": 3}),
                    dcc.Input(id="inp-start", type="text", value="20240315",
                              style={"width": "100%", "marginBottom": 10,
                                     "padding": "6px 10px", "borderRadius": 8,
                                     "border": f'1px solid {C["border"]}',
                                     "fontSize": 12, "fontFamily": "monospace"}),
                    html.Div("Fecha fin (YYYYMMDD)", style={"fontSize": 11, "color": C["dim"], "marginBottom": 3}),
                    dcc.Input(id="inp-end", type="text", value="20240317",
                              style={"width": "100%", "marginBottom": 12,
                                     "padding": "6px 10px", "borderRadius": 8,
                                     "border": f'1px solid {C["border"]}',
                                     "fontSize": 12, "fontFamily": "monospace"}),
                    html.Button("Descargar datos NASA POWER", id="btn-fetch-nasa",
                                n_clicks=0,
                                style={"width": "100%", "padding": "10px",
                                       "borderRadius": 10, "border": "none",
                                       "background": C["accent"], "color": "#fff",
                                       "fontWeight": 800, "fontSize": 12,
                                       "cursor": "pointer"}),
                    html.Div(id="nasa-status", style={"marginTop": 8, "fontSize": 11}),
                    html.Div([
                        "Parámetros: GHI · DNI · DHI · T2M · WS2M",
                        html.Br(), "Fuente: NASA POWER (CERES + MERRA-2)",
                    ], style={"marginTop": 10, "fontSize": 9, "color": C["dim"], "lineHeight": 1.6}),
                ], title="Rango de fechas"),
            ], style={"width": 290, "flexShrink": 0,
                      "display": "flex", "flexDirection": "column", "gap": 12}),

            # Panel derecho — gráficas
            html.Div([
                html.Div(id="irradiance-chart-container", children=[
                    html.Div("Selecciona ubicación y descarga datos para ver las gráficas.",
                             style={"textAlign": "center", "color": C["dim"],
                                    "padding": "80px 0", "fontSize": 13})
                ]),
            ], style={"flex": 1, "display": "flex", "flexDirection": "column", "gap": 12}),
        ], style={"display": "flex", "gap": 14}),
    ])


def tab_arreglo():
    slider_style = {"marginBottom": 12}

    def slider_row(label, id_, min_, max_, step_, value, unit, color):
        return html.Div([
            html.Div([
                html.Span(label, style={"fontSize": 12, "color": C["textMed"]}),
                html.Span(id=f"val-{id_}", style={"fontSize": 12, "fontWeight": 700,
                                                    "color": color, "fontFamily": "monospace"}),
            ], style={"display": "flex", "justifyContent": "space-between", "marginBottom": 3}),
            dcc.Slider(id=id_, min=min_, max=max_, step=step_, value=value,
                       marks=None, tooltip={"always_visible": False}),
            html.Div(id=f"unit-{id_}", children=unit,
                     style={"display": "none"}),  # guardamos la unidad
        ], style=slider_style)

    return html.Div([
        html.Div([
            card([
                slider_row("Paneles en serie (Ns)",  "sl-Ns",       1, 4,  1,    1,   "",      C["red"]),
                slider_row("Ramas en paralelo (Np)", "sl-Np",       1, 8,  1,    1,   "",      C["blue"]),
                html.Hr(style={"borderColor": C["border"], "margin": "8px 0"}),
                slider_row("Voc STC",                "sl-Voc",     30, 60, 0.5, 49.5, " V",    C["red"]),
                slider_row("Isc STC",                "sl-Isc",      5, 20, 0.1, 13.5, " A",    C["blue"]),
                slider_row("β Voc (V/°C)",           "sl-betaVoc", -0.3, 0, 0.01, -0.13, " V/°C", C["dim"]),
                slider_row("α Isc (A/°C)",           "sl-alphaIsc",  0, 0.005, 0.0001, 0.0005, " A/°C", C["dim"]),
                slider_row("NOCT (°C)",              "sl-noct",    40, 50, 1,   45,  " °C",   C["accent"]),
                slider_row("Inclinación (°)",        "sl-tilt",     0, 45, 1,   10,  "°",     C["dim"]),
                html.Hr(style={"borderColor": C["border"], "margin": "8px 0"}),
                html.Div("Modelo eléctrico", style={"fontSize": 10, "fontWeight": 800,
                                                    "color": C["dim"], "marginBottom": 6,
                                                    "textTransform": "uppercase", "letterSpacing": 1}),
                dcc.RadioItems(id="dd-model",
                    options=[
                        {"label": "  Simplificado (actual)", "value": "simplified"},
                        {"label": "  1 diodo — Villalva 2009", "value": "single_diode"},
                        {"label": "  2 diodos — Ishaque 2011", "value": "two_diode"},
                    ],
                    value="simplified",
                    labelStyle={"display": "block", "fontSize": 11,
                                "color": C["textMed"], "marginBottom": 5, "cursor": "pointer"}),
            ], title="Parámetros del módulo y arreglo"),
        ], style={"width": "48%"}),

        html.Div([
            card([html.Div(id="arreglo-diagram")],
                 title="Diagrama del arreglo"),
            card([html.Div(id="limites-check")],
                 title="Verificación de límites EA-PS 10060-170",
                 style={"marginTop": 12}),
        ], style={"width": "48%", "display": "flex", "flexDirection": "column", "gap": 12}),
    ], style={"display": "flex", "gap": 14})


def tab_perfiles():
    return html.Div([
        html.Div(id="perfiles-warning"),
        html.Div([
            html.Div([
                html.Span("Estrategia:", style={"fontSize": 11, "color": C["dim"]}),
                dcc.RadioItems(id="dd-strategy",
                    options=[
                        {"label": " Completa",        "value": "full"},
                        {"label": " Diurna (6–18h)", "value": "day"},
                        {"label": " Promedio",       "value": "average"},
                    ],
                    value="day", inline=True,
                    labelStyle={"marginLeft": 10, "fontSize": 11, "color": C["textMed"],
                                "cursor": "pointer"}),
            ], style={"display": "flex", "alignItems": "center", "gap": 8}),

            html.Div([
                html.Span("ms/paso:", style={"fontSize": 11, "color": C["dim"]}),
                dcc.Input(id="inp-dt", type="number", value=1000, min=200, step=100,
                          style={"width": 80, "padding": "5px 8px", "borderRadius": 8,
                                 "border": f'1px solid {C["border"]}',
                                 "fontSize": 12, "fontFamily": "monospace"}),
                html.Button("Exportar SeqLog CSV", id="btn-export-csv", n_clicks=0,
                            style={"padding": "7px 16px", "borderRadius": 8,
                                   "border": f'1px solid {C["accent"]}',
                                   "background": C["accentLight"], "color": C["accentDark"],
                                   "fontWeight": 700, "fontSize": 11, "cursor": "pointer"}),
                dcc.Download(id="download-csv"),
            ], style={"display": "flex", "alignItems": "center", "gap": 10}),
        ], style={"display": "flex", "justifyContent": "space-between",
                  "alignItems": "center", "marginBottom": 12}),

        # Stats
        html.Div(id="profile-stats",
                 style={"display": "grid", "gridTemplateColumns": "repeat(5, 1fr)",
                        "gap": 10, "marginBottom": 12}),

        card([dcc.Graph(id="chart-vi", config={"displayModeBar": False},
                        style={"height": 200})],
             title="Consignas V_set · I_set"),

        card([dcc.Graph(id="chart-pt", config={"displayModeBar": False},
                        style={"height": 180})],
             title="Potencia y temperatura de celda",
             style={"marginTop": 12}),
    ])


def tab_scpi():
    ports = list_serial_ports()
    return html.Div([
        html.Div([
            # Panel izquierdo — control
            card([
                # Selección de puerto
                html.Div("Puerto COM / USB", style={"fontSize": 11, "color": C["dim"], "marginBottom": 4}),
                dcc.Dropdown(id="dd-port",
                             options=ports,
                             value=ports[0]["value"] if ports else "NONE",
                             clearable=False,
                             style={"fontSize": 12, "marginBottom": 12}),

                html.Button("Conectar / verificar", id="btn-connect", n_clicks=0,
                            style={"width": "100%", "padding": "8px",
                                   "borderRadius": 8, "border": f'1px solid {C["border"]}',
                                   "background": C["accentBg"], "color": C["accentDark"],
                                   "fontWeight": 700, "fontSize": 11, "cursor": "pointer",
                                   "marginBottom": 8}),
                html.Div(id="connect-status",
                         style={"fontSize": 11, "marginBottom": 14}),

                html.Hr(style={"borderColor": C["border"]}),

                # Control manual
                html.Div("Control manual", style={"fontSize": 10, "fontWeight": 800,
                                                   "color": C["dim"], "textTransform": "uppercase",
                                                   "letterSpacing": 1, "marginBottom": 8}),
                html.Div([
                    html.Div([
                        html.Div("Voltaje (V)", style={"fontSize": 11, "color": C["dim"], "marginBottom": 3}),
                        dcc.Input(id="inp-manual-v", type="number", value=10.0,
                                  min=0, max=60, step=0.1,
                                  style={"width": "100%", "padding": "6px 8px",
                                         "borderRadius": 8, "border": f'1px solid {C["border"]}',
                                         "fontSize": 12, "fontFamily": "monospace"}),
                    ], style={"flex": 1}),
                    html.Div([
                        html.Div("Corriente (A)", style={"fontSize": 11, "color": C["dim"], "marginBottom": 3}),
                        dcc.Input(id="inp-manual-i", type="number", value=5.0,
                                  min=0, max=170, step=0.1,
                                  style={"width": "100%", "padding": "6px 8px",
                                         "borderRadius": 8, "border": f'1px solid {C["border"]}',
                                         "fontSize": 12, "fontFamily": "monospace"}),
                    ], style={"flex": 1}),
                ], style={"display": "flex", "gap": 8, "marginBottom": 10}),

                html.Div([
                    html.Button("OUTP ON", id="btn-outp-on", n_clicks=0,
                                style={"flex": 1, "padding": "8px",
                                       "borderRadius": 8, "border": "none",
                                       "background": C["accent"], "color": "#fff",
                                       "fontWeight": 800, "fontSize": 11, "cursor": "pointer"}),
                    html.Button("OUTP OFF", id="btn-outp-off", n_clicks=0,
                                style={"flex": 1, "padding": "8px",
                                       "borderRadius": 8, "border": "none",
                                       "background": C["red"], "color": "#fff",
                                       "fontWeight": 800, "fontSize": 11, "cursor": "pointer"}),
                ], style={"display": "flex", "gap": 8, "marginBottom": 14}),

                html.Div(id="manual-status", style={"fontSize": 11}),

                html.Hr(style={"borderColor": C["border"]}),

                # Ejecución del perfil
                html.Div("Ejecución del perfil", style={"fontSize": 10, "fontWeight": 800,
                                                          "color": C["dim"], "textTransform": "uppercase",
                                                          "letterSpacing": 1, "marginBottom": 8}),
                html.Div(id="exec-step-info",
                         style={"fontSize": 11, "color": C["dim"], "marginBottom": 8}),

                html.Div([
                    html.Button("EJECUTAR PERFIL", id="btn-exec-start", n_clicks=0,
                                style={"flex": 1, "padding": "10px",
                                       "borderRadius": 10, "border": "none",
                                       "background": C["accent"], "color": "#fff",
                                       "fontWeight": 800, "fontSize": 12, "cursor": "pointer"}),
                    html.Button("DETENER", id="btn-exec-stop", n_clicks=0,
                                style={"flex": 1, "padding": "10px",
                                       "borderRadius": 10, "border": "none",
                                       "background": C["red"], "color": "#fff",
                                       "fontWeight": 800, "fontSize": 12, "cursor": "pointer"}),
                ], style={"display": "flex", "gap": 8, "marginBottom": 10}),

                # Barra de progreso
                html.Div(style={"width": "100%", "height": 6,
                                "background": "#e8f0e8", "borderRadius": 4,
                                "overflow": "hidden"},
                         children=[html.Div(id="progress-bar",
                                            style={"width": "0%", "height": "100%",
                                                   "background": C["accent"],
                                                   "borderRadius": 4,
                                                   "transition": "width 0.3s"})]),
            ], title="Control SCPI — EA-PS 10060-170"),

            # Panel derecho — monitor
            card([
                # Live readout (se actualiza con dcc.Interval)
                html.Div(id="live-readout",
                         style={"display": "grid", "gridTemplateColumns": "1fr 1fr 1fr",
                                "gap": 10, "marginBottom": 14}),

                # Terminal SCPI
                html.Div("Comandos enviados", style={"fontSize": 10, "fontWeight": 800,
                                                      "color": C["dim"], "textTransform": "uppercase",
                                                      "letterSpacing": 1, "marginBottom": 6}),
                html.Div(id="scpi-terminal",
                         style={"background": "#1a2e1a", "borderRadius": 10,
                                "padding": 12, "maxHeight": 340,
                                "overflowY": "auto", "fontFamily": "monospace",
                                "fontSize": 10, "lineHeight": 1.8}),
                html.Div(id="scpi-summary",
                         style={"marginTop": 8, "fontSize": 10, "color": C["dim"]}),

                dcc.Interval(id="interval-live", interval=500, disabled=True),
            ], title="Monitor en tiempo real"),
        ], style={"display": "grid", "gridTemplateColumns": "340px 1fr", "gap": 14}),
    ])


def tab_resumen():
    return html.Div([
        html.Div(id="resumen-stats",
                 style={"display": "grid", "gridTemplateColumns": "repeat(4, 1fr)",
                        "gap": 10, "marginBottom": 12}),
        card([html.Div(id="resumen-config")], title="Configuración completa"),
        html.Div(style={"marginTop": 12},
                 children=[card([
                     dcc.Graph(id="chart-resumen", config={"displayModeBar": False},
                               style={"height": 200})
                 ], title="Perfil de operación")]),
    ])


# ─────────────────────────────────────────────────────────────────────────────
# APP DASH
# ─────────────────────────────────────────────────────────────────────────────
app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    suppress_callback_exceptions=True,
    title="PV Array Emulator",
)
server = app.server  # para despliegue futuro

app.layout = html.Div([
    # Almacén de datos en el cliente (no viajan al servidor hasta necesitarse)
    dcc.Store(id="store-nasa",    storage_type="memory"),
    dcc.Store(id="store-profile", storage_type="memory"),
    dcc.Store(id="store-loc-idx",  data=0),
    dcc.Store(id="store-scpi-log", data=[]),
    dcc.Store(id="store-exec-state", data={"running": False, "step": 0}),
    dcc.Interval(id="interval-exec", interval=300, disabled=True),

    # ── Header ────────────────────────────────────────────────────────────
    html.Div([
        html.Div([
            html.Div("PV", style={
                "width": 38, "height": 38, "borderRadius": 10,
                "background": "rgba(255,255,255,0.2)",
                "display": "flex", "alignItems": "center",
                "justifyContent": "center", "fontSize": 14,
                "fontWeight": 900, "color": "#fff",
            }),
            html.Div([
                html.Div("PV Array Emulator",
                         style={"fontSize": 16, "fontWeight": 800, "color": "#fff",
                                "letterSpacing": -0.3}),
                html.Div("EA-PS 10060-170 · NASA POWER · Microrred DC Uniandes",
                         style={"fontSize": 10, "color": "rgba(255,255,255,0.7)"}),
            ]),
        ], style={"display": "flex", "alignItems": "center", "gap": 14}),

        html.Div(id="header-live",
                 style={"display": "flex", "alignItems": "center", "gap": 14}),
    ], style={
        "background": f"linear-gradient(135deg, {C['header']}, #166534)",
        "padding": "12px 24px",
        "display": "flex",
        "alignItems": "center",
        "justifyContent": "space-between",
    }),

    # ── Tabs ──────────────────────────────────────────────────────────────
    dcc.Tabs(id="main-tabs", value="tab-0",
             children=[
                 dcc.Tab(label="Ubicación & Datos", value="tab-0"),
                 dcc.Tab(label="Arreglo PV",        value="tab-1"),
                 dcc.Tab(label="Perfiles",          value="tab-2"),
                 dcc.Tab(label="SCPI / Control",    value="tab-3"),
                 dcc.Tab(label="Resumen",           value="tab-4"),
             ],
             colors={"border": C["border"], "primary": C["accent"],
                     "background": C["white"]}),

    html.Div(id="tab-content",
             style={"padding": "16px 20px", "background": C["bg"],
                    "minHeight": "calc(100vh - 110px)"}),

], style={"fontFamily": "'Segoe UI', 'DM Sans', sans-serif",
          "background": C["bg"], "color": C["text"]})


# ─────────────────────────────────────────────────────────────────────────────
# CALLBACKS
# ─────────────────────────────────────────────────────────────────────────────

# Renderizar tab activa
@app.callback(Output("tab-content", "children"), Input("main-tabs", "value"))
def render_tab(tab):
    if tab == "tab-0": return tab_ubicacion()
    if tab == "tab-1": return tab_arreglo()
    if tab == "tab-2": return tab_perfiles()
    if tab == "tab-3": return tab_scpi()
    if tab == "tab-4": return tab_resumen()
    return html.Div()


# Guardar índice de ubicación
@app.callback(
    Output("store-loc-idx", "data"),
    [Input({"type": "btn-loc", "index": i}, "n_clicks") for i in range(9)],
    prevent_initial_call=True,
)
def set_location(*args):
    triggered = ctx.triggered_id
    if triggered and "index" in triggered:
        return triggered["index"]
    return 0


# Mostrar / ocultar coords personalizadas
@app.callback(
    Output("custom-coords-container", "style"),
    Input("store-loc-idx", "data"),
)
def toggle_custom(idx):
    base = {"display": "block"} if idx == 8 else {"display": "none"}
    return base


# Fetch NASA POWER
@app.callback(
    Output("store-nasa",   "data"),
    Output("nasa-status",  "children"),
    Input("btn-fetch-nasa", "n_clicks"),
    State("store-loc-idx", "data"),
    State("inp-lat",  "value"),
    State("inp-lon",  "value"),
    State("inp-start","value"),
    State("inp-end",  "value"),
    prevent_initial_call=True,
    running=[(Output("btn-fetch-nasa", "disabled"), True, False)],
)
def fetch_nasa_cb(n, loc_idx, lat, lon, start, end):
    loc = LOCATIONS[loc_idx]
    use_lat = lat if loc_idx == 8 else loc["lat"]
    use_lon = lon if loc_idx == 8 else loc["lon"]
    try:
        data = fetch_nasa(use_lat, use_lon, start, end)
        badge = html.Div(
            f"✓  {len(data)} registros horarios ({start[:4]}-{start[4:6]}-{start[6:]} → {end[:4]}-{end[4:6]}-{end[6:]})",
            style={"padding": "8px 12px", "background": C["accentLight"],
                   "border": f'1px solid #bbf7d0', "borderRadius": 8,
                   "color": C["accentDark"], "fontWeight": 600}
        )
        return data, badge
    except Exception as e:
        badge = html.Div(f"❌  {e}",
                         style={"padding": "8px 12px", "background": C["redLight"],
                                "border": "1px solid #fecaca", "borderRadius": 8,
                                "color": C["red"]})
        return no_update, badge


# Actualizar gráficas de irradiancia
@app.callback(
    Output("irradiance-chart-container", "children"),
    Input("store-nasa", "data"),
    State("store-loc-idx", "data"),
)
def update_irradiance_charts(data, loc_idx):
    if not data:
        return html.Div("Descarga datos para ver las gráficas.",
                        style={"textAlign": "center", "color": C["dim"],
                               "padding": "80px 0", "fontSize": 13})
    df = pd.DataFrame(data)
    loc_name = LOCATIONS[loc_idx]["name"]

    fig_irr = go.Figure()
    fig_irr.add_trace(go.Scatter(x=df["label"], y=df["ghi"], fill="tozeroy",
                                  name="GHI (W/m²)", line=dict(color=C["accent"], width=2)))
    fig_irr.add_trace(go.Scatter(x=df["label"], y=df["dni"], fill="tozeroy",
                                  name="DNI", line=dict(color=C["orange"], width=1.5),
                                  fillcolor="rgba(234,88,12,0.08)"))
    fig_irr.add_trace(go.Scatter(x=df["label"], y=df["dhi"], fill="tozeroy",
                                  name="DHI", line=dict(color=C["blue"], width=1),
                                  fillcolor="rgba(37,99,235,0.06)"))
    fig_irr.update_layout(
        title=f"Irradiancia — {loc_name}",
        height=210, margin=dict(t=30, b=20, l=30, r=10),
        paper_bgcolor="white", plot_bgcolor="white",
        legend=dict(font=dict(size=9)),
        xaxis=dict(tickfont=dict(size=8), dtick=max(1, len(df)//20)),
        yaxis=dict(tickfont=dict(size=9)),
    )

    fig_t = go.Figure()
    fig_t.add_trace(go.Scatter(x=df["label"], y=df["T2M"], name="T2M (°C)",
                                line=dict(color=C["cyan"], width=1.5)))
    fig_t.add_trace(go.Scatter(x=df["label"], y=df["WS"], name="Viento (m/s)",
                                line=dict(color=C["purple"], width=1), yaxis="y2"))
    fig_t.update_layout(
        height=150, margin=dict(t=10, b=20, l=30, r=30),
        paper_bgcolor="white", plot_bgcolor="white",
        legend=dict(font=dict(size=9)),
        xaxis=dict(tickfont=dict(size=8), dtick=max(1, len(df)//20)),
        yaxis=dict(tickfont=dict(size=9)),
        yaxis2=dict(overlaying="y", side="right", tickfont=dict(size=9)),
    )

    return [
        card([dcc.Graph(figure=fig_irr, config={"displayModeBar": False})],
             title=f"Irradiancia — {loc_name}"),
        card([dcc.Graph(figure=fig_t,   config={"displayModeBar": False})],
             title="Temperatura y viento",
             style={"marginTop": 12}),
    ]


# Valores de sliders en Tab 1
for sl_id, unit in [
    ("sl-Ns",""), ("sl-Np",""), ("sl-Voc"," V"), ("sl-Isc"," A"),
    ("sl-betaVoc"," V/°C"), ("sl-alphaIsc"," A/°C"), ("sl-noct"," °C"), ("sl-tilt","°"),
]:
    @app.callback(Output(f"val-{sl_id}", "children"),
                  Input(sl_id, "value"),
                  prevent_initial_call=False)
    def _update_label(v, _unit=unit):
        if isinstance(v, float) and abs(v) < 0.01 and v != 0:
            return f"{v:.4f}{_unit}"
        return f"{v}{_unit}"


# Diagrama del arreglo + verificación de límites
@app.callback(
    Output("arreglo-diagram", "children"),
    Output("limites-check",   "children"),
    Input("sl-Ns",  "value"), Input("sl-Np",  "value"),
    Input("sl-Voc", "value"), Input("sl-Isc", "value"),
)
def update_arreglo(Ns, Np, Voc, Isc):
    Ns = Ns or 1; Np = Np or 1
    cells = []
    for i in range(Ns * Np):
        cells.append(html.Div(
            f"{i//Ns+1},{i%Ns+1}",
            style={
                "width": min(48, 200//Ns), "height": min(28, 120//Np),
                "background": f"linear-gradient(135deg, {C['accentLight']}, #d1fae5)",
                "border": f"1.5px solid {C['accent']}44",
                "borderRadius": 4,
                "display": "flex", "alignItems": "center", "justifyContent": "center",
                "fontSize": 8, "color": C["accentDark"], "fontWeight": 600,
            }
        ))
    diagram = html.Div([
        html.Div(f"{Ns}s × {Np}p = {Ns*Np} módulos",
                 style={"fontSize": 11, "color": C["dim"], "fontWeight": 600, "marginBottom": 8}),
        html.Div(cells, style={"display": "grid",
                               "gridTemplateColumns": f"repeat({Ns}, 1fr)",
                               "gap": 4, "maxWidth": 240, "margin": "0 auto"}),
        html.Div([
            html.Span(f"V_oc = ", style={"fontSize": 11, "color": C["dim"]}),
            html.Span(f"{Voc*Ns:.1f} V", style={"color": C["red"], "fontFamily": "monospace", "fontWeight": 700}),
            html.Span("   I_sc = ", style={"fontSize": 11, "color": C["dim"]}),
            html.Span(f"{Isc*Np:.1f} A", style={"color": C["blue"], "fontFamily": "monospace", "fontWeight": 700}),
        ], style={"marginTop": 8, "textAlign": "center"}),
    ], style={"textAlign": "center", "padding": "12px 0"})

    checks = []
    for val, lim, u, lbl in [(Voc*Ns, V_MAX, "V", "Voltaje"), (Isc*Np, I_MAX, "A", "Corriente")]:
        ok = val <= lim
        checks.append(html.Div([
            html.Div(f"{lbl} máx equipo",  style={"fontSize": 10, "color": C["dim"]}),
            html.Div(f"{lim}{u}",          style={"fontSize": 18, "fontWeight": 900,
                                                    "fontFamily": "monospace",
                                                    "color": C["accent"] if ok else C["red"]}),
            html.Div(f"{'✓ OK' if ok else '⚠ CLIPPING'} ({val:.1f}{u})",
                     style={"fontSize": 10, "fontWeight": 600,
                            "color": C["accentDark"] if ok else C["red"]}),
        ], style={"padding": 12, "borderRadius": 10,
                  "background": C["accentLight"] if ok else C["redLight"],
                  "border": f"1px solid {'#bbf7d0' if ok else '#fecaca'}"}))

    limites = html.Div([
        html.Div(checks, style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": 10}),
        html.Div("EA-PS 10060-170: 5000W · Autoranging · Δt mín: 200ms",
                 style={"marginTop": 10, "padding": 10, "background": C["accentBg"],
                        "borderRadius": 8, "fontSize": 10, "color": C["textMed"]}),
    ])

    return diagram, limites


# Calcular perfil y actualizar Tab 2 + Store
@app.callback(
    Output("store-profile",       "data"),
    Output("profile-stats",       "children"),
    Output("chart-vi",            "figure"),
    Output("chart-pt",            "figure"),
    Output("perfiles-warning",    "children"),
    Input("store-nasa",   "data"),
    Input("sl-Ns",   "value"), Input("sl-Np",   "value"),
    Input("sl-Voc",  "value"), Input("sl-Isc",  "value"),
    Input("sl-betaVoc",  "value"), Input("sl-alphaIsc", "value"),
    Input("sl-noct", "value"), Input("sl-tilt",  "value"),
    Input("dd-model",    "value"),
    Input("dd-strategy", "value"),
    Input("inp-dt",      "value"),
)
def update_profile(data, Ns, Np, Voc, Isc, beta, alpha, noct, tilt, model, strategy, dt):
    if not data:
        warn = html.Div("⚠  Descarga datos ambientales en la pestaña 'Ubicación & Datos'",
                        style={"padding": "16px 20px", "background": C["redLight"],
                               "border": f"1px solid #fecaca",
                               "borderRadius": 10, "color": C["red"],
                               "marginBottom": 12, "fontWeight": 600, "fontSize": 13})
        empty_fig = go.Figure()
        empty_fig.update_layout(height=180, paper_bgcolor="white", plot_bgcolor="white")
        return no_update, [], empty_fig, empty_fig, warn

    full   = compute_pv(data, Ns or 1, Np or 1, Voc, Isc, beta, alpha, noct, tilt, model)
    prof   = apply_strategy(full, strategy)
    dt_ms  = max(dt or 200, DT_MIN)
    lab_s  = len(prof) * dt_ms / 1000

    if not prof:
        return [], [], go.Figure(), go.Figure(), no_update

    peak_P = max(d["P_set"] for d in prof)
    peak_V = max(d["V_set"] for d in prof)
    peak_I = max(d["I_set"] for d in prof)
    total_E = sum(d["P_set"] for d in prof) / 1000

    stats = [
        stat_box("Potencia pico", f"{peak_P:.0f}",   "W",   C["accent"]),
        stat_box("Voltaje pico",  f"{peak_V:.1f}",   "V",   C["red"]),
        stat_box("Corriente pico",f"{peak_I:.1f}",   "A",   C["blue"]),
        stat_box("Energía",       f"{total_E:.2f}",  "kWh", C["accentDark"]),
        stat_box("Duración lab",  f"{lab_s:.1f}",    "seg", C["purple"]),
    ]

    labels = [d["label"] for d in prof]

    fig_vi = go.Figure()
    fig_vi.add_trace(go.Scatter(x=labels, y=[d["V_set"] for d in prof],
                                 name="V (V)", line=dict(color=C["red"], width=2, shape="hv")))
    fig_vi.add_trace(go.Scatter(x=labels, y=[d["I_set"] for d in prof],
                                 name="I (A)", line=dict(color=C["blue"], width=2, shape="hv"),
                                 yaxis="y2"))
    fig_vi.update_layout(
        height=190, margin=dict(t=10, b=20, l=30, r=40),
        paper_bgcolor="white", plot_bgcolor="white",
        legend=dict(font=dict(size=9)),
        xaxis=dict(tickfont=dict(size=8), dtick=max(1, len(prof)//24)),
        yaxis=dict(tickfont=dict(size=9), range=[0, 65]),
        yaxis2=dict(overlaying="y", side="right", tickfont=dict(size=9)),
    )

    fig_pt = go.Figure()
    fig_pt.add_trace(go.Scatter(x=labels, y=[d["P_set"] for d in prof],
                                 name="P (W)", fill="tozeroy",
                                 line=dict(color=C["accent"], width=2),
                                 fillcolor=f"rgba(22,163,74,0.12)"))
    fig_pt.add_trace(go.Scatter(x=labels, y=[d["Tcell"] for d in prof],
                                 name="T_cell (°C)", line=dict(color=C["cyan"], width=1.5),
                                 yaxis="y2"))
    fig_pt.update_layout(
        height=170, margin=dict(t=10, b=20, l=30, r=40),
        paper_bgcolor="white", plot_bgcolor="white",
        legend=dict(font=dict(size=9)),
        xaxis=dict(tickfont=dict(size=8), dtick=max(1, len(prof)//24)),
        yaxis=dict(tickfont=dict(size=9)),
        yaxis2=dict(overlaying="y", side="right", tickfont=dict(size=9)),
    )

    return prof, stats, fig_vi, fig_pt, html.Div()


# Exportar SeqLog CSV
@app.callback(
    Output("download-csv", "data"),
    Input("btn-export-csv", "n_clicks"),
    State("store-profile", "data"),
    State("inp-dt", "value"),
    prevent_initial_call=True,
)
def export_csv(n, profile, dt):
    if not profile:
        return no_update
    csv_str = export_seqlog_csv(profile, dt or 1000)
    return {"content": csv_str, "filename": "perfil_seqlog.csv", "type": "text/csv"}


# Conectar / verificar puerto SCPI
@app.callback(
    Output("connect-status", "children"),
    Input("btn-connect", "n_clicks"),
    State("dd-port", "value"),
    prevent_initial_call=True,
)
def connect_scpi(n, port):
    if not SERIAL_AVAILABLE:
        return html.Div("⚠  pyserial no disponible. Instalar: pip install pyserial",
                        style={"color": C["red"], "fontSize": 11})
    if not port or port == "NONE":
        return html.Div("Selecciona un puerto COM primero.",
                        style={"color": C["red"], "fontSize": 11})
    try:
        _controller.port = port
        idn = _controller.connect()
        return html.Div(f"✓  Conectado: {idn[:50]}",
                        style={"color": C["accentDark"], "fontWeight": 600, "fontSize": 11})
    except Exception as e:
        return html.Div(f"❌  {e}", style={"color": C["red"], "fontSize": 11})


# Control manual OUTP ON / OFF
@app.callback(
    Output("manual-status", "children"),
    Output("store-scpi-log", "data"),
    Input("btn-outp-on",  "n_clicks"),
    Input("btn-outp-off", "n_clicks"),
    State("inp-manual-v",  "value"),
    State("inp-manual-i",  "value"),
    State("store-scpi-log","data"),
    prevent_initial_call=True,
)
def manual_control(n_on, n_off, V, I, log):
    triggered = ctx.triggered_id
    log = log or []
    try:
        if triggered == "btn-outp-on":
            _controller.set_output(V or 0, I or 0, on=True)
            cmds = [f"VOLT {V:.3f}", f"CURR {I:.3f}", "OUTP ON"]
            log.extend(cmds)
            return html.Div(f"✓  Salida ON  —  {V} V · {I} A",
                            style={"color": C["accentDark"], "fontWeight": 600}), log[-60:]
        else:
            _controller.send("OUTP OFF")
            log.append("OUTP OFF")
            return html.Div("■  Salida OFF",
                            style={"color": C["red"], "fontWeight": 600}), log[-60:]
    except Exception as e:
        return html.Div(f"❌  {e}", style={"color": C["red"]}), log


# Ejecutar / detener perfil completo en la fuente
@app.callback(
    Output("interval-exec",    "disabled"),
    Output("store-exec-state", "data"),
    Input("btn-exec-start",    "n_clicks"),
    Input("btn-exec-stop",     "n_clicks"),
    State("store-profile",     "data"),
    State("inp-dt",            "value"),
    State("dd-port",           "value"),
    State("store-exec-state",  "data"),
    prevent_initial_call=True,
)
def toggle_exec(n_start, n_stop, profile, dt, port, state):
    global _exec_thread, _controller
    triggered = ctx.triggered_id

    if triggered == "btn-exec-stop":
        _controller.stop()
        return True, {"running": False, "step": 0}

    if triggered == "btn-exec-start":
        if not profile:
            return True, state
        _controller.port = port or "COM3"
        dt_ms = max(dt or 1000, DT_MIN)

        def run():
            try:
                _controller.connect()
                _controller.run_profile(profile, dt_ms)
            except Exception as e:
                print(f"[SCPI ERROR] {e}")

        _exec_thread = threading.Thread(target=run, daemon=True)
        _exec_thread.start()
        return False, {"running": True, "step": 0}

    return True, state


# Actualizar barra de progreso e info del paso actual
@app.callback(
    Output("progress-bar",    "style"),
    Output("exec-step-info",  "children"),
    Output("live-readout",    "children"),
    Input("interval-exec",    "n_intervals"),
    State("store-profile",    "data"),
    State("store-exec-state", "data"),
)
def update_exec_progress(n, profile, state):
    if not profile or not state.get("running"):
        return {"width": "0%", "height": "100%", "background": C["accent"],
                "borderRadius": 4, "transition": "width 0.3s"}, \
               "Sin perfil en ejecución.", []

    # Aproximar el paso actual por tiempo transcurrido
    # (el controlador real lleva el paso internamente)
    total = len(profile)
    pct   = min(100, (n % (total + 1)) / total * 100) if total else 0
    step  = profile[min(int(n % total), total-1)] if profile else {}

    bar_style = {"width": f"{pct:.0f}%", "height": "100%",
                 "background": C["accent"], "borderRadius": 4, "transition": "width 0.3s"}
    info = f"Ejecutando perfil — {total} pasos · Δt mín {DT_MIN} ms"

    readout = []
    for label, val, unit, color, bg in [
        ("VOLT", step.get("V_set", 0), "V",  C["red"],    C["redLight"]),
        ("CURR", step.get("I_set", 0), "A",  C["blue"],   C["blueLight"]),
        ("POWER",step.get("P_set", 0), "W",  C["accent"], C["accentLight"]),
    ]:
        readout.append(html.Div([
            html.Div(f"{val}", style={"fontSize": 22, "fontWeight": 900,
                                      "color": color, "fontFamily": "monospace"}),
            html.Div(f"{label} ({unit})", style={"fontSize": 9, "color": C["dim"], "fontWeight": 600}),
        ], style={"padding": 12, "background": bg, "borderRadius": 10,
                  "textAlign": "center", "border": f"1px solid {color}22"}))

    return bar_style, info, readout


# Renderizar terminal SCPI
@app.callback(
    Output("scpi-terminal", "children"),
    Output("scpi-summary",  "children"),
    Input("store-scpi-log", "data"),
    Input("store-profile",  "data"),
)
def update_terminal(log, profile):
    if not profile:
        cmds_from_profile = []
    else:
        cmds_from_profile = [
            f"VOLT {s['V_set']:.3f}",
            f"CURR {s['I_set']:.3f}",
            f"# wait {DT_MIN}ms",
        ] * min(10, len(profile))

    all_cmds = (["SYST:REM:TRAN ON", "OUTP ON"] + cmds_from_profile +
                ["...", "OUTP OFF"] + (log or []))[:60]

    lines = []
    for i, cmd in enumerate(all_cmds):
        color = "#6b8a6b" if cmd.startswith("#") or cmd == "..." else "#4ade80"
        lines.append(html.Div([
            html.Span(f"{i+1:03d}",  style={"color": "#4a6a4a", "marginRight": 10}),
            html.Span(cmd, style={"color": color}),
        ]))

    total = len(profile) * 3 + 4 if profile else 0
    summary = f"Total estimado: {total} comandos · SCPI (ASCII) · USB/COM · Δt {DT_MIN} ms/paso"
    return lines, summary


# Tab Resumen
@app.callback(
    Output("resumen-stats",  "children"),
    Output("resumen-config", "children"),
    Output("chart-resumen",  "figure"),
    Input("store-profile",  "data"),
    State("store-loc-idx",  "data"),
    State("sl-Ns",  "value"), State("sl-Np",  "value"),
    State("sl-Voc", "value"), State("sl-Isc", "value"),
    State("sl-noct","value"), State("sl-tilt","value"),
    State("dd-model","value"),
    State("dd-strategy","value"),
    State("inp-dt","value"),
    State("inp-start","value"), State("inp-end","value"),
)
def update_resumen(profile, loc_idx, Ns, Np, Voc, Isc, noct, tilt, model, strategy, dt, start, end):
    if not profile:
        return [], html.Div("Sin datos aún.", style={"color": C["dim"]}), go.Figure()

    peak_P  = max(d["P_set"] for d in profile)
    total_E = sum(d["P_set"] for d in profile) / 1000
    lab_s   = len(profile) * max(dt or 1000, DT_MIN) / 1000
    loc     = LOCATIONS[loc_idx or 0]

    stats = [
        stat_box("Potencia pico", f"{peak_P:.0f}",        "W",   C["accent"]),
        stat_box("Energía",       f"{total_E:.2f}",       "kWh", C["accentDark"]),
        stat_box("Módulos",       f"{(Ns or 1)*(Np or 1)}",
                 f"{Ns or 1}s×{Np or 1}p", C["blue"]),
        stat_box("Duración",      f"{lab_s:.0f}",         "seg", C["purple"]),
    ]

    config_items = [
        ("Ubicación",  [f"{loc['name']}", f"{loc['lat']}°, {loc['lon']}°",
                        f"{start} → {end}", "Fuente: NASA POWER"]),
        ("Arreglo PV", [f"{Ns}s × {Np}p ({(Ns or 1)*(Np or 1)} módulos)",
                        f"Voc: {Voc}V · Isc: {Isc}A",
                        f"NOCT: {noct}°C · Tilt: {tilt}°",
                        f"Modelo: {model}"]),
        ("Emulación",  [f"Estrategia: {strategy}", f"{dt} ms/paso",
                        f"{len(profile)} pasos", f"Δt mín: {DT_MIN}ms"]),
        ("Equipo",     ["EA-PS 10060-170", "60V / 170A / 5kW",
                        "SCPI (ASCII)", "OVP / OCP / OPP / OT"]),
    ]
    cfg_div = html.Div([
        html.Div([
            html.Div(t, style={"fontWeight": 800, "color": C["accentDark"], "fontSize": 10,
                               "textTransform": "uppercase", "letterSpacing": 1.2,
                               "marginBottom": 8}),
            html.Div([html.Div(l, style={"color": C["textMed"], "lineHeight": 1.8,
                                         "fontSize": 11}) for l in lines]),
        ])
        for t, lines in config_items
    ], style={"display": "grid", "gridTemplateColumns": "repeat(4, 1fr)",
               "gap": 20, "fontSize": 11})

    labels = [d["label"] for d in profile]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=labels, y=[d["P_set"] for d in profile],
                              fill="tozeroy", name="P (W)",
                              line=dict(color=C["accent"], width=2),
                              fillcolor="rgba(22,163,74,0.1)"))
    fig.add_trace(go.Scatter(x=labels, y=[d["V_set"] for d in profile],
                              name="V (V)", line=dict(color=C["red"], width=1.5, shape="hv"),
                              yaxis="y2"))
    fig.update_layout(
        height=190, margin=dict(t=10, b=20, l=30, r=40),
        paper_bgcolor="white", plot_bgcolor="white",
        legend=dict(font=dict(size=9)),
        xaxis=dict(tickfont=dict(size=8), dtick=max(1, len(profile)//20)),
        yaxis=dict(tickfont=dict(size=9)),
        yaxis2=dict(overlaying="y", side="right", tickfont=dict(size=9)),
    )

    return stats, cfg_div, fig


# Header live (ubicación + estado NASA)
@app.callback(
    Output("header-live", "children"),
    Input("store-nasa",   "data"),
    Input("store-loc-idx","data"),
    State("sl-Ns", "value"), State("sl-Np", "value"),
)
def update_header(data, loc_idx, Ns, Np):
    loc  = LOCATIONS[loc_idx or 0]
    nasa = html.Div(f"NASA ✓  {len(data)}h",
                    style={"fontSize": 9, "padding": "3px 10px",
                           "background": "rgba(255,255,255,0.15)",
                           "borderRadius": 6, "color": "#bbf7d0",
                           "fontWeight": 600}) if data else html.Div()
    loc_div = html.Div(f"{loc['name']} · {Ns or 1}s{Np or 1}p",
                       style={"fontSize": 10, "color": "rgba(255,255,255,0.6)"})
    return [loc_div, nasa]


# ─────────────────────────────────────────────────────────────────────────────
# PUNTO DE ENTRADA
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    desktop_mode = "--desktop" in sys.argv

    if desktop_mode:
        try:
            import webview
            t = threading.Thread(target=lambda: app.run(debug=False, port=8050), daemon=True)
            t.start()
            time.sleep(1.5)  # esperar que Dash arranque
            webview.create_window("PV Array Emulator",
                                  "http://localhost:8050",
                                  width=1280, height=800,
                                  resizable=True)
            webview.start()
        except ImportError:
            print("pywebview no instalado. Usando modo navegador.")
            app.run(debug=False, port=8050)
    else:
        print("\n  PV Array Emulator — Dash HMI")
        print("  http://localhost:8050\n")
        app.run(debug=True, port=8050)
