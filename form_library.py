"""Document library registry for the client portal (v2.8.0).

Three data structures live here:

1. ``VAULT_FACTS`` — the profile-vault fact registry. Every shareable
   fact about a client has a key, a label, a sensitivity flag, and a
   store: an existing ``clients`` column, a ``case_financials`` key
   (per case), or the ``client_vault_facts`` key/value table (facts
   with no home column). Wizards read and write facts only through
   these keys, so a fact is collected once and reused everywhere.

2. ``LIBRARY`` — the verified catalog of Washington family-law forms.
   Each entry: slug, official form number, official title, tier
   (common | uncommon | rare), scenario tags, how much of it a client
   can complete (full | partial | none), the vault fact keys it uses,
   and the source the number/title was verified against. Entries with
   ``verified`` False carry a number seen only in secondary sources —
   the staff library view labels them "number unverified" rather than
   presenting them as settled. Catalog-only entries (``implemented``
   False) have no wizard yet and are never client-facing.

   Verification pass: October 2026, against the Washington Courts
   forms index (courts.wa.gov/forms), the official form PDFs hosted
   there, Northwest Justice Project form packets (WashingtonLawHelp),
   and county superior-court instruction packets (King, Clark,
   Clallam, Skagit, Cowlitz) that quote the official numbers. See
   docs/FORM_CATALOG.md for the per-tier source notes. NOTE: an early
   draft of this project listed the Certificate of Dissolution as
   "FL Divorce 211" — that is wrong. FL Divorce 211 is the Response
   to Petition about a Marriage; the certificate is Department of
   Health form DOH 422-027.

3. ``WIZARD_DEFS`` — data-driven portal wizards for the implemented
   documents (common tier in v2.8.0; uncommon tier added in v2.9.0).
   Shape mirrors PORTAL_FORM_DEFS in app.py
   (steps -> fields) with extensions: a field may carry ``vault``
   (the fact key it confirms/edits), ``prompt`` / ``guidance``
   (writing help for textareas), and new types: money, select,
   radio_cards, checkboxes, repeater. A wizard may set ``attest``
   True (declaration) to require a typed-name attestation on the
   review step, and ``generate`` describing how staff turn an
   approved submission into a case document.

4. ``PACKET_DEFS`` (v2.9.0) — scenario packets: guided checklists
   staff assign to a client. Each packet has a plain-language title
   and description, the standing guidance line (guidance from the
   office, not legal advice), and ordered steps. A step is one of:
   ``{"type": "wizard", "doc": <catalog slug>}``, ``{"type":
   "upload", "title": ..., "note": ..., "doc_type": <portal doc
   type>}`` (tracked through the v2.6.0 document-request machinery),
   or ``{"type": "info", "title": ..., "body": ...}`` (read and
   acknowledge). A step may set ``sequential`` True (later steps
   lock until it is done — used sparingly) or ``optional`` True
   (shown, but not counted toward packet completion).

Field targets reuse the portal import tuples:
  ("client", <clients column>)  ("financial", <case_financials key>)
  ("vault", <vault fact key>)   ("children",)  for the repeater
  None                          reference only (kept in the snapshot)
"""

FORMS_INDEX_URL = "https://www.courts.wa.gov/forms/"

# ----------------------------------------------------------------------------
# Vault fact registry
# ----------------------------------------------------------------------------
# store: "client"    -> clients.<column> (column given)
#        "financial" -> case_financials.<fkey> for the wizard's case
#        "vault"     -> client_vault_facts row keyed by this fact key
VAULT_FACTS = {
    "client.first_name": {"label": "First name", "store": "client",
                          "column": "first_name"},
    "client.last_name": {"label": "Last name", "store": "client",
                         "column": "last_name"},
    "client.email": {"label": "Email address", "store": "client",
                     "column": "email"},
    "client.phone": {"label": "Phone number", "store": "client",
                     "column": "phone"},
    "client.address": {"label": "Mailing address", "store": "client",
                       "column": "address"},
    "client.date_of_birth": {"label": "Date of birth", "store": "client",
                             "column": "date_of_birth", "sensitive": True},
    "client.ssn": {"label": "Social Security number", "store": "client",
                   "column": "ssn", "sensitive": True, "mask": True},
    "client.employer": {"label": "Employer", "store": "vault"},
    "client.job_title": {"label": "Job title", "store": "vault"},
    "client.birth_name": {"label": "Birth name (before any marriage)",
                          "store": "vault"},
    "client.birth_place": {"label": "Place of birth (city, state)",
                           "store": "vault"},
    "client.driver_license": {"label": "Driver's license / ID number",
                              "store": "vault", "sensitive": True,
                              "mask": True},
    "client.accounts_protected": {
        "label": "Financial accounts (institutions + last 4 digits)",
        "store": "vault", "sensitive": True},
    "spouse.name": {"label": "Spouse / other parent — full legal name",
                    "store": "client", "column": "spouse_name"},
    "spouse.date_of_birth": {"label": "Spouse / other parent — date of birth",
                             "store": "client", "column": "spouse_dob",
                             "sensitive": True},
    "spouse.employer": {"label": "Spouse / other parent — employer",
                        "store": "vault"},
    "spouse.birth_name": {"label": "Spouse — birth name", "store": "vault"},
    "spouse.birth_place": {"label": "Spouse — place of birth",
                           "store": "vault"},
    "spouse.ssn": {"label": "Spouse — Social Security number",
                   "store": "vault", "sensitive": True, "mask": True},
    "marriage.date": {"label": "Date of marriage", "store": "vault"},
    "marriage.place": {"label": "Place of marriage (city, state)",
                       "store": "vault"},
    "separation.date": {"label": "Date of separation", "store": "vault"},
    "service.address": {"label": "Address where the other party can be "
                                "served", "store": "vault"},
    "income.client_gross": {"label": "Your monthly GROSS income",
                            "store": "financial",
                            "fkey": "client_gross_income"},
    "income.client_net": {"label": "Your monthly NET (take-home) income",
                          "store": "financial",
                          "fkey": "client_net_income"},
    "income.other_parent_net": {
        "label": "Other parent's monthly NET income",
        "store": "financial", "fkey": "other_parent_net_income"},
    "costs.daycare": {"label": "Monthly daycare costs", "store": "financial",
                      "fkey": "daycare"},
    "costs.health_insurance": {
        "label": "Monthly health insurance for the children",
        "store": "financial", "fkey": "health_insurance"},
    "expenses.monthly_total": {"label": "Total monthly expenses",
                               "store": "financial",
                               "fkey": "monthly_expenses"},
    "expenses.housing": {"label": "Monthly housing (rent/mortgage)",
                         "store": "financial", "fkey": "housing_expenses"},
    "expenses.utilities": {"label": "Monthly utilities",
                           "store": "financial", "fkey": "utility_expenses"},
    "expenses.food": {"label": "Monthly food / household",
                      "store": "financial", "fkey": "food_expenses"},
    "expenses.transportation": {"label": "Monthly transportation",
                                "store": "financial",
                                "fkey": "transportation_expenses"},
    "expenses.insurance": {"label": "Monthly insurance premiums",
                           "store": "financial",
                           "fkey": "insurance_expenses"},
    "expenses.other": {"label": "Other monthly expenses",
                       "store": "financial", "fkey": "other_expenses"},
    "expenses.debt_payments": {"label": "Monthly debt payments",
                               "store": "financial",
                               "fkey": "debt_payments_monthly"},
    "notes.assets": {"label": "Assets", "store": "financial",
                     "fkey": "assets_notes"},
    "notes.debts": {"label": "Debts", "store": "financial",
                    "fkey": "debts_notes"},
    "notes.accounts": {"label": "Bank / financial accounts",
                       "store": "financial", "fkey": "accounts_notes"},
    "notes.other_income": {"label": "Other income", "store": "financial",
                           "fkey": "other_income_notes"},
    "household.size": {"label": "People in your household",
                       "store": "vault"},
    "benefits.receiving": {"label": "Receiving public benefits "
                                    "(SNAP, TANF, SSI, Medicaid…)?",
                           "store": "vault"},
    "benefits.details": {"label": "Public benefits — which programs "
                                  "and monthly amounts",
                         "store": "vault"},
}


def vault_fact(key):
    return VAULT_FACTS.get(key)


# ----------------------------------------------------------------------------
# The verified catalog
# ----------------------------------------------------------------------------
def _e(slug, number, title, tier, scenarios, completable, vault=(),
       source_url=FORMS_INDEX_URL, verified=True, implemented=False,
       wizard=None, note=""):
    return {
        "slug": slug, "form_number": number, "title": title,
        "tier": tier, "scenarios": list(scenarios),
        "completable": completable, "vault_fields": list(vault),
        "source_url": source_url, "verified": verified,
        "implemented": implemented, "wizard": wizard, "note": note,
    }


LIBRARY = [
    # ------------------------------------------------------------------
    # COMMON — the divorce packet and its everyday companions
    # ------------------------------------------------------------------
    _e("petition-divorce", "FL Divorce 201", "Petition for Divorce "
       "(Dissolution)", "common", ["starting_divorce", "uncontested"],
       "partial", ["marriage.date", "marriage.place", "separation.date",
                   "spouse.name"],
       implemented=True, wizard="petition_divorce",
       note="The wizard captures everything the client supplies; the "
            "attorney completes and files the petition. One capture "
            "serves the whole series: the wizard's first question "
            "asks whether this is a dissolution, a legal separation, "
            "or an invalidity (annulment) — the Divorce series covers "
            "all three, so there is no separate separation wizard."),
    _e("summons-marriage", "FL Divorce 200", "Summons: Notice About a "
       "Marriage or Domestic Partnership", "common",
       ["starting_divorce", "responding"], "none"),
    _e("joinder", "FL All Family 119", "Agreement to Join Petition "
       "(Joinder)", "common", ["uncontested"], "none",
       note="Used when the respondent agrees with the petition as filed."),
    _e("confidential-information", "FL All Family 001",
       "Confidential Information Form", "common",
       ["starting_divorce", "responding", "changing_order"], "full",
       ["client.date_of_birth", "client.ssn", "client.driver_license",
        "client.address", "client.phone", "spouse.name",
        "spouse.date_of_birth", "spouse.ssn", "client.accounts_protected"],
       implemented=True, wizard="confidential_information",
       note="GR 22: filed under seal; never part of the public file."),
    _e("cif-attachment", "FL All Family 002", "Attachment to Confidential "
       "Information (Additional Parties or Children)", "common",
       ["starting_divorce"], "partial",
       implemented=True, wizard="sealed_attachment",
       note="The wizard has the client flag which of their facts and "
            "documents are sensitive (and why) so staff can assemble "
            "the sealed attachment and any GR 22 requests."),
    _e("certificate-dissolution", "DOH 422-027", "Certificate of "
       "Dissolution, Declaration of Invalidity of Marriage, or Legal "
       "Separation (WA Dept. of Health)", "common",
       ["starting_divorce", "finalizing"], "full",
       ["client.birth_name", "client.birth_place", "client.date_of_birth",
        "spouse.name", "spouse.birth_name", "spouse.birth_place",
        "spouse.date_of_birth", "marriage.date", "marriage.place"],
       implemented=True, wizard="certificate_dissolution",
       note="Vital-statistics form. NOT an FL form — an earlier draft of "
            "this catalog mislabeled it 'FL Divorce 211'; that number is "
            "the Response to Petition (see below)."),
    _e("financial-declaration", "FL All Family 131", "Financial "
       "Declaration", "common",
       ["starting_divorce", "temporary_orders", "changing_order"], "full",
       ["client.employer", "client.job_title", "income.client_gross",
        "income.client_net", "notes.other_income", "expenses.housing",
        "expenses.utilities", "expenses.food", "expenses.transportation",
        "expenses.insurance", "expenses.other", "expenses.monthly_total",
        "notes.assets", "notes.accounts", "notes.debts",
        "expenses.debt_payments"],
       implemented=True, wizard="financial_declaration"),
    _e("declaration", "FL All Family 135", "Declaration", "common",
       ["starting_divorce", "temporary_orders", "responding",
        "changing_order"], "full",
       ["spouse.name", "marriage.date", "marriage.place",
        "separation.date", "client.employer", "income.client_gross",
        "income.client_net"],
       implemented=True, wizard="declaration",
       note="The flagship wizard: the client's own statement to the "
            "court, written with guided prompts."),
    _e("parenting-plan", "FL All Family 140", "Parenting Plan", "common",
       ["starting_divorce", "temporary_orders", "changing_order"],
       "partial", [],
       implemented=True, wizard="parenting_plan",
       note="The wizard captures the client's proposed schedule, "
            "decision-making, and any restrictions; the attorney "
            "completes the plan."),
    _e("child-support-worksheet", "WSCSS — Worksheets", "Washington State "
       "Child Support Schedule Worksheets", "common",
       ["starting_divorce", "temporary_orders", "changing_order"],
       "partial",
       ["income.client_gross", "income.client_net",
        "income.other_parent_net", "costs.daycare",
        "costs.health_insurance"],
       implemented=True, wizard="support_worksheet_data",
       note="The wizard confirms the worksheet inputs; the firm's "
            "existing worksheet generator produces the estimate. Always "
            "verify against the official RCW 26.19 schedule."),
    _e("child-support-order", "FL All Family 130", "Child Support Order",
       "common", ["starting_divorce", "finalizing"], "none",
       note="Prepared by the attorney for the court's signature."),
    _e("sealed-financial-cover", "FL All Family 011", "Sealed Financial "
       "Source Documents (Cover Sheet)", "common",
       ["starting_divorce", "changing_order"], "none"),
    _e("temp-parenting-info", "FL All Family 139", "Information for "
       "Temporary Parenting Plan", "common", ["temporary_orders"],
       "none"),
    _e("residential-time-summary", "FL Divorce 243", "Residential Time "
       "Summary Report", "common", ["starting_divorce"], "none"),
    _e("findings-marriage", "FL Divorce 231", "Findings and Conclusions "
       "About a Marriage", "common", ["finalizing"], "none",
       note="Attorney/court document — cataloged so staff see the full "
            "packet."),
    _e("final-divorce-order", "FL Divorce 241", "Final Divorce Order "
       "(Dissolution Decree) / Legal Separation Order / Invalid "
       "Marriage Order", "common", ["finalizing"], "none",
       note="Legal separation and invalidity ride this same divorce "
            "series (petition, summons, response, findings) — there is "
            "no separate legal-separation packet."),
    _e("proof-personal-service", "FL All Family 101", "Proof of Personal "
       "Service", "common", ["starting_divorce"], "none"),
    _e("service-accepted", "FL All Family 117", "Service Accepted",
       "common", ["starting_divorce", "responding"], "none"),
    _e("proof-mailing", "FL All Family 112", "Proof of Mailing or Hand "
       "Delivery", "common", ["starting_divorce"], "none"),
    _e("notice-of-hearing", "FL All Family 185", "Notice of Hearing",
       "common", ["temporary_orders", "changing_order"], "none",
       note="Clallam County: family-law motions are noted for hearing "
            "with this form — never by phone (see the Clallam overlay "
            "in deadlines.py, v1.9.0)."),
    _e("temporary-orders", "FL Divorce 223", "Motion for Temporary "
       "Family Law Order", "common", ["temporary_orders"], "partial",
       ["income.client_net", "income.other_parent_net"],
       implemented=True, wizard="temporary_orders",
       note="Pairs with FL Divorce 224 (the proposed Temporary Family "
            "Law Order the client fills out 'the way you would like "
            "the judge to decide'). The wizard captures what the client "
            "needs ordered now."),
    _e("case-cover-sheet", "CCS — Family", "Family Case Information "
       "Cover Sheet (Superior Court Clerk)", "common",
       ["starting_divorce"], "none",
       note="Clallam County requires the family case cover sheet "
            "(case types 3 and 5) with new filings."),

    # ------------------------------------------------------------------
    # UNCOMMON — responses, modifications, relocation, parentage, safety
    # ------------------------------------------------------------------
    _e("response-marriage", "FL Divorce 211", "Response to Petition "
       "about a Marriage", "uncommon", ["responding"], "partial",
       ["spouse.name"],
       implemented=True, wizard="response_marriage",
       note="The other half of the 211 confusion: this IS FL Divorce "
            "211. Clallam County's own response packet (Superior Court, "
            "DocumentCenter) is built around it. The wizard captures "
            "the client's agrees/disagrees and counter-requests; the "
            "attorney drafts the response."),
    _e("response-domestic-partnership", "FL Divorce 212", "Response to "
       "Petition about a Registered Domestic Partnership", "uncommon",
       ["responding"], "partial", ["spouse.name"]),
    _e("temporary-order-divorce", "FL Divorce 224", "Temporary Family "
       "Law Order", "uncommon", ["temporary_orders"], "partial",
       implemented=False,
       note="The proposed order that accompanies the FL Divorce 223 "
            "motion; captured through the Temporary Orders wizard in "
            "this release."),
    _e("immediate-restraining-order", "FL Divorce 221", "Motion for "
       "Immediate Restraining Order (Ex Parte)", "uncommon",
       ["temporary_orders", "protection"], "none"),
    _e("restraining-order", "FL All Family 150", "Restraining Order",
       "uncommon", ["temporary_orders", "protection"], "none"),
    _e("fee-waiver-motion", "GR 34.0100", "Motion and Declaration for "
       "Waiver of Civil Fees and Surcharges", "uncommon",
       ["starting_divorce"], "partial",
       ["income.client_gross", "income.client_net"]),
    _e("fee-waiver-statement", "GR 34.0300", "Financial Statement (Fee "
       "Waiver)", "uncommon", ["starting_divorce"], "partial",
       ["income.client_gross", "income.client_net",
        "expenses.monthly_total", "notes.assets", "notes.debts",
        "household.size", "benefits.receiving", "benefits.details"],
       implemented=True, wizard="fee_waiver",
       note="The client-completed half of the GR 34 fee-waiver "
            "application (the GR 34.0100 motion is prepared by the "
            "office from this data). The court decides — the wizard "
            "says so."),
    _e("fee-waiver-order", "GR 34.0500", "Order Re Waiver of Civil Fees "
       "and Surcharges", "uncommon", ["starting_divorce"], "none"),
    _e("public-assistance-declaration", "FL All Family 132", "Public "
       "Assistance Declaration", "uncommon",
       ["starting_divorce", "temporary_orders"], "partial"),
    _e("notice-address-change", "FL All Family 120", "Notice of Address "
       "Change", "uncommon", ["relocation"], "partial",
       ["client.address"],
       note="For moves WITHIN the same school district; moves out of "
            "the district use the FL Relocate series."),
    _e("motion-default", "FL All Family 161", "Motion for Default",
       "uncommon", ["finalizing"], "none"),
    _e("order-default", "FL All Family 162", "Order on Motion for "
       "Default", "uncommon", ["finalizing"], "none"),
    _e("military-dependent-notice", "FL All Family 103", "Notice re "
       "Military Dependent", "uncommon", ["starting_divorce"], "none"),
    _e("supervised-visitation-ack", "FL All Family 141", "Supervised "
       "Visitation Acknowledgment", "uncommon", ["starting_divorce"],
       "none"),
    _e("modify-support-petition", "FL Modify 501", "Petition to Modify "
       "Child Support Order", "uncommon", ["changing_order"], "partial",
       ["income.client_gross", "income.client_net",
        "income.other_parent_net"],
       implemented=True, wizard="modify_support",
       note="Registry note: FL Modify 501 is the CHILD SUPPORT "
            "modification petition; the parenting-plan petition is "
            "FL Modify 601 (below). The support wizard re-uses the "
            "Financial Declaration's vault financials as confirm "
            "cards."),
    _e("modify-parenting-summons", "FL Modify 600", "Summons: Notice "
       "about Petition to Change a Parenting Plan, Residential Schedule "
       "or Custody Order", "uncommon", ["changing_order"], "none"),
    _e("modify-parenting-petition", "FL Modify 601", "Petition to "
       "Change a Parenting Plan, Residential Schedule or Custody Order",
       "uncommon", ["changing_order"], "partial",
       implemented=True, wizard="modify_parenting"),
    _e("modify-adequate-cause-motion", "FL Modify 603", "Motion for "
       "Adequate Cause Decision (to Change a Parenting/Custody Order)",
       "uncommon", ["changing_order"], "partial"),
    _e("modify-adequate-cause-order", "FL Modify 604", "Order on "
       "Adequate Cause to Change a Parenting/Custody Order", "uncommon",
       ["changing_order"], "none"),
    _e("modify-parenting-final-order", "FL Modify 610", "Final Order "
       "and Findings on Petition to Change a Parenting Plan, "
       "Residential Schedule or Custody Order", "uncommon",
       ["changing_order"], "none"),
    _e("modify-temporary-motion", "FL Modify 623", "Motion for "
       "Temporary Family Law Order (Modification)", "uncommon",
       ["changing_order", "temporary_orders"], "partial"),
    _e("relocate-notice", "FL Relocate 701", "Notice of Intent to Move "
       "with Children (Relocation)", "uncommon", ["relocation"],
       "partial", ["client.address"],
       source_url="https://www.courts.wa.gov/forms/documents/"
                  "FL%20Relocate%20701%20Notice%20of%20Intent%20to%20Move"
                  "%20with%20Children_2022%2001%20(2).pdf",
       implemented=True, wizard="relocation_notice",
       note="Deadlines in relocation are short and statutory — the "
            "wizard urges the client to send it promptly and the "
            "office tracks the actual dates."),
    _e("relocate-objection-summons", "FL Relocate 720", "Summons: "
       "Notice of Objection about Moving with Children and Petition "
       "about Changing a Parenting/Custody Order (Relocation)",
       "uncommon", ["relocation"], "none"),
    _e("relocate-objection", "FL Relocate 721", "Objection about "
       "Moving with Children and Petition about Changing a "
       "Parenting/Custody Order (Relocation)", "uncommon",
       ["relocation"], "partial",
       implemented=True, wizard="relocation_objection",
       note="The other side of relocation: the wizard captures the "
            "objection and the client's counter-proposal."),
    _e("relocate-prevent-move-motion", "FL Relocate 725", "Motion for "
       "Temporary Order Preventing Move with Children", "uncommon",
       ["relocation", "temporary_orders"], "partial"),
    _e("parentage-petition", "FL Parentage 301", "Petition to Decide "
       "Parentage", "uncommon", ["parentage"], "partial",
       source_url="https://www.courts.wa.gov/forms/documents/"
                  "FL%20Parentage%20301%20Petition%20to%20Decide%20"
                  "Parentage_2019%2001.pdf",
       implemented=True, wizard="parentage_petition"),
    _e("parentage-acknowledgment", "DOH 422-159", "Acknowledgment of "
       "Parentage (WA Dept. of Health)", "uncommon", ["parentage"],
       "partial",
       ["spouse.name", "spouse.date_of_birth", "spouse.birth_place",
        "client.date_of_birth", "client.birth_place", "client.address",
        "client.phone"],
       source_url="https://doh.wa.gov/sites/default/files/legacy/"
                  "Documents/Pubs/422-159-AcknowledgmentOfParentage.pdf",
       implemented=True, wizard="parentage_acknowledgment",
       note="The voluntary acknowledgment both parents sign (usually "
            "at the hospital) — a vital-records form, NOT an FL form; "
            "it has the legal effect of a court finding of parentage "
            "once filed. Number and title verified on the official "
            "DOH form PDF (rev. 03/2021). (FL Parentage 303 is the "
            "Residential Schedule — see below — not this form.)"),
    _e("parentage-residential-schedule", "FL Parentage 303",
       "Residential Schedule", "uncommon", ["parentage"], "partial",
       source_url="https://www.courts.wa.gov/forms/documents/"
                  "FL%20Parentage%20303%20Residential%20Schedule_2021"
                  "%2002.pdf",
       note="Older parentage filings cite a 'Residential Schedule' at "
            "FL Parentage 304; the current official PDF is 303 "
            "(303 verified on courts.wa.gov)."),
    _e("parentage-plan-petition", "FL Parentage 331", "Petition for a "
       "Parenting Plan, Residential Schedule and/or Child Support",
       "uncommon", ["parentage"], "partial"),
    _e("parentage-plan-response", "FL Parentage 332", "Response to "
       "Petition for a Parenting Plan, Residential Schedule and/or "
       "Child Support", "uncommon", ["parentage", "responding"],
       "partial"),
    _e("contempt-motion", "FL All Family 165", "Motion for Contempt "
       "Hearing", "uncommon", ["changing_order"], "partial",
       note="Number verified as cited in superior-court local rules "
            "(e.g. Clark County LCR 4.1) for the contempt motion form."),
    _e("sealed-health-cover", "FL All Family 012", "Sealed Personal "
       "Health Care Records (Cover Sheet)", "uncommon",
       ["temporary_orders"], "none"),
    _e("sealed-reports-cover", "FL All Family 013", "Sealed Confidential "
       "Reports (Cover Sheet)", "uncommon", ["temporary_orders"],
       "none"),
    _e("email-service-agreement", "All Civil 006", "Email Service "
       "Agreement", "uncommon", ["starting_divorce"], "partial",
       ["client.email"]),

    # ------------------------------------------------------------------
    # RARE — protection orders, evaluators, and the long tail
    # ------------------------------------------------------------------
    _e("protection-order-petition", "PO 001", "Petition for Protection "
       "Order (RCW 7.105)", "rare", ["protection"], "partial",
       source_url="https://www.courts.wa.gov/forms/documents/"
                  "PO%20001%20Petition%20for%20Protection%20Order_2024"
                  "_01_CHS.pdf",
       note="Protection orders use the PO series, not 'FL Protect'. "
            "Safety note: a client who needs this needs it NOW — staff "
            "handle protection filings directly and urgently; a "
            "self-serve wizard is deliberately not the front door."),
    _e("parentage-immediate-restraining", "FL Parentage 321", "Motion "
       "for Immediate Restraining Order (Ex Parte) (Parentage)", "rare",
       ["parentage", "protection"], "none"),
    _e("parentage-temporary-motion", "FL Parentage 323", "Motion for "
       "Temporary Family Law Order and Restraining Order (Parentage)",
       "rare", ["parentage", "temporary_orders"], "partial"),
    _e("parentage-temporary-order", "FL Parentage 324", "Temporary "
       "Family Law Order (Parentage)", "rare",
       ["parentage", "temporary_orders"], "partial"),
    _e("parentage-sexual-assault-allegation", "FL Parentage 365",
       "Sexual Assault Allegation", "rare", ["parentage"], "none",
       note="Filed and served together with FL Parentage 301 when "
            "alleged; handle with the attorney, never as a casual "
            "portal task."),
    _e("relocate-final-ex-parte-motion", "FL Relocate 706", "Ex Parte "
       "Motion for Final Order Changing Parenting Plan — No Objection "
       "to Moving with Children (Relocation)", "rare", ["relocation"],
       "none", verified=False,
       note="Number seen in secondary form catalogs; not yet confirmed "
            "against the official list."),
    _e("relocate-final-ex-parte-order", "FL Relocate 707", "Ex Parte "
       "Order on Motion for Final Order Changing Parenting Plan — "
       "Moving with Children (Relocation)", "rare", ["relocation"],
       "none", verified=False,
       note="Number seen in secondary form catalogs; not yet confirmed "
            "against the official list."),
    _e("gal-order", "FL All Family 146", "Order Appointing Guardian Ad "
       "Litem for Child", "rare", ["starting_divorce"], "none"),
    _e("parenting-evaluator-order", "FL All Family 148", "Order "
       "Appointing Parenting Evaluator/Investigator", "rare",
       ["starting_divorce"], "none"),
    _e("visits-petition", "FL Visits 476", "Petition for Visits "
       "(Nonparent / Grandparent Visitation, RCW 26.11)", "rare",
       ["parentage"], "partial", verified=False,
       note="The Visits series exists (post-2021 Chapter 26.11 RCW), "
            "but this exact number was found only in secondary form "
            "catalogs — verify against the official list before "
            "relying on it."),
    _e("de-facto-parentage", "—", "De Facto Parentage (RCW 26.26A.440)",
       "rare", ["parentage"], "partial", verified=False,
       note="No dedicated mandatory state form number verified. "
            "De facto parentage is pleaded through the parentage "
            "series (see FL Parentage 301) — confirm the current "
            "procedure with the official forms list before use."),
    _e("committed-intimate-relationship", "—", "Committed Intimate "
       "Relationship (formerly 'meretricious relationship') — "
       "Complaint/Petition", "rare", ["starting_divorce"], "partial",
       verified=False,
       note="No mandatory Washington state form verified; these cases "
            "proceed by locally drafted pleading. Cataloged so the "
            "library shows the gap honestly."),
    _e("qdro-data", "—", "Qualified Domestic Relations Order (QDRO) — "
       "Retirement Division Data Sheet", "rare", ["finalizing"],
       "partial", verified=False,
       note="QDROs are drafted per the retirement plan's own "
            "requirements — there is no Washington state QDRO form. "
            "The firm collects the plan data and drafts (or refers) "
            "the order."),
]

LIBRARY_BY_SLUG = {e["slug"]: e for e in LIBRARY}

TIERS = ("common", "uncommon", "rare")

SCENARIOS = {
    "starting_divorce": "Starting a divorce",
    "responding": "Responding to papers you were served",
    "uncontested": "We agree on everything",
    "temporary_orders": "Temporary orders while we wait",
    "changing_order": "Changing an existing order",
    "relocation": "Moving with the kids",
    "protection": "Protection orders",
    "parentage": "Parentage",
    "finalizing": "Finishing a case",
}


def library_entry(slug):
    return LIBRARY_BY_SLUG.get(slug)


def implemented_entries():
    """Catalog entries that have a working portal wizard."""
    return [e for e in LIBRARY if e["implemented"] and e["wizard"]]


# ----------------------------------------------------------------------------
# Wizard definitions — the implemented common tier
# ----------------------------------------------------------------------------
# Field "vault" names the fact the field confirms or edits. Confirm
# behaviour (render the saved value as a card, track changes, staff
# confirmation on import) is driven entirely by this binding.
CHILDREN_REPEATER = {
    "name": "children", "label": "Your children", "type": "repeater",
    "vault": "children", "target": ("children",),
    "item_fields": [
        {"name": "name", "label": "Full name", "type": "text"},
        {"name": "date_of_birth", "label": "Date of birth",
         "type": "date"},
    ],
    "help": "List each child of this relationship. The office keeps "
            "this list on your file.",
}

WIZARD_DEFS = {
    # ------------------------------------------------------------------
    # 1. Declaration — the flagship (FL All Family 135)
    # ------------------------------------------------------------------
    "declaration": {
        "key": "declaration",
        "slug": "declaration",
        "title": "Declaration",
        "official": "FL All Family 135",
        "minutes": 20,
        "description": "Your own statement to the court, in your "
                       "words — who your family is, how things are "
                       "going, and what you're asking for. We guide "
                       "you section by section; there are no wrong "
                       "answers, just your facts.",
        "explainer": "A declaration is how you 'speak' to the judge "
                     "on paper. Write like you're explaining things "
                     "to a fair person who doesn't know your family "
                     "yet. Short, honest, and specific beats long and "
                     "heated, every time.",
        "case_required": True,
        "attest": True,
        "generate": {"kind": "declaration", "category": "pleadings",
                     "file_stem": "Declaration"},
        "steps": [
            {"title": "About you and your family",
             "explainer": "We filled in what the office already has — "
                          "just check that it's still right.",
             "fields": [
                 {"name": "spouse_name",
                  "label": "Your spouse / the other party's full legal "
                           "name",
                  "type": "text", "vault": "spouse.name",
                  "target": ("client", "spouse_name")},
                 {"name": "marriage_date", "label": "Date of marriage",
                  "type": "date", "vault": "marriage.date",
                  "target": ("vault", "marriage.date")},
                 {"name": "marriage_place",
                  "label": "Place of marriage (city, state)",
                  "type": "text", "vault": "marriage.place",
                  "target": ("vault", "marriage.place")},
                 {"name": "separation_date",
                  "label": "Date you separated (if you have)",
                  "type": "date", "vault": "separation.date",
                  "target": ("vault", "separation.date")},
                 dict(CHILDREN_REPEATER),
             ]},
            {"title": "Your children",
             "explainer": "This is the heart of most declarations. "
                          "Stick to what you've seen yourself — "
                          "dates and examples help the judge.",
             "fields": [
                 {"name": "children_week", "label": "A typical week "
                  "with the children", "type": "textarea", "rows": 6,
                  "prompt": "Who gets them up, feeds them, takes them "
                            "to school? What does a normal weekday and "
                            "weekend look like right now?",
                  "guidance": "A paragraph or two is plenty."},
                 {"name": "children_school", "label": "School, health, "
                  "and how they're doing", "type": "textarea", "rows": 5,
                  "prompt": "How are they doing in school? Any health, "
                            "counseling, or special needs the court "
                            "should know about? Who takes them to "
                            "appointments?",
                  "guidance": "Facts and examples help more than "
                              "conclusions."},
                 {"name": "children_concerns", "label": "Anything about "
                  "the children you're worried about?",
                  "type": "textarea", "rows": 5,
                  "prompt": "Optional. If something worries you — "
                            "missed exchanges, things said or done "
                            "around the children — describe what "
                            "happened, with dates if you remember them.",
                  "guidance": "You can leave this blank."},
             ]},
            {"title": "Work and money",
             "explainer": "Confirm the basics, then add anything the "
                          "court should understand about your "
                          "situation.",
             "fields": [
                 {"name": "client_employer", "label": "Your employer",
                  "type": "text", "vault": "client.employer",
                  "target": ("vault", "client.employer")},
                 {"name": "client_gross_income",
                  "label": "Your monthly GROSS income ($)",
                  "type": "money", "vault": "income.client_gross",
                  "target": ("financial", "client_gross_income")},
                 {"name": "client_net_income",
                  "label": "Your monthly NET (take-home) income ($)",
                  "type": "money", "vault": "income.client_net",
                  "target": ("financial", "client_net_income")},
                 {"name": "money_story", "label": "Anything about "
                  "work or money the court should understand",
                  "type": "textarea", "rows": 5,
                  "prompt": "Hours changes, a lost job, who pays which "
                            "bills right now, debts you're carrying "
                            "alone — whatever affects what you're "
                            "asking for.",
                  "guidance": "Optional, but often the most useful "
                              "part."},
             ]},
            {"title": "Safety concerns",
             "explainer": "Only if this applies to you. If you and "
                          "your children are safe and this section "
                          "isn't relevant, skip it — nothing here is "
                          "required. If the office needs to act fast "
                          "to keep you safe, call them instead of "
                          "writing it here.",
             "fields": [
                 {"name": "safety_concerns", "label": "Describe any "
                  "safety concerns", "type": "textarea", "rows": 6,
                  "prompt": "Threats, violence, intimidation, stalking, "
                            "substance abuse that affects the "
                            "children — what happened, and roughly "
                            "when. Include whether police or a court "
                            "were ever involved.",
                  "guidance": "Leave blank if this doesn't apply. "
                              "What you write goes only to the office "
                              "and the court — never to the other "
                              "party through this portal."},
             ]},
            {"title": "What you're asking the court to do",
             "explainer": "Finally — what do you want the judge to "
                          "order? Check what applies and explain in "
                          "your own words.",
             "fields": [
                 {"name": "asks", "label": "I'm asking the court to…",
                  "type": "checkboxes",
                  "options": [
                      "Approve the parenting plan I'm proposing",
                      "Order child support",
                      "Divide our property and debts fairly",
                      "Order spousal support (maintenance)",
                      "Order the other party to help with legal fees",
                      "Something else (explained below)",
                  ]},
                 {"name": "asks_details", "label": "Explain what "
                  "you're asking for", "type": "textarea", "rows": 6,
                  "prompt": "In your own words: if the judge could "
                            "give you exactly what you're asking for, "
                            "what would that look like for you and "
                            "the children?",
                  "guidance": "Be specific where you can — schedules, "
                              "amounts, dates."},
             ]},
        ],
    },

    # ------------------------------------------------------------------
    # 2. Financial Declaration (FL All Family 131)
    # ------------------------------------------------------------------
    "financial_declaration": {
        "key": "financial_declaration",
        "slug": "financial-declaration",
        "title": "Financial Declaration",
        "official": "FL All Family 131",
        "minutes": 15,
        "description": "Your income, expenses, assets, and debts — "
                       "the financial picture the court works from. "
                       "Most of this confirms what you've already told "
                       "us.",
        "explainer": "The court uses this to set support and divide "
                     "property fairly. Estimates are fine where the "
                     "form says so — being complete matters more than "
                     "being perfect.",
        "case_required": True,
        "generate": {"kind": "data_sheet", "category": "pleadings",
                     "file_stem": "Financial_Declaration_Client_Data"},
        "steps": [
            {"title": "Your job and income",
             "explainer": "Check off what we have, and fix anything "
                          "that's changed.",
             "fields": [
                 {"name": "client_employer", "label": "Your employer",
                  "type": "text", "vault": "client.employer",
                  "target": ("vault", "client.employer")},
                 {"name": "client_job_title", "label": "Your job title",
                  "type": "text", "vault": "client.job_title",
                  "target": ("vault", "client.job_title")},
                 {"name": "client_gross_income",
                  "label": "Monthly GROSS income ($)", "type": "money",
                  "required": True, "vault": "income.client_gross",
                  "target": ("financial", "client_gross_income")},
                 {"name": "client_net_income",
                  "label": "Monthly NET (take-home) income ($)",
                  "type": "money", "required": True,
                  "vault": "income.client_net",
                  "target": ("financial", "client_net_income")},
                 {"name": "other_income_notes",
                  "label": "Other income (overtime, second job, "
                         "benefits, help from family…)",
                  "type": "textarea", "rows": 3,
                  "vault": "notes.other_income",
                  "target": ("financial", "other_income_notes")},
             ]},
            {"title": "Monthly expenses",
             "explainer": "Your best monthly estimates for each — "
                          "the office will total them with you.",
             "fields": [
                 {"name": "housing_expenses",
                  "label": "Housing — rent or mortgage ($)",
                  "type": "money", "vault": "expenses.housing",
                  "target": ("financial", "housing_expenses")},
                 {"name": "utility_expenses",
                  "label": "Utilities — power, water, phone, "
                         "internet ($)", "type": "money",
                  "vault": "expenses.utilities",
                  "target": ("financial", "utility_expenses")},
                 {"name": "food_expenses",
                  "label": "Food and household supplies ($)",
                  "type": "money", "vault": "expenses.food",
                  "target": ("financial", "food_expenses")},
                 {"name": "transportation_expenses",
                  "label": "Transportation — car payment, fuel, "
                         "insurance ($)", "type": "money",
                  "vault": "expenses.transportation",
                  "target": ("financial", "transportation_expenses")},
                 {"name": "insurance_expenses",
                  "label": "Insurance — health, life, other ($)",
                  "type": "money", "vault": "expenses.insurance",
                  "target": ("financial", "insurance_expenses")},
                 {"name": "other_expenses",
                  "label": "Everything else ($)", "type": "money",
                  "vault": "expenses.other",
                  "target": ("financial", "other_expenses")},
                 {"name": "monthly_expenses",
                  "label": "Your total monthly expenses ($)",
                  "type": "money", "vault": "expenses.monthly_total",
                  "target": ("financial", "monthly_expenses"),
                  "help": "If the lines above add up differently, use "
                          "the total you believe is right — the "
                          "office will reconcile it with you."},
             ]},
            {"title": "Assets and accounts",
             "explainer": "What you own. Rough values are fine — "
                          "the office will verify figures before "
                          "anything is filed.",
             "fields": [
                 {"name": "assets_notes",
                  "label": "Assets — home, vehicles, retirement, "
                         "valuables", "type": "textarea", "rows": 4,
                  "vault": "notes.assets",
                  "target": ("financial", "assets_notes"),
                  "prompt": "One per line helps: what it is, roughly "
                            "what it's worth, and whose name is on "
                            "it."},
                 {"name": "accounts_notes",
                  "label": "Bank and investment accounts",
                  "type": "textarea", "rows": 4,
                  "vault": "notes.accounts",
                  "target": ("financial", "accounts_notes"),
                  "prompt": "Institution and type of account (e.g. "
                            "'Peninsula Credit Union — checking'). "
                            "Balances change daily; approximate is "
                            "fine here."},
             ]},
            {"title": "Debts",
             "explainer": "What you owe, and what you're paying "
                          "each month.",
             "fields": [
                 {"name": "debts_notes",
                  "label": "Debts — cards, loans, arrears",
                  "type": "textarea", "rows": 4,
                  "vault": "notes.debts",
                  "target": ("financial", "debts_notes"),
                  "prompt": "One per line helps: who it's owed to, "
                            "roughly how much, and whose name is on "
                            "it."},
                 {"name": "debt_payments_monthly",
                  "label": "Total monthly debt payments ($)",
                  "type": "money", "vault": "expenses.debt_payments",
                  "target": ("financial", "debt_payments_monthly")},
             ]},
        ],
    },

    # ------------------------------------------------------------------
    # 3. Confidential Information Form (FL All Family 001)
    # ------------------------------------------------------------------
    "confidential_information": {
        "key": "confidential_information",
        "slug": "confidential-information",
        "title": "Confidential Information Form",
        "official": "FL All Family 001",
        "minutes": 10,
        "description": "The private details the court needs but "
                       "keeps sealed — Social Security numbers, ID "
                       "numbers, account information. Almost all of "
                       "this is confirming what's already on your "
                       "file.",
        "explainer": "This form is filed under seal (GR 22) — the "
                     "public never sees it. It's how the court and "
                     "the state identify everyone without putting "
                     "private numbers in public documents.",
        "case_required": False,
        "generate": {"kind": "data_sheet", "category": "pleadings",
                     "file_stem": "Confidential_Information_Client_Data"},
        "steps": [
            {"title": "About you",
             "explainer": "Confirm your details exactly as they "
                          "appear on your ID.",
             "fields": [
                 {"name": "date_of_birth", "label": "Your date of "
                  "birth", "type": "date",
                  "vault": "client.date_of_birth",
                  "target": ("client", "date_of_birth")},
                 {"name": "ssn", "label": "Your Social Security "
                  "number", "type": "text", "vault": "client.ssn",
                  "target": ("client", "ssn"),
                  "help": "Stored encrypted. It goes only on the "
                          "sealed court form."},
                 {"name": "driver_license", "label": "Driver's "
                  "license / state ID number", "type": "text",
                  "vault": "client.driver_license",
                  "target": ("vault", "client.driver_license")},
                 {"name": "address", "label": "Your mailing address",
                  "type": "textarea", "rows": 3,
                  "vault": "client.address",
                  "target": ("client", "address")},
                 {"name": "phone", "label": "Your phone number",
                  "type": "tel", "vault": "client.phone",
                  "target": ("client", "phone")},
             ]},
            {"title": "The other party",
             "explainer": "What you know about your spouse / the "
                          "other parent. 'Don't know' is an honest "
                          "answer — leave a field blank if you're "
                          "unsure.",
             "fields": [
                 {"name": "spouse_name", "label": "Their full legal "
                  "name", "type": "text", "vault": "spouse.name",
                  "target": ("client", "spouse_name")},
                 {"name": "spouse_dob", "label": "Their date of "
                  "birth", "type": "date",
                  "vault": "spouse.date_of_birth",
                  "target": ("client", "spouse_dob")},
                 {"name": "spouse_ssn", "label": "Their Social "
                  "Security number (if you know it)", "type": "text",
                  "vault": "spouse.ssn",
                  "target": ("vault", "spouse.ssn")},
                 {"name": "service_address", "label": "Address where "
                  "they can be served papers", "type": "textarea",
                  "rows": 2, "vault": "service.address",
                  "target": ("vault", "service.address"),
                  "help": "Home or work — wherever a process server "
                          "can hand them documents."},
             ]},
            {"title": "Your children",
             "explainer": "The court keeps the children's details "
                          "on this sealed form too.",
             "fields": [dict(CHILDREN_REPEATER)]},
            {"title": "Financial accounts (protected)",
             "explainer": "For the sealed attachment: institutions "
                          "and the LAST 4 DIGITS ONLY. Never type a "
                          "full account number into the portal.",
             "fields": [
                 {"name": "accounts_protected",
                  "label": "Accounts — institution + last 4 digits",
                  "type": "textarea", "rows": 4,
                  "vault": "client.accounts_protected",
                  "target": ("vault", "client.accounts_protected"),
                  "prompt": "e.g. 'Peninsula Credit Union checking "
                            "…4471' — one per line."},
             ]},
        ],
    },

    # ------------------------------------------------------------------
    # 4. Certificate of Dissolution — vital statistics (DOH 422-027)
    # ------------------------------------------------------------------
    "certificate_dissolution": {
        "key": "certificate_dissolution",
        "slug": "certificate-dissolution",
        "title": "Certificate of Dissolution (Vital Statistics)",
        "official": "DOH 422-027",
        "minutes": 8,
        "description": "The state health department's record of the "
                       "marriage and its end — birth names, birth "
                       "places, and the marriage facts, exactly as "
                       "they'll appear on the official certificate.",
        "explainer": "This goes to the Washington State Department "
                     "of Health. Names should match birth records — "
                     "use birth (maiden) names where it asks, even if "
                     "they're different now.",
        "case_required": False,
        "generate": {"kind": "data_sheet", "category": "pleadings",
                     "file_stem": "Certificate_of_Dissolution_Data"},
        "steps": [
            {"title": "About you",
             "fields": [
                 {"name": "birth_name", "label": "Your birth name "
                  "(before any marriage)", "type": "text",
                  "vault": "client.birth_name",
                  "target": ("vault", "client.birth_name")},
                 {"name": "birth_place", "label": "Your place of "
                  "birth (city, state)", "type": "text",
                  "vault": "client.birth_place",
                  "target": ("vault", "client.birth_place")},
                 {"name": "date_of_birth", "label": "Your date of "
                  "birth", "type": "date",
                  "vault": "client.date_of_birth",
                  "target": ("client", "date_of_birth")},
             ]},
            {"title": "About your spouse",
             "fields": [
                 {"name": "spouse_name", "label": "Their full legal "
                  "name", "type": "text", "vault": "spouse.name",
                  "target": ("client", "spouse_name")},
                 {"name": "spouse_birth_name", "label": "Their birth "
                  "name (before any marriage)", "type": "text",
                  "vault": "spouse.birth_name",
                  "target": ("vault", "spouse.birth_name")},
                 {"name": "spouse_birth_place", "label": "Their "
                  "place of birth (city, state)", "type": "text",
                  "vault": "spouse.birth_place",
                  "target": ("vault", "spouse.birth_place")},
                 {"name": "spouse_dob", "label": "Their date of "
                  "birth", "type": "date",
                  "vault": "spouse.date_of_birth",
                  "target": ("client", "spouse_dob")},
             ]},
            {"title": "The marriage",
             "fields": [
                 {"name": "marriage_date", "label": "Date of "
                  "marriage", "type": "date", "vault": "marriage.date",
                  "target": ("vault", "marriage.date")},
                 {"name": "marriage_place", "label": "Place of "
                  "marriage (city, county, state)", "type": "text",
                  "vault": "marriage.place",
                  "target": ("vault", "marriage.place")},
                 dict(CHILDREN_REPEATER),
             ]},
        ],
    },

    # ------------------------------------------------------------------
    # 5. Petition for Divorce — client data capture (FL Divorce 201)
    # ------------------------------------------------------------------
    "petition_divorce": {
        "key": "petition_divorce",
        "slug": "petition-divorce",
        "title": "Petition for Divorce — Your Information",
        "official": "FL Divorce 201",
        "minutes": 15,
        "description": "Everything the petition needs from you: the "
                       "marriage facts, your children, a first "
                       "picture of property and debts, and what you're "
                       "asking for. Your attorney drafts the actual "
                       "petition from this.",
        "explainer": "The petition is the document that starts the "
                     "divorce. You supply the facts; the office turns "
                     "them into the formal filing and reviews it with "
                     "you before anything goes to the court.",
        "case_required": False,
        "generate": {"kind": "petition", "category": "pleadings",
                     "file_stem": "Petition_for_Dissolution_DRAFT"},
        "steps": [
            {"title": "The marriage",
             "explainer": "Confirm the marriage facts and your "
                          "current living situation.",
             "fields": [
                 {"name": "action_type", "label": "What are we "
                  "filing?", "type": "radio_cards",
                  "options": [
                      "Dissolution — end the marriage (divorce)",
                      "Legal separation",
                      "Invalidity — declare the marriage invalid "
                      "(annulment)"],
                  "help": "All three use the same court forms (the "
                          "FL Divorce series). If you're not sure, "
                          "choose dissolution and talk it through "
                          "with the office — the choice can be "
                          "changed before filing."},
                 {"name": "marriage_date", "label": "Date of "
                  "marriage", "type": "date", "required": True,
                  "vault": "marriage.date",
                  "target": ("vault", "marriage.date")},
                 {"name": "marriage_place", "label": "Place of "
                  "marriage (city, state)", "type": "text",
                  "vault": "marriage.place",
                  "target": ("vault", "marriage.place")},
                 {"name": "separation_date", "label": "Date you "
                  "separated (if you have)", "type": "date",
                  "vault": "separation.date",
                  "target": ("vault", "separation.date")},
                 {"name": "living_situation", "label": "Right now…",
                  "type": "radio_cards",
                  "options": ["We still live together",
                              "We live apart",
                              "One of us moved out recently"],
                  "help": "Just the current picture — it helps the "
                          "office plan service and temporary orders."},
             ]},
            {"title": "Your children",
             "fields": [dict(CHILDREN_REPEATER)]},
            {"title": "Property and debts — the first picture",
             "explainer": "Don't worry about completeness yet — "
                          "this is the overview the petition needs. "
                          "The Financial Declaration goes deeper.",
             "fields": [
                 {"name": "property_request",
                  "label": "Property — what you have and what you're "
                         "asking for", "type": "textarea", "rows": 5,
                  "prompt": "Home, vehicles, accounts, retirement, "
                            "household items — and how you'd like "
                            "them divided.",
                  "default_hint": "A just and equitable division of "
                                  "all community and separate "
                                  "property is the standard request."},
                 {"name": "debts_overview", "label": "Debts — the "
                  "overview", "type": "textarea", "rows": 4,
                  "prompt": "Cards, loans, taxes owed — roughly what "
                            "and whose name they're in."},
             ]},
            {"title": "What you're asking for",
             "fields": [
                 {"name": "maintenance_request",
                  "label": "Spousal support (maintenance)",
                  "type": "radio_cards",
                  "options": ["None", "Temporary maintenance",
                              "Permanent maintenance",
                              "Maintenance to be determined"],
                  "help": "Not sure? Choose 'to be determined' and "
                          "talk it through with the office."},
                 {"name": "name_change", "label": "Do you want to "
                  "restore a former name?", "type": "text",
                  "help": "Optional. Write the full former name "
                          "exactly as you want it restored."},
                 {"name": "other_relief", "label": "Anything else "
                  "you're asking the court for?", "type": "textarea",
                  "rows": 4},
             ]},
        ],
    },

    # ------------------------------------------------------------------
    # 6. Parenting Plan — client portions (FL All Family 140)
    # ------------------------------------------------------------------
    "parenting_plan": {
        "key": "parenting_plan",
        "slug": "parenting-plan",
        "title": "Parenting Plan — Your Proposal",
        "official": "FL All Family 140",
        "minutes": 20,
        "description": "Your proposed plan for the children: where "
                       "they'll live and when, how holidays split, "
                       "who decides what, and how exchanges work. "
                       "Your attorney turns this into the formal "
                       "plan.",
        "explainer": "Judges look for plans built around the "
                     "children's routines — school, activities, "
                     "bedtimes. Describe the schedule you'd actually "
                     "want a normal week to look like.",
        "case_required": True,
        "generate": {"kind": "parenting_plan", "category": "pleadings",
                     "file_stem": "Parenting_Plan_DRAFT"},
        "steps": [
            {"title": "Your children",
             "fields": [dict(CHILDREN_REPEATER)]},
            {"title": "Where the children live now",
             "fields": [
                 {"name": "living_now", "label": "The current "
                  "arrangement", "type": "textarea", "rows": 5,
                  "prompt": "Where do the children sleep most nights "
                            "right now? How much time do they spend "
                            "with each parent in a typical week?"},
             ]},
            {"title": "The schedule you're proposing",
             "fields": [
                 {"name": "residential_schedule",
                  "label": "Regular weekly schedule", "type": "textarea",
                  "rows": 6,
                  "prompt": "Walk through a normal two-week cycle: "
                            "which nights with which parent, exchange "
                            "days and times. Example: 'With me "
                            "Monday–Friday; with their dad Friday "
                            "6 p.m. to Sunday 6 p.m., alternating "
                            "weekends.'",
                  "guidance": "Specific days and times — 'every "
                              "other weekend' alone isn't enough for "
                              "a judge."},
                 {"name": "holidays", "label": "Holidays and school "
                  "breaks", "type": "textarea", "rows": 5,
                  "prompt": "Thanksgiving, Christmas/winter break, "
                            "spring break, summer, birthdays, "
                            "Mother's/Father's Day — how should they "
                            "rotate?"},
             ]},
            {"title": "Decisions and any limits",
             "explainer": "Who decides the big things — school, "
                          "medical care, activities — and whether "
                          "anything needs limits for the children's "
                          "safety.",
             "fields": [
                 {"name": "decision_making", "label": "Major "
                  "decisions should be made…", "type": "radio_cards",
                  "options": ["Jointly — both parents together",
                              "By me alone",
                              "By the other parent alone"]},
                 {"name": "decision_details", "label": "Details "
                  "about decision-making", "type": "textarea",
                  "rows": 3,
                  "prompt": "Anything specific — e.g. one parent "
                            "handles medical decisions, or decisions "
                            "about a particular child."},
                 {"name": "restrictions", "label": "Do any of these "
                  "apply to the other parent?", "type": "checkboxes",
                  "options": [
                      "None of these",
                      "Substance abuse that affects the children",
                      "Domestic violence or abuse",
                      "Neglect of the children",
                      "Time with the children should be supervised",
                      "Something else (explained below)",
                  ]},
                 {"name": "restrictions_details", "label": "If any "
                  "apply, explain briefly", "type": "textarea",
                  "rows": 4,
                  "prompt": "Facts only — what happened and when. "
                            "The office will talk this through with "
                            "you before anything is filed.",
                  "guidance": "Leave blank if none apply."},
             ]},
            {"title": "Getting the children back and forth",
             "fields": [
                 {"name": "transportation", "label": "Exchanges and "
                  "transportation", "type": "textarea", "rows": 4,
                  "prompt": "Where do exchanges happen, and who "
                            "drives? Any safety or practical concerns "
                            "about exchanges?"},
             ]},
        ],
    },

    # ------------------------------------------------------------------
    # 7. Child Support Worksheet data (WSCSS Worksheets)
    # ------------------------------------------------------------------
    "support_worksheet_data": {
        "key": "support_worksheet_data",
        "slug": "child-support-worksheet",
        "title": "Child Support Worksheet — Your Figures",
        "official": "WSCSS — Worksheets",
        "minutes": 8,
        "description": "Confirm the incomes and children's costs "
                       "the support worksheet runs on. The office "
                       "generates the worksheet from these figures.",
        "explainer": "Washington support is calculated from both "
                     "parents' net incomes plus the children's "
                     "costs (RCW 26.19). If you're estimating the "
                     "other parent's income, say so — estimates are "
                     "normal at this stage.",
        "case_required": True,
        "generate": {"kind": "support", "category": "other",
                     "file_stem": "Child_Support_Worksheet"},
        "steps": [
            {"title": "Your income",
             "fields": [
                 {"name": "client_gross_income",
                  "label": "Your monthly GROSS income ($)",
                  "type": "money", "required": True,
                  "vault": "income.client_gross",
                  "target": ("financial", "client_gross_income")},
                 {"name": "client_net_income",
                  "label": "Your monthly NET (take-home) income ($)",
                  "type": "money", "required": True,
                  "vault": "income.client_net",
                  "target": ("financial", "client_net_income")},
             ]},
            {"title": "The other parent's income",
             "fields": [
                 {"name": "other_parent_net_income",
                  "label": "Their monthly NET income ($, best "
                         "estimate)", "type": "money",
                  "vault": "income.other_parent_net",
                  "target": ("financial", "other_parent_net_income")},
                 {"name": "other_income_notes",
                  "label": "How you estimated it / anything else "
                         "about their income", "type": "textarea",
                  "rows": 3, "vault": "notes.other_income",
                  "target": ("financial", "other_income_notes")},
             ]},
            {"title": "Children and their costs",
             "fields": [
                 dict(CHILDREN_REPEATER),
                 {"name": "daycare", "label": "Monthly daycare "
                  "costs ($)", "type": "money",
                  "vault": "costs.daycare",
                  "target": ("financial", "daycare")},
                 {"name": "health_insurance",
                  "label": "Monthly health insurance for the "
                         "children ($)", "type": "money",
                  "vault": "costs.health_insurance",
                  "target": ("financial", "health_insurance")},
             ]},
        ],
    },

    # ------------------------------------------------------------------
    # 8. Temporary Orders — client data capture (FL Divorce 223/224)
    # ------------------------------------------------------------------
    "temporary_orders": {
        "key": "temporary_orders",
        "slug": "temporary-orders",
        "title": "Temporary Orders — What You Need Now",
        "official": "FL Divorce 223 / 224",
        "minutes": 12,
        "description": "Temporary orders cover the time between "
                       "now and the final decree: where everyone "
                       "lives, support, time with the children, and "
                       "safety. Tell us what you need; the office "
                       "prepares the motion (FL Divorce 223) and the "
                       "proposed order (FL Divorce 224).",
        "explainer": "These orders are meant to keep life stable "
                     "while the case runs — judges grant what's "
                     "reasonable and documented. If you need help "
                     "immediately for safety, call the office rather "
                     "than waiting on this form.",
        "case_required": True,
        "generate": {"kind": "data_sheet", "category": "pleadings",
                     "file_stem": "Temporary_Orders_Client_Data"},
        "steps": [
            {"title": "What do you need the court to order now?",
             "fields": [
                 {"name": "needs", "label": "I need the court to…",
                  "type": "checkboxes",
                  "options": [
                      "Let me stay in our home for now",
                      "Have the other party move out",
                      "Order temporary child support",
                      "Order temporary spousal support",
                      "Set a temporary parenting schedule",
                      "Restrain the other party from contacting or "
                      "coming near me or the children",
                      "Decide who uses the car / keeps property "
                      "for now",
                      "Order the other party to keep paying certain "
                      "bills",
                      "Something else (explained below)",
                  ]},
             ]},
            {"title": "The details",
             "explainer": "One short paragraph each is fine — the "
                          "office will shape this into the motion.",
             "fields": [
                 {"name": "housing_details", "label": "Housing — "
                  "what's happening and what you need",
                  "type": "textarea", "rows": 4,
                  "prompt": "Who's living where, whose name is on "
                            "the lease or mortgage, what you'd like "
                            "ordered."},
                 {"name": "money_details", "label": "Money — what "
                  "you need to get by", "type": "textarea", "rows": 4,
                  "prompt": "Bills that must be paid, support you "
                            "need, insurance that must stay in "
                            "place."},
                 {"name": "kids_details", "label": "The children — "
                  "the schedule you need for now",
                  "type": "textarea", "rows": 4,
                  "prompt": "The temporary schedule you're asking "
                            "for, and why it works for the children."},
             ]},
            {"title": "Safety and urgency",
             "explainer": "Skip anything that doesn't apply.",
             "fields": [
                 {"name": "restraints_details", "label": "If you're "
                  "asking for restraints, explain why",
                  "type": "textarea", "rows": 4,
                  "prompt": "What has happened that makes you ask "
                            "for a restraining order? Dates help."},
                 {"name": "urgency", "label": "How urgent is this?",
                  "type": "radio_cards",
                  "options": [
                      "Routine — the normal motion calendar is fine",
                      "Urgent — something needs to happen within "
                      "days",
                  ]},
                 {"name": "urgency_details", "label": "If urgent, "
                  "what's the deadline or risk?", "type": "textarea",
                  "rows": 3},
             ]},
        ],
    },

    # ==================================================================
    # UNCOMMON TIER (v2.9.0) — responses, modification, relocation,
    # parentage, sealed attachment, fee waiver
    # ==================================================================

    # ------------------------------------------------------------------
    # 9. Response to Petition + counter-requests (FL Divorce 211)
    # ------------------------------------------------------------------
    "response_marriage": {
        "key": "response_marriage",
        "slug": "response-marriage",
        "title": "Response to the Petition — Your Answers",
        "official": "FL Divorce 211",
        "minutes": 15,
        "description": "You were served with a petition. This walks "
                       "through it topic by topic — what you agree "
                       "with, what you don't, and what you're asking "
                       "for instead. Your attorney drafts the formal "
                       "response (FL Divorce 211) from your answers.",
        "explainer": "A response is due on a deadline the court "
                     "counts from the day you were served — your "
                     "attorney will confirm your exact date. Don't "
                     "wait to start this: rough answers now beat "
                     "perfect answers late.",
        "case_required": True,
        "generate": {"kind": "data_sheet", "category": "pleadings",
                     "file_stem": "Response_Client_Data"},
        "steps": [
            {"title": "The big picture",
             "explainer": "Overall, where do you stand on what the "
                          "petition asks for?",
             "fields": [
                 {"name": "spouse_name", "label": "The petitioner "
                  "(the person who filed) — full legal name",
                  "type": "text", "vault": "spouse.name",
                  "target": ("client", "spouse_name")},
                 {"name": "overall_stance", "label": "Overall, I…",
                  "type": "radio_cards",
                  "options": [
                      "Agree with most of the petition",
                      "Agree with some parts and disagree with "
                      "others",
                      "Disagree with most of the petition",
                      "Haven't been able to read it all yet"]},
                 {"name": "agree_divorce", "label": "Do you agree "
                  "the marriage should end?", "type": "radio_cards",
                  "options": ["Yes", "No", "Not sure yet"],
                  "help": "Washington is no-fault: the court can "
                          "grant the divorce even if one spouse "
                          "disagrees. Your answer still matters for "
                          "how the office plans."},
             ]},
            {"title": "The children",
             "fields": [
                 dict(CHILDREN_REPEATER),
                 {"name": "children_stance", "label": "What the "
                  "petition says about the children — I…",
                  "type": "radio_cards",
                  "options": ["Agree", "Disagree", "Partly agree",
                              "The petition doesn't mention children"]},
                 {"name": "children_details", "label": "What do you "
                  "agree or disagree with, and what do you want "
                  "instead?", "type": "textarea", "rows": 5,
                  "prompt": "Where the children live, the schedule, "
                            "who decides what, support for them — "
                            "anything in the petition about the "
                            "children that doesn't work, say why and "
                            "what you'd propose.",
                  "guidance": "Be specific; 'his schedule ignores "
                              "school nights' helps more than 'it's "
                              "unfair'."},
             ]},
            {"title": "Property and debts",
             "fields": [
                 {"name": "property_stance", "label": "What the "
                  "petition says about property and debts — I…",
                  "type": "radio_cards",
                  "options": ["Agree", "Disagree", "Partly agree",
                              "It doesn't say / I don't understand it"]},
                 {"name": "property_details", "label": "What's "
                  "missing, wrong, or unfair — and what you'd "
                  "propose instead", "type": "textarea", "rows": 5,
                  "prompt": "Property the petition leaves out, debts "
                            "that aren't yours, a division that "
                            "doesn't reflect who owns what."},
             ]},
            {"title": "Support and money",
             "fields": [
                 {"name": "support_stance", "label": "Child support "
                  "in the petition — I…", "type": "radio_cards",
                  "options": ["Agree", "Disagree",
                              "Partly agree",
                              "It doesn't mention support"]},
                 {"name": "maintenance_stance", "label": "Spousal "
                  "support (maintenance) — the petition…",
                  "type": "radio_cards",
                  "options": [
                      "Asks for maintenance for the other party",
                      "Asks for maintenance for me",
                      "Says no maintenance for either of us",
                      "Doesn't mention it"]},
                 {"name": "money_details", "label": "Anything about "
                  "the money the office should know",
                  "type": "textarea", "rows": 4,
                  "prompt": "Income the petition gets wrong, bills "
                            "you're covering alone, support figures "
                            "that don't match reality."},
             ]},
            {"title": "What you're asking for (counter-requests)",
             "explainer": "Your response can ask the court for "
                          "things too. Check what applies.",
             "fields": [
                 {"name": "counter_asks", "label": "I'm asking the "
                  "court to…", "type": "checkboxes",
                  "options": [
                      "Approve a different parenting plan (mine)",
                      "Recalculate child support",
                      "Divide property and debts differently",
                      "Order spousal support (maintenance) for me",
                      "Order the other party to help with legal fees",
                      "Restore my former name",
                      "Dismiss or slow down the case while we talk",
                      "Something else (explained below)"]},
                 {"name": "counter_details", "label": "Explain your "
                  "asks", "type": "textarea", "rows": 5,
                  "prompt": "In your own words: if the judge gave "
                            "you exactly what you're asking for, "
                            "what would that look like?"},
             ]},
        ],
    },

    # ------------------------------------------------------------------
    # 10. Relocation — Notice of Intent to Move (FL Relocate 701)
    # ------------------------------------------------------------------
    "relocation_notice": {
        "key": "relocation_notice",
        "slug": "relocate-notice",
        "title": "Notice of Intent to Move — Your Information",
        "official": "FL Relocate 701",
        "minutes": 12,
        "description": "You're planning to move with the children. "
                       "Washington law requires formal written "
                       "notice (FL Relocate 701) — usually at least "
                       "60 days before the move. This collects what "
                       "the notice needs; the office prepares and "
                       "serves it.",
        "explainer": "Relocation deadlines are set by statute "
                     "(RCW 26.09.430–.480) and they are unforgiving "
                     "— if your move is coming up fast, call the "
                     "office today rather than waiting on this form.",
        "case_required": True,
        "generate": {"kind": "data_sheet", "category": "pleadings",
                     "file_stem": "Relocation_Notice_Client_Data"},
        "steps": [
            {"title": "The move",
             "fields": [
                 {"name": "move_date", "label": "When do you plan "
                  "to move?", "type": "date", "required": True},
                 {"name": "new_address", "label": "New address (or "
                  "city and state, if the exact address isn't set "
                  "yet)", "type": "textarea", "rows": 2,
                  "required": True},
                 {"name": "move_reason", "label": "Why are you "
                  "moving?", "type": "textarea", "rows": 5,
                  "prompt": "A new job, family support, housing "
                            "costs, remarriage, safety — the court "
                            "looks at the real reasons, so be "
                            "straightforward.",
                  "guidance": "Judges are told to look at whether "
                              "the move is made in good faith."},
             ]},
            {"title": "The children and the move",
             "fields": [
                 dict(CHILDREN_REPEATER),
                 {"name": "schools_plan", "label": "School and "
                  "childcare at the new home", "type": "textarea",
                  "rows": 4,
                  "prompt": "What school(s) would they attend? "
                            "How do they compare with where they are "
                            "now?"},
                 {"name": "best_interest", "label": "Why is this "
                  "move good for the children?", "type": "textarea",
                  "rows": 5,
                  "prompt": "Write this the way you would in a "
                            "declaration: family nearby, better "
                            "schools, stability, your support "
                            "network — concrete facts about their "
                            "lives.",
                  "guidance": "These answers often become part of "
                              "your declaration if the move is "
                              "objected to."},
             ]},
            {"title": "Time with the other parent",
             "fields": [
                 {"name": "schedule_proposal", "label": "The "
                  "schedule you're proposing after the move",
                  "type": "textarea", "rows": 5,
                  "prompt": "Longer blocks in summer and holidays? "
                            "Who travels, and who pays for travel? "
                            "Virtual visits in between?"},
                 {"name": "notice_given", "label": "Have you "
                  "already told the other parent about the move?",
                  "type": "radio_cards",
                  "options": ["Not yet",
                              "Yes — informally (talked or texted)",
                              "Yes — in writing"],
                  "help": "Informal notice doesn't replace the "
                          "formal notice the law requires — the "
                          "office handles that."},
             ]},
        ],
    },

    # ------------------------------------------------------------------
    # 11. Relocation — Objection (FL Relocate 721)
    # ------------------------------------------------------------------
    "relocation_objection": {
        "key": "relocation_objection",
        "slug": "relocate-objection",
        "title": "Objection to a Move — Your Information",
        "official": "FL Relocate 721",
        "minutes": 12,
        "description": "You received notice that the other parent "
                       "plans to move with the children, and you "
                       "object. Objections have a short statutory "
                       "deadline — this collects your reasons and "
                       "your counter-proposal so the office can file "
                       "in time.",
        "explainer": "An objection must be filed within about 30 "
                     "days of receiving the notice (RCW 26.09.470) "
                     "— your attorney will confirm your exact "
                     "deadline. Start this now, even if your answers "
                     "are rough.",
        "case_required": True,
        "generate": {"kind": "data_sheet", "category": "pleadings",
                     "file_stem": "Relocation_Objection_Client_Data"},
        "steps": [
            {"title": "The notice you received",
             "fields": [
                 {"name": "notice_date", "label": "When did you "
                  "receive the notice of intent to move?",
                  "type": "date", "required": True,
                  "help": "Your deadline runs from this date — "
                          "your best memory is fine, the office "
                          "will verify."},
                 {"name": "move_summary", "label": "Where are they "
                  "planning to move, and when?", "type": "textarea",
                  "rows": 3},
             ]},
            {"title": "Why you object",
             "explainer": "The court weighs the effect on the "
                          "children most of all. Stick to facts "
                          "about their lives.",
             "fields": [
                 dict(CHILDREN_REPEATER),
                 {"name": "objection_reasons", "label": "How would "
                  "this move affect the children?",
                  "type": "textarea", "rows": 6,
                  "prompt": "Their school, friends, activities, "
                            "medical care, your role in their "
                            "day-to-day lives — what would actually "
                            "change for them?",
                  "guidance": "Write this the way you would in a "
                              "declaration: facts and examples, "
                              "not conclusions."},
                 {"name": "other_parent_reasons", "label": "Do you "
                  "believe the move is being made in good faith?",
                  "type": "textarea", "rows": 4,
                  "prompt": "Optional. If you think the move is "
                            "really about cutting you out rather "
                            "than the stated reason, say why — "
                            "with facts."},
             ]},
            {"title": "What you propose instead",
             "fields": [
                 {"name": "counter_proposal", "label": "If the "
                  "court lets the move happen, what arrangement "
                  "would you ask for?", "type": "textarea",
                  "rows": 5,
                  "prompt": "Longer blocks of time, holidays, "
                            "travel costs, virtual visits — your "
                            "realistic best alternative."},
                 {"name": "children_stay", "label": "Are you asking "
                  "that the children stay here — with you, or with "
                  "another arrangement?", "type": "textarea",
                  "rows": 4,
                  "prompt": "Some objections ask for the children "
                            "to remain in this area even if the "
                            "other parent moves. Say if that's what "
                            "you want and how it would work."},
             ]},
        ],
    },

    # ------------------------------------------------------------------
    # 12. Modify Parenting Plan (FL Modify 601)
    # ------------------------------------------------------------------
    "modify_parenting": {
        "key": "modify_parenting",
        "slug": "modify-parenting-petition",
        "title": "Changing a Parenting Plan — Your Information",
        "official": "FL Modify 601",
        "minutes": 15,
        "description": "You have a parenting plan (or custody "
                       "order) and something substantial has changed. "
                       "This captures what changed and what you're "
                       "asking for; your attorney drafts the petition "
                       "to change it (FL Modify 601).",
        "explainer": "Washington courts only change a parenting "
                     "plan when there's been a substantial change in "
                     "circumstances — the 'what changed' story below "
                     "is the heart of the case, so take your time "
                     "with it.",
        "case_required": True,
        "generate": {"kind": "data_sheet", "category": "pleadings",
                     "file_stem": "Modify_Parenting_Client_Data"},
        "steps": [
            {"title": "The order you have now",
             "fields": [
                 {"name": "current_order_date", "label": "When was "
                  "your current parenting plan/order signed?",
                  "type": "date"},
                 {"name": "current_arrangement", "label": "What "
                  "does the current plan say, in short?",
                  "type": "textarea", "rows": 4,
                  "prompt": "Who the children live with, the "
                            "schedule, who decides what — the "
                            "current setup as ordered."},
             ]},
            {"title": "What changed",
             "explainer": "Check everything that's changed since "
                          "the order, then tell the story.",
             "fields": [
                 {"name": "changes", "label": "What's changed?",
                  "type": "checkboxes",
                  "options": [
                      "My work schedule or job",
                      "The other parent's work schedule or job",
                      "A move (mine or theirs)",
                      "The children's needs, age, or school",
                      "Health — mine, theirs, or a child's",
                      "Safety concerns that weren't there before",
                      "The other parent isn't following the plan",
                      "The children are asking for a change",
                      "Something else (explained below)"]},
                 {"name": "change_story", "label": "Tell us what "
                  "changed", "type": "textarea", "rows": 6,
                  "required": True,
                  "prompt": "Write this the way you would in a "
                            "declaration: what was true when the "
                            "order was signed, what's true now, with "
                            "dates and examples.",
                  "guidance": "This narrative becomes the core of "
                              "your petition and declaration — "
                              "specific beats general."},
             ]},
            {"title": "What you're asking for",
             "fields": [
                 dict(CHILDREN_REPEATER),
                 {"name": "proposed_changes", "label": "The "
                  "changes you want", "type": "textarea", "rows": 5,
                  "prompt": "The schedule, decision-making, or other "
                            "terms you want instead — be as "
                            "specific as you can."},
             ]},
        ],
    },

    # ------------------------------------------------------------------
    # 13. Modify Child Support (FL Modify 501)
    # ------------------------------------------------------------------
    "modify_support": {
        "key": "modify_support",
        "slug": "modify-support-petition",
        "title": "Changing Child Support — Your Information",
        "official": "FL Modify 501",
        "minutes": 10,
        "description": "Support is based on incomes and the "
                       "children's costs — when those change "
                       "substantially, the order can change too. "
                       "Confirm your current figures and tell us "
                       "what's different.",
        "explainer": "Your saved financial figures are shown below "
                     "to confirm or update — the same numbers your "
                     "Financial Declaration uses, so you only ever "
                     "keep one set current.",
        "case_required": True,
        "generate": {"kind": "data_sheet", "category": "pleadings",
                     "file_stem": "Modify_Support_Client_Data"},
        "steps": [
            {"title": "The order you have now",
             "fields": [
                 {"name": "current_support", "label": "Current "
                  "monthly child support amount ($)", "type": "money"},
                 {"name": "changes", "label": "What's changed?",
                  "type": "checkboxes",
                  "options": [
                      "My income went up",
                      "My income went down or I lost work",
                      "The other parent's income changed",
                      "A child turned 18 or graduated",
                      "Daycare or health insurance costs changed",
                      "The children's living arrangement changed",
                      "A new child or dependent",
                      "Something else (explained below)"]},
                 {"name": "change_story", "label": "Tell us what "
                  "changed", "type": "textarea", "rows": 5,
                  "required": True,
                  "prompt": "When it changed, and how the numbers "
                            "moved — dates and amounts help."},
             ]},
            {"title": "Your income now",
             "explainer": "Confirm or update the figures from your "
                          "file.",
             "fields": [
                 {"name": "client_gross_income",
                  "label": "Your monthly GROSS income ($)",
                  "type": "money", "vault": "income.client_gross",
                  "target": ("financial", "client_gross_income")},
                 {"name": "client_net_income",
                  "label": "Your monthly NET (take-home) income ($)",
                  "type": "money", "vault": "income.client_net",
                  "target": ("financial", "client_net_income")},
                 {"name": "other_parent_net_income",
                  "label": "Other parent's monthly NET income ($, "
                         "best estimate)", "type": "money",
                  "vault": "income.other_parent_net",
                  "target": ("financial", "other_parent_net_income")},
             ]},
            {"title": "The children and their costs",
             "fields": [
                 dict(CHILDREN_REPEATER),
                 {"name": "daycare", "label": "Monthly daycare "
                  "costs ($)", "type": "money",
                  "vault": "costs.daycare",
                  "target": ("financial", "daycare")},
                 {"name": "health_insurance",
                  "label": "Monthly health insurance for the "
                         "children ($)", "type": "money",
                  "vault": "costs.health_insurance",
                  "target": ("financial", "health_insurance")},
             ]},
        ],
    },

    # ------------------------------------------------------------------
    # 14. Parentage — Petition to Decide Parentage (FL Parentage 301)
    # ------------------------------------------------------------------
    "parentage_petition": {
        "key": "parentage_petition",
        "slug": "parentage-petition",
        "title": "Petition to Decide Parentage — Your Information",
        "official": "FL Parentage 301",
        "minutes": 15,
        "description": "For parents who weren't married when a "
                       "child was born and don't have a signed "
                       "acknowledgment — a court case (FL Parentage "
                       "301) establishes legal parentage, and with "
                       "it a parenting plan and child support. This "
                       "collects your information; your attorney "
                       "drafts the petition.",
        "explainer": "Until parentage is established, an "
                     "unmarried father may have no legal right to "
                     "time with his child, and support can't be "
                     "ordered. This case fixes that — for both "
                     "parents.",
        "case_required": False,
        "generate": {"kind": "data_sheet", "category": "pleadings",
                     "file_stem": "Parentage_Petition_Client_Data"},
        "steps": [
            {"title": "The other parent",
             "fields": [
                 {"name": "spouse_name", "label": "The other "
                  "parent's full legal name", "type": "text",
                  "vault": "spouse.name",
                  "target": ("client", "spouse_name")},
                 {"name": "spouse_dob", "label": "Their date of "
                  "birth", "type": "date",
                  "vault": "spouse.date_of_birth",
                  "target": ("client", "spouse_dob")},
                 {"name": "service_address", "label": "Address "
                  "where they can be served papers",
                  "type": "textarea", "rows": 2,
                  "vault": "service.address",
                  "target": ("vault", "service.address")},
             ]},
            {"title": "Your children",
             "fields": [
                 dict(CHILDREN_REPEATER),
                 {"name": "birth_certificate", "label": "Is the "
                  "other parent named on the birth certificate(s)?",
                  "type": "radio_cards",
                  "options": ["Yes", "No", "For some children",
                              "Don't know"]},
                 {"name": "ack_signed", "label": "Did both parents "
                  "ever sign an Acknowledgment of Parentage (often "
                  "at the hospital)?", "type": "radio_cards",
                  "options": ["Yes", "No", "Not sure"],
                  "help": "If one was signed and filed, parentage "
                          "may already be established — the office "
                          "will check."},
             ]},
            {"title": "The facts",
             "fields": [
                 {"name": "relationship_facts", "label": "The "
                  "background the court needs", "type": "textarea",
                  "rows": 6,
                  "prompt": "Were you in a relationship with the "
                            "other parent when the children were "
                            "conceived/born? Have they acted as a "
                            "parent — lived with the children, "
                            "supported them, held themselves out as "
                            "a parent? Is anyone's parentage in "
                            "dispute?",
                  "guidance": "Facts with dates. If genetic "
                              "testing is an issue, say so here."},
                 {"name": "genetic_testing", "label": "Should the "
                  "court order genetic (DNA) testing?",
                  "type": "radio_cards",
                  "options": ["Yes — parentage is disputed",
                              "No — we agree who the parents are",
                              "Not sure — advise me"]},
             ]},
            {"title": "What you're asking for",
             "fields": [
                 {"name": "asks", "label": "I'm asking the court "
                  "to…", "type": "checkboxes",
                  "options": [
                      "Decide who the legal parents are",
                      "Make a parenting plan / residential schedule",
                      "Order child support (including back support)",
                      "Add or correct the birth certificate",
                      "Change a child's last name",
                      "Something else (explained below)"]},
                 {"name": "asks_details", "label": "Anything else "
                  "the office should know", "type": "textarea",
                  "rows": 4},
             ]},
        ],
    },

    # ------------------------------------------------------------------
    # 15. Acknowledgment of Parentage data (DOH 422-159)
    # ------------------------------------------------------------------
    "parentage_acknowledgment": {
        "key": "parentage_acknowledgment",
        "slug": "parentage-acknowledgment",
        "title": "Acknowledgment of Parentage — Your Details",
        "official": "DOH 422-159",
        "minutes": 8,
        "description": "The Acknowledgment of Parentage is the "
                       "voluntary form both parents sign so a "
                       "parent is added to the birth certificate — "
                       "it has the legal effect of a court finding "
                       "of parentage. This collects the details "
                       "exactly as the state form (DOH 422-159) "
                       "needs them.",
        "explainer": "Almost everything below should match birth "
                     "records exactly — that's why most of it is "
                     "confirming what's already on your file. Both "
                     "parents must sign the paper form in front of "
                     "a notary or witness; the office will walk "
                     "you through that part.",
        "case_required": False,
        "generate": {"kind": "data_sheet", "category": "pleadings",
                     "file_stem": "Acknowledgment_of_Parentage_Data"},
        "steps": [
            {"title": "The child",
             "fields": [
                 dict(CHILDREN_REPEATER),
                 {"name": "birth_place_child", "label": "City or "
                  "county where the child was born", "type": "text"},
                 {"name": "hospital", "label": "Hospital or place "
                  "of birth (name)", "type": "text"},
             ]},
            {"title": "The birth parent (mother)",
             "explainer": "As it appears on the birth parent's own "
                          "birth certificate.",
             "fields": [
                 {"name": "birth_name", "label": "Birth parent's "
                  "name as on their birth certificate",
                  "type": "text", "vault": "client.birth_name",
                  "target": ("vault", "client.birth_name"),
                  "help": "If you are the other parent rather than "
                          "the birth parent, enter her details as "
                          "best you know and the office will verify."},
                 {"name": "date_of_birth", "label": "Birth parent's "
                  "date of birth", "type": "date",
                  "vault": "client.date_of_birth",
                  "target": ("client", "date_of_birth")},
                 {"name": "birth_place", "label": "Birth parent's "
                  "place of birth (state or country)",
                  "type": "text", "vault": "client.birth_place",
                  "target": ("vault", "client.birth_place")},
             ]},
            {"title": "The parent being added",
             "fields": [
                 {"name": "spouse_name", "label": "Their full "
                  "legal name", "type": "text", "vault": "spouse.name",
                  "target": ("client", "spouse_name")},
                 {"name": "spouse_dob", "label": "Their date of "
                  "birth", "type": "date",
                  "vault": "spouse.date_of_birth",
                  "target": ("client", "spouse_dob")},
                 {"name": "spouse_birth_place", "label": "Their "
                  "place of birth (state or country)",
                  "type": "text", "vault": "spouse.birth_place",
                  "target": ("vault", "spouse.birth_place")},
                 {"name": "address", "label": "Your mailing "
                  "address", "type": "textarea", "rows": 3,
                  "vault": "client.address",
                  "target": ("client", "address")},
                 {"name": "phone", "label": "Your phone number",
                  "type": "tel", "vault": "client.phone",
                  "target": ("client", "phone")},
                 {"name": "parent_labels", "label": "Parent "
                  "labels for the birth certificate",
                  "type": "radio_cards",
                  "options": ["Mother / Father", "Parent / Parent"],
                  "help": "Leave unchosen for the state's default "
                          "(Mother/Father)."},
             ]},
        ],
    },

    # ------------------------------------------------------------------
    # 16. Sealed / protected information attachment (FL All Family 002)
    # ------------------------------------------------------------------
    "sealed_attachment": {
        "key": "sealed_attachment",
        "slug": "cif-attachment",
        "title": "Protecting Your Private Information",
        "official": "FL All Family 002",
        "minutes": 8,
        "description": "Some information has to be given to the "
                       "court but shouldn't sit in the public file "
                       "— and some shouldn't be shared with the "
                       "other party at all. Tell us what needs "
                       "protecting and why; the office prepares the "
                       "sealed attachment (FL All Family 002) and "
                       "any protection requests.",
        "explainer": "Court files are public records. Sealing "
                     "isn't automatic — the court needs a reason — "
                     "so the 'why' below matters as much as the "
                     "'what'.",
        "case_required": False,
        "generate": {"kind": "data_sheet", "category": "pleadings",
                     "file_stem": "Sealed_Attachment_Client_Data"},
        "steps": [
            {"title": "What needs protecting",
             "fields": [
                 {"name": "protected_items", "label": "I need the "
                  "following protected…", "type": "checkboxes",
                  "options": [
                      "My home address",
                      "My phone number or email",
                      "Social Security numbers",
                      "Financial account information",
                      "The children's school or childcare location",
                      "Health or counseling records",
                      "My workplace or work schedule",
                      "Something else (explained below)"]},
                 {"name": "protected_details", "label": "The "
                  "specifics (what exactly, and where it appears)",
                  "type": "textarea", "rows": 4,
                  "prompt": "e.g. 'My new address in Sequim — it "
                            "appears on my declaration.' Don't "
                            "re-type full account numbers here; "
                            "institutions and last-4 digits only."},
             ]},
            {"title": "Why it needs protecting",
             "fields": [
                 {"name": "protection_reasons", "label": "Why?",
                  "type": "checkboxes",
                  "options": [
                      "Safety — the other party must not learn "
                      "where I/we live",
                      "History of threats, stalking, or violence",
                      "Identity theft / financial fraud risk",
                      "The children's safety or privacy",
                      "Court already ordered it protected",
                      "Another reason (explained below)"]},
                 {"name": "reasons_details", "label": "Explain "
                  "briefly", "type": "textarea", "rows": 5,
                  "prompt": "Facts the court can rely on: what "
                            "happened, when, and what you're afraid "
                            "will happen if the information is "
                            "public or shared.",
                  "guidance": "If you're in danger now, call 911 "
                              "or the office — don't wait on this "
                              "form."},
                 {"name": "existing_orders", "label": "Is there "
                  "already a protection or no-contact order in "
                  "place?", "type": "radio_cards",
                  "options": ["Yes", "No", "Not sure"]},
             ]},
        ],
    },

    # ------------------------------------------------------------------
    # 17. Fee waiver (IFP) — GR 34 financial statement
    # ------------------------------------------------------------------
    "fee_waiver": {
        "key": "fee_waiver",
        "slug": "fee-waiver-statement",
        "title": "Fee Waiver — Financial Statement",
        "official": "GR 34.0300",
        "minutes": 10,
        "description": "Court filing fees can be waived for "
                       "people who can't afford them. This is the "
                       "financial statement (GR 34.0300) behind the "
                       "waiver request — mostly confirming figures "
                       "already on your file. The office files the "
                       "motion; the court decides.",
        "explainer": "Be complete and honest — the judge reads "
                     "this closely, and the waiver can be revisited "
                     "if finances change. Public-benefit recipients "
                     "usually qualify on that basis alone.",
        "case_required": False,
        "generate": {"kind": "data_sheet", "category": "pleadings",
                     "file_stem": "Fee_Waiver_Client_Data",
                     "sheet_note": "The court decides whether court "
                                   "fees are waived. This statement "
                                   "supports the GR 34.0100 motion "
                                   "the office files — completing it "
                                   "does not guarantee a waiver."},
        "steps": [
            {"title": "Your household",
             "fields": [
                 {"name": "household_size", "label": "How many "
                  "people are in your household (you, children, "
                  "others you support)?", "type": "text",
                  "vault": "household.size",
                  "target": ("vault", "household.size")},
                 {"name": "benefits_receiving", "label": "Do you "
                  "receive public benefits (SNAP/food, TANF/cash, "
                  "SSI, Medicaid/Apple Health)?",
                  "type": "radio_cards",
                  "options": ["Yes", "No"],
                  "vault": "benefits.receiving",
                  "target": ("vault", "benefits.receiving")},
                 {"name": "benefits_details", "label": "If yes — "
                  "which programs, and the monthly amounts",
                  "type": "textarea", "rows": 3,
                  "vault": "benefits.details",
                  "target": ("vault", "benefits.details")},
             ]},
            {"title": "Income and expenses",
             "explainer": "Confirm or update the figures from "
                          "your file.",
             "fields": [
                 {"name": "client_employer", "label": "Your "
                  "employer (or 'not employed')", "type": "text",
                  "vault": "client.employer",
                  "target": ("vault", "client.employer")},
                 {"name": "client_gross_income",
                  "label": "Your monthly GROSS income ($)",
                  "type": "money", "vault": "income.client_gross",
                  "target": ("financial", "client_gross_income")},
                 {"name": "client_net_income",
                  "label": "Your monthly NET (take-home) income ($)",
                  "type": "money", "vault": "income.client_net",
                  "target": ("financial", "client_net_income")},
                 {"name": "monthly_expenses",
                  "label": "Your total monthly expenses ($)",
                  "type": "money", "vault": "expenses.monthly_total",
                  "target": ("financial", "monthly_expenses")},
             ]},
            {"title": "What you own and owe",
             "fields": [
                 {"name": "assets_notes",
                  "label": "Assets — home, vehicles (year/make), "
                         "accounts, valuables", "type": "textarea",
                  "rows": 4, "vault": "notes.assets",
                  "target": ("financial", "assets_notes"),
                  "prompt": "With rough values — the court expects "
                            "your vehicles and any money in "
                            "accounts to be listed."},
                 {"name": "debts_notes",
                  "label": "Debts — what you owe and to whom",
                  "type": "textarea", "rows": 4,
                  "vault": "notes.debts",
                  "target": ("financial", "debts_notes")},
                 {"name": "hardship", "label": "Anything else "
                  "about your finances the judge should know",
                  "type": "textarea", "rows": 4,
                  "prompt": "Recent job loss, medical bills, "
                            "caring for a family member — whatever "
                            "explains why the fee is a hardship."},
             ]},
        ],
    },
}


# ----------------------------------------------------------------------------
# Scenario packets (v2.9.0) — guided checklists staff assign to a client
# ----------------------------------------------------------------------------
# The line COMPLIANCE requires on every packet a client sees.
PACKET_GUIDANCE = ("This checklist is guidance from our office, not "
                   "legal advice about your situation.")

_W = "wizard"
_U = "upload"
_I = "info"


def _step(kind, **kw):
    step = {"type": kind}
    step.update(kw)
    return step


PACKET_DEFS = {
    "starting-divorce": {
        "slug": "starting-divorce",
        "title": "Starting a divorce",
        "scenario": "starting_divorce",
        "description": "You're starting a divorce — here's "
                       "everything we need from you, in order. Work "
                       "at your own pace; your answers save as you "
                       "go.",
        "guidance": PACKET_GUIDANCE,
        "steps": [
            _step(_W, doc="petition-divorce"),
            _step(_W, doc="confidential-information"),
            _step(_W, doc="financial-declaration"),
            _step(_W, doc="declaration"),
            _step(_W, doc="parenting-plan"),
            _step(_W, doc="child-support-worksheet"),
            _step(_U, title="Your last two pay stubs",
                  doc_type="pay_stubs",
                  note="Photos or scans are fine — all pages, "
                       "including the year-to-date totals."),
            _step(_U, title="Your most recent tax return",
                  doc_type="tax_return",
                  note="The full return with all schedules, if you "
                       "have it."),
            _step(_W, doc="certificate-dissolution"),
        ],
    },
    "responding": {
        "slug": "responding",
        "title": "Responding to papers you were served",
        "scenario": "responding",
        "description": "You were served with divorce papers — "
                       "here's everything we need from you, in "
                       "order. A response is due on a deadline, so "
                       "start with the first step today.",
        "guidance": PACKET_GUIDANCE,
        "steps": [
            _step(_I, title="How service works — read this first",
                  sequential=True,
                  body="Being 'served' starts the court's clock. In "
                       "Washington, a response is usually due 20 "
                       "days after you were personally served in "
                       "this state (60 days if you were served "
                       "outside Washington) — your attorney will "
                       "confirm your exact deadline, because it "
                       "controls everything else.\n\n"
                       "Three things to do right away:\n"
                       "1. Keep every page you were handed, including "
                       "the envelope.\n"
                       "2. Note the date, time, and place you "
                       "received them.\n"
                       "3. Don't sign anything the other party gives "
                       "you until the office has seen it.\n\n"
                       "Missing the deadline can let the court enter "
                       "orders against you by default — that's why "
                       "the steps below matter, and why rough "
                       "answers now beat perfect answers late."),
            _step(_U, title="The papers you were served",
                  doc_type="other",
                  note="A photo or scan of EVERY page, including "
                       "the summons on top. Blurry is better than "
                       "missing — the office can ask for a rescan."),
            _step(_W, doc="response-marriage"),
            _step(_W, doc="declaration"),
            _step(_W, doc="financial-declaration"),
        ],
    },
    "uncontested": {
        "slug": "uncontested",
        "title": "We agree on everything",
        "scenario": "uncontested",
        "description": "You and your spouse agree on the terms — "
                       "here's everything we need from you, in "
                       "order, to turn that agreement into final "
                       "court orders.",
        "guidance": PACKET_GUIDANCE,
        "steps": [
            _step(_W, doc="petition-divorce"),
            _step(_W, doc="confidential-information"),
            _step(_W, doc="financial-declaration"),
            _step(_W, doc="parenting-plan"),
            _step(_W, doc="child-support-worksheet"),
            _step(_W, doc="certificate-dissolution"),
            _step(_I, title="What happens next",
                  body="Once your forms are in, the office drafts "
                       "the final orders from your agreement — the "
                       "Findings, the Final Divorce Order, and (if "
                       "there are children) the Parenting Plan and "
                       "Child Support Order.\n\n"
                       "Your spouse will sign an Agreement to Join "
                       "Petition (Joinder), which the office "
                       "prepares — it says they agree with the "
                       "petition as filed, so no response or hearing "
                       "is usually needed.\n\n"
                       "Washington has a 90-day waiting period from "
                       "filing before a divorce can be finalized. "
                       "The office will tell you the earliest date "
                       "your decree can be signed and will review "
                       "every document with you before anything is "
                       "filed."),
        ],
    },
    "temporary-orders": {
        "slug": "temporary-orders",
        "title": "Temporary orders while we wait",
        "scenario": "temporary_orders",
        "description": "Your case is underway and you need the "
                       "court to order some things NOW — support, "
                       "a schedule, who stays in the home — while "
                       "the case runs. Here's what we need from you.",
        "guidance": PACKET_GUIDANCE,
        "steps": [
            _step(_W, doc="temporary-orders"),
            _step(_W, doc="declaration"),
            _step(_W, doc="financial-declaration"),
            _step(_U, title="Your last two pay stubs",
                  doc_type="pay_stubs",
                  note="The judge sets temporary support from "
                       "these — all pages, including year-to-date "
                       "totals."),
            _step(_U, title="Bills or statements that back up your "
                            "requests",
                  doc_type="other",
                  note="Mortgage or rent statements, the bills "
                       "you're asking to have covered, insurance "
                       "notices — whatever documents what you wrote "
                       "in step 1."),
        ],
    },
    "changing-order": {
        "slug": "changing-order",
        "title": "Changing an existing order",
        "scenario": "changing_order",
        "description": "You already have court orders and "
                       "something substantial has changed — here's "
                       "everything we need from you, in order. The "
                       "first two steps cover the two kinds of "
                       "change; complete the one that matches yours "
                       "(or both).",
        "guidance": PACKET_GUIDANCE,
        "steps": [
            _step(_W, doc="modify-parenting-petition", optional=True),
            _step(_W, doc="modify-support-petition", optional=True),
            _step(_W, doc="financial-declaration"),
            _step(_W, doc="declaration"),
        ],
    },
    "relocation": {
        "slug": "relocation",
        "title": "Moving with the kids",
        "scenario": "relocation",
        "description": "A move with the children is coming — "
                       "yours, or one you've been told about. "
                       "Relocation law runs on short deadlines, so "
                       "start the step that matches your side today.",
        "guidance": PACKET_GUIDANCE,
        "steps": [
            _step(_I, title="Which side are you on? — read this "
                            "first",
                  body="If YOU are planning to move with the "
                       "children: Washington law (RCW 26.09.430) "
                       "requires formal written notice to the other "
                       "parent — usually at least 60 days before "
                       "the intended move (less only in narrow "
                       "emergencies). Complete the 'Notice of "
                       "Intent to Move' step below.\n\n"
                       "If you RECEIVED a notice that the other "
                       "parent is moving: you generally have about "
                       "30 days from receiving it to file an "
                       "objection. Complete the 'Objection to a "
                       "Move' step below instead.\n\n"
                       "Either way, your attorney will confirm your "
                       "exact deadline — these dates are statutory "
                       "and missing one can decide the case."),
            _step(_W, doc="relocate-notice", optional=True),
            _step(_W, doc="relocate-objection", optional=True),
            _step(_W, doc="declaration"),
            _step(_U, title="Anything that documents the move or "
                            "your objection",
                  doc_type="other",
                  note="A job offer or transfer letter, a lease, "
                       "school information — or, if you're "
                       "objecting, the notice you received."),
        ],
    },
    "protection": {
        "slug": "protection",
        "title": "Protection order",
        "scenario": "protection",
        "description": "You need the court's protection — here's "
                       "what we need from you. If you are in danger "
                       "right now, call 911 first; this checklist "
                       "can wait, your safety can't.",
        "guidance": PACKET_GUIDANCE,
        "steps": [
            _step(_I, title="Getting protection — read this first",
                  sequential=True,
                  body="If you or your children are in immediate "
                       "danger, call 911.\n\n"
                       "A protection order (RCW 7.105) is a court "
                       "order that can require a person to stay away "
                       "from you, your home, your work, and your "
                       "children's school, and to surrender "
                       "firearms. The office files these the same "
                       "day whenever possible — call the office as "
                       "soon as you've read this, and don't wait to "
                       "finish the steps below first.\n\n"
                       "The steps below help the office build the "
                       "strongest petition: your own statement (the "
                       "declaration), protection for your private "
                       "information, and whatever documentation you "
                       "have. Write facts and dates — what happened, "
                       "when, and who saw it."),
            _step(_W, doc="declaration"),
            _step(_W, doc="cif-attachment"),
            _step(_U, title="Anything that documents what happened",
                  doc_type="other",
                  note="Photos of injuries or damage, screenshots "
                       "of messages, police reports, medical "
                       "paperwork — whatever you have. Originals "
                       "stay safe with you; send copies here."),
        ],
    },
    "parentage": {
        "slug": "parentage",
        "title": "Proving parentage",
        "scenario": "parentage",
        "description": "For parents who weren't married when a "
                       "child was born — here's everything we need "
                       "from you, in order, to establish legal "
                       "parentage and everything that flows from "
                       "it: a parenting plan and child support.",
        "guidance": PACKET_GUIDANCE,
        "steps": [
            _step(_W, doc="parentage-petition"),
            _step(_W, doc="parentage-acknowledgment"),
            _step(_W, doc="confidential-information"),
            _step(_W, doc="parenting-plan"),
            _step(_W, doc="child-support-worksheet"),
        ],
    },
}

PACKETS_BY_SLUG = {p["slug"]: p for p in PACKET_DEFS.values()}


def packet_def(slug):
    return PACKETS_BY_SLUG.get(slug)


def wizard_def(key):
    return WIZARD_DEFS.get(key)


def wizard_fields(wdef):
    """Flat list of a wizard's fields across its steps."""
    return [f for step in wdef["steps"] for f in step["fields"]]


# Implemented entries must line up with wizard defs — checked by
# tests/test_v280.py (and cheap enough to assert at import in dev).
for _entry in LIBRARY:
    if _entry["implemented"]:
        assert _entry["wizard"] in WIZARD_DEFS, _entry["slug"]

# Packet steps must reference live material: a wizard step's doc is
# an implemented catalog slug; upload/info steps are self-contained.
for _packet in PACKET_DEFS.values():
    for _step_def in _packet["steps"]:
        if _step_def["type"] == "wizard":
            _doc = LIBRARY_BY_SLUG.get(_step_def["doc"])
            assert _doc and _doc["implemented"], (
                _packet["slug"], _step_def["doc"])
