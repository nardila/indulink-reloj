import streamlit as st
import pandas as pd
from datetime import date
from reloj_circular import generar_reloj

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
    "1GSoaEg-ZUn5jB_VvLXcCkZjUnLR24ynIBPH3BcpCXXM/export?format=xlsx"
)

# =========================================================
# Carga de datos
# =========================================================
@st.cache_data(show_spinner=False)
def cargar_excel_desde_sheet(url: str) -> pd.DataFrame:
    # En el Sheet los encabezados reales están en la fila 2 → header=1
    df = pd.read_excel(url, sheet_name=0, engine="openpyxl", header=1)
    return df

def normalizar_columnas(df: pd.DataFrame) -> pd.DataFrame:
    # Limpieza básica de encabezados
    df.columns = [str(c).strip() for c in df.columns]

    # Mapear alias a nombres canónicos
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

    df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce", dayfirst=True)
    df["Id Equipo"] = df["Id Equipo"].astype(str).str.strip()
    return df

# Descargar y preparar datos
with st.spinner("Cargando datos de Google Sheets..."):
    raw = cargar_excel_desde_sheet(SHEET_EXPORT_URL)

try:
    df = normalizar_columnas(raw)
except Exception as e:
    st.error(f"Error al interpretar columnas: {e}")
    st.stop()

# =========================================================
# Interfaz
# =========================================================
maquinas = sorted(df["Id Equipo"].dropna().unique())
if not maquinas:
    st.error("No se encontraron máquinas en el archivo.")
    st.stop()

col1, col2, col3 = st.columns([1, 1, 1])
maquina_sel = col1.selectbox("Máquina", maquinas, index=0)

fechas_disponibles = sorted(pd.Series(df["Fecha"].dt.date.dropna().unique()).tolist())
fecha_defecto = fechas_disponibles[0] if fechas_disponibles else date.today()
fecha_sel = col2.selectbox(
    "Fecha",
    fechas_disponibles,
    index=fechas_disponibles.index(fecha_defecto) if fechas_disponibles else 0,
)

umbral_min = col3.number_input(
    "Umbral de pausa no planificada (min)",
    min_value=1, max_value=30, value=3, step=1,
)

# =========================================================
# Acción
# =========================================================
if st.button("Generar gráfico", type="primary"):
    with st.spinner("Procesando..."):
        fig, indicadores, lista_gaps = generar_reloj(
            df, maquina_sel, fecha_sel, umbral_minutos=umbral_min
        )

    # Gráfico
    st.pyplot(fig, use_container_width=True)

    # Indicadores
    st.divider()
    st.subheader("📋 Indicadores del día")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total disponible (min)", indicadores["total_disponible"])
    c2.metric("Inutilizado (pausas, min)", indicadores["inutilizado_programado"])
    c3.metric("Neto (min)", indicadores["neto"])
    c4.metric("Perdido no programado (min)", indicadores["perdido_no_programado"])
    c5.metric("% Perdido", indicadores["porcentaje_perdido"])

    # Detalle de tiempos muertos + descargas
    st.divider()
    st.subheader("⏱️ Tiempos muertos detectados (> umbral)")
    st.write(
        f"Total: **{len(lista_gaps)} intervalos**, "
        f"sumando **{indicadores['perdido_no_programado']} min**"
    )

    if lista_gaps:
        # ---------------------------
        # Armar DataFrame base
        # ---------------------------
        df_gaps = pd.DataFrame(lista_gaps)  # columnas: Inicio, Fin, Duracion_min (minutos exactos, sin redondeo)

        # ---------------------------
        # Duración en formato 00:00:00 para la TABLA
        # ---------------------------
        # Convertimos minutos (float) -> timedelta -> string HH:MM:SS
        td = pd.to_timedelta(df_gaps["Duracion_min"], unit="m")
        df_show = df_gaps.copy()
        df_show["Duracion"] = td.apply(lambda x: str(x).split(".")[0])  # HH:MM:SS (sin milisegundos)
        # Mostramos columnas limpias (sin Duracion_min para evitar confundir)
        df_show = df_show[["Inicio", "Fin", "Duracion"]]
        st.dataframe(df_show, use_container_width=True)

        # ---------------------------
        # Descarga CSV (con HH:MM:SS)
        # ---------------------------
        csv_df = df_show.copy()  # ya tiene Duracion como HH:MM:SS
        csv_bytes = csv_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "📥 Descargar detalle (CSV)",
            data=csv_bytes,
            file_name=f"tiempos_muertos_{maquina_sel}_{fecha_sel}.csv",
            mime="text/csv",
        )

        # ---------------------------
        # Descarga Excel (Duracion con formato [h]:mm:ss real)
        # ---------------------------
        # Para Excel, usamos valor numérico en días y aplicamos formato de hora
        xlsx_df = df_gaps.copy()
        xlsx_df["Duracion"] = pd.to_timedelta(xlsx_df["Duracion_min"], unit="m").dt.total_seconds() / 86400.0
        xlsx_df = xlsx_df[["Inicio", "Fin", "Duracion"]]  # Duracion en días (Excel time)

        from io import BytesIO
        from openpyxl.utils import get_column_letter
        output = BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            xlsx_df.to_excel(writer, index=False, sheet_name="TiemposMuertos")
            ws = writer.book["TiemposMuertos"]
            # Aplicar formato [h]:mm:ss a la columna Duracion (columna 3)
            dur_col_letter = get_column_letter(3)
            for row in range(2, ws.max_row + 1):
                ws[f"{dur_col_letter}{row}"].number_format = "[h]:mm:ss"

            # Ajuste de ancho básico
            ws.column_dimensions["A"].width = 10  # Inicio
            ws.column_dimensions["B"].width = 10  # Fin
            ws.column_dimensions["C"].width = 12  # Duracion

        st.download_button(
            "📥 Descargar detalle (Excel)",
            data=output.getvalue(),
            file_name=f"tiempos_muertos_{maquina_sel}_{fecha_sel}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    else:
        st.info("No se detectaron tiempos muertos para este día.")
