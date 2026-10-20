#!/usr/bin/env python3
"""v2.11.0 checks — full-system audit + cleanup.

Covers, against a scratch copy of the app:
  * BUG 1 (reported): the Clallam court-schedule watcher.
    - The parser reads a real-style county PDF (FlateDecode streams)
      AND ReportLab-style PDFs (ASCII85+Flate): "Updated" date +
      judge assignment lines; signature ignores everything but the
      assignment lines.
    - Simulated watcher runs: first parse -> baseline, no alert;
      genuine change -> ONE alert whose message carries real dates
      (never 'unknown' -> 'unknown'); the baseline is NOT overwritten
      by a change; confirm on the review screen -> baseline updated,
      alert cleared, audit-logged; dismiss -> alert cleared, baseline
      kept, same change stays muted, NEXT change re-alerts;
      parse failure -> NO alert, baseline untouched, audit-logged.
    - The dashboard card's "Review" is a real link to a working
      review screen (was a static <div> — the alert could never be
      cleared from the UI); a legacy pre-v2.11 stuck alert (no stored
      texts) can be cleared from that screen via a live fetch.
    - Permission gates: no calculate_deadlines -> 403 on review;
      calculate without push_deadlines -> can review, cannot confirm.
  * BUG 2 (reported): date/time inputs overflow on phones.
    - style.css carries the global phone-band rule for the whole
      date/time family (width:100%, min-width:0, max-width:100%,
      border-box, appearance reset) and the any-viewport guard;
      grid floors use the min() pattern; no old fixed minmax remains.
    - The major forms (event, invoice, client, case, employee, time
      entry, trust transaction) render inside the constrained card
      containers with their date/time inputs present.
  * Crypto robustness: decrypt_value/encrypt_value/looks_encrypted
    survive non-string legacy values; an employee row whose pay rate
    was stored as a raw integer (the crawl's 500 repro) no longer
    500s the accounting pages.
  * Portal -> staff pipeline spot chain (Garrett's P0): declaration
    wizard draft -> submit -> staff queue -> review -> import ->
    generate -> document exists in the case file, non-empty, PDF
    text carries the DRAFT banner; upload -> quarantine -> accept
    into case documents; reject with a note the client can read;
    client message marks read_by_staff_at once staff opens it.
  * Money spot-audit: trust overdraft + reversal pins; invoice from
    a time entry -> paid -> linked operating transaction; retention
    blocks a plain delete; the admin override delete keeps the
    income record, unlinked; payroll gross/net/WA-Cares math.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap

TEST_CODE = r'''
import io
import json
import os
import re
import sqlite3
import sys
import zlib
import base64
from datetime import datetime, timezone

sys.path.insert(0, os.getcwd())
import app as appmod
import crypto
import deadlines
import form_library as fl
import payroll as payrollmod

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

# ---------------------------------------------------------------- seed
dbx("INSERT INTO clients (first_name,last_name,email,phone,address,"
    "date_of_birth,spouse_name,spouse_dob,ssn,created_at,updated_at)"
    " VALUES ('Alice','Anderson','alice@example.com','360-555-0100',"
    "'12 Harbor Way',?,?,?,?,?,?)",
    (enc("1988-04-02"), "Andrew Anderson", enc("1986-09-14"),
     enc("123-45-6789"), NOW, NOW))
dbx("INSERT INTO cases (client_id,title,case_number,case_type,status,"
    "created_at,updated_at) VALUES (1,'Anderson v. Anderson',"
    "'26-2-00101','dissolution','open',?,?)", (NOW, NOW))
dbx("INSERT INTO trust_accounts (name,bank_name,account_number,"
    "is_active,created_at) VALUES ('IOLTA Trust','First Bank',?,1,?)",
    (enc("987654321"), NOW))
dbx("INSERT INTO children (client_id,name,date_of_birth) VALUES (1,"
    "'Kid Anderson',?)", (enc("2018-05-01"),))

admin = appmod.app.test_client()
admin.get("/login")
admin.post("/login", data={"username": "admin", "password": PW0,
                           "csrf_token": csrf(admin)})
admin.post("/change-password", data={
    "current_password": PW0, "new_password": "Admin" + "Pass123!",
    "confirm_password": "Admin" + "Pass123!",
    "csrf_token": csrf(admin)})
ADMIN_PW = "Admin" + "Pass123!"

def make_user(username, role):
    perms = json.dumps(appmod.role_default_permissions(role))
    from werkzeug.security import generate_password_hash
    dbx("INSERT INTO users (username,password_hash,full_name,"
        "role,permissions,is_active,must_change_password,created_at)"
        " VALUES (?,?,?,?,?,1,0,?)",
        (username, generate_password_hash("Password" + "123!"),
         username.title(), role, perms, NOW))
    cl = appmod.app.test_client()
    cl.get("/login")
    cl.post("/login", data={"username": username,
                            "password": "Password" + "123!",
                            "csrf_token": csrf(cl)})
    return cl

acct = make_user("acct", "accountant")
staffy = make_user("staffy", "staff")

# portal client A
admin.post("/clients/1/portal/invite", data={"csrf_token": csrf(admin)})
r = admin.get("/clients/1")
tok = re.search(rb"/portal/accept-invite/([A-Za-z0-9_\-]+)", r.data).group(1).decode()
A = appmod.app.test_client()
A.get(f"/portal/accept-invite/{tok}")
A.post(f"/portal/accept-invite/{tok}", data={
    "password": "Alice" + "Pass123", "confirm_password": "Alice" + "Pass123",
    "csrf_token": csrf(A)})
A.get("/portal/login")
A.post("/portal/login", data={"email": "alice@example.com",
                              "password": "Alice" + "Pass123",
                              "csrf_token": csrf(A)})

# ------------------------------------------------- BUG 1a: the parser
def make_pdf(text_lines):
    """Build a minimal FlateDecode PDF whose content stream shows the
    given lines with (line) Tj operators, one per line move."""
    ops = []
    for i, ln in enumerate(text_lines):
        esc = ln.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        ops.append(f"BT /F1 12 Tf 0 -{0 if i == 0 else 14} Td ({esc}) Tj ET")
    content = "\n".join(ops).encode("latin-1")
    comp = zlib.compress(content)
    return (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/Parent 2 0 R/Contents 4 0 R>>endobj\n"
            b"4 0 obj<</Length " + str(len(comp)).encode() +
            b">>stream\n" + comp + b"\nendstream\nendobj\n%%EOF")

cal_v1 = ["Friday Superior Court Judges Calendar", "Updated 10/13/26",
          "10/16/26 JUDGE ELIZABETH STANLEY 9:00 CRIMINAL [CT2]",
          "10/23/26 JUDGE SIMON BARNHART 9:00 CIVIL [CT1]"]
cal_v2 = ["Friday Superior Court Judges Calendar", "Updated 10/20/26",
          "10/16/26 JUDGE BRENT BASDEN 9:00 CRIMINAL [CT2]",
          "10/23/26 JUDGE SIMON BARNHART 9:00 CIVIL [CT1]"]
text1 = deadlines.extract_pdf_text(make_pdf(cal_v1))
upd, lines = deadlines.parse_clallam_calendar_text(text1)
check("parser: Flate PDF yields the Updated date", upd == "10/13/26", upd)
check("parser: assignment lines extracted", len(lines) == 2
      and "STANLEY" in lines[0], lines)
upd2, lines2 = deadlines.parse_clallam_calendar_text(
    deadlines.extract_pdf_text(make_pdf(cal_v2)))
check("parser: changed judge line differs", lines2[0] != lines[0])
garbage = deadlines.parse_clallam_calendar_text(
    deadlines.extract_pdf_text(b"%PDF-1.4 junk"))
check("parser: unparseable document yields no assignments",
      garbage == ("", []), garbage)
# ReportLab-style ASCII85+Flate stream decodes too
import template_pdf
try:
    pdf_bytes = template_pdf.build_wizard_declaration({
        "declarant": "Alice Anderson",
        "paragraphs": ["I am the petitioner in this matter."]})
except Exception:
    pdf_bytes = None
if not pdf_bytes:
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 720, "DRAFT - sample")
    c.save()
    pdf_bytes = buf.getvalue()
rtext = deadlines.extract_pdf_text(pdf_bytes)
check("parser: ReportLab (ASCII85+Flate) text readable",
      "DRAFT" in rtext, rtext[:80])

# ------------------------------------------------- BUG 1b: the watcher
def meta(k):
    with appmod.app.app_context():
        return appmod._meta_get(k)

def run_check(fake):
    with appmod.app.app_context():
        appmod._fetch_clallam_schedule = fake
        return appmod.clallam_schedule_check()

def sig_of(lines_):
    import hashlib
    return hashlib.sha256("\n".join(lines_).encode()).hexdigest()

lines_v1 = ["10/16/26 JUDGE ELIZABETH STANLEY 9:00 CRIMINAL [CT2]",
            "10/23/26 JUDGE SIMON BARNHART 9:00 CIVIL [CT1]"]
lines_v2 = ["10/16/26 JUDGE BRENT BASDEN 9:00 CRIMINAL [CT2]",
            "10/23/26 JUDGE SIMON BARNHART 9:00 CIVIL [CT1]"]
lines_v3 = ["10/16/26 JUDGE SIMON BARNHART 9:00 CRIMINAL [CT2]",
            "10/23/26 JUDGE SIMON BARNHART 9:00 CIVIL [CT1]"]
V1 = {"updated": "10/13/26", "signature": sig_of(lines_v1),
      "text": "\n".join(lines_v1)}
V2 = {"updated": "10/20/26", "signature": sig_of(lines_v2),
      "text": "\n".join(lines_v2)}
V3 = {"updated": "10/27/26", "signature": sig_of(lines_v3),
      "text": "\n".join(lines_v3)}

st = run_check(lambda: dict(V1))
check("watcher: first parse establishes baseline, no alert",
      st == "baseline-established" and meta("clallam_cal_alert") != "1", st)
st = run_check(lambda: dict(V1))
check("watcher: identical re-check is no-change", st == "no-change", st)
st = run_check(lambda: dict(V2))
check("watcher: genuine change raises the alert",
      st == "changed-alert" and meta("clallam_cal_alert") == "1", st)
msg = meta("clallam_cal_alert_msg")
check("watcher: alert names the real dates, never unknown->unknown",
      "10/13/26" in msg and "10/20/26" in msg and "unknown" not in msg,
      msg)
check("watcher: a change does NOT overwrite the confirmed baseline",
      meta("clallam_cal_base_sig") == V1["signature"])
st = run_check(lambda: dict(V2))
check("watcher: repeat run keeps one stable alert",
      st == "changed-alert-active", st)

r = admin.get("/dashboard")
check("dashboard: the alert's Review is a working link now",
      b'href="/clallam/schedule/review"' in r.data)
r = admin.get("/clallam/schedule/review")
check("review screen renders baseline vs latest with a diff",
      r.status_code == 200 and b"STANLEY" in r.data
      and b"BASDEN" in r.data and b"Confirm these assignments" in r.data,
      r.status_code)
r = acct.get("/clallam/schedule/review")
check("review screen: no calculate_deadlines -> 403",
      r.status_code == 403, r.status_code)
r = staffy.post("/clallam/schedule/confirm",
                data={"csrf_token": csrf(staffy)})
check("confirm: calculate without push_deadlines -> 403",
      r.status_code == 403, r.status_code)
r = staffy.get("/clallam/schedule/review")
check("review screen: staff role (calculate) can view",
      r.status_code == 200, r.status_code)

r = admin.post("/clallam/schedule/confirm",
               data={"csrf_token": csrf(admin)})
check("confirm: clears the alert and updates the baseline",
      meta("clallam_cal_alert") != "1"
      and meta("clallam_cal_base_sig") == V2["signature"]
      and meta("clallam_cal_base_by") == "admin",
      (meta("clallam_cal_alert"), meta("clallam_cal_base_sig")))
n = dbq("SELECT COUNT(*) c FROM audit_log WHERE action="
        "'clallam_schedule_confirmed'")[0]["c"]
check("confirm: audit-logged with the confirmer", n == 1, n)
st = run_check(lambda: dict(V2))
check("watcher: post-confirm same calendar is no-change",
      st == "no-change", st)
st = run_check(lambda: dict(V3))
check("watcher: a second genuine change alerts again",
      st == "changed-alert", st)
r = admin.post("/clallam/schedule/dismiss",
               data={"csrf_token": csrf(admin)})
check("dismiss: clears alert, baseline stays",
      meta("clallam_cal_alert") != "1"
      and meta("clallam_cal_base_sig") == V2["signature"])
st = run_check(lambda: dict(V3))
check("dismiss: the SAME change does not re-alert",
      st == "changed-dismissed", st)
st = run_check(lambda: dict(V1))
check("dismiss: a FURTHER change re-alerts",
      st == "changed-alert", st)
admin.post("/clallam/schedule/dismiss", data={"csrf_token": csrf(admin)})

def parse_boom():
    raise appmod.ClallamParseError("no assignments parsed")
base_before = meta("clallam_cal_base_sig")
st = run_check(parse_boom)
check("parse failure: NO alert, baseline untouched, status recorded",
      st == "parse-failed" and meta("clallam_cal_alert") != "1"
      and meta("clallam_cal_base_sig") == base_before
      and meta("clallam_cal_last_status") == "parse-failed", st)
n = dbq("SELECT COUNT(*) c FROM audit_log WHERE action="
        "'clallam_schedule_parse_failed'")[0]["c"]
check("parse failure: written to the audit log", n >= 1, n)

# Legacy stuck alert from before v2.11 (no stored texts at all)
with appmod.app.app_context():
    db = appmod.get_db()
    for k in ("clallam_cal_latest_text", "clallam_cal_latest_sig",
              "clallam_cal_base_text", "clallam_cal_base_sig"):
        db.execute("DELETE FROM meta WHERE key=?", (k,))
    db.commit()
    appmod._meta_set("clallam_cal_alert", "1")
    appmod._meta_set(
        "clallam_cal_alert_msg",
        "The Clallam County Friday judge calendar may have changed "
        "(was 'unknown', now 'unknown').")
r = admin.get("/clallam/schedule/review")
check("legacy stuck alert: review screen still renders",
      r.status_code == 200, r.status_code)
with appmod.app.app_context():
    appmod._fetch_clallam_schedule = lambda: dict(V1)
r = admin.post("/clallam/schedule/confirm",
               data={"csrf_token": csrf(admin)})
check("legacy stuck alert: confirm fetches live and clears it",
      meta("clallam_cal_alert") != "1"
      and meta("clallam_cal_base_sig") == V1["signature"],
      meta("clallam_cal_base_sig"))

# ------------------------------------------------------- BUG 2: CSS
css = open(os.path.join("static", "style.css")).read()
m768 = [m.start() for m in re.finditer(r"@media \(max-width: 768px\)", css)]
check("css: phone-band blocks present", len(m768) >= 3, len(m768))
base_css = css[:m768[0]]
guard = re.search(
    r'input\[type="date"\], input\[type="time"\], '
    r'input\[type="datetime-local"\],\s*input\[type="month"\], '
    r'input\[type="week"\], input\[type="file"\] \{\s*min-width: 0; '
    r'max-width: 100%;', base_css)
check("css: any-viewport guard for intrinsically-sized inputs", bool(guard))
band = css[m768[0]:]
full = re.search(
    r'input\[type="date"\], input\[type="time"\], '
    r'input\[type="datetime-local"\],\s*input\[type="month"\], '
    r'input\[type="week"\] \{\s*width: 100%; min-width: 0; '
    r'max-width: 100%; box-sizing: border-box;\s*'
    r'-webkit-appearance: none; appearance: none;', band)
check("css: phone band forces the date/time family to the card width",
      bool(full))
check("css: grid floors use the min() pattern (no fixed-px overflow)",
      "minmax(min(280px, 100%)" in css
      and "minmax(min(320px, 100%)" in css
      and "minmax(min(250px, 100%)" in css
      and "minmax(280px, 1fr)" not in css
      and "minmax(320px, 1fr)" not in css
      and "minmax(250px, 1fr)" not in css)
check("css: compose-row children cannot force overflow",
      ".compose-row > * { min-width: 0; }" in css)

form_pages = [
    ("/events/new", "event form"),
    ("/invoices/new", "invoice form"),
    ("/clients/new", "client form"),
    ("/cases/new", "case form"),
    ("/accounting/employees/new", "employee form"),
    ("/cases/1/time", "time entry page"),
    ("/trust/transactions/new", "trust transaction form"),
]
for path, label in form_pages:
    r = admin.get(path)
    has_card = (b"form-card" in r.data or b"detail-card" in r.data)
    has_dt = (b'type="date"' in r.data or b'type="time"' in r.data
              or b'type="datetime-local"' in r.data)
    check(f"form renders constrained with date/time inputs: {label}",
          r.status_code == 200 and has_card and has_dt,
          (r.status_code, has_card, has_dt))

# ------------------------------------------------- crypto robustness
check("crypto: decrypt_value survives a raw int legacy value",
      crypto.decrypt_value(2500) == "2500")
check("crypto: decrypt_value survives None / garbage",
      crypto.decrypt_value(None) == ""
      and crypto.decrypt_value("not-a-token") == "not-a-token")
check("crypto: encrypt_value + looks_encrypted survive non-strings",
      crypto.decrypt_value(crypto.encrypt_value(2500)) == "2500"
      and crypto.looks_encrypted(2500) is False)
dbx("INSERT INTO employees (full_name,pay_type,pay_rate_cents,"
    "is_active,created_at) VALUES ('Legacy Larry','hourly',2500,1,?)",
    (NOW,))
r = acct.get("/accounting/employees")
check("accounting: legacy int pay rate no longer 500s employees page",
      r.status_code == 200, r.status_code)
r = acct.get("/accounting/payroll")
check("accounting: legacy int pay rate no longer 500s payroll page",
      r.status_code == 200, r.status_code)

# --------------------------------------- portal -> staff pipeline (P0)
def fill_for(name, ftype, options, entry):
    nm = name.lower()
    if name in ("agree", "attest_agree") or nm.endswith("_agree"):
        return options[0] if options else "yes"
    if name == "attest_name":
        return "Alice Anderson"
    if ftype == "hidden":
        return None
    if options:
        return options[0]
    if ftype == "date" or nm.endswith("_date") or nm.endswith("_dob"):
        return "2020-01-15"
    if ftype == "number":
        return "2"
    if ftype in ("email",):
        return "alice@example.com"
    if ftype in ("tel", "phone"):
        return "360-555-0100"
    if "amount" in nm or "income" in nm or "value" in nm or "price" in nm:
        return "1,000"
    if "name" in nm:
        return "Kid Anderson" if (entry and "child" in nm) else \
            "Andrew Anderson"
    if ftype == "textarea":
        return "Provided for the office during this review."
    return "Provided"

def parse_inputs(html):
    fields = []
    radio_groups = {}
    for tag in re.findall(r"<input[^>]*>", html):
        nm = re.search(r'name="([^"]+)"', tag)
        if not nm or nm.group(1) == "csrf_token":
            continue
        tp = re.search(r'type="([^"]+)"', tag)
        tp = tp.group(1) if tp else "text"
        vv = re.search(r'value="([^"]*)"', tag)
        vv = vv.group(1) if vv else ""
        if tp in ("radio", "checkbox"):
            radio_groups.setdefault(nm.group(1), []).append(vv)
            continue
        fields.append((nm.group(1), tp, vv))
    for m in re.finditer(r'<select[^>]*name="([^"]+)"[^>]*>(.*?)</select>',
                         html, re.S):
        opts = re.findall(r'value="([^"]*)"', m.group(2))
        fields.append((m.group(1), "select", opts))
    for m in re.finditer(r'<textarea[^>]*name="([^"]+)"', html):
        fields.append((m.group(1), "textarea", []))
    for name, opts in radio_groups.items():
        fields.append((name, "radio", opts))
    return fields

def wizard_submit(cl, slug):
    """Walk a portal wizard generically until its submission row is
    marked submitted (the exact walk the v2.11 audit drivers used).
    The wizard carries progress in the ?step= redirect, so follow it."""
    url = f"/portal/library/{slug}"
    for _ in range(40):
        sub = dbq("SELECT * FROM portal_form_submissions WHERE "
                  "form_key=? AND client_id=1 AND status='submitted'",
                  (slug,))
        if sub:
            return None
        r = cl.get(url)
        if r.status_code != 200:
            return f"GET step -> {r.status_code}"
        html = r.data.decode("utf-8", "ignore")
        data = {"csrf_token": csrf(cl)}
        for name, ftype, extra in parse_inputs(html):
            if ftype == "hidden":
                data[name] = extra
                continue
            v = fill_for(name, ftype,
                         extra if ftype in ("select", "radio") else [],
                         None)
            if v is not None:
                data[name] = v
        # The step buttons are <button name="action"> elements: "next"
        # through the data steps, "submit" on the review/attest step.
        data["action"] = "submit" if 'value="submit"' in html else "next"
        r = cl.post(url, data=data)
        if r.status_code not in (200, 302):
            return f"POST step -> {r.status_code}"
        loc = r.headers.get("Location")
        if loc:
            url = loc
    return "never submitted"

err = wizard_submit(A, "declaration")
sub = dbq("SELECT * FROM portal_form_submissions WHERE form_key="
          "'declaration' AND client_id=1 ORDER BY id DESC LIMIT 1")
check("portal pipeline: declaration submitted from the portal",
      err is None and bool(sub) and sub[0]["status"] == "submitted",
      (err, sub))
r = admin.get("/portal-review")
check("portal pipeline: submission waits in the staff review queue",
      r.status_code == 200 and b"Declaration" in r.data, r.status_code)
if sub:
    sid = sub[0]["id"]
    r = admin.get(f"/portal-review/forms/{sid}")
    check("portal pipeline: staff review screen renders",
          r.status_code == 200, r.status_code)
    admin.post(f"/portal-review/forms/{sid}/import",
               data={"csrf_token": csrf(admin)})
    sub2 = dbq("SELECT status FROM portal_form_submissions WHERE id=?",
               (sid,))[0]
    check("portal pipeline: staff import lands",
          sub2["status"] == "imported", sub2["status"])
    before = dbq("SELECT COUNT(*) c FROM documents WHERE case_id=1")[0]["c"]
    admin.post(f"/portal-review/forms/{sid}/generate-document",
               data={"csrf_token": csrf(admin)})
    docs = dbq("SELECT * FROM documents WHERE case_id=1 ORDER BY id DESC")
    check("portal pipeline: generated document filed in the case",
          len(docs) > before and bool(docs), (before, len(docs)))
    if docs:
        doc = docs[0]
        p = os.path.join(appmod._case_doc_dir(1), doc["stored_name"])
        ok = os.path.exists(p) and os.path.getsize(p) > 500
        text = deadlines.extract_pdf_text(open(p, "rb").read()) if ok else ""
        check("portal pipeline: document is a real PDF with DRAFT banner",
              ok and open(p, "rb").read(4) == b"%PDF" and "DRAFT" in text,
              (ok, text[:60]))

# upload: quarantine -> accept -> reject-with-note -> message read state
PDFB = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF"
r = A.post("/portal/documents/upload", data={
    "doc_type": "pay_stubs", "csrf_token": csrf(A),
    "file": (io.BytesIO(PDFB), "stubs.pdf")},
    content_type="multipart/form-data")
up = dbq("SELECT * FROM portal_uploads WHERE original_name='stubs.pdf'")
check("uploads: client upload lands in quarantine as pending",
      bool(up) and up[0]["status"] == "pending", up)
check("uploads: nothing reaches the case file before review",
      dbq("SELECT COUNT(*) c FROM documents WHERE case_id=1 AND "
          "uploaded_by LIKE 'portal:%'")[0]["c"] == 0)
if up:
    admin.post(f"/portal-review/uploads/{up[0]['id']}/accept",
               data={"csrf_token": csrf(admin), "case_id": "1"})
    up2 = dbq("SELECT * FROM portal_uploads WHERE id=?", (up[0]["id"],))[0]
    check("uploads: accept files it into the case documents",
          up2["status"] == "accepted" and bool(up2["document_id"]), up2)
r = A.post("/portal/documents/upload", data={
    "doc_type": "other", "csrf_token": csrf(A),
    "file": (io.BytesIO(PDFB), "blurry.pdf")},
    content_type="multipart/form-data")
up = dbq("SELECT * FROM portal_uploads WHERE original_name='blurry.pdf'")
if up:
    admin.post(f"/portal-review/uploads/{up[0]['id']}/reject",
               data={"csrf_token": csrf(admin),
                     "staff_note": "Too blurry - please resend."})
    r = A.get("/portal/documents")
    check("uploads: rejection note reaches the client",
          b"Too blurry" in r.data)
A.post("/portal/messages", data={"csrf_token": csrf(A),
                                 "body": "A question about Friday."})
r = admin.get("/portal-messages/1")
n = dbq("SELECT COUNT(*) c FROM portal_messages WHERE client_id=1 AND "
        "sender_type='client' AND read_by_staff_at IS NULL")[0]["c"]
check("messaging: staff opening the thread marks client msgs read",
      r.status_code == 200 and n == 0, (r.status_code, n))

# ------------------------------------------------------- money spots
def trust_post(data):
    data.setdefault("csrf_token", csrf(admin))
    return admin.post("/trust/transactions/new", data=data)

trust_post({"account_id": "1", "client_id": "1", "txn_type": "deposit",
            "amount": "500.00", "description": "Retainer"})
dep = dbq("SELECT * FROM trust_transactions ORDER BY id DESC LIMIT 1")[0]
trust_post({"account_id": "1", "client_id": "1",
            "txn_type": "disbursement", "amount": "600.00",
            "description": "Too much"})
n = dbq("SELECT COUNT(*) c FROM trust_transactions")[0]["c"]
check("trust: overdraft disbursement refused", n == 1, n)
trust_post({"account_id": "1", "client_id": "1",
            "txn_type": "disbursement", "amount": "200.00",
            "description": "Filing fee"})
disb = dbq("SELECT * FROM trust_transactions ORDER BY id DESC LIMIT 1")[0]
trust_post({"reverse_id": str(dep["id"]), "txn_type": "reversal_debit",
            "amount": "500.00", "description": "undo"})
check("trust: reversing the deposit now would overdraw ($300 left) "
      "-> refused",
      len(dbq("SELECT * FROM trust_transactions WHERE reverses_id=?",
              (dep["id"],))) == 0)
trust_post({"reverse_id": str(disb["id"]),
            "txn_type": "reversal_credit", "amount": "200.00",
            "description": "undo fee"})
revs = dbq("SELECT * FROM trust_transactions WHERE reverses_id=?",
           (disb["id"],))
check("trust: reversal posts pinned to the original",
      len(revs) == 1 and revs[0]["amount_cents"] == 20000
      and revs[0]["client_id"] == 1, revs)
trust_post({"reverse_id": str(disb["id"]),
            "txn_type": "reversal_credit", "amount": "200.00",
            "description": "again"})
check("trust: double reversal blocked",
      len(dbq("SELECT * FROM trust_transactions WHERE reverses_id=?",
              (disb["id"],))) == 1)
with appmod.app.app_context():
    bal = appmod.client_trust_balance(appmod.get_db(), 1, 1)
check("trust: balance consistent after the dance ($500)", bal == 50000,
      bal)

admin.post("/cases/1/time", data={
    "csrf_token": csrf(admin), "entry_date": "2026-10-19",
    "hours": "2.5", "description": "Draft motion", "rate": "300"})
te = dbq("SELECT * FROM time_entries WHERE case_id=1 ORDER BY id DESC "
         "LIMIT 1")
r = admin.post("/invoices/new", data={
    "csrf_token": csrf(admin), "client_id": "1", "case_id": "1",
    "issue_date": "2026-10-20", "due_date": "2026-11-19",
    "entry_ids": [str(te[0]["id"])] if te else []})
inv = dbq("SELECT * FROM invoices ORDER BY id DESC LIMIT 1")
items = dbq("SELECT * FROM invoice_items WHERE invoice_id=?",
            (inv[0]["id"],)) if inv else []
tot = round(sum(i["amount"] for i in items) * 100) if items else None
check("invoice: built from the time entry at $750", tot == 75000, tot)
if inv:
    inv = inv[0]
    admin.post(f"/invoices/{inv['id']}/status",
               data={"csrf_token": csrf(admin), "status": "paid"})
    ops = dbq("SELECT * FROM op_transactions WHERE invoice_id=?",
              (inv["id"],))
    check("invoice: payment creates the linked operating transaction",
          len(ops) == 1 and ops[0]["amount_cents"] == 75000, ops)
    admin.post(f"/invoices/{inv['id']}/delete",
               data={"csrf_token": csrf(admin)})
    check("invoice: plain delete blocked by 7-year retention",
          dbq("SELECT COUNT(*) c FROM invoices WHERE id=?",
              (inv["id"],))[0]["c"] == 1)
    admin.post(f"/invoices/{inv['id']}/delete", data={
        "csrf_token": csrf(admin), "retention_override": "1",
        "override_reason": "Test cleanup", "override_confirm": "DELETE"})
    ops2 = dbq("SELECT * FROM op_transactions WHERE id=?",
               (ops[0]["id"],)) if ops else []
    check("invoice: override delete keeps income record, unlinked",
          dbq("SELECT COUNT(*) c FROM invoices WHERE id=?",
              (inv["id"],))[0]["c"] == 0 and bool(ops2)
          and ops2[0]["invoice_id"] is None, ops2)

dbx("INSERT INTO employees (full_name,pay_type,pay_rate_cents,"
    "pay_frequency,filing_status,allowances,is_active,created_at)"
    " VALUES ('Pay Paul','hourly',?, 'biweekly','single',0,1,?)",
    (enc("2500"), NOW))
with appmod.app.app_context():
    db = appmod.get_db()
    row = db.execute("SELECT * FROM employees WHERE full_name="
                     "'Pay Paul'").fetchone()
    emp = appmod._employee_dict(row)
    chk = payrollmod.calculate_paycheck(db, emp, 80.0, 5.0)
check("payroll: gross = 80h + 5h OT at $25",
      abs(chk["gross"] - 2187.50) < 0.01, chk["gross"])
check("payroll: net = gross - total deductions",
      abs(chk["net"] - (chk["gross"] - chk["total_deductions"])) < 0.011,
      chk["net"])
check("payroll: WA Cares is 0.58% of gross",
      abs(chk["wacares"] - round(chk["gross"] * 0.0058, 2)) < 0.02,
      chk["wacares"])
check("payroll: SS 6.2% + Medicare 1.45%",
      abs(chk["ss"] - round(chk["gross"] * 0.062, 2)) < 0.02
      and abs(chk["medicare"] - round(chk["gross"] * 0.0145, 2)) < 0.02,
      (chk["ss"], chk["medicare"]))

print()
if FAILURES:
    print("FAILURES:", FAILURES)
    raise SystemExit(1)
print("ALL V211 CHECKS PASSED")
'''


def main():
    tmp = tempfile.mkdtemp(prefix="lawfirm-v211-")
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
        testfile = os.path.join(tmp, "run_v211_checks.py")
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
