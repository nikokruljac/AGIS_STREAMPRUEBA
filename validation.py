import pandas as pd

REQUIRED_COLUMNS = [
    "id_unico", "lote", "establecimiento", "cultivo", "campania",
    "periodo_inicio", "periodo_fin", "ultima_pasada_S2", "ultima_pasada_S1",
    "prioridad", "fundamento_prioridad", "tipo_interpretacion",
    "nivel_interpretacion", "hallazgo_agis", "hipotesis_agis", "que_revisar",
    "hipotesis_alternativas", "fundamento_interpretacion", "limitaciones",
    "ndmi", "ndre", "senal_relativa_NDMI", "senal_relativa_NDRE",
    "convergencia", "lineas_evidencia_utilizables", "SAR_disponible",
    "observaciones_referencia_NDMI", "observaciones_referencia_NDRE",
    "minimo_observaciones_referencia", "fecha_exportacion"
]
VALID_PRIORITIES = {"PRIORIDAD ALTA", "PRIORIDAD MEDIA", "SEGUIMIENTO"}


def _normalized_ids(values):
    return values.astype(str).str.strip()


def validate_csv(df):
    errors = []
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        errors.append("Faltan columnas del contrato AGIS: " + ", ".join(missing))
        return errors
    if df.empty:
        errors.append("El CSV no contiene registros.")
        return errors

    ids = _normalized_ids(df["id_unico"])
    if ids.isna().any() or ids.eq("").any() or ids.str.lower().eq("nan").any():
        errors.append("Hay registros sin id_unico.")
    if ids.duplicated().any():
        examples = ids[ids.duplicated(keep=False)].unique()[:8].tolist()
        errors.append("Hay id_unico duplicados: " + ", ".join(examples))

    for field in ("lote", "establecimiento", "prioridad"):
        vals = df[field].fillna("").astype(str).str.strip()
        if vals.eq("").any():
            errors.append(f"Hay registros sin el campo {field}.")

    priorities = set(df["prioridad"].dropna().astype(str).str.strip().unique())
    unknown = sorted(priorities - VALID_PRIORITIES)
    if unknown:
        errors.append("Hay prioridades no reconocidas: " + ", ".join(unknown))

    for field in ("periodo_inicio", "periodo_fin", "fecha_exportacion"):
        parsed = pd.to_datetime(df[field], errors="coerce")
        invalid = df[field].notna() & parsed.isna()
        if invalid.any():
            errors.append(f"Hay fechas inválidas en {field}.")

    return errors


def validate_geojson_ids(df, gdf):
    errors = []
    csv_ids = set(_normalized_ids(df["id_unico"]))
    geo_ids = set(_normalized_ids(gdf["id_unico"]))
    only_csv = sorted(csv_ids - geo_ids)
    only_geo = sorted(geo_ids - csv_ids)
    if only_csv:
        errors.append(
            f"Hay {len(only_csv)} id_unico del CSV que no aparecen en GeoJSON "
            f"(ej.: {', '.join(only_csv[:8])})."
        )
    if only_geo:
        errors.append(
            f"Hay {len(only_geo)} id_unico del GeoJSON que no aparecen en CSV "
            f"(ej.: {', '.join(only_geo[:8])})."
        )
    return errors


def validate_raster_contract(raster):
    errors = []
    data = raster.get("data")
    if data is None or getattr(data, "ndim", 0) != 3:
        return ["El TIFF no tiene una estructura de bandas válida."]
    if data.shape[0] not in (2, 3):
        errors.append(f"El TIFF debe tener 2 o 3 bandas; tiene {data.shape[0]}.")
    if not data.shape[1] or not data.shape[2]:
        errors.append("El TIFF no contiene píxeles.")
    if raster.get("crs") is None:
        errors.append("El TIFF no declara CRS.")
    if data.size and not pd.notna(data).any():
        errors.append("El TIFF no contiene valores numéricos válidos.")
    return errors


def summary(df):
    counts = df["prioridad"].fillna("").astype(str).str.strip().value_counts()
    return {
        "total": len(df),
        "alta": int(counts.get("PRIORIDAD ALTA", 0)),
        "media": int(counts.get("PRIORIDAD MEDIA", 0)),
        "seguimiento": int(counts.get("SEGUIMIENTO", 0)),
        "sin_clasificar": int(len(df) - sum(
            counts.get(k, 0) for k in VALID_PRIORITIES
        )),
    }
