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


def _add_continuous_legend(fig, ax, cmap, vmin, vmax, label, unit=""):
    """Agrega leyendas independientes en bandas reservadas, sin superposición."""
    if vmin is None or vmax is None:
        return
    import matplotlib as mpl
    norm = mpl.colors.Normalize(vmin=float(vmin), vmax=float(vmax))
    scalar = mpl.cm.ScalarMappable(norm=norm, cmap=cmap)
    scalar.set_array([])

    # Las dos escalas se dibujan en ejes propios. El rótulo va arriba
    # de cada barra y los valores abajo, evitando que NDRE y SAR se pisen.
    label_upper = str(label).strip().upper()
    if label_upper.startswith("NDRE"):
        cax = fig.add_axes([0.12, 0.175, 0.76, 0.022])
    else:  # SAR VV
        cax = fig.add_axes([0.12, 0.075, 0.76, 0.022])

    cbar = fig.colorbar(scalar, cax=cax, orientation="horizontal")
    cbar.set_label(label + (f" ({unit})" if unit else ""), fontsize=6.5, labelpad=2)
    cbar.ax.xaxis.set_label_position("top")
    cbar.ax.tick_params(labelsize=6, length=1.5, pad=1)
    cbar.outline.set_linewidth(0.5)


def _basemap_looks_like_error(ax, previous_count):
    """Detecta mosaicos grises de error que algunos servidores devuelven sin excepción."""
    artists = ax.images[previous_count:]
    for artist in artists:
        try:
            arr = np.asarray(artist.get_array())
            if arr.ndim != 3 or arr.shape[-1] < 3:
                continue
            sample = arr[::max(1, arr.shape[0] // 100), ::max(1, arr.shape[1] // 100), :3].astype(float)
            if sample.max() > 1:
                sample /= 255.0
            mx = sample.max(axis=2)
            mn = sample.min(axis=2)
            saturation = np.mean((mx - mn) / np.maximum(mx, 1e-6))
            luminance = float(np.mean(sample))
            # Los tiles de error de Esri observados son casi uniformemente grises,
            # con texto blanco superpuesto. Evita confundirlos con imagen satelital.
            if saturation < 0.035 and 0.58 < luminance < 0.90:
                artist.remove()
                return True
        except Exception:
            continue
    return False


def _add_satellite_with_retry(ax, crs):
    """Carga Esri World Imagery y descarta también mosaicos de error sin excepción."""
    for adjust in (-1, -2, -3):
        before = len(ax.images)
        try:
            ctx.add_basemap(
                ax, source=ctx.providers.Esri.WorldImagery,
                crs=crs, attribution=False, zoom_adjust=adjust
            )
            if _basemap_looks_like_error(ax, before):
                continue
            return True
        except Exception:
            # El proveedor puede dejar artistas parciales antes de fallar.
            for artist in ax.images[before:]:
                try:
                    artist.remove()
                except Exception:
                    pass
    ax.set_facecolor("#E8E8E5")
    return False


def _spatial_lot_sectors(gdf, max_sectors=4):
    """Agrupa lotes cercanos en sectores sin alterar sus posiciones geográficas."""
    lots = gdf.copy()
    if "tipo_geometria" in lots.columns:
        lots = lots[lots["tipo_geometria"].astype(str).str.upper() == "LOTE"].copy()
    lots = lots[lots.geometry.notna() & ~lots.geometry.is_empty]
    if lots.empty:
        return []
    projected = lots.to_crs(epsg=3857)
    centroids = projected.geometry.centroid
    xy = np.column_stack([centroids.x.to_numpy(), centroids.y.to_numpy()])
    if len(xy) == 1:
        return [lots]
    distances = np.sqrt(((xy[:, None, :] - xy[None, :, :]) ** 2).sum(axis=2))
    np.fill_diagonal(distances, np.inf)
    nearest = np.min(distances, axis=1)
    threshold = float(np.clip(np.median(nearest) * 2.5, 1200, 5000))

    # Componentes conexas por proximidad.
    labels = np.arange(len(xy))
    def root(i):
        while labels[i] != i:
            labels[i] = labels[labels[i]]
            i = labels[i]
        return i
    for i in range(len(xy)):
        for j in range(i + 1, len(xy)):
            if distances[i, j] <= threshold:
                ri, rj = root(i), root(j)
                if ri != rj:
                    labels[rj] = ri
    groups = {}
    for i in range(len(xy)):
        groups.setdefault(root(i), []).append(i)
    clusters = [list(v) for v in groups.values()]

    # Limita la cantidad de paneles fusionando siempre los sectores más cercanos.
    while len(clusters) > max_sectors:
        centers = [xy[idx].mean(axis=0) for idx in clusters]
        pair = min(((np.linalg.norm(centers[i] - centers[j]), i, j)
                    for i in range(len(centers)) for j in range(i + 1, len(centers))))
        _, i, j = pair
        clusters[i] = clusters[i] + clusters[j]
        clusters.pop(j)
    clusters.sort(key=lambda idx: (xy[idx].mean(axis=0)[1], xy[idx].mean(axis=0)[0]), reverse=True)
    return [lots.iloc[idx].copy() for idx in clusters]


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

    _add_satellite_with_retry(
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
        fontsize=12,
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
    """Mapa de estado general con sectores ordenados en un bloque compacto."""
    data = raster["data"][band - 1]
    bounds = raster["bounds"]
    crs = raster["crs"]
    max_size = 1800
    height, width = data.shape
    factor = max(1, int(max(height, width) / max_size))
    if factor > 1:
        data = data[::factor, ::factor]
    vmin, vmax = _visual_limits(data)
    cmap = NDMI_CMAP if band == 3 else INDEX_CMAP

    sectors = _spatial_lot_sectors(gdf) if gdf is not None and not gdf.empty else []
    if not sectors:
        sectors = [None]

    # Orden de lectura: izquierda a derecha y de arriba hacia abajo.
    # Con tres sectores, el tercero queda centrado debajo de los dos primeros.
    n = len(sectors)
    fig = plt.figure(figsize=(12, 7.2))
    if n == 1:
        grid = fig.add_gridspec(1, 1, left=0.025, right=0.975,
                                top=0.94, bottom=0.18)
        axes_list = [fig.add_subplot(grid[0, 0])]
    elif n == 2:
        grid = fig.add_gridspec(1, 2, left=0.025, right=0.975,
                                top=0.94, bottom=0.18, wspace=0.035)
        axes_list = [fig.add_subplot(grid[0, 0]), fig.add_subplot(grid[0, 1])]
    else:
        grid = fig.add_gridspec(2, 4, left=0.025, right=0.975,
                                top=0.94, bottom=0.18,
                                wspace=0.035, hspace=0.07)
        if n == 3:
            positions = [(0, slice(0, 2)), (0, slice(2, 4)),
                         (1, slice(1, 3))]
        else:
            positions = [(0, slice(0, 2)), (0, slice(2, 4)),
                         (1, slice(0, 2)), (1, slice(2, 4))]
        axes_list = []
        for idx in range(n):
            row, cols = positions[idx]
            axes_list.append(fig.add_subplot(grid[row, cols]))

    masked = np.ma.masked_where((~np.isfinite(data)) | (data <= -9998), data)
    for idx, ax in enumerate(axes_list):
        sector = sectors[idx]
        if sector is None:
            minx, miny, maxx, maxy = bounds.left, bounds.bottom, bounds.right, bounds.top
            sector_plot = None
        else:
            sector_plot = sector.to_crs(crs) if sector.crs != crs else sector.copy()
            minx, miny, maxx, maxy = sector_plot.total_bounds
        dx, dy = maxx - minx, maxy - miny
        padx = max(dx * 0.08, abs(bounds.right - bounds.left) * 0.001)
        pady = max(dy * 0.08, abs(bounds.top - bounds.bottom) * 0.001)
        ax.set_xlim(minx - padx, maxx + padx)
        ax.set_ylim(miny - pady, maxy + pady)
        _add_satellite_with_retry(ax, crs)
        ax.imshow(masked, cmap=cmap, interpolation="nearest",
                  extent=[bounds.left, bounds.right, bounds.bottom, bounds.top],
                  origin="upper", vmin=vmin, vmax=vmax, alpha=0.68)
        if sector_plot is not None and not sector_plot.empty:
            sector_plot.boundary.plot(ax=ax, color="white", linewidth=0.85, alpha=0.98)
        ax.set_axis_off()
        ax.set_title(f"SECTOR {idx + 1}" if n > 1 else "",
                     loc="left", fontsize=9, fontweight="bold", color=CHARCOAL, pad=2)

    if vmin is not None and vmax is not None:
        import matplotlib as mpl
        norm = mpl.colors.Normalize(vmin=float(vmin), vmax=float(vmax))
        scalar = mpl.cm.ScalarMappable(norm=norm, cmap=cmap)
        scalar.set_array([])
        cax = fig.add_axes([0.22, 0.095, 0.56, 0.022])
        cbar = fig.colorbar(scalar, cax=cax, orientation="horizontal")
        legend_name = "NDMI · menor a mayor valor" if band == 3 else "NDRE · menor a mayor valor"
        cbar.set_label(legend_name, fontsize=6.5, labelpad=2)
        cbar.ax.tick_params(labelsize=6, length=1.5, pad=1)
        cbar.outline.set_linewidth(0.5)
    if title:
        fig.suptitle(title, x=0.03, ha="left", fontsize=11, fontweight="bold", color=CHARCOAL)
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

    _add_satellite_with_retry(ax, crs)

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

    # Leyendas continuas de las dos capas realmente dibujadas.
    # Los rangos son los límites visuales del recorte, no umbrales diagnósticos.
    if sar_vmin is not None and sar_vmax is not None:
        _add_continuous_legend(fig, ax, SAR_CMAP, sar_vmin, sar_vmax, "SAR VV", "dB")
    if ndre_vmin is not None and ndre_vmax is not None:
        _add_continuous_legend(fig, ax, INDEX_CMAP, ndre_vmin, ndre_vmax, "NDRE", "índice")

    ax.set_axis_off()
    fig.subplots_adjust(bottom=0.29, top=0.98, left=0.03, right=0.97)
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

    _add_satellite_with_retry(ax, crs)

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

