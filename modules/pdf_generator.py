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
                    Image(map_img, width=145 * mm, height=(145 * 104 / 175) * mm)
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
