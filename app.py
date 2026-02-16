import streamlit as st
import pandas as pd
import numpy as np
import requests
from io import BytesIO
from datetime import datetime, timedelta, date

from reloj_circular import generar_reloj


# =========================
# Config
# =========================
st.set_page_config(page_title="Reloj Circular de Tiempos Muertos", layout="wide")

SHEET_XLSX_URL = "https://docs.google.com/spreadsheets/d/1clzNg0YblSQVvpWlWqeAwHKYiTyKcv-meWaI1RILAFo/export?format=xlsx"

MACHINE_NAME_TO_ID = {
    "Seccionadora": "4C4F686CDDA0",
    "Centro de Mecanizado 1": "84EA676CDDA0",
    "Centro de Mecanizado 2": "98D1676CDDA0",
    "Pegadora 1": "3C75A0C964EC",
    "Pegadora 2": "8C6EA51FB608",
    "Pegadoras (1+2)": ["3C75A0C964EC", "8C6EA51FB608"],
    "Centros de Mecanizado (1+2)": ["84EA676CDDA0", "98D1676CDDA0"],
}


# =========================
# Helpers
# =========================
@st.cache_data(show_spinner=False, ttl=60)
def download_xlsx(url: str) -> bytes:
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return r.content


def normalizar_columnas(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normaliza nombres esperados y tipos:
      - 'Fecha' -> datetime
      - 'Id Equipo' -> string
      - Permite columnas duplicadas (si vienen duplicadas, toma la 1ra)
    """
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]

    # Asegurar columnas requeridas
    required = {"Fecha", "Id Equipo"}
    if not required.issubset(set(df.columns)):
        raise ValueError(f"No se encuentran las columnas requeridas: {required - set(df.columns)}")

    # FIX CRÍTICO:
    # Si hay columnas duplicadas, df.loc[:, "Id Equipo"] devuelve DataFrame.
    # Tomamos la primera.
    id_equipo_col = df.loc[:, "Id Equipo"]
    if isinstance(id_equipo_col, pd.DataFrame):
        id_equipo_col = id_equipo_col.iloc[:, 0]
    df["Id Equipo"] = id_equipo_col.astype(str).str.strip()

    # Fecha (puede venir duplicada también)
    fecha_col = df.loc[:, "Fecha"]
    if isinstance(fecha_col, pd.DataFrame):
        fecha_col = fecha_col.iloc[:, 0]
    df["Fecha"] = pd.to_datetime(fecha_col, errors="coerce", infer_datetime_format=True)

    df = df.dropna(subset=["Fecha"])
    return df


def get_df_base() -> pd.DataFrame:
    content = download_xlsx(SHEET_XLSX_URL)
    df = pd.read_excel(BytesIO(content))
    df = normalizar_columnas(df)
    return df


def render_dia(df_base: pd.DataFrame, maquina_id, fecha_dia: date, umbral_min: float, turno: str):
    fig, indicadores, gaps = generar_reloj(
        df_base,
        maquina_id,
        fecha_dia,
        umbral_minutos=umbral_min,
        turno=turno
    )
    return fig, indicadores, gaps


# =========================
# UI
# =========================
st.title("Reloj Circular de Tiempos Muertos")

with st.spinner("Cargando datos desde Google Sheets..."):
    try:
        df_base = get_df_base()
    except Exception as e:
        st.error(str(e))
        st.stop()

# Máquinas disponibles en datos
ids_en_datos = set(df_base["Id Equipo"].astype(str).unique())

nombres_disponibles = [
    name for name, mid in MACHINE_NAME_TO_ID.items()
    if (
        (isinstance(mid, list) and all(_id in ids_en_datos for _id in mid))
        or (not isinstance(mid, list) and mid in ids_en_datos)
    )
]

# Si hay IDs no mapeados, mostrarlos como "Código: XXXX"
mapped_ids = set()
for _v in MACHINE_NAME_TO_ID.values():
    if isinstance(_v, list):
        mapped_ids.update(_v)
    else:
        mapped_ids.add(_v)

extras = [f"Código: {mid}" for mid in ids_en_datos if mid not in mapped_ids]

opciones_maquina = sorted(nombres_disponibles) + sorted(extras)

col1, col2, col3 = st.columns([1.2, 1.2, 2])

with col1:
    maquina = st.selectbox("Máquina", opciones_maquina)

with col2:
    umbral_min = st.number_input("Umbral de pausa no planificada (min)", min_value=0.0, value=3.0, step=0.5)

with col3:
    multi_fechas = st.toggle("Seleccionar múltiples fechas", value=False)
    multi_maquinas = st.toggle("Seleccionar múltiples máquinas", value=False)

# Turnos
turno_options = ["Mañana", "Tarde"]
turnos_sel = st.multiselect("Turnos", turno_options, default=["Mañana"])

# Fechas disponibles (desde df)
fechas_disponibles = sorted(df_base["Fecha"].dt.date.unique())

if multi_fechas:
    fechas_sel = st.multiselect("Fechas (podés elegir varias)", fechas_disponibles, default=fechas_disponibles[:1])
else:
    fecha_sel = st.selectbox("Fecha", fechas_disponibles)
    fechas_sel = [fecha_sel]

# Máquinas seleccionadas
if multi_maquinas:
    maquinas_sel = st.multiselect("Máquinas (podés elegir varias)", opciones_maquina, default=[maquina])
else:
    maquinas_sel = [maquina]

if st.button("Generar gráfico(s)"):
    if not fechas_sel:
        st.warning("Seleccioná al menos una fecha.")
        st.stop()
    if not maquinas_sel:
        st.warning("Seleccioná al menos una máquina.")
        st.stop()
    if not turnos_sel:
        st.warning("Seleccioná al menos un turno.")
        st.stop()

    resumen_rows = []

    for maq_name in maquinas_sel:
        if maq_name.startswith("Código: "):
            maq_id = maq_name.replace("Código: ", "").strip()
            maq_label = maq_name
        else:
            maq_id = MACHINE_NAME_TO_ID.get(maq_name, maq_name)
            maq_label = maq_name

        for turno in turnos_sel:
            st.subheader(f"{maq_label} — Turno {turno}")

            for f in sorted(fechas_sel):
                fig, indicadores, gaps = render_dia(df_base, maq_id, f, umbral_min, turno)

                st.markdown(f"### Día {f}")
                st.pyplot(fig, clear_figure=True)

                # Indicadores
                cA, cB, cC, cD = st.columns(4)
                cA.metric("Tiempo total disponible (min)", f"{indicadores['total_disponible']:.2f}")
                cB.metric("Paradas programadas (min)", f"{indicadores['inutilizado_programado']:.2f}")
                cC.metric("Paradas no programadas (min)", f"{indicadores['perdido_no_programado']:.2f}")
                cD.metric("% Perdido", f"{indicadores['porcentaje_perdido']:.2f}%")

                # Detalle gaps
                if gaps:
                    st.dataframe(pd.DataFrame(gaps), use_container_width=True)
                else:
                    st.info("Sin gaps no programados para este día/turno.")

                resumen_rows.append({
                    "Maquina": maq_label,
                    "Turno": turno,
                    "Fecha": f,
                    "Tiempo total (min)": indicadores["total_disponible"],
                    "Programado (min)": indicadores["inutilizado_programado"],
                    "No programado (min)": indicadores["perdido_no_programado"],
                    "% Perdido": indicadores["porcentaje_perdido"],
                })

    if resumen_rows:
        st.markdown("## Resumen de días seleccionados")
        df_resumen = pd.DataFrame(resumen_rows).sort_values(["Maquina", "Turno", "Fecha"])
        st.dataframe(df_resumen, use_container_width=True)
