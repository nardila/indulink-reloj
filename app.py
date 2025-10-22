import streamlit as st
import pandas as pd
from datetime import date
from reloj_circular import generar_reloj
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
maquina_vis = col_top1.selectbox("Máquina", opciones_maquina, index=0)

# Resolvemos el ID según lo elegido
if maquina_vis.startswith("Código: "):
    maquina_id = maquina_vis.replace("Código: ", "").strip()
    maquina_nombre = ID_TO_MACHINE_NAME.get(maquina_id, maquina_id)
else:
    maquina_id = MACHINE_NAME_TO_ID.get(maquina_vis, maquina_vis)
    maquina_nombre = maquina_vis

fechas_disponibles = sorted(pd.Series(df["Fecha"].dt.date.dropna().unique()).tolist())
modo_multiple = col_top2.toggle("Seleccionar múltiples fechas", value=False)

# Toggle para mostrar o no los gráficos individuales (solo aplica en múltiple)
mostrar_detalle = True
if modo_multiple:
    mostrar_detalle = col_top3.toggle(
        "Mostrar gráficos individuales",
        value=True,
        help="Si lo desactivás, solo verás el Resumen y el gráfico histórico."
    )

if not modo_multiple:
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

umbral_min = st.number_input(
    "Umbral de pausa no planificada (min)",
    min_value=1, max_value=30, value=3, step=1
)

def fmt_hms(td: pd.Timedelta):
    total = int(td.total_seconds())
    h, m, s = total // 3600, (total % 3600) // 60, total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

def render_dia(fecha_dia):
    # generar_reloj sigue recibiendo el ID de equipo
    fig, indicadores, lista_gaps = generar_reloj(
        df, maquina_id, fecha_dia, umbral_minutos=umbral_min
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

    # === EXPORTAR A EXCEL (cambio mínimo con fallback) ===
    # Se genera siempre el archivo (incluso si no hay filas), respetando formato [h]:mm:ss
    from io import BytesIO
    output = BytesIO()

    # Preparar DataFrame para Excel con columnas fijas
    if not df_gaps.empty:
        dur_seconds = pd.to_timedelta(df_gaps["Duracion_min"], unit="m").dt.total_seconds()
        df_xlsx = pd.DataFrame({
            "Inicio": df_gaps["Inicio"],
            "Fin": df_gaps["Fin"],
            # Excel guarda tiempos como fracción del día
            "Duracion": (dur_seconds / 86400.0)
        })
    else:
        df_xlsx = pd.DataFrame(columns=["Inicio", "Fin", "Duracion"])

    try:
        # Intento 1: openpyxl
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df_xlsx.to_excel(writer, index=False, sheet_name="TiemposMuertos")
            ws = writer.book["TiemposMuertos"]
            # Formato de tiempo en la tercera columna
            from openpyxl.utils import get_column_letter
            dur_col_letter = get_column_letter(3)
            for row in range(2, ws.max_row + 1):
                ws[f"{dur_col_letter}{row}"].number_format = "[h]:mm:ss"
            ws.column_dimensions["A"].width = 10
            ws.column_dimensions["B"].width = 10
            ws.column_dimensions["C"].width = 12
        excel_bytes = output.getvalue()
    except Exception:
        # Fallback: xlsxwriter
        output = BytesIO()
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
        file_name=f"tiempos_muertos_{maquina_nombre}_{fecha_dia}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
    # === FIN EXPORTAR A EXCEL ===

    return {
        "Fecha": fecha_dia,
        "%_Perdido": indicadores["porcentaje_perdido"]
    }

def resumen_solo(fecha_dia):
    _, indicadores, _ = generar_reloj(
        df, maquina_id, fecha_dia, umbral_minutos=umbral_min
    )
    return {
        "Fecha": fecha_dia,
        "%_Perdido": indicadores["porcentaje_perdido"]
    }

if st.button("Generar gráfico(s)", type="primary", use_container_width=True):
    st.caption(f"Máquina seleccionada: **{maquina_nombre}**  ·  ID: `{maquina_id}`")
    resumen = []

    for f in fechas_seleccionadas:
        if not modo_multiple or mostrar_detalle:
            st.subheader(f"📅 Día {f}")
            res = render_dia(f)
            resumen.append(res)
            st.divider()
        else:
            res = resumen_solo(f)
            resumen.append(res)

    if len(resumen) > 1:
        st.subheader("📈 Resumen de días seleccionados")
        df_res = pd.DataFrame(resumen).sort_values("Fecha")
        st.dataframe(df_res, use_container_width=True)

        # 📉 Gráfico histórico (% Perdido)
        st.markdown("#### 📉 Histórico de % Perdido")
        labels = df_res["Fecha"].astype(str).tolist()
        x = range(len(labels))

        fig, ax = plt.subplots(figsize=(8, 3))
        ax.plot(x, df_res["%_Perdido"], marker="o", linewidth=2)
        ax.set_xlabel("Fecha")
        ax.set_ylabel("% Perdido")
        ax.set_ylim(bottom=0, top=df_res["%_Perdido"].max() * 2 if len(df_res) else 1)
        ax.set_xticks(list(x))
        ax.set_xticklabels(labels, rotation=45, ha="right")
        ax.grid(True, alpha=0.3)

        # Etiquetas (fuente 7 y margen 7% del máximo)
        for i, y in enumerate(df_res["%_Perdido"]):
            ax.text(
                i, y + (df_res["%_Perdido"].max() * 0.07),
                f"{y:.2f}%",
                ha="center", va="bottom", fontsize=7, fontweight="bold"
            )

        st.pyplot(fig, use_container_width=True)
