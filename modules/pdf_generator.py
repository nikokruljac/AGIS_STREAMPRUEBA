# AGIS PDF GENERATOR — ADAPTATIVO SAR TRIVARIADO V5
# V4 — FICHAS DIFERENCIADAS: lectura óptico-SAR, fechas y verificación de campo por patrón.
# Mantiene cálculos, categorías y lógica de priorización sin cambios.

MIXED_GREEN = "#6F927D"

from io import BytesIO
from pathlib import Path
from datetime import date
import os
import re

import pandas as pd
import matplotlib.pyplot as plt

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Image,
    Table,
    TableStyle,
    PageBreak,
    KeepTogether
)

from .maps import (
    general_priority_map,
    sar_behavior_map,
    SAR_BEHAVIOR_COLORS,
    raster_map,
    record_map,
    radar_record_map,
    GREEN,
    CHARCOAL,
    BONE
)


# ---------------------------------------------------------
# TIPOGRAFÍA
# ---------------------------------------------------------
# Preferimos Arial. En Streamlit Cloud, si Arial no está
# instalada/licenciada en el entorno, usamos Liberation Sans,
# que mantiene una apariencia muy cercana y permite que el
# PDF sea reproducible sin depender de Helvetica.
def _register_agis_fonts():
    candidates = [
        ("Arial", "assets/arial.ttf", "assets/Arial.ttf"),
        ("Arial", "/usr/share/fonts/truetype/msttcorefonts/Arial.ttf"),
        ("Arial", "/usr/share/fonts/truetype/msttcorefonts/arial.ttf"),
        ("Arial", "/mnt/data/Arial.ttf"),
        ("LiberationSans", "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
    ]

    regular = None
    for item in candidates:
        name = item[0]
        paths = item[1:] if len(item) > 2 else (item[1],)
        for path in paths:
            if os.path.exists(path):
                try:
                    pdfmetrics.registerFont(TTFont(name, path))
                    regular = name
                    break
                except Exception:
                    pass
        if regular:
            break

    bold_candidates = [
        ("Arial-Bold", "assets/arialbd.ttf", "assets/Arial-Bold.ttf"),
        ("Arial-Bold", "/usr/share/fonts/truetype/msttcorefonts/Arial_Bold.ttf"),
        ("Arial-Bold", "/usr/share/fonts/truetype/msttcorefonts/arialbd.ttf"),
        ("Arial-Bold", "/mnt/data/Arial-Bold.ttf"),
        ("LiberationSans-Bold", "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"),
    ]

    bold = None
    for item in bold_candidates:
        name = item[0]
        paths = item[1:] if len(item) > 2 else (item[1],)
        for path in paths:
            if os.path.exists(path):
                try:
                    pdfmetrics.registerFont(TTFont(name, path))
                    bold = name
                    break
                except Exception:
                    pass
        if bold:
            break

    if regular is None:
        regular = "Helvetica"
    if bold is None:
        bold = "Helvetica-Bold"

    return regular, bold


FONT_REGULAR, FONT_BOLD = _register_agis_fonts()


class RoundedTable(Table):
    """Table con marco y/o fondo de esquinas redondeadas."""
    def __init__(self, *args, radius=6, panel_fill=None, panel_stroke=None, panel_width=0.7, **kwargs):
        self._radius = radius
        self._panel_fill = panel_fill
        self._panel_stroke = panel_stroke
        self._panel_width = panel_width
        super().__init__(*args, **kwargs)

    def draw(self):
        canvas = self.canv
        canvas.saveState()
        if self._panel_fill is not None:
            canvas.setFillColor(self._panel_fill)
        else:
            canvas.setFillColor(colors.transparent)
        if self._panel_stroke is not None:
            canvas.setStrokeColor(self._panel_stroke)
            canvas.setLineWidth(self._panel_width)
        else:
            canvas.setStrokeColor(colors.transparent)
        canvas.roundRect(0, 0, self._width, self._height, self._radius,
                         stroke=1 if self._panel_stroke is not None else 0,
                         fill=1 if self._panel_fill is not None else 0)
        canvas.restoreState()
        super().draw()


def _fmt(v):
    return "—" if pd.isna(v) else str(v)


def _fmt2(v):
    """Formato compacto para indicadores numéricos: dos decimales."""
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return "—"
        return f"{float(v):.2f}"
    except Exception:
        return _fmt(v)


def _latest_s2_date(df):
    if df.empty or "ultima_pasada_S2" not in df.columns:
        return "—"

    values = pd.to_datetime(
        df["ultima_pasada_S2"],
        errors="coerce"
    ).dropna()

    if values.empty:
        return "—"

    return values.max().strftime("%d/%m/%Y")


def _latest_s1_date(df):
    if df.empty or "ultima_pasada_S1" not in df.columns:
        return "—"

    values = pd.to_datetime(
        df["ultima_pasada_S1"],
        errors="coerce"
    ).dropna()

    if values.empty:
        return "—"

    return values.max().strftime("%d/%m/%Y")


def _priority_donut(high, medium, follow):
    fig, ax = plt.subplots(figsize=(4.6, 3.1))

    values = [high, medium, follow]
    labels = ["Señal relativa convergente", "Señal relativa parcial", "Seguimiento"]

    if sum(values) > 0:
        ax.pie(
            values,
            labels=labels,
            autopct="%1.0f%%",
            startangle=90,
            wedgeprops={"width": 0.38}
        )

    fig.tight_layout()

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


def _stacked_metric_cell(title_text, value_text, note_text=None, value_size=20,
                         title_size=8.8, note_size=7.5, color=CHARCOAL):
    """Celda vertical con separación explícita entre título, valor y nota."""
    items = [
        Paragraph(
            f"<b>{title_text}</b>",
            ParagraphStyle(
                f"MetricTitle_{title_text}",
                fontName=FONT_BOLD,
                fontSize=title_size,
                leading=10.5,
                textColor=colors.HexColor(CHARCOAL),
                spaceAfter=0,
            )
        ),
        Spacer(1, 1.8 * mm),
        Paragraph(
            f"<font size='{value_size}'><b>{value_text}</b></font>",
            ParagraphStyle(
                f"MetricValue_{title_text}",
                fontName=FONT_BOLD,
                fontSize=value_size,
                leading=value_size + 1,
                textColor=colors.HexColor(color),
            )
        )
    ]
    if note_text is not None:
        items.extend([
            Spacer(1, 0.7 * mm),
            Paragraph(
                str(note_text),
                ParagraphStyle(
                    f"MetricNote_{title_text}",
                    fontName=FONT_REGULAR,
                    fontSize=note_size,
                    leading=9,
                    textColor=colors.HexColor(CHARCOAL),
                )
            )
        ])
    return items


def _resolve_logo_bytes(logo_bytes):
    """
    Uses an explicitly supplied logo when available.
    Otherwise, loads the AGIS logo bundled with the Streamlit project.
    Expected location:
        assets/agis_logo.png
    """
    if logo_bytes:
        return logo_bytes

    logo_path = (
        Path(__file__).resolve().parent.parent
        / "assets"
        / "logo_agis.png"
    )

    if logo_path.exists():
        return logo_path.read_bytes()

    return None


def _footer(canvas, doc):
    canvas.saveState()

    canvas.setTitle(
        getattr(
            doc,
            "_agis_pdf_title",
            "AGIS · Informe de monitoreo"
        )
    )
    canvas.setAuthor("AGIS")
    canvas.setFont(
        FONT_REGULAR,
        8
    )

    canvas.setFillColor(
        colors.HexColor(CHARCOAL)
    )

    canvas.drawRightString(
        A4[0] - 17 * mm,
        9 * mm,
        f"AGIS · {doc.page}"
    )

    canvas.restoreState()



def _high_priority_area_ha(gdf):
    """Calcula la superficie de los lotes en prioridad alta."""
    if gdf is None or gdf.empty:
        return 0.0
    if "prioridad" not in gdf.columns:
        return 0.0
    high = gdf[gdf["prioridad"] == "PRIORIDAD ALTA"].copy()
    if "tipo_geometria" in high.columns:
        high = high[high["tipo_geometria"].astype(str) == "LOTE"]
    if high.empty:
        return 0.0
    try:
        area_m2 = high.to_crs(epsg=6933).geometry.area.sum()
        return float(area_m2 / 10000.0)
    except Exception:
        return 0.0


def _is_true(value):
    return str(value).strip().lower() in ("true", "1", "sí", "si", "yes")


def _monitoring_mode(row):
    """
    Modalidad definida por cobertura óptica espacial.
    Prioriza el campo generado por GEE; conserva compatibilidad con CSV antiguos.
    """
    if "modalidad_monitoreo" in row.index and pd.notna(row["modalidad_monitoreo"]):
        mode = str(row["modalidad_monitoreo"]).strip().upper()
        if mode in ("MONITOREO OPTICO", "MONITOREO MIXTO", "MONITOREO POR RADAR SAR"):
            return mode

    return "MONITOREO POR RADAR SAR" if _legacy_radar_only(row) else "MONITOREO OPTICO"


def _legacy_radar_only(row):
    sar_available = _is_true(
        row["SAR_disponible"] if "SAR_disponible" in row.index else False
    )

    if not sar_available:
        return False

    if "lineas_evidencia_utilizables" in row.index:
        try:
            value = row["lineas_evidencia_utilizables"]
            if pd.notna(value):
                return float(value) <= 0
        except Exception:
            pass

    ndre_missing = "ndre" not in row.index or pd.isna(row["ndre"])
    ndmi_missing = "ndmi" not in row.index or pd.isna(row["ndmi"])
    return ndre_missing and ndmi_missing


def _is_radar_only(row):
    """Lote cuya modalidad operativa es exclusivamente SAR."""
    return _monitoring_mode(row) == "MONITOREO POR RADAR SAR"


def _natural_sort_key(value):
    """Clave natural: ordena identificadores alfanuméricos por sus tramos numéricos."""
    if value is None or pd.isna(value):
        value = ""
    parts = re.split(r"(\d+)", str(value).strip().lower())
    return tuple((0, int(part)) if part.isdigit() else (1, part) for part in parts if part != "")


def _sort_lots_naturally(frame):
    """
    Ordena primero por prioridad (si existe), luego por establecimiento
    y finalmente por identificador de lote en orden natural.
    Ejemplo: Cuadro-2, Cuadro-9, Cuadro-10.
    """
    if frame is None or frame.empty:
        return frame

    result = frame.copy()
    sort_columns = []

    # La prioridad debe conservarse como criterio principal.
    if "_orden_prioridad" in result.columns:
        sort_columns.append("_orden_prioridad")

    if "establecimiento" in result.columns:
        result["_orden_establecimiento"] = result["establecimiento"].map(_natural_sort_key)
    else:
        result["_orden_establecimiento"] = [tuple()] * len(result)
    sort_columns.append("_orden_establecimiento")

    if "lote" in result.columns:
        result["_orden_lote"] = result["lote"].map(_natural_sort_key)
    else:
        result["_orden_lote"] = [tuple()] * len(result)
    sort_columns.append("_orden_lote")

    result = result.sort_values(sort_columns, kind="stable")
    return result.drop(
        columns=["_orden_establecimiento", "_orden_lote"],
        errors="ignore"
    )


def _num(value):
    """Convierte un valor numérico del CSV; devuelve None si no es utilizable."""
    try:
        if value is None or pd.isna(value) or str(value).strip() == "":
            return None
        return float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def _sar_direction(delta):
    if delta is None:
        return "sin dato", "#777777", "—"
    if delta > 0:
        return "aumentó", "#2E7D4F", "↑"
    if delta < 0:
        return "disminuyó", "#C43D3D", "↓"
    return "se mantuvo", "#777777", "→"


def _sar_change_interpretation(radar):
    """Interpreta conjuntamente VV, VH y VH−VV sin asignar una causa única."""
    vv = radar.get("delta_vv_num")
    vh = radar.get("delta_vh_num")
    ratio = radar.get("delta_ratio_num")

    if vv is None and vh is None:
        return (
            "No hay una comparación válida de VV y VH con la observación anterior. "
            "Por ahora no es posible describir una tendencia del comportamiento radar."
        )

    if vv is not None and vh is not None:
        if vv > 0 and vh > 0:
            base = (
                "La respuesta radar aumentó en VV y VH. El cambio conjunto puede estar "
                "relacionado con variaciones en la humedad de la superficie o con cambios "
                "en la cobertura y estructura de la vegetación."
            )
        elif vv < 0 and vh < 0:
            base = (
                "La respuesta radar disminuyó en VV y VH. El cambio conjunto puede estar "
                "relacionado con variaciones en las condiciones de la superficie o con "
                "cambios en la cobertura y estructura de la vegetación."
            )
        elif vv == 0 and vh == 0:
            base = (
                "VV y VH se mantienen sin variaciones apreciables respecto de la "
                "observación anterior. La respuesta radar resulta estable en esta comparación."
            )
        else:
            base = (
                "VV y VH evolucionaron en direcciones diferentes. Esto muestra que la "
                "respuesta radar cambió de manera no uniforme y puede estar reflejando "
                "una modificación en la interacción de la señal con la superficie y la vegetación."
            )
    elif vv is not None:
        base = (
            f"La respuesta VV {('aumentó' if vv > 0 else 'disminuyó' if vv < 0 else 'se mantuvo')} "
            "respecto de la observación anterior. Sin una variación VH válida, la lectura "
            "del comportamiento conjunto queda incompleta."
        )
    else:
        base = (
            f"La respuesta VH {('aumentó' if vh > 0 else 'disminuyó' if vh < 0 else 'se mantuvo')} "
            "respecto de la observación anterior. Sin una variación VV válida, la lectura "
            "del comportamiento conjunto queda incompleta."
        )

    if ratio is not None:
        if ratio > 0:
            base += " La diferencia entre VH y VV también aumentó, por lo que cambió la relación entre ambas respuestas."
        elif ratio < 0:
            base += " La diferencia entre VH y VV disminuyó, por lo que cambió la relación entre ambas respuestas."
        else:
            base += " La diferencia entre VH y VV se mantuvo estable."

    base += (
        " Estas variaciones pueden responder a humedad, rugosidad del suelo y "
        "características de la cobertura vegetal; los datos por sí solos no permiten "
        "determinar cuál de esos factores produjo el cambio."
    )
    return base


def _sar_followup_text(radar):
    vv = radar.get("delta_vv_num")
    vh = radar.get("delta_vh_num")
    if vv is None or vh is None:
        return (
            "Revisar la próxima adquisición Sentinel-1 y completar la comparación "
            "cuando estén disponibles ambas polarizaciones."
        )
    if (vv > 0 and vh > 0) or (vv < 0 and vh < 0):
        return (
            "Comparar la próxima adquisición con la misma geometría y órbita. "
            "Si el cambio se mantiene, contrastarlo con lluvias recientes, estado "
            "del cultivo y antecedentes de manejo."
        )
    if vv == 0 and vh == 0:
        return (
            "Mantener el seguimiento en la próxima adquisición para comprobar "
            "si la estabilidad de la respuesta radar continúa."
        )
    return (
        "Revisar la próxima adquisición con la misma geometría y órbita y contrastar "
        "el comportamiento con el estado del cultivo y las labores recientes."
    )


def _state_signal(row, signal_field, value_field):
    """Presenta el estado calculado por AGIS sin inferir diagnósticos nuevos."""
    signal = (
        str(row[signal_field]).strip().upper()
        if signal_field in row.index and pd.notna(row[signal_field])
        else ""
    )
    if signal == "BAJA_RELATIVA":
        return "Señal baja relativa"
    if signal in {"NO_CONCLUYENTE", "INDETERMINADA", "INDETERMINADO"}:
        return "No concluyente"
    if signal in {"SIN_EVIDENCIA", "NO_DISPONIBLE", "SIN_DATOS"}:
        return "Sin evidencia óptica"
    if signal in {"SIN_DESVIACION_RELATIVA", "SIN DESVIACION RELATIVA", "NORMAL"}:
        return "Sin desviación relativa"
    if not signal and value_field in row.index and pd.notna(row[value_field]):
        return "Estado no informado"
    return "Sin evidencia óptica"


def _general_state(row):
    mode = _monitoring_mode(row)
    if mode == "MONITOREO POR RADAR SAR":
        return "Seguimiento por SAR"

    ndmi_low = (
        "senal_relativa_NDMI" in row.index
        and str(row["senal_relativa_NDMI"]).strip().upper() == "BAJA_RELATIVA"
    )
    ndre_low = (
        "senal_relativa_NDRE" in row.index
        and str(row["senal_relativa_NDRE"]).strip().upper() == "BAJA_RELATIVA"
    )

    if ndmi_low and ndre_low:
        return "Observar ambas dimensiones"
    if ndmi_low or ndre_low:
        return "Observar"
    return "Seguimiento"


def _sar_pattern_label(row):
    """Clasifica solo la dirección conjunta de VV/VH; no asigna prioridad agronómica."""
    radar = _sar_metrics(row)
    vv, vh = radar["delta_vv_num"], radar["delta_vh_num"]
    if vv is None or vh is None:
        return "Sin comparación completa"
    if vv == 0 and vh == 0:
        return "Sin variación en VV y VH"
    if vv > 0 and vh > 0:
        return "Aumento conjunto en VV y VH"
    if vv < 0 and vh < 0:
        return "Disminución conjunta en VV y VH"
    return "Cambios en direcciones diferentes"


def _interpretation_sections(row, radar_only=False):
    """
    Redacta una lectura operativa y diferenciada por patrón de evidencia.
    No recalcula señales, prioridades ni diagnósticos agronómicos.
    """
    def value(field, fallback=""):
        if field not in row.index or pd.isna(row[field]):
            return fallback
        return str(row[field]).strip()

    def number(field):
        return _num(row[field]) if field in row.index else None

    def direction(delta):
        if delta is None:
            return "sin comparación temporal disponible"
        if delta > 0:
            return "aumentó"
        if delta < 0:
            return "disminuyó"
        return "se mantuvo"

    def clean_text(text):
        return re.sub(r"\s+", " ", str(text or "")).strip(" .;")

    def date_short(raw):
        raw = str(raw or "").strip()
        if not raw or raw.lower() in ("nan", "none", "—"):
            return "fecha no informada"
        try:
            return pd.to_datetime(raw).strftime("%d/%m/%Y")
        except Exception:
            return raw

    if radar_only:
        radar = _sar_metrics(row)
        radar_line = (
            f"VV {radar['vv_actual']} dB; VH {radar['vh_actual']} dB; "
            f"VH−VV {radar['ratio_actual']} dB. "
            f"Comparación anterior: VV {radar['vv_anterior']}, VH {radar['vh_anterior']} "
            f"y VH−VV {radar['ratio_anterior']} dB."
        )
        if radar["comparison"] not in ("—", ""):
            radar_line += f" {radar['comparison']}."
        return [
            ("Evidencia disponible", "No hubo observaciones ópticas válidas suficientes en este período; el seguimiento se apoya en Sentinel-1."),
            ("Lectura del radar", radar_line),
            ("Qué podría estar pasando", _sar_change_interpretation(radar)),
            ("Qué conviene revisar", _sar_followup_text(radar)),
        ]

    ndmi = value("senal_relativa_NDMI", "NO_INFORMADA").upper()
    ndre = value("senal_relativa_NDRE", "NO_INFORMADA").upper()
    conv = value("convergencia", "").lower()
    ndmi_label = _state_signal(row, "senal_relativa_NDMI", "ndmi")
    ndre_label = _state_signal(row, "senal_relativa_NDRE", "ndre")
    delta_ndmi = number("delta_ndmi")
    delta_ndre = number("delta_ndre")
    ndmi_low = "BAJA_RELATIVA" in ndmi
    ndre_low = "BAJA_RELATIVA" in ndre
    both_low = ndmi_low and ndre_low
    convergent = conv in ("true", "1", "sí", "si", "yes")
    partial = ndmi_low != ndre_low

    both_down = delta_ndmi is not None and delta_ndre is not None and delta_ndmi < 0 and delta_ndre < 0
    both_up = delta_ndmi is not None and delta_ndre is not None and delta_ndmi > 0 and delta_ndre > 0
    mixed = delta_ndmi is not None and delta_ndre is not None and (
        (delta_ndmi < 0 < delta_ndre) or (delta_ndre < 0 < delta_ndmi)
    )

    # Descripción óptica: qué índice aporta la señal y cómo cambió en la referencia temporal.
    if both_low and convergent:
        optical_reading = (
            f"NDMI y NDRE están en posición relativa baja frente al conjunto comparable. "
            f"En sus referencias temporales, NDMI {direction(delta_ndmi)} y NDRE {direction(delta_ndre)}. "
            "La coincidencia refuerza la señal relativa, pero ambos índices están relacionados y no identifican una causa."
        )
    elif partial:
        low_index = "NDMI" if ndmi_low else "NDRE"
        other_index = "NDRE" if ndmi_low else "NDMI"
        optical_reading = (
            f"La señal relativa baja aparece en {low_index}; {other_index} no presenta una señal equivalente. "
            f"En la comparación temporal, NDMI {direction(delta_ndmi)} y NDRE {direction(delta_ndre)}. "
            "La respuesta es parcial, no una confirmación entre indicadores."
        )
    else:
        optical_reading = (
            f"No se observa una señal relativa baja coincidente (NDMI: {ndmi_label.lower()}; "
            f"NDRE: {ndre_label.lower()}). En la comparación temporal, NDMI {direction(delta_ndmi)} "
            f"y NDRE {direction(delta_ndre)}. Estos cambios se conservan como contexto, no como diagnóstico."
        )

    # Radar: integrar las dos polarizaciones y su relación, con fechas explícitas.
    radar = _sar_metrics(row)
    sar_available = _is_true(value("SAR_disponible", "false"))
    s2_date = date_short(value("ultima_pasada_S2", ""))
    s1_date = date_short(value("sar_fecha_actual", value("ultima_pasada_S1", "")))
    if not sar_available:
        radar_clause = "Sentinel-1 no aporta una observación válida para esta ficha."
    elif radar["delta_vv_num"] is None and radar["delta_vh_num"] is None:
        radar_clause = f"Sentinel-1 disponible al {s1_date}, sin comparación válida de VV y VH."
    else:
        radar_bits = []
        if radar["delta_vv_num"] is not None:
            radar_bits.append(f"VV {radar['delta']} dB")
        if radar["delta_vh_num"] is not None:
            radar_bits.append(f"VH {radar['delta_vh']} dB")
        if radar["delta_ratio_num"] is not None:
            radar_bits.append(f"VH−VV {radar['delta_ratio']} dB")
        radar_clause = (
            f"Radar Sentinel-1 ({s1_date}): variación " + ", ".join(radar_bits) + ". "
            f"La última observación óptica fue {s2_date}; las fechas no son simultáneas. "
        )
        vv_delta = radar["delta_vv_num"]
        vh_delta = radar["delta_vh_num"]
        if vv_delta is not None and vh_delta is not None:
            if vv_delta * vh_delta > 0:
                radar_clause += "VV y VH cambiaron en la misma dirección. "
            elif vv_delta * vh_delta < 0:
                radar_clause += "VV y VH cambiaron en direcciones opuestas; la respuesta radar no fue uniforme. "
            else:
                radar_clause += "Una polarización se mantuvo sin variación mientras la otra cambió. "
        if radar["comparison"] not in ("—", ""):
            radar_clause += "La comparación SAR mantiene la misma órbita relativa, sentido y plataforma. "
        radar_clause += (
            "El radar aporta una respuesta complementaria de la superficie y la estructura de la cobertura; "
            "no confirma ni contradice por sí solo los índices ópticos."
        )
    integrated = optical_reading + " " + radar_clause

    # Hallazgo conciso; evita duplicar la interpretación temporal en tres apartados.
    if both_low and convergent:
        observation = "Señal relativa baja coincidente en NDMI y NDRE respecto del conjunto comparable."
    elif partial:
        low_index = "NDMI" if ndmi_low else "NDRE"
        observation = f"Señal relativa baja en {low_index}, sin coincidencia en el otro indicador."
    else:
        observation = "Sin señal relativa baja coincidente en los indicadores ópticos disponibles."

    fenologia = value("fenologia_etapa", "")
    if fenologia and fenologia.upper() not in ("NO_DETERMINABLE", "NO INFORMADA"):
        observation += f" Etapa fenológica informada: {fenologia}."
    else:
        observation += " La etapa fenológica no pudo determinarse en esta corrida."

    # Significado: separa posición relativa y evolución temporal, sin convertir un intervalo en tendencia.
    if both_low and both_up:
        meaning = (
            "El lote se ubica relativamente bajo frente a sus comparables, pero ambos índices aumentaron "
            "respecto de sus referencias. La señal indica una diferencia entre lotes, no una caída reciente."
        )
    elif both_low and both_down:
        meaning = (
            "La posición relativa baja coincide con descensos de ambos índices frente a sus referencias. "
            "Es un motivo concreto para contrastar el sector en campo; este intervalo aislado no demuestra "
            "persistencia ni deterioro."
        )
    elif both_low and mixed:
        meaning = (
            "La posición relativa baja coincide con cambios temporales en direcciones distintas. "
            "La señal merece contraste, pero no hay una evolución óptica coincidente."
        )
    elif both_low:
        meaning = (
            "La señal se basa en la posición relativa baja de ambos índices. La comparación temporal disponible "
            "no permite establecer una evolución común."
        )
    elif partial:
        low_index = "NDMI" if ndmi_low else "NDRE"
        low_delta = delta_ndmi if ndmi_low else delta_ndre
        if low_delta is not None and low_delta < 0:
            meaning = (
                f"La señal se concentra en {low_index}, que además disminuyó frente a su referencia. "
                "Conviene comprobar si la diferencia tiene una expresión visible y localizada en el lote."
            )
        elif low_delta is not None and low_delta > 0:
            meaning = (
                f"La señal se concentra en {low_index}, aunque aumentó frente a su referencia temporal. "
                "Por ahora describe una posición relativa, no una caída reciente del indicador."
            )
        else:
            meaning = (
                f"La señal se concentra en {low_index}; la evolución temporal no alcanza para caracterizar "
                "un cambio en esa misma dimensión."
            )
    else:
        meaning = (
            "No se identificó una señal relativa baja suficiente para destacar este lote. "
            "Las variaciones temporales, por sí solas, no justifican elevar su atención."
        )

    # Orientación de campo diferenciada por cultivo, indicador y patrón temporal.
    crop = value("cultivo", "").strip().lower()
    if crop in ("manzano", "peral"):
        if both_low and both_down:
            field_check = (
                "Recorrer primero los sectores que concentran la señal en el mapa. Comparar continuidad de copa, "
                "densidad de follaje y coloración entre esos sectores y otros del mismo lote. Revisar uniformidad "
                "de emisores y distribución del agua; comprobar si el patrón coincide con cambios de suelo, "
                "bordes o diferencias de manejo. Registrar si se repite en más de un sector."
            )
        elif both_low and both_up:
            field_check = (
                "Comprobar si los sectores relativamente bajos tienen menor continuidad o densidad de copa que "
                "el resto, o si la diferencia responde a variación entre plantas, filas o etapa de desarrollo. "
                "Comparar follaje y distribución de frutos entre sectores; revisar riego y suelo solo donde "
                "el patrón espacial lo sugiera."
            )
        elif both_low and mixed:
            field_check = (
                "Localizar los sectores con señal y comparar por separado cobertura/densidad de copa y coloración "
                "del follaje. Verificar si las diferencias se repiten entre filas o plantas y contrastarlas con "
                "riego, suelo y manejo reciente; no asumir una respuesta uniforme del cultivo."
            )
        elif both_low:
            field_check = (
                "Comparar en los sectores señalados continuidad de copa, densidad de follaje y coloración con "
                "sectores representativos del mismo lote. Verificar si la diferencia se concentra en filas, bordes "
                "o cambios de suelo y contrastarla con la distribución del riego."
            )
        elif partial and ndmi_low:
            field_check = (
                "En los sectores señalados, revisar continuidad de copa y distribución del follaje; comprobar "
                "uniformidad del riego y diferencias visibles de humedad del suelo, sin inferirlas directamente "
                "del NDMI. Comparar con sectores vecinos del mismo lote."
            )
        elif partial and ndre_low:
            field_check = (
                "En los sectores señalados, comparar coloración y densidad del follaje entre plantas y filas. "
                "Revisar si la diferencia coincide con variación de copa, etapa de desarrollo o manejo reciente; "
                "contrastar con sectores vecinos antes de atribuirle una causa."
            )
        else:
            field_check = (
                "No hay un sector que requiera una verificación específica a partir de estas señales. "
                "Mantener la observación habitual y comparar la próxima actualización con la distribución "
                "actual de copa y follaje."
            )
    else:
        if both_low and both_down:
            field_check = (
                "Recorrer primero los sectores señalados y comparar cobertura, uniformidad y estado visible "
                "del cultivo con sectores representativos del mismo lote. Revisar si el patrón coincide con "
                "diferencias de suelo, relieve, agua o manejo; registrar si aparece en más de un sector."
            )
        elif partial and ndmi_low:
            field_check = (
                "Comprobar cobertura y distribución de la vegetación en los sectores señalados y contrastarlas "
                "con humedad superficial, suelo y manejo reciente. No interpretar el NDMI como medición directa "
                "de agua disponible."
            )
        elif partial and ndre_low:
            field_check = (
                "Comparar cobertura, uniformidad y coloración visible de la vegetación en los sectores señalados. "
                "Revisar diferencias de desarrollo, suelo y manejo antes de atribuir una causa al patrón."
            )
        else:
            field_check = (
                "Contrastar el patrón espacial con sectores representativos del lote y con la etapa del cultivo. "
                "No se desprende de esta corrida una verificación agronómica específica."
            )

    # Conservar observaciones de la KB cuando aportan un foco concreto, sin duplicar frases genéricas.
    kb_focus = clean_text(value("que_revisar", ""))
    kb_focus = re.sub(r"\s*Observación radar:.*$", "", kb_focus, flags=re.IGNORECASE).strip(" .;")
    generic_phrases = (
        "mantener seguimiento",
        "contrastar la evolución temporal",
        "contexto fenológico",
    )
    if kb_focus and not any(p in kb_focus.lower() for p in generic_phrases):
        if len(kb_focus) <= 220 and kb_focus.lower() not in field_check.lower():
            field_check = f"Además, {kb_focus[0].lower() + kb_focus[1:]}"

    alternatives = clean_text(value("hipotesis_alternativas", ""))
    limits = clean_text(value("limitaciones", ""))
    # Acotar el listado de alternativas para que no opaque la orientación principal.
    if alternatives:
        alternatives = alternatives.replace(" | ", "; ")
        scope = f"Factores alternativos: {alternatives}. "
    else:
        scope = ""
    scope += limits or (
        "Los índices y el radar no identifican por sí solos una causa ni sustituyen la observación agronómica."
    )
    scope = clean_text(scope)

    return [
        ("Qué observamos", observation),
        ("Lectura integrada de evidencias", integrated),
        ("Qué significa para el seguimiento", meaning),
        ("Qué conviene verificar en campo", field_check),
        ("Límites de la interpretación", scope),
    ]

def _interpretation_table(row, body, small, radar_only=False):
    """Construye la ficha interpretativa a partir de campos existentes del CSV."""
    sections = _interpretation_sections(row, radar_only=radar_only)
    rows = []
    for label, text in sections:
        rows.append([
            Paragraph(
                f"<b>{label}</b>",
                ParagraphStyle(
                    f"InterpretationLabel{label}",
                    parent=small,
                    fontName=FONT_BOLD,
                    fontSize=8.8,
                    leading=11,
                    textColor=colors.HexColor(CHARCOAL),
                )
            ),
            Paragraph(
                text or "—",
                ParagraphStyle(
                    f"InterpretationBody{label}",
                    parent=small,
                    fontName=FONT_REGULAR,
                    fontSize=8.2,
                    leading=10.5,
                    textColor=colors.HexColor(CHARCOAL),
                )
            )
        ])
    table = RoundedTable(
        rows,
        colWidths=[43 * mm, 132 * mm],
        radius=7,
        panel_fill=colors.white,
        panel_stroke=colors.HexColor("#CDD6D1")
    )
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    for r in range(len(rows)):
        style.extend([
            ("BACKGROUND", (0, r), (0, r), colors.HexColor("#F0F6F2" if r % 2 == 0 else "#F7F9F7")),
            ("LINEBEFORE", (0, r), (0, r), 2, colors.HexColor(GREEN if not radar_only else "#5C625F")),
        ])
    table.setStyle(TableStyle(style))
    return table

def _format_reference_date(value):
    """Fecha compacta DD/MM, conservando el año cuando cambia."""
    if value is None or pd.isna(value):
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return str(value)
    return parsed.strftime("%d/%m")


def _temporal_trend_cell(row, index_name, trend_cell_style):
    """
    Presenta valor actual, promedio de referencia y diferencia temporal.
    Utiliza exclusivamente los campos ya exportados por AGIS.
    """
    suffix = index_name.upper()
    current_field = index_name.lower()
    reference_field = f"{index_name.lower()}_anterior"
    delta_field = f"delta_{index_name.lower()}"
    state_field = f"estado_comparacion_{suffix}"
    start_field = f"fecha_referencia_inicio_{suffix}"
    end_field = f"fecha_referencia_fin_{suffix}"
    count_field = f"observaciones_referencia_{suffix}_temporal"

    current = row[current_field] if current_field in row.index else None
    reference = row[reference_field] if reference_field in row.index else None
    delta_value = row[delta_field] if delta_field in row.index else None
    state = (
        str(row[state_field]).strip().upper()
        if state_field in row.index and pd.notna(row[state_field])
        else ""
    )

    current_txt = _fmt2(current)
    if state.startswith("NO_") or reference is None or pd.isna(reference) or delta_value is None or pd.isna(delta_value):
        label = "Sin dato óptico" if _is_radar_only(row) else "Sin comparación"
        return Paragraph(
            f"<b>{current_txt}</b><br/>"
            f"<font size='6.5' color='#777F7A'>{label}</font>",
            trend_cell_style
        )

    try:
        reference_num = float(reference)
        delta = float(delta_value)
    except (TypeError, ValueError):
        return Paragraph(
            f"<b>{current_txt}</b><br/><font size='6.5' color='#777F7A'>Sin comparación</font>",
            trend_cell_style
        )

    if delta > 0:
        arrow, color_hex = "↑", "#25834A"
    elif delta < 0:
        arrow, color_hex = "↓", "#C43D42"
    else:
        arrow, color_hex = "→", "#626A66"

    return Paragraph(
        f"<b>{current_txt}</b>"
        f"<br/><font size='6.5' color='#626A66'>Ref.: {reference_num:.3f}</font>"
        f"<br/><font color='{color_hex}'><b>{arrow} {delta:+.3f}</b></font>",
        trend_cell_style
    )


def _priority_comparison_cell(row, index_name, body):
    """Indicador de ficha: índice, valor actual, referencia y diferencia."""
    suffix = index_name.upper()
    current_field = index_name.lower()
    reference_field = f"{index_name.lower()}_anterior"
    delta_field = f"delta_{index_name.lower()}"
    state_field = f"estado_comparacion_{suffix}"

    current = row[current_field] if current_field in row.index else None
    reference = row[reference_field] if reference_field in row.index else None
    delta_value = row[delta_field] if delta_field in row.index else None
    state = (
        str(row[state_field]).strip().upper()
        if state_field in row.index and pd.notna(row[state_field])
        else ""
    )

    index_label = "NDRE · Índice de vegetación" if index_name.lower() == "ndre" else "NDMI · Índice de vegetación"
    current_txt = _fmt2(current)

    lines = [
        f"<font size='8' color='#33503F'><b>{index_label}</b></font>",
        f"<font size='14'><b>{current_txt}</b></font>",
    ]

    valid_comparison = (
        not state.startswith("NO_")
        and reference is not None and not pd.isna(reference)
        and delta_value is not None and not pd.isna(delta_value)
    )

    if valid_comparison:
        try:
            reference_num = float(reference)
            delta = float(delta_value)
            if delta > 0:
                arrow, color_hex = "↑", "#25834A"
            elif delta < 0:
                arrow, color_hex = "↓", "#C43D42"
            else:
                arrow, color_hex = "→", "#626A66"

            lines.append(
                f"<font size='7' color='#626A66'>Ref.: {reference_num:.3f}</font>"
            )
            lines.append(
                f"<font size='8' color='{color_hex}'><b>{arrow} {delta:+.3f}</b></font>"
            )
        except (TypeError, ValueError):
            lines.append("<font size='7' color='#777F7A'>Sin comparación</font>")
    else:
        label = "Sin dato óptico" if _is_radar_only(row) else "Sin comparación"
        lines.append(f"<font size='7' color='#777F7A'>{label}</font>")

    return Paragraph(
        "<br/>".join(lines),
        ParagraphStyle(
            f"PriorityComparison_{index_name}",
            parent=body,
            fontName=FONT_REGULAR,
            fontSize=8,
            leading=11,
            textColor=colors.HexColor(CHARCOAL),
            spaceBefore=0,
            spaceAfter=0,
        )
    )


def _state_table(df, body, small, follow_df=None):
    if follow_df is None:
        follow_df = df[df["prioridad"] == "SEGUIMIENTO"].copy()
    else:
        follow_df = follow_df.copy()
    if follow_df.empty:
        return None

    header_style = ParagraphStyle(
        "AGIS_TableHeaderWhite",
        parent=small,
        textColor=colors.white,
        fontName=FONT_BOLD,
        fontSize=7.2,
        leading=8.2,
    )

    state_cell_style = ParagraphStyle(
        "AGIS_StateTableCell",
        parent=small,
        fontSize=9.2,
        leading=11.0,
    )

    trend_cell_style = ParagraphStyle(
        "AGIS_TemporalTrendCell",
        parent=small,
        fontSize=9.1,
        leading=11.0,
        spaceAfter=0,
    )

    rows = [[
        Paragraph("ESTABLECIMIENTO", header_style),
        Paragraph("LOTE", header_style),
        Paragraph("MODALIDAD", header_style),
        Paragraph("NDMI<br/>ACTUAL / REF. / DIF.", header_style),
        Paragraph("NDRE<br/>ACTUAL / REF. / DIF.", header_style),
        Paragraph("ESTADO GENERAL", header_style),
    ]]
    states = []

    for _, row in follow_df.iterrows():
        mode = _monitoring_mode(row)
        estado = _general_state(row)
        states.append(estado.lower())

        rows.append([
            Paragraph(f"<b>{_fmt(row['establecimiento'])}</b>", state_cell_style),
            Paragraph(f"<b>{_fmt(row['lote'])}</b>", state_cell_style),
            Paragraph(mode.replace("MONITOREO ", ""), state_cell_style),
            _temporal_trend_cell(row, "ndmi", trend_cell_style),
            _temporal_trend_cell(row, "ndre", trend_cell_style),
            Paragraph(estado, state_cell_style),
        ])

    table = Table(
        rows,
        colWidths=[32 * mm, 20 * mm, 25 * mm, 37 * mm, 37 * mm, 24 * mm],
        repeatRows=1
    )

    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(GREEN)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#D0D6D2")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E0E4E1")),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3.6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.6),
    ]

    for r, state in enumerate(states, start=1):
        if r % 2 == 0:
            style.append(("BACKGROUND", (0, r), (-1, r), colors.HexColor("#F7F9F7")))
        if "observar" in state:
            style.append(("TEXTCOLOR", (5, r), (5, r), colors.HexColor("#7A6414")))
        elif "sar" in state:
            style.append(("TEXTCOLOR", (5, r), (5, r), colors.HexColor("#4A4F4C")))
        else:
            style.append(("TEXTCOLOR", (5, r), (5, r), colors.HexColor(GREEN)))

    table.setStyle(TableStyle(style))
    return table


def _sar_metrics(row):
    """Lee los nueve campos trivariados SAR del CSV; conserva respaldo textual."""
    def get_num(fields):
        for field in fields:
            if field in row.index:
                value = _num(row[field])
                if value is not None:
                    return value
        return None

    def fmt(value):
        return "—" if value is None else f"{value:.2f}".replace(".", ",")

    vv_actual_n = get_num(["sar_VV_actual_dB"])
    vv_previous_n = get_num(["sar_VV_anterior_dB"])
    vv_delta_n = get_num(["sar_delta_VV_dB"])
    vh_actual_n = get_num(["sar_VH_actual_dB"])
    vh_previous_n = get_num(["sar_VH_anterior_dB"])
    vh_delta_n = get_num(["sar_delta_VH_dB"])
    ratio_actual_n = get_num(["sar_VH_minus_VV_actual_dB"])
    ratio_previous_n = get_num(["sar_VH_minus_VV_anterior_dB"])
    ratio_delta_n = get_num(["sar_delta_VH_minus_VV_dB"])

    # Si falta el delta exportado, calcularlo solo a partir de los dos valores de origen.
    if vv_delta_n is None and vv_actual_n is not None and vv_previous_n is not None:
        vv_delta_n = vv_actual_n - vv_previous_n
    if vh_delta_n is None and vh_actual_n is not None and vh_previous_n is not None:
        vh_delta_n = vh_actual_n - vh_previous_n
    if ratio_delta_n is None and ratio_actual_n is not None and ratio_previous_n is not None:
        ratio_delta_n = ratio_actual_n - ratio_previous_n

    # Compatibilidad con exportaciones anteriores que solo incluían VV en texto.
    if vv_actual_n is None:
        texts = " ".join(str(row.get(f, "")) for f in ("hallazgo_agis", "fundamento_interpretacion", "hipotesis_agis", "que_revisar"))
        match = re.search(r"VV\s+actual\s*[:=]?\s*([-+]?\d+(?:[.,]\d+)?)\s*dB", texts, re.I)
        if match:
            vv_actual_n = _num(match.group(1))
        match = re.search(r"VV\s+anterior\s*[:=]?\s*([-+]?\d+(?:[.,]\d+)?)\s*dB", texts, re.I)
        if match:
            vv_previous_n = _num(match.group(1))
        if vv_delta_n is None and vv_actual_n is not None and vv_previous_n is not None:
            vv_delta_n = vv_actual_n - vv_previous_n

    comparison = str(row.get("sar_tipo_comparacion", row.get("__tipo_comparacion_SAR", "—")))
    if comparison in ("nan", "None", ""):
        comparison = "—"
    elif comparison == "MISMA_ORBITA_SENTIDO_PLATAFORMA":
        comparison = (
            "Comparación realizada con la misma órbita relativa, "
            "sentido de observación y plataforma"
        )
    s1_date = _fmt(row.get("sar_fecha_actual", row.get("ultima_pasada_S1", "—")))

    return {
        "vv_actual": fmt(vv_actual_n), "vv_anterior": fmt(vv_previous_n), "delta": fmt(vv_delta_n),
        "vh_actual": fmt(vh_actual_n), "vh_anterior": fmt(vh_previous_n), "delta_vh": fmt(vh_delta_n),
        "ratio_actual": fmt(ratio_actual_n), "ratio_anterior": fmt(ratio_previous_n), "delta_ratio": fmt(ratio_delta_n),
        "delta_vv_num": vv_delta_n, "delta_vh_num": vh_delta_n, "delta_ratio_num": ratio_delta_n,
        "comparison": comparison, "s1_date": s1_date,
    }


def build_pdf(df, gdf, raster, logo_bytes):

    logo_bytes = _resolve_logo_bytes(logo_bytes)

    out = BytesIO()

    doc = SimpleDocTemplate(
        out,
        pagesize=A4,
        rightMargin=17 * mm,
        leftMargin=17 * mm,
        topMargin=12 * mm,
        bottomMargin=15 * mm
    )
    # Identificador verificable del generador realmente ejecutado.
    doc.title = "AGIS Informe de Monitoreo — Generador PDF V4 · SAR Trivariado V5"
    doc.author = "AGIS"
    doc.subject = "PDF generado con interpretación SAR trivariada VV, VH y VH−VV — V5"

    styles = getSampleStyleSheet()

    title = ParagraphStyle(
        "AGISTitle",
        parent=styles["Title"],
        fontName=FONT_BOLD,
        fontSize=23,
        leading=27,
        textColor=colors.HexColor(CHARCOAL),
        alignment=TA_LEFT,
        spaceAfter=5
    )

    h2 = ParagraphStyle(
        "AGISH2",
        parent=styles["Heading2"],
        fontName=FONT_BOLD,
        fontSize=15,
        leading=18,
        textColor=colors.HexColor(GREEN),
        spaceBefore=3,
        spaceAfter=6
    )

    body = ParagraphStyle(
        "AGISBody",
        parent=styles["BodyText"],
        fontName=FONT_REGULAR,
        fontSize=9.2,
        leading=12.5,
        textColor=colors.HexColor(CHARCOAL)
    )

    small = ParagraphStyle(
        "AGISSmall",
        parent=body,
        fontSize=8,
        leading=10
    )

    big = ParagraphStyle(
        "AGISBig",
        parent=body,
        fontSize=12,
        leading=15
    )

    priority_style = ParagraphStyle(
        "AGISPriority",
        parent=body,
        fontName=FONT_BOLD,
        fontSize=11,
        leading=13,
        textColor=colors.HexColor(GREEN)
    )

    story = []

    # ---------------------------------------------------------
    # DATOS GENERALES
    # ---------------------------------------------------------

    client_name = (
        _fmt(df["cliente"].dropna().iloc[0])
        if not df.empty and "cliente" in df.columns
        else "—"
    )

    period_start = (
        _fmt(df["periodo_inicio"].dropna().iloc[0])
        if not df.empty
        else "—"
    )

    period_end = (
        _fmt(df["periodo_fin"].dropna().iloc[0])
        if not df.empty
        else "—"
    )

    latest_s2 = _latest_s2_date(df)
    latest_s1 = _latest_s1_date(df)

    # Activación excepcional: solo cuando TODOS los lotes son exclusivamente SAR.
    # No modifica modalidades, prioridades ni cálculos generados por AGIS.
    radar_lot_count = int(df.apply(_is_radar_only, axis=1).sum()) if not df.empty else 0
    all_sar_mode = bool(not df.empty and radar_lot_count == len(df))

    report_date = date.today().strftime("%d/%m/%Y")
    doc._agis_pdf_title = f"AGIS - Informe de monitoreo - {client_name} - {report_date}"

    # ---------------------------------------------------------
    # PORTADA / RESUMEN
    # ---------------------------------------------------------

    header_data = []

    title_block = [
        Paragraph(
            "Informe de monitoreo",
            title
        ),
        Paragraph(
            f"<b>Cliente:</b> {client_name}",
            big
        ),
        Spacer(1, 1.5 * mm),
        Paragraph(
            f"<b>Fecha de emisión:</b> {report_date}",
            body
        ),
        Spacer(1, 1.5 * mm),
        Paragraph(
            f"Período analizado: {period_start} → {period_end}",
            body
        ),
        Spacer(1, 1.5 * mm),
        Paragraph(
            f"Última observación óptica (Sentinel-2): {latest_s2}",
            body
        ),
        Spacer(1, 1.5 * mm),
        Paragraph(
            f"Última observación radar (Sentinel-1): {latest_s1}",
            body
        )
    ]

    if logo_bytes:

        logo = Image(
            BytesIO(logo_bytes),
            width=28 * mm,
            height=28 * mm
        )

        header_table = Table(
            [[title_block, logo]],
            colWidths=[
                140 * mm,
                35 * mm
            ]
        )

        header_table.setStyle(
            TableStyle([
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "TOP"
                ),
                (
                    "ALIGN",
                    (1, 0),
                    (1, 0),
                    "RIGHT"
                ),
                (
                    "LEFTPADDING",
                    (0, 0),
                    (-1, -1),
                    0
                ),
                (
                    "RIGHTPADDING",
                    (0, 0),
                    (-1, -1),
                    0
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    0
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    0
                )
            ])
        )

        story.append(header_table)

    else:

        story.append(
            Paragraph(
                "Informe de monitoreo",
                title
            )
        )

        story.append(
            Paragraph(
                f"<b>Cliente:</b> {client_name}",
                big
            )
        )

        story.append(
            Paragraph(
                f"<b>Fecha de emisión:</b> {report_date}",
                body
            )
        )

        story.append(
            Paragraph(
                f"Período analizado: {period_start} → {period_end}",
                body
            )
        )

        story.append(Paragraph(
            f"Última observación óptica (Sentinel-2): {latest_s2}", body
        ))
        story.append(Paragraph(
            f"Última observación radar (Sentinel-1): {latest_s1}", body
        ))

    if all_sar_mode:
        sar_notice = RoundedTable(
            [[Paragraph(
                f"<b>MODALIDAD DE MONITOREO: 100% RADAR SAR</b><br/>"
                f"Los {radar_lot_count} lotes fueron monitoreados mediante radar Sentinel-1. "
                "Durante el período no hubo evidencia óptica válida suficiente para el seguimiento.",
                ParagraphStyle(
                    "AllSARCoverNotice",
                    parent=body,
                    fontName=FONT_REGULAR,
                    fontSize=9,
                    leading=12,
                    textColor=colors.white,
                )
            )]],
            colWidths=[175 * mm],
            radius=7,
            panel_fill=colors.HexColor("#343836"),
            panel_stroke=colors.HexColor("#343836"),
        )
        sar_notice.setStyle(TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        story.append(sar_notice)
        story.append(Spacer(1, 3 * mm))

    story.append(
        Spacer(1, 8 * mm)
    )

    # ---------------------------------------------------------
    # RESUMEN INTEGRADO DE PRIORIDADES
    # ---------------------------------------------------------

    high = int((df["prioridad"] == "PRIORIDAD ALTA").sum())
    medium = int((df["prioridad"] == "PRIORIDAD MEDIA").sum())
    follow = int((df["prioridad"] == "SEGUIMIENTO").sum())
    high_area_ha = _high_priority_area_ha(gdf)

    def _ha_text(value):
        return f"{value:,.1f} ha".replace(",", "X").replace(".", ",").replace("X", ".")

    # 1) Resumen de prioridades: bloque ancho, arriba.
    priority_cards = [
        [
            _stacked_metric_cell("LOTES", len(df), value_size=21),
            _stacked_metric_cell("SEÑAL RELATIVA CONVERGENTE", high, value_size=14),
            _stacked_metric_cell("SEÑAL RELATIVA PARCIAL", medium, value_size=14),
            _stacked_metric_cell("SEGUIMIENTO", follow, value_size=21)
        ]
    ]

    priority_grid = Table(
        priority_cards,
        colWidths=[43.75 * mm] * 4,
        rowHeights=[28 * mm]
    )
    priority_grid.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("BACKGROUND", (0, 0), (0, 0), colors.HexColor(BONE)),
        ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#FFF0F2")),
        ("BACKGROUND", (2, 0), (2, 0), colors.HexColor("#FFFBE6")),
        ("BACKGROUND", (3, 0), (3, 0), colors.HexColor("#EAF3EE")),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor(CHARCOAL)),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))

    summary_title = Paragraph(
        "<b>Resumen del seguimiento</b>",
        ParagraphStyle(
            "PrioritySummaryTitleFinal",
            parent=body,
            fontName=FONT_BOLD,
            fontSize=12,
            leading=14,
            textColor=colors.HexColor(GREEN)
        )
    )

    summary_panel = RoundedTable(
        [[summary_title], [priority_grid]],
        colWidths=[175 * mm],
        radius=8,
        panel_fill=colors.HexColor("#F8FAF8"),
        panel_stroke=colors.HexColor("#D5DDD8")
    )
    summary_panel.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 7),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 3),
        ("TOPPADDING", (0, 1), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 7),
    ]))
    story.append(summary_panel)
    if all_sar_mode:
        story.append(Spacer(1, 1.5 * mm))
        story.append(Paragraph(
            "No se asignaron prioridades alta o media en esta entrega; los 76 lotes permanecen en seguimiento. "
            "El comportamiento radar se describe por separado, sin convertirlo en prioridad agronómica.",
            small
        ))
    story.append(Spacer(1, 5 * mm))

    # 2) En modalidad 100% SAR se resume el comportamiento radar,
    # sin convertirlo en una prioridad agronómica. En modalidad óptica/mixta
    # se conserva la distribución de prioridades original.
    if all_sar_mode:
        behavior_counts = df.apply(_sar_pattern_label, axis=1).value_counts()
        behavior_order = [
            "Aumento conjunto en VV y VH",
            "Disminución conjunta en VV y VH",
            "Cambios en direcciones diferentes",
            "Sin variación en VV y VH",
            "Sin comparación completa",
        ]
        behavior_cards = []
        for label in behavior_order:
            count = int(behavior_counts.get(label, 0))
            if count <= 0:
                continue
            behavior_cards.append(
                _stacked_metric_cell(
                    label.upper(), count,
                    note_text=f"{count / len(df) * 100:.0f}% de los lotes",
                    value_size=19, title_size=7.5, note_size=7.2
                )
            )
        behavior_grid = Table(
            [behavior_cards],
            colWidths=[175 * mm / max(1, len(behavior_cards))] * len(behavior_cards),
            rowHeights=[31 * mm],
        )
        behavior_grid.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F1F3F2")),
            ("LINEBEFORE", (1, 0), (-1, -1), 0.6, colors.white),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        behavior_title = Paragraph(
            "<b>Comportamiento observado por radar</b>",
            ParagraphStyle(
                "SARBehaviorTitle", parent=body, fontName=FONT_BOLD,
                fontSize=12, leading=14, textColor=colors.HexColor(GREEN)
            )
        )
        behavior_note = Paragraph(
            "Clasificación descriptiva según la dirección de los cambios en VV y VH. "
            "No expresa magnitud, causa ni condición agronómica.",
            ParagraphStyle(
                "SARBehaviorNote", parent=small, fontSize=7.8, leading=9.5,
                alignment=TA_LEFT, textColor=colors.HexColor("#5A5F5C")
            )
        )
        behavior_panel = RoundedTable(
            [[behavior_title], [behavior_grid], [behavior_note]],
            colWidths=[175 * mm], radius=8,
            panel_fill=colors.white, panel_stroke=colors.HexColor("#D5DDD8")
        )
        behavior_panel.setStyle(TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, 0), 7),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
            ("TOPPADDING", (0, 1), (-1, 1), 1),
            ("BOTTOMPADDING", (0, 1), (-1, 1), 3),
            ("TOPPADDING", (0, 2), (-1, 2), 3),
            ("BOTTOMPADDING", (0, 2), (-1, 2), 7),
        ]))
        story.append(behavior_panel)
    else:
        donut = Image(_priority_donut(high, medium, follow), width=108 * mm, height=73 * mm)
        donut_title = Paragraph(
            "<b>Distribución de señales relativas</b>",
            ParagraphStyle(
                "PriorityDonutTitleFinal", parent=body, fontName=FONT_BOLD,
                fontSize=12, leading=14, textColor=colors.HexColor(GREEN),
                alignment=TA_CENTER
            )
        )
        donut_note = Paragraph(
            "La distribución muestra la clasificación relativa de los lotes según los indicadores disponibles; no representa diagnósticos ni confirma deterioro agronómico.",
            ParagraphStyle(
                "PriorityDonutNoteFinal", parent=small, fontSize=8.2,
                leading=10, alignment=TA_CENTER
            )
        )
        donut_panel = RoundedTable(
            [[donut_title], [donut], [donut_note]],
            colWidths=[175 * mm], radius=8,
            panel_fill=colors.white, panel_stroke=colors.HexColor("#D5DDD8")
        )
        donut_panel.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, 0), 7),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 1),
            ("TOPPADDING", (0, 1), (-1, 1), 0),
            ("BOTTOMPADDING", (0, 1), (-1, 1), 0),
            ("TOPPADDING", (0, 2), (-1, 2), 2),
            ("BOTTOMPADDING", (0, 2), (-1, 2), 7),
        ]))
        story.append(donut_panel)
    story.append(Spacer(1, 5 * mm))

    # 3) Superficie de prioridad alta: bloque independiente y visible.
    if not all_sar_mode:
        area_panel = RoundedTable(
            [[
                Paragraph(
                    "<b>SUPERFICIE CON SEÑAL RELATIVA CONVERGENTE</b>",
                    ParagraphStyle(
                        "HighAreaLabelFinal",
                        parent=body,
                        fontName=FONT_BOLD,
                        fontSize=10.5,
                        leading=13,
                        textColor=colors.HexColor(GREEN)
                    )
                ),
                Paragraph(
                    f"<font size='18'><b>{_ha_text(high_area_ha)}</b></font>",
                    ParagraphStyle(
                        "HighAreaValueFinal",
                        parent=body,
                        fontName=FONT_BOLD,
                        fontSize=12,
                        leading=15,
                        textColor=colors.HexColor(CHARCOAL),
                        alignment=TA_RIGHT
                    )
                )
            ]],
            colWidths=[125 * mm, 50 * mm],
            radius=8,
            panel_fill=colors.HexColor("#EAF3EE"),
            panel_stroke=colors.HexColor(GREEN)
        )
        area_panel.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        story.append(area_panel)
    story.append(Spacer(1, 5 * mm))

    closing_summary = (
        "Los cambios descritos corresponden al comportamiento de la señal radar y no "
        "constituyen por sí solos una condición ni una prioridad agronómica. La evaluación "
        "final corresponde al profesional."
        if all_sar_mode else
        "AGIS organiza la evidencia disponible para señalar qué merece atención y por qué. "
        "La evaluación agronómica final corresponde al profesional."
    )
    story.append(Paragraph(closing_summary, body))
    story.append(
        PageBreak()
    )

    # ---------------------------------------------------------
    # MAPA GENERAL
    # ---------------------------------------------------------

    map_section_title = (
        "1. Distribución del comportamiento radar" if all_sar_mode
        else "1. Dónde prestar atención"
    )
    story.append(Paragraph(map_section_title, h2))

    map_gdf = gdf.copy()
    if all_sar_mode and "id_unico" in map_gdf.columns:
        behavior_lookup = df[["id_unico"]].copy()
        behavior_lookup["comportamiento_sar"] = df.apply(_sar_pattern_label, axis=1).values
        behavior_lookup["id_unico"] = behavior_lookup["id_unico"].astype(str)
        map_gdf["id_unico"] = map_gdf["id_unico"].astype(str)
        map_gdf = map_gdf.merge(behavior_lookup, on="id_unico", how="left", suffixes=("", "_csv"))
        if "comportamiento_sar_csv" in map_gdf.columns:
            map_gdf["comportamiento_sar"] = map_gdf["comportamiento_sar_csv"].fillna(map_gdf.get("comportamiento_sar"))
            map_gdf = map_gdf.drop(columns=["comportamiento_sar_csv"])
        map_image = sar_behavior_map(map_gdf)
    else:
        map_image = general_priority_map(map_gdf)

    story.append(Image(map_image, width=175 * mm, height=132 * mm))

    story.append(
        Spacer(1, 3 * mm)
    )

    story.append(Spacer(1, 2 * mm))

    # Leyenda explícita, con los mismos colores definidos en maps.py.
    legend_style = ParagraphStyle(
        "PriorityMapLegendV4",
        parent=small,
        fontName=FONT_BOLD,
        fontSize=8,
        leading=10,
        textColor=colors.HexColor(CHARCOAL),
    )
    if all_sar_mode:
        legend_items = [
            (SAR_BEHAVIOR_COLORS["Aumento conjunto en VV y VH"], "Aumento conjunto VV y VH"),
            (SAR_BEHAVIOR_COLORS["Disminución conjunta en VV y VH"], "Disminución conjunta VV y VH"),
            (SAR_BEHAVIOR_COLORS["Cambios en direcciones diferentes"], "Direcciones diferentes"),
        ]
    else:
        legend_items = [
            ("#FF1744", "Señal relativa convergente"),
            ("#FFF000", "Señal relativa parcial"),
            ("#00FF66", "Seguimiento"),
        ]
    legend_cells = []
    for color_hex, label in legend_items:
        swatch = Table(
            [[Paragraph(" ", small)]],
            colWidths=[5 * mm],
            rowHeights=[3 * mm],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(color_hex)),
                ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor("#B9C1BC")),
            ])
        )
        legend_cells.extend([swatch, Paragraph(label, legend_style)])

    legend = Table(
        [legend_cells],
        colWidths=[7 * mm, 48 * mm, 7 * mm, 48 * mm, 7 * mm, 48 * mm],
        hAlign="LEFT",
    )
    legend.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 1),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(legend)
    story.append(Spacer(1, 1.5 * mm))
    if all_sar_mode:
        story.append(Paragraph(
            "Cada lote se agrupa por la dirección conjunta de los cambios VV y VH. "
            "La categoría describe la respuesta radar entre dos adquisiciones comparables; "
            "no identifica una causa ni indica por sí sola una condición favorable o desfavorable.",
            small
        ))
    else:
        story.append(Paragraph(
            "La distribución espacial localiza los lotes según su clasificación relativa. Estas categorías orientan el seguimiento y no constituyen por sí solas una prioridad agronómica confirmada.",
            small
        ))

    story.append(
        PageBreak()
    )

    if not all_sar_mode:
        # ---------------------------------------------------------
        # ESTADO GENERAL DEL CULTIVO
        # ---------------------------------------------------------

        story.append(
            Paragraph(
                "2. Estado general del cultivo",
                h2
            )
        )

        story.append(
            Paragraph(
                "Esta sección acompaña el seguimiento de campaña. Resume el comportamiento relativo observado en los lotes clasificados en seguimiento, sin convertir los indicadores en diagnósticos agronómicos.",
                body
            )
        )
        story.append(Spacer(1, 4 * mm))

        if raster is not None and getattr(raster, "get", lambda *_: None)("data") is not None and raster["data"].shape[0] >= 3:
            ndre_img = raster_map(
                raster,
                2,
                gdf=gdf,
                title=""
            )
            ndmi_img = raster_map(
                raster,
                3,
                gdf=gdf,
                title=""
            )

            if ndre_img and ndmi_img:
                # Los mapas de estado general ocupan una página propia.
                # Se muestran uno debajo del otro para que NDRE y NDMI
                # puedan apreciarse correctamente y no compitan con la tabla.
                story.append(
                    Paragraph(
                        "Evidencia óptica · NDRE",
                        ParagraphStyle(
                            "StateMapTitleNDRE",
                            parent=body,
                            fontName=FONT_BOLD,
                            fontSize=10,
                            leading=12,
                            textColor=colors.HexColor(GREEN),
                            spaceAfter=2
                        )
                    )
                )
                story.append(
                    Image(
                        ndre_img,
                        width=175 * mm,
                        height=108 * mm
                    )
                )
                story.append(Spacer(1, 2.5 * mm))
                story.append(
                    Paragraph(
                        "Evidencia óptica · NDMI",
                        ParagraphStyle(
                            "StateMapTitleNDMI",
                            parent=body,
                            fontName=FONT_BOLD,
                            fontSize=10,
                            leading=12,
                            textColor=colors.HexColor(GREEN),
                            spaceAfter=2
                        )
                    )
                )
                story.append(
                    Image(
                        ndmi_img,
                        width=175 * mm,
                        height=108 * mm
                    )
                )
                story.append(Spacer(1, 1.5 * mm))
                story.append(
                    Paragraph(
                        "Las escalas representan valores de los índices. Su lectura debe considerar el cultivo, el momento fenológico y la comparación entre lotes; los colores no constituyen por sí solos un diagnóstico agronómico.",
                        ParagraphStyle(
                            "IndexMapReadingNoteV4",
                            parent=small,
                            fontSize=7.4,
                            leading=9,
                            textColor=colors.HexColor("#5A5F5C")
                        )
                    )
                )

        # La tabla comienza en una página independiente.
        story.append(PageBreak())

        follow_df = df[df["prioridad"] == "SEGUIMIENTO"].copy()
        if not follow_df.empty:
            # Una sola tabla continua: ReportLab distribuye las filas según el
            # espacio real disponible en cada página y repite el encabezado.
            # Evita dividir previamente en mitades, lo que generaba páginas
            # casi vacías cuando cada mitad necesitaba a su vez más de una hoja.
            state_title_style = ParagraphStyle(
                "StateTableTitle",
                parent=body,
                fontName=FONT_BOLD,
                fontSize=11,
                leading=13,
                textColor=colors.HexColor(GREEN),
                spaceAfter=4
            )
            state_note_style = ParagraphStyle(
                "StateNote",
                parent=small,
                fontSize=7.4,
                leading=9.5,
                textColor=colors.HexColor("#5A5F5C")
            )

            story.append(
                Paragraph(
                    "Lotes en seguimiento",
                    state_title_style
                )
            )
            story.append(_state_table(df, body, small, follow_df=follow_df))
            story.append(Spacer(1, 3 * mm))
            story.append(
                Paragraph(
                     "En cada indicador se muestra el valor actual, el promedio del período de referencia y su diferencia. NDMI y NDRE se comparan por separado: un aumento o una disminución en un único intervalo no demuestra mejora, deterioro ni diagnóstico agronómico. Las fichas siguientes desarrollan los lotes con señales relativas bajas.",
                    state_note_style
                )
            )

    if not all_sar_mode:
        story.append(PageBreak())

    # ---------------------------------------------------------
    # LOTES PRIORITARIOS — FICHAS
    # ---------------------------------------------------------

    radar_only_mask = df.apply(_is_radar_only, axis=1)

    priority_df = df[
        df["prioridad"].isin(
            ["PRIORIDAD ALTA", "PRIORIDAD MEDIA"]
        ) & (~radar_only_mask)
    ].copy()

    priority_order = {
        "PRIORIDAD ALTA": 0,
        "PRIORIDAD MEDIA": 1
    }

    priority_df["_orden_prioridad"] = (
        priority_df["prioridad"].map(priority_order).fillna(99)
    )
    priority_df = priority_df.sort_values(
        "_orden_prioridad",
        kind="stable"
    )
    priority_df = _sort_lots_naturally(priority_df)

    radar_df = df[radar_only_mask].copy()
    radar_df["_orden_prioridad"] = (
        radar_df["prioridad"].map(priority_order).fillna(99)
    )
    radar_df = radar_df.sort_values(
        "_orden_prioridad",
        kind="stable"
    )
    radar_df = _sort_lots_naturally(radar_df)

    # ---------------------------------------------------------
    # SECCIÓN DE FICHAS DE PRIORIDADES
    # ---------------------------------------------------------

    if not priority_df.empty:
        story.append(
            Paragraph(
                "3. Fichas de señales relativas",
                h2
            )
        )
        story.append(
            Paragraph(
                "Lotes con señales relativas que merecen contraste y seguimiento. La clasificación no confirma por sí sola deterioro ni una causa agronómica.",
                body
            )
        )
        story.append(Spacer(1, 5 * mm))

    def _priority_config(priority):
        """
        Presenta la prioridad que ya viene calculada por AGIS.
        No crea ni modifica la prioridad.
        """
        if priority == "PRIORIDAD ALTA":
            return {
                "main": "#FF1744",
                "soft": "#FFF0F2",
                "label": "SEÑAL RELATIVA CONVERGENTE",
                "text": "#FFFFFF"
            }

        if priority == "PRIORIDAD MEDIA":
            return {
                "main": "#E8D16A",
                "soft": "#FFF7D9",
                "label": "SEÑAL RELATIVA PARCIAL",
                "text": "#30352F"
            }

        # SEGUIMIENTO: no debe presentarse como PRIORIDAD MEDIA.
        return {
            "main": "#D9DEDB",
            "soft": "#F1F3F2",
            "label": "SEGUIMIENTO",
            "text": "#30352F"
        }

    def _consistency_text(value):
        raw = str(value).strip().lower()
        if raw in ("true", "1", "sí", "si", "yes"):
            return (
                "Convergencia relativa",
                "Ambos indicadores se ubican en el rango relativo bajo del conjunto comparable; no son evidencias independientes ni identifican una causa."
            )
        if raw in ("false", "0", "no"):
            return (
                "Sin convergencia relativa",
                "Los indicadores no presentan una clasificación relativa coincidente."
            )
        return ("Sin conclusión", "No hay evidencia suficiente para expresarlo.")

    def _value_text(row, field):
        return _fmt(row[field]) if field in row.index else "—"

    for idx, (_, row) in enumerate(priority_df.iterrows()):

        if idx > 0:
            story.append(PageBreak())

        cfg = _priority_config(_fmt(row["prioridad"]))
        consistency_label, consistency_note = _consistency_text(
            row["convergencia"] if "convergencia" in row.index else "—"
        )

        # -----------------------------------------------------
        # ENCABEZADO AGIS
        # -----------------------------------------------------
        title_text = (
            f"<b>{_fmt(row['establecimiento'])} · "
            f"{_fmt(row['lote'])}</b>"
        )
        crop_text = f"{_fmt(row['cultivo'])}"

        title_cell = [
            Paragraph(title_text, ParagraphStyle(
                "FichaTitle",
                parent=body,
                fontName=FONT_BOLD,
                fontSize=17,
                leading=20,
                textColor=colors.HexColor(CHARCOAL),
                spaceAfter=2
            )),
            Paragraph(crop_text, ParagraphStyle(
                "FichaCrop",
                parent=body,
                fontName=FONT_REGULAR,
                fontSize=10.5,
                leading=13,
                textColor=colors.HexColor(GREEN)
            ))
        ]

        priority_cell = Paragraph(
            f"<b>{cfg['label']}</b>",
            ParagraphStyle(
                "FichaPriority",
                parent=body,
                fontName=FONT_BOLD,
                fontSize=10.5,
                leading=13,
                alignment=TA_CENTER,
                textColor=colors.HexColor(cfg["text"])
            )
        )

        header = Table(
            [[title_cell, priority_cell]],
            colWidths=[130 * mm, 45 * mm]
        )
        header.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#EAF3EE")),
            ("BACKGROUND", (1, 0), (1, 0), colors.HexColor(cfg["main"])),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#D5DDD8")),
            ("LEFTPADDING", (0, 0), (0, 0), 8),
            ("RIGHTPADDING", (0, 0), (0, 0), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(header)
        story.append(Spacer(1, 2 * mm))

        mode = _monitoring_mode(row)
        if mode == "MONITOREO MIXTO":
            banner_title = "MONITOREO MIXTO"
            banner_subtitle = "Evidencia óptica parcial · radar SAR completa la continuidad del monitoreo"
            banner_color = MIXED_GREEN
        else:
            banner_title = "MONITOREO ÓPTICO"
            banner_subtitle = "Evidencia óptica suficiente · radar SAR como evidencia complementaria"
            banner_color = GREEN

        optical_banner = RoundedTable([[
            Paragraph(
                f"<b>{banner_title}</b><br/>"
                f"<font size='8.2'>{banner_subtitle}</font>",
                ParagraphStyle(
                    "OpticalBanner",
                    parent=body,
                    fontName=FONT_BOLD,
                    fontSize=10.5,
                    leading=13,
                    textColor=colors.white
                )
            )
        ]], colWidths=[175 * mm], radius=7,
        panel_fill=colors.HexColor(banner_color),
        panel_stroke=colors.HexColor(banner_color))
        optical_banner.setStyle(TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(optical_banner)
        story.append(Spacer(1, 3 * mm))

        # -----------------------------------------------------
        # FICHA INTERPRETATIVA — SEIS BLOQUES
        # -----------------------------------------------------
        info = _interpretation_table(row, body, small, radar_only=False)
        story.append(info)
        story.append(Spacer(1, 2 * mm))

        # -----------------------------------------------------
        # INDICADORES — versión simple
        # -----------------------------------------------------
        raw_conv = str(
            row["convergencia"] if "convergencia" in row.index else "—"
        ).strip().lower()

        if raw_conv in ("true", "1", "sí", "si", "yes"):
            consistency_title = "Señal relativa convergente"
            consistency_note = "Ambos indicadores presentan una posición relativa baja; esto no confirma deterioro."
            consistency_bg = "#F0F6F2"
            consistency_color = GREEN
        elif raw_conv in ("false", "0", "no"):
            ndmi_state = str(row.get("senal_relativa_NDMI", "")).strip().upper()
            ndre_state = str(row.get("senal_relativa_NDRE", "")).strip().upper()
            has_inconclusive = (
                "NO CONCLUYENTE" in ndmi_state
                or "NO_CONCLUYENTE" in ndmi_state
                or "NO CONCLUYENTE" in ndre_state
                or "NO_CONCLUYENTE" in ndre_state
                or not ndmi_state
                or not ndre_state
            )
            if has_inconclusive:
                consistency_title = "Convergencia no confirmada"
                consistency_note = "La evidencia no permite establecer una respuesta coincidente."
                consistency_bg = "#F1F3F5"
                consistency_color = CHARCOAL
            else:
                consistency_title = "Señales relativas diferentes"
                consistency_note = "Los indicadores no presentan una clasificación relativa coincidente."
                consistency_bg = "#FFFBE6"
                consistency_color = "#8A7600"
        else:
            consistency_title = "Sin conclusión"
            consistency_note = "No hay evidencia suficiente para compararlas."
            consistency_bg = "#F1F3F5"
            consistency_color = CHARCOAL

        indicator_cells = [
            _priority_comparison_cell(row, "ndre", body),
            _priority_comparison_cell(row, "ndmi", body),
            _stacked_metric_cell(
                "Consistencia", consistency_title,
                consistency_note,
                value_size=8.5, title_size=8.5, note_size=7.5,
                color=consistency_color
            ),
        ]

        indicators = RoundedTable(
            [indicator_cells],
            colWidths=[55 * mm, 55 * mm, 65 * mm],
            rowHeights=[24 * mm],
            radius=8,
            panel_fill=colors.white,
            panel_stroke=colors.HexColor("#D5DDD8")
        )
        indicators.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#F1F8EE")),
            ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#EEF7FB")),
            ("BACKGROUND", (2, 0), (2, 0), colors.HexColor(consistency_bg)),
            ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#DDE3DF")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(indicators)
        story.append(Spacer(1, 2 * mm))

        # -----------------------------------------------------
        # MAPA
        # -----------------------------------------------------
        map_title = RoundedTable([[
            Paragraph(
                "<b>Mapa del lote</b>",
                ParagraphStyle(
                    "MapTitleFinal",
                    parent=body,
                    fontName=FONT_BOLD,
                    fontSize=11,
                    leading=13,
                    textColor=colors.white
                )
            ),
            Paragraph(
                (
                    "SAR VV (base) · NDRE (capa óptica)"
                    + (" · Focos" if "tipo_geometria" in gdf.columns and
                       (gdf["tipo_geometria"].astype(str) != "LOTE").any() else "")
                ),
                ParagraphStyle(
                    "MapLegendFinal",
                    parent=small,
                    fontName=FONT_REGULAR,
                    fontSize=7.2,
                    leading=9,
                    alignment=TA_RIGHT,
                    textColor=colors.white
                )
            )
        ]], colWidths=[48 * mm, 127 * mm], radius=7,
        panel_fill=colors.HexColor(GREEN),
        panel_stroke=colors.HexColor(GREEN))
        map_title.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        map_img = record_map(
            raster,
            gdf,
            row["id_unico"]
        )

        # Mantener el título y el mapa en el mismo bloque evita que el título
        # quede huérfano al pie de una página y el mapa pase a la siguiente.
        map_block = [map_title, Spacer(1, 1 * mm)]
        if map_img:
            map_block.append(
                Image(map_img, width=125 * mm, height=(125 * 104 / 175) * mm)
            )
        else:
            map_block.append(
                Paragraph(
                    "No se pudo generar la visualización para este lote.",
                    ParagraphStyle(
                        "PriorityMapFallback", parent=small, fontSize=7.2,
                        leading=9, textColor=colors.HexColor("#7A7F7C")
                    )
                )
            )
        story.append(KeepTogether(map_block))

    # ---------------------------------------------------------
    # LOTES SIN EVIDENCIA ÓPTICA — FICHAS RADAR
    # ---------------------------------------------------------

    if not radar_df.empty:
        # En modo 100% SAR, el salto de página ya se produjo después del mapa general.
        # Evitamos un segundo salto consecutivo que generaría una página vacía.
        if not all_sar_mode:
            story.append(PageBreak())
        radar_section_number = "2" if all_sar_mode else ("4" if not priority_df.empty else "3")
        story.append(
            Paragraph(
                f"{radar_section_number}. Lotes con monitoreo por radar",
                h2
            )
        )
        story.append(
            Paragraph(
                "Estos lotes no contaron con evidencia óptica válida suficiente "
                "durante el período. AGIS mantiene el seguimiento mediante radar "
                "SAR y presenta la ficha desde esa fuente de evidencia.",
                body
            )
        )
        story.append(Spacer(1, 5 * mm))

        for radar_idx, (_, row) in enumerate(radar_df.iterrows()):

            if radar_idx > 0:
                story.append(PageBreak())

            cfg = _priority_config(
                _fmt(row["prioridad"]) if "prioridad" in row.index else "SEGUIMIENTO"
            )
            sar_info = _sar_metrics(row)

            title_text = (
                f"<b>{_fmt(row['establecimiento'])} · "
                f"{_fmt(row['lote'])}</b>"
            )
            crop_text = f"{_fmt(row['cultivo'])}"

            title_cell = [
                Paragraph(
                    title_text,
                    ParagraphStyle(
                        "RadarFichaTitle",
                        parent=body,
                        fontName=FONT_BOLD,
                        fontSize=17,
                        leading=20,
                        textColor=colors.HexColor(CHARCOAL),
                        spaceAfter=2
                    )
                ),
                Paragraph(
                    crop_text,
                    ParagraphStyle(
                        "RadarFichaCrop",
                        parent=body,
                        fontName=FONT_REGULAR,
                        fontSize=10.5,
                        leading=13,
                        textColor=colors.HexColor("#4A4F4C")
                    )
                )
            ]

            priority_cell = Paragraph(
                f"<b>{cfg['label']}</b>",
                ParagraphStyle(
                    "RadarFichaPriority",
                    parent=body,
                    fontName=FONT_BOLD,
                    fontSize=10.5,
                    leading=13,
                    alignment=TA_CENTER,
                    textColor=colors.HexColor(cfg["text"])
                )
            )

            header = Table(
                [[title_cell, priority_cell]],
                colWidths=[130 * mm, 45 * mm]
            )
            header.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#E3E5E4")),
                ("BACKGROUND", (1, 0), (1, 0), colors.HexColor(cfg["main"])),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#B8BCBA")),
                ("LEFTPADDING", (0, 0), (0, 0), 8),
                ("RIGHTPADDING", (0, 0), (0, 0), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]))
            story.append(header)
            story.append(Spacer(1, 3 * mm))

            radar_banner = Table([[
                Paragraph(
                    "<b>MONITOREO POR RADAR SAR</b><br/>"
                    "<font size='8.2'>Óptica no disponible para este lote · "
                    "seguimiento mediante evidencia radar</font>",
                    ParagraphStyle(
                        "RadarBanner",
                        parent=body,
                        fontName=FONT_BOLD,
                        fontSize=10.5,
                        leading=13,
                        textColor=colors.white
                    )
                )
            ]], colWidths=[175 * mm])

            radar_banner.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#343836")),
                ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#565B58")),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]))
            story.append(radar_banner)
            story.append(Spacer(1, 4 * mm))

            # Ficha SAR exclusiva: no presenta NDMI/NDRE como evidencia disponible.
            info = _interpretation_table(row, body, small, radar_only=True)
            story.append(info)
            story.append(Spacer(1, 2.5 * mm))

            radar_indicator_cells = []
            for label, actual_key, previous_key, delta_key, delta_num_key in [
                ("VV", "vv_actual", "vv_anterior", "delta", "delta_vv_num"),
                ("VH", "vh_actual", "vh_anterior", "delta_vh", "delta_vh_num"),
                ("VH−VV", "ratio_actual", "ratio_anterior", "delta_ratio", "delta_ratio_num"),
            ]:
                direction, direction_color, arrow = _sar_direction(sar_info[delta_num_key])
                delta_value = sar_info[delta_key]
                if delta_value != "—" and sar_info[delta_num_key] is not None and sar_info[delta_num_key] > 0:
                    delta_value = "+" + delta_value
                note = (
                    f"Anterior: {sar_info[previous_key]} dB  "
                    f"<font color='{direction_color}'><b>{arrow} {delta_value} dB</b></font>"
                )
                radar_indicator_cells.append(
                    _stacked_metric_cell(label, f"{sar_info[actual_key]} dB", note,
                                         value_size=14, title_size=8.5, note_size=7.1)
                )

            radar_indicators = Table(
                [radar_indicator_cells],
                colWidths=[58 * mm, 58 * mm, 59 * mm],
                rowHeights=[25 * mm]
            )
            radar_indicators.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#E8EAE9")),
                ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#F0F1F0")),
                ("BACKGROUND", (2, 0), (2, 0), colors.HexColor("#E6E8E7")),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#BFC4C1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#D9DCDA")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]))
            story.append(radar_indicators)
            story.append(Spacer(1, 1.2 * mm))
            story.append(Paragraph(
                f"<font color='#2E7D4F'><b>↑ Aumentó</b></font>  ·  "
                f"<font color='#C43D3D'><b>↓ Disminuyó</b></font>  ·  "
                f"<font color='#777777'><b>→ Sin variación</b></font>  "
                f"<font color='#777777'>| Las flechas indican dirección del cambio, no una condición favorable o desfavorable. "
                f"Adquisición: {sar_info['s1_date']} · {sar_info['comparison']}</font>",
                small
            ))
            story.append(Spacer(1, 2 * mm))

            map_title = RoundedTable([[
                Paragraph(
                    "<b>Mapa SAR del lote</b>",
                    ParagraphStyle(
                        "RadarMapTitleFinal",
                        parent=body,
                        fontName=FONT_BOLD,
                        fontSize=11,
                        leading=13,
                        textColor=colors.white
                    )
                ),
                Paragraph(
                    "La interpretación del período proviene de SAR",
                    ParagraphStyle(
                        "RadarMapLegendFinal",
                        parent=small,
                        fontName=FONT_REGULAR,
                        fontSize=7.2,
                        leading=9,
                        alignment=TA_RIGHT,
                        textColor=colors.white
                    )
                )
            ]], colWidths=[80 * mm, 95 * mm], radius=7,
            panel_fill=colors.HexColor(GREEN),
            panel_stroke=colors.HexColor(GREEN))
            map_title.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            story.append(map_title)

            map_img = radar_record_map(
                raster,
                gdf,
                row["id_unico"]
            )

            if map_img:
                story.append(
                    Image(map_img, width=132 * mm, height=(132 * 104 / 175) * mm)
                )
            else:
                story.append(
                    Paragraph(
                        "No se pudo generar la visualización SAR para este lote.",
                        ParagraphStyle(
                            "RadarMapFallback", parent=small, fontSize=7.2, leading=9,
                            textColor=colors.HexColor("#7A7F7C")
                        )
                    )
                )

            story.append(
                Paragraph(
                    "El mapa representa la retrodispersión VV en dB dentro del lote.",
                    ParagraphStyle(
                        "RadarMapNoteFinal",
                        parent=small,
                        fontName=FONT_REGULAR,
                        fontSize=7.2,
                        leading=9,
                        textColor=colors.HexColor("#5A5F5C"),
                        alignment=TA_LEFT
                    )
                )
            )

    # ---------------------------------------------------------
    # CONSTRUCCIÓN
    # ---------------------------------------------------------

    doc.build(
        story,
        onFirstPage=_footer,
        onLaterPages=_footer
    )

    out.seek(0)

    return out
