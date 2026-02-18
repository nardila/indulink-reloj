import streamlit as st
import pandas as pd
from datetime import date, datetime, timedelta
from reloj_circular import generar_reloj, DEFAULT_TURNOS
import matplotlib.pyplot as plt

# ======================================
# Config UI
# ======================================
st.set_page_config(page_title="Reloj Circular", layout="wide")

# =========================================================
# Config de fuente (Drive)
# =========================================================
SHEET_XLSX_URL = "https://docs.google.com/spreadsheets/d/1clzNg0YblSQVvpWlWqeAwHKYiTyKcv-meWaI1RILAFo/export?format=xlsx"

# =========================================================
# Mapeo máquina (id → nombre amigable)
# =========================================================
MACHINE_NAME_TO_ID = {
    "Seccionadora": "4C4F686CDDA0",
    "Centro de Mecanizado 1": "84EA676CDDA0",
    "Centro de Mecanizado 2": "98D1676CDDA0",
    "Pegadora 1": "3C75A0C964EC",
    "Pegadora 2": "8C6EA51FB608",
}

MACHINE_GROUPS = {
    "Pegadoras (1+2)": ["3C75A0C964EC", "8C6EA51FB608"],
    "Centros de Mecanizado (1+2)": ["84EA676CDDA0", "98D1676CDDA0"],
}

ID_TO_MACHINE_NAME = {v: k for k, v in MACHINE_NAME_TO_ID.items() if isinstance(v, str)}

# =========================================================
# Carga de datos
# =========================================================
@st.cache_data(show_spinner=False, ttl=60)
def load_data_from_google_sheet(url: str) -> pd.DataFrame:
    # Descarga XLSX desde Google Sheets
    df = pd.read_excel(url)

    # Normalización nombres de columnas
    rename_map = {}
    for c in df.columns:
        cl = str(c).strip().lower()
        cl = (
            cl.replace("_", " ").replace("-", " ")
            .replace("á", "a").replace("í", "i").replace("é", "e")
            .replace("ó", "o").replace("ú", "u")
        )
        if cl in ["fecha", "fecha y hora", "fecha/hora", "timestamp", "date", "datetime"]:
            rename_map[c] = "Fecha"
        if cl in ["id equipo", "id_equipo", "id maquina", "id máquina", "equipo", "machineid", "idequipo"]:
            rename_map[c] = "Id Equipo"
    df = df.rename(columns=rename_map)

    # Parse de Fecha
    if "Fecha" in df.columns:
        df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")

    return df


st.title("Reloj Circular de Tiempos Muertos")

with st.spinner("Cargando datos desde Google Sheets…"):
    df = load_data_from_google_sheet(SHEET_XLSX_URL)

if df.empty:
    st.error("No se cargaron datos desde Google Sheets.")
    st.stop()

if "Fecha" not in df.columns or "Id Equipo" not in df.columns:
    st.error("El dataset no contiene las columnas requeridas: Fecha e Id Equipo.")
    st.stop()

# IDs disponibles en datos
ids_en_datos = sorted(df["Id Equipo"].dropna().astype(str).unique())

# Construimos lista visible de nombres:
# 1) Primero los nombres mapeados que estén en los datos
nombres_disponibles = [name for name, mid in MACHINE_NAME_TO_ID.items() if mid in ids_en_datos]

# Grupos (solo se muestran si ambas máquinas existen en los datos)
grupos_disponibles = [gname for gname, mids in MACHINE_GROUPS.items() if all(mid in ids_en_datos for mid in mids)]

# 2) Si hay IDs en los datos que no estén en el mapeo, los agregamos como “Código: <id>”
extras = [f"Código: {mid}" for mid in ids_en_datos if mid not in MACHINE_NAME_TO_ID.values()]

opciones_maquina = nombres_disponibles + grupos_disponibles + extras


def _resolver_maquina(mv: str):
    """Devuelve (nombre_visible, maquina_id_o_lista)."""
    if mv.startswith("Código: "):
        mid = mv.replace("Código: ", "").strip()
        return ID_TO_MACHINE_NAME.get(mid, mid), mid
    if mv in MACHINE_GROUPS:
        return mv, MACHINE_GROUPS[mv]
    mid = MACHINE_NAME_TO_ID.get(mv, mv)
    return mv, mid


col_top1, col_top2, col_top3 = st.columns([1, 1, 1])

# 🔀 NUEVO: toggle para múltiples máquinas
modo_multiple_maquinas = col_top1.toggle("Seleccionar múltiples máquinas", value=False)

if not modo_multiple_maquinas:
    # Selección única (comportamiento anterior)
    maquina_vis = col_top1.selectbox("Máquina", opciones_maquina, index=0)
    maquina_nombre_unica, maquina_id_unica = _resolver_maquina(maquina_vis)
    maquinas_seleccionadas = [(maquina_nombre_unica, maquina_id_unica)]
else:
    # Selección múltiple
    maquinas_pick = col_top1.multiselect("Máquinas", opciones_maquina, default=nombres_disponibles[:1] if nombres_disponibles else [])
    if not maquinas_pick:
        st.stop()
    maquinas_seleccionadas = []
    for mv in maquinas_pick:
        mname, mid = _resolver_maquina(mv)
        maquinas_seleccionadas.append((mname, mid))

fechas_disponibles = sorted(pd.Series(df["Fecha"].dt.date.dropna().unique()).tolist())

modo_multiple_fechas = col_top2.toggle("Seleccionar múltiples fechas", value=False)
if not modo_multiple_fechas:
    fecha_unica = col_top2.selectbox("Fecha", fechas_disponibles, index=len(fechas_disponibles) - 1)
    fechas_seleccionadas = [fecha_unica]
else:
    fechas_pick = col_top2.multiselect("Fechas", fechas_disponibles, default=fechas_disponibles[-5:] if len(fechas_disponibles) >= 5 else fechas_disponibles)
    if not fechas_pick:
        st.stop()
    fechas_seleccionadas = sorted(fechas_pick)

umbral_min = int(col_top3.number_input("Umbral pausa no planificada (min)", min_value=0, max_value=120, value=3, step=1))

# Turnos
turnos_default = list(DEFAULT_TURNOS.keys())
turnos_sel = st.multiselect("Turnos", turnos_default, default=["Mañana"] if "Mañana" in turnos_default else turnos_default[:1])

# ===== contador total utilizado (suma de Parcial>0) en el turno seleccionado =====
def contador_total_utilizado(df_base: pd.DataFrame, maquina_id, fecha_dia, turno: str) -> float:
    # límites del turno desde el motor (evita duplicar lógica)
    _fig, indicadores, _gaps = generar_reloj(df_base, maquina_id, fecha_dia, umbral_minutos=umbral_min, turno=turno)
    inicio = indicadores.get("inicio")
    fin = indicadores.get("fin")
    if inicio is None or fin is None:
        return 0.0

    mask_eq = df_base["Id Equipo"].isin(list(maquina_id)) if isinstance(maquina_id, (list, tuple, set)) else (df_base["Id Equipo"] == maquina_id)
    d = df_base[mask_eq].copy()
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
    # generar_reloj recibe el ID de equipo (o lista si es grupo)
    fig, indicadores, lista_gaps = generar_reloj(
        df_base, maquina_id, fecha_dia, umbral_minutos=umbral_min, turno=turno
    )
    st.pyplot(fig, use_container_width=True)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total disponible (min)", f"{indicadores['total_disponible']:.2f}")
    c2.metric("Inutilizado (pausas, min)", f"{indicadores['inutilizado_programado']:.2f}")
    c3.metric("Neto (min)", f"{indicadores['neto']:.2f}")
    c4.metric("No programado (min)", f"{indicadores['perdido_no_programado']:.2f}")
    c5.metric("% Perdido", f"{indicadores['porcentaje_perdido']:.2f}%")

    # Tabla de gaps
    if lista_gaps:
        st.dataframe(pd.DataFrame(lista_gaps), use_container_width=True)
    else:
        st.info("No hay gaps no programados para este día/turno.")

def resumen_solo(df_base: pd.DataFrame, maquina_id: str, fecha_dia: date, umbral_min: int, turno: str):
    _, indicadores, _ = generar_reloj(
        df_base, maquina_id, fecha_dia, umbral_minutos=umbral_min, turno=turno
    )
    total_contador = contador_total_utilizado(df_base, maquina_id, fecha_dia, turno)
    return {
        "Fecha": fecha_dia,
        "Turno": turno,
        "Total disponible (min)": indicadores["total_disponible"],
        "Inutilizado (min)": indicadores["inutilizado_programado"],
        "Neto (min)": indicadores["neto"],
        "No programado (min)": indicadores["perdido_no_programado"],
        "% Perdido": indicadores["porcentaje_perdido"],
        "Contador total (Parcial>0)": total_contador,
    }

st.divider()

# =========================================================
# Generación
# =========================================================
if st.button("Generar"):
    resumen_rows = []

    for maquina_nombre, maquina_id in maquinas_seleccionadas:
        st.header(f"Máquina: {maquina_nombre}")

        for turno in turnos_sel:
            st.subheader(f"Turno: {turno}")

            for fecha_dia in fechas_seleccionadas:
                st.markdown(f"### Día: {fecha_dia}")
                render_dia(df, maquina_id, maquina_nombre, fecha_dia, umbral_min, turno)
                resumen_rows.append({
                    "Máquina": maquina_nombre,
                    **resumen_solo(df, maquina_id, fecha_dia, umbral_min, turno)
                })

    if resumen_rows:
        st.divider()
        st.subheader("Resumen de días seleccionados")
        df_resumen = pd.DataFrame(resumen_rows)
        st.dataframe(df_resumen, use_container_width=True)
