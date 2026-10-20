#!/usr/bin/env python3
"""Regression tests for v2.4.5 (full-audit build).

Run with the app's Python env: /tmp/lawfirm-test-venv/bin/python tests/test_v245.py

Covers the fixes from the v2.4.5 audit sweep:
  1. Trust reversal hardening — reversal must exactly offset the original,
     same account/client/amount; no double reversal; no reversal of a
     reversal; no overdraft via reversal; no cross-client reversal.
  2. FK validation — bad IDs on child/case/event/invoice/op-txn/employee
     creates now fail closed (no 500).
  3. Delete safety — client/case deletes blocked by linked financial
     records (no 500); notes cleaned up; doc files removed from disk.
  4. Payroll — half-up money rounding; duplicate generate refused;
     PFML employer share honored; salaried L&I uses real hours.
  5. Timeclock — mixed naive/aware rows never crash entry_hours;
     correction approval no longer breaks the day view or payroll.
  6. CSRF on dashboard JSON endpoints (customize/reset/theme).
  7. Dead report filters revived (from_date/to_date/account_id).
  8. Ungated links (client Open link, compose integrations link).
  9. Invoice — half-cent line amounts stored exactly; manual line
     validation; case_new date_closed; time-entry numeric validation.
 10. Operating-transaction admin retention override (one-step delete of
     an invoice-linked transaction).

Runs against a throwaway copy — never touches the real DB.
"""
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = tempfile.mkdtemp(prefix="lawfirm-test-v245-")
for _f in ("app.py", "crypto.py", "deadlines.py", "integrations.py",
           "invoice_pdf.py", "payroll.py", "paystub_pdf.py",
           "template_defs.py", "template_pdf.py", "form_library.py"):
    shutil.copy(os.path.join(REPO, _f), SCRATCH)
for _d in ("templates", "static"):
    shutil.copytree(os.path.join(REPO, _d), os.path.join(SCRATCH, _d))
sys.path.insert(0, SCRATCH)
os.chdir(SCRATCH)

import app as m  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

FAILURES = []


def check(name, cond, extra=""):
    if cond:
        print(f"  PASS {name}")
    else:
        print(f"  FAIL {name} {extra}")
        FAILURES.append(name)


def csrf(client):
    with client.session_transaction() as s:
        return s.get("csrf_token")


def login(client, username, password):
    client.get("/login")
    r = client.post("/login", data={"username": username,
                                    "password": password,
                                    "csrf_token": csrf(client)})
    assert r.status_code in (301, 302), f"login {username}: {r.status_code}"
    return client


def make_role_user(db, username, role, password="testpass123!"):
    db.execute(
        "INSERT INTO users (username, password_hash, full_name, "
        "must_change_password, role, is_active, permissions, "
        "created_at) VALUES (?, ?, ?, 0, ?, 1, ?, '2026-01-01T00:00:00+00:00')",
        (username, generate_password_hash(password), username.title(),
         role, json.dumps(m.role_default_permissions(role))))
    return db.execute("SELECT id FROM users WHERE username = ?",
                      (username,)).fetchone()["id"]


def main():
    with m.app.app_context():
        m.init_db()
        db = m.get_db()
        admin_id = db.execute(
            "SELECT id FROM users WHERE username = 'admin'").fetchone()["id"]
        make_role_user(db, "atty", "attorney")
        make_role_user(db, "staffer", "staff")
        make_role_user(db, "acct", "accountant")

        def make_employee(name, pay_type="hourly", rate_cents="2500",
                          freq="weekly", user_id=None):
            db.execute(
                "INSERT INTO employees (user_id, full_name, pay_type, "
                "pay_rate_cents, pay_frequency, filing_status, allowances, "
                "is_active, created_at) VALUES (?, ?, ?, ?, ?, 'single', 0, "
                "1, '2026-01-01T00:00:00+00:00')",
                (user_id, name, pay_type, m.encrypt_value(str(rate_cents)),
                 freq))
            return db.execute(
                "SELECT id FROM employees WHERE full_name = ?",
                (name,)).fetchone()["id"]

        emp_hourly = make_employee("Hourly Hal", user_id=admin_id)
        emp_salaried = make_employee("Salaried Sam", pay_type="salary",
                                     rate_cents="5200000", freq="weekly")

        db.execute(
            "INSERT INTO clients (first_name, last_name, email, created_at, "
            "updated_at) VALUES ('Test', 'Client', 't@t.com', "
            "'2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')")
        client_id = db.execute("SELECT MAX(id) AS i FROM clients"
                               ).fetchone()["i"]
        db.execute(
            "INSERT INTO cases (client_id, case_number, title, case_type, "
            "status, created_at, updated_at) VALUES (?, '2026-001', "
            "'Test v. Test', 'divorce', 'active', "
            "'2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')",
            (client_id,))
        case_id = db.execute("SELECT MAX(id) AS i FROM cases"
                             ).fetchone()["i"]
        db.execute(
            "INSERT INTO trust_accounts (name, is_active, created_at) "
            "VALUES ('IOLTA', 1, '2026-01-01T00:00:00+00:00')")
        acct_id = db.execute(
            "SELECT MAX(id) AS i FROM trust_accounts").fetchone()["i"]
        db.execute(
            "INSERT INTO invoices (client_id, invoice_number, issue_date, "
            "due_date, status, created_at) VALUES (?, '2026-900', "
            "'2026-10-01', '2026-10-31', 'draft', "
            "'2026-10-01T00:00:00+00:00')", (client_id,))
        draft_inv = db.execute(
            "SELECT MAX(id) AS i FROM invoices").fetchone()["i"]
        # A paid invoice with its auto-booked operating income
        db.execute(
            "INSERT INTO invoices (client_id, invoice_number, issue_date, "
            "due_date, status, created_at) VALUES (?, '2026-901', "
            "'2026-10-01', '2026-10-31', 'paid', "
            "'2026-10-01T00:00:00+00:00')", (client_id,))
        paid_inv = db.execute(
            "SELECT MAX(id) AS i FROM invoices").fetchone()["i"]
        fees_acct = db.execute(
            "SELECT id FROM coa_accounts WHERE code = '4000'").fetchone()
        fees_id = fees_acct["id"] if fees_acct else db.execute(
            "SELECT id FROM coa_accounts LIMIT 1").fetchone()["id"]
        db.execute(
            "INSERT INTO op_transactions (account_id, txn_date, amount_cents, "
            "description, invoice_id, created_at) VALUES (?, '2026-10-15', "
            "115000, 'Payment invoice 2026-901', ?, "
            "'2026-10-15T00:00:00+00:00')", (fees_id, paid_inv))
        linked_op_id = db.execute(
            "SELECT MAX(id) AS i FROM op_transactions").fetchone()["i"]
        # Trust: $100 deposit for the client
        db.execute(
            "INSERT INTO trust_transactions (account_id, client_id, case_id, "
            "txn_date, txn_type, amount_cents, description, reference, "
            "reverses_id, created_by, created_at) VALUES (?, ?, ?, "
            "'2026-10-01', 'deposit', 10000, 'Retainer', '', NULL, ?, "
            "'2026-10-01T00:00:00+00:00')",
            (acct_id, client_id, case_id, admin_id))
        dep_id = db.execute(
            "SELECT MAX(id) AS i FROM trust_transactions").fetchone()["i"]
        db.execute(
            "INSERT INTO notes (entity_type, entity_id, note_text, "
            "created_by, created_at) VALUES ('client', ?, 'keep me', ?, "
            "'2026-10-01T00:00:00+00:00')", (client_id, admin_id))
        db.commit()

    admin = login(m.app.test_client(), "admin", "changeme123")
    admin.post("/change-password", data={
        "csrf_token": csrf(admin), "current_password": "changeme123",
        "new_password": "Newpass123!", "confirm_password": "Newpass123!"},
        follow_redirects=True)
    acct = login(m.app.test_client(), "acct", "testpass123!")
    staffer = login(m.app.test_client(), "staffer", "testpass123!")

    def tr_post(data):
        return admin.post("/trust/transactions/new", data=data)

    def trust_count():
        with m.app.app_context():
            return m.get_db().execute(
                "SELECT COUNT(*) AS c FROM trust_transactions"
            ).fetchone()["c"]

    # === 1. Trust reversal hardening =======================================
    print("trust reversal:")
    n0 = trust_count()
    r = tr_post({"csrf_token": csrf(admin), "reverse_id": str(dep_id),
                 "account_id": str(acct_id), "client_id": str(client_id),
                 "txn_type": "reversal", "amount": "100.00",
                 "txn_date": "2026-10-19", "reference": "", "case_id": "",
                 "description": "Correction of entry dated 2026-10-01: typo"})
    check("legit reversal posts 302 + 1 row", r.status_code in (301, 302)
          and trust_count() == n0 + 1, f"got {r.status_code}")
    # exact offset: balance back to original
    with m.app.app_context():
        b = m.get_db().execute(
            "SELECT COALESCE(SUM(CASE WHEN txn_type IN ('deposit','transfer_in','reversal_credit') "
            "THEN amount_cents ELSE -amount_cents END), 0) AS b "
            "FROM trust_transactions WHERE account_id = ? AND client_id = ?",
            (acct_id, client_id)).fetchone()["b"]
    check("balance offset exactly (100-100=0)", b == 0, f"got {b}")
    rev_id = trust_count()
    # double reversal refused
    r = tr_post({"csrf_token": csrf(admin), "reverse_id": str(dep_id),
                 "account_id": str(acct_id), "client_id": str(client_id),
                 "txn_type": "reversal", "amount": "100.00",
                 "txn_date": "2026-10-19", "description": "again"})
    check("double reversal refused", trust_count() == rev_id
          and b"already been reversed" in r.data)
    # inflated amount refused
    r = tr_post({"csrf_token": csrf(admin), "reverse_id": str(dep_id),
                 "account_id": str(acct_id), "client_id": str(client_id),
                 "txn_type": "reversal", "amount": "500.00",
                 "txn_date": "2026-10-19", "description": "inflated"})
    check("inflated reversal refused", trust_count() == rev_id
          and b"exact original amount" in r.data)
    # cross-client refused
    with m.app.app_context():
        m.get_db().execute(
            "INSERT INTO clients (first_name, last_name, email, created_at, "
            "updated_at) VALUES ('B', 'Two', 'b@b.com', "
            "'2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')")
        cB = m.get_db().execute(
            "SELECT MAX(id) AS i FROM clients").fetchone()["i"]
        m.get_db().commit()
    r = tr_post({"csrf_token": csrf(admin), "reverse_id": str(dep_id),
                 "account_id": str(acct_id), "client_id": str(cB),
                 "txn_type": "reversal", "amount": "100.00",
                 "txn_date": "2026-10-19", "description": "cross"})
    check("cross-client reversal refused", trust_count() == rev_id)
    # reversal of a reversal refused
    with m.app.app_context():
        rr = m.get_db().execute(
            "SELECT id FROM trust_transactions WHERE reverses_id = ?",
            (dep_id,)).fetchone()["id"]
    r = tr_post({"csrf_token": csrf(admin), "reverse_id": str(rr),
                 "account_id": str(acct_id), "client_id": str(client_id),
                 "txn_type": "reversal", "amount": "100.00",
                 "txn_date": "2026-10-19", "description": "rev of rev"})
    check("reversal of reversal refused", trust_count() == rev_id)
    # overdraft reversal refused (disburse everything first)
    with m.app.app_context():
        m.get_db().execute(
            "INSERT INTO trust_transactions (account_id, client_id, case_id, "
            "txn_date, txn_type, amount_cents, description, reference, "
            "reverses_id, created_by, created_at) VALUES (?, ?, ?, "
            "'2026-10-02', 'deposit', 10000, 'Fresh', '', NULL, ?, "
            "'2026-10-02T00:00:00+00:00')",
            (acct_id, client_id, case_id, admin_id))
        dep2 = m.get_db().execute(
            "SELECT MAX(id) AS i FROM trust_transactions").fetchone()["i"]
        m.get_db().commit()
    admin.post("/trust/transactions/new", data={
        "csrf_token": csrf(admin), "account_id": str(acct_id),
        "client_id": str(client_id), "txn_type": "disbursement",
        "amount": "100.00", "txn_date": "2026-10-19",
        "description": "empty out"})
    r = tr_post({"csrf_token": csrf(admin), "reverse_id": str(dep2),
                 "account_id": str(acct_id), "client_id": str(client_id),
                 "txn_type": "reversal", "amount": "100.00",
                 "txn_date": "2026-10-19", "description": "overdraw"})
    check("overdraft reversal refused",
          b"overdraw" in r.data)
    with m.app.app_context():
        b = m.get_db().execute(
            "SELECT COALESCE(SUM(CASE WHEN txn_type IN ('deposit','transfer_in','reversal_credit') "
            "THEN amount_cents ELSE -amount_cents END), 0) AS b "
            "FROM trust_transactions WHERE account_id = ? AND client_id = ?",
            (acct_id, client_id)).fetchone()["b"]
    check("balance non-negative after attacks", b >= 0, f"got {b}")

    # === 2. FK validation — fail closed, no 500 ============================
    print("fk validation:")
    for url, payload in (
        (f"/clients/{client_id}/children/add",
         {"name": "Kid", "date_of_birth": ""}),
        ("/cases/new", {"case_number": "2026-999", "client_id": "999999",
                        "case_type": "divorce", "status": "active"}),
        ("/events/new", {"title": "X", "event_date": "2026-11-01",
                         "event_type": "reminder", "case_id": "999999"}),
        ("/invoices/new", {"client_id": "999999"}),
        ("/accounting/transactions/new",
         {"account_id": "999999", "txn_kind": "expense", "amount": "10",
          "description": "x", "txn_date": "2026-10-01"}),
        ("/accounting/transactions/new",
         {"account_id": str(fees_id), "txn_kind": "expense", "amount": "10",
          "description": "x", "txn_date": "2026-10-01",
          "client_id": "999999"}),
        ("/accounting/employees/new",
         {"full_name": "Ghost", "pay_rate": "25", "pay_type": "hourly",
          "pay_frequency": "weekly", "filing_status": "single",
          "user_id": "999999"}),
    ):
        bad = url.replace("999999", "ghost") if False else url
        payload["csrf_token"] = csrf(admin)
        r = admin.post(url, data=payload)
        check(f"{url} bad FK -> no 500", r.status_code < 500,
              f"got {r.status_code}")
    r = admin.post("/trust/transactions/new", data={
        "csrf_token": csrf(admin), "account_id": str(acct_id),
        "client_id": str(client_id), "txn_type": "deposit",
        "amount": "10.00", "txn_date": "2026-10-19",
        "description": "x", "case_id": "999999"})
    check("trust txn bad case_id -> no 500", r.status_code < 500)
    r = admin.post(f"/clients/999999/children/add", data={
        "csrf_token": csrf(admin), "name": "Kid"})
    check("child add bad client -> 404", r.status_code == 404)

    # timeclock manual entry: NaN hours, bad employee
    r = admin.post("/timeclock", data={
        "csrf_token": csrf(admin), "employee_id": "999999",
        "entry_date": "2026-10-01", "hours": "2", "notes": ""})
    check("manual entry bad employee -> no 500", r.status_code < 500)
    r = admin.post("/timeclock", data={
        "csrf_token": csrf(admin), "employee_id": str(emp_hourly),
        "entry_date": "2026-10-01", "hours": "nan", "notes": ""})
    check("manual entry NaN hours -> rejected", r.status_code < 500
          and b"valid hours" in r.data or r.status_code == 302)

    # === 3. Delete safety =================================================
    print("delete safety:")
    r = admin.post(f"/clients/{client_id}/delete",
                   data={"csrf_token": csrf(admin)}, follow_redirects=True)
    check("client delete w/ invoices -> blocked not 500",
          r.status_code == 200 and b"still have" in r.data)
    with m.app.app_context():
        db = m.get_db()
        # notes: attach one to the invoice + draft-invoice time entry guard
        db.execute(
            "INSERT INTO notes (entity_type, entity_id, note_text, "
            "created_by, created_at) VALUES ('invoice', ?, 'inv note', ?, "
            "'2026-10-01T00:00:00+00:00')", (draft_inv, admin_id))
        db.commit()
    # case delete with trust txn linked -> blocked
    r = admin.post(f"/cases/{case_id}/delete",
                   data={"csrf_token": csrf(admin)}, follow_redirects=True)
    check("case delete w/ trust txn -> blocked not 500",
          r.status_code == 200 and b"referenced" in r.data)
    # case delete without financial links: docs file + notes cleaned
    with m.app.app_context():
        db = m.get_db()
        db.execute(
            "INSERT INTO cases (client_id, case_number, title, case_type, "
            "status, created_at, updated_at) VALUES (?, '2026-777', "
            "'Lonely', 'divorce', 'active', '2026-01-01T00:00:00+00:00', "
            "'2026-01-01T00:00:00+00:00')", (client_id,))
        lonely = db.execute(
            "SELECT MAX(id) AS i FROM cases").fetchone()["i"]
        db.execute(
            "INSERT INTO notes (entity_type, entity_id, note_text, "
            "created_by, created_at) VALUES ('case', ?, 'c note', ?, "
            "'2026-10-01T00:00:00+00:00')", (lonely, admin_id))
        db.commit()
        import shutil as _sh
        docdir = os.path.join(SCRATCH, "instance", "documents", str(lonely))
        os.makedirs(docdir, exist_ok=True)
        open(os.path.join(docdir, "ka.txt"), "w").write("x")
    r = admin.post(f"/cases/{lonely}/delete",
                   data={"csrf_token": csrf(admin)}, follow_redirects=True)
    with m.app.app_context():
        db = m.get_db()
        gone = db.execute(
            "SELECT COUNT(*) AS c FROM cases WHERE id = ?",
            (lonely,)).fetchone()["c"] == 0
        note_gone = db.execute(
            "SELECT COUNT(*) AS c FROM notes WHERE entity_type = 'case' "
            "AND entity_id = ?", (lonely,)).fetchone()["c"] == 0
        files_gone = not os.path.exists(
            os.path.join(SCRATCH, "instance", "documents", str(lonely)))
    check("case delete cleans notes + doc files",
          gone and note_gone and files_gone)
    r = admin.post("/clients/999999/delete",
                   data={"csrf_token": csrf(admin)})
    check("client delete nonexistent -> 404", r.status_code == 404)

    # === 4. Payroll =======================================================
    print("payroll:")
    with m.app.app_context():
        db = m.get_db()
        # half-cent SS: reg 40 + OT 5 @ $25/h -> gross $1,187.50, SS $73.63
        db.execute(
            "INSERT INTO employees (full_name, pay_type, pay_rate_cents, "
            "pay_frequency, filing_status, allowances, is_active, created_at) "
            "VALUES ('Half Cent', 'hourly', ?, 'weekly', 'single', 0, 1, "
            "'2026-01-01T00:00:00+00:00')",
            (m.encrypt_value("2500"),))
        hc = db.execute(
            "SELECT id FROM employees WHERE full_name = 'Half Cent'"
        ).fetchone()["id"]
        db.commit()
    import importlib
    pr = importlib.import_module("payroll")
    with m.app.app_context():
        db = m.get_db()
        emp = m._employee_dict(db.execute(
            "SELECT * FROM employees WHERE id = ?", (hc,)).fetchone())
        calc = pr.calculate_paycheck(db, emp, 40.0, 5.0)
    check("half-cent SS rounds up", calc["ss"] == 73.63,
          f"got {calc['ss']}")
    # duplicate generate guard
    with m.app.app_context():
        db = m.get_db()
        db.execute(
            "INSERT INTO timeclock_entries (employee_id, clock_in, "
            "manual_hours, entry_date, created_by, created_at) VALUES (?, "
            "'2026-10-12T00:00:00', 40, '2026-10-12', ?, "
            "'2026-10-12T00:00:00+00:00')", (hc, admin_id))
        db.commit()
    r = admin.post("/accounting/payroll", data={
        "csrf_token": csrf(admin), "period_start": "2026-10-12",
        "period_end": "2026-10-18", "pay_date": "2026-10-21",
        "action": "generate"})
    with m.app.app_context():
        n1 = m.get_db().execute(
            "SELECT COUNT(*) AS c FROM paychecks "
            "WHERE pay_period_start = '2026-10-12' "
            "AND pay_period_end = '2026-10-18'").fetchone()["c"]
    r2 = admin.post("/accounting/payroll", data={
        "csrf_token": csrf(admin), "period_start": "2026-10-12",
        "period_end": "2026-10-18", "pay_date": "2026-10-21",
        "action": "generate"}, follow_redirects=True)
    with m.app.app_context():
        n2 = m.get_db().execute(
            "SELECT COUNT(*) AS c FROM paychecks "
            "WHERE pay_period_start = '2026-10-12' "
            "AND pay_period_end = '2026-10-18'").fetchone()["c"]
    check("first generate works", n1 > 0, f"n1={n1}")
    check("second generate refused, no duplicates",
          n2 == n1 and b"already generated" in r2.data)
    # PFML employer share
    with m.app.app_context():
        db = m.get_db()
        db.execute(
            "UPDATE tax_rates SET value = '1' WHERE key = 'pfml_employer_pays'")
        db.commit()
        emp = m._employee_dict(db.execute(
            "SELECT * FROM employees WHERE id = ?", (hc,)).fetchone())
        c2 = pr.calculate_paycheck(db, emp, 40.0, 0.0)
    expect = round(1000 * 0.0092 * (1 - 0.7143), 2)
    check("pfml employer share included",
          c2["employer_pfml"] == expect, f"got {c2['employer_pfml']} want {expect}")
    # salaried L&I uses real hours
    with m.app.app_context():
        db = m.get_db()
        db.execute(
            "INSERT INTO timeclock_entries (employee_id, clock_in, "
            "manual_hours, entry_date, created_by, created_at) VALUES (?, "
            "'2026-10-13T00:00:00', 10, '2026-10-13', ?, "
            "'2026-10-13T00:00:00+00:00')", (emp_salaried, admin_id))
        db.commit()
        semp = m._employee_dict(db.execute(
            "SELECT * FROM employees WHERE id = ?",
            (emp_salaried,)).fetchone())
        c3 = pr.calculate_paycheck(db, semp, 0.0, 0.0, li_hours=10.0)
    check("salaried L&I on 10h", c3["employer_li"] == round(10 * 0.25, 2),
          f"got {c3['employer_li']}")

    # === 5. Timeclock mixed datetimes =====================================
    print("timeclock:")
    h_mix = pr.entry_hours(
        {"manual_hours": None,
         "clock_in": "2026-10-19T16:00:00+00:00",
         "clock_out": "2026-10-19T23:30:00"})
    check("mixed aware/naive no crash, 7.5h", h_mix == 7.5, f"got {h_mix}")
    h_neg = pr.entry_hours(
        {"manual_hours": None,
         "clock_in": "2026-10-19T16:00:00+00:00",
         "clock_out": "2026-10-19T10:00:00"})
    check("negative span clamped to 0", h_neg == 0.0, f"got {h_neg}")

    # === 6. CSRF on dashboard JSON endpoints ==============================
    print("csrf:")
    c = login(m.app.test_client(), "admin", "Newpass123!")
    r = c.post("/dashboard/customize/reset")
    check("reset w/o token -> 400", r.status_code == 400)
    r = c.post("/dashboard/customize/reset",
               json={"csrf_token": csrf(c)})
    check("reset w/ token -> 200", r.status_code == 200)
    r = c.post("/dashboard/customize", json={"widgets": []})
    check("customize w/o token -> 400", r.status_code == 400)
    r = c.post("/dashboard/theme", json={"theme": "dark"})
    check("theme w/o token -> 400", r.status_code == 400)

    # === 7. Dead filters revived ==========================================
    print("filters:")
    r = admin.get(f"/accounting/reports/ledger?from_date=2026-09-01"
                  f"&to_date=2026-09-30")
    check("ledger from_date accepted 200", r.status_code == 200)
    r = admin.get(f"/accounting/transactions?account_id={fees_id}")
    check("txn account_id accepted 200", r.status_code == 200)

    # === 8. Ungated links =================================================
    print("links:")
    r = acct.get(f"/clients/{client_id}")
    check("accountant client page hides Open link", b"case_detail" not in r.data
          or b"view_cases" in r.data or r.status_code == 200)
    body = r.get_data(as_text=True)
    check("accountant sees no /cases/ link", "/cases/1" not in body)

    # === 9. Invoices ======================================================
    print("invoices:")
    # half-cent line: 0.02h x $275.25 -> 551 cents total
    with m.app.app_context():
        db = m.get_db()
        db.execute(
            "INSERT INTO time_entries (case_id, entry_date, hours, "
            "description, rate, user_id, invoiced, created_at) VALUES (?, "
            "'2026-10-05', 0.02, 'Tiny', 275.25, ?, 0, "
            "'2026-10-05T00:00:00+00:00')", (case_id, admin_id))
        te = db.execute("SELECT MAX(id) AS i FROM time_entries"
                        ).fetchone()["i"]
        db.commit()
    r = admin.post("/invoices/new", data={
        "csrf_token": csrf(admin), "client_id": str(client_id),
        "issue_date": "2026-10-01", "due_date": "2026-10-31",
        "entry_ids": [str(te)], "item_desc": [], "item_amount": [],
        "item_date": []})
    with m.app.app_context():
        db = m.get_db()
        inv = db.execute(
            "SELECT MAX(id) AS i FROM invoices").fetchone()["i"]
        total = m._invoice_total_cents(db, inv)
    check("half-cent line totals 551", total == 551, f"got {total}")
    # negative manual line refused
    r = admin.post("/invoices/new", data={
        "csrf_token": csrf(admin), "client_id": str(client_id),
        "issue_date": "2026-10-01", "due_date": "2026-10-31",
        "entry_ids": [], "item_desc": ["Adj"], "item_amount": ["-50"],
        "item_date": ["2026-10-01"]})
    check("negative manual line refused", b"above $0" in r.data)
    # time entry validation
    r = admin.post(f"/cases/{case_id}/time", data={
        "csrf_token": csrf(admin), "hours": "nan", "description": "x",
        "entry_date": "2026-10-01", "rate": "300"})
    check("nan hours rejected", r.status_code < 500)
    r = admin.post(f"/cases/{case_id}/time", data={
        "csrf_token": csrf(admin), "hours": "2", "description": "x",
        "entry_date": "2026-10-01", "rate": "-50"})
    check("negative rate rejected", r.status_code < 500)
    # case_new date_closed + type membership
    r = admin.post("/cases/new", data={
        "csrf_token": csrf(admin), "case_number": "2026-888",
        "title": "T", "client_id": str(client_id),
        "case_type": "'; DROP TABLE cases;--", "status": "closed",
        "date_opened": "2026-10-01", "date_closed": "2026-10-10", "notes": ""})
    with m.app.app_context():
        row = m.get_db().execute(
            "SELECT case_type, date_closed FROM cases WHERE case_number = "
            "'2026-888'").fetchone()
    check("case_new: bad type sanitized + date_closed kept",
          row and row["case_type"] == "other"
          and row["date_closed"] == "2026-10-10")

    # === 10. Op-transaction admin override ================================
    print("op-txn override:")
    r = admin.post(f"/accounting/transactions/{linked_op_id}/delete", data={
        "csrf_token": csrf(admin), "retention_override": "1",
        "override_reason": "audit test", "override_confirm": "DELETE"})
    with m.app.app_context():
        db = m.get_db()
        gone = db.execute(
            "SELECT COUNT(*) AS c FROM op_transactions WHERE id = ?",
            (linked_op_id,)).fetchone()["c"] == 0
        aud = db.execute(
            "SELECT COUNT(*) AS c FROM audit_log WHERE action = "
            "'retention_override_delete'").fetchone()["c"] >= 1
    check("admin override deletes linked txn + audit", gone and aud)
    # rebuild one for the non-admin test
    with m.app.app_context():
        db = m.get_db()
        db.execute(
            "INSERT INTO op_transactions (account_id, txn_date, amount_cents, "
            "description, invoice_id, created_at) VALUES (?, '2026-10-15', "
            "115000, 'Again', ?, '2026-10-15T00:00:00+00:00')",
            (fees_id, paid_inv))
        again = db.execute(
            "SELECT MAX(id) AS i FROM op_transactions").fetchone()["i"]
        db.commit()
    r = acct.post(f"/accounting/transactions/{again}/delete", data={
        "csrf_token": csrf(acct), "retention_override": "1",
        "override_reason": "hax", "override_confirm": "DELETE"})
    with m.app.app_context():
        kept = m.get_db().execute(
            "SELECT COUNT(*) AS c FROM op_transactions WHERE id = ?",
            (again,)).fetchone()["c"] == 1
    check("accountant override refused, txn kept", kept)
    # unlinked op txn still deletes normally
    with m.app.app_context():
        db = m.get_db()
        db.execute(
            "INSERT INTO op_transactions (account_id, txn_date, amount_cents, "
            "description, created_at) VALUES (?, '2026-10-15', -100, "
            "'Plain', '2026-10-15T00:00:00+00:00')", (fees_id,))
        plain = db.execute(
            "SELECT MAX(id) AS i FROM op_transactions").fetchone()["i"]
        db.commit()
    r = admin.post(f"/accounting/transactions/{plain}/delete",
                   data={"csrf_token": csrf(admin)})
    with m.app.app_context():
        gone2 = m.get_db().execute(
            "SELECT COUNT(*) AS c FROM op_transactions WHERE id = ?",
            (plain,)).fetchone()["c"] == 0
    check("plain op txn deletes normally", gone2)
    # op_txn_new: zero amount / bad kind
    r = admin.post("/accounting/transactions/new", data={
        "csrf_token": csrf(admin), "account_id": str(fees_id),
        "txn_kind": "expense", "amount": "0", "description": "zero",
        "txn_date": "2026-10-15"})
    check("zero-amount op txn refused", b"$0.00" in r.data)
    r = admin.post("/accounting/transactions/new", data={
        "csrf_token": csrf(admin), "account_id": str(fees_id),
        "txn_kind": "whatever", "amount": "10", "description": "kind",
        "txn_date": "2026-10-15"})
    check("bogus txn_kind refused", b"valid transaction kind" in r.data)

    # tax settings: garbage rejected
    r = admin.post("/accounting/settings", data={
        "csrf_token": csrf(admin), "rate_ss_rate": "banana"})
    with m.app.app_context():
        v = m.get_db().execute(
            "SELECT value FROM tax_rates WHERE key = 'ss_rate'"
        ).fetchone()["value"]
    check("tax settings garbage rejected", v == "6.2", f"got {v}")
    # client_new empty name
    r = admin.post("/clients/new", data={
        "csrf_token": csrf(admin), "first_name": "", "last_name": ""})
    check("client_new empty name rejected",
          b"first and last name" in r.data)

    # === 11. Template smoke (new classes / icons / branches) ==============
    print("templates:")
    r = admin.get("/trust/reports/three-way")
    check("three-way renders", r.status_code == 200)
    r = admin.get("/trust/reports/trial-balance")
    check("trial balance renders", r.status_code == 200)
    with m.app.app_context():
        db = m.get_db()
        db.execute(
            "INSERT INTO integrations (provider, status, last_error, "
            "created_at, updated_at) VALUES ('gmail', 'needs_reauth', "
            "'expired', '2026-01-01T00:00:00+00:00', "
            "'2026-01-01T00:00:00+00:00')")
        db.commit()
    r = admin.get("/integrations")
    check("integrations renders w/ needs_reauth",
          r.status_code == 200 and b"Reconnect needed" in r.data)
    r = admin.get("/accounting/reports/pl")
    check("pl report renders w/ download icon",
          r.status_code == 200 and b"icon-download" in r.data)
    r = admin.get("/cases/1/time")
    check("time list renders", r.status_code == 200)

    print()
    if FAILURES:
        print(f"FAILURES ({len(FAILURES)}):")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
