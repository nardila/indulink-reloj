import streamlit as st
import pandas as pd
from datetime import date, datetime, timedelta
from reloj_circular import generar_reloj, DEFAULT_TURNOS
import matplotlib.pyplot as plt

# =========================================================
# Configuración general
# =========================================================
st.set_page_config(page_title="Reloj de Tiempos Muertos", layout="wide")
st.title("📊 Reloj Circular de Tiempos Muertos")

# =========================================================
# CONFIGURACIÓN GOOGLE SHEETS (XLSX export)
# =========================================================
SHEET_EXPORT_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1clzNg0YblSQVvpWlWqeAwHKYiTyKcv-meWaI1RILAFo/export?format=xlsx"
)

# =========================================================
# Mapeo nombre ↔ ID de máquina (para UI amigable)
# =========================================================
MACHINE_NAME_TO_ID = {
    "Seccionadora": "4C4F686CDDA0",
    "Centro de Mecanizado 1": "84EA676CDDA0",
    "Centro de Mecanizado 2": "98D1676CDDA0",
    "Pegadora 1": "3C75A0C964EC",
    "Pegadora 2": "8C6EA51FB608",
}
ID_TO_MACHINE_NAME = {v: k for k, v in MACHINE_NAME_TO_ID.items()}

# =========================================================
# Carga de datos
# =========================================================
@st.cache_data(show_spinner=False)
def cargar_excel_desde_sheet(url: str) -> pd.DataFrame:
    df = pd.read_excel(url, sheet_name=0, engine="openpyxl", header=1)
    return df

def normalizar_columnas(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [str(c).strip() for c in df.columns]
    rename_map = {}
    for c in df.columns:
        cl = (
            str(c)
            .strip()
            .lower()
            .replace("í", "i").replace("á", "a").replace("é", "e")
            .replace("ó", "o").replace("ú", "u")
        )
        if cl in ["fecha", "fecha y hora", "fecha/hora", "timestamp", "date", "datetime"]:
            rename_map[c] = "Fecha"
        if cl in ["id equipo", "id_equipo", "id maquina", "id máquina", "equipo", "machineid", "idequipo"]:
            rename_map[c] = "Id Equipo"
    df = df.rename(columns=rename_map)
    if "Fecha" not in df.columns or "Id Equipo" not in df.columns:
        raise ValueError("No se encuentran las columnas requeridas: 'Fecha' y 'Id Equipo'.")
    df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce", infer_datetime_format=True)
    df["Id Equipo"] = df["Id Equipo"].astype(str).str.strip()
    return df

with st.spinner("Cargando datos de Google Sheets..."):
    raw = cargar_excel_desde_sheet(SHEET_EXPORT_URL)
df = normalizar_columnas(raw)

# =========================================================
# Interfaz
# =========================================================
# IDs que realmente existen en los datos
ids_en_datos = sorted(df["Id Equipo"].dropna().unique())

# Construimos lista visible de nombres:
# 1) Primero los nombres mapeados que estén en los datos
nombres_disponibles = [name for name, mid in MACHINE_NAME_TO_ID.items() if mid in ids_en_datos]
# 2) Si hay IDs en los datos que no estén en el mapeo, los agregamos como “Código: <id>”
extras = [f"Código: {mid}" for mid in ids_en_datos if mid not in MACHINE_NAME_TO_ID.values()]
opciones_maquina = nombres_disponibles + extras

col_top1, col_top2, col_top3 = st.columns([1, 1, 1])

# 🔀 NUEVO: toggle para múltiples máquinas
modo_multiple_maquinas = col_top1.toggle("Seleccionar múltiples máquinas", value=False)

if not modo_multiple_maquinas:
    # Selección única (comportamiento anterior)
    maquina_vis = col_top1.selectbox("Máquina", opciones_maquina, index=0)
    if maquina_vis.startswith("Código: "):
        maquina_id_unica = maquina_vis.replace("Código: ", "").strip()
        maquina_nombre_unica = ID_TO_MACHINE_NAME.get(maquina_id_unica, maquina_id_unica)
    else:
        maquina_id_unica = MACHINE_NAME_TO_ID.get(maquina_vis, maquina_vis)
        maquina_nombre_unica = maquina_vis
    maquinas_seleccionadas = [(maquina_nombre_unica, maquina_id_unica)]
else:
    # Selección múltiple
    maquinas_pick = col_top1.multiselect("Máquinas", opciones_maquina, default=nombres_disponibles[:1] if nombres_disponibles else [])
    if not maquinas_pick:
        st.stop()
    maquinas_seleccionadas = []
    for mv in maquinas_pick:
        if mv.startswith("Código: "):
            mid = mv.replace("Código: ", "").strip()
            mname = ID_TO_MACHINE_NAME.get(mid, mid)
        else:
            mid = MACHINE_NAME_TO_ID.get(mv, mv)
            mname = mv
        maquinas_seleccionadas.append((mname, mid))

fechas_disponibles = sorted(pd.Series(df["Fecha"].dt.date.dropna().unique()).tolist())
modo_multiple_fechas = col_top2.toggle("Seleccionar múltiples fechas", value=False)

# Toggle para mostrar o no los gráficos individuales (solo aplica en múltiple de fechas)
mostrar_detalle = True
if modo_multiple_fechas:
    mostrar_detalle = col_top3.toggle(
        "Mostrar gráficos individuales",
        value=True,
        help="Si lo desactivás, solo verás el Resumen y el gráfico histórico."
    )

if not modo_multiple_fechas:
    fecha_sel = col_top3.selectbox("Fecha", fechas_disponibles)
    fechas_seleccionadas = [fecha_sel]
else:
    fechas_seleccionadas = col_top3.multiselect(
        "Fechas (podés elegir varias)",
        options=fechas_disponibles,
        default=fechas_disponibles[-5:] if len(fechas_disponibles) > 5 else fechas_disponibles,
    )
    if not fechas_seleccionadas:
        st.stop()


# ---------------- Turnos ----------------
turnos_disponibles = list(DEFAULT_TURNOS.keys())
turnos_seleccionados = st.multiselect("Turnos", options=turnos_disponibles, default=["Mañana"])
if not turnos_seleccionados:
    st.stop()

umbral_min = st.number_input(
    "Umbral de pausa no planificada (min)",
    min_value=1, max_value=30, value=3, step=1
)

def fmt_hms(td: pd.Timedelta):
    total = int(td.total_seconds())
    h, m, s = total // 3600, (total % 3600) // 60, total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

# ===== Helper: suma del contador (Parcial > 0) en el turno seleccionado =====
def contador_total_utilizado(df_base: pd.DataFrame, maquina_id: str, fecha_dia, turno: str) -> float:
    # límites del turno desde el motor (evita duplicar lógica)
    _fig, indicadores, _gaps = generar_reloj(df_base, maquina_id, fecha_dia, umbral_minutos=umbral_min, turno=turno)
    inicio = indicadores.get("inicio")
    fin = indicadores.get("fin")
    if inicio is None or fin is None:
        return 0.0

    d = df_base[(df_base["Id Equipo"] == maquina_id)].copy()
    d = d.dropna(subset=["Fecha"])
    # recorte estricto al turno
    d = d[(d["Fecha"] >= inicio) & (d["Fecha"] <= fin)]
    if d.empty:
        return 0.0

    # localizar columna 'Parcial' de forma robusta
    parcial_col = None
    for c in d.columns:
        if "parcial" in str(c).strip().lower():
            parcial_col = c
            break
    if parcial_col is None:
        return 0.0

    parc = pd.to_numeric(d[parcial_col], errors="coerce").fillna(0)
    return float(parc[parc > 0].sum())

def render_dia(df_base: pd.DataFrame, maquina_id: str, maquina_nombre: str, fecha_dia: date, umbral_min: int, turno: str):
    # generar_reloj recibe el ID de equipo
    fig, indicadores, lista_gaps = generar_reloj(
        df_base, maquina_id, fecha_dia, umbral_minutos=umbral_min, turno=turno
    )
    st.pyplot(fig, use_container_width=True)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total disponible (min)", f"{indicadores['total_disponible']:.2f}")
    c2.metric("Inutilizado (pausas, min)", f"{indicadores['inutilizado_programado']:.2f}")
    c3.metric("Neto (min)", f"{indicadores['neto']:.2f}")
    c4.metric("Perdido no programado (min)", f"{indicadores['perdido_no_programado']:.2f}")
    c5.metric("% Perdido", f"{indicadores['porcentaje_perdido']:.2f}")

    df_gaps = pd.DataFrame(lista_gaps)
    if not df_gaps.empty:
        df_gaps["Duracion"] = pd.to_timedelta(df_gaps["Duracion_min"], unit="m").apply(fmt_hms)
        st.dataframe(df_gaps[["Inicio", "Fin", "Duracion"]], use_container_width=True)

    # === EXPORTAR A EXCEL (descarga garantizada con xlsxwriter) ===
    from io import BytesIO
    output = BytesIO()

    if not df_gaps.empty:
        dur_seconds = pd.to_timedelta(df_gaps["Duracion_min"], unit="m").dt.total_seconds()
        df_xlsx = pd.DataFrame({
            "Inicio": df_gaps["Inicio"],
            "Fin": df_gaps["Fin"],
            "Duracion": (dur_seconds / 86400.0)  # Excel: fracción del día
        })
    else:
        df_xlsx = pd.DataFrame(columns=["Inicio", "Fin", "Duracion"])

    # Forzamos xlsxwriter para evitar problemas de entorno
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df_xlsx.to_excel(writer, index=False, sheet_name="TiemposMuertos")
        workbook  = writer.book
        worksheet = writer.sheets["TiemposMuertos"]
        time_fmt = workbook.add_format({"num_format": "[h]:mm:ss"})
        worksheet.set_column(0, 0, 10)             # A: Inicio
        worksheet.set_column(1, 1, 10)             # B: Fin
        worksheet.set_column(2, 2, 12, time_fmt)   # C: Duracion
    excel_bytes = output.getvalue()

    st.download_button(
        "📥 Descargar detalle (Excel)",
        data=excel_bytes,
        file_name=f"tiempos_muertos_{maquina_nombre}_{turno}_{fecha_dia}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
    # === FIN EXPORTAR A EXCEL ===

    # 🔢 Contador total utilizado (Parcial > 0)
    total_contador = contador_total_utilizado(df_base, maquina_id, fecha_dia, turno)

    # Devolvemos todos los campos para el resumen consolidado
    return {
        "Fecha": fecha_dia,
        "Turno": turno,
        "Total disponible (min)": indicadores["total_disponible"],
        "Pausas programadas (min)": indicadores["inutilizado_programado"],
        "No programadas (min)": indicadores["perdido_no_programado"],
        "%_Perdido": indicadores["porcentaje_perdido"],
        "Contador total (parcial>0)": total_contador,
    }

def resumen_solo(df_base: pd.DataFrame, maquina_id: str, fecha_dia: date, umbral_min: int, turno: str):
    _, indicadores, _ = generar_reloj(
        df_base, maquina_id, fecha_dia, umbral_minutos=umbral_min, turno=turno
    )
    total_contador = contador_total_utilizado(df_base, maquina_id, fecha_dia, turno)
    return {
        "Fecha": fecha_dia,
        "Turno": turno,
        "Total disponible (min)": indicadores["total_disponible"],
        "Pausas programadas (min)": indicadores["inutilizado_programado"],
        "No programadas (min)": indicadores["perdido_no_programado"],
        "%_Perdido": indicadores["porcentaje_perdido"],
        "Contador total (parcial>0)": total_contador,
    }


if st.button("Generar gráfico(s)", type="primary", use_container_width=True):
    # Recorremos cada máquina seleccionada
    for maquina_nombre, maquina_id in maquinas_seleccionadas:
        # Recorremos cada turno seleccionado
        for turno in turnos_seleccionados:
            st.caption(f"Máquina seleccionada: **{maquina_nombre}** · Turno: **{turno}** · ID: `{maquina_id}`")
            resumen = []

            # Recorremos fechas
            for f in fechas_seleccionadas:
                if (not modo_multiple_fechas) or mostrar_detalle:
                    st.subheader(f"📅 {maquina_nombre} – Turno {turno} – Día {f}")
                    res = render_dia(df, maquina_id, maquina_nombre, f, umbral_min, turno)
                    resumen.append(res)
                    st.divider()
                else:
                    res = resumen_solo(df, maquina_id, f, umbral_min, turno)
                    resumen.append(res)

            # Resumen y gráfico histórico por máquina+turno
            if len(resumen) > 0:
                st.subheader(f"📈 Resumen – {maquina_nombre} – Turno {turno}")
                df_res = pd.DataFrame(resumen).sort_values("Fecha")
                st.dataframe(df_res, use_container_width=True)

                if len(df_res) > 1:
                    st.markdown(f"#### 📉 Histórico de % Perdido – {maquina_nombre} – Turno {turno}")
                    labels = df_res["Fecha"].astype(str).tolist()
                    x = range(len(labels))

                    fig, ax = plt.subplots(figsize=(8, 3))
                    ax.plot(x, df_res["%_Perdido"], marker="o", linewidth=2)
                    ax.set_xlabel("Fecha")
                    ax.set_ylabel("% Perdido")
                    ymax = float(df_res["%_Perdido"].max()) if len(df_res) else 1.0
                    ax.set_ylim(bottom=0, top=max(1.0, ymax * 2))
                    ax.set_xticks(list(x))
                    ax.set_xticklabels(labels, rotation=45, ha="right")
                    ax.grid(True, alpha=0.3)

                    bump = ymax * 0.07 if ymax > 0 else 0.1
                    for i, y in enumerate(df_res["%_Perdido"]):
                        ax.text(
                            i, y + bump,
                            f"{y:.2f}%",
                            ha="center", va="bottom", fontsize=7, fontweight="bold"
                        )

                    st.pyplot(fig, use_container_width=True)
