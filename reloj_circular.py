import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from datetime import timedelta


def generar_reloj(df, maquina_id, fecha, umbral_minutos=3):
    df_filtrado = df[
        (df["Id Equipo"] == maquina_id) &
        (df["Fecha"].dt.date == fecha)
    ].copy()

    if df_filtrado.empty:
        raise ValueError("No hay registros para la fecha y máquina seleccionadas.")

    df_filtrado = df_filtrado.sort_values("Fecha")
    df_filtrado["Delta"] = df_filtrado["Fecha"].diff().dt.total_seconds().div(60)
    df_filtrado["Gap"] = df_filtrado["Delta"].fillna(0)

    # Pausas programadas
    pausas_programadas = {
        "Desayuno": ("08:00", "08:20"),
        "Almuerzo": ("12:00", "13:00"),
        "Limpieza": ("15:00", "15:20")
    }

    total_disponible = 600  # 10 horas (6:00 a 16:00)
    tiempo_inutilizado = sum([
        (pd.to_datetime(v[1]) - pd.to_datetime(v[0])).seconds / 60
        for v in pausas_programadas.values()
    ])

    # Gaps no programados
    gaps = df_filtrado[df_filtrado["Gap"] > umbral_minutos].copy()
    lista_gaps = []
    total_perdido = 0

    for _, row in gaps.iterrows():
        inicio = row["Fecha"] - timedelta(minutes=row["Gap"])
        fin = row["Fecha"]
        duracion = round(row["Gap"], 1)
        total_perdido += duracion
        lista_gaps.append({
            "Inicio": inicio.time(),
            "Fin": fin.time(),
            "Duración (min)": duracion
        })

    neto = total_disponible - tiempo_inutilizado
    porcentaje_perdido = round((total_perdido / neto) * 100, 2)

    indicadores = {
        "total_disponible": total_disponible,
        "inutilizado_programado": tiempo_inutilizado,
        "neto": neto,
        "perdido_no_programado": round(total_perdido, 1),
        "porcentaje_perdido": porcentaje_perdido
    }

    # Gráfico circular
    fig = plt.figure(figsize=(10, 6))
    ax = plt.subplot(111, polar=True)
    ax.set_theta_direction(-1)
    ax.set_theta_zero_location("N")

    horas = np.linspace(0, 2 * np.pi, 13)
    etiquetas = [f"{h:02d}:00" for h in range(6, 18)]
    ax.set_xticks(np.linspace(0, 2 * np.pi, len(etiquetas)))
    ax.set_xticklabels(etiquetas)

    # Dibujar pausas programadas
    for nombre, (ini, fin) in pausas_programadas.items():
        ini_ang = ((pd.to_datetime(ini).hour - 6) + pd.to_datetime(ini).minute / 60) / 12 * 2 * np.pi
        fin_ang = ((pd.to_datetime(fin).hour - 6) + pd.to_datetime(fin).minute / 60) / 12 * 2 * np.pi
        ax.barh(1, fin_ang - ini_ang, left=ini_ang, height=0.5, color="royalblue", alpha=0.4)
        ax.text((ini_ang + fin_ang) / 2, 1.2, nombre, ha="center", va="center", fontsize=8)

    # Dibujar tiempos muertos
    for gap in lista_gaps:
        ini_ang = ((gap["Inicio"].hour - 6) + gap["Inicio"].minute / 60) / 12 * 2 * np.pi
        fin_ang = ((gap["Fin"].hour - 6) + gap["Fin"].minute / 60) / 12 * 2 * np.pi
        ax.barh(1, fin_ang - ini_ang, left=ini_ang, height=0.4, color="red", alpha=0.6)

    ax.set_yticklabels([])
    ax.set_title(f"Reloj Circular de Tiempos Muertos\nMáquina {maquina_id} - Día {fecha}", va="bottom")
    plt.tight_layout()

    return fig, indicadores, lista_gaps
