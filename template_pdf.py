"""PDF generation for legal document templates.

Matches the invoice PDF style (DGM logo, navy/gold) for correspondence,
and uses a formal court-caption style for pleadings.

Each builder takes ``data`` (a dict of resolved field values) and an
optional ``logo_path``, and returns PDF bytes.
"""
import io
import os
from datetime import date

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
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
MARGIN = 0.9 * inch


def _styles():
    return {
        "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=20,
                                textColor=NAVY, leading=24, alignment=TA_CENTER,
                                spaceAfter=4),
        "subtitle": ParagraphStyle("subtitle", fontName="Helvetica", fontSize=11,
                                   textColor=MUTED, leading=14, alignment=TA_CENTER,
                                   spaceAfter=10),
        "firm": ParagraphStyle("firm", fontName="Helvetica-Bold", fontSize=13,
                               textColor=NAVY, leading=16),
        "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=13,
                             textColor=NAVY, leading=16, spaceBefore=16,
                             spaceAfter=8),
        "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=11,
                             textColor=NAVY, leading=14, spaceBefore=12,
                             spaceAfter=6),
        "body": ParagraphStyle("body", fontName="Helvetica", fontSize=10.5,
                               textColor=DARK, leading=15, alignment=TA_JUSTIFY,
                               spaceAfter=8),
        "body_l": ParagraphStyle("body_l", fontName="Helvetica", fontSize=10.5,
                                 textColor=DARK, leading=15, alignment=TA_LEFT,
                                 spaceAfter=8),
        "caption": ParagraphStyle("caption", fontName="Helvetica-Bold",
                                  fontSize=10.5, textColor=DARK, leading=14,
                                  alignment=TA_CENTER, spaceAfter=2),
        "caption_s": ParagraphStyle("caption_s", fontName="Helvetica",
                                    fontSize=10.5, textColor=DARK, leading=14,
                                    alignment=TA_CENTER, spaceAfter=2),
        "num": ParagraphStyle("num", fontName="Helvetica", fontSize=10.5,
                              textColor=DARK, leading=15, alignment=TA_JUSTIFY,
                              leftIndent=24, firstLineIndent=0, spaceAfter=8),
        "muted": ParagraphStyle("muted", fontName="Helvetica", fontSize=9,
                                textColor=MUTED, leading=12),
        "right": ParagraphStyle("right", fontName="Helvetica", fontSize=10.5,
                                textColor=DARK, leading=15, alignment=TA_RIGHT,
                                spaceAfter=4),
        "sig": ParagraphStyle("sig", fontName="Helvetica", fontSize=10.5,
                              textColor=DARK, leading=15, spaceBefore=36),
        "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=9.5,
                               textColor=DARK, leading=13),
        "cell_r": ParagraphStyle("cell_r", parent=None, fontName="Helvetica",
                                 fontSize=9.5, textColor=DARK, leading=13,
                                 alignment=TA_RIGHT),
        "th": ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=9.5,
                             textColor=HexColor("#ffffff"), leading=12),
        "warn": ParagraphStyle("warn", fontName="Helvetica-Bold", fontSize=9.5,
                               textColor=HexColor("#92400e"), leading=13,
                               backColor=HexColor("#fef3c7"),
                               borderPadding=8, spaceAfter=10),
    }


def _logo_cell(logo_path, width=1.35 * inch):
    s = _styles()["body"]
    if logo_path and os.path.exists(logo_path):
        try:
            img = Image(logo_path, width=width, height=width * 0.467)
            img.hAlign = "CENTER"
            return img
        except Exception:
            pass
    return Paragraph("", s)


def _letterhead(story, logo_path, s):
    """Firm letterhead block: centered logo + firm name + gold rule."""
    story.append(_logo_cell(logo_path, width=1.6 * inch))
    story.append(Spacer(1, 4))
    story.append(Paragraph(f"<b>{FIRM_NAME}</b>", s["firm"]))
    story[-1].style.alignment = TA_CENTER
    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", thickness=2, color=GOLD))
    story.append(Spacer(1, 14))


def _court_caption(story, s, county, case_number, petitioner, respondent,
                   doc_title):
    """Formal superior court caption block."""
    story.append(Paragraph(
        "IN THE SUPERIOR COURT OF THE STATE OF WASHINGTON", s["caption"]))
    story.append(Paragraph(
        f"IN AND FOR {str(county).upper()} COUNTY", s["caption"]))
    story.append(Spacer(1, 12))
    names = "In re the Marriage of:" if petitioner and respondent else "In re:"
    story.append(Paragraph(names, s["caption_s"]))
    story.append(Spacer(1, 6))
    if petitioner:
        story.append(Paragraph(f"<b>{_esc(petitioner)}</b>,", s["caption"]))
        story.append(Paragraph("Petitioner,", s["caption_s"]))
    if respondent:
        story.append(Paragraph("and", s["caption_s"]))
        story.append(Paragraph(f"<b>{_esc(respondent)}</b>,", s["caption"]))
        story.append(Paragraph("Respondent.", s["caption_s"]))
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=0.75, color=BORDER))
    story.append(Spacer(1, 6))
    if case_number:
        story.append(Paragraph(
            f"NO. {_esc(str(case_number))}", s["caption_s"]))
    story.append(Spacer(1, 10))
    story.append(Paragraph(f"<b>{_esc(doc_title)}</b>", s["title"]))
    story.append(Spacer(1, 10))


def _esc(text):
    """Escape minimal HTML for reportlab Paragraph."""
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _para(text, s):
    """Split text into paragraphs on blank lines; single newlines -> <br/>."""
    return [Paragraph(_esc(p.strip()).replace("\n", "<br/>"), s)
            for p in str(text or "").split("\n\n") if p.strip()]


def _numbered_paras(story, s, paragraphs):
    """Add numbered paragraphs (1., 2., 3. ...)."""
    for i, p in enumerate(paragraphs, 1):
        story.append(Paragraph(
            f"<b>{i}.</b>&nbsp;&nbsp;{_esc(p.strip())}", s["num"]))


def _split_paras(text):
    return [p.strip() for p in str(text or "").split("\n\n") if p.strip()]


def _doc(title, author_suffix=""):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=MARGIN,
        title=title, author=f"{FIRM_NAME}{author_suffix}",
    )
    return buf, doc


def _signature_block(story, s, signer="Derek G. Medina"):
    story.append(Paragraph("DATED this _____ day of ______________, 20___.",
                           s["body_l"]))
    story.append(Paragraph(f"<b>{_esc(signer)}</b><br/>Attorney for Petitioner",
                           s["sig"]))


def _children_lines(children):
    """Format child list for display: [{'name','date_of_birth'}] -> lines."""
    lines = []
    for c in children or []:
        dob = c.get("date_of_birth") or "DOB unknown"
        lines.append(f"{c.get('name', '')} (DOB: {dob})")
    return lines


# ---------------------------------------------------------------------------
# Child support calculation (simplified WA schedule estimate)
# ---------------------------------------------------------------------------
# Simplified basic monthly support obligation by combined monthly NET income
# bracket. Each entry: (income ceiling, [1 child, 2, 3, 4, 5+ children]).
# These are APPROXIMATIONS for worksheet purposes only — the PDF carries a
# prominent disclaimer to verify with the official RCW 26.19 schedule.
_SUPPORT_TABLE = [
    (1500,   [230,  355,  435,  500,  555]),
    (2500,   [330,  510,  625,  715,  795]),
    (3500,   [425,  655,  805,  920, 1025]),
    (5000,   [545,  840, 1030, 1180, 1310]),
    (7000,   [680, 1050, 1285, 1470, 1635]),
    (10000,  [850, 1310, 1605, 1840, 2045]),
    (15000,  [1060, 1635, 2000, 2290, 2550]),
    (999999, [1250, 1930, 2360, 2700, 3000]),
]

SUPPORT_DISCLAIMER = (
    "ESTIMATE ONLY — This worksheet uses a SIMPLIFIED version of the "
    "Washington State Child Support Schedule (RCW 26.19) and does not account "
    "for all statutory adjustments (e.g., residential credits, overtime, "
    "deviation factors). VERIFY all figures with the official state schedule "
    "or a qualified professional before filing or relying on this worksheet."
)


def calc_support(income_a, income_b, n_children, daycare=0.0, insurance=0.0):
    """Return dict with the simplified support calculation."""
    income_a = max(0.0, float(income_a or 0))
    income_b = max(0.0, float(income_b or 0))
    combined = income_a + income_b
    n = max(1, min(5, int(n_children or 1)))
    basic = 0.0
    for ceiling, amounts in _SUPPORT_TABLE:
        if combined <= ceiling:
            basic = float(amounts[n - 1])
            break
    total = basic + float(daycare or 0) + float(insurance or 0)
    if combined > 0:
        share_a = total * income_a / combined
        share_b = total * income_b / combined
    else:
        share_a = share_b = 0.0
    return {
        "income_a": income_a, "income_b": income_b, "combined": combined,
        "n_children": n, "basic": basic,
        "daycare": float(daycare or 0), "insurance": float(insurance or 0),
        "total": total, "share_a": share_a, "share_b": share_b,
    }


def _money(v):
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return "—"


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------
def build_petition_dissolution(data, logo_path=None):
    s = _styles()
    buf, doc = _doc("Petition for Dissolution")
    story = []
    _court_caption(story, s, data.get("county"), data.get("case_number"),
                   data.get("petitioner"), data.get("respondent"),
                   "PETITION FOR DISSOLUTION OF MARRIAGE")

    paras = []
    paras.append(
        f"Petitioner {data.get('petitioner', '')} petitions the Court for a "
        f"decree dissolving the marriage to Respondent "
        f"{data.get('respondent', '')}.")
    md = data.get("marriage_date") or "[date]"
    mp = data.get("marriage_place") or "[place]"
    paras.append(f"The parties were married on {md} in {mp}.")
    if data.get("separation_date"):
        paras.append(f"The parties separated on {data.get('separation_date')}.")
    paras.append("The marriage is irretrievably broken and there is no "
                 "reasonable prospect of reconciliation.")
    kids = _children_lines(data.get("children"))
    if kids:
        paras.append("The following minor children were born of the marriage: "
                     + "; ".join(kids) + ". Petitioner requests the Court "
                     "enter a parenting plan and child support order in the "
                     "children's best interests.")
    else:
        paras.append("No minor children were born of the marriage.")
    paras.append(data.get("property_request") or "")
    paras.append(f"Spousal maintenance: {data.get('maintenance_request') or 'None'}.")
    if data.get("other_relief"):
        paras.append(data.get("other_relief"))
    paras.append("Petitioner requests the Court dissolve the marriage and "
                 "grant such other relief as is just and equitable.")
    _numbered_paras(story, s, [p for p in paras if p.strip()])
    _signature_block(story, s)
    doc.build(story)
    return buf.getvalue()


def build_parenting_plan(data, logo_path=None):
    s = _styles()
    buf, doc = _doc("Parenting Plan")
    story = []
    _court_caption(story, s, data.get("county"), data.get("case_number"),
                   data.get("parent_a"), data.get("parent_b"),
                   "PARENTING PLAN")
    story.append(Paragraph("I. Children", s["h1"]))
    kids = _children_lines(data.get("children"))
    if kids:
        for k in kids:
            story.append(Paragraph(f"• {_esc(k)}", s["body_l"]))
    else:
        story.append(Paragraph("No minor children listed.", s["body_l"]))
    story.append(Paragraph("II. Residential Schedule", s["h1"]))
    for p in _para(data.get("residential_schedule"), s["body"]):
        story.append(p)
    story.append(Paragraph("III. Holidays and School Breaks", s["h1"]))
    for p in _para(data.get("holidays"), s["body"]):
        story.append(p)
    story.append(Paragraph("IV. Decision-Making", s["h1"]))
    story.append(Paragraph(
        f"<b>{_esc(data.get('decision_making') or '')}</b>", s["body_l"]))
    for p in _para(data.get("decision_details"), s["body"]):
        story.append(p)
    story.append(Paragraph("V. Transportation", s["h1"]))
    for p in _para(data.get("transportation"), s["body"]):
        story.append(p)
    story.append(Spacer(1, 12))
    story.append(Paragraph(
        "The parents agree to act in the children's best interests and to "
        "communicate respectfully regarding the children.", s["body"]))
    _signature_block(story, s)
    doc.build(story)
    return buf.getvalue()


def build_support_worksheet(data, logo_path=None):
    s = _styles()
    buf, doc = _doc("Child Support Worksheet")
    story = []
    _letterhead(story, logo_path, s)
    story.append(Paragraph("<b>CHILD SUPPORT WORKSHEET</b> (Estimate)", s["title"]))
    story.append(Paragraph(
        "Simplified worksheet — see disclaimer below.", s["subtitle"]))

    calc = calc_support(data.get("parent_a_income"), data.get("parent_b_income"),
                        len(data.get("children") or []),
                        data.get("daycare"), data.get("health_insurance"))
    pa, pb = data.get("parent_a") or "Parent A", data.get("parent_b") or "Parent B"

    story.append(Paragraph("Parents and Children", s["h1"]))
    info = [
        [Paragraph("<b>Parent A</b>", s["cell"]), Paragraph(_esc(pa), s["cell"]),
         Paragraph("<b>Monthly net income</b>", s["cell"]),
         Paragraph(_money(calc["income_a"]), s["cell_r"])],
        [Paragraph("<b>Parent B</b>", s["cell"]), Paragraph(_esc(pb), s["cell"]),
         Paragraph("<b>Monthly net income</b>", s["cell"]),
         Paragraph(_money(calc["income_b"]), s["cell_r"])],
        [Paragraph("<b>Combined</b>", s["cell"]), Paragraph("", s["cell"]),
         Paragraph("<b>Combined monthly net</b>", s["cell"]),
         Paragraph(_money(calc["combined"]), s["cell_r"])],
    ]
    kids = _children_lines(data.get("children"))
    for k in kids:
        info.append([Paragraph("<b>Child</b>", s["cell"]),
                     Paragraph(_esc(k), s["cell"]),
                     Paragraph("", s["cell"]), Paragraph("", s["cell"])])
    t = Table(info, colWidths=[1.3 * inch, 2.4 * inch, 1.6 * inch, 1.2 * inch])
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(t)

    story.append(Paragraph("Calculation", s["h1"]))
    rows = [
        [Paragraph("<b>Basic support obligation (simplified schedule)</b>", s["cell"]),
         Paragraph(_money(calc["basic"]), s["cell_r"])],
        [Paragraph("Plus: daycare costs", s["cell"]),
         Paragraph(_money(calc["daycare"]), s["cell_r"])],
        [Paragraph("Plus: children's health insurance", s["cell"]),
         Paragraph(_money(calc["insurance"]), s["cell_r"])],
        [Paragraph("<b>Total monthly obligation</b>", s["cell"]),
         Paragraph(f"<b>{_money(calc['total'])}</b>", s["cell_r"])],
        [Paragraph(f"{_esc(pa)}'s share", s["cell"]),
         Paragraph(f"<b>{_money(calc['share_a'])}</b>", s["cell_r"])],
        [Paragraph(f"{_esc(pb)}'s share", s["cell"]),
         Paragraph(f"<b>{_money(calc['share_b'])}</b>", s["cell_r"])],
    ]
    t2 = Table(rows, colWidths=[4.9 * inch, 1.6 * inch])
    t2.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("BACKGROUND", (0, 3), (-1, 3), LIGHT_BG),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(t2)
    story.append(Spacer(1, 12))
    if data.get("notes"):
        story.append(Paragraph("Notes", s["h2"]))
        for p in _para(data.get("notes"), s["body"]):
            story.append(p)
    story.append(Spacer(1, 8))
    story.append(Paragraph(SUPPORT_DISCLAIMER, s["warn"]))
    doc.build(story)
    return buf.getvalue()


def build_declaration(data, logo_path=None):
    s = _styles()
    buf, doc = _doc("Declaration")
    story = []
    _court_caption(story, s, data.get("county"), data.get("case_number"),
                   None, None, "DECLARATION")
    story.append(Paragraph(
        f"I, <b>{_esc(data.get('declarant') or '')}</b>, declare as follows:",
        s["body_l"]))
    story.append(Spacer(1, 6))
    for p in _para(data.get("body"), s["body"]):
        story.append(p)
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "I certify under penalty of perjury under the laws of the State of "
        "Washington that the foregoing is true and correct.", s["body"]))
    story.append(Spacer(1, 6))
    story.append(Paragraph("DATED this _____ day of ______________, 20___.",
                           s["body_l"]))
    story.append(Paragraph(f"<b>{_esc(data.get('declarant') or '')}</b>",
                           s["sig"]))
    doc.build(story)
    return buf.getvalue()


def build_cover_letter(data, logo_path=None):
    s = _styles()
    buf, doc = _doc("Cover Letter")
    story = []
    _letterhead(story, logo_path, s)
    story.append(Paragraph(_esc(data.get("letter_date") or str(date.today())),
                           s["body_l"]))
    story.append(Spacer(1, 10))
    story.append(Paragraph(f"<b>{_esc(data.get('recipient_name') or '')}</b>",
                           s["body_l"]))
    for p in _para(data.get("recipient_address"), s["body_l"]):
        story.append(p)
    story.append(Spacer(1, 10))
    if data.get("re_line"):
        story.append(Paragraph(f"<b>{_esc(data.get('re_line'))}</b>", s["body_l"]))
        story.append(Spacer(1, 10))
    for p in _para(data.get("body"), s["body"]):
        story.append(p)
    story.append(Spacer(1, 6))
    story.append(Paragraph(_esc(data.get("closing") or "Sincerely,"), s["body_l"]))
    story.append(Paragraph(f"<b>{_esc(data.get('signer') or 'Derek G. Medina')}</b>",
                           s["sig"]))
    doc.build(story)
    return buf.getvalue()


BUILDERS = {
    "petition_dissolution": build_petition_dissolution,
    "parenting_plan": build_parenting_plan,
    "support_worksheet": build_support_worksheet,
    "declaration": build_declaration,
    "cover_letter": build_cover_letter,
}


def build_template_pdf(layout_key, data, logo_path=None):
    """Build a PDF for the given template layout key."""
    builder = BUILDERS.get(layout_key)
    if not builder:
        raise ValueError(f"Unknown template layout: {layout_key}")
    return builder(data, logo_path)
