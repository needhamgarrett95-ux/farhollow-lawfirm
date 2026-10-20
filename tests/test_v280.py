#!/usr/bin/env python3
"""
Tests for v2.8.0 — Document Library, Profile Vault, Wizard Engine.

  * Catalog integrity: every implemented entry has a wizard def,
    every vault binding names a real vault fact, all tiers present,
    and the FL Divorce 211 correction is in the registry (211 is the
    Response; the Certificate of Dissolution is DOH 422-027).
  * Vault scoping hammer: client B never sees client A's confirmed
    facts; a CHANGED confirm answer parks in client_vault_pending
    and the confirmed fact is untouched until staff import (which
    confirms) — dismiss would reject.
  * Wizard engine: draft save/resume server-side, confirm-card
    server rule (posting a fake value with "keep" keeps the vault
    value), required-field gating, attestation gating, submit
    freezes the snapshot.
  * Declaration end-to-end: vault prefill renders as confirm cards,
    submit -> staff queue -> import -> generation produces a PDF
    with the caption, case number, numbered-paragraph content, the
    perjury block, and the DRAFT banner.
  * Every implemented wizard runs: financial declaration (pending
    flow), confidential information (masked SSN, encrypted vault
    writes), petition (draft petition + data sheet), parenting plan,
    support worksheet data, temporary orders, certificate.
  * Staff library view: tiers, verified/unverified labels, drafts in
    progress, enable/disable actually gates the portal.
  * Boundaries: unauthenticated -> login; portal session never
    satisfies staff routes; catalog-only slugs 404 in the portal.

Run:  python3 tests/test_v280.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable

TEST_CODE = r'''
import io, json, os, re, sqlite3, sys, zlib, base64
sys.path.insert(0, ".")
import app as appmod
import form_library as fl
from werkzeug.security import generate_password_hash

appmod.app.config.update(TESTING=True)
with appmod.app.app_context():
    appmod.init_db()

FAILURES = []
def check(name, cond, extra=""):
    print(("PASS" if cond else "FAIL"), "-", name, extra)
    if not cond:
        FAILURES.append(name)

DBP = "instance/lawfirm.db"
def dbq(sql, args=()):
    db = sqlite3.connect(DBP); db.row_factory = sqlite3.Row
    rows = db.execute(sql, args).fetchall(); db.close()
    return rows
def dbx(sql, args=()):
    db = sqlite3.connect(DBP); db.execute(sql, args); db.commit(); db.close()

def csrf(cl):
    with cl.session_transaction() as s:
        return s["csrf_token"]

def staff_login(cl, username="admin", password="changeme123",
                new_password="AdminPass123!"):
    cl.get("/login")
    with cl.session_transaction() as s:
        s["csrf_token"] = "tok"
    cl.post("/login", data={"username": username, "password": password,
                            "csrf_token": "tok"})
    if password == "changeme123":
        cl.post("/change-password", data={
            "current_password": password, "new_password": new_password,
            "confirm_password": new_password, "csrf_token": csrf(cl)})

staff = appmod.app.test_client()
staff_login(staff)

NOW = "2026-10-20T00:00:00+00:00"
enc = appmod.encrypt_value
# Client A comes with a stocked vault: spouse, encrypted DOB/SSN, a
# child, vault-store facts, and case financials.
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

def invite_token_for(cl, client_id):
    cl.post(f"/clients/{client_id}/portal/invite",
            data={"csrf_token": csrf(cl)})
    r = cl.get(f"/clients/{client_id}")
    m = re.search(rb"/portal/accept-invite/([A-Za-z0-9_\-]+)", r.data)
    return m.group(1).decode() if m else None

def accept_invite(token, password):
    cl = appmod.app.test_client()
    cl.get(f"/portal/accept-invite/{token}")
    r = cl.post(f"/portal/accept-invite/{token}", data={
        "password": password, "confirm_password": password,
        "csrf_token": csrf(cl)})
    return cl

def portal_login(cl, email, password):
    cl.get("/portal/login")
    return cl.post("/portal/login", data={
        "email": email, "password": password, "csrf_token": csrf(cl)})

A = accept_invite(invite_token_for(staff, 1), "AlicePass123")
B = accept_invite(invite_token_for(staff, 2), "BobPass12345")
portal_login(A, "alice@example.com", "AlicePass123")
portal_login(B, "bob@example.com", "BobPass12345")

def wiz_post(cl, slug, step, fields, action):
    data = {"step": str(step), "action": action, "csrf_token": csrf(cl)}
    data.update(fields)
    return cl.post(f"/portal/library/{slug}", data=data)

def pdf_text_norm(doc_row):
    path = os.path.join(appmod._case_doc_dir(doc_row["case_id"]),
                        doc_row["stored_name"])
    raw = open(path, "rb").read()
    out = []
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", raw, re.S):
        chunk = m.group(1).strip()
        data = None
        try:
            data = zlib.decompress(chunk)
        except Exception:
            pass
        if data is None:
            # reportlab content streams are ASCII85 + Flate.
            try:
                data = zlib.decompress(base64.a85decode(
                    chunk.rstrip(b"~>").strip(), adobe=False))
            except Exception:
                pass
        if data:
            out.append(data)
    blob = b"\n".join(out)
    return re.sub(rb"[^A-Za-z0-9]", b"", blob)

# ======================================================================
# 1. Catalog registry integrity
# ======================================================================
check("catalog has 50+ entries", len(fl.LIBRARY) >= 50,
      f"({len(fl.LIBRARY)})")
tiers = {e["tier"] for e in fl.LIBRARY}
check("all three tiers present", tiers == {"common", "uncommon", "rare"})
impl = [e for e in fl.LIBRARY if e["implemented"]]
check("8 common wizards + sealed attachment (v2.9.0: +8 uncommon "
      "= 17 live)",
      len(impl) == 17
      and sum(1 for e in impl if e["tier"] == "common") == 9
      and sum(1 for e in impl if e["tier"] == "uncommon") == 8
      and all(e["tier"] in ("common", "uncommon") for e in impl))
check("every implemented entry has a wizard def",
      all(e["wizard"] in fl.WIZARD_DEFS for e in impl))
check("wizard def keys and entry wizards line up",
      {e["wizard"] for e in impl} == set(fl.WIZARD_DEFS))
check("wizard def slugs match their catalog entry slugs",
      all(fl.LIBRARY_BY_SLUG[w["slug"]]["wizard"] == w["key"]
          and fl.LIBRARY_BY_SLUG[w["slug"]]["slug"] == w["slug"]
          for w in fl.WIZARD_DEFS.values()))
bad = [k for e in fl.LIBRARY for k in e["vault_fields"]
       if k not in fl.VAULT_FACTS]
check("every catalog vault field is a real vault fact", not bad,
      str(bad))
bad = [f["name"] for w in fl.WIZARD_DEFS.values()
       for f in fl.wizard_fields(w)
       if f.get("vault") and f["vault"] != "children"
       and f["vault"] not in fl.VAULT_FACTS]
check("every wizard vault binding is a real vault fact", not bad,
      str(bad))
check("FL Divorce 211 is the Response, not the certificate",
      fl.LIBRARY_BY_SLUG["response-marriage"]["form_number"]
      == "FL Divorce 211"
      and fl.LIBRARY_BY_SLUG["certificate-dissolution"]["form_number"]
      == "DOH 422-027")
check("unverified entries are honestly flagged",
      sum(1 for e in fl.LIBRARY if not e["verified"]) >= 4)
check("the declaration is the flagship (FL All Family 135)",
      fl.LIBRARY_BY_SLUG["declaration"]["form_number"]
      == "FL All Family 135")

# ======================================================================
# 2. Boundaries on the new routes
# ======================================================================
anon = appmod.app.test_client()
r = anon.get("/portal/library")
check("unauthenticated /portal/library -> portal login",
      r.status_code == 302
      and "/portal/login" in r.headers.get("Location", ""))
r = anon.get("/portal/library/declaration")
check("unauthenticated wizard URL -> portal login",
      r.status_code == 302
      and "/portal/login" in r.headers.get("Location", ""))
r = anon.get("/library")
check("unauthenticated /library -> staff login",
      r.status_code == 302
      and r.headers.get("Location", "").endswith("/login"))
r = A.get("/library")
check("portal session hitting staff /library -> staff login",
      r.status_code == 302
      and r.headers.get("Location", "").endswith("/login"))
r = staff.get("/portal/library")
check("staff session hitting the portal library -> portal login",
      r.status_code == 302
      and "/portal/login" in r.headers.get("Location", ""))
r = A.get("/portal/library/summons-marriage")
check("catalog-only entry is NOT client-facing (404)",
      r.status_code == 404)
r = A.get("/portal/library/no-such-doc")
check("unknown library slug -> 404", r.status_code == 404)

# ======================================================================
# 3. Client-facing library + Documents "Forms to complete"
# ======================================================================
r = A.get("/portal/library")
check("A's library lists the implemented common tier",
      b"Declaration" in r.data and b"FL All Family 135" in r.data
      and b"Parenting Plan" in r.data and b"DOH 422-027" in r.data)
check("A's library shows uncommon live but NO rare/unverified "
      "entries (v2.9.0)",
      b"FL Divorce 211" in r.data and b"PO 001" not in r.data
      and b"FL Relocate 706" not in r.data)
r = A.get("/portal/documents")
check("Documents area shows 'Forms to complete'",
      b"Forms to complete" in r.data and b"FL All Family 135" in r.data)
r = A.get("/portal/forms")
check("Forms page links the document library",
      b"Document library" in r.data)

# ======================================================================
# 4. Vault prefill renders as CONFIRM cards; B sees none of A's facts
# ======================================================================
r = A.get("/portal/library/declaration?step=0")
check("declaration step 1 renders confirm cards from the vault",
      b"We have:" in r.data and b"Andrew Anderson" in r.data
      and b"2015-06-20" in r.data and b"Port Angeles, WA" in r.data
      and b"Still right" in r.data)
check("children repeater is prefilled from the record",
      b"Kid Anderson" in r.data and b"2018-05-01" in r.data)
r = B.get("/portal/library/declaration?step=0")
check("B's declaration shows NONE of A's facts",
      b"Andrew Anderson" not in r.data and b"2015-06-20" not in r.data
      and b"Kid Anderson" not in r.data and b"We have:" not in r.data)
r = A.get("/portal/library/confidential-information?step=0")
check("SSN confirm card is MASKED (last 4 only)",
      "••••6789".encode() in r.data
      and b"123-45-6789" not in r.data)

# ======================================================================
# 5. Declaration end-to-end (flagship)
# ======================================================================
# Step 0: "keep" must beat a tampered posted value (server truth);
# a real change is accepted into the DRAFT only.
wiz_post(A, "declaration", 0, {
    "case_id": "1",
    "cf_spouse_name": "keep", "spouse_name": "Mallory Intruder",
    "cf_marriage_date": "change", "marriage_date": "2015-06-21",
    "cf_marriage_place": "keep", "marriage_place": "x",
    "separation_date": "",
    "children_name": ["Kid Anderson"], "children_dob": ["2018-05-01"],
}, "next")
draft = dbq("SELECT * FROM portal_form_submissions WHERE client_id = 1"
            " AND form_key = 'declaration' AND status = 'draft'")[0]
ddata = json.loads(draft["data_json"])
check("confirm-card KEEP wins over a tampered posted value",
      ddata["spouse_name"] == "Andrew Anderson")
check("confirm-card CHANGE lands in the draft",
      ddata["marriage_date"] == "2015-06-21")
check("the confirmed fact is NOT overwritten by the draft",
      dbq("SELECT value FROM client_vault_facts WHERE client_id = 1"
          " AND fact_key = 'marriage.date'")[0]["value"] == "2015-06-20")
r = A.get("/portal/library/declaration?step=0")
check("draft resumes server-side (changed date shown)",
      b"2015-06-21" in r.data)

wiz_post(A, "declaration", 1, {
    "children_week": "I get the kids up, make breakfast, and take "
                     "them to school every weekday.",
    "children_school": "Both are doing well in school. I take them "
                       "to every appointment.",
    "children_concerns": ""}, "next")
wiz_post(A, "declaration", 2, {
    "cf_client_employer": "keep", "client_employer": "x",
    "cf_client_gross_income": "keep", "client_gross_income": "x",
    "cf_client_net_income": "keep", "client_net_income": "x",
    "money_story": "I have carried the mortgage alone since March."},
    "next")
wiz_post(A, "declaration", 3, {"safety_concerns": ""}, "next")
wiz_post(A, "declaration", 4, {
    "asks": ["Order child support",
             "Divide our property and debts fairly"],
    "asks_details": "I am asking for the parenting plan I proposed "
                    "and support under the guidelines."}, "next")
r = A.get("/portal/library/declaration?step=5")
check("review screen summarizes the answers + attestation block",
      b"Review your answers" in r.data
      and b"penalty of perjury" in r.data
      and b"Order child support" in r.data)
# Attestation gating: no checkbox -> no submit.
wiz_post(A, "declaration", 5, {"attest_name": "Alice Anderson"},
         "submit")
check("submit is refused without the attestation checkbox",
      dbq("SELECT status FROM portal_form_submissions WHERE id = ?",
          (draft["id"],))[0]["status"] == "draft")
wiz_post(A, "declaration", 5, {
    "attest_name": "Alice Anderson", "attest_agree": "yes"}, "submit")
sub = dbq("SELECT * FROM portal_form_submissions WHERE id = ?",
          (draft["id"],))[0]
snap = json.loads(sub["snapshot_json"])
check("declaration submitted with a frozen snapshot",
      sub["status"] == "submitted"
      and "make breakfast" in snap["children_week"]
      and snap["attest_name"] == "Alice Anderson")
pend = dbq("SELECT * FROM client_vault_pending WHERE submission_id = ?",
           (sub["id"],))
check("the marriage-date change pends for staff (not applied)",
      len(pend) == 1 and pend[0]["fact_key"] == "marriage.date"
      and pend[0]["status"] == "pending"
      and pend[0]["new_value"] == "2015-06-21")
check("confirmed marriage date still the old value pre-import",
      dbq("SELECT value FROM client_vault_facts WHERE client_id = 1"
          " AND fact_key = 'marriage.date'")[0]["value"] == "2015-06-20")

r = staff.get("/portal-review")
check("declaration appears in the staff review queue",
      b"Declaration" in r.data)
r = staff.get(f"/portal-review/forms/{sub['id']}")
check("staff review shows answers + the pending-change section",
      b"make breakfast" in r.data
      and b"Changes to saved information" in r.data
      and b"2015-06-21" in r.data)
r = B.get(f"/portal-review/forms/{sub['id']}")
check("portal session hitting staff review -> staff login",
      r.status_code == 302
      and r.headers.get("Location", "").endswith("/login"))

staff.post(f"/portal-review/forms/{sub['id']}/import",
           data={"csrf_token": csrf(staff)})
check("import confirms the pending vault update",
      dbq("SELECT value FROM client_vault_facts WHERE client_id = 1"
          " AND fact_key = 'marriage.date'")[0]["value"] == "2015-06-21"
      and dbq("SELECT status FROM client_vault_pending"
              " WHERE submission_id = ?",
              (sub["id"],))[0]["status"] == "confirmed")
staff.post(f"/portal-review/forms/{sub['id']}/generate-document",
           data={"csrf_token": csrf(staff)})
docs = dbq("SELECT * FROM documents WHERE case_id = 1"
           " AND original_name = 'Declaration.pdf'")
check("declaration document generated into the case file",
      len(docs) == 1)
if docs:
    txt = pdf_text_norm(docs[0])
    check("PDF has the caption, case number, declarant",
          b"DECLARATION" in txt and b"26200101" in txt
          and b"AliceAnderson" in txt)
    check("PDF has numbered-paragraph content (children roster)",
          b"KidAnderson" in txt and b"makebreakfast" in txt)
    check("PDF has the perjury block and the DRAFT banner",
          b"penaltyofperjury" in txt and b"DRAFT" in txt)

# Snapshot freeze: a new draft run must not mutate the submitted copy.
wiz_post(A, "declaration", 1, {
    "children_week": "TOTALLY DIFFERENT TEXT", "children_school": "",
    "children_concerns": ""}, "save_exit")
snap2 = json.loads(dbq(
    "SELECT snapshot_json FROM portal_form_submissions WHERE id = ?",
    (sub["id"],))[0]["snapshot_json"])
check("submitted snapshot stays frozen after a new draft starts",
      "make breakfast" in snap2["children_week"])

# ======================================================================
# 6. Financial Declaration — required gating + financial pending flow
# ======================================================================
wiz_post(A, "financial-declaration", 0, {
    "case_id": "1", "cf_client_employer": "keep", "client_employer": "",
    "client_job_title": "Millwright",
    "cf_client_gross_income": "change", "client_gross_income": "",
    "cf_client_net_income": "keep", "client_net_income": ""}, "next")
for st in (1, 2, 3):
    wiz_post(A, "financial-declaration", st, {}, "next")
wiz_post(A, "financial-declaration", 4, {}, "submit")
fd = dbq("SELECT * FROM portal_form_submissions WHERE client_id = 1"
         " AND form_key = 'financial_declaration'")[0]
check("required-field gating blocks submit (gross income missing)",
      fd["status"] == "draft")
wiz_post(A, "financial-declaration", 0, {
    "cf_client_employer": "keep", "client_employer": "",
    "client_job_title": "Millwright",
    "cf_client_gross_income": "change",
    "client_gross_income": "4,200",
    "cf_client_net_income": "keep", "client_net_income": ""}, "next")
wiz_post(A, "financial-declaration", 4, {}, "submit")
fd = dbq("SELECT * FROM portal_form_submissions WHERE id = ?",
         (fd["id"],))[0]
check("financial declaration submits once required fields are in",
      fd["status"] == "submitted")
check("changed gross income pends; case financials untouched",
      dbq("SELECT value FROM case_financials WHERE case_id = 1"
          " AND key = 'client_gross_income'")[0]["value"] == "4,000"
      and len(dbq("SELECT * FROM client_vault_pending"
                  " WHERE submission_id = ?", (fd["id"],))) == 1)
staff.post(f"/portal-review/forms/{fd['id']}/import",
           data={"csrf_token": csrf(staff)})
check("import applies the confirmed income + first-time job title",
      dbq("SELECT value FROM case_financials WHERE case_id = 1"
          " AND key = 'client_gross_income'")[0]["value"] == "4,200"
      and dbq("SELECT value FROM client_vault_facts WHERE client_id = 1"
              " AND fact_key = 'client.job_title'")[0]["value"]
      == "Millwright")
staff.post(f"/portal-review/forms/{fd['id']}/generate-document",
           data={"csrf_token": csrf(staff)})
check("financial declaration generates its data sheet",
      len(dbq("SELECT * FROM documents WHERE case_id = 1 AND"
              " original_name ="
              " 'Financial_Declaration_Client_Data.pdf'")) == 1)

# ======================================================================
# 7. Confidential Information — masked confirms, encrypted vault writes
# ======================================================================
wiz_post(A, "confidential-information", 0, {
    "cf_date_of_birth": "keep", "date_of_birth": "",
    "cf_ssn": "keep", "ssn": "",
    "driver_license": "WDL ANDER 42",
    "cf_address": "keep", "address": "",
    "cf_phone": "keep", "phone": ""}, "next")
wiz_post(A, "confidential-information", 1, {
    "cf_spouse_name": "keep", "spouse_name": "",
    "cf_spouse_dob": "keep", "spouse_dob": "",
    "spouse_ssn": "", "service_address": "9 Dock Street"}, "next")
wiz_post(A, "confidential-information", 2, {
    "children_name": ["Kid Anderson"],
    "children_dob": ["2018-05-01"]}, "next")
wiz_post(A, "confidential-information", 3, {
    "accounts_protected": "Peninsula Credit Union checking 4471"},
    "next")
wiz_post(A, "confidential-information", 4, {}, "submit")
cif = dbq("SELECT * FROM portal_form_submissions WHERE client_id = 1"
          " AND form_key = 'confidential_information'")[0]
check("confidential information wizard submits", cif["status"]
      == "submitted")
staff.post(f"/portal-review/forms/{cif['id']}/import",
           data={"csrf_token": csrf(staff)})
vf = {x["fact_key"]: x["value"] for x in dbq(
    "SELECT * FROM client_vault_facts WHERE client_id = 1")}
check("driver license stored ENCRYPTED in the vault",
      vf["client.driver_license"] != "WDL ANDER 42"
      and appmod.decrypt_value(vf["client.driver_license"])
      == "WDL ANDER 42")
check("service address + protected accounts land in the vault",
      vf["service.address"] == "9 Dock Street"
      and appmod.decrypt_value(vf["client.accounts_protected"])
      == "Peninsula Credit Union checking 4471")
check("SSN on the client record is unchanged and encrypted",
      appmod.decrypt_value(dbq(
          "SELECT ssn FROM clients WHERE id = 1")[0]["ssn"])
      == "123-45-6789")
staff.post(f"/portal-review/forms/{cif['id']}/generate-document",
           data={"csrf_token": csrf(staff)})
check("CIF generates a data sheet into the client's case",
      len(dbq("SELECT * FROM documents WHERE case_id = 1 AND"
              " original_name ="
              " 'Confidential_Information_Client_Data.pdf'")) == 1)

# ======================================================================
# 8. Petition (partial) — draft petition + data sheet
# ======================================================================
wiz_post(A, "petition-divorce", 0, {
    "cf_marriage_date": "keep", "marriage_date": "",
    "cf_marriage_place": "keep", "marriage_place": "",
    "separation_date": "2026-03-01",
    "living_situation": "We live apart"}, "next")
wiz_post(A, "petition-divorce", 1, {
    "children_name": ["Kid Anderson"],
    "children_dob": ["2018-05-01"]}, "next")
wiz_post(A, "petition-divorce", 2, {
    "property_request": "The house to me, the truck to him, accounts "
                        "split evenly.",
    "debts_overview": "One card, about $2,000, in both names."},
    "next")
wiz_post(A, "petition-divorce", 3, {
    "maintenance_request": "None", "name_change": "",
    "other_relief": ""}, "next")
wiz_post(A, "petition-divorce", 4, {}, "submit")
pet = dbq("SELECT * FROM portal_form_submissions WHERE client_id = 1"
          " AND form_key = 'petition_divorce'")[0]
check("petition data capture submits", pet["status"] == "submitted")
staff.post(f"/portal-review/forms/{pet['id']}/import",
           data={"csrf_token": csrf(staff)})
staff.post(f"/portal-review/forms/{pet['id']}/generate-document",
           data={"csrf_token": csrf(staff)})
pd = dbq("SELECT * FROM documents WHERE case_id = 1 AND"
         " original_name = 'Petition_for_Dissolution_DRAFT.pdf'")
check("petition generates a DRAFT petition + data sheet",
      len(pd) == 1 and len(dbq(
          "SELECT * FROM documents WHERE case_id = 1 AND"
          " original_name LIKE 'Petition_for_Dissolution_DRAFT%'")) == 2)
if pd:
    txt = pdf_text_norm(pd[0])
    check("draft petition PDF is bannered DRAFT with the caption",
          b"DRAFT" in txt and b"PETITIONFORDISSOLUTION" in txt)

# ======================================================================
# 9. Parenting Plan (partial) + Support data + Temporary Orders
# ======================================================================
wiz_post(A, "parenting-plan", 0, {
    "case_id": "1", "children_name": ["Kid Anderson"],
    "children_dob": ["2018-05-01"]}, "next")
wiz_post(A, "parenting-plan", 1, {
    "living_now": "The kids are with me on school nights."}, "next")
wiz_post(A, "parenting-plan", 2, {
    "residential_schedule": "With me Monday to Friday; with their "
                            "dad Friday 6pm to Sunday 6pm, alternating "
                            "weekends.",
    "holidays": "Alternate Thanksgiving and Christmas each year."},
    "next")
wiz_post(A, "parenting-plan", 3, {
    "decision_making": "Jointly — both parents together",
    "decision_details": "", "restrictions": ["None of these"],
    "restrictions_details": ""}, "next")
wiz_post(A, "parenting-plan", 4, {
    "transportation": "Exchanges at the school parking lot."}, "next")
wiz_post(A, "parenting-plan", 5, {}, "submit")
pp = dbq("SELECT * FROM portal_form_submissions WHERE client_id = 1"
         " AND form_key = 'parenting_plan'")[0]
staff.post(f"/portal-review/forms/{pp['id']}/import",
           data={"csrf_token": csrf(staff)})
staff.post(f"/portal-review/forms/{pp['id']}/generate-document",
           data={"csrf_token": csrf(staff)})
ppd = dbq("SELECT * FROM documents WHERE case_id = 1 AND"
          " original_name = 'Parenting_Plan_DRAFT.pdf'")
check("parenting plan generates a DRAFT plan document",
      dbq("SELECT status FROM portal_form_submissions WHERE id = ?",
          (pp["id"],))[0]["status"] == "imported" and len(ppd) == 1)
if ppd:
    txt = pdf_text_norm(ppd[0])
    check("draft parenting plan PDF bannered + titled",
          b"DRAFT" in txt and b"PARENTINGPLAN" in txt)

wiz_post(A, "child-support-worksheet", 0, {
    "case_id": "1",
    "cf_client_gross_income": "keep", "client_gross_income": "",
    "cf_client_net_income": "keep", "client_net_income": ""}, "next")
wiz_post(A, "child-support-worksheet", 1, {
    "other_parent_net_income": "2,900",
    "other_income_notes": "From his pay stubs."}, "next")
wiz_post(A, "child-support-worksheet", 2, {
    "children_name": ["Kid Anderson"],
    "children_dob": ["2018-05-01"],
    "daycare": "450", "health_insurance": "210"}, "next")
wiz_post(A, "child-support-worksheet", 3, {}, "submit")
sw = dbq("SELECT * FROM portal_form_submissions WHERE client_id = 1"
         " AND form_key = 'support_worksheet_data'")[0]
staff.post(f"/portal-review/forms/{sw['id']}/import",
           data={"csrf_token": csrf(staff)})
staff.post(f"/portal-review/forms/{sw['id']}/generate-document",
           data={"csrf_token": csrf(staff)})
swd = dbq("SELECT * FROM documents WHERE case_id = 1 AND"
          " original_name = 'Child_Support_Worksheet.pdf'")
check("support data wizard feeds the worksheet generator",
      dbq("SELECT status FROM portal_form_submissions WHERE id = ?",
          (sw["id"],))[0]["status"] == "imported" and len(swd) == 1)
if swd:
    txt = pdf_text_norm(swd[0])
    check("support worksheet PDF carries the DRAFT banner",
          b"DRAFT" in txt and b"WORKSHEET" in txt)

wiz_post(A, "temporary-orders", 0, {
    "case_id": "1",
    "needs": ["Order temporary child support",
              "Set a temporary parenting schedule"]}, "next")
wiz_post(A, "temporary-orders", 1, {
    "housing_details": "", "money_details": "Support so the mortgage "
                                           "stays current.",
    "kids_details": ""}, "next")
wiz_post(A, "temporary-orders", 2, {
    "restraints_details": "",
    "urgency": "Routine — the normal motion calendar is fine",
    "urgency_details": ""}, "next")
wiz_post(A, "temporary-orders", 3, {}, "submit")
to = dbq("SELECT * FROM portal_form_submissions WHERE client_id = 1"
         " AND form_key = 'temporary_orders'")[0]
staff.post(f"/portal-review/forms/{to['id']}/import",
           data={"csrf_token": csrf(staff)})
staff.post(f"/portal-review/forms/{to['id']}/generate-document",
           data={"csrf_token": csrf(staff)})
check("temporary orders capture generates its data sheet",
      dbq("SELECT status FROM portal_form_submissions WHERE id = ?",
          (to["id"],))[0]["status"] == "imported" and len(dbq(
          "SELECT * FROM documents WHERE case_id = 1 AND"
          " original_name = 'Temporary_Orders_Client_Data.pdf'")) == 1)

# ======================================================================
# 10. Intake employer now writes a vault fact (Part 2 extension)
# ======================================================================
def form_post(cl, key, step, fields, action):
    data = {"step": str(step), "action": action,
            "csrf_token": csrf(cl)}
    data.update(fields)
    return cl.post(f"/portal/forms/{key}", data=data)

form_post(B, "client_intake", 0, {
    "email": "bob@example.com", "phone": "360-555-0200",
    "address": "", "date_of_birth": ""}, "next")
form_post(B, "client_intake", 1, {
    "spouse_name": "", "spouse_dob": ""}, "next")
form_post(B, "client_intake", 2, {
    "child1_name": "", "child1_dob": "", "child2_name": "",
    "child2_dob": "", "child3_name": "", "child3_dob": "",
    "children_notes": ""}, "next")
form_post(B, "client_intake", 3, {
    "employer_name": "Baker Logging", "monthly_income": ""}, "submit")
bsub = dbq("SELECT * FROM portal_form_submissions WHERE client_id = 2"
           " AND form_key = 'client_intake'")[0]
staff.post(f"/portal-review/forms/{bsub['id']}/import",
           data={"csrf_token": csrf(staff)})
bvf = dbq("SELECT * FROM client_vault_facts WHERE client_id = 2"
          " AND fact_key = 'client.employer'")
check("intake import writes the employer into B's vault",
      len(bvf) == 1 and bvf[0]["value"] == "Baker Logging"
      and bvf[0]["source"] == "portal:client_intake")
check("A's vault is untouched by B's import",
      dbq("SELECT value FROM client_vault_facts WHERE client_id = 1"
          " AND fact_key = 'client.employer'")[0]["value"]
      == "Harbor Mill")

# ======================================================================
# 11. Staff library view + enable/disable + drafts in progress
# ======================================================================
wiz_post(B, "certificate-dissolution", 0, {
    "birth_name": "Robert Baker", "birth_place": "Forks, WA",
    "date_of_birth": "1990-01-15"}, "save_exit")
r = staff.get("/library")
check("staff library shows the full catalog with tiers",
      b"Common tier" in r.data and b"Uncommon tier" in r.data
      and b"Rare tier" in r.data and b"FL Divorce 201" in r.data
      and b"DOH 422-027" in r.data)
check("staff library flags unverified numbers + later releases",
      b"number unverified" in r.data and b"In a later release" in r.data)
check("staff library shows B's draft in progress",
      b"Drafts in progress" in r.data and b"Bob" in r.data
      and b"Certificate of Dissolution" in r.data)
r = B.get("/portal/library/certificate-dissolution?step=0")
check("B's certificate draft resumed with B's own fact",
      b"Robert Baker" in r.data and b"Alice" not in r.data)

staff.post("/library/declaration/toggle",
           data={"csrf_token": csrf(staff)})
r = A.get("/portal/library")
check("disabled document disappears from the client library",
      b"FL All Family 135" not in r.data)
r = A.get("/portal/library/declaration")
check("disabled document's wizard URL 404s", r.status_code == 404)
staff.post("/library/declaration/toggle",
           data={"csrf_token": csrf(staff)})
r = A.get("/portal/library/declaration")
check("re-enabled document's wizard opens again",
      r.status_code == 200)
check("toggle is audited",
      len(dbq("SELECT * FROM audit_log WHERE action ="
              " 'library_toggled'")) >= 2)

print()
print("FAILURES:", len(FAILURES))
for f in FAILURES:
    print("  FAILED:", f)
sys.exit(1 if FAILURES else 0)
'''


def main():
    scratch = tempfile.mkdtemp(prefix="lawfirm-v280-")
    try:
        for name in ("app.py", "crypto.py", "deadlines.py",
                     "integrations.py", "invoice_pdf.py", "payroll.py",
                     "paystub_pdf.py", "template_defs.py",
                     "template_pdf.py", "form_library.py"):
            shutil.copy(os.path.join(ROOT, name), scratch)
        shutil.copytree(os.path.join(ROOT, "templates"),
                        os.path.join(scratch, "templates"))
        shutil.copytree(os.path.join(ROOT, "static"),
                        os.path.join(scratch, "static"))
        with open(os.path.join(scratch, "run_tests.py"), "w") as fh:
            fh.write(TEST_CODE)
        proc = subprocess.run(
            [PY, "run_tests.py"], cwd=scratch,
            capture_output=True, text=True, timeout=600,
        )
        sys.stdout.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        return proc.returncode
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
