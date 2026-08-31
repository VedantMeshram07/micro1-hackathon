"""
Renders the same report data render_business_report() uses into a polished
PDF via ReportLab — built directly from the structured report dict, NOT
from the markdown text. ReportLab's built-in fonts don't reliably render
emoji (💰⚠️✅📄👥❓, used throughout the markdown as section markers) —
confirmed via the pdf skill's own documented gotcha about missing glyphs
rendering as solid boxes. Section headers use color/weight instead.
"""

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
)
from reportlab.lib.enums import TA_LEFT

BRASS = colors.HexColor("#8A6D1F")
SAGE = colors.HexColor("#3E6459")
BRICK = colors.HexColor("#8F3330")
MUTED = colors.HexColor("#5A5A5A")
INK = colors.HexColor("#1A1A1A")


def _verdict_color(score):
    if score is None:
        return MUTED
    try:
        s = float(score)
    except (TypeError, ValueError):
        return MUTED
    return SAGE if s >= 8 else (BRASS if s >= 5 else BRICK)


def _styles():
    base = getSampleStyleSheet()
    styles = {
        "title": ParagraphStyle("title", parent=base["Title"], fontSize=20, spaceAfter=4),
        "verdict": ParagraphStyle("verdict", parent=base["Heading1"], fontSize=15, spaceAfter=10),
        "section": ParagraphStyle("section", parent=base["Heading2"], fontSize=13,
                                   spaceBefore=16, spaceAfter=6, textColor=INK),
        "body": ParagraphStyle("body", parent=base["Normal"], fontSize=10, leading=14, spaceAfter=8),
        "bullet_point": ParagraphStyle("bullet_point", parent=base["Normal"], fontSize=10,
                                        leading=13, spaceAfter=2, leftIndent=0, alignment=TA_LEFT),
        "bullet_evidence": ParagraphStyle("bullet_evidence", parent=base["Normal"], fontSize=8.5,
                                           leading=11, spaceAfter=8, leftIndent=14,
                                           textColor=MUTED, fontName="Courier"),
        "disclosure": ParagraphStyle("disclosure", parent=base["Normal"], fontSize=8,
                                      leading=11, textColor=MUTED, spaceAfter=6),
        "badge_pass": ParagraphStyle("badge_pass", parent=base["Normal"], fontSize=9,
                                      textColor=SAGE, spaceAfter=10),
        "badge_fail": ParagraphStyle("badge_fail", parent=base["Normal"], fontSize=9,
                                      textColor=BRICK, spaceAfter=10),
    }
    return styles


def _esc(text) -> str:
    """ReportLab Paragraphs interpret text as a light XML dialect — escape
    raw evidence/summary text (which can contain characters like & or <
    from code snippets) so it doesn't break layout or get silently dropped.

    Also normalizes U+2011 (non-breaking hyphen) to a plain ASCII hyphen —
    confirmed via a real generated report that some models emit this
    specifically in compound words ("high\u2011entropy", "react\u2011dom"),
    and ReportLab's default font has no glyph for it, rendering as a
    visible black box in the PDF. Verified via a controlled test: plain
    hyphens, en dashes, and em dashes all render fine; only U+2011 breaks."""
    if text is None:
        return ""
    return (
        str(text)
        .replace("\u2011", "-")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def render_pdf_report(report: dict, repo_name: str, output_path: str) -> str:
    styles = _styles()
    doc = SimpleDocTemplate(
        output_path, pagesize=letter,
        topMargin=0.75 * inch, bottomMargin=0.75 * inch,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
    )
    story = []

    score = report.get("score")
    remediation = report.get("remediation_estimate", {})
    total_hours = remediation.get("total_hours_estimate")
    low, high = remediation.get("range_low"), remediation.get("range_high")
    integrity = report.get("integrity_check", {})

    story.append(Paragraph(f"Due-Diligence Report: {_esc(repo_name)}", styles["title"]))

    if integrity:
        if integrity.get("passed"):
            story.append(Paragraph(
                "Self-audit passed &mdash; every finding this report gathered is cited below.",
                styles["badge_pass"]))
        else:
            n = len(integrity.get("violations", []))
            story.append(Paragraph(
                f"Self-audit flagged {n} finding(s) present in evidence but not fully reflected below.",
                styles["badge_fail"]))

    verdict_color = _verdict_color(score)
    verdict_text = f"Verdict: {score}/10"
    if total_hours is not None:
        verdict_text += f" &mdash; Est. {low}-{high} engineer-hours to acquisition-ready"
    story.append(Paragraph(verdict_text, ParagraphStyle(
        "verdict_colored", parent=styles["verdict"], textColor=verdict_color)))
    story.append(Paragraph(_esc(report.get("summary", "")), styles["body"]))
    story.append(HRFlowable(width="100%", color=colors.HexColor("#CCCCCC"), spaceAfter=8))

    if remediation.get("line_items"):
        story.append(Paragraph("Remediation Cost Estimate", styles["section"]))
        table_data = [["Item", "Hours", "Basis"]]
        for item in remediation["line_items"]:
            table_data.append([
                Paragraph(_esc(item["item"]), styles["body"]),
                str(item["hours"]),
                Paragraph(_esc(item["basis"]), ParagraphStyle(
                    "basis", parent=styles["body"], fontSize=8.5, textColor=MUTED)),
            ])
        t = Table(table_data, colWidths=[2.6 * inch, 0.6 * inch, 3.3 * inch])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDEAE2")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(t)
        story.append(Paragraph(f"<b>Total: {total_hours} hours (range: {low}-{high}h)</b>",
                                ParagraphStyle("total", parent=styles["body"], spaceBefore=6)))
        story.append(Paragraph(_esc(remediation.get("disclosure", "")), styles["disclosure"]))

    def _bullet_section(title, items, point_key="point", evidence_key="evidence"):
        if not items:
            return
        story.append(Paragraph(title, styles["section"]))
        for it in items:
            story.append(Paragraph(f"&bull; {_esc(it.get(point_key, ''))}", styles["bullet_point"]))
            ev = it.get(evidence_key)
            if ev:
                story.append(Paragraph(_esc(ev), styles["bullet_evidence"]))

    _bullet_section("Risks", report.get("risks", []))
    _bullet_section("Strengths", report.get("strengths", []))

    raw = report.get("raw_evidence", {})
    license_check = raw.get("license_check", {})
    if license_check:
        story.append(Paragraph("License", styles["section"]))
        proj = license_check.get("project_license", {})
        dep = license_check.get("dependency_licenses", {})
        story.append(Paragraph(
            f"Project license: <b>{_esc(proj.get('license') or 'not found')}</b>", styles["body"]))
        if dep.get("attempted"):
            story.append(Paragraph(
                f"Dependencies checked: {dep.get('checked', 0)}, "
                f"conflicts: {len(dep.get('conflicts', []))}, "
                f"unknown license: {dep.get('unknown_count', 0)}", styles["body"]))
            for c in dep.get("conflicts", []):
                story.append(Paragraph(
                    f"&bull; {_esc(c['package'])} &mdash; {_esc(c['license'])} (copyleft)",
                    styles["bullet_point"]))

    ownership = raw.get("ownership_risk", {})
    if ownership.get("attempted") and not ownership.get("error"):
        story.append(Paragraph("Ownership &amp; Continuity Risk", styles["section"]))
        days = ownership.get("days_since_last_push")
        share = ownership.get("top_contributor_share_pct")
        count = ownership.get("contributor_count")
        line = f"{count} contributor(s), top contributor: {share}% of commits"
        if days is not None:
            line += f", last push: {days} days ago"
        story.append(Paragraph(line, styles["body"]))
        if ownership.get("bus_factor_flag"):
            story.append(Paragraph(
                "Bus-factor risk: commit history is highly concentrated in one "
                "contributor and the repo has gone quiet.",
                ParagraphStyle("risk_note", parent=styles["body"], textColor=BRICK)))

    _bullet_section("Could Not Verify", [{"point": u} for u in report.get("unverifiable", [])])

    story.append(Spacer(1, 12))
    story.append(HRFlowable(width="100%", color=colors.HexColor("#CCCCCC")))
    story.append(Paragraph(
        "Every claim above is backed by evidence in the full JSON report.",
        styles["disclosure"]))

    doc.build(story)
    return output_path
