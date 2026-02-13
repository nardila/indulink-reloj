import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from datetime import datetime, timedelta


# =========================
# Utilidades internas
# =========================
def _combine(date_dt, t):
    return datetime(date_dt.year, date_dt.month, date_dt.day, t.hour, t.minute, 0)

def _parse_hhmm(s):
    return datetime.strptime(s, "%H:%M").time()

def _interval_subtract(base_interval, cut_interval):
    """
    Resta un intervalo [c,d) del intervalo [a,b) y devuelve una lista con los remanentes.
    Si no hay solapamiento, devuelve [a,b). Si hay, recorta.
    """
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
    """
    Filtra los segmentos que queden < min_minutes.
    (No une gaps: solo filtra por umbral.)
    """
    intervals = [(a, b) for a, b in intervals if (b - a).total_seconds() / 60.0 >= min_minutes]
    return intervals

def _dt_to_angle(dt, start_dt, end_dt):
    total_min = (end_dt - start_dt).total_seconds() / 60.0
    if total_min <= 0:
        return 0.0
    minutes = (dt - start_dt).total_seconds() / 60.0
    return 2 * np.pi * (minutes / total_min)


# =========================
# API principal
# =========================
def generar_reloj(df, maquina_id, fecha, umbral_minutos=3):
    """
    Devuelve:
      - fig: gráfico polar
      - indicadores: métricas del día
      - lista_gaps: detalle de intervalos de tiempo muerto (> umbral) con inicio, fin y duración (min)

    Reglas:
      - Turno: Lun–Jue 06:00–16:00, Vie 06:00–15:00
      - Pausas programadas: 08:00–08:20, 12:00–12:40 y últimos 20 min del turno (limpieza)
      - Crea eventos teóricos a las 06:00 y al cierre (15:00/16:00)
      - Gaps > umbral
      - Las pausas NO planificadas NO se marcan dentro de pausas programadas (se recortan)
    """
    # ---------------- Turno por día ----------------
    weekday = fecha.weekday()  # 0=lunes ... 4=viernes
    inicio_str = "06:00"
    fin_str = "16:00" if weekday < 4 else "15:00"
    inicio_dt = _combine(pd.to_datetime(fecha), _parse_hhmm(inicio_str))
    fin_dt    = _combine(pd.to_datetime(fecha), _parse_hhmm(fin_str))

    # ---------------- Pausas programadas ----------------
    desayuno = (_combine(pd.to_datetime(fecha), _parse_hhmm("08:00")),
                _combine(pd.to_datetime(fecha), _parse_hhmm("08:20")))
    almuerzo = (_combine(pd.to_datetime(fecha), _parse_hhmm("12:00")),
                _combine(pd.to_datetime(fecha), _parse_hhmm("12:40")))
    limpieza = (fin_dt - timedelta(minutes=20), fin_dt)  # últimos 20 min del turno

    pausas = [("Desayuno", *desayuno), ("Almuerzo", *almuerzo), ("Limpieza", *limpieza)]

    # ---------------- Filtrado y normalización ----------------
    df_dia = df[(df["Id Equipo"] == maquina_id) & (df["Fecha"].dt.date == fecha)].copy()
    if df_dia.empty:
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.axis("off")
        ax.text(0.5, 0.5, "Sin eventos para la combinación seleccionada", ha="center", va="center")
        indicadores = dict(total_disponible=0, inutilizado_programado=0, neto=0,
                           perdido_no_programado=0, porcentaje_perdido=0)
        return fig, indicadores, []

    df_dia = df_dia.sort_values("Fecha").reset_index(drop=True)
    df_dia["Fecha"] = pd.to_datetime(df_dia["Fecha"], errors="coerce").dt.floor("min")
    df_dia = df_dia.drop_duplicates(subset=["Fecha"])

    # ---------------- Candidatos de gap (> umbral) ----------------
    eventos = [inicio_dt] + list(df_dia["Fecha"]) + [fin_dt]
    candidatos = []
    for i in range(len(eventos) - 1):
        a, b = eventos[i], eventos[i + 1]
        if (b - a).total_seconds() / 60.0 > umbral_minutos:
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
    )

    lista_gaps = [
        dict(
            Inicio=a.strftime("%H:%M:%S"),
            Fin=b.strftime("%H:%M:%S"),
            Duracion=(b - a),
        )
        for a, b in unplanned
    ]

    # ---------------- Gráfico polar ----------------
    fig = plt.figure(figsize=(11.5, 8), facecolor="white")
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

    h = inicio_dt.replace(minute=0, second=0)
    if h < inicio_dt:
        h += timedelta(hours=1)
    while h <= fin_dt:
        ang = _dt_to_angle(h, inicio_dt, fin_dt)
        ax.plot([ang, ang], [0, 1.1], color="#888888", linewidth=1)
        ax.text(ang, 1.35, h.strftime("%H:00"), ha="center", va="center",
                fontsize=10, fontweight="bold", color="black")
        h += timedelta(hours=1)

    ax.set_title(
        f"Reloj Circular de Tiempos Muertos – Máquina {maquina_id} – {inicio_dt.date()}",
        va="bottom", fontsize=14, fontweight="bold"
    )

    return fig, indicadores, lista_gaps


# =========================
# API adicional: consolidación de múltiples máquinas (mismo equipo)
# =========================
def generar_reloj_multi(df, maquina_ids, fecha, umbral_minutos=3, etiqueta=None):
    """
    Igual que generar_reloj, pero consolida eventos de varias máquinas:
    - Los eventos se toman como la unión de timestamps de todas las máquinas del grupo.
    - Los gaps se calculan cuando *ninguna* máquina del grupo reporta evento (según el mismo criterio de umbral).
    - NO cambia ninguna regla del cálculo original; solo cambia el universo de eventos.
    """
    if etiqueta is None:
        etiqueta = " + ".join([str(x) for x in maquina_ids])

    df_dia = df[df["Id Equipo"].isin(maquina_ids) & (df["Fecha"].dt.date == fecha)].copy()

    # Si existe columna de parcial/contador (algunas versiones), ignorar filas sin activación real (parcial==0)
    for col in ["Parcial", "parcial", "J", "j"]:
        if col in df_dia.columns:
            try:
                df_dia = df_dia[pd.to_numeric(df_dia[col], errors="coerce").fillna(0) > 0]
            except Exception:
                pass
            break

    if df_dia.empty:
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.axis("off")
        ax.text(0.5, 0.5, "Sin eventos para la combinación seleccionada", ha="center", va="center")
        indicadores = dict(total_disponible=0, inutilizado_programado=0, neto=0,
                           perdido_no_programado=0, porcentaje_perdido=0)
        return fig, indicadores, []

    df_tmp = df_dia.copy()
    df_tmp["Id Equipo"] = etiqueta
    return generar_reloj(df_tmp, etiqueta, fecha, umbral_minutos=umbral_minutos)
