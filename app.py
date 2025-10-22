import streamlit as st
import pandas as pd
import requests
import io
from datetime import date
from reloj_circular import generar_reloj

# Configuración general
st.set_page_config(page_title="Reloj de Tiempos Muertos", layout="wide")
st.title("📊 Reloj Circular de Tiempos Muertos")

# =========================
# CONFIGURACIÓN GOOGLE SHEETS
# =========================
DRIVE_FILE_ID = ""
SHEET_EXPORT_URL = "https://docs.google.com/spreadsheets/d/1GSoaEg-ZUn5jB_VvLXcCkZjUnLR24ynIBPH3BcpCXXM/export?format=xlsx"


@st.cache_data(show_spinner=False)
def cargar_excel_desde_sheet(url: str) -> pd.DataFrame:
    df = pd.read_excel(url, sheet_name=0, engine="openpyxl")
    return df


def normalizar_columnas(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [str(c).strip() for c in df.columns]
    rename_map = {}

    for c in df.columns:
        cl = (str(c).strip().lower()
              .replace("í", "i")
              .replace("á", "a")
              .replace("é", "e")
              .replace("ó", "o")
              .replace("ú", "u"))
        if cl in ["fecha", "fecha y hora", "fecha/hora", "timestamp", "date", "datetime"]:
            rename_map[c] = "Fecha"
        if cl in ["id equipo", "id_equipo", "id maquina", "id máquina", "equipo", "machineid", "idequipo"]:
            rename_map[c] = "Id Equipo"

    df = df.rename(columns=rename_map)

    if "Fecha" not in df.columns or "Id Equipo" not in df.columns:
        raise ValueError("No se encuentran las columnas requeridas: 'Fecha' y 'Id Equipo'.")

    df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce", dayfirst=True)
    df["Id Equipo"] = df["Id Equipo"].astype(str).str.strip()
    return df


# =========================
# CARGA DE DATOS
# =========================
with st.spinner("Cargando datos de Google Sheets..."):
    raw = cargar_excel_desde_sheet(SHEET_EXPORT_URL)

try:
    df = normalizar_columnas(raw)
except Exception as e:
    st.error(f"Error al interpretar columnas: {e}")
    st.stop()

# =========================
# UI
# =========================
maquinas = sorted(df["Id Equipo"].dropna().unique())
if not maquinas:
    st.error("No se encontraron máquinas en el archivo.")
    st.stop()

col1, col2, col3 = st.columns([1, 1, 1])
maquina_sel = col1.selectbox("Máquina", maquinas, index=0)

fechas_disponibles = sorted(pd.Series(df["Fecha"].dt.date.dropna().unique()).tolist())
fecha_defecto = fechas_disponibles[0] if fechas_disponibles else date.today()
fecha_sel = col2.selectbox("Fecha", fechas_disponibles, index=fechas_disponibles.index(fecha_defecto) if fechas_disponibles else 0)

umbral_min = col3.number_input("Umbral de pausa no planificada (min)", min_value=1, max_value=30, value=3, step=1)

if st.button("Generar gráfico", type="primary"):
    with st.spinner("Procesando..."):
        fig, indicadores, lista_gaps = generar_reloj(df, maquina_sel, fecha_sel, umbral_minutos=umbral_min)

    st.pyplot(fig, use_container_width=True)

    st.divider()
    st.subheader("📋 Indicadores del día")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total disponible (min)", indicadores["total_disponible"])
    c2.metric("Inutilizado (pausas prog., min)", indicadores["inutilizado_programado"])
    c3.metric("Neto (min)", indicadores["neto"])
    c4.metric("Perdido no programado (min)", indicadores["perdido_no_programado"])
    c5.metric("% Perdido", indicadores["porcentaje_perdido"])

    st.divider()
    st.subheader("⏱️ Detalle de tiempos muertos")
    st.write(f"Total: **{len(lista_gaps)} intervalos**, sumando **{indicadores['perdido_no_programado']} min**")
    if lista_gaps:
        st.dataframe(pd.DataFrame(lista_gaps), use_container_width=True)
    else:
        st.info("No se detectaron tiempos muertos para este día.")
