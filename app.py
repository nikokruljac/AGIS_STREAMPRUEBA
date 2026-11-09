
import re
import streamlit as st
from datetime import datetime

from modules.readers import read_csv, read_geojson, read_raster
from modules.validation import (
    validate_csv, validate_geojson_ids, validate_raster_contract, summary
)
from modules.pdf_generator import build_pdf

st.set_page_config(page_title="AGIS · Informe de monitoreo", page_icon="🌱", layout="wide")

GREEN = "#33503F"
CHARCOAL = "#1A1A1A"
BONE = "#F5F3EF"


def cliente_para_archivo(cliente):
    cliente = str(cliente).strip().upper()
    cliente = re.sub(r"[^\w\s-]", "", cliente, flags=re.UNICODE)
    cliente = re.sub(r"[\s_]+", "-", cliente)
    cliente = re.sub(r"-+", "-", cliente)
    return cliente.strip("-") or "CLIENTE"


st.markdown(
    f'''
    <style>
    .stApp {{ background: white; }}
    h1, h2, h3 {{ color: {CHARCOAL}; }}
    [data-testid="stSidebar"] {{ background: {BONE}; }}
    .agis-header {{
        border-bottom: 3px solid {GREEN};
        padding-bottom: 12px;
        margin-bottom: 24px;
    }}
    .stButton > button {{
        background: {GREEN};
        color: white;
        border: 0;
        border-radius: 6px;
        font-weight: 600;
    }}
    </style>
    ''',
    unsafe_allow_html=True
)

st.markdown(
    '<div class="agis-header">'
    '<h1>AGIS · Informe de monitoreo</h1>'
    '<p>Transformar evidencia en atención priorizada.</p>'
    '</div>',
    unsafe_allow_html=True
)

with st.sidebar:
    st.markdown("### Archivos")
    csv_file = st.file_uploader("CSV AGIS", type=["csv"])
    geo_file = st.file_uploader("GeoJSON de lotes y focos AGIS", type=["geojson", "json"])
    tif_file = st.file_uploader("TIFF SAR + NDRE + NDMI", type=["tif", "tiff"])

if not all([csv_file, geo_file, tif_file]):
    st.info("Cargá CSV + GeoJSON + TIFF para comenzar.")
    st.stop()

try:
    with st.spinner("Leyendo y validando archivos..."):
        df = read_csv(csv_file)
        csv_errors = validate_csv(df)
        if csv_errors:
            for error in csv_errors:
                st.error(error)
            st.stop()

        gdf = read_geojson(geo_file)
        raster = read_raster(tif_file)

        consistency_errors = validate_geojson_ids(df, gdf)
        raster_errors = validate_raster_contract(raster)
        if consistency_errors or raster_errors:
            for error in consistency_errors + raster_errors:
                st.error(error)
            st.stop()

        gdf_raster_crs = gdf.to_crs(raster["crs"])
        rb = raster["bounds"]
        from shapely.geometry import box
        raster_box = box(rb.left, rb.bottom, rb.right, rb.top)
        spatial_hits = int(gdf_raster_crs.geometry.intersects(raster_box).sum())

        if spatial_hits == 0:
            st.error("El GeoJSON y el TIFF no se superponen espacialmente. Revisá que pertenezcan al mismo establecimiento y ejecución.")
            st.stop()

        if spatial_hits < len(gdf_raster_crs):
            st.warning(
                f"El raster intersecta {spatial_hits} de {len(gdf_raster_crs)} geometrías. "
                "Algunos lotes podrían no tener mapa raster."
            )

    s = summary(df)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Lotes", s["total"])
    c2.metric("Prioridad alta", s["alta"])
    c3.metric("Prioridad media", s["media"])
    c4.metric("Seguimiento", s["seguimiento"])

    if s["sin_clasificar"]:
        st.warning(f"Hay {s['sin_clasificar']} registros sin prioridad reconocida.")

    st.success(
        f"Archivos validados: {len(df)} registros CSV, "
        f"{len(gdf)} geometrías y {raster['data'].shape[0]} bandas raster."
    )

    st.markdown("### Vista previa")
    preview_cols = [
        c for c in [
            "id_unico", "lote", "cultivo", "prioridad",
            "ndre", "ndmi", "convergencia"
        ] if c in df.columns
    ]
    st.dataframe(
        df[preview_cols].head(20),
        use_container_width=True,
        hide_index=True
    )

    if st.button("GENERAR PDF AGIS", type="primary"):
        try:
            with st.spinner("Generando informe..."):
                pdf = build_pdf(df, gdf, raster, None)

            cliente = (
                df["cliente"].dropna().astype(str).iloc[0]
                if "cliente" in df.columns and not df["cliente"].dropna().empty
                else "CLIENTE"
            )

            fecha_hora = datetime.now().strftime("%Y-%m-%d_%H-%M")
            nombre_pdf = (
                f"AGIS_INFORME_MONITOREO_"
                f"{cliente_para_archivo(cliente)}_"
                f"{fecha_hora}.pdf"
            )

            st.success("Informe generado.")

            st.download_button(
                "DESCARGAR PDF",
                data=pdf.getvalue(),
                file_name=nombre_pdf,
                mime="application/pdf"
            )

        except Exception as exc:
            st.error(
                f"No se pudo generar el PDF: "
                f"{type(exc).__name__}: {exc}"
            )

except Exception as exc:
    st.error(
        f"No se pudo procesar el conjunto de archivos: "
        f"{type(exc).__name__}: {exc}"
    )
