#!/usr/bin/env python3
"""Regression tests for v2.4.3 (run with the app's Python env):

    python3 tests/test_v243.py

Covers:
  1. Payroll "Generate paychecks" — POST with the modal-submitted field
     (action=generate) must actually create paycheck rows (Bug 1).
  2. Invoice/time-entry delete — plain delete blocked by the 7-year
     retention lock with NO 500, admin override delete works, non-admin
     override is refused (Bug 2 regression: retention_ok naive/aware
     TypeError crash).
  3. Unhandled exceptions render the designed 500 page, not Werkzeug's
     default page.
  4. Timeclock employee day view: admin/attorney can open ANY employee's
     day; staff only their own (hand-edited URL -> 403), incl. print.

Runs against a throwaway copy of the app in a temp dir — never touches
the real instance/ database.
"""
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = tempfile.mkdtemp(prefix="lawfirm-test-")
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
    tok = csrf(client)
    r = client.post("/login", data={"username": username,
                                    "password": password,
                                    "csrf_token": tok})
    assert r.status_code in (301, 302), f"login {username}: {r.status_code}"
    return client


def fresh_client():
    return m.app.test_client()


def main():
    # Register a test-only exploding route BEFORE the app's first request
    # (Flask forbids route registration afterwards).
    @m.app.route("/__test_boom")
    def _boom():
        raise RuntimeError("synthetic test explosion")

    with m.app.app_context():
        m.init_db()
        db = m.get_db()

        # --- Seed users -------------------------------------------------
        def make_user(username, role):
            db.execute(
                "INSERT INTO users (username, password_hash, full_name, "
                "must_change_password, role, is_active, permissions, "
                "created_at) VALUES (?, ?, ?, 0, ?, 1, ?, "
                "'2026-01-01T00:00:00+00:00')",
                (username, generate_password_hash("testpass123!"),
                 username.title(), role,
                 json.dumps(m.role_default_permissions(role))))
            return db.execute("SELECT id FROM users WHERE username = ?",
                              (username,)).fetchone()["id"]

        admin_id = db.execute(
            "SELECT id FROM users WHERE username = 'admin'").fetchone()["id"]
        attorney_uid = make_user("atty", "attorney")
        staff_uid = make_user("staffer", "staff")

        # --- Seed employees (rate stored Fernet-encrypted) -------------
        def make_employee(name, user_id=None):
            db.execute(
                "INSERT INTO employees (user_id, full_name, pay_type, "
                "pay_rate_cents, pay_frequency, filing_status, allowances, "
                "is_active, created_at) VALUES (?, ?, 'hourly', ?, "
                "'weekly', 'single', 0, 1, '2026-01-01T00:00:00+00:00')",
                (user_id, name, m.encrypt_value("2500")))
            return db.execute(
                "SELECT id FROM employees WHERE full_name = ?",
                (name,)).fetchone()["id"]

        emp_admin = make_employee("Admin Testing", admin_id)
        emp_staff = make_employee("Sally Staff", staff_uid)
        emp_other = make_employee("Oliver Other")

        # Punch for today for both staff and other employees.
        today_iso = m.date.today().isoformat()
        for emp_id, ci, co in (
                (emp_staff, f"{today_iso}T09:00:00", f"{today_iso}T17:00:00"),
                (emp_other, f"{today_iso}T08:30:00", f"{today_iso}T16:30:00")):
            db.execute(
                "INSERT INTO timeclock_entries (employee_id, clock_in, "
                "clock_out, entry_date, created_by, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (emp_id, ci, co, today_iso, admin_id,
                 f"{today_iso}T09:00:00"))

        # --- Seed billing data ------------------------------------------
        db.execute(
            "INSERT INTO clients (first_name, last_name, email, created_at, "
            "updated_at) VALUES ('Test', 'Client', 't@t.com', "
            "'2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')")
        client_id = db.execute("SELECT MAX(id) AS i FROM clients").fetchone()["i"]
        db.execute(
            "INSERT INTO invoices (client_id, invoice_number, issue_date, "
            "due_date, status, created_at) VALUES (?, '2026-001', "
            "'2026-10-01', '2026-10-31', 'draft', "
            "'2026-10-01T00:00:00+00:00')", (client_id,))
        inv_id = db.execute("SELECT MAX(id) AS i FROM invoices").fetchone()["i"]
        db.execute(
            "INSERT INTO invoice_items (invoice_id, description, amount) "
            "VALUES (?, 'Work', 10000)", (inv_id,))

        # Case + time entry (for time_delete override path)
        db.execute(
            "INSERT INTO cases (client_id, case_number, title, case_type, "
            "status, created_at, updated_at) VALUES (?, '2026-001', "
            "'Test v. Test', 'Divorce', 'active', "
            "'2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')",
            (client_id,))
        case_id = db.execute("SELECT MAX(id) AS i FROM cases").fetchone()["i"]
        db.execute(
            "INSERT INTO time_entries (case_id, entry_date, hours, "
            "description, rate, user_id, invoiced, created_at) VALUES "
            "(?, '2026-10-05', 1.5, 'Drafting', 300.0, ?, 0, "
            "'2026-10-05T00:00:00+00:00')", (case_id, admin_id))
        entry_id = db.execute(
            "SELECT MAX(id) AS i FROM time_entries").fetchone()["i"]
        db.commit()

    # === retention_ok units ============================================
    print("retention_ok:")
    check("date-only recent -> locked", m.retention_ok("2026-10-01") is False)
    check("datetime naive recent -> locked",
          m.retention_ok("2026-10-01T10:00:00") is False)
    check("datetime aware recent -> locked",
          m.retention_ok("2026-10-01T10:00:00+00:00") is False)
    check("old date -> ok", m.retention_ok("2010-01-01") is True)
    check("None -> fail closed", m.retention_ok(None) is False)
    check("garbage -> fail closed", m.retention_ok("junk") is False)

    # === Admin: change forced password =================================
    admin = login(fresh_client(), "admin", "changeme123")
    admin.post("/change-password", data={
        "csrf_token": csrf(admin), "current_password": "changeme123",
        "new_password": "testpass123!", "confirm_password": "testpass123!"})

    # === Bug 1: payroll generate end-to-end =============================
    print("payroll generate:")
    ps, pe = "2026-10-12", "2026-10-18"
    with m.app.app_context():
        db = m.get_db()
        # One manual-hours entry inside the period for the admin employee
        db.execute(
            "INSERT INTO timeclock_entries (employee_id, clock_in, "
            "manual_hours, entry_date, created_by, created_at) VALUES "
            "(?, '2026-10-13T00:00:00', 8.0, '2026-10-13', ?, "
            "'2026-10-13T00:00:00')", (emp_admin, admin_id))
        db.commit()
        before = db.execute("SELECT COUNT(*) AS c FROM paychecks").fetchone()["c"]
    r = admin.post("/accounting/payroll", data={
        "csrf_token": csrf(admin), "period_start": ps, "period_end": pe,
        "pay_date": "2026-10-20",
        # Exactly what the FIXED modal sends: the submit button's field
        "action": "generate"})
    check("generate POST redirects (no 500)", r.status_code in (301, 302),
          f"got {r.status_code}")
    with m.app.app_context():
        db = m.get_db()
        after = db.execute("SELECT COUNT(*) AS c FROM paychecks").fetchone()["c"]
        row = db.execute(
            "SELECT gross_cents FROM paychecks WHERE employee_id = ?",
            (emp_admin,)).fetchone()
    check("paycheck rows created", after > before, f"{before} -> {after}")
    check("paycheck gross = 8h x $25 = $200",
          row is not None and row["gross_cents"] == 20000,
          f"got {row['gross_cents'] if row else None}")
    # And the no-action POST (old broken modal behavior) creates nothing
    r = admin.post("/accounting/payroll", data={
        "csrf_token": csrf(admin), "period_start": ps, "period_end": pe,
        "pay_date": "2026-10-20"})
    with m.app.app_context():
        db = m.get_db()
        count2 = db.execute("SELECT COUNT(*) AS c FROM paychecks").fetchone()["c"]
    check("POST without action=generate creates nothing", count2 == after)

    # === Bug 2: invoice delete paths ===================================
    print("invoice delete:")
    r = admin.post(f"/invoices/{inv_id}/delete",
                   data={"csrf_token": csrf(admin)})
    check("plain delete of locked invoice: no 500", r.status_code in (301, 302),
          f"got {r.status_code}")
    with m.app.app_context():
        db = m.get_db()
        exists = db.execute("SELECT id FROM invoices WHERE id = ?",
                            (inv_id,)).fetchone()
    check("locked invoice still exists after plain delete", exists is not None)

    # Non-admin (attorney) override attempt must be refused
    atty = login(fresh_client(), "atty", "testpass123!")
    r = atty.post(f"/invoices/{inv_id}/delete", data={
        "csrf_token": csrf(atty), "retention_override": "1",
        "override_reason": "trying", "override_confirm": "DELETE"})
    check("attorney override attempt: no 500", r.status_code in (301, 302),
          f"got {r.status_code}")
    with m.app.app_context():
        db = m.get_db()
        exists = db.execute("SELECT id FROM invoices WHERE id = ?",
                            (inv_id,)).fetchone()
    check("invoice survives non-admin override attempt", exists is not None)

    # Admin override — wrong confirm word refused
    r = admin.post(f"/invoices/{inv_id}/delete", data={
        "csrf_token": csrf(admin), "retention_override": "1",
        "override_reason": "Duplicate entry", "override_confirm": "delete"})
    with m.app.app_context():
        db = m.get_db()
        exists = db.execute("SELECT id FROM invoices WHERE id = ?",
                            (inv_id,)).fetchone()
    check("override with lowercase 'delete' refused", exists is not None)

    # Admin override — correct flow
    r = admin.post(f"/invoices/{inv_id}/delete", data={
        "csrf_token": csrf(admin), "retention_override": "1",
        "override_reason": "Duplicate entry created in error",
        "override_confirm": "DELETE"})
    check("admin override delete: no 500", r.status_code in (301, 302),
          f"got {r.status_code}")
    with m.app.app_context():
        db = m.get_db()
        exists = db.execute("SELECT id FROM invoices WHERE id = ?",
                            (inv_id,)).fetchone()
        audit_row = db.execute(
            "SELECT details FROM audit_log WHERE action = "
            "'retention_override_delete' ORDER BY id DESC LIMIT 1").fetchone()
    check("invoice deleted via override", exists is None)
    check("override snapshot audit written",
          audit_row is not None and "Duplicate entry" in audit_row["details"])

    # === Bug 2b: time entry delete paths ===============================
    print("time entry delete:")
    time_del_url = f"/time/{entry_id}/delete"
    r = admin.post(time_del_url, data={"csrf_token": csrf(admin)})
    check("plain delete of locked time entry: no 500",
          r.status_code in (301, 302), f"got {r.status_code}")
    with m.app.app_context():
        db = m.get_db()
        exists = db.execute("SELECT id FROM time_entries WHERE id = ?",
                            (entry_id,)).fetchone()
    check("locked time entry survives plain delete", exists is not None)
    r = admin.post(time_del_url, data={
        "csrf_token": csrf(admin), "retention_override": "1",
        "override_reason": "Entered twice", "override_confirm": "DELETE"})
    check("time entry override delete: no 500", r.status_code in (301, 302),
          f"got {r.status_code}")
    with m.app.app_context():
        db = m.get_db()
        exists = db.execute("SELECT id FROM time_entries WHERE id = ?",
                            (entry_id,)).fetchone()
    check("time entry deleted via override", exists is None)

    # === 500 handler =====================================================
    print("500 handler:")
    r = admin.get("/__test_boom")
    body = r.get_data(as_text=True)
    check("exception returns 500", r.status_code == 500,
          f"got {r.status_code}")
    check("designed error page shown", "Something went wrong" in body)
    check("Werkzeug default page NOT shown",
          "The server encountered an internal error" not in body)

    # === Feature: employee day view =====================================
    print("employee day view:")
    r = admin.get(f"/timeclock/day/{emp_other}?date={today_iso}")
    check("admin opens other employee's day -> 200", r.status_code == 200,
          f"got {r.status_code}")
    check("page shows that employee", "Oliver Other" in r.get_data(as_text=True))

    r = atty.get(f"/timeclock/day/{emp_staff}?date={today_iso}")
    check("attorney opens other employee's day -> 200", r.status_code == 200,
          f"got {r.status_code}")

    staff = login(fresh_client(), "staffer", "testpass123!")
    r = staff.get(f"/timeclock/day/{emp_staff}?date={today_iso}")
    check("staff opens OWN day -> 200", r.status_code == 200,
          f"got {r.status_code}")
    r = staff.get(f"/timeclock/day/{emp_other}?date={today_iso}")
    check("staff opens OTHER employee's day -> 403", r.status_code == 403,
          f"got {r.status_code}")
    check("403 page leaks no punch data",
          "Oliver Other" not in r.get_data(as_text=True))

    # Print: admin single-employee sheet, staff blocked for others
    r = admin.get(f"/timeclock/day/print?date={today_iso}"
                  f"&employee_id={emp_other}")
    body = r.get_data(as_text=True)
    check("admin prints other employee's day -> 200", r.status_code == 200,
          f"got {r.status_code}")
    check("print sheet contains only that employee",
          "Oliver Other" in body and "Sally Staff" not in body)
    r = staff.get(f"/timeclock/day/print?date={today_iso}"
                  f"&employee_id={emp_other}")
    check("staff prints OTHER employee's day -> 403", r.status_code == 403,
          f"got {r.status_code}")
    r = staff.get(f"/timeclock/day/print?date={today_iso}"
                  f"&employee_id={emp_staff}")
    check("staff prints OWN day -> 200", r.status_code == 200,
          f"got {r.status_code}")

    # Aggregate day view unchanged
    r = admin.get(f"/timeclock?view=day&date={today_iso}")
    body = r.get_data(as_text=True)
    check("aggregate day view 200 w/ drill-down links",
          r.status_code == 200 and f"/timeclock/day/{emp_other}" in body)
    r = staff.get(f"/timeclock?view=day&date={today_iso}")
    body = r.get_data(as_text=True)
    check("staff aggregate day view shows only self",
          r.status_code == 200 and "Sally Staff" in body
          and "Oliver Other" not in body)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
