import streamlit as st
import pandas as pd
from datetime import datetime
from reloj_circular import generar_reloj

st.set_page_config(page_title="Reloj de Tiempos Muertos", layout="wide")

st.title("📊 Reloj Circular de Tiempos Muertos")

uploaded_file = st.file_uploader("Subí el archivo Excel de producción", type=["xlsx"])

if uploaded_file:
    df = pd.read_excel(uploaded_file)
    df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")

    maquinas = sorted(df["Id Equipo"].dropna().unique())
    maquina_sel = st.selectbox("Seleccioná la máquina", maquinas)
    fechas = sorted(df["Fecha"].dt.date.unique())
    fecha_sel = st.selectbox("Seleccioná la fecha", fechas)

    if st.button("Generar gráfico"):
        fig, indicadores, lista_gaps = generar_reloj(df, maquina_sel, fecha_sel, umbral_minutos=3)
        st.pyplot(fig)

        st.divider()
        st.subheader("📋 Indicadores del día")
        col1, col2 = st.columns(2)
        col1.metric("Tiempo total disponible (min)", indicadores["total_disponible"])
        col1.metric("Tiempo inutilizado (pausas, min)", indicadores["inutilizado_programado"])
        col2.metric("Tiempo neto (min)", indicadores["neto"])
        col2.metric("Tiempo perdido no programado (min)", indicadores["perdido_no_programado"])
        st.metric("Porcentaje perdido (%)", indicadores["porcentaje_perdido"])

        st.divider()
        st.subheader("⏱️ Tiempos muertos detectados (>3 min)")
        st.write(f"Total: **{len(lista_gaps)} intervalos**, sumando **{indicadores['perdido_no_programado']} min**")

        if lista_gaps:
            df_gaps = pd.DataFrame(lista_gaps)
            st.dataframe(df_gaps, use_container_width=True)
        else:
            st.info("No se detectaron tiempos muertos para este día.")
