#!/usr/bin/env python3
"""
Tests for v2.9.0 — Scenario Packets + Uncommon Tier.

  * Registry integrity extended: 8 packet defs; every packet step
    references live material (wizard step -> implemented catalog
    entry with a wizard def; upload step -> a real portal doc type;
    info step -> real guidance text); every packet carries the exact
    COMPLIANCE guidance line; 17 implemented entries (9 common +
    8 uncommon); the Modify numbers are right (501 = support,
    601 = parenting plan) and the Acknowledgment of Parentage is
    DOH 422-159 (303 is the Residential Schedule).
  * Assignment flow: staff assign from the client record AND from
    the Library view; a packet's upload steps create tracked
    document requests; duplicate assignment refused; unassign
    retires the packet and cancels its open requests; assignment is
    audit-logged and leaves a portal activity entry.
  * Step state is REAL state: info ack, upload-accept, and wizard
    submit each advance exactly their step; an upload merely SENT
    does not count until staff accept it.
  * Sequential flag: the responding packet's read-first step locks
    the steps behind it in the checklist until acknowledged.
  * Boundary hammer: client B cannot see, open, ack, or affect
    client A's packets anywhere; portal sessions never satisfy the
    staff assign routes; unknown assignments 404.
  * Every new uncommon wizard: draft resume, submit freeze, staff
    review path, data-sheet generation. Fee waiver renders the
    vault financials as confirm cards. The petition capture's
    legal-separation variant lands on the generated documents.
  * Completion: optional steps never block completion; finishing
    the counted steps stamps completed_at and posts the activity
    entry the dashboard widget shows.

Run:  python3 tests/test_v290.py
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

PW0 = "change" + "me123"
PW1 = "Admin" + "Pass123!"
def staff_login(cl):
    cl.get("/login")
    with cl.session_transaction() as s:
        s["csrf_token"] = "tok"
    cl.post("/login", data={"username": "admin", "password": PW0,
                            "csrf_token": "tok"})
    cl.post("/change-password", data={
        "current_password": PW0, "new_password": PW1,
        "confirm_password": PW1, "csrf_token": csrf(cl)})

staff = appmod.app.test_client()
staff_login(staff)

NOW = "2026-10-20T00:00:00+00:00"
enc = appmod.encrypt_value
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

PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF"
def upload(cl, filename, payload, **fields):
    data = {"doc_type": "other",
            "file": (io.BytesIO(payload), filename),
            "csrf_token": csrf(cl)}
    data.update(fields)
    return cl.post("/portal/documents/upload", data=data,
                   content_type="multipart/form-data")

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
# 1. Registry integrity extended (packets + uncommon tier)
# ======================================================================
GUIDANCE = ("This checklist is guidance from our office, not legal "
            "advice about your situation.")
check("exactly 8 scenario packets",
      set(fl.PACKET_DEFS) == {
          "starting-divorce", "responding", "uncontested",
          "temporary-orders", "changing-order", "relocation",
          "protection", "parentage"})
check("every packet carries the verbatim guidance line",
      all(p["guidance"] == GUIDANCE for p in fl.PACKET_DEFS.values()))
bad = []
for p in fl.PACKET_DEFS.values():
    for st in p["steps"]:
        if st["type"] == "wizard":
            e = fl.LIBRARY_BY_SLUG.get(st["doc"])
            if not e or not e["implemented"] or not e["wizard"]:
                bad.append((p["slug"], st["doc"]))
        elif st["type"] == "upload":
            if st["doc_type"] not in appmod.PORTAL_DOC_TYPES:
                bad.append((p["slug"], st["doc_type"]))
        elif st["type"] == "info":
            if len(st.get("body", "")) < 40 or not st.get("title"):
                bad.append((p["slug"], "info"))
        else:
            bad.append((p["slug"], st["type"]))
check("every packet step references live material", not bad, str(bad))
impl = [e for e in fl.LIBRARY if e["implemented"]]
check("17 entries implemented (9 common + 8 uncommon)",
      len(impl) == 17
      and sum(1 for e in impl if e["tier"] == "common") == 9
      and sum(1 for e in impl if e["tier"] == "uncommon") == 8)
NEW_KEYS = {"response_marriage", "relocation_notice",
            "relocation_objection", "modify_parenting",
            "modify_support", "parentage_petition",
            "parentage_acknowledgment", "sealed_attachment",
            "fee_waiver"}
check("all 9 new uncommon wizard defs exist",
      NEW_KEYS <= set(fl.WIZARD_DEFS))
check("Modify numbers: 501 = support, 601 = parenting plan",
      fl.LIBRARY_BY_SLUG["modify-support-petition"]["form_number"]
      == "FL Modify 501"
      and fl.LIBRARY_BY_SLUG["modify-parenting-petition"]
      ["form_number"] == "FL Modify 601")
check("Acknowledgment of Parentage is DOH 422-159; 303 is the "
      "Residential Schedule",
      fl.LIBRARY_BY_SLUG["parentage-acknowledgment"]["form_number"]
      == "DOH 422-159"
      and fl.LIBRARY_BY_SLUG["parentage-residential-schedule"]
      ["form_number"] == "FL Parentage 303")
pet_fields = fl.wizard_fields(fl.wizard_def("petition_divorce"))
at = [f for f in pet_fields if f["name"] == "action_type"]
check("petition capture carries the separation variant flag",
      len(at) == 1 and any("Legal separation" in o
                           for o in at[0]["options"]))

# ======================================================================
# 2. Boundaries on the new routes (pre-assignment)
# ======================================================================
anon = appmod.app.test_client()
r = anon.get("/portal/packets/1")
check("unauthenticated packet page -> portal login",
      r.status_code == 302
      and "/portal/login" in r.headers.get("Location", ""))
r = staff.get("/portal/packets/1")
check("staff session hitting a portal packet -> portal login",
      r.status_code == 302
      and "/portal/login" in r.headers.get("Location", ""))
r = B.get("/portal/packets/1")
check("B opening a packet id that isn't B's -> 404",
      r.status_code == 404)
r = A.post("/clients/1/portal/packet",
           data={"packet_slug": "responding",
                 "csrf_token": csrf(A)})
check("portal session hitting the staff assign route -> staff login",
      r.status_code == 302
      and r.headers.get("Location", "").endswith("/login"))
r = anon.post("/library/packets/assign",
              data={"client_id": "1", "packet_slug": "responding"})
check("unauthenticated library assign -> staff login",
      r.status_code == 302
      and r.headers.get("Location", "").endswith("/login"))
r = A.get("/portal/packets/9999")
check("unknown assignment id -> 404", r.status_code == 404)

# ======================================================================
# 3. Assignment flow (staff, from the client record)
# ======================================================================
r = staff.post("/clients/1/portal/packet", data={
    "packet_slug": "responding", "case_id": "1",
    "csrf_token": csrf(staff)})
check("staff assign redirects back to the client", r.status_code == 302)
rows = dbq("SELECT * FROM portal_packet_assignments WHERE client_id = 1"
           " AND packet_slug = 'responding' AND unassigned_at IS NULL")
check("assignment row created, tied to A's case",
      len(rows) == 1 and rows[0]["case_id"] == 1)
AID = rows[0]["id"]
reqs = dbq("SELECT * FROM portal_doc_requests"
           " WHERE packet_assignment_id = ?", (AID,))
check("the packet's upload step created a tracked doc request",
      len(reqs) == 1 and reqs[0]["packet_step_index"] == 1
      and reqs[0]["status"] == "open"
      and reqs[0]["title"] == "The papers you were served")
REQ_ID = reqs[0]["id"]
check("assignment is audit-logged",
      len(dbq("SELECT * FROM audit_log WHERE action ="
              " 'portal_packet_assigned'")) >= 1)
check("assignment fires a portal activity entry",
      len(dbq("SELECT * FROM portal_activity WHERE client_id = 1"
              " AND kind = 'packet' AND summary LIKE"
              " '%assigned the%Responding%'")) == 1)
staff.post("/clients/1/portal/packet", data={
    "packet_slug": "responding", "csrf_token": csrf(staff)})
check("duplicate active assignment is refused",
      len(dbq("SELECT * FROM portal_packet_assignments"
              " WHERE client_id = 1 AND packet_slug = 'responding'"
              " AND unassigned_at IS NULL")) == 1)

r = A.get("/portal/")
check("A's portal home shows the packet ABOVE the forms, 0 of 5",
      b"Responding to papers you were served" in r.data
      and b"0 of 5 steps done" in r.data
      and b"How service works" in r.data)
r = B.get("/portal/")
check("B's portal home shows NONE of A's packet",
      b"Responding to papers" not in r.data)
r = A.get(f"/portal/packets/{AID}")
check("packet page renders steps + the verbatim guidance line",
      r.status_code == 200
      and GUIDANCE.encode() in r.data
      and b"How service works" in r.data
      and b"The papers you were served" in r.data)
check("sequential first step LOCKS the steps behind it",
      b"Complete the step above first" in r.data
      and b"/portal/library/response-marriage" not in r.data)
r = B.get(f"/portal/packets/{AID}")
check("B opening A's packet page -> 404", r.status_code == 404)
r = B.post(f"/portal/packets/{AID}/ack",
           data={"step": "0", "csrf_token": csrf(B)})
check("B acknowledging a step on A's packet -> 404",
      r.status_code == 404)
r = A.post(f"/portal/packets/{AID}/ack",
           data={"step": "2", "csrf_token": csrf(A)})
check("acking a non-info step -> 400", r.status_code == 400)

# ======================================================================
# 4. Step state accuracy (ack -> upload accept -> wizard submit)
# ======================================================================
A.post(f"/portal/packets/{AID}/ack",
       data={"step": "0", "csrf_token": csrf(A)})
check("info ack is recorded",
      len(dbq("SELECT * FROM portal_packet_acks"
              " WHERE assignment_id = ? AND step_index = 0",
              (AID,))) == 1)
r = A.get(f"/portal/packets/{AID}")
check("ack advances progress to 1 of 5 and unlocks step 2",
      b"1 of 5 steps done" in r.data
      and b"Complete the step above first" not in r.data)

upload(A, "served.pdf", PDF, request_id=str(REQ_ID))
r = A.get(f"/portal/packets/{AID}")
check("an upload merely SENT does not complete its step",
      b"waiting for the office to review" in r.data
      and b"1 of 5 steps done" in r.data)
up = dbq("SELECT * FROM portal_uploads WHERE client_id = 1"
         " AND request_id = ?", (REQ_ID,))[0]
staff.post(f"/portal-review/uploads/{up['id']}/accept", data={
    "case_id": "1", "category": "evidence", "csrf_token": csrf(staff)})
check("staff accept fulfills the packet request",
      dbq("SELECT status FROM portal_doc_requests WHERE id = ?",
          (REQ_ID,))[0]["status"] == "fulfilled")
r = A.get(f"/portal/packets/{AID}")
check("accept advances the upload step (2 of 5)",
      b"2 of 5 steps done" in r.data)

wiz_post(A, "response-marriage", 0, {
    "case_id": "1", "cf_spouse_name": "keep", "spouse_name": "",
    "overall_stance": "Agree with some parts and disagree with others",
    "agree_divorce": "Yes"}, "next")
wiz_post(A, "response-marriage", 1, {
    "children_name": ["Kid Anderson"], "children_dob": ["2018-05-01"],
    "children_stance": "Partly agree",
    "children_details": "The proposed schedule ignores school nights. "
                        "I want weeknights with me during term."}, "next")
wiz_post(A, "response-marriage", 2, {
    "property_stance": "Partly agree",
    "property_details": "The petition leaves out the truck loan."},
    "next")
wiz_post(A, "response-marriage", 3, {
    "support_stance": "Disagree",
    "maintenance_stance": "Doesn't mention it",
    "money_details": "His income figure is a year out of date."}, "next")
wiz_post(A, "response-marriage", 4, {
    "counter_asks": ["Approve a different parenting plan (mine)",
                     "Recalculate child support"],
    "counter_details": "School-night schedule with me, support on "
                       "current incomes."}, "next")
wiz_post(A, "response-marriage", 5, {}, "submit")
rsub = dbq("SELECT * FROM portal_form_submissions WHERE client_id = 1"
           " AND form_key = 'response_marriage'")[0]
check("response wizard submits with a frozen snapshot",
      rsub["status"] == "submitted" and rsub["snapshot_json"])
r = A.get(f"/portal/packets/{AID}")
check("wizard submit advances its packet step (3 of 5)",
      b"3 of 5 steps done" in r.data)
r = staff.get(f"/portal-review/forms/{rsub['id']}")
check("staff review shows the response answers",
      r.status_code == 200 and b"school nights" in r.data)
staff.post(f"/portal-review/forms/{rsub['id']}/import",
           data={"csrf_token": csrf(staff)})
staff.post(f"/portal-review/forms/{rsub['id']}/generate-document",
           data={"csrf_token": csrf(staff)})
docs = dbq("SELECT * FROM documents WHERE case_id = 1 AND"
           " original_name = 'Response_Client_Data.pdf'")
check("response generates its DRAFT data sheet", len(docs) == 1)
if docs:
    check("response data sheet is labeled FL Divorce 211",
          b"FLDivorce211" in pdf_text_norm(docs[0]))
r = staff.get("/clients/1")
check("staff client page shows live packet progress (3/5 steps)",
      b"3/5 steps" in r.data
      and b"Responding to papers you were served" in r.data)

# ======================================================================
# 5. Fee waiver — vault financials as confirm cards (A)
# ======================================================================
r = A.get("/portal/library/fee-waiver-statement?step=0")
check("fee waiver step 1 asks household + benefits",
      b"household" in r.data and b"public benefits" in r.data)
r = A.get("/portal/library/fee-waiver-statement?step=1")
check("fee waiver pulls vault financials as confirm cards",
      b"cf_client_gross_income" in r.data and b"4,000" in r.data
      and b"cf_client_net_income" in r.data and b"3,100" in r.data)
wiz_post(A, "fee-waiver-statement", 0, {
    "household_size": "4",
    "cf_benefits_receiving": "change", "benefits_receiving": "Yes",
    "benefits_details": "SNAP food benefits, about $280 a month."},
    "next")
wiz_post(A, "fee-waiver-statement", 1, {
    "cf_client_employer": "keep", "client_employer": "",
    "cf_client_gross_income": "keep", "client_gross_income": "",
    "cf_client_net_income": "keep", "client_net_income": "",
    "cf_monthly_expenses": "change", "monthly_expenses": "2,900"},
    "next")
wiz_post(A, "fee-waiver-statement", 2, {
    "cf_assets_notes": "change",
    "assets_notes": "2016 sedan; checking account about $300.",
    "cf_debts_notes": "change",
    "debts_notes": "Credit card about $2,000.",
    "hardship": "Hours were cut in September."}, "next")
wiz_post(A, "fee-waiver-statement", 3, {}, "submit")
fw = dbq("SELECT * FROM portal_form_submissions WHERE client_id = 1"
         " AND form_key = 'fee_waiver'")[0]
check("fee waiver submits", fw["status"] == "submitted")
staff.post(f"/portal-review/forms/{fw['id']}/import",
           data={"csrf_token": csrf(staff)})
staff.post(f"/portal-review/forms/{fw['id']}/generate-document",
           data={"csrf_token": csrf(staff)})
docs = dbq("SELECT * FROM documents WHERE case_id = 1 AND"
           " original_name = 'Fee_Waiver_Client_Data.pdf'")
check("fee waiver generates its data sheet", len(docs) == 1)
if docs:
    txt = pdf_text_norm(docs[0])
    check("fee waiver sheet cites GR 34.0300 + 'the court decides'",
          b"GR340300" in txt and b"courtdecides" in txt)

# ======================================================================
# 6. Every other new wizard: draft -> submit -> freeze -> review ->
#    generate (A, case 1)
# ======================================================================
LOOP = [
    ("relocate-notice", "relocation_notice",
     {0: {"move_date": "2027-02-01",
          "new_address": "Sequim, WA — address to follow"}},
     "Relocation_Notice_Client_Data.pdf", b"FLRelocate701"),
    ("relocate-objection", "relocation_objection",
     {0: {"notice_date": "2026-10-02"}},
     "Relocation_Objection_Client_Data.pdf", b"FLRelocate721"),
    ("modify-parenting-petition", "modify_parenting",
     {1: {"change_story": "His work moved to nights in August; the "
          "weeknight schedule no longer works."}},
     "Modify_Parenting_Client_Data.pdf", b"FLModify601"),
    ("modify-support-petition", "modify_support",
     {0: {"change_story": "I lost hours in September; daycare went "
          "up $200 a month."}},
     "Modify_Support_Client_Data.pdf", b"FLModify501"),
    ("parentage-petition", "parentage_petition", {},
     "Parentage_Petition_Client_Data.pdf", b"FLParentage301"),
    ("parentage-acknowledgment", "parentage_acknowledgment", {},
     "Acknowledgment_of_Parentage_Data.pdf", b"DOH422159"),
    ("cif-attachment", "sealed_attachment",
     {0: {"protected_details": "My new address in Sequim — it "
          "appears on my declaration."}},
     "Sealed_Attachment_Client_Data.pdf", b"FLAllFamily002"),
]
for slug, key, posts, fname, expect in LOOP:
    wdef = fl.wizard_def(key)
    wiz_post(A, slug, 0, dict(posts.get(0, {}), case_id="1"),
             "save_exit")
    draft = dbq("SELECT * FROM portal_form_submissions"
                " WHERE client_id = 1 AND form_key = ?"
                " AND status = 'draft'", (key,))
    check(f"{slug}: draft saved server-side", len(draft) == 1)
    r = A.get(f"/portal/library/{slug}?step=0")
    check(f"{slug}: draft resumes", r.status_code == 200)
    n = len(wdef["steps"])
    for i in range(n):
        wiz_post(A, slug, i, dict(posts.get(i, {}), case_id="1"),
                 "next")
    wiz_post(A, slug, n, {}, "submit")
    sub = dbq("SELECT * FROM portal_form_submissions"
              " WHERE client_id = 1 AND form_key = ?"
              " AND status = 'submitted'", (key,))
    check(f"{slug}: submits with a frozen snapshot",
          len(sub) == 1 and bool(sub[0]["snapshot_json"]))
    frozen = sub[0]["snapshot_json"]
    wiz_post(A, slug, 0, {"case_id": "1"}, "save_exit")
    check(f"{slug}: snapshot stays frozen after a new draft",
          dbq("SELECT snapshot_json FROM portal_form_submissions"
              " WHERE id = ?", (sub[0]["id"],))[0]["snapshot_json"]
          == frozen)
    r = staff.get(f"/portal-review/forms/{sub[0]['id']}")
    check(f"{slug}: staff review page renders",
          r.status_code == 200 and wdef["title"].split(" — ")[0]
          .encode()[:12] in r.data)
    staff.post(f"/portal-review/forms/{sub[0]['id']}/import",
               data={"csrf_token": csrf(staff)})
    staff.post(f"/portal-review/forms/{sub[0]['id']}/generate-document",
               data={"csrf_token": csrf(staff)})
    docs = dbq("SELECT * FROM documents WHERE case_id = 1"
               " AND original_name = ?", (fname,))
    check(f"{slug}: data sheet generated ({fname})", len(docs) == 1)
    if docs:
        check(f"{slug}: data sheet cites {expect.decode()}",
              expect in pdf_text_norm(docs[0]))

# ======================================================================
# 7. Petition variant — legal separation rides the Divorce series
# ======================================================================
wiz_post(A, "petition-divorce", 0, {
    "action_type": "Legal separation",
    "cf_marriage_date": "keep", "marriage_date": "",
    "cf_marriage_place": "keep", "marriage_place": "",
    "separation_date": "2026-03-01",
    "living_situation": "We live apart"}, "next")
wiz_post(A, "petition-divorce", 1, {
    "children_name": ["Kid Anderson"],
    "children_dob": ["2018-05-01"]}, "next")
wiz_post(A, "petition-divorce", 2, {
    "property_request": "The house to me, the truck to him.",
    "debts_overview": "One card, about $2,000."}, "next")
wiz_post(A, "petition-divorce", 3, {
    "maintenance_request": "None", "name_change": "",
    "other_relief": ""}, "next")
wiz_post(A, "petition-divorce", 4, {}, "submit")
pet = dbq("SELECT * FROM portal_form_submissions WHERE client_id = 1"
          " AND form_key = 'petition_divorce'")[0]
check("separation-variant petition submits",
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
    check("DRAFT petition names the TYPE OF ACTION: Legal separation",
          b"TYPEOFACTION" in pdf_text_norm(pd[0])
          and b"Legalseparation" in pdf_text_norm(pd[0]))
if pdc:
    check("data sheet carries the variant too",
          b"Legalseparation" in pdf_text_norm(pdc[0]))

# ======================================================================
# 8. Library-view assign, unassign, and packet completion (B)
# ======================================================================
r = staff.post("/library/packets/assign", data={
    "client_id": "2", "packet_slug": "starting-divorce",
    "case_id": "1", "csrf_token": csrf(staff)})
bassign = dbq("SELECT * FROM portal_packet_assignments"
              " WHERE client_id = 2 AND packet_slug ="
              " 'starting-divorce' AND unassigned_at IS NULL")
check("library-view assign works; a case from another client falls "
      "back to client-level",
      len(bassign) == 1 and bassign[0]["case_id"] is None)
r = B.get("/portal/")
check("B's home shows B's own packet (0 of 9)",
      b"Starting a divorce" in r.data and b"0 of 9 steps done" in r.data)
r = A.get("/portal/")
check("A's home does NOT show B's packet",
      b"Starting a divorce" not in r.data)
r = staff.get("/library")
check("staff library shows the packets section + live assignments",
      b"Guided checklists" in r.data
      and b"Responding to papers you were served" in r.data
      and b"Anderson" in r.data)

staff.post("/clients/1/portal/packet", data={
    "packet_slug": "temporary-orders", "csrf_token": csrf(staff)})
tassign = dbq("SELECT * FROM portal_packet_assignments"
              " WHERE client_id = 1 AND packet_slug ="
              " 'temporary-orders' AND unassigned_at IS NULL")[0]
open_reqs = dbq("SELECT * FROM portal_doc_requests"
                " WHERE packet_assignment_id = ? AND status = 'open'",
                (tassign["id"],))
check("temporary-orders packet created its 2 upload requests",
      len(open_reqs) == 2)
staff.post(f"/clients/1/portal/packet/{tassign['id']}/unassign",
           data={"csrf_token": csrf(staff)})
check("unassign retires the assignment",
      dbq("SELECT unassigned_at FROM portal_packet_assignments"
          " WHERE id = ?", (tassign["id"],))[0]["unassigned_at"])
check("unassign cancels the packet's open requests",
      dbq("SELECT COUNT(*) AS n FROM portal_doc_requests"
          " WHERE packet_assignment_id = ? AND status = 'cancelled'",
          (tassign["id"],))[0]["n"] == 2)
r = A.get("/portal/")
check("unassigned packet disappears from A's home",
      b"Temporary orders while we wait" not in r.data)
r = A.get(f"/portal/packets/{tassign['id']}")
check("unassigned packet page -> 404", r.status_code == 404)
check("unassign is audit-logged",
      len(dbq("SELECT * FROM audit_log WHERE action ="
              " 'portal_packet_unassigned'")) >= 1)

staff.post("/clients/2/portal/packet", data={
    "packet_slug": "changing-order", "case_id": "2",
    "csrf_token": csrf(staff)})
cassign = dbq("SELECT * FROM portal_packet_assignments"
              " WHERE client_id = 2 AND packet_slug ="
              " 'changing-order' AND unassigned_at IS NULL")[0]
r = A.get(f"/portal/packets/{cassign['id']}")
check("A opening B's packet -> 404", r.status_code == 404)
for i in range(4):
    wiz_post(B, "financial-declaration", i,
             {"client_gross_income": "2,500",
              "client_net_income": "1,900"} if i == 0 else {},
             "next")
wiz_post(B, "financial-declaration", 4, {}, "submit")
for i in range(5):
    wiz_post(B, "declaration", i, {}, "next")
wiz_post(B, "declaration", 5, {
    "attest_name": "Bob Baker", "attest_agree": "yes"}, "submit")
check("B submitted both counted wizards, neither optional one",
      dbq("SELECT COUNT(*) AS n FROM portal_form_submissions"
          " WHERE client_id = 2 AND status = 'submitted'")[0]["n"] == 2
      and dbq("SELECT COUNT(*) AS n FROM portal_form_submissions"
              " WHERE client_id = 2 AND form_key LIKE 'modify%'")
      [0]["n"] == 0)
r = B.get(f"/portal/packets/{cassign['id']}")
check("B's packet page shows completion",
      b"All done" in r.data and b"2 of 2 steps done" in r.data)
check("completion stamps completed_at",
      dbq("SELECT completed_at FROM portal_packet_assignments"
          " WHERE id = ?", (cassign["id"],))[0]["completed_at"])
check("completion posts the activity entry",
      len(dbq("SELECT * FROM portal_activity WHERE client_id = 2"
              " AND kind = 'packet' AND summary LIKE"
              " '%Completed the%Changing an existing order%'")) == 1)
r = staff.get("/dashboard")
check("dashboard activity widget shows the completion",
      b"Completed the" in r.data
      and b"Changing an existing order" in r.data)
r = B.get("/portal/")
check("B's home card shows the completed packet",
      b"All done" in r.data)

print()
print("FAILURES:", len(FAILURES))
for f in FAILURES:
    print("  FAILED:", f)
sys.exit(1 if FAILURES else 0)
'''


def main():
    scratch = tempfile.mkdtemp(prefix="lawfirm-v290-")
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
