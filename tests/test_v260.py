#!/usr/bin/env python3
"""
Boundary-hammer tests for v2.6.0 — the client portal.

The portal is a second door into the same house, so the tests are
mostly about the walls:

  * Two portal clients (A and B), each with a case, documents, forms,
    messages and requests. As A: every B URL is a 403/404, every B ID
    is inert, and A's lists contain zero B items.
  * Realm separation: a portal session NEVER satisfies staff routes
    (redirect to staff login, never 200); a staff session does not
    satisfy portal routes either.
  * Invite lifecycle: single-use, expiring, hashed; revoked access
    refuses login; 5 bad passwords lock the account.
  * Upload pipeline: content sniffing (an .exe renamed .pdf is
    rejected), the 25 MB cap (designed 413), quarantine (invisible in
    the case file until staff accept), accept -> real versioned
    document + request fulfilled, reject -> client sees the note.
  * Forms: drafts are invisible to staff; submit freezes a snapshot;
    import writes real client/case records (DOBs encrypted).
  * Messages: unread counts both directions; attachments ride the
    same quarantine queue.
  * Audit: portal login/upload/submit/message/accept all leave rows.

Run:  python3 tests/test_v260.py
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
import io, json, re, sqlite3, sys
sys.path.insert(0, ".")
import app as appmod
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
# Clients A and B (+ D for the lockout test), one case each.
for fn, ln, em in (("Alice", "Anderson", "alice@example.com"),
                   ("Bob", "Baker", "bob@example.com"),
                   ("Dan", "Doyle", "dan@example.com")):
    dbx("INSERT INTO clients (first_name,last_name,email,phone,"
        "created_at,updated_at) VALUES (?,?,?,?,?,?)",
        (fn, ln, em, "360-555-0100", NOW, NOW))
dbx("INSERT INTO cases (client_id,title,case_number,case_type,status,"
    "created_at,updated_at) VALUES (1,'Anderson v. Anderson','26-2-00101',"
    "'dissolution','open',?,?)", (NOW, NOW))
dbx("INSERT INTO cases (client_id,title,case_number,case_type,status,"
    "created_at,updated_at) VALUES (2,'Baker v. Baker','26-2-00202',"
    "'dissolution','open',?,?)", (NOW, NOW))
# Bob is the opposing party on Alice's case; both have portal access —
# the client page must warn staff about exactly this.
dbx("INSERT INTO opposing_parties (case_id,first_name,last_name,created_at)"
    " VALUES (1,'Bob','Baker',?)", (NOW,))

def invite_token_for(cl, client_id):
    cl.post(f"/clients/{client_id}/portal/invite",
            data={"csrf_token": csrf(cl)})
    r = cl.get(f"/clients/{client_id}")
    m = re.search(rb"/portal/accept-invite/([A-Za-z0-9_\-]+)", r.data)
    return m.group(1).decode() if m else None

tok_a = invite_token_for(staff, 1)
tok_b = invite_token_for(staff, 2)
tok_d = invite_token_for(staff, 3)
check("invite links are issued from the client page",
      bool(tok_a and tok_b and tok_d))
row = dbq("SELECT * FROM portal_invites WHERE client_id = 1")[0]
check("only the invite HASH is stored",
      len(row["token_hash"]) == 64 and tok_a not in row["token_hash"])

def accept_invite(token, password):
    cl = appmod.app.test_client()
    r = cl.get(f"/portal/accept-invite/{token}")
    ok_page = r.status_code == 200
    r = cl.post(f"/portal/accept-invite/{token}", data={
        "password": password, "confirm_password": password,
        "csrf_token": csrf(cl)})
    return cl, ok_page, r

# Weak passwords are refused and create nothing.
clw, _, rw = accept_invite(tok_d, "short")
check("password under 10 chars is refused",
      rw.status_code == 200
      and dbq("SELECT * FROM portal_users WHERE client_id = 3") == [])

A, ok_a, ra = accept_invite(tok_a, "AlicePass123")
B, ok_b, rb = accept_invite(tok_b, "BobPass12345")
D, ok_d, rd = accept_invite(tok_d, "DanPass12345")
check("both clients can set a password via the invite",
      ok_a and ok_b and ra.status_code == 302 and rb.status_code == 302)
check("portal_users rows are bound 1:1 to client records",
      len(dbq("SELECT * FROM portal_users")) == 3)

# Single use: the same link is dead afterwards.
rx = appmod.app.test_client().get(f"/portal/accept-invite/{tok_a}")
check("invite token is single-use",
      b"doesn't work anymore" in rx.data)

# Expiry: a fresh invite whose clock has run out is dead too.
tok_d2 = invite_token_for(staff, 3)
dbx("UPDATE portal_invites SET expires_at = '2020-01-01T00:00:00+00:00'"
    " WHERE used_at IS NULL")
rx = appmod.app.test_client().get(f"/portal/accept-invite/{tok_d2}")
check("expired invite is refused", b"doesn't work anymore" in rx.data)

def portal_login(cl, email, password):
    cl.get("/portal/login")
    return cl.post("/portal/login", data={
        "email": email, "password": password, "csrf_token": csrf(cl)})

r = portal_login(A, "alice@example.com", "wrong-password")
check("wrong portal password gets the generic error, no session",
      r.status_code == 200 and b"That email and password combination" in r.data)
r = portal_login(A, "alice@example.com", "AlicePass123")
check("portal login succeeds", r.status_code == 302
      and r.headers.get("Location", "").endswith("/portal/"))
portal_login(B, "bob@example.com", "BobPass12345")

# --- Realm separation -------------------------------------------------
for path in ("/dashboard", "/clients", "/users", "/cases"):
    r = A.get(path)
    loc = r.headers.get("Location", "")
    check(f"portal session hitting staff {path} -> staff login",
          r.status_code == 302 and loc.endswith("/login")
          and "/portal/" not in loc)
r = staff.get("/portal/")
check("staff session hitting portal home -> portal login",
      r.status_code == 302
      and r.headers.get("Location", "").endswith("/portal/login"))
anon = appmod.app.test_client()
for path in ("/portal/", "/portal/documents", "/portal/forms",
             "/portal/messages", "/portal-review", "/portal-messages"):
    r = anon.get(path)
    check(f"unauthenticated {path} -> a login page",
          r.status_code == 302 and "/login" in r.headers.get("Location", ""))

# --- Home scoping ------------------------------------------------------
r = A.get("/portal/")
check("A's home shows A's case only",
      b"26-2-00101" in r.data and b"26-2-00202" not in r.data)

# --- Document requests -------------------------------------------------
staff.post("/clients/1/portal/request", data={
    "title": "2024 tax return", "note": "All pages please",
    "case_id": "1", "csrf_token": csrf(staff)})
staff.post("/clients/2/portal/request", data={
    "title": "Bob pay stubs", "note": "", "case_id": "2",
    "csrf_token": csrf(staff)})
req_a = dbq("SELECT * FROM portal_doc_requests WHERE client_id = 1")[0]
req_b = dbq("SELECT * FROM portal_doc_requests WHERE client_id = 2")[0]
r = A.get("/portal/documents")
check("A sees A's request, never B's",
      b"2024 tax return" in r.data and b"Bob pay stubs" not in r.data)
r = staff.get("/clients/1")
check("client page warns when the opposing party has portal access",
      b"also has portal access" in r.data)

# --- Uploads + content sniffing ---------------------------------------
PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
EXE = b"MZ\x90\x00" + b"\x00" * 64

def upload(cl, filename, payload, **fields):
    data = {"doc_type": "pay_stubs",
            "file": (io.BytesIO(payload), filename),
            "csrf_token": csrf(cl)}
    data.update(fields)
    return cl.post("/portal/documents/upload", data=data,
                   content_type="multipart/form-data")

r = upload(A, "tax.pdf", EXE, request_id=str(req_a["id"]))
r2 = A.get("/portal/documents")
check("an .exe renamed .pdf is rejected by content sniffing",
      b"Please send a PDF" in r2.data
      and dbq("SELECT * FROM portal_uploads WHERE client_id = 1") == [])

big = b"%PDF-" + b"0" * (26 * 1024 * 1024)
r = upload(A, "big.pdf", big)
check("oversize upload gets the designed 413", r.status_code == 413
      and dbq("SELECT * FROM portal_uploads WHERE client_id = 1") == [])

r = upload(A, "stubs.pdf", PDF, request_id=str(req_a["id"]))
ups = dbq("SELECT * FROM portal_uploads WHERE client_id = 1")
check("PDF upload lands in quarantine, linked to the request",
      len(ups) == 1 and ups[0]["status"] == "pending"
      and ups[0]["request_id"] == req_a["id"]
      and ups[0]["case_id"] == 1 and ups[0]["detected_type"] == "pdf")
up_a = ups[0]

# Cross-wiring attempts are inert.
upload(A, "sneaky.pdf", PDF, request_id=str(req_b["id"]))
upload(A, "sneaky2.pdf", PDF, case_id="2")
rows = dbq("SELECT * FROM portal_uploads WHERE client_id = 1"
           " AND original_name LIKE 'sneaky%'")
check("A cannot link an upload to B's request or B's case",
      len(rows) == 2 and all(x["request_id"] is None
                             and x["case_id"] != 2 for x in rows))
dbx("DELETE FROM portal_uploads WHERE original_name LIKE 'sneaky%'")

# Quarantine: staff case file stays clean until acceptance.
r = staff.get("/cases/1/documents")
check("quarantined upload is invisible in the case documents",
      b"stubs.pdf" not in r.data
      and dbq("SELECT * FROM documents") == [])
r = A.get("/portal/documents")
check("...but the client sees it as waiting for review",
      b"stubs.pdf" in r.data and b"waiting for review" in r.data)

# Cross-client download: B gets nothing, A gets the file.
r = B.get(f"/portal/documents/{up_a['id']}/download")
check("B downloading A's upload -> 404", r.status_code == 404)
r = A.get(f"/portal/documents/{up_a['id']}/download")
check("A can download A's own upload", r.status_code == 200)

# Review queue + acceptance into the real document store.
r = staff.get("/portal-review")
check("staff review queue lists the pending upload",
      r.status_code == 200 and b"stubs.pdf" in r.data)
r = staff.post(f"/portal-review/uploads/{up_a['id']}/accept", data={
    "case_id": "1", "category": "evidence", "csrf_token": csrf(staff)})
docs = dbq("SELECT * FROM documents")
check("accept creates a real document, version 1",
      len(docs) == 1 and docs[0]["version"] == 1
      and docs[0]["case_id"] == 1
      and docs[0]["uploaded_by"] == "portal:Alice Anderson")
check("accepting the linked upload fulfills the request",
      dbq("SELECT status FROM portal_doc_requests WHERE id = ?",
          (req_a["id"],))[0]["status"] == "fulfilled")
r = staff.get("/cases/1/documents")
check("accepted document now appears in the case file",
      b"stubs.pdf" in r.data)
r = A.get("/portal/documents")
check("client sees the upload marked filed",
      b"stubs.pdf" in r.data and b"filed" in r.data)

# Reject path: the client sees the staff note.
upload(A, "blurry.png", PNG)
up2 = dbq("SELECT * FROM portal_uploads WHERE original_name = 'blurry.png'")[0]
staff.post(f"/portal-review/uploads/{up2['id']}/reject", data={
    "staff_note": "Too blurry — please retake in daylight",
    "csrf_token": csrf(staff)})
r = A.get("/portal/documents")
check("rejected upload shows the staff note to the client",
      b"Too blurry" in r.data and b"needs attention" in r.data)

# --- Quick-fill forms ---------------------------------------------------
def form_post(cl, key, step, fields, action):
    data = {"step": str(step), "action": action, "csrf_token": csrf(cl)}
    data.update(fields)
    return cl.post(f"/portal/forms/{key}", data=data)

# Draft: step 0 saved, then finish later. Staff must NOT see it.
form_post(A, "client_intake", 0, {
    "email": "alice.new@example.com", "phone": "360-555-0199",
    "address": "12 Harbor Way", "date_of_birth": "1988-04-02"},
    "save_exit")
draft = dbq("SELECT * FROM portal_form_submissions WHERE client_id = 1"
            " AND form_key = 'client_intake'")[0]
check("intake draft is saved server-side", draft["status"] == "draft")
r = staff.get("/portal-review")
check("draft is invisible in the staff review queue",
      b"Client Intake Form" not in r.data)
r = staff.post(f"/portal-review/forms/{draft['id']}/import",
               data={"csrf_token": csrf(staff)})
check("a draft cannot be imported",
      dbq("SELECT status FROM portal_form_submissions WHERE id = ?",
          (draft["id"],))[0]["status"] == "draft")

# Finish + submit.
form_post(A, "client_intake", 1, {
    "spouse_name": "Andrew Anderson", "spouse_dob": "1986-09-14"}, "next")
form_post(A, "client_intake", 2, {
    "child1_name": "Kid Anderson", "child1_dob": "2018-05-01",
    "child2_name": "", "child2_dob": "", "child3_name": "",
    "child3_dob": "", "children_notes": ""}, "next")
r = form_post(A, "client_intake", 3, {
    "employer_name": "Harbor Mill", "monthly_income": "3,100"}, "submit")
sub = dbq("SELECT * FROM portal_form_submissions WHERE client_id = 1"
          " AND form_key = 'client_intake'")[0]
check("submit freezes an immutable snapshot",
      sub["status"] == "submitted" and sub["snapshot_json"]
      and "alice.new@example.com" in sub["snapshot_json"])
r = staff.get("/portal-review")
check("submitted form appears in the review queue",
      b"Client Intake Form" in r.data)
r = staff.get(f"/portal-review/forms/{sub['id']}")
check("review screen shows submitted vs current side by side",
      b"alice.new@example.com" in r.data and b"alice@example.com" in r.data)

r = staff.post(f"/portal-review/forms/{sub['id']}/import",
               data={"csrf_token": csrf(staff)})
cl_row = dbq("SELECT * FROM clients WHERE id = 1")[0]
kids = dbq("SELECT * FROM children WHERE client_id = 1")
check("import writes the real client record",
      cl_row["email"] == "alice.new@example.com"
      and cl_row["phone"] == "360-555-0199"
      and cl_row["spouse_name"] == "Andrew Anderson")
check("import adds the child with an ENCRYPTED date of birth",
      len(kids) == 1 and kids[0]["name"] == "Kid Anderson"
      and kids[0]["date_of_birth"] != "2018-05-01"
      and appmod.decrypt_value(kids[0]["date_of_birth"]) == "2018-05-01")
check("client's own DOB is encrypted at rest after import",
      cl_row["date_of_birth"] != "1988-04-02"
      and appmod.decrypt_value(cl_row["date_of_birth"]) == "1988-04-02")
check("submission is marked imported",
      dbq("SELECT status FROM portal_form_submissions WHERE id = ?",
          (sub["id"],))[0]["status"] == "imported")

# Financial worksheet -> case financials -> support worksheet PDF.
form_post(A, "financial_worksheet", 0, {
    "case_id": "1", "client_gross_income": "4,000",
    "client_net_income": "3,100", "other_income_notes": ""}, "next")
form_post(A, "financial_worksheet", 1, {
    "other_parent_net_income": "2,900"}, "next")
form_post(A, "financial_worksheet", 2, {
    "daycare": "450", "health_insurance": "210"}, "next")
form_post(A, "financial_worksheet", 3, {
    "monthly_expenses": "2,700", "assets_notes": "House, truck",
    "debts_notes": "Card $2,000"}, "submit")
fin_sub = dbq("SELECT * FROM portal_form_submissions WHERE client_id = 1"
              " AND form_key = 'financial_worksheet'")[0]
check("financial worksheet submitted against A's case",
      fin_sub["status"] == "submitted" and fin_sub["case_id"] == 1)
staff.post(f"/portal-review/forms/{fin_sub['id']}/import",
           data={"csrf_token": csrf(staff)})
fin = {x["key"]: x["value"] for x in dbq(
    "SELECT * FROM case_financials WHERE case_id = 1")}
check("import stores the case financials",
      fin.get("client_net_income") == "3,100"
      and fin.get("daycare") == "450"
      and fin.get("other_parent_net_income") == "2,900")
r = staff.post(f"/portal-review/forms/{fin_sub['id']}/generate-support",
               data={"csrf_token": csrf(staff)}, follow_redirects=True)
sup = dbq("SELECT * FROM documents WHERE case_id = 1"
          " AND original_name LIKE '%support%'")
check("one-click support worksheet lands in the case documents",
      r.status_code == 200 and len(sup) == 1)

# --- Messaging ----------------------------------------------------------
r = A.post("/portal/messages", data={
    "body": "Hi, did my stubs arrive?", "csrf_token": csrf(A)},
    content_type="multipart/form-data")
unread = dbq("SELECT COUNT(*) AS c FROM portal_messages"
             " WHERE sender_type = 'client'"
             " AND read_by_staff_at IS NULL")[0]["c"]
check("client message starts unread for staff", unread == 1)
r = staff.get("/portal-messages")
check("staff inbox shows the thread with its unread count",
      r.status_code == 200 and b"Alice" in r.data and b"bdg" in r.data)
r = staff.get("/portal-messages/1")
check("opening the thread shows the message", b"did my stubs arrive" in r.data)
unread = dbq("SELECT COUNT(*) AS c FROM portal_messages"
             " WHERE sender_type = 'client'"
             " AND read_by_staff_at IS NULL")[0]["c"]
check("opening the thread marks it read for staff", unread == 0)
r = staff.get("/cases/1")
check("case page links Portal Messages with the thread",
      b"Portal Messages" in r.data)

staff.post("/portal-messages/1", data={
    "body": "Yes — all filed, thank you.", "csrf_token": csrf(staff)})
unread_c = dbq("SELECT COUNT(*) AS c FROM portal_messages"
               " WHERE client_id = 1 AND sender_type = 'staff'"
               " AND read_by_client_at IS NULL")[0]["c"]
check("staff reply starts unread for the client", unread_c == 1)
r = A.get("/portal/messages")
check("client sees the reply and the office-hours disclaimer",
      b"all filed, thank you" in r.data
      and b"For emergencies call 911" in r.data)
unread_c = dbq("SELECT COUNT(*) AS c FROM portal_messages"
               " WHERE client_id = 1 AND sender_type = 'staff'"
               " AND read_by_client_at IS NULL")[0]["c"]
check("reading the thread marks staff messages read", unread_c == 0)

# A message attachment rides the same quarantine queue.
A.post("/portal/messages", data={
    "body": "Here is the letter", "csrf_token": csrf(A),
    "file": (io.BytesIO(PNG), "letter.png")},
    content_type="multipart/form-data")
att = dbq("SELECT * FROM portal_uploads WHERE original_name = 'letter.png'")
check("message attachment is a pending portal upload",
      len(att) == 1 and att[0]["status"] == "pending"
      and att[0]["message_id"] is not None)
r = staff.get("/portal-messages/1")
check("staff thread flags the pending attachment",
      b"pending review" in r.data)
r = staff.get("/portal-review")
check("attachment also waits in the review queue", b"letter.png" in r.data)

# B's lists stay clean throughout.
r = B.get("/portal/documents")
check("B's document list contains zero A items",
      b"stubs.pdf" not in r.data and b"letter.png" not in r.data)
r = B.get("/portal/messages")
check("B's thread contains zero A messages",
      b"did my stubs arrive" not in r.data)
r = B.get("/portal/forms")
check("B's forms page renders only B's own state", r.status_code == 200)
r = B.get(f"/portal-review/forms/{sub['id']}")
check("portal session hitting a staff form-review URL -> staff login",
      r.status_code == 302
      and r.headers.get("Location", "").endswith("/login")
      and "/portal/" not in r.headers.get("Location", ""))

# --- Revocation + lockout ------------------------------------------------
staff.post("/clients/2/portal/revoke", data={"csrf_token": csrf(staff)})
B2 = appmod.app.test_client()
r = portal_login(B2, "bob@example.com", "BobPass12345")
check("revoked access refuses login",
      r.status_code == 200 and b"That email and password combination" in r.data)

for i in range(5):
    portal_login(D, "dan@example.com", "nope-nope-nope")
r = portal_login(D, "dan@example.com", "DanPass12345")
check("5 bad passwords lock the account (correct one refused too)",
      r.status_code == 200 and b"That email and password combination" in r.data)

# --- Permission wall ------------------------------------------------------
dbx("INSERT INTO users (username,password_hash,full_name,role,permissions,"
    "is_active,must_change_password,created_at) VALUES ('limited',?,'Lim',"
    "'staff',?,1,0,?)",
    (generate_password_hash("LimitedPass123"),
     json.dumps({"view_clients": False, "view_cases": True}), NOW))
lim = appmod.app.test_client()
lim.get("/login")
with lim.session_transaction() as s:
    s["csrf_token"] = "tok"
lim.post("/login", data={"username": "limited",
                         "password": "LimitedPass123",
                         "csrf_token": "tok"})
r = lim.get("/portal-review")
check("staff without view_clients cannot open the review queue",
      r.status_code == 403)
r = lim.get("/portal-messages")
check("staff without view_clients cannot open the inbox",
      r.status_code == 403)

# --- Audit trail ----------------------------------------------------------
actions = {x["action"] for x in dbq(
    "SELECT DISTINCT action FROM audit_log WHERE username LIKE 'portal:%'"
    " OR action LIKE 'portal%'")}
for want in ("portal_login", "portal_upload", "portal_form_submitted",
             "portal_message_sent", "portal_upload_accepted",
             "portal_invite_created", "portal_form_imported",
             "portal_access_revoked"):
    check(f"audit log has {want}", want in actions)
prow = dbq("SELECT * FROM audit_log WHERE action = 'portal_login'")[0]
check("portal audit rows carry the portal identity, not a staff user",
      prow["username"].startswith("portal:")
      and prow["user_id"] is None)

print()
print("FAILURES:", len(FAILURES))
for f in FAILURES:
    print("  FAILED:", f)
sys.exit(1 if FAILURES else 0)
'''


def main():
    scratch = tempfile.mkdtemp(prefix="lawfirm-v260-")
    try:
        for name in ("app.py", "crypto.py", "deadlines.py",
                     "integrations.py", "invoice_pdf.py", "payroll.py",
                     "paystub_pdf.py", "template_defs.py", "template_pdf.py"):
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
