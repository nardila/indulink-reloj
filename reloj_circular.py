import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta

def generar_reloj(df, maquina_id, fecha, umbral_minutos=3):
    """
    Genera el gráfico circular de tiempos muertos y devuelve:
      - fig: el gráfico matplotlib listo para mostrar
      - indicadores: métricas agregadas del día
      - lista_gaps: detalle de intervalos de tiempo muerto (> umbral)
    """

    # --- CONFIGURACIÓN DE TURNOS ---
    dow = fecha.weekday()
    if dow in [0, 1, 2, 3]:  # lunes a jueves
        inicio_h, fin_h = 6, 16
    else:  # viernes
        inicio_h, fin_h = 6, 15

    inicio_dt = datetime.combine(fecha, datetime.min.time()) + timedelta(hours=inicio_h)
    fin_dt = datetime.combine(fecha, datetime.min.time()) + timedelta(hours=fin_h)

    # Pausas programadas
    pausas = [
        (datetime.combine(fecha, datetime.min.time()) + timedelta(hours=8, minutes=0),
         datetime.combine(fecha, datetime.min.time()) + timedelta(hours=8, minutes=20)),
        (datetime.combine(fecha, datetime.min.time()) + timedelta(hours=12, minutes=0),
         datetime.combine(fecha, datetime.min.time()) + timedelta(hours=12, minutes=40)),
        (fin_dt - timedelta(minutes=20), fin_dt)  # limpieza
    ]

    # --- FILTRADO DE DATOS ---
    df_dia = df[(df["Id Equipo"] == maquina_id) & (df["Fecha"].dt.date == fecha)].copy()
    df_dia = df_dia.sort_values("Fecha").reset_index(drop=True)

    # --- EVENTOS (con inicio y fin teóricos) ---
    eventos = [inicio_dt] + list(df_dia["Fecha"]) + [fin_dt]

    # --- GAPS > umbral ---
    gaps = []
    for i in range(len(eventos) - 1):
        a, b = eventos[i], eventos[i + 1]
        delta = (b - a).total_seconds() / 60
        if delta > umbral_minutos:
            gaps.append((a, b))

    # --- RESTAR PAUSAS ---
    def restar_pausas(gaps, pausas):
        resultado = []
        for a, b in gaps:
            segmentos = [(a, b)]
            for p1, p2 in pausas:
                nuevos = []
                for x1, x2 in segmentos:
                    if x2 <= p1 or x1 >= p2:
                        nuevos.append((x1, x2))
                    else:
                        if x1 < p1:
                            nuevos.append((x1, p1))
                        if x2 > p2:
                            nuevos.append((p2, x2))
                segmentos = nuevos
            resultado.extend(segmentos)
        return resultado

    gaps_netos = restar_pausas(gaps, pausas)

    # --- CÁLCULOS DE INDICADORES ---
    total_disp = (fin_dt - inicio_dt).total_seconds() / 60
    inutilizado_prog = sum((b - a).total_seconds() for a, b in pausas) / 60
    perdido = sum((b - a).total_seconds() for a, b in gaps_netos) / 60
    neto = total_disp - inutilizado_prog
    pct = (perdido / neto) * 100 if neto > 0 else 0

    indicadores = dict(
        total_disponible=round(total_disp, 1),
        inutilizado_programado=round(inutilizado_prog, 1),
        neto=round(neto, 1),
        perdido_no_programado=round(perdido, 1),
        porcentaje_perdido=round(pct, 1)
    )

    # --- LISTA DETALLADA DE TIEMPOS MUERTOS ---
    lista_gaps = [
        dict(
            inicio=a.strftime("%H:%M"),
            fin=b.strftime("%H:%M"),
            duracion=round((b - a).total_seconds() / 60, 1)
        )
        for a, b in gaps_netos
    ]

    # --- GRÁFICO POLAR ---
    fig, ax = plt.subplots(subplot_kw={"projection": "polar"}, figsize=(6, 6))
    ax.set_theta_direction(-1)
    ax.set_theta_offset(1.57)
    ax.set_title(f"Reloj Circular – Máquina {maquina_id}\n{fecha.strftime('%d/%m/%Y')}", pad=30)

    # Dibujar pausas en azul
    for (a, b) in pausas:
        t1 = (a - inicio_dt).total_seconds() / 3600 * (2 * 3.1416 / (fin_h - inicio_h))
        t2 = (b - inicio_dt).total_seconds() / 3600 * (2 * 3.1416 / (fin_h - inicio_h))
        ax.barh(1, width=(t2 - t1), left=t1, height=0.3, color="skyblue", edgecolor="none")

    # Dibujar gaps no programados en rojo con borde negro
    for (a, b) in gaps_netos:
        t1 = (a - inicio_dt).total_seconds() / 3600 * (2 * 3.1416 / (fin_h - inicio_h))
        t2 = (b - inicio_dt).total_seconds() / 3600 * (2 * 3.1416 / (fin_h - inicio_h))
        ax.barh(1, width=(t2 - t1), left=t1, height=0.3, color="red", edgecolor="black", linewidth=1.5)

    # Líneas horarias
    for h in range(inicio_h, fin_h + 1):
        angle = (h - inicio_h) * (2 * 3.1416 / (fin_h - inicio_h))
        ax.plot([angle, angle], [0, 1.15], color="gray", linewidth=0.6)
        ax.text(angle, 1.22, f"{h:02d}:00", ha="center", va="center", fontsize=8)

    ax.set_yticklabels([])
    ax.set_xticklabels([])
    ax.set_ylim(0, 1.25)

    return fig, indicadores, lista_gaps
