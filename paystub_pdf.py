"""Professional PDF paystub generation for the Law Office of Derek G. Medina.

Uses reportlab platypus — same visual language as the invoice PDFs.
"""
import io
import os

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, HRFlowable,
)

NAVY = HexColor("#1f3a5f")
GOLD = HexColor("#b9975b")
DARK = HexColor("#222222")
MUTED = HexColor("#6b7280")
LIGHT_BG = HexColor("#f4f5f7")
BORDER = HexColor("#d9dee5")

FIRM_NAME = "Law Office of Derek G. Medina"

PAGE_W, PAGE_H = letter
MARGIN = 0.75 * inch


def _money(cents):
    try:
        return f"${float(cents) / 100:,.2f}"
    except (TypeError, ValueError):
        return "—"


def build_paystub_pdf(paycheck, employee, ytd, logo_path=None):
    """Return PDF bytes for a paycheck row + employee row + YTD totals dict."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=MARGIN,
        title=f"Paystub {paycheck['pay_date']}",
        author=FIRM_NAME,
    )
    usable = PAGE_W - 2 * MARGIN

    s_title = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=22,
                             textColor=NAVY, leading=26)
    s_firm = ParagraphStyle("firm", fontName="Helvetica-Bold", fontSize=13,
                            textColor=NAVY, leading=16)
    s_h2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=11,
                          textColor=NAVY, leading=14, spaceBefore=14, spaceAfter=6)
    s_body = ParagraphStyle("body", fontName="Helvetica", fontSize=10,
                            textColor=DARK, leading=14)
    s_muted = ParagraphStyle("muted", fontName="Helvetica", fontSize=9,
                             textColor=MUTED, leading=12)
    s_right = ParagraphStyle("right", parent=s_body, alignment=TA_RIGHT)
    s_cell = ParagraphStyle("cell", fontName="Helvetica", fontSize=9.5,
                            textColor=DARK, leading=12)
    s_cell_r = ParagraphStyle("cell_r", parent=s_cell, alignment=TA_RIGHT)
    s_th = ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=9.5,
                          textColor=HexColor("#ffffff"), leading=12)
    s_th_r = ParagraphStyle("th_r", parent=s_th, alignment=TA_RIGHT)

    story = []

    # ---- Header ----
    logo_cell = Paragraph("", s_body)
    if logo_path and os.path.exists(logo_path):
        try:
            logo_cell = Image(logo_path, width=0.9 * inch, height=0.9 * inch)
        except Exception:
            pass
    header = Table(
        [[logo_cell,
          Paragraph(f"<b>{FIRM_NAME}</b><br/><font size=9 color='#6b7280'>210 East Fifth Street, Port Angeles, WA 98362</font>", s_firm),
          Paragraph("<b>PAY STUB</b>", s_title)]],
        colWidths=[1.0 * inch, usable - 2.8 * inch, 1.8 * inch],
    )
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (2, 0), (2, 0), "RIGHT"),
    ]))
    story.append(header)
    story.append(HRFlowable(width="100%", thickness=2, color=GOLD, spaceAfter=12, spaceBefore=8))

    # ---- Employee + period info ----
    if employee["pay_type"] == "hourly":
        pay_desc = f"${employee['pay_rate_cents'] / 100:,.2f}/hour"
    else:
        pay_desc = f"${employee['pay_rate_cents'] / 100:,.2f}/year salary"
    info = Table(
        [[Paragraph(f"<b>Employee:</b> {employee['full_name']}", s_body),
          Paragraph(f"<b>Pay period:</b> {paycheck['pay_period_start']} to {paycheck['pay_period_end']}", s_right)],
         [Paragraph(f"<b>Pay rate:</b> {pay_desc} · {employee['pay_frequency'].capitalize()}", s_body),
          Paragraph(f"<b>Pay date:</b> {paycheck['pay_date']}", s_right)]],
        colWidths=[usable / 2, usable / 2],
    )
    info.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(info)

    # ---- Earnings ----
    story.append(Paragraph("Earnings", s_h2))
    earn_rows = [[Paragraph("<b>Description</b>", s_th),
                   Paragraph("<b>Hours</b>", s_th_r),
                   Paragraph("<b>Current</b>", s_th_r),
                   Paragraph("<b>YTD</b>", s_th_r)]]
    hourly = employee["pay_rate_cents"] / 100 if employee["pay_type"] == "hourly" else None
    if employee["pay_type"] == "hourly":
        earn_rows.append([
            Paragraph("Regular pay", s_cell),
            Paragraph(f"{paycheck['reg_hours']:.2f}", s_cell_r),
            Paragraph(_money(paycheck["reg_hours"] * employee["pay_rate_cents"]), s_cell_r),
            Paragraph("", s_cell_r),
        ])
        if paycheck["ot_hours"]:
            earn_rows.append([
                Paragraph("Overtime pay (1.5x)", s_cell),
                Paragraph(f"{paycheck['ot_hours']:.2f}", s_cell_r),
                Paragraph(_money(paycheck["ot_hours"] * employee["pay_rate_cents"] * 1.5), s_cell_r),
                Paragraph("", s_cell_r),
            ])
    else:
        earn_rows.append([
            Paragraph("Salary", s_cell),
            Paragraph("—", s_cell_r),
            Paragraph(_money(paycheck["gross_cents"]), s_cell_r),
            Paragraph("", s_cell_r),
        ])
    earn_rows.append([
        Paragraph("<b>Total earnings</b>", s_cell),
        Paragraph("", s_cell_r),
        Paragraph(f"<b>{_money(paycheck['gross_cents'])}</b>", s_cell_r),
        Paragraph(f"<b>{_money(ytd['gross'])}</b>", s_cell_r),
    ])
    t = Table(earn_rows, colWidths=[usable * 0.4, usable * 0.2, usable * 0.2, usable * 0.2])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#ffffff")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [HexColor("#ffffff"), LIGHT_BG]),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t)

    # ---- Deductions ----
    story.append(Paragraph("Deductions", s_h2))
    ded_rows = [[Paragraph("<b>Description</b>", s_th),
                  Paragraph("<b>Current</b>", s_th_r),
                  Paragraph("<b>YTD</b>", s_th_r)]]
    ded_items = [
        ("Federal income tax", paycheck["federal_cents"], ytd["federal"]),
        ("Social Security", paycheck["ss_cents"], ytd["ss"]),
        ("Medicare", paycheck["medicare_cents"], ytd["medicare"]),
        ("WA Paid Family & Medical Leave", paycheck["pfml_cents"], ytd["pfml"]),
        ("WA Cares (long-term care)", paycheck["wacares_cents"], ytd["wacares"]),
    ]
    if paycheck["other_deductions_cents"]:
        ded_items.append(("Other deductions", paycheck["other_deductions_cents"], ytd["other"]))
    for label, cur, y in ded_items:
        ded_rows.append([
            Paragraph(label, s_cell),
            Paragraph(_money(cur), s_cell_r),
            Paragraph(_money(y), s_cell_r),
        ])
    total_ded = (paycheck["federal_cents"] + paycheck["ss_cents"] + paycheck["medicare_cents"]
                 + paycheck["pfml_cents"] + paycheck["wacares_cents"] + paycheck["other_deductions_cents"])
    total_ded_ytd = ytd["federal"] + ytd["ss"] + ytd["medicare"] + ytd["pfml"] + ytd["wacares"] + ytd["other"]
    ded_rows.append([
        Paragraph("<b>Total deductions</b>", s_cell),
        Paragraph(f"<b>{_money(total_ded)}</b>", s_cell_r),
        Paragraph(f"<b>{_money(total_ded_ytd)}</b>", s_cell_r),
    ])
    t2 = Table(ded_rows, colWidths=[usable * 0.6, usable * 0.2, usable * 0.2])
    t2.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#ffffff")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [HexColor("#ffffff"), LIGHT_BG]),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t2)

    # ---- Net pay ----
    story.append(Spacer(1, 0.15 * inch))
    net_box = Table(
        [[Paragraph("<b>NET PAY</b>", ParagraphStyle("net", parent=s_h2, textColor=HexColor("#ffffff"), spaceBefore=0)),
          Paragraph(f"<b>{_money(paycheck['net_cents'])}</b>",
                    ParagraphStyle("netamt", fontName="Helvetica-Bold", fontSize=18,
                                   textColor=HexColor("#ffffff"), alignment=TA_RIGHT))]],
        colWidths=[usable * 0.5, usable * 0.5],
    )
    net_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("ROUNDEDCORNERS", [6, 6, 6, 6]),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
    ]))
    story.append(net_box)

    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph(
        "This paystub was generated by the firm's internal payroll system. "
        "Tax rates should be verified annually against IRS and Washington State publications. "
        "This document does not replace professional tax advice.",
        ParagraphStyle("fine", parent=s_muted, fontSize=8, leading=10),
    ))

    doc.build(story)
    return buf.getvalue()
