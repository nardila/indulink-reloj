import matplotlib
matplotlib.rcParams['font.family'] = 'DejaVu Sans'
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

def _combine(date_dt, t):
    return datetime(date_dt.year, date_dt.month, date_dt.day, t.hour, t.minute, 0)

def _parse_hhmm(s):
    return datetime.strptime(s, "%H:%M").time()

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

def _dt_to_angle(dt, start_dt, end_dt):
    total_min = (end_dt - start_dt).total_seconds() / 60.0
    if total_min <= 0:
        return 0.0
    minutes = (dt - start_dt).total_seconds() / 60.0
    return 2 * np.pi * (minutes / total_min)

def _merge_small_gaps(intervals, min_minutes=3.0):
    intervals = [(a,b) for a,b in intervals if (b-a).total_seconds()/60.0 > min_minutes]
    if not intervals:
        return []
    intervals.sort(key=lambda x: x[0])
    merged = [intervals[0]]
    for a,b in intervals[1:]:
        la, lb = merged[-1]
        if (a - lb).total_seconds() <= 10:
            merged[-1] = (la, max(lb, b))
        else:
            merged.append((a,b))
    merged = [(a,b) for a,b in merged if (b-a).total_seconds()/60.0 > min_minutes]
    return merged

def generar_reloj(df, maquina_id, fecha, umbral_minutos=3):
    alerta = ""
    weekday = fecha.weekday()
    inicio_str = "06:00"
    fin_str = "16:00" if weekday < 4 else "15:00"
    inicio_dt = _combine(pd.to_datetime(fecha), _parse_hhmm(inicio_str))
    fin_dt = _combine(pd.to_datetime(fecha), _parse_hhmm(fin_str))

    desayuno = (_combine(pd.to_datetime(fecha), _parse_hhmm("08:00")),
                _combine(pd.to_datetime(fecha), _parse_hhmm("08:20")))
    almuerzo = (_combine(pd.to_datetime(fecha), _parse_hhmm("12:00")),
                _combine(pd.to_datetime(fecha), _parse_hhmm("12:40")))
    limpieza = (fin_dt - timedelta(minutes=20), fin_dt)
    pausas = [("Desayuno", *desayuno), ("Almuerzo", *almuerzo), ("Limpieza", *limpieza)]

    if "timestamp" not in df.columns or "id_equipo" not in df.columns:
        return None, {}, "Faltan columnas requeridas: timestamp e id_equipo."
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["id_equipo"] = df["id_equipo"].astype(str).str.strip().str.upper()
    maquina_id_norm = str(maquina_id).strip().upper()
    df_day = df[(df["id_equipo"] == maquina_id_norm) & (df["timestamp"].dt.date == pd.to_datetime(fecha).date())].copy()
    df_day = df_day.sort_values("timestamp").reset_index(drop=True)

    if df_day.empty:
        return None, {}, "Sin eventos para esa fecha y máquina en el archivo."

    candidatos = []
    first_ts = df_day["timestamp"].iloc[0]
    last_ts = df_day["timestamp"].iloc[-1]

    if first_ts > inicio_dt:
        candidatos.append((inicio_dt, first_ts))
    prev = first_ts
    for ts in df_day["timestamp"].iloc[1:]:
        if ts > prev:
            candidatos.append((prev, ts))
        prev = ts
    if fin_dt > last_ts:
        candidatos.append((last_ts, fin_dt))

    candidatos = [(a,b) for a,b in candidatos if (b-a).total_seconds()/60.0 > umbral_minutos]

    unplanned = candidatos[:]
    for _, ps, pe in pausas:
        new_unp = []
        for seg in unplanned:
            new_unp.extend(_interval_subtract(seg, (ps, pe)))
        unplanned = new_unp
    unplanned = _merge_small_gaps(unplanned, min_minutes=umbral_minutos)

    total_disponible = (fin_dt - inicio_dt).total_seconds() / 60.0
    inutilizado_programado = sum((pe-ps).total_seconds() for _,ps,pe in pausas) / 60.0
    neto = total_disponible - inutilizado_programado
    perdido_no_programado = sum((b-a).total_seconds() for a,b in unplanned) / 60.0
    porcentaje_perdido = (perdido_no_programado / neto * 100.0) if neto > 0 else 0.0
    indicadores = dict(
        total_disponible=total_disponible,
        inutilizado_programado=inutilizado_programado,
        neto=neto,
        perdido_no_programado=perdido_no_programado,
        porcentaje_perdido=porcentaje_perdido
    )

    fig = plt.figure(figsize=(11.5,8), facecolor="white")
    ax = plt.subplot(111, polar=True)
    ax.set_theta_direction(-1)
    ax.set_theta_offset(np.pi/2)
    ax.spines["polar"].set_linewidth(3)
    ax.set_yticklabels([])
    ax.set_xticklabels([])

    # Pausas (azul)
    for nombre, ps, pe in pausas:
        ang0 = _dt_to_angle(ps, inicio_dt, fin_dt)
        ang1 = _dt_to_angle(pe, inicio_dt, fin_dt)
        ax.barh(1.0, width=max(0, ang1-ang0), left=ang0, height=0.10,
                color="royalblue", alpha=0.8, edgecolor="black", linewidth=0.5)
        ax.text(ang0 + (ang1-ang0)/2 if ang1>ang0 else ang0, 1.12, nombre,
                ha="center", va="center", fontsize=9, color="black")

    # No planificadas (rojo)
    for a,b in unplanned:
        ang0 = _dt_to_angle(a, inicio_dt, fin_dt)
        ang1 = _dt_to_angle(b, inicio_dt, fin_dt)
        if ang1 > ang0:
            ax.barh(1.0, width=ang1-ang0, left=ang0, height=0.10,
                    color="red", alpha=0.85, edgecolor="black", linewidth=0.8)

    # Radiales y etiquetas
    h = inicio_dt.replace(minute=0, second=0)
    if h < inicio_dt:
        h += timedelta(hours=1)
    while h <= fin_dt:
        ang = _dt_to_angle(h, inicio_dt, fin_dt)
        ax.plot([ang, ang], [0, 1.1], color="#888888", linewidth=1)
        ax.text(ang, 1.35, h.strftime("%H:00"), ha="center", va="center",
                fontsize=10, fontweight="bold", color="black")
        h += timedelta(hours=1)

    # Recuadro indicadores
    texto = (f"Indicadores del día ({inicio_dt.date()}):\n"
             f"• Total disponible: {total_disponible:.0f} min\n"
             f"• Inutilizado (programado): {inutilizado_programado:.0f} min\n"
             f"• Neto: {neto:.0f} min\n"
             f"• Perdido no programado: {perdido_no_programado:.0f} min\n"
             f"• % Perdido: {porcentaje_perdido:.2f}%")
    ax.text(3.65, 0.5, texto, transform=ax.transAxes, ha="left", va="center",
            fontsize=10, bbox=dict(boxstyle="round", fc="white", ec="black"))

    ax.set_title(f"Reloj Circular de Tiempos Muertos – Máquina {maquina_id} – {inicio_dt.date()}",
                 va="bottom", fontsize=14, fontweight="bold")

    return fig, indicadores, alerta
