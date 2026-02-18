import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, time


# =========================
# Utilidades internas
# =========================
def _combine(date_dt, t: time):
    return datetime(date_dt.year, date_dt.month, date_dt.day, t.hour, t.minute, t.second)

def _parse_hhmm(s: str) -> time:
    fmt = "%H:%M:%S" if len(s.strip()) == 8 else "%H:%M"
    return datetime.strptime(s.strip(), fmt).time()

def _dt_in_shift(date_dt, t: time, shift_start_t: time, crosses_midnight: bool) -> datetime:
    base = _combine(date_dt, t)
    if crosses_midnight and (t < shift_start_t):
        base = base + timedelta(days=1)
    return base

def _interval_subtract(base_interval, cut_interval):
    a, b = base_interval
    c, d = cut_interval
    if d <= a or c >= b:
        return [base_interval]
    parts = []
    if c > a:
        parts.append((a, min(c, b)))
    if d < b:
        parts.append((max(d, a), b))
    return parts

def _merge_small_gaps(intervals, min_minutes=3.0):
    """Filtra segmentos menores a min_minutes (NO los une entre sí)."""
    return [(a, b) for a, b in intervals if (b - a).total_seconds() / 60.0 >= min_minutes]

def _dt_to_angle(dt, start_dt, end_dt):
    total_min = (end_dt - start_dt).total_seconds() / 60.0
    if total_min <= 0:
        return 0.0
    minutes = (dt - start_dt).total_seconds() / 60.0
    return 2 * np.pi * (minutes / total_min)


# =========================
# Turnos (configurable)
# =========================
DEFAULT_TURNOS = {
    "Mañana": {
        "inicio": "06:00",
        "fin_lj": "16:00",
        "fin_v": "15:00",
        "pausas": [
            ("Desayuno", "08:00", "08:20"),
            ("Almuerzo", "12:00", "12:40"),
        ],
        "limpieza_ultimos_min": 20,
    },
    "Tarde": {
        # Lun–Jue 16:00 a 02:00
        "inicio": "16:00",
        "fin_lj": "02:00",
        # Vie 15:00 a 00:00
        "fin_v": "00:00",
        "pausas": [
            ("Pausa 1", "19:30", "19:50"),
            ("Pausa 2", "22:00", "22:40"),
        ],
        "limpieza_ultimos_min": 20,
    },
}


# =========================
# API principal
# =========================
def generar_reloj(df, maquina_id, fecha, umbral_minutos=3, turno="Mañana", turnos_config=None):
    """
    Devuelve:
      - fig: gráfico polar
      - indicadores: métricas del turno
      - lista_gaps: detalle de intervalos de tiempo muerto (>= umbral)

    Reglas:
      - Turno configurable (Mañana / Tarde)
      - Pausas programadas por turno + limpieza últimos N min
      - Crea eventos teóricos a inicio y cierre
      - No marca no planificadas dentro de pausas programadas
      - Ignora eventos fuera del turno (filtro estricto al rango [inicio, fin])
      - Ignora filas con "Parcial" == 0 (si existe esa columna)
    """
    if turnos_config is None:
        turnos_config = DEFAULT_TURNOS
    if turno not in turnos_config:
        raise ValueError(f"Turno '{turno}' no existe en la configuración.")

    cfg = turnos_config[turno]
    fecha_dt = pd.to_datetime(fecha)
    weekday = fecha_dt.weekday()  # 0=lunes ... 4=viernes

    inicio_t = _parse_hhmm(cfg["inicio"])
    fin_t = _parse_hhmm(cfg["fin_lj"] if weekday < 4 else cfg["fin_v"])

    inicio_dt = _combine(fecha_dt, inicio_t)
    fin_dt = _combine(fecha_dt, fin_t)

    crosses_midnight = fin_dt <= inicio_dt
    if crosses_midnight:
        fin_dt = fin_dt + timedelta(days=1)

    # ---------------- Pausas programadas ----------------
    pausas = []
    for nombre, ps_str, pe_str in cfg.get("pausas", []):
        ps_t = _parse_hhmm(ps_str)
        pe_t = _parse_hhmm(pe_str)
        ps = _dt_in_shift(fecha_dt, ps_t, inicio_t, crosses_midnight)
        pe = _dt_in_shift(fecha_dt, pe_t, inicio_t, crosses_midnight)
        if pe <= ps:
            pe = pe + timedelta(days=1)
        pausas.append((nombre, ps, pe))

    limpieza_min = int(cfg.get("limpieza_ultimos_min", 20))
    if limpieza_min > 0:
        pausas.append(("Limpieza", fin_dt - timedelta(minutes=limpieza_min), fin_dt))

    # ---------------- Filtrado y normalización ----------------
    df_turno = df[(df["Id Equipo"] == maquina_id)].copy()
    df_turno["Fecha"] = pd.to_datetime(df_turno["Fecha"], errors="coerce")
    df_turno = df_turno.dropna(subset=["Fecha"])
    df_turno = df_turno[(df_turno["Fecha"] >= inicio_dt) & (df_turno["Fecha"] <= fin_dt)]

    if df_turno.empty:
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.axis("off")
        ax.text(0.5, 0.5, "Sin eventos para la combinación seleccionada",
                ha="center", va="center")
        indicadores = dict(total_disponible=0, inutilizado_programado=0, neto=0,
                           perdido_no_programado=0, porcentaje_perdido=0,
                           inicio=inicio_dt, fin=fin_dt, turno=turno)
        return fig, indicadores, []

    df_turno = df_turno.sort_values("Fecha").reset_index(drop=True)
    df_turno = df_turno.drop_duplicates(subset=["Fecha"])

    # ✅ Ignorar filas con "Parcial == 0" (si existe)
    parcial_col = None
    for c in df_turno.columns:
        if "parcial" in str(c).strip().lower():
            parcial_col = c
            break
    if parcial_col is not None:
        parc = pd.to_numeric(df_turno[parcial_col], errors="coerce").fillna(0)
        df_turno = df_turno[parc > 0]

    if df_turno.empty:
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.axis("off")
        ax.text(0.5, 0.5, "Sin eventos para la combinación seleccionada",
                ha="center", va="center")
        indicadores = dict(total_disponible=0, inutilizado_programado=0, neto=0,
                           perdido_no_programado=0, porcentaje_perdido=0,
                           inicio=inicio_dt, fin=fin_dt, turno=turno)
        return fig, indicadores, []

    # ---------------- Candidatos de gap (>= umbral) ----------------
    eventos = [inicio_dt] + list(df_turno["Fecha"]) + [fin_dt]
    candidatos = []
    for i in range(len(eventos) - 1):
        a, b = eventos[i], eventos[i + 1]
        if (b - a).total_seconds() / 60.0 >= umbral_minutos:
            candidatos.append((a, b))

    # ---------------- Restar pausas programadas ----------------
    unplanned = candidatos[:]
    for _, ps, pe in pausas:
        nuevos = []
        for seg in unplanned:
            nuevos.extend(_interval_subtract(seg, (ps, pe)))
        unplanned = nuevos

    unplanned = _merge_small_gaps(unplanned, min_minutes=umbral_minutos)

    # ---------------- Indicadores ----------------
    total_disponible = (fin_dt - inicio_dt).total_seconds() / 60.0
    inutilizado_programado = sum((pe - ps).total_seconds() for _, ps, pe in pausas) / 60.0
    neto = total_disponible - inutilizado_programado
    perdido_no_programado = sum((b - a).total_seconds() for a, b in unplanned) / 60.0
    porcentaje_perdido = (perdido_no_programado / neto * 100.0) if neto > 0 else 0.0

    indicadores = dict(
        total_disponible=total_disponible,
        inutilizado_programado=inutilizado_programado,
        neto=neto,
        perdido_no_programado=perdido_no_programado,
        porcentaje_perdido=porcentaje_perdido,
        inicio=inicio_dt,
        fin=fin_dt,
        turno=turno,
    )

    # ---------------- Listado detallado ----------------
    lista_gaps = [
        dict(
            Inicio=a.strftime("%H:%M:%S"),
            Fin=b.strftime("%H:%M:%S"),
            Duracion_min=(b - a).total_seconds() / 60.0,
        )
        for a, b in unplanned
    ]

    # ---------------- Gráfico polar ----------------
    fig = plt.figure(figsize=(6, 4.5), facecolor="white")
    ax = plt.subplot(111, polar=True)
    ax.set_theta_direction(-1)
    ax.set_theta_offset(np.pi / 2)
    ax.spines["polar"].set_linewidth(3)
    ax.set_yticklabels([])
    ax.set_xticklabels([])

    for nombre, ps, pe in pausas:
        ang0 = _dt_to_angle(ps, inicio_dt, fin_dt)
        ang1 = _dt_to_angle(pe, inicio_dt, fin_dt)
        if ang1 > ang0:
            ax.barh(
                1.0, width=ang1 - ang0, left=ang0, height=0.10,
                color="royalblue", alpha=0.8, edgecolor="black", linewidth=0.5
            )
            ax.text(ang0 + (ang1 - ang0) / 2, 1.12, nombre, ha="center", va="center", fontsize=9)

    for a, b in unplanned:
        ang0 = _dt_to_angle(a, inicio_dt, fin_dt)
        ang1 = _dt_to_angle(b, inicio_dt, fin_dt)
        if ang1 > ang0:
            ax.barh(
                1.0, width=ang1 - ang0, left=ang0, height=0.10,
                color="red", alpha=0.85, edgecolor="black", linewidth=0.8
            )

    h = inicio_dt.replace(minute=0, second=0, microsecond=0)
    if h < inicio_dt:
        h += timedelta(hours=1)
    while h <= fin_dt:
        ang = _dt_to_angle(h, inicio_dt, fin_dt)
        ax.plot([ang, ang], [0, 1.1], color="#888888", linewidth=1)
        ax.text(ang, 1.35, h.strftime("%H:%M"), ha="center", va="center",
                fontsize=10, fontweight="bold", color="black")
        h += timedelta(hours=1)

    ax.set_title(
        f"Reloj Circular de Tiempos Muertos – {turno} – Máquina {maquina_id} – {inicio_dt.date()}",
        va="bottom", fontsize=13, fontweight="bold"
    )

    return fig, indicadores, lista_gaps
