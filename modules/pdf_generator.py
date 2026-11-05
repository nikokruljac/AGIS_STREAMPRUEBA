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
    PageBreak
)

from .maps import (
    general_priority_map,
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
    labels = ["Prioridad alta", "Prioridad media", "Seguimiento"]

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


def _interpretation_sections(row, radar_only=False):
    """
    Organiza en una lectura comprensible los campos ya calculados por AGIS.
    No genera diagnósticos, no recalcula indicadores ni modifica prioridades.
    """
    def value(field, fallback=""):
        if field not in row.index or pd.isna(row[field]):
            return fallback
        return str(row[field]).strip()

    if radar_only:
        radar = _sar_metrics(row)
        radar_line = (
            f"VV actual: {radar['vv_actual']} dB · "
            f"VV anterior: {radar['vv_anterior']} dB · "
            f"variación: {radar['delta']} dB."
        )
        if radar["comparison"] not in ("—", ""):
            radar_line += f" Comparación: {radar['comparison']}."
        return [
            (
                "Evidencia disponible",
                "No hubo evidencia óptica válida suficiente para este lote durante el período. AGIS mantiene el seguimiento mediante observaciones Sentinel-1 SAR."
            ),
            ("Lectura del radar", radar_line),
            (
                "Interpretación y alcance",
                "La variación de la señal VV aporta continuidad al monitoreo, pero por sí sola no permite establecer una causa agronómica ni inferir el estado de NDMI o NDRE."
            ),
            ("Qué conviene verificar", value("que_revisar", "Mantener el seguimiento y contrastar la evolución del cultivo con su contexto fenológico.")),
            ("Limitaciones", value("limitaciones", "La interpretación se limita a la evidencia radar disponible y a su comparabilidad temporal.")),
        ]

    ndmi = value("senal_relativa_NDMI", "NO_INFORMADA").upper()
    ndre = value("senal_relativa_NDRE", "NO_INFORMADA").upper()
    conv = value("convergencia", "").lower()
    ndmi_label = _state_signal(row, "senal_relativa_NDMI", "ndmi")
    ndre_label = _state_signal(row, "senal_relativa_NDRE", "ndre")

    if conv in ("true", "1", "sí", "si", "yes"):
        relation = (
            f"Hay convergencia: NDMI ({ndmi_label.lower()}) y NDRE "
            f"({ndre_label.lower()}) presentan una respuesta relativa coincidente. "
            "Esto refuerza la consistencia de la señal, pero no identifica por sí solo su causa."
        )
    elif conv in ("false", "0", "no"):
        relation = (
            f"No hay convergencia entre los indicadores: NDMI ({ndmi_label.lower()}) "
            f"y NDRE ({ndre_label.lower()}) no muestran una respuesta coincidente. "
            "La señal debe leerse de manera diferenciada, sin asumir un efecto común."
        )
    else:
        relation = (
            f"La relación entre indicadores no puede establecerse con la información disponible "
            f"(NDMI: {ndmi_label.lower()}; NDRE: {ndre_label.lower()})."
        )

    sar = _sar_metrics(row)
    sar_available = _is_true(value("SAR_disponible", "false"))
    if not sar_available:
        radar_text = "No hay evidencia SAR disponible para complementar esta lectura."
    elif sar["delta"] != "—":
        radar_text = (
            f"VV actual: {sar['vv_actual']} dB; anterior: {sar['vv_anterior']} dB; "
            f"variación informada: {sar['delta']} dB."
        )
        if sar["comparison"] not in ("—", ""):
            radar_text += f" {sar['comparison']}."
        radar_text += " El radar se presenta como evidencia complementaria; no se fuerza una equivalencia con NDMI o NDRE."
    else:
        radar_text = "Hay disponibilidad SAR, pero el CSV no aporta una variación VV interpretable para esta ficha."

    fenologia = value("fenologia_etapa", "")
    dias = value("dias_desde_siembra", "")
    phenology_text = f"Etapa fenológica: {fenologia}." if fenologia else ""
    if dias:
        phenology_text += f" Días desde siembra: {dias}."
    observation = value("hallazgo_agis", "AGIS no informó un hallazgo textual.")
    # El CSV puede incluir dentro del hallazgo una oración sobre SAR.
    # Se separa para que esa evidencia aparezca una sola vez en su bloque propio.
    observation = re.sub(
        r"\s*La señal radar .*?(?=\s*Última observación S1 válida:|$)",
        "",
        observation,
        flags=re.IGNORECASE,
    ).strip()

    alternatives = value("hipotesis_alternativas", "")
    limits = value("limitaciones", "")
    scope = " ".join(part for part in (alternatives, limits) if part)
    if not scope:
        scope = "La señal satelital no determina por sí sola una causa agronómica."

    return [
        ("Qué observamos", observation),
        ("Cómo se relacionan las evidencias", relation),
        ("Qué aporta el radar", radar_text),
        ("Qué significa para el seguimiento", value("hipotesis_agis", "—")),
        ("Qué conviene verificar", value("que_revisar", "—")),
        ("Alcance de la interpretación", scope),
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

def _temporal_trend_cell(row, index_name, trend_cell_style):
    """Muestra solo la variación temporal, sin fechas ni metadatos secundarios."""
    suffix = index_name.upper()
    delta_field = f"delta_{index_name.lower()}"
    state_field = f"estado_comparacion_{suffix}"
    state = str(row[state_field]).strip().upper() if state_field in row.index and pd.notna(row[state_field]) else ""
    value = row[delta_field] if delta_field in row.index else None
    if state.startswith("NO_") or value is None or pd.isna(value):
        label = "Sin dato óptico" if _is_radar_only(row) else "Sin dato"
        return Paragraph(f"<font color='#777F7A'><b>— {label}</b></font>", trend_cell_style)
    try:
        delta = float(value)
    except (TypeError, ValueError):
        return Paragraph("<font color='#777F7A'><b>—</b></font>", trend_cell_style)
    if delta > 0:
        arrow, color_hex = "↑", "#25834A"
    elif delta < 0:
        arrow, color_hex = "↓", "#C43D42"
    else:
        arrow, color_hex = "→", "#626A66"
    return Paragraph(f"<font color='{color_hex}'><b>{arrow} {delta:+.3f}</b></font>", trend_cell_style)


def _state_table(df, body, small):
    follow_df = df[df["prioridad"] == "SEGUIMIENTO"].copy()
    if follow_df.empty:
        return None

    header_style = ParagraphStyle(
        "AGIS_TableHeaderWhite",
        parent=small,
        textColor=colors.white,
        fontName=FONT_BOLD,
        fontSize=6.4,
        leading=7,
    )

    trend_cell_style = ParagraphStyle(
        "AGIS_TemporalTrendCell",
        parent=small,
        fontSize=6.8,
        leading=7.2,
        spaceAfter=0,
    )

    rows = [[
        Paragraph("ESTABLECIMIENTO", header_style),
        Paragraph("LOTE", header_style),
        Paragraph("MODALIDAD", header_style),
        Paragraph("AGUA VEGETAL<br/>NDMI · EVOLUCIÓN", header_style),
        Paragraph("CLOROFILA<br/>NDRE · EVOLUCIÓN", header_style),
        Paragraph("ESTADO GENERAL", header_style),
    ]]
    states = []

    for _, row in follow_df.iterrows():
        mode = _monitoring_mode(row)
        estado = _general_state(row)
        states.append(estado.lower())

        rows.append([
            Paragraph(f"<b>{_fmt(row['establecimiento'])}</b>", small),
            Paragraph(f"<b>{_fmt(row['lote'])}</b>", small),
            Paragraph(mode.replace("MONITOREO ", ""), small),
            _temporal_trend_cell(row, "ndmi", trend_cell_style),
            _temporal_trend_cell(row, "ndre", trend_cell_style),
            Paragraph(estado, small),
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
        ("TOPPADDING", (0, 0), (-1, -1), 1.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.2),
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
    """
    Extrae los valores SAR que ya vienen documentados en el CSV.
    No recalcula SAR: solamente presenta la evidencia ya generada por AGIS.
    """
    texts = []
    for field in (
        "hallazgo_agis",
        "fundamento_interpretacion",
        "hipotesis_agis",
        "que_revisar",
    ):
        if field in row.index and pd.notna(row[field]):
            texts.append(str(row[field]))
    text = " ".join(texts)

    def extract(pattern):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        return match.group(1).replace(",", ".") if match else "—"

    vv_actual = extract(r"VV actual:\s*([-+]?\d+(?:[.,]\d+)?)\s*dB")
    vv_anterior = extract(r"VV anterior:\s*([-+]?\d+(?:[.,]\d+)?)\s*dB")
    delta = extract(r"ΔVV:\s*([-+]?\d+(?:[.,]\d+)?)\s*dB")
    comparison = extract(r"Comparación:\s*([^.]+)")
    s1_date = _fmt(row["ultima_pasada_S1"]) if "ultima_pasada_S1" in row.index else "—"

    return {
        "vv_actual": vv_actual,
        "vv_anterior": vv_anterior,
        "delta": delta,
        "comparison": comparison,
        "s1_date": s1_date,
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

        story.append(
            Paragraph(
                f"Última observación satelital: {latest_s2}",
                body
            )
        )

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
            _stacked_metric_cell("PRIORIDAD ALTA", high, value_size=21),
            _stacked_metric_cell("PRIORIDAD MEDIA", medium, value_size=21),
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
        "<b>Resumen de prioridades</b>",
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
    story.append(Spacer(1, 5 * mm))

    # 2) Distribución: gráfico grande y protagonista.
    donut = Image(
        _priority_donut(high, medium, follow),
        width=108 * mm,
        height=73 * mm
    )

    donut_title = Paragraph(
        "<b>Distribución de prioridades</b>",
        ParagraphStyle(
            "PriorityDonutTitleFinal",
            parent=body,
            fontName=FONT_BOLD,
            fontSize=12,
            leading=14,
            textColor=colors.HexColor(GREEN),
            alignment=TA_CENTER
        )
    )

    donut_note = Paragraph(
        "La distribución permite identificar rápidamente dónde concentrar la atención.",
        ParagraphStyle(
            "PriorityDonutNoteFinal",
            parent=small,
            fontSize=8.2,
            leading=10,
            alignment=TA_CENTER
        )
    )

    donut_panel = RoundedTable(
        [[donut_title], [donut], [donut_note]],
        colWidths=[175 * mm],
        radius=8,
        panel_fill=colors.white,
        panel_stroke=colors.HexColor("#D5DDD8")
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
    area_panel = RoundedTable(
        [[
            Paragraph(
                "<b>SUPERFICIE EN PRIORIDAD ALTA</b>",
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

    story.append(
        Paragraph(
            "AGIS organiza la evidencia disponible para señalar qué merece atención y por qué. La evaluación agronómica final corresponde al profesional.",
            body
        )
    )
    story.append(
        PageBreak()
    )

    # ---------------------------------------------------------
    # MAPA GENERAL
    # ---------------------------------------------------------

    story.append(
        Paragraph(
            "1. Dónde prestar atención",
            h2
        )
    )

    story.append(
        Image(
            general_priority_map(gdf),
            width=175 * mm,
            height=150 * mm
        )
    )

    story.append(
        Spacer(1, 3 * mm)
    )

    story.append(
        Paragraph(
            "La distribución de prioridades permite identificar "
            "rápidamente dónde concentrar la recorrida.",
            small
        )
    )

    story.append(
        PageBreak()
    )

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
            "Esta sección acompaña el seguimiento de campaña. Resume el comportamiento relativo observado en los lotes que no requieren una ficha de alerta, sin convertir los indicadores en diagnósticos agronómicos.",
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
                    "Evidencia óptica relacionada con Clorofila · NDRE",
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
                    height=105 * mm
                )
            )
            story.append(Spacer(1, 3 * mm))
            story.append(
                Paragraph(
                    "Evidencia óptica relacionada con Agua Vegetal · NDMI",
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
                    height=105 * mm
                )
            )

    # La tabla comienza en una página independiente.
    story.append(PageBreak())

    state_table = _state_table(df, body, small)
    if state_table is not None:
        story.append(
            Paragraph(
                "Lotes en seguimiento",
                ParagraphStyle(
                    "StateTableTitle",
                    parent=body,
                    fontName=FONT_BOLD,
                    fontSize=11,
                    leading=13,
                    textColor=colors.HexColor(GREEN),
                    spaceAfter=3
                )
            )
        )
        story.append(state_table)
        story.append(Spacer(1, 3 * mm))
        story.append(
            Paragraph(
                "Las flechas muestran la variación temporal de cada índice respecto de su referencia anterior (NDMI y NDRE por separado). Verde = aumento; rojo = disminución. Se informa la cantidad de observaciones y el período de referencia. La dirección del cambio no constituye por sí sola una mejora, deterioro ni diagnóstico agronómico. Los lotes con prioridad alta o media se desarrollan en las fichas de alerta.",
                ParagraphStyle(
                    "StateNote",
                    parent=small,
                    fontSize=7.2,
                    leading=9,
                    textColor=colors.HexColor("#5A5F5C")
                )
            )
        )

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

    radar_df = df[radar_only_mask].copy()
    radar_df["_orden_prioridad"] = (
        radar_df["prioridad"].map(priority_order).fillna(99)
    )
    radar_df = radar_df.sort_values(
        "_orden_prioridad",
        kind="stable"
    )

    # ---------------------------------------------------------
    # SECCIÓN DE FICHAS DE PRIORIDADES
    # ---------------------------------------------------------

    if not priority_df.empty:
        story.append(
            Paragraph(
                "3. Fichas de prioridades",
                h2
            )
        )
        story.append(
            Paragraph(
                "Lotes que requieren atención priorizada según la evidencia analizada por AGIS.",
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
                "label": "PRIORIDAD ALTA",
                "text": "#FFFFFF"
            }

        if priority == "PRIORIDAD MEDIA":
            return {
                "main": "#E8D16A",
                "soft": "#FFF7D9",
                "label": "PRIORIDAD MEDIA",
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
                "Sí hay consistencia",
                "NDMI y NDRE muestran una tendencia similar."
            )
        if raw in ("false", "0", "no"):
            return (
                "Señales no coincidentes",
                "NDMI y NDRE no muestran la misma tendencia."
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
        story.append(Spacer(1, 4 * mm))

        # -----------------------------------------------------
        # INDICADORES — versión simple
        # -----------------------------------------------------
        ndre = _fmt2(row["ndre"]) if "ndre" in row.index else "—"
        ndmi = _fmt2(row["ndmi"]) if "ndmi" in row.index else "—"
        sar = _fmt(row["SAR_disponible"]) if "SAR_disponible" in row.index else "—"

        ndmi_rel = _fmt(row["senal_relativa_NDMI"]) if "senal_relativa_NDMI" in row.index else "—"
        ndre_rel = _fmt(row["senal_relativa_NDRE"]) if "senal_relativa_NDRE" in row.index else "—"

        raw_conv = str(
            row["convergencia"] if "convergencia" in row.index else "—"
        ).strip().lower()

        if raw_conv in ("true", "1", "sí", "si", "yes"):
            consistency_title = "Las señales coinciden"
            consistency_note = "NDMI y NDRE apuntan en la misma dirección."
            consistency_bg = "#F0F6F2"
            consistency_color = GREEN
        elif raw_conv in ("false", "0", "no"):
            consistency_title = "Las señales no coinciden"
            consistency_note = "NDMI y NDRE no apuntan en la misma dirección."
            consistency_bg = "#FFFBE6"
            consistency_color = "#8A7600"
        else:
            consistency_title = "Sin conclusión"
            consistency_note = "No hay evidencia suficiente para compararlas."
            consistency_bg = "#F1F3F5"
            consistency_color = CHARCOAL

        indicator_cells = [
            _stacked_metric_cell(
                "NDRE", ndre,
                ndre_rel.replace("_", " ").title(),
                value_size=16, title_size=8.5, note_size=7.5
            ),
            _stacked_metric_cell(
                "NDMI", ndmi,
                ndmi_rel.replace("_", " ").title(),
                value_size=16, title_size=8.5, note_size=7.5
            ),
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
        story.append(Spacer(1, 3 * mm))

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
        story.append(map_title)

        map_img = record_map(
            raster,
            gdf,
            row["id_unico"]
        )

        if map_img:
            story.append(
                Image(
                    map_img,
                    width=175 * mm,
                    height=104 * mm
                )
            )
        else:
            story.append(
                Paragraph(
                    "No se pudo generar la visualización para este lote.",
                    ParagraphStyle(
                        "PriorityMapFallback", parent=small, fontSize=7.2,
                        leading=9, textColor=colors.HexColor("#7A7F7C")
                    )
                )
            )

        # Small supporting line, only when SAR is available.
        if str(sar).strip().lower() in ("true", "1", "sí", "si", "yes"):
            story.append(
                Paragraph(
                    ("Radar SAR como base de continuidad · NDRE donde existe cobertura óptica."
                     if mode == "MONITOREO MIXTO"
                     else "Radar SAR disponible como evidencia complementaria."),
                    ParagraphStyle(
                        "SARNote",
                        parent=small,
                        fontName=FONT_REGULAR,
                        fontSize=7.2,
                        leading=9,
                        textColor=colors.HexColor("#5C665F"),
                        alignment=TA_LEFT
                    )
                )
            )



    # ---------------------------------------------------------
    # LOTES SIN EVIDENCIA ÓPTICA — FICHAS RADAR
    # ---------------------------------------------------------

    if not radar_df.empty:
        story.append(PageBreak())
        radar_section_number = "4" if not priority_df.empty else "3"
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
            story.append(Spacer(1, 4 * mm))

            radar_indicator_cells = [
                _stacked_metric_cell("VV actual", f"{sar_info['vv_actual']} dB", value_size=15, title_size=8.5),
                _stacked_metric_cell("VV anterior", f"{sar_info['vv_anterior']} dB", f"ΔVV: {sar_info['delta']} dB", value_size=15, title_size=8.5, note_size=7.5),
                _stacked_metric_cell("Última observación S1", sar_info['s1_date'], sar_info['comparison'], value_size=11, title_size=8.5, note_size=7.5),
            ]

            radar_indicators = Table(
                [radar_indicator_cells],
                colWidths=[58 * mm, 58 * mm, 59 * mm],
                rowHeights=[24 * mm]
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
            story.append(Spacer(1, 3 * mm))

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
                    Image(
                        map_img,
                        width=175 * mm,
                        height=104 * mm
                    )
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
                    "El mapa muestra la señal SAR disponible para mantener la referencia espacial del lote durante la falta de cobertura óptica.",
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
