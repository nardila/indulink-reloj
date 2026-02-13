import io
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
from datetime import datetime
from reloj_circular import generar_reloj, generar_reloj_multi

st.set_page_config(page_title="Reloj Circular de Tiempos Muertos", layout="wide")

MACHINE_NAME_TO_ID = {
    "Seccionadora": "4C4F686CDDA0",
    "Centro de Mecanizado 1": "84EA676CDDA0",
    "Centro de Mecanizado 2": "98D1676CDDA0",
    "Pegadora 1": "3C75A0C964EC",
    "Pegadora 2": "8C6EA51FB608",
}
ID_TO_MACHINE_NAME = {v: k for k, v in MACHINE_NAME_TO_ID.items()}

# Grupos de máquinas que suelen operar alternadas con el mismo equipo
MACHINE_GROUPS = {
    "Pegadoras (equipo)": ["3C75A0C964EC", "8C6EA51FB608"],
    "Centros de Mecanizado (equipo)": ["84EA676CDDA0", "98D1676CDDA0"],
}


def cargar_excel(uploaded_file):
    df = pd.read_excel(uploaded_file, engine="openpyxl")

    # Ajuste defensivo de columnas esperadas
    # (mantenemos tu lógica actual lo más intacta posible)
    if "Fecha" not in df.columns:
        for c in df.columns:
            if "fecha" in str(c).lower():
                df = df.rename(columns={c: "Fecha"})
                break

    if "Id Equipo" not in df.columns:
        for c in df.columns:
            if "equipo" in str(c).lower() or "id equipo" in str(c).lower():
                df = df.rename(columns={c: "Id Equipo"})
                break

    df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")
    df = df.dropna(subset=["Fecha", "Id Equipo"])
    df["Id Equipo"] = df["Id Equipo"].astype(str).str.strip()

    return df


def contador_total_utilizado(df_base, maquina_id, fecha_dia):
    # Mantenemos tu lógica, pero permitimos lista (consolidación por grupos)
    if fecha_dia is None:
        return 0

    if isinstance(maquina_id, (list, tuple, set)):
        d = df_base[(df_base["Id Equipo"].isin(list(maquina_id))) &
                    (df_base["Fecha"].dt.date == fecha_dia)].copy()
    else:
        d = df_base[(df_base["Id Equipo"] == maquina_id) &
                    (df_base["Fecha"].dt.date == fecha_dia)].copy()

    if d.empty:
        return 0

    # Busca columna "contador total" con heurística existente
    contador_candidates = [c for c in d.columns if "contador" in str(c).lower() or str(c).strip().upper() == "K"]
    if contador_candidates:
        col_k = contador_candidates[0]
        try:
            return int(pd.to_numeric(d[col_k], errors="coerce").fillna(0).max())
        except Exception:
            return 0

    return 0


def render_dia(df_base, maquina_id, maquina_nombre, fecha_dia, umbral_min):
    st.subheader(f"Día {fecha_dia} · {maquina_nombre}")

    if isinstance(maquina_id, (list, tuple, set)):
        fig, indicadores, lista_gaps = generar_reloj_multi(
            df_base, list(maquina_id), fecha_dia, umbral_minutos=umbral_min, etiqueta=maquina_nombre
        )
    else:
        fig, indicadores, lista_gaps = generar_reloj(
            df_base, maquina_id, fecha_dia, umbral_minutos=umbral_min
        )

    st.pyplot(fig, clear_figure=True)

    total_contador = contador_total_utilizado(df_base, maquina_id, fecha_dia)

    col_a, col_b, col_c, col_d, col_e = st.columns(5)
    col_a.metric("Disponible total (min)", f"{indicadores['total_disponible']:.2f}")
    col_b.metric("Paradas programadas (min)", f"{indicadores['inutilizado_programado']:.2f}")
    col_c.metric("Paradas no programadas (min)", f"{indicadores['perdido_no_programado']:.2f}")
    col_d.metric("% Perdido", f"{indicadores['porcentaje_perdido']:.2f}%")
    col_e.metric("Contador total (K)", f"{total_contador}")

    df_gaps = pd.DataFrame(lista_gaps)
    if not df_gaps.empty:
        # Formato HH:MM:SS sin "days"
        df_gaps["Duracion"] = df_gaps["Duracion"].apply(
            lambda td: f"{int(td.total_seconds()//3600):02d}:{int((td.total_seconds()%3600)//60):02d}:{int(td.total_seconds()%60):02d}"
        )
        st.dataframe(df_gaps[["Inicio", "Fin", "Duracion"]], use_container_width=True)

    return indicadores, total_contador, df_gaps


st.title("📊 Reloj Circular de Tiempos Muertos")

uploaded_file = st.file_uploader("Subí el archivo Excel de producción", type=["xlsx"])

if uploaded_file is None:
    st.stop()

try:
    df_base = cargar_excel(uploaded_file)
except Exception as e:
    st.error(f"Error al interpretar columnas: {e}")
    st.stop()

fechas_disponibles = sorted(df_base["Fecha"].dt.date.dropna().unique())
if len(fechas_disponibles) == 0:
    st.warning("No se detectaron fechas válidas en el archivo.")
    st.stop()

col_top1, col_top2, col_top3 = st.columns([1.2, 1.0, 2.2])

with col_top1:
    st.subheader("Máquina")
    multi_maquinas = st.toggle("Seleccionar múltiples máquinas", value=False)

    if not multi_maquinas:
        maquina_nombre = st.selectbox("Máquina", list(MACHINE_NAME_TO_ID.keys()))
        maquinas_seleccionadas = [(maquina_nombre, MACHINE_NAME_TO_ID[maquina_nombre])]
    else:
        maquinas_seleccionadas = []
        selec = st.multiselect("Máquinas", list(MACHINE_NAME_TO_ID.keys()), default=list(MACHINE_NAME_TO_ID.keys()))
        for mname in selec:
            maquinas_seleccionadas.append((mname, MACHINE_NAME_TO_ID[mname]))

    # NUEVO: consolidación por grupos (mismo equipo)
    modo_consolidar_grupos = st.toggle(
        "Consolidar por grupos (mismo equipo)",
        value=False,
        help="Calcula pérdidas cuando ninguna máquina del grupo reporta actividad. Si no es el mismo equipo, no lo uses."
    )

with col_top2:
    st.subheader("Fechas")
    multi_fechas = st.toggle("Seleccionar múltiples fechas", value=False)

    if not multi_fechas:
        fecha = st.selectbox("Fecha", fechas_disponibles, index=len(fechas_disponibles) - 1)
        fechas_seleccionadas = [fecha]
    else:
        fechas_seleccionadas = st.multiselect("Fechas (podés elegir varias)", fechas_disponibles, default=fechas_disponibles[-3:])

with col_top3:
    st.subheader("Parámetros")
    umbral_min = st.number_input("Umbral de pausa no planificada (min)", min_value=1, max_value=120, value=3, step=1)
    mostrar_detalle = st.toggle(
        "Mostrar gráficos individuales (solo aplica si hay múltiples fechas)",
        value=True,
        help="Si lo apagás, podés mostrar solo el resumen agregado sin renderizar todos los polares."
    )

st.divider()

if st.button("Generar gráfico(s)", use_container_width=True):
    if not maquinas_seleccionadas:
        st.warning("Seleccioná al menos una máquina.")
        st.stop()
    if not fechas_seleccionadas:
        st.warning("Seleccioná al menos una fecha.")
        st.stop()

    fechas_ordenadas = sorted(fechas_seleccionadas)

    # Armamos objetivos de cálculo (máquinas individuales o grupos)
    objetivos = []  # (label, maquina_id_o_lista)
    if modo_consolidar_grupos:
        ids_sel = [mid for _, mid in maquinas_seleccionadas]
        for gname, gids in MACHINE_GROUPS.items():
            if any(mid in gids for mid in ids_sel):
                objetivos.append((gname, gids))
        ids_en_grupos = set([x for _, gids in objetivos for x in gids])
        for mname, mid in maquinas_seleccionadas:
            if mid not in ids_en_grupos:
                objetivos.append((mname, mid))
    else:
        objetivos = [(mname, mid) for mname, mid in maquinas_seleccionadas]

    for maquina_nombre, maquina_id in objetivos:
        st.header(f"🏭 {maquina_nombre}")

        resumen_rows = []
        detalles_para_export = []

        for f in fechas_ordenadas:
            if (not multi_fechas) or mostrar_detalle:
                indicadores, total_k, df_gaps = render_dia(df_base, maquina_id, maquina_nombre, f, umbral_min)
            else:
                # Si no renderizamos el polar, igual calculamos indicadores
                if isinstance(maquina_id, (list, tuple, set)):
                    _fig, indicadores, _gaps = generar_reloj_multi(df_base, list(maquina_id), f, umbral_minutos=umbral_min, etiqueta=maquina_nombre)
                else:
                    _fig, indicadores, _gaps = generar_reloj(df_base, maquina_id, f, umbral_minutos=umbral_min)
                total_k = contador_total_utilizado(df_base, maquina_id, f)
                df_gaps = pd.DataFrame(_gaps)

            resumen_rows.append({
                "Fecha": f,
                "Disponible_total_min": indicadores["total_disponible"],
                "Paradas_programadas_min": indicadores["inutilizado_programado"],
                "Paradas_no_programadas_min": indicadores["perdido_no_programado"],
                "%_Perdido": indicadores["porcentaje_perdido"],
                "Contador_total_K": total_k
            })

            if df_gaps is not None and not df_gaps.empty:
                df_gaps2 = df_gaps.copy()
                df_gaps2.insert(0, "Fecha", f)
                detalles_para_export.append(df_gaps2)

        df_resumen = pd.DataFrame(resumen_rows)
        st.subheader("Resumen de días seleccionados")
        st.dataframe(df_resumen, use_container_width=True)

        # Export resumen + detalle
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df_resumen.to_excel(writer, index=False, sheet_name="Resumen")
            if detalles_para_export:
                df_det = pd.concat(detalles_para_export, ignore_index=True)
                df_det.to_excel(writer, index=False, sheet_name="Detalle gaps")

        st.download_button(
            "⬇️ Descargar Excel (Resumen + Detalle)",
            data=output.getvalue(),
            file_name=f"reloj_{maquina_nombre.replace(' ', '_')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
