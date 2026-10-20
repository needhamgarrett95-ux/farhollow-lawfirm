#!/usr/bin/env python3
"""v2.10.0 checks — Rare tier + Polish.

Covers, against a scratch copy of the app:
  * Registry integrity: EVERY rare-tier entry is either implemented
    with a wizard def or carries a plain-language catalog-only
    reason; 25 entries implemented (11 common + 9 uncommon + 5 rare);
    the FL Divorce 241 order stays a pointer to the Final Review
    wizard; the FL Visits number is unconfirmed ("—") with the 476
    lead kept as an unverified note.
  * The minutes model: every def's minutes literal equals
    form_library.estimate_wizard_minutes(def); packet totals come
    from packet_est_minutes.
  * Staff Library stats math on seeded submissions: started / sent /
    filed counts, the modal stall step (from saved _step), average
    sections completed, and an honest "no data yet" state.
  * New wizards end-to-end: contempt, residential time summary,
    final review (FL Divorce 231/241), parentage temporary (FL
    Parentage 323), visits, de facto parentage, committed intimate
    relationship, QDRO — draft, submit (snapshot), staff review,
    import, generate a DRAFT data sheet.
  * No-state-form honesty: QDRO / CIR / de facto wizards say so in
    the portal AND on the generated data sheet (IMPORTANT note +
    no "transfer to the official form" subtitle).
  * Stale drafts: a draft untouched 14+ days earns a dismissible
    "pick up where you left off" card on that client's portal home
    only; dismissing never touches the draft; cross-client dismiss
    is a 404.
  * Polish: portal library groups by tier under plain-language
    headings; packet pages show estimated total minutes; the wizard
    review screen carries per-section Edit jumps; catalog-only rare
    slugs stay 404 in the portal.
  * Invalidity end-to-end: the petition variant flag generates a
    petition + data sheet that NAME the action as invalidity.
"""
import base64
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import zlib

TEST_CODE = r'''
import base64
import io
import json
import os
import re
import sqlite3
import sys
import zlib
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.getcwd())
import app as appmod
import form_library as fl

appmod.app.config.update(TESTING=True)
with appmod.app.app_context():
    appmod.init_db()

FAILURES = []

def check(name, cond, detail=""):
    if cond:
        print("PASS -", name)
    else:
        print("FAIL -", name, detail)
        FAILURES.append(name)

def dbq(sql, params=()):
    db = sqlite3.connect("instance/lawfirm.db")
    db.row_factory = sqlite3.Row
    rows = db.execute(sql, params).fetchall()
    db.close()
    return rows

def dbx(sql, params=()):
    db = sqlite3.connect("instance/lawfirm.db")
    db.execute(sql, params)
    db.commit()
    db.close()

enc = appmod.encrypt_value
PW0 = "change" + "me123"
NOW = "2026-10-20T00:00:00+00:00"

def csrf(cl):
    with cl.session_transaction() as s:
        return s.get("csrf_token", "")

dbx("INSERT INTO clients (first_name,last_name,email,phone,address,"
    "date_of_birth,spouse_name,spouse_dob,ssn,created_at,updated_at)"
    " VALUES ('Alice','Anderson','alice@example.com','360-555-0100',"
    "'12 Harbor Way',?,?,?,?,?,?)",
    (enc("1988-04-02"), "Andrew Anderson", enc("1986-09-14"),
     enc("123-45-6789"), NOW, NOW))
dbx("INSERT INTO clients (first_name,last_name,email,phone,"
    "created_at,updated_at) VALUES ('Bob','Baker','bob@example.com',"
    "'360-555-0200',?,?)", (NOW, NOW))
dbx("INSERT INTO cases (client_id,title,case_number,case_type,status,"
    "created_at,updated_at) VALUES (1,'Anderson v. Anderson',"
    "'26-2-00101','dissolution','open',?,?)", (NOW, NOW))
dbx("INSERT INTO cases (client_id,title,case_number,case_type,status,"
    "created_at,updated_at) VALUES (2,'Baker v. Baker','26-2-00202',"
    "'dissolution','open',?,?)", (NOW, NOW))
dbx("INSERT INTO children (client_id,name,date_of_birth) VALUES (1,"
    "'Kid Anderson',?)", (enc("2018-05-01"),))
for key, val in (("marriage.date", "2015-06-20"),
                 ("marriage.place", "Port Angeles, WA"),
                 ("client.employer", "Harbor Mill")):
    dbx("INSERT INTO client_vault_facts (client_id,fact_key,value,"
        "source,updated_at) VALUES (1,?,?,'staff',?)", (key, val, NOW))
for key, val in (("client_gross_income", "4,000"),
                 ("client_net_income", "3,100")):
    dbx("INSERT INTO case_financials (case_id,key,value,updated_at)"
        " VALUES (1,?,?,?)", (key, val, NOW))

staff = appmod.app.test_client()
staff.get("/login")
r = staff.post("/login", data={"username": "admin", "password": PW0,
                               "csrf_token": csrf(staff)})
check("staff logs in with the seed admin", r.status_code == 302)
r = staff.post("/change-password", data={
    "current_password": PW0,
    "new_password": "Admin" + "Pass123!",
    "confirm_password": "Admin" + "Pass123!",
    "csrf_token": csrf(staff)})
check("forced password change succeeds", r.status_code == 302)

def invite_token_for(cl, client_id):
    cl.post(f"/clients/{client_id}/portal/invite",
            data={"csrf_token": csrf(cl)})
    r = cl.get(f"/clients/{client_id}")
    m = re.search(rb"/portal/accept-invite/([A-Za-z0-9_\-]+)", r.data)
    return m.group(1).decode() if m else None

def accept_invite(token, password):
    cl = appmod.app.test_client()
    cl.get(f"/portal/accept-invite/{token}")
    cl.post(f"/portal/accept-invite/{token}", data={
        "password": password, "confirm_password": password,
        "csrf_token": csrf(cl)})
    return cl

def portal_login(cl, email, password):
    cl.get("/portal/login")
    return cl.post("/portal/login", data={
        "email": email, "password": password, "csrf_token": csrf(cl)})

A = accept_invite(invite_token_for(staff, 1), "Alice" + "Pass123")
B = accept_invite(invite_token_for(staff, 2), "Bob" + "Pass12345")
portal_login(A, "alice@example.com", "Alice" + "Pass123")
portal_login(B, "bob@example.com", "Bob" + "Pass12345")

def wiz_post(cl, slug, step, fields, action):
    data = {"step": str(step), "action": action, "csrf_token": csrf(cl)}
    data.update(fields)
    return cl.post(f"/portal/library/{slug}", data=data)

def pdf_text_norm(doc_row):
    path = os.path.join(appmod._case_doc_dir(doc_row["case_id"]),
                        doc_row["stored_name"])
    raw = open(path, "rb").read()
    chunks = []
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", raw, re.S):
        chunk = m.group(1).strip()
        data = None
        try:
            data = zlib.decompress(chunk)
        except Exception:
            pass
        if data is None:
            try:
                data = zlib.decompress(base64.a85decode(
                    chunk.rstrip(b"~>").strip(), adobe=False))
            except Exception:
                pass
        if data:
            chunks.append(data)
    # Pull only the literal strings reportlab drew (Tj operands):
    # operator junk between wrapped lines would otherwise break
    # multi-word markers, and octal escapes (\227 = em dash) must
    # be decoded before normalizing.
    parts = []
    for data in chunks:
        for sm in re.finditer(rb"\((?:\\.|[^\\()])*\)", data):
            s = sm.group(0)[1:-1]
            s = re.sub(rb"\\(\d{1,3})",
                       lambda mm: bytes(
                           [int(mm.group(1), 8) & 0xFF]), s)
            s = (s.replace(b"\\(", b"(").replace(b"\\)", b")")
                 .replace(b"\\\\", b"\\"))
            parts.append(s)
    blob = b"".join(parts)
    return re.sub(rb"[^A-Za-z0-9]", b"", blob)

DRAFT_BANNER = b"DRAFTNOTFORFILINGATTORNEYREVIEWREQUIRED"

# ======================================================================
# 1. Registry integrity — the library is complete and honest
# ======================================================================
impl = [e for e in fl.LIBRARY if e["implemented"]]
check("25 entries implemented (11 common + 9 uncommon + 5 rare)",
      len(impl) == 25
      and sum(1 for e in impl if e["tier"] == "common") == 11
      and sum(1 for e in impl if e["tier"] == "uncommon") == 9
      and sum(1 for e in impl if e["tier"] == "rare") == 5)
check("implemented wizard keys == WIZARD_DEFS keys exactly",
      {e["wizard"] for e in impl} == set(fl.WIZARD_DEFS)
      and len(fl.WIZARD_DEFS) == 25)
bad = [e["slug"] for e in fl.LIBRARY
       if not e["implemented"] and not e.get("catalog_only_reason")]
check("no entry is silently unimplemented (every non-live entry "
      "carries a catalog-only reason)", not bad, str(bad))
rare = [e for e in fl.LIBRARY if e["tier"] == "rare"]
check("every RARE entry is implemented or justified",
      all(e["implemented"] or e.get("catalog_only_reason")
          for e in rare))
CATALOG_ONLY_RARE = {
    "protection-order-petition", "parentage-immediate-restraining",
    "parentage-temporary-order",
    "parentage-sexual-assault-allegation",
    "relocate-final-ex-parte-motion", "relocate-final-ex-parte-order",
    "gal-order", "parenting-evaluator-order"}
check("the 8 deliberately catalog-only rare entries are exactly "
      "the court-order / urgent / attorney ones",
      {e["slug"] for e in rare if not e["implemented"]}
      == CATALOG_ONLY_RARE)
check("protection order stays wizard-less ON PURPOSE (urgent, "
      "human-first) and its reason says so",
      "needs staff help immediately"
      in fl.LIBRARY_BY_SLUG["protection-order-petition"]
      ["catalog_only_reason"]
      and "not homework"
      in fl.LIBRARY_BY_SLUG["protection-order-petition"]
      ["catalog_only_reason"])
check("contempt (FL All Family 165) is implemented",
      fl.LIBRARY_BY_SLUG["contempt-motion"]["implemented"]
      and fl.LIBRARY_BY_SLUG["contempt-motion"]["wizard"]
      == "contempt")
check("Residential Time Summary (243) + Findings (231) implemented",
      fl.LIBRARY_BY_SLUG["residential-time-summary"]["wizard"]
      == "residential_time_summary"
      and fl.LIBRARY_BY_SLUG["findings-marriage"]["wizard"]
      == "final_review")
fo = fl.LIBRARY_BY_SLUG["final-divorce-order"]
check("Final Divorce Order (241) stays a pointer to Final Review, "
      "not a duplicate wizard",
      not fo["implemented"] and "Final Review"
      in fo["catalog_only_reason"])
check("the 241 entry doubles as the invalidity order pointer",
      "Invalid" in fo["title"])
vis = fl.LIBRARY_BY_SLUG["visits-petition"]
check("FL Visits number is NOT settled: number shows as unconfirmed "
      "and the 476 lead is kept as an unverified note",
      vis["implemented"] and vis["form_number"] == "\u2014"
      and "476" in vis["note"] and "NOT confirmed" in vis["note"])
check("QDRO + de facto + CIR implemented as intakes",
      all(fl.LIBRARY_BY_SLUG[s]["implemented"] for s in
          ("qdro-data", "de-facto-parentage",
           "committed-intimate-relationship")))
bad = [k for k, w in fl.WIZARD_DEFS.items()
       if w["minutes"] != fl.estimate_wizard_minutes(w)]
check("minutes model present for every live wizard (each def's "
      "minutes == estimate_wizard_minutes)", not bad, str(bad))
check("packet totals come from the model and are positive",
      all(fl.packet_est_minutes(p) > 0
          for p in fl.PACKET_DEFS.values()))

# ======================================================================
# 2. Staff Library stats — math on seeded submissions
# ======================================================================
CH = [{"name": "Kid Anderson", "date_of_birth": "2018-05-01"}]
FULL = {"children": CH, "overnights_you": "9", "overnights_other": "5",
        "holiday_split": "Alternate major holidays each year"}
def seed_sub(form_key, status, data, updated=NOW):
    dbx("INSERT INTO portal_form_submissions (client_id, case_id,"
        " form_key, status, data_json, snapshot_json, created_at,"
        " updated_at) VALUES (1, 1, ?, ?, ?, ?, ?, ?)",
        (form_key, status, json.dumps(data),
         json.dumps(data) if status != "draft" else None,
         updated, updated))
seed_sub("residential_time_summary", "draft",
         {"_step": 1, "children": CH})
seed_sub("residential_time_summary", "draft",
         {"_step": 1, "children": CH})
seed_sub("residential_time_summary", "draft",
         {"_step": 2, "children": CH, "overnights_you": "9",
          "overnights_other": "5"})
seed_sub("residential_time_summary", "submitted", dict(FULL))
seed_sub("residential_time_summary", "imported", dict(FULL))
r = staff.get("/library")
check("staff library page renders with stats", r.status_code == 200)
check("stats: started 5 / sent 2 / filed 1 for the seeded wizard",
      b"Started 5" in r.data and b"sent to office 2" in r.data
      and b"added to file 1" in r.data)
check("stats: drafts stall at the modal step 'A typical two weeks' "
      "(2 drafts)",
      b"A typical two weeks" in r.data and b"(2 drafts)" in r.data)
check("stats: average sections completed ~67%",
      b"~67% of sections" in r.data)
check("stats: untouched wizards show an honest 'No portal data yet'",
      b"No portal data yet" in r.data)
check("library view explains catalog-only entries with their reason",
      b"Catalog only" in r.data
      and b"needs staff help immediately" in r.data)

# ======================================================================
# 3. New wizards end-to-end (A): draft -> submit -> review -> import
#    -> DRAFT data sheet
# ======================================================================
def run_wizard(slug, step_fields, doc_name, markers, label):
    for i, fields in enumerate(step_fields):
        wiz_post(A, slug, i, fields, "next")
    last = len(step_fields)
    wiz_post(A, slug, last, {}, "submit")
    sub = dbq("SELECT * FROM portal_form_submissions WHERE client_id"
              " = 1 AND form_key = ? ORDER BY id DESC",
              (fl.LIBRARY_BY_SLUG[slug]["wizard"],))
    check(f"{label}: submits with a frozen snapshot",
          sub and sub[0]["status"] == "submitted"
          and sub[0]["snapshot_json"])
    if not sub:
        return
    sid = sub[0]["id"]
    r = staff.get(f"/portal-review/forms/{sid}")
    check(f"{label}: staff review page renders", r.status_code == 200)
    staff.post(f"/portal-review/forms/{sid}/import",
               data={"csrf_token": csrf(staff)})
    staff.post(f"/portal-review/forms/{sid}/generate-document",
               data={"csrf_token": csrf(staff)})
    docs = dbq("SELECT * FROM documents WHERE case_id = 1 AND"
               " original_name = ?", (doc_name,))
    check(f"{label}: data sheet generated ({doc_name})",
          len(docs) == 1)
    if docs:
        text = pdf_text_norm(docs[0])
        check(f"{label}: sheet carries the canonical DRAFT banner",
              DRAFT_BANNER in text)
        for m in markers:
            check(f"{label}: sheet contains {m!r}", m in text)

contempt_relief = fl.wizard_def("contempt")["steps"][2]["fields"][0]
run_wizard("contempt-motion", [
    {"case_id": "1", "order_title": "Final Parenting Plan",
     "order_date": "2026-02-10",
     "order_requires": "Weekend exchanges at 5 PM Fridays"},
    {"violations": "ZZZMARK March 3 - support payment $450 not paid; "
                   "March 20 - exchange 2 hours late",
     "evidence_notes": "Bank statement and texts",
     "still_ongoing": "Yes, it is still happening"},
    {"relief": [contempt_relief["options"][0]],
     "relief_details": "Make-up weekends in April"},
], "Contempt_Client_Data.pdf", [b"FLAllFamily165"], "contempt")

FR = fl.wizard_def("final_review")
division_ok = [f for s in FR["steps"] for f in s["fields"]
               if f["name"] == "division_ok"][0]
run_wizard("findings-marriage", [
    {"case_id": "1", "cf_spouse_name": "keep", "spouse_name": "",
     "cf_marriage_date": "keep", "marriage_date": "",
     "cf_marriage_place": "keep", "marriage_place": "",
     "separation_date": "2026-03-01"},
    {"children_name": ["Kid Anderson"],
     "children_dob": ["2018-05-01"]},
    {"assets_notes": "House and two accounts, split as agreed",
     "debts_notes": "Truck loan to Andrew",
     "cf_client_gross_income": "keep",
     "cf_client_net_income": "keep",
     "other_parent_net_income": "2,800",
     "division_ok": division_ok["options"][0]},
    {"name_change_final": "", "anything_else": ""},
], "Final_Review_Client_Data.pdf", [b"FLDivorce231"], "final review")

run_wizard("parentage-temporary-motion", [
    {"case_id": "1", "children_name": ["Kid Anderson"],
     "children_dob": ["2018-05-01"]},
    {"needs": ["Decide where the child lives day to day"],
     "schedule_now": "Week on / week off until trial",
     "support_now": "Guideline support starting November"},
    {"safety": ""},
], "Parentage_Temporary_Client_Data.pdf", [b"FLParentage323"],
    "parentage temporary (323)")

# The seeded RTS drafts: the wizard resumes the LATEST draft (seed 3).
wiz_post(A, "residential-time-summary", 0, {
    "children_name": ["Kid Anderson"],
    "children_dob": ["2018-05-01"]}, "next")
wiz_post(A, "residential-time-summary", 1, {
    "overnights_you": "9", "overnights_other": "5"}, "next")
wiz_post(A, "residential-time-summary", 2, {
    "holiday_split": "Alternate major holidays each year",
    "changes_expected": "No"}, "next")
wiz_post(A, "residential-time-summary", 3, {}, "submit")
# The stats section seeded a 'submitted' row too — the wizard's own
# submission is the one whose data carries the saved _step marker.
rsub = dbq("SELECT * FROM portal_form_submissions WHERE client_id = 1"
           " AND form_key = 'residential_time_summary'"
           " AND status = 'submitted'"
           " AND data_json LIKE '%\"_step\"%'")
check("residential time summary submits", len(rsub) == 1)
if rsub:
    staff.post(f"/portal-review/forms/{rsub[0]['id']}/import",
               data={"csrf_token": csrf(staff)})
    staff.post(
        f"/portal-review/forms/{rsub[0]['id']}/generate-document",
        data={"csrf_token": csrf(staff)})
    docs = dbq("SELECT * FROM documents WHERE case_id = 1 AND"
               " original_name = 'Residential_Time_Summary_Data.pdf'")
    check("residential time summary data sheet generated",
          len(docs) == 1)
    if docs:
        check("RTS sheet cites FL Divorce 243",
              b"FLDivorce243" in pdf_text_norm(docs[0]))

# ======================================================================
# 4. No-state-form honesty — portal copy AND generated output
# ======================================================================
r = A.get("/portal/library/qdro-data?step=0")
check("QDRO wizard tells the client plainly: no state QDRO form",
      b"NO Washington state QDRO form" in r.data)
run_wizard("qdro-data", [
    {"case_id": "1", "plan_holder": "Mine",
     "plan_names": "ZZZPLAN 401(k) at Cascade Fabrication",
     "plan_types": ["401(k) / 403(b) (defined contribution)"]},
    {"cf_marriage_date": "keep", "marriage_date": "",
     "separation_date": "2026-03-01",
     "decree_status": "The divorce is final",
     "decree_terms": "Split the 401(k) earned during the marriage"},
    {"approx_balances": "About $86,000 at separation",
     "admin_contact": ""},
], "QDRO_Plan_Data.pdf", [b"NOSTATEFORM"], "QDRO intake")
docs = dbq("SELECT * FROM documents WHERE case_id = 1 AND"
           " original_name = 'QDRO_Plan_Data.pdf'")
if docs:
    text = pdf_text_norm(docs[0])
    check("QDRO sheet subtitle is honest (no official form to "
          "transfer onto)",
          b"nostandardWashingtonformexists" in text
          and b"transferverifiedfigures" not in text)

r = A.get("/portal/library/committed-intimate-relationship?step=0")
check("CIR wizard says NO standard state form up front",
      b"NO standard state form" in r.data)
run_wizard("committed-intimate-relationship", [
    {"cf_partner_name": "keep", "partner_name": "",
     "relationship_start": "2019-04-01",
     "lived_together": "Yes, the whole time",
     "separation_date": "2026-08-15"},
    {"shared_property": "A house in Sequim, bought together in 2021",
     "joint_finances": "One joint checking account",
     "contributions": "We split the mortgage evenly"},
    {"division_ask": "Sell the house and split the proceeds",
     "children_together": "No"},
], "CIR_Intake_Client_Data.pdf", [b"NOSTANDARDFORM"], "CIR intake")

r = A.get("/portal/library/de-facto-parentage?step=0")
check("de facto wizard says NO standard state form up front",
      b"NO standard state form" in r.data)
run_wizard("de-facto-parentage", [
    {"child_name": "Kid Anderson", "child_dob": "2018-05-01",
     "child_home": "With me, full time"},
    {"lived_together": "Yes - since the child was a baby",
     "daily_care": "Meals, school runs, doctor visits, homework",
     "bond_note": "She calls me Dad and I am who she runs to"},
    {"legal_parents": "Her mother; no other parent on the "
                      "birth certificate",
     "parents_agree": "One agrees, the other does not",
     "why_now": "School enrollment needs a court order",
     "more_children": ""},
], "De_Facto_Parentage_Intake.pdf", [b"NOSTANDARDFORM"],
    "de facto intake")

run_wizard("visits-petition", [
    {"relationship": "Grandparent", "child_name": "Kid Anderson",
     "child_dob": "2018-05-01",
     "child_lives_with": "Her mother"},
    {"bond_history": "Weekly Sundays and every holiday since "
                     "she was born",
     "time_recent": "No visits since March"},
    {"requested_visits": "Two Sundays a month, 10 AM to 4 PM",
     "parents_position": "Her mother has cut off contact",
     "more_children": ""},
], "Visits_Intake_Client_Data.pdf",
    [b"NOTverifiedagainsttheofficiallist"], "visits intake")

# ======================================================================
# 5. Stale drafts — the gentle card, dismissal, and boundaries
# ======================================================================
OLD = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
dbx("INSERT INTO portal_form_submissions (client_id, case_id,"
    " form_key, status, data_json, created_at, updated_at) VALUES"
    " (1, 1, 'declaration', 'draft', ?, ?, ?)",
    (json.dumps({"_step": 2}), OLD, OLD))
stale = dbq("SELECT * FROM portal_form_submissions WHERE client_id"
            " = 1 AND form_key = 'declaration' AND status = 'draft'")[0]
wiz_post(A, "contempt-motion", 0, {"case_id": "1"}, "save_exit")
r = A.get("/portal/")
check("stale draft (20 days) earns the pickup card",
      b"Pick up where you left off" in r.data
      and b"20 days ago" in r.data)
check("the card names the document",
      b"Declaration" in r.data)
check("a FRESH draft earns no card (only one card shows)",
      r.data.count(b"Pick up where you left off") == 1)
r = B.get("/portal/")
check("the other client never sees A's stale card",
      b"Pick up where you left off" not in r.data)
r = B.post(f"/portal/drafts/{stale['id']}/dismiss",
           data={"csrf_token": csrf(B)})
check("B cannot dismiss A's draft (404)", r.status_code == 404)
r = A.post("/portal/drafts/99999/dismiss",
           data={"csrf_token": csrf(A)})
check("dismissing a nonexistent draft 404s", r.status_code == 404)
sub_row = dbq("SELECT * FROM portal_form_submissions WHERE client_id"
              " = 1 AND form_key = 'contempt'"
              " AND status != 'draft' ORDER BY id DESC")[0]
r = A.post(f"/portal/drafts/{sub_row['id']}/dismiss",
           data={"csrf_token": csrf(A)})
check("a SENT form cannot be dismissed as a draft (404)",
      r.status_code == 404)
r = A.post(f"/portal/drafts/{stale['id']}/dismiss",
           data={"csrf_token": csrf(A)})
check("owner dismisses the card", r.status_code == 302)
r = A.get("/portal/")
check("card is gone after dismissal",
      b"Pick up where you left off" not in r.data)
check("dismissal never touches the draft itself",
      dbq("SELECT status FROM portal_form_submissions WHERE id = ?",
          (stale["id"],))[0]["status"] == "draft")

# ======================================================================
# 6. Polish — tier headings, packet minutes, review Edit jumps
# ======================================================================
r = A.get("/portal/library")
i1 = r.data.find(b"The usual documents")
i2 = r.data.find(b"Less common")
i3 = r.data.find(b"Rare")
check("portal library groups by tier under plain-language headings",
      -1 < i1 < i2 < i3)
check("implemented rare entries are client-facing in the library",
      b"Retirement Division (QDRO)" in r.data)
staff.post("/clients/2/portal/packet", data={
    "packet_slug": "starting-divorce", "case_id": "2",
    "csrf_token": csrf(staff)})
asg = dbq("SELECT * FROM portal_packet_assignments WHERE client_id"
          " = 2 AND packet_slug = 'starting-divorce'"
          " AND unassigned_at IS NULL")[0]
exp_min = fl.packet_est_minutes(fl.packet_def("starting-divorce"))
r = B.get(f"/portal/packets/{asg['id']}")
check("packet page shows the estimated total minutes",
      f"About {exp_min} minutes in total".encode() in r.data,
      f"expected {exp_min}")
r = B.get("/portal/")
check("home packet card shows the estimated total too",
      f"About {exp_min} minutes in total".encode() in r.data)
r = A.get("/portal/library/declaration?step=5")
check("wizard review screen carries per-section Edit jumps",
      r.status_code == 200 and b"Edit this section" in r.data
      and b"/portal/library/declaration?step=0" in r.data)
r = staff.get("/library")
check("staff library intro no longer claims rare is catalog-only",
      b"Rare entries are catalog-only in this release" not in r.data)

# ======================================================================
# 7. Invalidity end-to-end — the variant names itself on the output
# ======================================================================
pet_fields = fl.wizard_fields(fl.wizard_def("petition_divorce"))
action_field = [f for f in pet_fields
                if f["name"] == "action_type"][0]
invalidity = [o for o in action_field["options"]
              if "nvalidity" in o][0]
wiz_post(A, "petition-divorce", 0, {
    "action_type": invalidity,
    "cf_marriage_date": "keep", "marriage_date": "",
    "cf_marriage_place": "keep", "marriage_place": "",
    "separation_date": "2026-03-01",
    "living_situation": "We live apart"}, "next")
wiz_post(A, "petition-divorce", 1, {
    "children_name": ["Kid Anderson"],
    "children_dob": ["2018-05-01"]}, "next")
wiz_post(A, "petition-divorce", 2, {
    "property_request": "Very little to divide.",
    "debts_overview": "None together."}, "next")
wiz_post(A, "petition-divorce", 3, {
    "maintenance_request": "None", "name_change": "",
    "other_relief": ""}, "next")
wiz_post(A, "petition-divorce", 4, {}, "submit")
pet = dbq("SELECT * FROM portal_form_submissions WHERE client_id = 1"
          " AND form_key = 'petition_divorce'")[0]
check("invalidity-variant petition submits",
      pet["status"] == "submitted")
staff.post(f"/portal-review/forms/{pet['id']}/import",
           data={"csrf_token": csrf(staff)})
staff.post(f"/portal-review/forms/{pet['id']}/generate-document",
           data={"csrf_token": csrf(staff)})
pd = dbq("SELECT * FROM documents WHERE case_id = 1 AND"
         " original_name = 'Petition_for_Dissolution_DRAFT.pdf'")
pdc = dbq("SELECT * FROM documents WHERE case_id = 1 AND"
          " original_name ="
          " 'Petition_for_Dissolution_DRAFT_Client_Data.pdf'")
check("variant generates the petition + data sheet",
      len(pd) == 1 and len(pdc) == 1)
if pd:
    text = pdf_text_norm(pd[0])
    check("generated petition NAMES the action: Invalidity "
          "(annulment)",
          b"TYPEOFACTION" in text and b"Invalidityannulment"
          in text)
if pdc:
    check("data sheet carries the variant choice too",
          b"Invalidity" in pdf_text_norm(pdc[0]))

# ======================================================================
# 8. Cross-client hammer on the new surface
# ======================================================================
for slug in ("protection-order-petition",
             "parentage-temporary-order", "gal-order",
             "parentage-immediate-restraining"):
    r = A.get(f"/portal/library/{slug}")
    check(f"catalog-only slug {slug} stays 404 in the portal",
          r.status_code == 404)
r = B.get("/portal/library/contempt-motion?step=1")
check("B's contempt wizard shows none of A's answers",
      b"ZZZMARK" not in r.data)
r = B.get("/portal/library/qdro-data?step=0")
check("B's QDRO wizard shows none of A's plan names",
      b"ZZZPLAN" not in r.data)
r = B.get("/portal/library")
check("B's library shows B's own state only (no A markers)",
      b"ZZZPLAN" not in r.data and b"ZZZMARK" not in r.data)
anon = appmod.app.test_client()
r = anon.post(f"/portal/drafts/{stale['id']}/dismiss", data={})
check("anonymous dismiss redirects to portal login",
      r.status_code == 302 and "/portal/login" in r.headers["Location"])
r = A.get("/library")
check("portal session cannot open the staff library stats page",
      r.status_code == 302 and "/login" in r.headers["Location"])

print()
if FAILURES:
    print("FAILURES:", len(FAILURES))
    for f in FAILURES:
        print(" -", f)
    raise SystemExit(1)
print("ALL V210 CHECKS PASSED")
'''


def main():
    tmp = tempfile.mkdtemp(prefix="lawfirm-v210-")
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        root = os.path.dirname(here)
        for name in ("app.py", "crypto.py", "deadlines.py",
                     "integrations.py", "invoice_pdf.py", "payroll.py",
                     "paystub_pdf.py", "template_defs.py",
                     "template_pdf.py", "form_library.py"):
            shutil.copy(os.path.join(root, name), tmp)
        shutil.copytree(os.path.join(root, "templates"),
                        os.path.join(tmp, "templates"))
        shutil.copytree(os.path.join(root, "static"),
                        os.path.join(tmp, "static"))
        os.makedirs(os.path.join(tmp, "instance"))
        testfile = os.path.join(tmp, "run_v210_checks.py")
        with open(testfile, "w") as fh:
            fh.write(textwrap.dedent(TEST_CODE))
        proc = subprocess.run([sys.executable, testfile], cwd=tmp,
                              capture_output=True, text=True,
                              timeout=600)
        sys.stdout.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        return proc.returncode
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
