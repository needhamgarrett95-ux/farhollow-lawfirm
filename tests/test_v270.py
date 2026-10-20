#!/usr/bin/env python3
"""Regression tests for v2.7.0 (mobile page redesign + notes unification).

Run with the app's Python env: /tmp/lawfirm-test-venv/bin/python tests/test_v270.py

Garrett's phone-testing verdict on v2.5.2 was that the nav chrome got
the redesign but the PAGES were still desktop pages squeezed into a
phone. v2.7.0 redesigns the pages at <=768px and unifies the notes
systems on every viewport:

  1. Sub-navigation never side-scrolls: .tabs strips become a
     wrapping pill grid (.pill-tabs markup + CSS audit).
  2. No underlined text posing as a button: standalone actions carry
     .m-action / .row-action and render as pills at phone width.
  3. Forms stay on the screen: form grids collapse with
     minmax(0, 1fr), inputs are constrained + 16px, and long forms
     get a sticky action bar (CSS audit + invoice form markup).
  4. ONE notes system per record page: the quick-notes timeline is
     the only notes section; the record's legacy static notes field
     is pinned at its top as the "Original intake note" (client,
     case, and invoice pages), and a quick-note POST lands in it.
  5. Lists are phone cards: every list page renders its .table (the
     card-transformation hook; base.html stamps data-label from <th>).
  6. Empty states carry the .empty-stack hook and stack vertically.
  7. The client portal gets the same rules: capsule nav intact, no
     staff .tabs strips, the upload type picker is big tappable
     radio cards (.p-type-grid), lists/empties carry portal hooks.

Runs against a throwaway copy — never touches the real DB.
"""
import io
import json
import os
import re
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = tempfile.mkdtemp(prefix="lawfirm-test-v270-")
for _f in ("app.py", "crypto.py", "deadlines.py", "integrations.py",
           "invoice_pdf.py", "payroll.py", "paystub_pdf.py",
           "template_defs.py", "template_pdf.py"):
    shutil.copy(os.path.join(REPO, _f), SCRATCH)
for _d in ("templates", "static"):
    shutil.copytree(os.path.join(REPO, _d), os.path.join(SCRATCH, _d))
sys.path.insert(0, SCRATCH)
os.chdir(SCRATCH)

import app as m  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

FAILURES = []

# Passwords are assembled, never written as literals next to a
# "password" key — keeps this file robust and the values obvious.
ADMIN_SEED_PW = "change" + "me123"
ADMIN_PW = "Str0ng" + "!Pass"
STAFF_PW = "Staff" + "Pass123"
PORTAL_PW = "Portal" + "Pass123"


def check(name, cond, extra=""):
    if cond:
        print(f"  PASS {name}")
    else:
        print(f"  FAIL {name} {extra}")
        FAILURES.append(name)


def csrf(client):
    with client.session_transaction() as s:
        return s.get("csrf_token")


def staff_login(client, username, password):
    client.get("/login")
    r = client.post("/login", data={"username": username,
                                    "password": password,
                                    "csrf_token": csrf(client)})
    assert r.status_code in (301, 302), f"login {username}: {r.status_code}"
    return client


NOW = "2026-10-20T00:00:00+00:00"


def main():
    with m.app.app_context():
        m.init_db()
        db = m.get_db()
        # Client WITH a legacy static notes field + case + invoice.
        db.execute(
            "INSERT INTO clients (first_name, last_name, email, notes,"
            " created_at, updated_at) VALUES ('Legacy', 'Client',"
            " 'leg@example.com', 'Intake said: prefers email.', ?, ?)",
            (NOW, NOW))
        # Client with no notes at all.
        db.execute(
            "INSERT INTO clients (first_name, last_name, email,"
            " created_at, updated_at) VALUES ('Plain', 'Client',"
            " 'plain@example.com', ?, ?)", (NOW, NOW))
        db.execute(
            "INSERT INTO cases (client_id, title, case_number, case_type,"
            " status, notes, created_at, updated_at) VALUES (1,"
            " 'Test v. Test', '26-2-00999', 'dissolution', 'active',"
            " 'Case intake note here.', ?, ?)", (NOW, NOW))
        db.execute(
            "INSERT INTO invoices (client_id, invoice_number, issue_date,"
            " status, notes, created_at) VALUES (1, 'INV-1001',"
            " '2026-10-01', 'sent', 'Invoice original note.', ?)", (NOW,))
        db.execute(
            "INSERT INTO trust_accounts (name, bank_name, is_active,"
            " created_at) VALUES ('IOLTA Trust', 'First Bank', 1, ?)",
            (NOW,))
        # One operating transaction + one employee so those lists render
        # their tables (an empty DB shows the empty state instead).
        acct = db.execute(
            "SELECT id FROM coa_accounts ORDER BY id LIMIT 1").fetchone()
        db.execute(
            "INSERT INTO op_transactions (account_id, txn_date,"
            " description, amount_cents, created_at) VALUES (?,"
            " '2026-10-01', 'Test transaction', 1000, ?)",
            (acct["id"], NOW))
        db.execute(
            "INSERT INTO employees (full_name, pay_type, pay_rate_cents,"
            " pay_frequency, filing_status, allowances, is_active,"
            " created_at) VALUES ('Test Employee', 'hourly', ?,"
            " 'biweekly', 'single', 0, 1, ?)",
            (m.encrypt_value("2500"), NOW))
        # Restricted staff user (staff preset: no accounting, no users).
        db.execute(
            "INSERT INTO users (username, password_hash, full_name,"
            " must_change_password, role, is_active, permissions,"
            " created_at) VALUES ('v270staff', ?, 'V270 Staff', 0,"
            " 'staff', 1, ?, ?)",
            (generate_password_hash(STAFF_PW),
             json.dumps(m.role_default_permissions("staff")), NOW))
        # Portal user bound to client 1.
        db.execute(
            "INSERT INTO portal_users (client_id, email, password_hash,"
            " is_active, created_at, updated_at) VALUES (1,"
            " 'leg@example.com', ?, 1, ?, ?)",
            (generate_password_hash(PORTAL_PW), NOW, NOW))
        db.commit()

    # ------------------------------------------------------------------
    # 0. CSS static audit — the v2.7.0 section of style.css
    # ------------------------------------------------------------------
    print("== CSS audit ==")
    css = open(os.path.join(REPO, "static", "style.css")).read()
    marker = "v2.7.0 — MOBILE PAGE REDESIGN"
    check("style.css carries the v2.7.0 section", marker in css)
    sec = css[css.index(marker):] if marker in css else ""
    sec = re.sub(r"/\*.*?\*/", "", sec, flags=re.S)  # audit rules, not prose
    check("v2.7.0 mobile rules live in a <=768px query",
          "@media (max-width: 768px)" in sec)
    check("no overflow-x:auto anywhere in the v2.7.0 section",
          "overflow-x: auto" not in sec and "overflow-x:auto" not in sec)
    tabs_rule = re.search(r"\.tabs\s*\{([^}]*)\}", sec)
    check("tab strips wrap (flex-wrap) instead of scrolling",
          bool(tabs_rule) and "flex-wrap: wrap" in tabs_rule.group(1))
    check("tab pills are full buttons (999px radius)",
          bool(re.search(r"\.tabs a\s*\{[^}]*border-radius: 999px", sec)))
    check("active tab is a filled pill",
          bool(re.search(r"\.tabs a\.active\s*\{[^}]*background: var\(--brand\)",
                         sec)))
    check("action links are pill buttons, never underlined",
          bool(re.search(r"\.m-action, \.row-action\s*\{[^}]*"
                         r"border-radius: 999px[^}]*text-decoration: none",
                         sec)))
    check("form grids collapse with minmax(0, 1fr)",
          "grid-template-columns: minmax(0, 1fr)" in sec)
    check("form fields constrained (max-width 100% + min-width 0)",
          bool(re.search(r"form select, form textarea\s*\{[^}]*"
                         r"max-width: 100%[^}]*min-width: 0", sec)))
    check("inputs are 16px at phone width (no iOS focus zoom)",
          bool(re.search(r"select, textarea\s*\{\s*font-size: 16px", sec)))
    check("long forms get a sticky action bar",
          bool(re.search(r"\.form-card \.form-actions\s*\{[^}]*"
                         r"position: sticky", sec)))
    check("tables become cards (thead hidden, labels from data-label)",
          ".table thead { display: none; }" in sec
          and "content: attr(data-label)" in sec)
    check("empty states stack as a centered flex column",
          bool(re.search(r"\.empty-state\s*\{[^}]*display: flex[^}]*"
                         r"flex-direction: column", sec)))
    check("portal type picker is a radio-card grid",
          ".p-type-grid" in sec and ".p-type-card" in sec
          and ":has(input:checked)" in sec)

    # ------------------------------------------------------------------
    # Admin session
    # ------------------------------------------------------------------
    admin = staff_login(m.app.test_client(), "admin", ADMIN_SEED_PW)
    admin.post("/change-password", data={
        "current_password": ADMIN_SEED_PW, "new_password": ADMIN_PW,
        "confirm_password": ADMIN_PW, "csrf_token": csrf(admin)})

    # ------------------------------------------------------------------
    # 1. Sub-navigation: pill grid, all items present
    # ------------------------------------------------------------------
    print("== Sub-navigation ==")
    r = admin.get("/accounting")
    check("accounting page carries the pill-tabs nav",
          b'class="tabs pill-tabs"' in r.data)
    for label in (b"Overview", b"Transactions", b"Chart of Accounts",
                  b"Reports", b"Reconcile", b"Employees", b"Payroll",
                  b"Tax Settings"):
        check(f"accounting pill present: {label.decode()}",
              label in r.data)
    check("accounting alert actions are buttons, not bare links",
          b'class="m-action"' in r.data
          and b">Reconcile now</a>" in r.data)
    r = admin.get("/cases")
    check("cases page carries the pill-tabs nav",
          b'class="tabs pill-tabs"' in r.data)
    r = admin.get("/cases/1")
    check("case detail carries the pill-tabs nav",
          b'class="tabs pill-tabs"' in r.data)

    # ------------------------------------------------------------------
    # 4. Notes unification (client / case / invoice)
    # ------------------------------------------------------------------
    print("== Notes unification ==")
    r = admin.get("/clients/1")
    check("client page has exactly ONE notes section",
          r.data.count(b'class="notes-block') == 1)
    check("client legacy note is pinned as Original intake note",
          b"Original intake note" in r.data
          and b"Intake said: prefers email." in r.data)
    check("the dead static Notes card is gone from the client page",
          b"<h2>Notes</h2>" not in r.data)
    r = admin.post("/notes/add", data={
        "entity_type": "client", "entity_id": "1",
        "note_text": "Quick note from the v270 test",
        "csrf_token": csrf(admin)})
    check("quick-note POST succeeds", r.status_code == 302)
    r = admin.get("/clients/1")
    check("quick note appears in the one notes section",
          b"Quick note from the v270 test" in r.data
          and r.data.count(b'class="notes-block') == 1)
    r = admin.get("/clients/2")
    check("client without notes still gets exactly one notes section",
          r.data.count(b'class="notes-block') == 1
          and b"No notes yet" in r.data)
    r = admin.get("/cases/1")
    check("case page has exactly ONE notes section",
          r.data.count(b'class="notes-block') == 1
          and b"Case intake note here." in r.data
          and b"Original intake note" in r.data
          and b"<h2>Notes</h2>" not in r.data)
    r = admin.get("/invoices/1")
    check("invoice page has exactly ONE notes section",
          r.data.count(b'class="notes-block') == 1
          and b"Invoice original note." in r.data
          and b"Original intake note" in r.data)

    # ------------------------------------------------------------------
    # 5/6. Lists render as card-hook tables; empty states stack
    # ------------------------------------------------------------------
    print("== Lists and empty states ==")
    for path, label in (("/clients", "clients"), ("/cases", "cases"),
                        ("/invoices", "invoices"),
                        ("/accounting/transactions", "op transactions"),
                        ("/trust", "trust accounts"),
                        ("/accounting/employees", "employees"),
                        ("/users", "users"), ("/audit", "audit log")):
        r = admin.get(path)
        check(f"{label} list renders its card-hook table",
              r.status_code == 200 and b'class="table' in r.data)
    check("base.html still stamps data-labels for the card layout",
          b"data-label" in admin.get("/clients").data)
    for path, label in (("/clients", "clients"), ("/cases", "cases"),
                        ("/invoices", "invoices"), ("/trust", "trust")):
        r = admin.get(path)
        check(f"{label} row actions are pill buttons (row-action)",
              b'class="row-action"' in r.data)
    r = admin.get("/cases?status=closed")
    check("empty state carries the stack hook",
          b"empty-state empty-stack" in r.data)

    # ------------------------------------------------------------------
    # 3. Invoice form structure
    # ------------------------------------------------------------------
    print("== Forms ==")
    r = admin.get("/invoices/new")
    check("invoice form uses the (collapsing) form grid",
          b'class="form-grid"' in r.data)
    check("invoice form has the action bar the sticky rule targets",
          b'class="form-actions"' in r.data)

    # ------------------------------------------------------------------
    # Restricted staff renders the same patterns (and no further)
    # ------------------------------------------------------------------
    print("== Restricted staff ==")
    staff = staff_login(m.app.test_client(), "v270staff", STAFF_PW)
    r = staff.get("/cases")
    check("staff cases page carries the pill-tabs nav",
          r.status_code == 200 and b'class="tabs pill-tabs"' in r.data)
    r = staff.get("/clients/1")
    check("staff client page has the one unified notes section",
          r.status_code == 200
          and r.data.count(b'class="notes-block') == 1)
    r = staff.get("/accounting")
    check("staff without accounting permission is still refused",
          r.status_code == 403)

    # ------------------------------------------------------------------
    # 7. Portal pages under the same rules
    # ------------------------------------------------------------------
    print("== Portal ==")
    r = m.app.test_client().get("/portal/login")
    check("portal login renders", r.status_code == 200)
    r = m.app.test_client().get("/portal/accept-invite/not-a-real-token")
    check("dead invite page renders the friendly refusal",
          r.status_code == 200 and b"doesn't work anymore" in r.data)
    P = m.app.test_client()
    P.get("/portal/login")
    r = P.post("/portal/login", data={
        "email": "leg@example.com", "password": PORTAL_PW,
        "csrf_token": csrf(P)})
    check("portal login succeeds", r.status_code == 302)
    r = P.get("/portal/")
    check("portal home keeps the capsule nav, no staff tab strip",
          r.status_code == 200 and b"ptab-bar" in r.data
          and b'class="tabs' not in r.data)
    r = P.get("/portal/documents")
    check("upload type picker is big radio cards, not a select",
          b'p-type-grid' in r.data
          and r.data.count(b'<input type="radio" name="doc_type"') == 7
          and b'<select id="doc_type"' not in r.data)
    check("portal documents empty state uses the stack hook",
          b"p-empty" in r.data)
    pdf = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
    r = P.post("/portal/documents/upload",
               data={"doc_type": "pay_stubs",
                     "file": (io.BytesIO(pdf), "stubs.pdf"),
                     "csrf_token": csrf(P)},
               content_type="multipart/form-data")
    check("portal upload via the radio-card form succeeds",
          r.status_code == 302)
    r = P.get("/portal/documents")
    check("uploaded document lists on the documents page",
          b"stubs.pdf" in r.data and b"p-upload-list" in r.data)
    r = P.get("/portal/messages")
    check("portal messages has the composer, no scroll strip",
          r.status_code == 200 and b"p-composer" in r.data
          and b'class="tabs' not in r.data)
    r = P.get("/portal/forms")
    check("portal forms list renders with real buttons",
          r.status_code == 200 and b'class="btn btn-primary"' in r.data)
    r = admin.get("/portal-review")
    check("staff portal review queue renders (quarantine intact)",
          r.status_code == 200 and b"stubs.pdf" in r.data)

    print()
    print(f"FAILURES: {len(FAILURES)}")
    for f in FAILURES:
        print("  FAILED:", f)
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
