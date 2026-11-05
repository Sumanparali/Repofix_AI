from __future__ import annotations

from io import BytesIO
from xml.sax.saxutils import escape


def build_pdf_report(identifier: int, job, report: dict) -> bytes:
    """Create a polished, printable PDF for a completed repository scan."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        BaseDocTemplate, Frame, KeepTogether, PageTemplate, Paragraph, Spacer, Table, TableStyle,
    )

    buffer = BytesIO()
    navy = colors.HexColor("#071321")
    amber = colors.HexColor("#F4B867")
    ink = colors.HexColor("#172033")
    muted = colors.HexColor("#667085")
    line = colors.HexColor("#D9DEE7")
    danger = colors.HexColor("#B42318")

    def header_footer(canvas, doc):
        canvas.saveState()
        width, height = A4
        canvas.setFillColor(navy)
        canvas.rect(0, height - 24 * mm, width, 24 * mm, fill=1, stroke=0)
        canvas.setFillColor(amber)
        canvas.setFont("Helvetica-Bold", 15)
        canvas.drawString(18 * mm, height - 15 * mm, "RepoFix")
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica", 8)
        canvas.drawString(43 * mm, height - 15 * mm, "LOCAL REPOSITORY SCAN")
        canvas.setFillColor(muted)
        canvas.setFont("Helvetica", 8)
        canvas.drawString(18 * mm, 12 * mm, f"Analysis #{identifier}")
        canvas.setFillColor(ink)
        canvas.drawRightString(width - 18 * mm, 12 * mm, f"Page {doc.page}")
        canvas.restoreState()

    doc = BaseDocTemplate(
        buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=32 * mm, bottomMargin=20 * mm,
        title=report.get("title", "RepoFix analysis report"), author="RepoFix",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="report")
    doc.addPageTemplates(PageTemplate(id="report", frames=[frame], onPage=header_footer))

    base = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "Title", parent=base["Title"], fontName="Helvetica-Bold", fontSize=24,
        leading=29, textColor=navy, alignment=0, spaceAfter=7 * mm,
    )
    heading = ParagraphStyle(
        "Heading", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=13,
        leading=17, textColor=navy, spaceBefore=6 * mm, spaceAfter=3 * mm,
    )
    body = ParagraphStyle(
        "Body", parent=base["BodyText"], fontName="Helvetica", fontSize=9.5,
        leading=14, textColor=ink,
    )
    small = ParagraphStyle("Small", parent=body, fontSize=8, leading=11, textColor=muted)
    badge = ParagraphStyle(
        "Badge", parent=small, fontName="Helvetica-Bold", textColor=danger,
        alignment=TA_RIGHT,
    )

    def safe(value) -> str:
        return escape(str(value or "Not available"))

    story = [
        Paragraph(safe(report.get("title", "RepoFix analysis report")), title_style),
        Table(
            [
                [Paragraph("REPOSITORY", small), Paragraph("STATUS", small)],
                [Paragraph(safe(job.repository), body), Paragraph(safe(job.status).upper(), badge)],
                [Paragraph("REQUEST", small), Paragraph("ENVIRONMENT", small)],
                [
                    Paragraph(safe(report.get("issue", job.issue)), body),
                    Paragraph(
                        f"{safe(report.get('language', 'Unknown'))} / "
                        f"{safe(report.get('framework', 'Not detected'))}", body,
                    ),
                ],
            ],
            colWidths=[doc.width * 0.68, doc.width * 0.32],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F6F8FB")),
                ("BOX", (0, 0), (-1, -1), 0.7, line),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, line),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]),
        ),
        Paragraph("Executive summary", heading),
        Paragraph(safe(report.get("outcome", "No findings were recorded.")), body),
        Spacer(1, 2 * mm),
        Table(
            [[Paragraph("VALIDATION", small), Paragraph(safe(report.get("validation")), body)]],
            colWidths=[32 * mm, doc.width - 32 * mm],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFF7EA")),
                ("BOX", (0, 0), (-1, -1), 0.7, amber),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]),
        ),
    ]

    findings = report.get("findings", [])
    story.append(Paragraph(f"Findings ({len(findings)})", heading))
    if findings:
        for number, item in enumerate(findings, 1):
            location = item.get("path", "Repository")
            if item.get("line"):
                location += f":{item['line']}"
            story.append(KeepTogether([
                Table(
                    [[
                        Paragraph(f"{number}. {safe(item.get('title', 'Finding'))}", body),
                        Paragraph(safe(str(item.get('severity', 'info')).upper()), badge),
                    ]],
                    colWidths=[doc.width - 31 * mm, 31 * mm],
                    style=TableStyle([
                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F6F8FB")),
                        ("LINEBELOW", (0, 0), (-1, -1), 0.5, line),
                        ("LEFTPADDING", (0, 0), (-1, -1), 8),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ]),
                ),
                Paragraph(f"<b>{safe(location)}</b><br/>{safe(item.get('detail', ''))}", small),
                Spacer(1, 3 * mm),
            ]))
    else:
        story.append(Paragraph("No static-analysis findings were recorded.", body))

    def bullet_section(name: str, values: list[str]):
        story.append(Paragraph(name, heading))
        if not values:
            story.append(Paragraph("None recorded.", body))
        else:
            for value in values:
                story.append(Paragraph(f"- {safe(value)}", body))
                story.append(Spacer(1, 1.2 * mm))

    bullet_section("Relevant files", report.get("relevant_files", []))
    bullet_section("Recommendations", report.get("recommendations", []))
    doc.build(story)
    return buffer.getvalue()
