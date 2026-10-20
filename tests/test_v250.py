#!/usr/bin/env python3
"""Regression tests for v2.5.0 (mobile layer — phone-only presentation).

Run with the app's Python env: /tmp/lawfirm-test-venv/bin/python tests/test_v250.py

The mobile layer is a second outfit for the same pages: a bottom tab bar
(Home / Practice / Timeclock / Billing / More) and a bottom sheet that
lists the same NAV_GROUPS the desktop nav renders. style.css displays
this chrome only at <=768px; the desktop markup must be untouched.

Covers:
  1. Every role's dashboard carries BOTH navs: the desktop .nav-tabs
     markup (unchanged) and the mobile .mtab-bar + .msheet markup.
  2. Bottom-bar tabs match each role's permissions exactly:
       admin/attorney/accountant: Home, Practice, Timeclock, Billing
       staff: Home, Practice, Timeclock — NO Billing (no view_billing)
  3. More-sheet contents match NAV_GROUPS permission filtering per role:
       staff sheet has Practice items but no Trust / Audit Log /
       Templates / Users / Integrations;
       accountant sheet has Trust + Accounting but no Cases / Deadlines
       / Audit Log / Users / Integrations;
       attorney sheet has Trust + Audit Log but NOT Users / Integrations
       (admin-only items follow the v2.4.7 hard role gate);
       admin sheet has everything, Users + Integrations included.
  3b. (v2.5.1) The Practice sheet is scoped: it contains ONLY the
       permitted Practice items — no other group's items, no profile
       card, no Log out — for every role.
  4. Timeclock page carries the mobile hero markup (live clock ids,
     status pill, big button, today's punches, totals) alongside the
     untouched desktop hero; the clock-in flow flips the mobile status
     pill to "On the clock".

Runs against a throwaway copy — never touches the real DB.
"""
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = tempfile.mkdtemp(prefix="lawfirm-test-v250-")
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


def make_role_user(db, username, role, password="<redacted>"):
    db.execute(
        "INSERT INTO users (username, password_hash, full_name, "
        "must_change_password, role, is_active, permissions, "
        "created_at) VALUES (?, ?, ?, 0, ?, 1, ?, '2026-01-01T00:00:00+00:00')",
        (username, generate_password_hash(password), username.title(),
         role, json.dumps(m.role_default_permissions(role))))
    return db.execute("SELECT id FROM users WHERE username = ?",
                      (username,)).fetchone()["id"]


def regions(html):
    """Slice (more_sheet, practice_sheet, bottom_bar) out of a page.

    v2.5.1: there are TWO sheets. The More sheet (id=msheetWrap) is the
    full menu; the Practice sheet (id=msheetPracticeWrap) is scoped to
    the Practice group only. Page order: More sheet, Practice sheet,
    bottom bar, <main>.
    """
    m_start = html.index('id="msheetWrap"')
    p_start = html.index('id="msheetPracticeWrap"')
    bar_start = html.index('class="mtab-bar"')
    more = html[m_start:p_start]
    practice = html[p_start:bar_start]
    bar = html[bar_start:html.index("<main")]
    return more, practice, bar


def main():
    with m.app.app_context():
        m.init_db()
        db = m.get_db()
        staff_id = make_role_user(db, "mobstaff", "staff")
        make_role_user(db, "mobatty", "attorney")
        make_role_user(db, "mobacct", "accountant")
        # Employee linked to the staff user (timeclock hero needs one)
        db.execute(
            "INSERT INTO employees (user_id, full_name, pay_type, "
            "pay_rate_cents, pay_frequency, filing_status, allowances, "
            "is_active, created_at) VALUES (?, 'Mob Staff', 'hourly', ?, "
            "'biweekly', 'single', 0, 1, '2026-01-01T00:00:00+00:00')",
            (staff_id, m.encrypt_value("2500")))
        emp_id = db.execute(
            "SELECT id FROM employees WHERE user_id = ?",
            (staff_id,)).fetchone()["id"]
        db.commit()

    # Admin client (seeded admin must change password first)
    admin = login(m.app.test_client(), "admin", "changeme123")
    admin.post("/change-password", data={
        "csrf_token": csrf(admin), "current_password": "changeme123",
        "new_password": "<redacted>", "confirm_password": "<redacted>"})

    clients = {
        "admin": admin,
        "attorney": login(m.app.test_client(), "mobatty", "<redacted>"),
        "staff": login(m.app.test_client(), "mobstaff", "<redacted>"),
        "accountant": login(m.app.test_client(), "mobacct", "<redacted>"),
    }

    # === 1+2+3. Per-role dashboard: both navs, tabs, sheet ==============
    for role, c in clients.items():
        r = c.get("/dashboard")
        check(f"{role}: GET /dashboard -> 200", r.status_code == 200)
        html = r.get_data(as_text=True)
        check(f"{role}: desktop nav markup still present",
              'class="nav-tabs"' in html)
        check(f"{role}: mobile sheet markup present",
              'class="msheet-wrap"' in html)
        sheet, practice, bar = regions(html)
        check(f"{role}: bar has Home tab", 'mtab-label">Home<' in bar)
        check(f"{role}: bar has Practice tab (sheet opener)",
              'data-msheet-open="practice"' in bar)
        check(f"{role}: bar has Timeclock tab", 'href="/timeclock"' in bar)
        check(f"{role}: bar has More tab (sheet opener)",
              'data-msheet-open="all"' in bar)
        check(f"{role}: sheet has profile card + Log out",
              "msheet-profile" in sheet and "Log out" in sheet)

    # Billing tab: everyone except staff (staff preset has no view_billing)
    _, _, bar = regions(clients["staff"].get("/dashboard").get_data(as_text=True))
    check("staff: NO Billing tab in bottom bar", 'href="/invoices"' not in bar)
    for role in ("admin", "attorney", "accountant"):
        _, _, bar = regions(clients[role].get("/dashboard").get_data(as_text=True))
        check(f"{role}: Billing tab in bottom bar", 'href="/invoices"' in bar)

    # More-sheet (full menu) contents per role
    sheet, _, _ = regions(clients["staff"].get("/dashboard").get_data(as_text=True))
    check("staff sheet: has Cases + Deadlines",
          ">Cases<" in sheet and ">Deadlines<" in sheet)
    for absent in (">Trust<", ">Audit Log<", ">Templates<",
                   ">Users<", ">Integrations<"):
        check(f"staff sheet: no {absent}", absent not in sheet)
    check("staff sheet: no /users or /integrations hrefs",
          'href="/users"' not in sheet and 'href="/integrations"' not in sheet)

    sheet, _, _ = regions(clients["accountant"].get("/dashboard").get_data(as_text=True))
    check("accountant sheet: has Trust + Accounting",
          ">Trust<" in sheet and ">Accounting<" in sheet)
    for absent in (">Cases<", ">Deadlines<", ">Audit Log<",
                   ">Users<", ">Integrations<"):
        check(f"accountant sheet: no {absent}", absent not in sheet)

    sheet, _, _ = regions(clients["attorney"].get("/dashboard").get_data(as_text=True))
    check("attorney sheet: has Trust + Audit Log",
          ">Trust<" in sheet and ">Audit Log<" in sheet)
    check("attorney sheet: no Users / Integrations (admin-role only)",
          ">Users<" not in sheet and ">Integrations<" not in sheet
          and 'href="/users"' not in sheet
          and 'href="/integrations"' not in sheet)

    sheet, _, _ = regions(clients["admin"].get("/dashboard").get_data(as_text=True))
    check("admin sheet: has Users + Integrations",
          'href="/users"' in sheet and 'href="/integrations"' in sheet)
    check("admin sheet: has every group label",
          all(lbl in sheet for lbl in
              ("Dashboard", "Practice", "Documents", "Financial",
               "Team", "System")))

    # === 3b. Practice sheet (v2.5.1): Practice group ONLY ===============
    # The Practice tab must NOT open the same menu as More: the scoped
    # panel holds the permitted Practice destinations and nothing else —
    # no other groups, no profile card, no account rows.
    OTHER_GROUP_ITEMS = (">Trust<", ">Billing<", ">Accounting<",
                         ">Templates<", ">Audit Log<", ">Users<",
                         ">Integrations<")
    for role, c in clients.items():
        _, practice, _ = regions(c.get("/dashboard").get_data(as_text=True))
        check(f"{role} practice sheet: present",
              'aria-label="Practice sections"' in practice)
        check(f"{role} practice sheet: no profile card / Log out",
              "msheet-profile" not in practice and "Log out" not in practice)
        for absent in OTHER_GROUP_ITEMS:
            check(f"{role} practice sheet: no {absent}", absent not in practice)
        check(f"{role} practice sheet: no /users or /integrations hrefs",
              'href="/users"' not in practice
              and 'href="/integrations"' not in practice)

    _, practice, _ = regions(clients["staff"].get("/dashboard").get_data(as_text=True))
    check("staff practice sheet: has Clients/Cases/Calendar/Deadlines",
          all(lbl in practice for lbl in
              (">Clients<", ">Cases<", ">Calendar<", ">Deadlines<")))
    _, practice, _ = regions(clients["accountant"].get("/dashboard").get_data(as_text=True))
    check("accountant practice sheet: has Clients only",
          ">Clients<" in practice)
    for absent in (">Cases<", ">Calendar<", ">Deadlines<"):
        check(f"accountant practice sheet: no {absent}", absent not in practice)
    _, practice, _ = regions(clients["attorney"].get("/dashboard").get_data(as_text=True))
    check("attorney practice sheet: has all four practice items",
          all(lbl in practice for lbl in
              (">Clients<", ">Cases<", ">Calendar<", ">Deadlines<")))

    # === 4. Timeclock mobile hero ========================================
    c = clients["staff"]
    r = c.get("/timeclock")
    check("staff: GET /timeclock -> 200", r.status_code == 200)
    html = r.get_data(as_text=True)
    check("timeclock: desktop hero still present", 'class="tc-hero"' in html)
    check("timeclock: mobile hero present", 'class="tc-m-hero"' in html)
    check("timeclock: mobile live clock ids present",
          'id="tcmTime"' in html and 'id="tcmSec"' in html
          and 'id="tcmDate"' in html)
    check("timeclock: mobile status pill shows Clocked out",
          "Clocked out" in html)
    check("timeclock: mobile big button present", "tc-m-btn" in html)
    check("timeclock: mobile today's punches section present",
          "Today's punches" in html)
    check("timeclock: mobile today/week totals present",
          "This week" in html and "tc-m-totals" in html)
    check("timeclock: page still carries the mobile bottom bar",
          'class="mtab-bar"' in html)

    # Clock in through the real endpoint -> status flips on both heroes
    r = c.post(f"/timeclock/clock-in/{emp_id}",
               data={"csrf_token": csrf(c)})
    check("staff: clock-in POST redirects", r.status_code in (301, 302))
    html = c.get("/timeclock").get_data(as_text=True)
    check("timeclock: after clock-in, pill says On the clock",
          "On the clock" in html)
    check("timeclock: after clock-in, Clock out button offered",
          "Clock out" in html)

    # === Summary ==========================================================
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURES: {FAILURES}")
        sys.exit(1)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
