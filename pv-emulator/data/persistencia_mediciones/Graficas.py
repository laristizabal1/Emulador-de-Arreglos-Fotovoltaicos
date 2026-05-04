"""
Análisis comparativo de sesiones de emulación fotovoltaica
──────────────────────────────────────────────────────────
Compara tres modelos eléctricos (Simplificado, Un diodo, Dos diodos)
a partir de archivos JSON generados por el emulador.

Estilo: calidad de publicación IEEE / Elsevier (doble columna, 300 DPI, serif).
Uso   : solo cambiar CARPETA_JSON al inicio.
"""

import json
import warnings
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.backends.backend_pdf import PdfPages

matplotlib.use("Agg")
warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN  ← solo cambia esta variable
# ─────────────────────────────────────────────────────────────────────────────
CARPETA_JSON = Path(r"C:\Users\Lenovo\OneDrive - Universidad de los Andes\Documentos\Universidad\Tallerpot\pv-emulator\data\persistencia_mediciones")
CARPETA_OUT  = Path(r"C:\Users\Lenovo\OneDrive - Universidad de los Andes\Documentos\Universidad\Tallerpot\pv-emulator\data\persistencia_mediciones\graficas")
# ─────────────────────────────────────────────────────────────────────────────
# PARÁMETROS GLOBALES — estilo publicación académica IEEE / Elsevier
# ─────────────────────────────────────────────────────────────────────────────
plt.rcParams.update({
    # Tipografía — Liberation Serif es métrica-compatible con Times New Roman
    "font.family":          "serif",
    "font.serif":           ["Liberation Serif", "Times New Roman",
                             "DejaVu Serif", "Palatino"],
    "mathtext.fontset":     "dejavuserif",

    # Tamaños de fuente (≥ 11 pt ejes, ≥ 10 pt ticks, ≤ 9 pt leyenda)
    "font.size":            10,
    "axes.labelsize":       11,
    "axes.titlesize":       11,
    "xtick.labelsize":      10,
    "ytick.labelsize":      10,
    "legend.fontsize":      8.5,
    "legend.title_fontsize": 9,

    # Resolución
    "figure.dpi":           150,
    "savefig.dpi":          300,

    # Spines: solo abajo e izquierda
    "axes.spines.top":      False,
    "axes.spines.right":    False,
    "axes.linewidth":       0.8,

    # Grilla mayor + menor
    "axes.grid":            True,
    "grid.color":           "#cccccc",
    "grid.linestyle":       "--",
    "grid.linewidth":       0.45,
    "grid.alpha":           0.7,

    # Ticks hacia adentro
    "xtick.direction":      "in",
    "ytick.direction":      "in",
    "xtick.major.size":     4.0,
    "ytick.major.size":     4.0,
    "xtick.minor.size":     2.5,
    "ytick.minor.size":     2.5,
    "xtick.minor.visible":  True,
    "ytick.minor.visible":  True,

    # Leyenda
    "legend.framealpha":    0.90,
    "legend.edgecolor":     "#999999",
    "legend.borderpad":     0.5,
    "legend.handlelength":  2.4,
    "legend.fancybox":      False,

    # Layout
    "figure.constrained_layout.use": True,
})

# ─────────────────────────────────────────────────────────────────────────────
# IDENTIDAD VISUAL POR MODELO
# Paleta apta para daltonismo (Wong 2011 / IBM Design)
# Líneas: consigna → dashes, medición → sólida + marcador
# ─────────────────────────────────────────────────────────────────────────────
MODELOS = {
    "simplified": {
        "nombre":  "Simplificado",
        "color":   "#0072B2",          # azul Wong
        "ls_dc":   "-",
        "ls_set":  (0, (5, 2.5)),      # dash largo
        "marker":  "o",
        "ms":      4.0,
        "zorder":  4,
    },
    "single_diode": {
        "nombre":  "Un diodo",
        "color":   "#D55E00",          # vermellón Wong
        "ls_dc":   "-",
        "ls_set":  (0, (4, 2)),        # dash medio
        "marker":  "s",
        "ms":      3.8,
        "zorder":  3,
    },
    "two_diode": {
        "nombre":  "Dos diodos",
        "color":   "#009E73",          # verde Wong
        "ls_dc":   "-",
        "ls_set":  (0, (1.5, 2)),      # punteado
        "marker":  "^",
        "ms":      4.5,
        "zorder":  2,
    },
}

# Ancho doble columna IEEE ≈ 7.16 in; relación 3:2
FIG_W = 7.0
FIG_H = FIG_W / 1.55            # ≈ 4.52 in
FIG_H_COMPACT = 3.2             # para paneles del subplot compuesto
LW_SET = 1.2                    # linewidth consigna
LW_DC  = 1.8                    # linewidth medición

# ─────────────────────────────────────────────────────────────────────────────
# 1. CARGA Y PREPROCESAMIENTO
# ─────────────────────────────────────────────────────────────────────────────

def cargar_sesiones(carpeta):
    sesiones = {}
    for archivo in sorted(carpeta.glob("sesion_*.json")):
        with open(archivo, encoding="utf-8") as f:
            datos = json.load(f)
        key = datos["perfil"]["modelo_key"]
        sesiones[key] = datos
        print(f"  ✔  {archivo.name}  →  {key!r}  "
              f"({datos['sesion']['n_muestras']} muestras)")
    return sesiones


def _orden_horas(horas):
    return sorted(horas.unique(), key=lambda h: int(h.rstrip("h")))


def procesar_sesion(datos):
    med = pd.DataFrame(datos["mediciones"])
    cols = ["V_dc", "I_dc", "P_dc", "V_set", "I_set", "P_set"]
    grupo = med.groupby("hora_emulada")[cols].median().reset_index()
    grupo["error_P"]     = grupo["P_set"] - grupo["P_dc"]
    grupo["error_V"]     = grupo["V_set"] - grupo["V_dc"]
    grupo["error_I"]     = grupo["I_set"] - grupo["I_dc"]
    grupo["eta_mppt"]    = np.where(
        grupo["P_set"] > 0, grupo["P_dc"] / grupo["P_set"] * 100, np.nan)
    grupo["abs_error_P"] = grupo["error_P"].abs()
    orden = _orden_horas(grupo["hora_emulada"])
    grupo["hora_emulada"] = pd.Categorical(
        grupo["hora_emulada"], categories=orden, ordered=True)
    return grupo.sort_values("hora_emulada").reset_index(drop=True)


def tabla_resumen(resultados):
    filas = []
    for key, df in resultados.items():
        mask = df["P_set"] > 0
        filas.append({
            "Modelo":    MODELOS[key]["nombre"],
            "RMSE_P":    round(np.sqrt((df.loc[mask, "error_P"]**2).mean()), 2),
            "MAE_P":     round(df.loc[mask, "abs_error_P"].mean(), 2),
            "eta_mppt":  round(df.loc[mask, "eta_mppt"].mean(), 1),
            "V_dc_prom": round(df.loc[mask, "V_dc"].mean(), 2),
            "I_dc_prom": round(df.loc[mask, "I_dc"].mean(), 2),
        })
    return pd.DataFrame(filas)


# ─────────────────────────────────────────────────────────────────────────────
# 2. UTILIDADES DE GRAFICACIÓN
# ─────────────────────────────────────────────────────────────────────────────

def _meta(sesiones):
    p = next(iter(sesiones.values()))["perfil"]
    return {
        "ciudad":     p.get("ciudad", "—"),
        "estrategia": p.get("estrategia", "—"),
        "r_ini":      p.get("nasa_rango_inicio", "") or "—",
        "r_fin":      p.get("nasa_rango_fin",   "") or "—",
    }


def _subtitulo(meta):
    return (f"{meta['ciudad']} · {meta['estrategia']} · "
            f"NASA {meta['r_ini']}–{meta['r_fin']}")


def _filtrar_horas_activas(resultados):
    """Excluye horas donde TODOS los modelos tienen P_set == 0."""
    primer = next(iter(resultados.values()))
    horas  = list(primer["hora_emulada"])
    activas = []
    for i, h in enumerate(horas):
        if any(df["P_set"].iloc[i] > 0 for df in resultados.values()):
            activas.append(i)
    return activas


def _eje_x(ax, horas, indices_activos=None):
    if indices_activos is not None:
        labels = [horas[i] for i in indices_activos]
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=0)
    else:
        ax.set_xticks(range(len(horas)))
        ax.set_xticklabels(list(horas), rotation=0)
    ax.set_xlabel("Hora del día [h]", fontweight="bold")


def _grilla_menor(ax):
    ax.grid(which="minor", color="#e0e0e0", linestyle=":", linewidth=0.3,
            alpha=0.5)
    ax.minorticks_on()


def _guardar_dual(fig, nombre_base, carpeta):
    """Guarda versión screen (PNG 150 dpi) y print (PDF vectorial)."""
    carpeta.mkdir(parents=True, exist_ok=True)
    # PNG screen
    ruta_png = carpeta / f"{nombre_base}_screen.png"
    fig.savefig(ruta_png, dpi=150, bbox_inches="tight", facecolor="white")
    print(f"  💾  {ruta_png}")
    # PDF vectorial
    ruta_pdf = carpeta / f"{nombre_base}_print.pdf"
    fig.savefig(ruta_pdf, bbox_inches="tight", facecolor="white")
    print(f"  💾  {ruta_pdf}")
    plt.close(fig)


def _leyenda_par(ax, modelos_activos, loc="best"):
    """
    Leyenda explícita: cada entrada dice «Modelo — tipo».
    Fila 1: todas las consignas.  Fila 2: todas las mediciones.
    ncol = n_modelos → queda en forma de tabla 2×3.
    """
    handles, labels = [], []

    # Fila 1 — Consignas (set point)
    for key in modelos_activos:
        m = MODELOS[key]
        handles.append(Line2D([0], [0], color=m["color"], linewidth=LW_SET + 0.3,
                               linestyle=m["ls_set"], alpha=0.75))
        labels.append(f"{m['nombre']} — consigna")

    # Fila 2 — Mediciones DC
    for key in modelos_activos:
        m = MODELOS[key]
        handles.append(Line2D([0], [0], color=m["color"], linewidth=LW_DC,
                               linestyle=m["ls_dc"], marker=m["marker"],
                               markersize=m["ms"] + 0.5, markevery=[0]))
        labels.append(f"{m['nombre']} — medición DC")

    ax.legend(handles, labels,
              ncol=len(modelos_activos),
              columnspacing=1.2,
              handletextpad=0.5,
              handlelength=2.8,
              loc=loc,
              framealpha=0.92,
              edgecolor="#999999",
              fontsize=7.8)


# ─────────────────────────────────────────────────────────────────────────────
# 3. FIGURAS INDIVIDUALES
# ─────────────────────────────────────────────────────────────────────────────

def fig_variable(resultados, col_set, col_dc, ylabel, nombre_base,
                 carpeta):
    """Figura individual de una variable (P, V o I) — sin título grande."""
    fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))
    primer  = next(iter(resultados.values()))
    horas   = list(primer["hora_emulada"])
    idx_act = _filtrar_horas_activas(resultados)
    x       = list(range(len(idx_act)))

    for key, df in resultados.items():
        m = MODELOS[key]
        y_set = [df[col_set].iloc[i] for i in idx_act]
        y_dc  = [df[col_dc].iloc[i]  for i in idx_act]
        ax.plot(x, y_set, color=m["color"], linestyle=m["ls_set"],
                linewidth=LW_SET, alpha=0.70, zorder=m["zorder"])
        ax.plot(x, y_dc,  color=m["color"], linestyle=m["ls_dc"],
                linewidth=LW_DC, marker=m["marker"], markersize=m["ms"],
                zorder=m["zorder"])

    _eje_x(ax, horas, idx_act)
    ax.set_ylabel(ylabel, fontweight="bold")
    _grilla_menor(ax)
    _leyenda_par(ax, list(resultados.keys()))
    _guardar_dual(fig, nombre_base, carpeta)


def fig_eficiencia(resultados, carpeta):
    """Eficiencia MPPT — sin título, con anotación de max η por modelo."""
    fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))
    primer  = next(iter(resultados.values()))
    horas   = list(primer["hora_emulada"])
    idx_act = _filtrar_horas_activas(resultados)
    x       = list(range(len(idx_act)))

    ax.axhline(100, color="#888888", linestyle="--", linewidth=0.9,
               zorder=1, label="Referencia 100 %")

    for key, df in resultados.items():
        m   = MODELOS[key]
        eta = [df["eta_mppt"].iloc[i] for i in idx_act]
        ax.plot(x, eta, color=m["color"], linestyle=m["ls_dc"],
                linewidth=LW_DC, marker=m["marker"], markersize=m["ms"],
                label=m["nombre"], zorder=m["zorder"])

        # Anotación: valor máximo de η con flecha
        eta_arr = np.array(eta)
        valid   = ~np.isnan(eta_arr)
        if valid.any():
            i_max   = np.nanargmax(eta_arr)
            eta_max = eta_arr[i_max]
            ax.annotate(
                f'{eta_max:.1f}%',
                xy=(x[i_max], eta_max),
                xytext=(0, 14), textcoords="offset points",
                color=m["color"], fontsize=8, fontweight="bold",
                ha="center", va="bottom",
                arrowprops=dict(arrowstyle="-|>", color=m["color"],
                                lw=0.8, shrinkA=0, shrinkB=2))

    _eje_x(ax, horas, idx_act)
    ax.set_ylabel(r"Eficiencia MPPT, $\eta$ [%]", fontweight="bold")
    ax.set_ylim(0, 130)
    ax.yaxis.set_major_locator(ticker.MultipleLocator(20))
    _grilla_menor(ax)
    ax.legend(loc="lower right", framealpha=0.90, edgecolor="#999999")
    _guardar_dual(fig, "fig4_eficiencia_mppt", carpeta)


def fig_error_potencia(resultados, carpeta):
    """Error absoluto de potencia — sin título."""
    fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))
    primer  = next(iter(resultados.values()))
    horas   = list(primer["hora_emulada"])
    idx_act = _filtrar_horas_activas(resultados)
    x       = list(range(len(idx_act)))

    for key, df in resultados.items():
        m = MODELOS[key]
        y = [df["abs_error_P"].iloc[i] for i in idx_act]
        ax.plot(x, y, color=m["color"], linestyle=m["ls_dc"],
                linewidth=LW_DC, marker=m["marker"], markersize=m["ms"],
                label=m["nombre"], zorder=m["zorder"])
        ax.fill_between(x, 0, y, color=m["color"], alpha=0.08, zorder=1)

        mae = df.loc[df["P_set"] > 0, "abs_error_P"].mean()
        ax.annotate(f'MAE = {mae:.2f} W',
                    xy=(x[-1], y[-1]),
                    xytext=(6, 0), textcoords="offset points",
                    color=m["color"], fontsize=8,
                    va="center", fontweight="bold")

    _eje_x(ax, horas, idx_act)
    ax.set_ylabel(r"$|\Delta P|$ [W]", fontweight="bold")
    ax.set_ylim(bottom=0)
    _grilla_menor(ax)
    ax.legend(loc="upper left", framealpha=0.90, edgecolor="#999999")
    _guardar_dual(fig, "fig5_error_abs_potencia", carpeta)


# ─────────────────────────────────────────────────────────────────────────────
# 4. FIGURA COMPUESTA (3 × 1) — P, V, I con eje X compartido
# ─────────────────────────────────────────────────────────────────────────────

def fig_compuesta_PVI(resultados, carpeta):
    """Subplot 3×1: (a) Potencia, (b) Voltaje, (c) Corriente, eje X compartido."""
    primer  = next(iter(resultados.values()))
    horas   = list(primer["hora_emulada"])
    idx_act = _filtrar_horas_activas(resultados)
    x       = list(range(len(idx_act)))

    fig, axes = plt.subplots(3, 1, figsize=(FIG_W, 3 * FIG_H_COMPACT),
                             sharex=True)

    configs = [
        ("P_set", "P_dc", "Potencia [W]",   "(a)"),
        ("V_set", "V_dc", "Voltaje [V]",    "(b)"),
        ("I_set", "I_dc", "Corriente [A]",  "(c)"),
    ]

    for ax, (col_set, col_dc, ylabel, panel_label) in zip(axes, configs):
        for key, df in resultados.items():
            m     = MODELOS[key]
            y_set = [df[col_set].iloc[i] for i in idx_act]
            y_dc  = [df[col_dc].iloc[i]  for i in idx_act]
            ax.plot(x, y_set, color=m["color"], linestyle=m["ls_set"],
                    linewidth=LW_SET, alpha=0.70, zorder=m["zorder"])
            ax.plot(x, y_dc,  color=m["color"], linestyle=m["ls_dc"],
                    linewidth=LW_DC, marker=m["marker"], markersize=m["ms"],
                    zorder=m["zorder"])

        ax.set_ylabel(ylabel, fontweight="bold")
        _grilla_menor(ax)

        # Etiqueta de panel (a), (b), (c)
        ax.text(0.015, 0.92, panel_label, transform=ax.transAxes,
                fontsize=11, fontweight="bold", va="top",
                bbox=dict(boxstyle="round,pad=0.2", facecolor="white",
                          edgecolor="#cccccc", alpha=0.85))

    # Leyenda solo en el panel superior
    _leyenda_par(axes[0], list(resultados.keys()))

    # Eje X solo en el panel inferior
    labels = [horas[i] for i in idx_act]
    axes[-1].set_xticks(range(len(labels)))
    axes[-1].set_xticklabels(labels, rotation=0)
    axes[-1].set_xlabel("Hora del día [h]", fontweight="bold")

    _guardar_dual(fig, "fig_compuesta_PVI", carpeta)


# ─────────────────────────────────────────────────────────────────────────────
# 5. TABLA RESUMEN — PNG + LaTeX
# ─────────────────────────────────────────────────────────────────────────────

def fig_tabla_resumen(df_tabla, carpeta):
    col_labels = [
        "Modelo",
        r"RMSE$_P$ [W]",
        r"MAE$_P$ [W]",
        r"$\bar{\eta}_{\rm MPPT}$ [%]",
        r"$\bar{V}_{\rm dc}$ [V]",
        r"$\bar{I}_{\rm dc}$ [A]",
    ]
    KEY_ORDER = ["simplified", "single_diode", "two_diode"]

    fig, ax = plt.subplots(figsize=(FIG_W, 2.0))
    ax.axis("off")

    fila_colores = []
    for _, row in df_tabla.iterrows():
        key = next(k for k in KEY_ORDER if MODELOS[k]["nombre"] == row["Modelo"])
        rgb = matplotlib.colors.to_rgba(MODELOS[key]["color"], 0.12)
        fila_colores.append([rgb] * len(col_labels))

    tabla = ax.table(
        cellText=df_tabla.values,
        colLabels=col_labels,
        cellLoc="center",
        loc="center",
        cellColours=fila_colores,
    )
    tabla.auto_set_font_size(False)
    tabla.set_fontsize(9)
    tabla.scale(1, 2.0)

    for j in range(len(col_labels)):
        cell = tabla[(0, j)]
        cell.set_facecolor("#1a2a3a")
        cell.set_text_props(color="white", fontweight="bold")
        cell.set_edgecolor("#ffffff")

    for i in range(1, len(df_tabla) + 1):
        for j in range(len(col_labels)):
            tabla[(i, j)].set_edgecolor("#dddddd")

    _guardar_dual(fig, "tabla_resumen", carpeta)


def exportar_latex(df_tabla, carpeta):
    """Genera tabla LaTeX compatible con booktabs para IEEE/Elsevier."""
    latex_cols = {
        "Modelo":    "Modelo",
        "RMSE_P":    r"RMSE$_P$ [W]",
        "MAE_P":     r"MAE$_P$ [W]",
        "eta_mppt":  r"$\bar{\eta}_{\mathrm{MPPT}}$ [\%]",
        "V_dc_prom": r"$\bar{V}_{\mathrm{dc}}$ [V]",
        "I_dc_prom": r"$\bar{I}_{\mathrm{dc}}$ [A]",
    }
    df_tex = df_tabla.rename(columns=latex_cols)

    # Formateo: 2 decimales para W y V/A, 1 decimal para %
    formatters = {
        r"RMSE$_P$ [W]":                     "{:.2f}".format,
        r"MAE$_P$ [W]":                      "{:.2f}".format,
        r"$\bar{\eta}_{\mathrm{MPPT}}$ [\%]": "{:.1f}".format,
        r"$\bar{V}_{\mathrm{dc}}$ [V]":      "{:.2f}".format,
        r"$\bar{I}_{\mathrm{dc}}$ [A]":      "{:.2f}".format,
    }

    latex_str = df_tex.to_latex(
        index=False,
        escape=False,
        column_format="l" + "c" * (len(latex_cols) - 1),
        formatters=formatters,
    )

    # Insertar booktabs
    latex_str = latex_str.replace(r"\toprule", r"\toprule")
    latex_str = latex_str.replace(r"\bottomrule", r"\bottomrule")

    ruta = carpeta / "tabla_resumen.tex"
    ruta.write_text(latex_str, encoding="utf-8")
    print(f"  💾  {ruta}")
    return latex_str


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    CARPETA_OUT.mkdir(parents=True, exist_ok=True)

    print("\n── Cargando sesiones ──────────────────────────────────────────")
    sesiones = cargar_sesiones(CARPETA_JSON)
    if not sesiones:
        raise FileNotFoundError(
            f"No se encontraron archivos sesion_*.json en {CARPETA_JSON}")

    print("\n── Procesando mediciones ──────────────────────────────────────")
    resultados = {}
    for key, datos in sesiones.items():
        resultados[key] = procesar_sesion(datos)
        print(f"  ✔  {key!r}  →  {len(resultados[key])} pasos")

    meta = _meta(sesiones)
    sub  = _subtitulo(meta)
    print(f"\n── Metadata: {sub}")

    # ── Figuras individuales (sin título, para caption del journal) ──────
    print("\n── Generando figuras individuales ─────────────────────────────")
    fig_variable(resultados, "P_set", "P_dc",
                 ylabel="Potencia [W]",
                 nombre_base="fig1_potencia",
                 carpeta=CARPETA_OUT)

    fig_variable(resultados, "V_set", "V_dc",
                 ylabel="Voltaje [V]",
                 nombre_base="fig2_voltaje",
                 carpeta=CARPETA_OUT)

    fig_variable(resultados, "I_set", "I_dc",
                 ylabel="Corriente [A]",
                 nombre_base="fig3_corriente",
                 carpeta=CARPETA_OUT)

    fig_eficiencia(resultados, CARPETA_OUT)
    fig_error_potencia(resultados, CARPETA_OUT)

    # ── Figura compuesta 3×1 (P, V, I con eje X compartido) ─────────────
    print("\n── Generando figura compuesta 3×1 ─────────────────────────────")
    fig_compuesta_PVI(resultados, CARPETA_OUT)

    # ── Tabla resumen — PNG + LaTeX ─────────────────────────────────────
    print("\n── Tabla resumen ──────────────────────────────────────────────")
    df_res = tabla_resumen(resultados)
    fig_tabla_resumen(df_res, CARPETA_OUT)
    latex = exportar_latex(df_res, CARPETA_OUT)
    print()
    print(df_res.to_string(index=False))
    print()
    print("── LaTeX ──")
    print(latex)

    print(f"\n✅  Análisis completado. Archivos en: {CARPETA_OUT}")


if __name__ == "__main__":
    main()