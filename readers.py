import io
import pandas as pd
import geopandas as gpd
import rasterio
import numpy as np


def read_csv(uploaded_file):
    uploaded_file.seek(0)
    try:
        df = pd.read_csv(uploaded_file)
    except UnicodeDecodeError:
        uploaded_file.seek(0)
        df = pd.read_csv(uploaded_file, encoding="latin-1")
    finally:
        uploaded_file.seek(0)

    if df.empty:
        raise ValueError("El CSV no contiene registros.")
    if df.columns.duplicated().any():
        duplicated = df.columns[df.columns.duplicated()].tolist()
        raise ValueError("El CSV contiene columnas duplicadas: " + ", ".join(duplicated))
    return df


def read_geojson(uploaded_file):
    data = uploaded_file.read()
    uploaded_file.seek(0)
    try:
        gdf = gpd.read_file(io.BytesIO(data))
    except Exception as exc:
        raise ValueError(f"No se pudo leer el GeoJSON: {exc}") from exc

    if gdf.empty:
        raise ValueError("El GeoJSON no contiene geometrías.")
    # GeoJSON (RFC 7946) usa WGS84 si no declara CRS.
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    if gdf.geometry.isna().any() or gdf.geometry.is_empty.any():
        raise ValueError("El GeoJSON contiene geometrías nulas o vacías.")
    invalid = ~gdf.geometry.is_valid
    if invalid.any():
        raise ValueError(f"El GeoJSON contiene {int(invalid.sum())} geometrías inválidas.")
    if "id_unico" not in gdf.columns:
        raise ValueError("El GeoJSON no contiene el campo obligatorio id_unico.")
    return gdf


def read_raster(uploaded_file):
    data = uploaded_file.read()
    uploaded_file.seek(0)
    try:
        with rasterio.io.MemoryFile(data).open() as src:
            if src.count not in (2, 3):
                raise ValueError(
                    f"El TIFF debe tener 2 o 3 bandas; se encontraron {src.count}."
                )
            if src.crs is None:
                raise ValueError("El TIFF no declara un CRS.")
            if src.width <= 0 or src.height <= 0:
                raise ValueError("El TIFF no contiene dimensiones válidas.")
            arr = src.read(out_dtype="float32")
            transform, crs, bounds = src.transform, src.crs, src.bounds
            nodata, descriptions = src.nodata, src.descriptions
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"No se pudo leer el TIFF: {exc}") from exc

    if arr.ndim != 3 or arr.shape[0] != len(descriptions) and any(descriptions):
        raise ValueError("La estructura interna del TIFF no es consistente.")
    if arr.shape[1] == 0 or arr.shape[2] == 0:
        raise ValueError("El TIFF no contiene píxeles.")

    return {
        "data": arr,
        "transform": transform,
        "crs": crs,
        "bounds": bounds,
        "nodata": nodata if nodata is not None else -9999,
        "descriptions": descriptions,
    }
