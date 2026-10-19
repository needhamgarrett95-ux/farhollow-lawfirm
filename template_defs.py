"""Document template definitions for the Law Office of Derek G. Medina.

Each template is a dict with:
  - key: URL-safe identifier
  - name: display name
  - description: shown on the gallery card
  - doc_category: which document category a generated file is saved under
  - file_stem: base filename for generated PDFs
  - fields: list of field dicts. Each field:
      - name: form field name
      - label: display label
      - type: text | date | dropdown | textarea | currency | child-list | info
        (child-list is read-only, auto-filled from the client's children;
         info is a read-only note rendered in the form)
      - options: for dropdown, list of strings
      - source: optional auto-fill source: "client.name", "client.spouse_name",
        "case.number", "case.title"
      - default: default value (may contain {{placeholders}})
      - rows: for textarea, height in rows
      - required: bool
  - layout: name of the PDF builder function in template_pdf.py

To add a new template: add an entry here and a builder function in
template_pdf.py with the same layout name. No other code changes needed.
"""

TEMPLATES = {
    "petition_dissolution": {
        "key": "petition_dissolution",
        "name": "Petition for Dissolution",
        "description": (
            "Petition to dissolve a marriage (divorce) for filing in "
            "Washington Superior Court. Auto-fills petitioner, respondent, "
            "and children from the client record."
        ),
        "doc_category": "pleadings",
        "file_stem": "Petition_for_Dissolution",
        "layout": "petition_dissolution",
        "fields": [
            {"name": "county", "label": "County of filing", "type": "text",
             "default": "Clallam", "required": True},
            {"name": "petitioner", "label": "Petitioner (full legal name)",
             "type": "text", "source": "client.name", "required": True},
            {"name": "respondent", "label": "Respondent (full legal name)",
             "type": "text", "source": "client.spouse_name", "required": True},
            {"name": "marriage_date", "label": "Date of marriage",
             "type": "date", "required": True},
            {"name": "marriage_place", "label": "Place of marriage (city, state)",
             "type": "text"},
            {"name": "separation_date", "label": "Date of separation (if separated)",
             "type": "date"},
            {"name": "children", "label": "Minor children of the marriage",
             "type": "child-list"},
            {"name": "property_request",
             "label": "Property division requested",
             "type": "textarea", "rows": 4,
             "default": "Petitioner requests a just and equitable division of "
                        "all community and separate property and debts."},
            {"name": "maintenance_request",
             "label": "Spousal maintenance requested",
             "type": "dropdown",
             "options": ["None", "Temporary maintenance", "Permanent maintenance",
                         "Maintenance to be determined"]},
            {"name": "other_relief",
             "label": "Other relief requested",
             "type": "textarea", "rows": 3,
             "default": "Petitioner requests such other and further relief as "
                        "the Court deems just and equitable."},
        ],
    },
    "parenting_plan": {
        "key": "parenting_plan",
        "name": "Parenting Plan",
        "description": (
            "Residential schedule, decision-making, and holiday plan for the "
            "children. Children's names and birth dates fill in automatically."
        ),
        "doc_category": "pleadings",
        "file_stem": "Parenting_Plan",
        "layout": "parenting_plan",
        "fields": [
            {"name": "county", "label": "County of filing", "type": "text",
             "default": "Clallam", "required": True},
            {"name": "parent_a", "label": "Parent A (full legal name)",
             "type": "text", "source": "client.name", "required": True},
            {"name": "parent_b", "label": "Parent B (full legal name)",
             "type": "text", "source": "client.spouse_name", "required": True},
            {"name": "children", "label": "Children covered by this plan",
             "type": "child-list"},
            {"name": "residential_schedule",
             "label": "Residential schedule",
             "type": "textarea", "rows": 6,
             "default": "The children shall reside with Parent A except as "
                        "follows:\n\n[Describe the regular schedule, e.g. "
                        "every other weekend with Parent B from Friday 6pm "
                        "to Sunday 6pm, plus one midweek evening visit.]"},
            {"name": "holidays",
             "label": "Holidays and school breaks",
             "type": "textarea", "rows": 4,
             "default": "Holidays shall be shared as follows:\n\n[Describe "
                        "holiday rotation, winter/spring/summer breaks.]"},
            {"name": "decision_making",
             "label": "Decision-making authority",
             "type": "dropdown",
             "options": ["Joint decision-making",
                         "Sole decision-making to Parent A",
                         "Sole decision-making to Parent B"]},
            {"name": "decision_details",
             "label": "Decision-making details",
             "type": "textarea", "rows": 3,
             "default": ""},
            {"name": "transportation",
             "label": "Transportation arrangements",
             "type": "textarea", "rows": 3,
             "default": "The parent beginning their residential time shall "
                        "provide transportation, unless otherwise agreed."},
        ],
    },
    "support_worksheet": {
        "key": "support_worksheet",
        "name": "Child Support Worksheet",
        "description": (
            "Estimate monthly child support using a simplified version of the "
            "Washington State Child Support Schedule. Verify figures with the "
            "official schedule before filing."
        ),
        "doc_category": "other",
        "file_stem": "Child_Support_Worksheet",
        "layout": "support_worksheet",
        "fields": [
            {"name": "worksheet_note", "label": "",
             "type": "info",
             "default": "This worksheet uses a SIMPLIFIED version of the "
                        "Washington State Child Support Schedule (RCW 26.19) "
                        "to produce an estimate. Always verify with the "
                        "official schedule or calculator before filing."},
            {"name": "parent_a", "label": "Parent A (full name)",
             "type": "text", "source": "client.name", "required": True},
            {"name": "parent_a_income",
             "label": "Parent A monthly NET income ($)",
             "type": "currency", "required": True},
            {"name": "parent_b", "label": "Parent B (full name)",
             "type": "text", "source": "client.spouse_name", "required": True},
            {"name": "parent_b_income",
             "label": "Parent B monthly NET income ($)",
             "type": "currency", "required": True},
            {"name": "children", "label": "Children",
             "type": "child-list"},
            {"name": "daycare",
             "label": "Monthly daycare costs ($, if any)",
             "type": "currency"},
            {"name": "health_insurance",
             "label": "Monthly health insurance for children ($, if any)",
             "type": "currency"},
            {"name": "notes", "label": "Notes", "type": "textarea", "rows": 3,
             "default": ""},
        ],
    },
    "declaration": {
        "key": "declaration",
        "name": "Declaration",
        "description": (
            "Sworn written statement for filing with the court. Declarant and "
            "case number fill in automatically; you write the body."
        ),
        "doc_category": "pleadings",
        "file_stem": "Declaration",
        "layout": "declaration",
        "fields": [
            {"name": "county", "label": "County of filing", "type": "text",
             "default": "Clallam", "required": True},
            {"name": "declarant", "label": "Declarant (full legal name)",
             "type": "text", "source": "client.name", "required": True},
            {"name": "body",
             "label": "Declaration body (numbered paragraphs will be kept as written)",
             "type": "textarea", "rows": 14, "required": True,
             "default": "1. I am the {{client.role}} in this matter and make "
                        "this declaration from personal knowledge.\n\n"
                        "2. [State the facts here.]\n\n"
                        "3. [Continue numbering your paragraphs.]"},
        ],
    },
    "cover_letter": {
        "key": "cover_letter",
        "name": "Cover Letter",
        "description": (
            "Firm letterhead cover letter to a client or opposing counsel. "
            "Prints on letterhead with the DGM logo."
        ),
        "doc_category": "correspondence",
        "file_stem": "Cover_Letter",
        "layout": "cover_letter",
        "fields": [
            {"name": "recipient_name", "label": "Recipient name",
             "type": "text", "required": True},
            {"name": "recipient_address", "label": "Recipient address",
             "type": "textarea", "rows": 3},
            {"name": "letter_date", "label": "Date", "type": "date",
             "default": "{{today}}", "required": True},
            {"name": "re_line", "label": "Re: line", "type": "text",
             "default": "Re: {{case.title}} ({{case.number}})"},
            {"name": "body", "label": "Letter body",
             "type": "textarea", "rows": 12, "required": True,
             "default": "Dear {{recipient_name}},\n\n[Write your letter here. "
                        "You can use {{client.name}}, {{case.number}}, and "
                        "{{today}} as placeholders.]\n\n"},
            {"name": "closing", "label": "Closing",
             "type": "dropdown",
             "options": ["Sincerely,", "Respectfully,", "Very truly yours,"]},
            {"name": "signer", "label": "Signed by", "type": "text",
             "default": "Derek G. Medina"},
        ],
    },
}


def get_template(key):
    """Return the template dict for key, or None."""
    return TEMPLATES.get(key)


def template_list():
    """Return templates in display order."""
    order = ["petition_dissolution", "parenting_plan", "support_worksheet",
             "declaration", "cover_letter"]
    return [TEMPLATES[k] for k in order if k in TEMPLATES]
