"""
config/hardware.py
==================
Constantes de hardware y paleta de colores de la HMI.
Migradas de las variables globales V_MAX, I_MAX, DT_MIN y el dict C en app.py.

Importar así en cualquier módulo:
    from config.hardware import V_MAX, I_MAX, DT_MIN, C
"""

# ── Límites eléctricos EA-PS 10060-170 ───────────────────────────────────────
# Fuente: Manual EA-PS 10000 3U, documento 06230820_EN
V_MAX:  float = 60.0    # V  — voltaje máximo de salida
I_MAX:  float = 170.0   # A  — corriente máxima de salida
P_MAX:  float = 5000.0  # W  — potencia máxima nominal
DT_MIN: int   = 200     # ms — intervalo mínimo estable entre comandos
                         #      validado experimentalmente (sección VI del doc.)

# Puerto serie por defecto — sobreescribir desde la HMI o el CLI
DEFAULT_PORT: str   = "COM3"
DEFAULT_BAUD: int   = 115200
DEFAULT_TIMEOUT: float = 2.0   # s

# ── Paleta de colores de la HMI ───────────────────────────────────────────────
# Esquema verde industrial — idéntico al App.jsx original para mantener
# coherencia visual durante la migración a Dash.
C: dict[str, str] = {
    # Fondos
    "bg":          "#f0f5f1",
    "white":       "#ffffff",
    "panel":       "#ffffff",
    # Bordes
    "border":      "#d4e2d4",
    "borderLight": "#e8f0e8",
    # Acento principal (verde)
    "accent":      "#16a34a",
    "accentDark":  "#15803d",
    "accentLight": "#dcfce7",
    "accentBg":    "#f0fdf4",
    # Texto
    "text":        "#1a2e1a",
    "textMed":     "#3d5a3d",
    "dim":         "#6b8a6b",
    # Semánticos
    "red":         "#dc2626",
    "redLight":    "#fef2f2",
    "blue":        "#2563eb",
    "blueLight":   "#eff6ff",
    "purple":      "#7c3aed",
    "cyan":        "#0891b2",
    "orange":      "#ea580c",
    # Grilla de gráficas
    "grid":        "#e2ece2",
    # Header
    "header":      "#15803d",
}
