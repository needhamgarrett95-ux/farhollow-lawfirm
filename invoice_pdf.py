"""Professional PDF invoice generation for the Law Office of Derek G. Medina.

Uses reportlab platypus for precise, print-ready layout.
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


def _val(row, key):
    """Safe accessor for sqlite3.Row (which has no .get())."""
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return None


def _money(v):
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return "—"


def build_invoice_pdf(invoice, items, total, logo_path=None):
    """Return PDF bytes for the given invoice row, item rows, and total."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=MARGIN,
        title=f"Invoice {invoice['invoice_number']}",
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

    # ---- Header: logo + firm name (left), INVOICE (right) ----
    logo_cell = Paragraph("", s_body)
    if logo_path and os.path.exists(logo_path):
        try:
            logo_img = Image(logo_path, width=1.35 * inch, height=0.63 * inch)
            logo_img.hAlign = "LEFT"
            logo_cell = logo_img
        except Exception:
            pass
    left_stack = Table(
        [[logo_cell],
         [Paragraph(f"<b>{FIRM_NAME}</b>", s_firm)]],
        colWidths=[usable * 0.62])
    left_stack.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    header = Table([[left_stack, Paragraph(
        f"<font color=\"{NAVY.hexval()}\"><b>INVOICE</b></font>",
        ParagraphStyle("inv_title", parent=s_title, alignment=TA_RIGHT))]],
        colWidths=[usable * 0.62, usable * 0.38])
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(header)
    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", thickness=2, color=GOLD))
    story.append(Spacer(1, 14))

    # ---- Invoice meta + Bill-to (two columns) ----
    inv_no = invoice["invoice_number"]
    meta_rows = [
        [Paragraph("<b>Invoice number</b>", s_body),
         Paragraph(inv_no, s_right)],
        [Paragraph("<b>Issue date</b>", s_body),
         Paragraph(str(invoice["issue_date"] or "—"), s_right)],
        [Paragraph("<b>Due date</b>", s_body),
         Paragraph(str(invoice["due_date"] or "—"), s_right)],
        [Paragraph("<b>Status</b>", s_body),
         Paragraph(str(invoice["status"] or "").capitalize(), s_right)],
    ]
    meta = Table(meta_rows, colWidths=[usable * 0.20, usable * 0.36])
    meta.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))

    bill_lines = [
        f"<b>{invoice['first_name']} {invoice['last_name']}</b>",
    ]
    if _val(invoice, "address"):
        bill_lines.append(str(invoice["address"]))
    contact = " ".join(
        x for x in [_val(invoice, "email"), _val(invoice, "phone")] if x)
    if contact:
        bill_lines.append(contact)
    bill = Table(
        [[Paragraph("<b>Bill to</b>", s_h2)],
         [Paragraph("<br/>".join(bill_lines), s_body)]],
        colWidths=[usable * 0.5])
    bill.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))

    top = Table([[bill, meta]], colWidths=[usable * 0.44, usable * 0.56])
    top.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(top)
    story.append(Spacer(1, 10))

    # ---- Line items ----
    story.append(Paragraph("Services", s_h2))

    col_date = 0.95 * inch
    col_hours = 0.65 * inch
    col_rate = 0.85 * inch
    col_amt = 0.95 * inch
    col_desc = usable - col_date - col_hours - col_rate - col_amt

    data = [[
        Paragraph("<b>Date</b>", s_th),
        Paragraph("<b>Description</b>", s_th),
        Paragraph("<b>Hours</b>", s_th_r),
        Paragraph("<b>Rate</b>", s_th_r),
        Paragraph("<b>Amount</b>", s_th_r),
    ]]
    for it in items:
        hours = it["hours"]
        rate = it["rate"]
        data.append([
            Paragraph(str(it["entry_date"] or "—"), s_cell),
            Paragraph(str(it["description"] or ""), s_cell),
            Paragraph(f"{float(hours):.1f}" if hours else "—", s_cell_r),
            Paragraph(_money(rate) if rate else "—", s_cell_r),
            Paragraph(_money(it["amount"]), s_cell_r),
        ])

    t = Table(data, colWidths=[col_date, col_desc, col_hours, col_rate, col_amt],
              repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#ffffff")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [HexColor("#ffffff"), LIGHT_BG]),
    ]
    t.setStyle(TableStyle(style))
    story.append(t)
    story.append(Spacer(1, 12))

    # ---- Totals ----
    totals = [
        [Paragraph("<b>Total due</b>", ParagraphStyle(
            "tot_l", parent=s_body, alignment=TA_RIGHT, fontName="Helvetica-Bold",
            fontSize=12, textColor=NAVY)),
         Paragraph(f"<b>{_money(total)}</b>", ParagraphStyle(
             "tot_r", parent=s_right, fontName="Helvetica-Bold", fontSize=12,
             textColor=NAVY))],
    ]
    tt = Table(totals, colWidths=[usable - 1.6 * inch, 1.6 * inch])
    tt.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 1.5, NAVY),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(tt)
    story.append(Spacer(1, 18))

    # ---- Notes ----
    if _val(invoice, "notes"):
        story.append(Paragraph("Notes", s_h2))
        story.append(Paragraph(str(invoice["notes"]), s_body))
        story.append(Spacer(1, 12))

    # ---- Footer ----
    story.append(HRFlowable(width="100%", thickness=0.75, color=BORDER))
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "Payment is due within 30 days of the invoice date. "
        "Please reference the invoice number with your payment.",
        s_muted))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        f"Thank you for your business — {FIRM_NAME}.",
        ParagraphStyle("thanks", parent=s_muted, fontName="Helvetica-Oblique")))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "This invoice was generated by the firm's case management system. "
        "Questions? Contact the office.",
        s_muted))

    doc.build(story)
    return buf.getvalue()
