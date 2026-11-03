from io import BytesIO

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

import contextily as ctx
import rasterio


GREEN = "#33503F"
CHARCOAL = "#1A1A1A"
BONE = "#F5F3EF"
GRAY = "#B9B7B0"

# Color de las alertas/focos
ALERT = "#19D3E6"


# ---------------------------------------------------------
# PALETAS AGIS
# ---------------------------------------------------------

AGIS_CMAP = LinearSegmentedColormap.from_list(
    "agis",
    [BONE, "#C9D4CD", "#7F9B8B", GREEN],
    N=256
)

# NDRE: se mantiene como capa de información óptica.
INDEX_CMAP = LinearSegmentedColormap.from_list(
    "index_agis",
    [
        "#D7191C",
        "#F46D43",
        "#FDAE61",
        "#FFFFBF",
        "#A6D96A",
        "#1A9850"
    ],
    N=256
)

# NDMI: escala diferenciada de humedad relativa.
# Marrón → amarillo pálido → azul.
NDMI_CMAP = LinearSegmentedColormap.from_list(
    "ndmi_agis",
    [
        "#8C5A3C",
        "#D9B66F",
        "#F7E8B0",
        "#B9D9E8",
        "#4F9FC2",
        "#155D7A"
    ],
    N=256
)

# SAR: capa base. Se busca que sea visualmente estable y no compita
# con el NDRE cuando ambas capas están disponibles.
SAR_CMAP = LinearSegmentedColormap.from_list(
    "sar_agis",
    [
        "#111111",
        "#444444",
        "#777777",
        "#AAAAAA",
        "#D6D6D6",
        "#F2F2F2"
    ],
    N=256
)


# ---------------------------------------------------------
# GUARDAR FIGURA
# ---------------------------------------------------------

def _save(fig):

    buf = BytesIO()

    fig.savefig(
        buf,
        format="png",
        dpi=170,
        bbox_inches="tight",
        facecolor="white"
    )

    plt.close(fig)
    buf.seek(0)

    return buf


# ---------------------------------------------------------
# ESTILO DE PRIORIDADES
# ---------------------------------------------------------

def _priority_style(priority):

    if priority == "PRIORIDAD ALTA":
        return {
            "facecolor": GREEN,
            "edgecolor": GREEN,
            "alpha": 0.30
        }

    if priority == "PRIORIDAD MEDIA":
        return {
            "facecolor": CHARCOAL,
            "edgecolor": CHARCOAL,
            "alpha": 0.25
        }

    return {
        "facecolor": BONE,
        "edgecolor": GRAY,
        "alpha": 0.22
    }


# ---------------------------------------------------------
# LÍMITES VISUALES
# ---------------------------------------------------------

def _visual_limits(data):

    valid = data[np.isfinite(data) & (data > -9998)]

    if valid.size == 0:
        return None, None

    vmin, vmax = np.nanpercentile(
        valid,
        [2, 98]
    )

    if vmin == vmax:
        vmin = np.nanmin(valid)
        vmax = np.nanmax(valid)

    if vmin == vmax:
        vmax = vmin + 0.001

    return vmin, vmax


# ---------------------------------------------------------
# MAPA BASE SATELITAL
# ---------------------------------------------------------

def _add_satellite(ax, crs):

    try:
        ctx.add_basemap(
            ax,
            source=ctx.providers.Esri.WorldImagery,
            crs=crs,
            attribution=False
        )
        return True

    except Exception:
        return False


# ---------------------------------------------------------
# MAPA GENERAL DE PRIORIDADES
# ---------------------------------------------------------

def general_priority_map(gdf):

    fig, ax = plt.subplots(
        figsize=(9, 7)
    )

    if "tipo_geometria" in gdf.columns:

        lots = gdf[
            gdf["tipo_geometria"].astype(str) == "LOTE"
        ].copy()

        foci = gdf[
            gdf["tipo_geometria"].astype(str) != "LOTE"
        ].copy()

    else:

        lots = gdf.copy()
        foci = gdf.iloc[0:0].copy()

    if lots.empty:

        ax.set_axis_off()

        return _save(fig)

    v = lots.to_crs(epsg=3857)

    minx, miny, maxx, maxy = v.total_bounds

    width = maxx - minx
    height = maxy - miny

    margin_x = width * 0.08
    margin_y = height * 0.08

    if margin_x == 0:
        margin_x = 100

    if margin_y == 0:
        margin_y = 100

    ax.set_xlim(
        minx - margin_x,
        maxx + margin_x
    )

    ax.set_ylim(
        miny - margin_y,
        maxy + margin_y
    )

    _add_satellite(
        ax,
        v.crs
    )

    PRIORITY_COLORS = {
        "SEGUIMIENTO": "#00FF66",
        "PRIORIDAD MEDIA": "#FFF000",
        "PRIORIDAD ALTA": "#FF1744"
    }

    if "prioridad" in v.columns:

        for pr in [
            "SEGUIMIENTO",
            "PRIORIDAD MEDIA",
            "PRIORIDAD ALTA"
        ]:

            part = v[
                v["prioridad"] == pr
            ]

            if part.empty:
                continue

            part.plot(
                ax=ax,
                facecolor=PRIORITY_COLORS[pr],
                edgecolor=PRIORITY_COLORS[pr],
                linewidth=2.0,
                alpha=0.92
            )

    ax.set_axis_off()

    ax.set_title(
        "Dónde prestar atención",
        loc="left",
        fontsize=16,
        fontweight="bold",
        color=CHARCOAL
    )

    return _save(fig)


# ---------------------------------------------------------
# MAPA RASTER COMPUESTO
#
# TIFF PRODUCTIVO:
#   Band 1 = SAR_VV
#   Band 2 = NDRE
#
# El SAR funciona como capa base y el NDRE se superpone
# únicamente donde existe información óptica válida.
# ---------------------------------------------------------

def raster_map(
    raster,
    band,
    gdf=None,
    title=""
):
    """Renderiza una banda individual del TIFF AGIS.

    Contrato actual del TIFF:
      Band 1 = SAR_VV
      Band 2 = NDRE
      Band 3 = NDMI

    Para el estado general se utilizan Band 2 y Band 3 como evidencia
    óptica visual, sin convertirlas directamente en diagnósticos.
    """

    # Vista directa de la banda; se evita convertir el raster completo
    # a float64. La máscara NoData se aplica sin modificar el original.
    data = raster["data"][band - 1]

    bounds = raster["bounds"]
    crs = raster["crs"]

    max_size = 1800
    height, width = data.shape
    factor = max(
        1,
        int(max(height, width) / max_size)
    )

    if factor > 1:
        data = data[::factor, ::factor]

    vmin, vmax = _visual_limits(data)

    fig, ax = plt.subplots(figsize=(9, 7))

    ax.set_xlim(bounds.left, bounds.right)
    ax.set_ylim(bounds.bottom, bounds.top)

    _add_satellite(ax, crs)

    masked = np.ma.masked_where(
        (~np.isfinite(data)) | (data <= -9998),
        data
    )

    # Band 3 = NDMI según el contrato actual del TIFF.
    # Se diferencia visualmente del NDRE (Band 2).
    cmap = NDMI_CMAP if band == 3 else INDEX_CMAP

    ax.imshow(
        masked,
        cmap=cmap,
        interpolation="nearest",
        extent=[
            bounds.left,
            bounds.right,
            bounds.bottom,
            bounds.top
        ],
        origin="upper",
        vmin=vmin,
        vmax=vmax,
        alpha=0.68
    )

    if gdf is not None and not gdf.empty:
        if gdf.crs != crs:
            v = gdf.to_crs(crs)
        else:
            v = gdf.copy()

        if "tipo_geometria" in v.columns:
            v = v[v["tipo_geometria"].astype(str) == "LOTE"]

        if not v.empty:
            v.boundary.plot(
                ax=ax,
                color="white",
                linewidth=0.65,
                alpha=0.92
            )

    ax.set_axis_off()
    ax.set_title(
        title,
        loc="left",
        fontsize=15,
        fontweight="bold",
        color=CHARCOAL
    )

    return _save(fig)


def record_map(raster, gdf, record_id):

    from rasterio.features import geometry_mask
    from rasterio.windows import Window, from_bounds

    if "id_unico" not in gdf.columns:
        return None

    # -----------------------------------------------------
    # BUSCAR EL LOTE
    # -----------------------------------------------------

    sub = gdf[
        gdf["id_unico"].astype(str).str.strip().str.lstrip("0")
        == str(record_id).strip().lstrip("0")
    ].copy()

    if sub.empty:
        return None

    # -----------------------------------------------------
    # SEPARAR LOTE Y ALERTAS
    # -----------------------------------------------------

    if "tipo_geometria" in sub.columns:

        lots = sub[
            sub["tipo_geometria"].astype(str) == "LOTE"
        ].copy()

        foci = sub[
            sub["tipo_geometria"].astype(str) != "LOTE"
        ].copy()

    else:

        lots = sub
        foci = sub.iloc[0:0].copy()

    if lots.empty:
        return None

    # -----------------------------------------------------
    # CRS
    # -----------------------------------------------------

    crs = raster["crs"]

    if lots.crs != crs:
        lots_plot = lots.to_crs(crs)
    else:
        lots_plot = lots.copy()

    if not foci.empty:

        if foci.crs != crs:
            foci_plot = foci.to_crs(crs)
        else:
            foci_plot = foci.copy()

    else:
        foci_plot = foci

    # -----------------------------------------------------
    # RASTER PRODUCTIVO
    # -----------------------------------------------------

    raster_data = raster["data"]

    if raster_data.shape[0] < 2:
        return _record_map_without_raster(
            lots_plot,
            foci_plot,
            crs,
            "Información raster incompleta"
        )

    # Las bandas se mantienen como vistas del array original.
    # No convertir aquí el raster completo a float64: con un TIFF
    # productivo de 3 bandas eso genera copias de cientos de MB.
    sar_full = raster_data[0]
    ndre_full = raster_data[1]

    transform = raster["transform"]

    raster_height, raster_width = sar_full.shape

    # -----------------------------------------------------
    # EXTENSIÓN DEL LOTE
    # -----------------------------------------------------

    minx, miny, maxx, maxy = lots_plot.total_bounds

    width_lot = maxx - minx
    height_lot = maxy - miny

    margin_x = width_lot * 0.12
    margin_y = height_lot * 0.12

    if margin_x <= 0:
        margin_x = 0.0005

    if margin_y <= 0:
        margin_y = 0.0005

    # -----------------------------------------------------
    # VENTANA DEL RASTER
    # -----------------------------------------------------

    try:

        window = from_bounds(
            minx,
            miny,
            maxx,
            maxy,
            transform=transform
        )

        window = window.round_offsets().round_lengths()

    except Exception:

        return _record_map_without_raster(
            lots_plot,
            foci_plot,
            crs,
            "Información raster no disponible"
        )

    # Intersectar la ventana original con el raster. El extremo se
    # calcula antes de limitar el inicio para no desplazar el recorte.
    raw_col_start = int(window.col_off)
    raw_row_start = int(window.row_off)
    raw_col_end = raw_col_start + int(window.width)
    raw_row_end = raw_row_start + int(window.height)

    col_start = max(0, raw_col_start)
    row_start = max(0, raw_row_start)
    col_end = min(raster_width, raw_col_end)
    row_end = min(raster_height, raw_row_end)

    if col_end <= col_start or row_end <= row_start:

        return _record_map_without_raster(
            lots_plot,
            foci_plot,
            crs,
            "Información raster no disponible"
        )

    # -----------------------------------------------------
    # RECORTE DE AMBAS BANDAS
    # -----------------------------------------------------

    sar = sar_full[
        row_start:row_end,
        col_start:col_end
    ].copy()

    ndre = ndre_full[
        row_start:row_end,
        col_start:col_end
    ].copy()

    if sar.size == 0 or ndre.size == 0:

        return _record_map_without_raster(
            lots_plot,
            foci_plot,
            crs,
            "Información raster no disponible"
        )

    crop_window = Window(
        col_start,
        row_start,
        col_end - col_start,
        row_end - row_start
    )

    crop_transform = rasterio.windows.transform(
        crop_window,
        transform
    )

    # -----------------------------------------------------
    # MÁSCARA REAL DEL LOTE
    # -----------------------------------------------------

    geometries = [
        geom.__geo_interface__
        for geom in lots_plot.geometry
        if geom is not None and not geom.is_empty
    ]

    if not geometries:

        return _record_map_without_raster(
            lots_plot,
            foci_plot,
            crs,
            "Información raster no disponible"
        )

    try:

        mask = geometry_mask(
            geometries,
            out_shape=sar.shape,
            transform=crop_transform,
            invert=True
        )

        sar[~mask] = np.nan
        ndre[~mask] = np.nan

    except Exception:

        return _record_map_without_raster(
            lots_plot,
            foci_plot,
            crs,
            "Información raster no disponible"
        )

    # -----------------------------------------------------
    # REDUCCIÓN PARA EL PDF
    # -----------------------------------------------------

    max_size = 1400

    height, width = sar.shape

    factor = max(
        1,
        int(max(height, width) / max_size)
    )

    if factor > 1:
        sar = sar[::factor, ::factor]
        ndre = ndre[::factor, ::factor]

    # -----------------------------------------------------
    # EXTENSIÓN ESPACIAL DEL RECORTE
    # -----------------------------------------------------

    left = crop_transform.c
    top = crop_transform.f

    right = (
        left
        + crop_transform.a * sar.shape[1] * factor
    )

    bottom = (
        top
        + crop_transform.e * sar.shape[0] * factor
    )

    extent = [
        min(left, right),
        max(left, right),
        min(bottom, top),
        max(bottom, top)
    ]

    # -----------------------------------------------------
    # CONTRASTE
    # -----------------------------------------------------

    sar_vmin, sar_vmax = _visual_limits(sar)
    ndre_vmin, ndre_vmax = _visual_limits(ndre)

    # -----------------------------------------------------
    # FIGURA
    # -----------------------------------------------------

    fig, ax = plt.subplots(
        figsize=(10, 7.2)
    )

    ax.set_xlim(
        minx - margin_x,
        maxx + margin_x
    )

    ax.set_ylim(
        miny - margin_y,
        maxy + margin_y
    )

    # -----------------------------------------------------
    # FONDO SATELITAL
    # -----------------------------------------------------

    # -----------------------------------------------------
    # FONDO SATELITAL
    # -----------------------------------------------------
    # En los mapas individuales se solicita un nivel de zoom
    # ligeramente menor para evitar tiles sin cobertura de
    # World Imagery en escalas demasiado detalladas.
    #
    # NO se modifica:
    #   - raster
    #   - SAR
    #   - NDRE
    #   - geometría
    #   - prioridades
    #   - extensión del lote
    #
    # El cambio afecta únicamente a este mapa individual.
    # -----------------------------------------------------

    try:
        ctx.add_basemap(
            ax,
            source=ctx.providers.Esri.WorldImagery,
            crs=crs,
            attribution=False,
            zoom_adjust=-1
        )
    except Exception:
        # Se mantiene el comportamiento original:
        # si el proveedor no puede cargar el fondo, el mapa
        # continúa mostrando las capas AGIS disponibles.
        pass

    # -----------------------------------------------------
    # SAR BASE
    # -----------------------------------------------------

    if np.any(np.isfinite(sar)):

        ax.imshow(
            np.ma.masked_invalid(sar),
            cmap=SAR_CMAP,
            interpolation="nearest",
            extent=extent,
            origin="upper",
            vmin=sar_vmin,
            vmax=sar_vmax,
            alpha=0.62
        )

    # -----------------------------------------------------
    # NDRE SOBRE SAR
    # -----------------------------------------------------

    if np.any(np.isfinite(ndre)):

        ax.imshow(
            np.ma.masked_invalid(ndre),
            cmap=INDEX_CMAP,
            interpolation="nearest",
            extent=extent,
            origin="upper",
            vmin=ndre_vmin,
            vmax=ndre_vmax,
            alpha=0.68
        )

    # -----------------------------------------------------
    # CONTORNO DEL LOTE
    # -----------------------------------------------------

    lots_plot.boundary.plot(
        ax=ax,
        color="white",
        linewidth=2.4,
        alpha=1.0
    )

    lots_plot.boundary.plot(
        ax=ax,
        color=CHARCOAL,
        linewidth=0.9,
        alpha=1.0
    )

    # -----------------------------------------------------
    # ALERTAS
    # -----------------------------------------------------

    if not foci_plot.empty:

        foci_plot.plot(
            ax=ax,
            facecolor=ALERT,
            edgecolor=ALERT,
            linewidth=1.2,
            alpha=0.25
        )

        foci_plot.boundary.plot(
            ax=ax,
            color=ALERT,
            linewidth=2.8,
            alpha=1.0
        )

    # -----------------------------------------------------
    # ENCUADRE FINAL
    # -----------------------------------------------------

    ax.set_xlim(
        minx - margin_x,
        maxx + margin_x
    )

    ax.set_ylim(
        miny - margin_y,
        maxy + margin_y
    )

    ax.set_axis_off()

    return _save(fig)

# ---------------------------------------------------------
# MAPA SAR EXCLUSIVO PARA FICHAS DE MONITOREO POR RADAR
#
# Se mantiene separado de record_map para que una ficha SAR
# nunca dependa de la presencia de NDRE para poder mostrar
# su mapa. Band 1 = SAR_VV.
# ---------------------------------------------------------

def radar_record_map(raster, gdf, record_id):

    from rasterio.features import geometry_mask
    from rasterio.windows import Window, from_bounds

    if "id_unico" not in gdf.columns:
        return None

    target = str(record_id).strip().lstrip("0") or "0"
    sub = gdf[
        gdf["id_unico"].astype(str).str.strip().str.lstrip("0").replace("", "0") == target
    ].copy()

    if sub.empty:
        return None

    if "tipo_geometria" in sub.columns:
        lots = sub[sub["tipo_geometria"].astype(str) == "LOTE"].copy()
        foci = sub[sub["tipo_geometria"].astype(str) != "LOTE"].copy()
    else:
        lots = sub.copy()
        foci = sub.iloc[0:0].copy()

    if lots.empty:
        return None

    crs = raster["crs"]
    lots_plot = lots.to_crs(crs) if lots.crs != crs else lots.copy()
    foci_plot = foci.to_crs(crs) if (not foci.empty and foci.crs != crs) else foci.copy()

    data = raster["data"]
    if data.ndim != 3 or data.shape[0] < 1:
        return None

    # Vista de la banda SAR; la conversión a float32 se hace solamente
    # sobre la ventana del lote, no sobre todo el raster.
    sar_full = data[0]
    transform = raster["transform"]
    height, width = sar_full.shape

    minx, miny, maxx, maxy = lots_plot.total_bounds
    margin_x = max((maxx - minx) * 0.12, 0.0005)
    margin_y = max((maxy - miny) * 0.12, 0.0005)

    try:
        window = from_bounds(minx, miny, maxx, maxy, transform=transform)
        window = window.round_offsets().round_lengths()
    except Exception:
        return None

    raw_col_start = int(window.col_off)
    raw_row_start = int(window.row_off)
    raw_col_end = raw_col_start + int(window.width)
    raw_row_end = raw_row_start + int(window.height)

    col_start = max(0, raw_col_start)
    row_start = max(0, raw_row_start)
    col_end = min(width, raw_col_end)
    row_end = min(height, raw_row_end)

    if col_end <= col_start or row_end <= row_start:
        return None

    sar = sar_full[row_start:row_end, col_start:col_end].astype(np.float32, copy=True)
    sar[sar <= -9998] = np.nan
    crop_window = Window(col_start, row_start, col_end - col_start, row_end - row_start)
    crop_transform = rasterio.windows.transform(crop_window, transform)

    geometries = [
        geom.__geo_interface__
        for geom in lots_plot.geometry
        if geom is not None and not geom.is_empty
    ]
    if not geometries:
        return None

    try:
        mask = geometry_mask(
            geometries,
            out_shape=sar.shape,
            transform=crop_transform,
            invert=True
        )
        sar[~mask] = np.nan
    except Exception:
        return None

    max_size = 1400
    h, w = sar.shape
    factor = max(1, int(max(h, w) / max_size))
    if factor > 1:
        sar = sar[::factor, ::factor]

    left = crop_transform.c
    top = crop_transform.f
    right = left + crop_transform.a * sar.shape[1] * factor
    bottom = top + crop_transform.e * sar.shape[0] * factor
    extent = [min(left, right), max(left, right), min(bottom, top), max(bottom, top)]

    vmin, vmax = _visual_limits(sar)
    if vmin is None or vmax is None:
        return None

    fig, ax = plt.subplots(figsize=(10, 7.2))
    ax.set_xlim(minx - margin_x, maxx + margin_x)
    ax.set_ylim(miny - margin_y, maxy + margin_y)

    _add_satellite(ax, crs)

    ax.imshow(
        np.ma.masked_invalid(sar),
        cmap=SAR_CMAP,
        interpolation="nearest",
        extent=extent,
        origin="upper",
        vmin=vmin,
        vmax=vmax,
        alpha=0.78
    )

    lots_plot.boundary.plot(ax=ax, color="white", linewidth=2.4, alpha=1.0)
    lots_plot.boundary.plot(ax=ax, color=CHARCOAL, linewidth=0.9, alpha=1.0)

    if not foci_plot.empty:
        foci_plot.plot(ax=ax, facecolor=ALERT, edgecolor=ALERT, linewidth=1.2, alpha=0.25)
        foci_plot.boundary.plot(ax=ax, color=ALERT, linewidth=2.8, alpha=1.0)

    ax.set_axis_off()
    return _save(fig)
