#!/usr/bin/env python3
"""Regression tests for v2.4.7 (hard admin-role gate for user management).

Run with the app's Python env: /tmp/lawfirm-test-venv/bin/python tests/test_v247.py

Garrett's scenario: a staff user whose STORED permissions JSON contains
manage_users=true (polluted data — granted during testing or an admin slip)
must NOT be able to use user management. Administration routes are now
gated by the admin ROLE (hard role check), not the grantable permission.

Covers:
  1. Polluted staff (manage_users=true in stored perms): GET /users, GET+POST
     /users/<own>/edit, POST reset-password, POST deactivate -> all 403,
     and a hostile POST to the edit endpoint leaves their DB permissions
     byte-identical (attack wrote nothing).
  2. Polluted attorney (manage_users=true) -> same refusals.
  3. Polluted accountant (manage_users=true) -> same refusals.
  4. Integrations routes are admin-gated too: polluted staff GET
     /integrations -> 403, POST integration_settings -> 403.
  5. Nav: polluted staff's dashboard HTML has no Users or Integrations
     links (href="/users" and href="/integrations" absent).
  6. first_allowed_endpoint never hands a non-admin the users page.
  7. Admin role: all routes work; admin CANNOT deactivate self or remove
     own manage_users (existing guards intact under the new gate);
     a second admin edit still works normally.

Runs against a throwaway copy — never touches the real DB.
"""
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = tempfile.mkdtemp(prefix="lawfirm-test-v247-")
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
    r = client.post("/login", data={"username": username,
                                    "password": password,
                                    "csrf_token": csrf(client)})
    assert r.status_code in (301, 302), f"login {username}: {r.status_code}"
    return client


def pollute(user_id, db):
    """Grant manage_users into a NON-admin user's stored permission JSON."""
    perms = json.dumps({**m.role_default_permissions("staff"),
                        "manage_users": True})
    db.execute("UPDATE users SET permissions = ? WHERE id = ?",
               (perms, user_id))
    db.commit()


def make_role_user(db, username, role, password="<redacted>"):
    db.execute(
        "INSERT INTO users (username, password_hash, full_name, "
        "must_change_password, role, is_active, permissions, "
        "created_at) VALUES (?, ?, ?, 0, ?, 1, ?, '2026-01-01T00:00:00+00:00')",
        (username, generate_password_hash(password), username.title(),
         role, json.dumps(m.role_default_permissions(role))))
    return db.execute("SELECT id FROM users WHERE username = ?",
                      (username,)).fetchone()["id"]


def get_perms_json(db, user_id):
    return db.execute("SELECT permissions FROM users WHERE id = ?",
                      (user_id,)).fetchone()["permissions"]


def main():
    with m.app.app_context():
        m.init_db()
        db = m.get_db()

        # Seeded admin from init_db has must_change_password=1 and the
        # default admin password; leave it for the admin tests below.
        staff_id = make_role_user(db, "pollstaff", "staff")
        atty_id = make_role_user(db, "pollatty", "attorney")
        acct_id = make_role_user(db, "pollacct", "accountant")
        for uid in (staff_id, atty_id, acct_id):
            pollute(uid, db)

        admin_id = db.execute(
            "SELECT id FROM users WHERE username = 'admin'").fetchone()["id"]

    # === 1-3. Polluted non-admins: every admin route refuses ==============
    for uname, uid, label in (("pollstaff", staff_id, "staff"),
                             ("pollatty", atty_id, "attorney"),
                             ("pollacct", acct_id, "accountant")):
        c = login(m.app.test_client(), uname, "<redacted>")
        tok = csrf(c)
        with m.app.app_context():
            before_perms = get_perms_json(m.get_db(), uid)

        check(f"{label}: GET /users -> 403",
              c.get("/users").status_code == 403)
        check(f"{label}: GET /users/new -> 403",
              c.get("/users/new").status_code == 403)
        check(f"{label}: GET own edit page -> 403",
              c.get(f"/users/{uid}/edit").status_code == 403)
        check(f"{label}: POST /users/new -> 403",
              c.post("/users/new", data={"csrf_token": tok,
                                         "username": "evil",
                                         "password": "<redacted>",
                                         "full_name": "Evil",
                                         "role": "admin"}).status_code == 403)

        # Hostile attack POST: try to grant self everything via the edit page
        r = c.post(f"/users/{uid}/edit", data={
            "csrf_token": tok, "full_name": "Pwned",
            "role": "admin", "is_active": "1",
            "perm_manage_users": "1", "perm_view_trust": "1"})
        check(f"{label}: hostile edit POST -> 403", r.status_code == 403)
        with m.app.app_context():
            db = m.get_db()
            perms_row = get_perms_json(db, uid)
            role = db.execute("SELECT role, full_name FROM users WHERE id = ?",
                              (uid,)).fetchone()
        check(f"{label}: DB permissions byte-identical after attack",
              perms_row == before_perms)
        check(f"{label}: full_name unchanged after attack",
              "Pwned" != role["full_name"])
        check(f"{label}: role unchanged after attack", role["role"] != "admin")

        check(f"{label}: POST reset-password on admin -> 403",
              c.post(f"/users/{admin_id}/reset-password",
                     data={"csrf_token": tok}).status_code == 403)
        check(f"{label}: POST deactivate admin -> 403",
              c.post(f"/users/{admin_id}/deactivate",
                     data={"csrf_token": tok}).status_code == 403)
        check(f"{label}: POST reactivate -> 403",
              c.post(f"/users/{admin_id}/reactivate",
                     data={"csrf_token": tok}).status_code == 403)
        with m.app.app_context():
            db = m.get_db()
            admin_active = db.execute(
                "SELECT is_active FROM users WHERE id = ?",
                (admin_id,)).fetchone()["is_active"]
        check(f"{label}: admin account untouched", admin_active == 1)

    # === 4. Integrations routes admin-gated ===============================
    c = login(m.app.test_client(), "pollstaff", "<redacted>")
    tok = csrf(c)
    check("polluted staff: GET /integrations -> 403",
          c.get("/integrations").status_code == 403)
    check("polluted staff: GET /admin/update -> 403",
          c.get("/admin/update").status_code == 403)
    check("polluted staff: POST /integrations/gmail/settings -> 403",
          c.post("/integrations/gmail/settings",
                 data={"csrf_token": tok}).status_code == 403)
    check("polluted staff: POST /admin/update/apply -> 403",
          c.post("/admin/update/apply",
                 data={"csrf_token": tok}).status_code == 403)

    # === 5. Nav: no Users/Integrations links for polluted staff ==========
    html = c.get("/dashboard").get_data(as_text=True)
    check("nav: no href=\"/users\" for polluted staff", 'href="/users"' not in html)
    check("nav: no href=\"/integrations\" for polluted staff",
          'href="/integrations"' not in html)

    # === 6. first_allowed_endpoint skips admin-only for non-admins =======
    check("first_allowed_endpoint: non-admin never gets user_list/integrations",
          m.first_allowed_endpoint(
              {**m.role_default_permissions("staff"), "manage_users": True},
              admin=False) not in ("user_list", "integration_list"))
    check("first_allowed_endpoint: admin still lands on a permitted page",
          m.first_allowed_endpoint(m.role_default_permissions("admin"),
                                   admin=True) == "dashboard")

    # === 7. Admin: everything works, self-guards intact ===================
    admin = login(m.app.test_client(), "admin", "changeme123")
    admin.post("/change-password", data={
        "csrf_token": csrf(admin), "current_password": "changeme123",
        "new_password": "<redacted>", "confirm_password": "<redacted>"})
    check("admin: GET /users -> 200",
          admin.get("/users").status_code == 200)
    check("admin: GET /integrations -> 200",
          admin.get("/integrations").status_code == 200)
    check("admin: GET /admin/update -> 200",
          admin.get("/admin/update").status_code == 200)
    tok = csrf(admin)
    # Admin edits another user normally
    r = admin.post(f"/users/{staff_id}/edit", data={
        "csrf_token": tok, "full_name": "Poll Staff Renamed",
        "role": "staff", "is_active": "1",
        "perm_use_timeclock": "1", "perm_manage_users": "1"})
    check("admin: edit other user -> redirect to /users",
          r.status_code in (301, 302))
    with m.app.app_context():
        db = m.get_db()
        nm = db.execute("SELECT full_name FROM users WHERE id = ?",
                        (staff_id,)).fetchone()["full_name"]
    check("admin: other-user edit took effect", nm == "Poll Staff Renamed")

    # Admin cannot strip own manage_users (guard kept)
    r = admin.post(f"/users/{admin_id}/edit", data={
        "csrf_token": csrf(admin), "full_name": "System Administrator",
        "role": "admin", "is_active": "1", "perm_use_timeclock": "1"})
    with m.app.app_context():
        db = m.get_db()
        row = db.execute("SELECT full_name FROM users WHERE id = ?",
                         (admin_id,)).fetchone()
    check("admin: self edit without manage_users refused (name unchanged)",
          row["full_name"] != "System Administrator")

    # Admin cannot deactivate self (guard kept)
    r = admin.post(f"/users/{admin_id}/deactivate",
                   data={"csrf_token": csrf(admin)})
    with m.app.app_context():
        db = m.get_db()
        active = db.execute("SELECT is_active FROM users WHERE id = ?",
                            (admin_id,)).fetchone()["is_active"]
    check("admin: self-deactivate refused", active == 1)

    # Admin CAN deactivate/reactivate a non-admin (sanity)
    r = admin.post(f"/users/{staff_id}/deactivate",
                   data={"csrf_token": csrf(admin)})
    with m.app.app_context():
        db = m.get_db()
        active = db.execute("SELECT is_active FROM users WHERE id = ?",
                            (staff_id,)).fetchone()["is_active"]
    check("admin: deactivate staff works", r.status_code in (301, 302)
          and active == 0)
    admin.post(f"/users/{staff_id}/reactivate",
               data={"csrf_token": csrf(admin)})

    # === Summary ==========================================================
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURES: {FAILURES}")
        sys.exit(1)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
