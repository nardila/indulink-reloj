import io
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

from reloj_circular import generar_reloj


# =========================================================
# Config general
# =========================================================
st.set_page_config(page_title="Reloj Circular de Tiempos Muertos", layout="wide")

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
            c.lower()
            .replace("á", "a")
            .replace("é", "e")
            .replace("í", "i")
            .replace("ó", "o")
            .replace("ú", "u")
        )
        if cl in {"fecha", "timestamp", "time"}:
            rename_map[c] = "Fecha"
        elif cl in {"id equipo", "id_equipo", "equipo", "maquina", "id"}:
            rename_map[c] = "Id Equipo"
        elif cl in {"contador", "count", "k"}:
            rename_map[c] = "Contador"
        elif cl in {"parcial", "j"}:
            rename_map[c] = "Parcial"
    if rename_map:
        df = df.rename(columns=rename_map)

    # Validaciones mínimas
    required = {"Fecha", "Id Equipo"}
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(
            f"Error al interpretar columnas: No se encuentran las columnas requeridas: {missing}"
        )

    df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")
    df = df.dropna(subset=["Fecha"])
    df["Id Equipo"] = df["Id Equipo"].astype(str).str.strip()

    # Si existen, aseguramos numéricos
    if "Parcial" in df.columns:
        df["Parcial"] = pd.to_numeric(df["Parcial"], errors="coerce").fillna(0)
    if "Contador" in df.columns:
        df["Contador"] = pd.to_numeric(df["Contador"], errors="coerce").fillna(0)

    return df

def fmt_hms(td: timedelta) -> str:
    total_seconds = int(td.total_seconds())
    if total_seconds < 0:
        total_seconds = 0
    h = total_seconds // 3600
    m = (total_seconds % 3600) // 60
    s = total_seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

def fmt_percent(x: float) -> str:
    return f"{x:.2f}%"

def render_historico_linea(df_resumen: pd.DataFrame):
    import matplotlib.pyplot as plt

    if df_resumen.empty:
        st.info("No hay datos para graficar histórico.")
        return

    df_plot = df_resumen.copy()
    df_plot = df_plot.sort_values("Fecha")
    x = df_plot["Fecha"].astype(str).tolist()
    y = df_plot["% Perdido"].astype(float).tolist()

    max_y = max(y) if y else 0.0
    y_max = max(0.0, 2.0 * max_y)

    fig = plt.figure(figsize=(10, 4.5))
    ax = fig.add_subplot(111)
    ax.plot(x, y, marker="o")
    ax.set_ylabel("% Perdido")
    ax.set_xlabel("Fecha")
    ax.set_ylim(0, y_max)

    # etiquetas arriba (fuente 20% más chica)
    for xi, yi in zip(x, y):
        ax.text(xi, yi + (y_max * 0.02 if y_max > 0 else 0.5), f"{yi:.2f}%", ha="center", va="bottom", fontsize=10)

    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()
    st.pyplot(fig, clear_figure=True)

def construir_excel_export(df_detalles_por_dia: list, df_resumen: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        if not df_resumen.empty:
            df_resumen.to_excel(writer, index=False, sheet_name="Resumen")

        for item in df_detalles_por_dia:
            sheet = item["sheet_name"]
            df_det = item["df_detalle"]
            df_det.to_excel(writer, index=False, sheet_name=sheet[:31])

    return output.getvalue()

# =========================================================
# UI
# =========================================================
st.title("Reloj Circular de Tiempos Muertos")

with st.spinner("Cargando datos desde Google Sheets..."):
    df_raw = cargar_excel_desde_sheet(SHEET_EXPORT_URL)

try:
    df_base = normalizar_columnas(df_raw)
except Exception as e:
    st.error(str(e))
    st.stop()

# Máquina (single o múltiple)
st.subheader("Parámetros")

colA, colB, colC = st.columns([1.2, 1.2, 1.2])

with colA:
    multi_maquinas = st.toggle("Seleccionar múltiples máquinas", value=False)

with colB:
    multi_fechas = st.toggle("Seleccionar múltiples fechas", value=False)

with colC:
    umbral_min = st.number_input("Umbral de pausa no planificada (min)", min_value=0.0, value=3.0, step=0.5)

# máquinas disponibles (por dataset)
maquinas_disponibles = sorted(df_base["Id Equipo"].dropna().unique().tolist())
nombres_disponibles = [ID_TO_MACHINE_NAME.get(mid, mid) for mid in maquinas_disponibles]

if multi_maquinas:
    sel_maquinas_nombres = st.multiselect(
        "Máquinas (podés elegir varias)",
        options=nombres_disponibles,
        default=[nombres_disponibles[0]] if nombres_disponibles else [],
    )
    sel_maquinas_ids = [MACHINE_NAME_TO_ID.get(n, n) for n in sel_maquinas_nombres]
else:
    sel_maquina_nombre = st.selectbox("Máquina", options=nombres_disponibles)
    sel_maquinas_ids = [MACHINE_NAME_TO_ID.get(sel_maquina_nombre, sel_maquina_nombre)]

# fechas disponibles
fechas_disponibles = sorted(df_base["Fecha"].dt.date.dropna().unique().tolist())

if multi_fechas:
    sel_fechas = st.multiselect("Fechas (podés elegir varias)", options=fechas_disponibles, default=fechas_disponibles[:1])
else:
    sel_fecha = st.selectbox("Fecha", options=fechas_disponibles)
    sel_fechas = [sel_fecha]

# Turnos
st.subheader("Turnos")
turnos_sel = st.multiselect(
    "Seleccioná uno o más turnos",
    options=["Mañana", "Tarde"],
    default=["Mañana"],
)

btn = st.button("Generar gráfico(s)", type="primary", use_container_width=True)

if btn:
    if not sel_maquinas_ids or not sel_fechas:
        st.warning("Elegí al menos una máquina y una fecha.")
        st.stop()

    resumen_rows = []
    detalles_excel = []

    for maquina_id in sel_maquinas_ids:
        nombre_maquina = ID_TO_MACHINE_NAME.get(maquina_id, maquina_id)

        for fecha_dia in sel_fechas:
            for turno in turnos_sel:
                st.markdown(f"### {nombre_maquina} — Día {fecha_dia} — Turno {turno}")

                fig, indicadores, lista_gaps = generar_reloj(
                    df_base,
                    maquina_id,
                    fecha_dia,
                    umbral_minutos=float(umbral_min),
                    turno=turno,
                )

                c1, c2, c3, c4, c5 = st.columns(5)
                c1.metric("Tiempo disponible (min)", f"{indicadores['total_disponible']:.2f}")
                c2.metric("Programado (min)", f"{indicadores['inutilizado_programado']:.2f}")
                c3.metric("No programado (min)", f"{indicadores['perdido_no_programado']:.2f}")
                c4.metric("% Perdido", f"{indicadores['porcentaje_perdido']:.2f}%")
                c5.metric("Contador total", f"{indicadores.get('contador_total', 0)}")

                st.pyplot(fig, clear_figure=True)

                df_gaps = pd.DataFrame(lista_gaps)
                if not df_gaps.empty:
                    # asegurar formato HH:MM:SS (sin "0 days")
                    if "Duracion" in df_gaps.columns:
                        # ya viene como HH:MM:SS
                        pass
                    st.dataframe(df_gaps, use_container_width=True)
                else:
                    st.info("No se detectaron tiempos muertos según el umbral y reglas.")

                resumen_rows.append(
                    {
                        "Máquina": nombre_maquina,
                        "Id Equipo": maquina_id,
                        "Fecha": fecha_dia,
                        "Turno": turno,
                        "Tiempo disponible (min)": float(indicadores["total_disponible"]),
                        "Programado (min)": float(indicadores["inutilizado_programado"]),
                        "No programado (min)": float(indicadores["perdido_no_programado"]),
                        "% Perdido": float(indicadores["porcentaje_perdido"]),
                        "Contador total": int(indicadores.get("contador_total", 0)),
                    }
                )

                # Excel detalle
                sheet_name = f"{nombre_maquina}_{fecha_dia}_{turno}".replace(" ", "_")
                detalles_excel.append(
                    {
                        "sheet_name": sheet_name,
                        "df_detalle": df_gaps,
                    }
                )

    df_resumen = pd.DataFrame(resumen_rows)

    st.divider()
    st.subheader("Resumen de días seleccionados")
    st.dataframe(df_resumen, use_container_width=True)

    st.subheader("Histórico de % perdido")
    # Para histórico: agrupamos por fecha en orden cronológico SOLO con fechas existentes
    df_hist = df_resumen[["Fecha", "% Perdido"]].copy()
    df_hist = df_hist.groupby("Fecha", as_index=False).mean(numeric_only=True)
    render_historico_linea(df_hist)

    # Export Excel
    try:
        xlsx_bytes = construir_excel_export(detalles_excel, df_resumen)
        st.download_button(
            "Descargar Excel",
            data=xlsx_bytes,
            file_name="reloj_tiempos_muertos.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    except Exception as e:
        st.error(f"No se pudo generar Excel: {e}")
