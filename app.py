import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO
from datetime import datetime, date, timedelta

from reloj_circular import generar_reloj

st.set_page_config(page_title="Reloj Circular Indulink", layout="wide")

st.title("🕒 Dashboard de Tiempos Muertos – Indulink")

st.markdown("""
**Cómo usar**
1) Elegí la fecha y la máquina.
2) Presioná **Generar gráfico**.
3) Podés **descargar** el PNG.
""")

# === Carga desde Google Sheets público (solo lectura) ===
SHEET_EXPORT_URL = "https://docs.google.com/spreadsheets/d/1GSoaEg-ZUn5jB_VvLXcCkZjUnLR24ynIBPH3BcpCXXM/export?format=xlsx"

@st.cache_data(show_spinner=False)
def cargar_excel_desde_google_sheet(url: str) -> pd.DataFrame:
    df_raw = pd.read_excel(url, sheet_name=0, engine="openpyxl")
    df = df_raw.copy()

    # Si la primera fila parece encabezado, usarla como header real
    if df.shape[0] > 0:
        possible_headers = set(str(x).strip().lower() for x in df.iloc[0].tolist())
        if ("fecha" in possible_headers) or ("id equipo" in possible_headers) or ("id_equipo" in possible_headers):
            df.columns = df.iloc[0]
            df = df[1:]

    # Normalizar nombres de columnas
    df.columns = [str(c).strip() for c in df.columns]

    # Mapear alias a columnas canónicas
    rename_map = {}
    for c in df.columns:
        cl = (c.strip().lower()
              .replace("í","i").replace("á","a").replace("é","e").replace("ó","o").replace("ú","u"))
        if cl in ["fecha", "date", "timestamp", "fecha y hora", "fecha/hora"]:
            rename_map[c] = "timestamp"
        if cl in ["id equipo", "id_equipo", "idequipo", "id maquina", "id máquina", "machineid", "equipo"]:
            rename_map[c] = "id_equipo"
    df = df.rename(columns=rename_map)

    return df

with st.spinner("Cargando datos desde Google Sheets..."):
    df = cargar_excel_desde_google_sheet(SHEET_EXPORT_URL)

# Validaciones
if "timestamp" not in df.columns or "id_equipo" not in df.columns:
    st.error("No se encuentran las columnas necesarias (`timestamp` y `id_equipo`). Verificá la hoja de cálculo.")
    st.stop()

# Tipos
df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", dayfirst=True)
df["id_equipo"] = df["id_equipo"].astype(str).str.strip()

# Controles UI
col1, col2, col3 = st.columns([1,1,1])
fecha_sel = col1.date_input("Fecha", value=date.today())
maquinas = sorted(df["id_equipo"].dropna().astype(str).str.strip().unique())
maquina_sel = col2.selectbox("Máquina", maquinas)
umbral_min = col3.number_input("Umbral de pausa no planificada (min)", min_value=1, max_value=30, value=3, step=1)

if st.button("Generar gráfico", type="primary"):
    with st.spinner("Procesando..."):
        fig, indicadores, alerta = generar_reloj(df, maquina_sel, fecha_sel, umbral_minutos=umbral_min)
    if alerta:
        st.warning(alerta)
    if fig is None:
        st.error("No hay datos para esa combinación de fecha y máquina después del filtrado.")
    else:
        st.pyplot(fig, use_container_width=True)
        st.subheader("Indicadores del día")
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Total disponible (min)", f"{indicadores['total_disponible']:.0f}")
        c2.metric("Inutilizado programado (min)", f"{indicadores['inutilizado_programado']:.0f}")
        c3.metric("Neto (min)", f"{indicadores['neto']:.0f}")
        c4.metric("Perdido no programado (min)", f"{indicadores['perdido_no_programado']:.0f}")
        c5.metric("% Perdido", f"{indicadores['porcentaje_perdido']:.2f}%")
        out = BytesIO()
        fig.savefig(out, format="png", dpi=300, bbox_inches="tight")
        st.download_button("📥 Descargar PNG", out.getvalue(),
                           file_name=f"reloj_tiempos_muertos_{maquina_sel}_{fecha_sel}.png",
                           mime="image/png")
