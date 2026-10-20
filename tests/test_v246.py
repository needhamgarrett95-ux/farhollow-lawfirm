#!/usr/bin/env python3
"""Regression tests for v2.4.6 (admin deletion of UNUSED trust accounts).

Run with the app's Python env: /tmp/lawfirm-test-venv/bin/python tests/test_v246.py

Covers:
  1. Admin deletes a brand-new trust account (0 transactions, 0
     reconciliations, $0 balance) -> row gone, audit row written with a
     snapshot; the Fernet ciphertext is stored verbatim, never plaintext.
  2. Admin tries to delete an account WITH a transaction -> refused,
     account intact, refusal audit-logged, message names the blockers
     (transactions AND balance).
  3. Admin tries to delete an account with a reconciliation but no
     transactions -> refused, account intact.
  4. Staff / attorney / accountant POSTing the delete URL directly ->
     refused (403), account intact. (Admin is a hard role gate, not a
     permission checkbox.)
  5. account_trust_balance() helper: 0 for an unused account, exact
     cents for a used one (the balance check the route relies on).
  6. Danger zone renders on the detail page for admins only: delete
     button when unused, explanation when used; non-admins see nothing.

Runs against a throwaway copy — never touches the real DB.
"""
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = tempfile.mkdtemp(prefix="lawfirm-test-v246-")
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

        db.execute(
            "INSERT INTO clients (first_name, last_name, email, created_at, "
            "updated_at) VALUES ('Test', 'Client', 't@t.com', "
            "'2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')")
        client_id = db.execute("SELECT MAX(id) AS i FROM clients"
                               ).fetchone()["i"]

        plain_acct_no = "1234567890"

        def make_ta(name, with_number=False):
            db.execute(
                "INSERT INTO trust_accounts (name, bank_name, "
                "account_number, notes, is_active, created_at) VALUES "
                "(?, 'Test Bank', ?, '', 1, '2026-01-01T00:00:00+00:00')",
                (name, m.encrypt_value(plain_acct_no) if with_number else ""))
            return db.execute("SELECT MAX(id) AS i FROM trust_accounts"
                              ).fetchone()["i"]

        fresh_id = make_ta("Fresh Unused (Garrett test)", with_number=True)
        used_id = make_ta("Used Account")
        recon_id = make_ta("Reconciled Only")

        # Used account: one $500 deposit -> 1 txn, balance 50000 cents
        db.execute(
            "INSERT INTO trust_transactions (account_id, client_id, case_id, "
            "txn_date, txn_type, amount_cents, description, reference, "
            "reverses_id, created_by, created_at) VALUES (?, ?, NULL, "
            "'2026-10-01', 'deposit', 50000, 'Retainer', '', NULL, ?, "
            "'2026-10-01T00:00:00+00:00')", (used_id, client_id, admin_id))
        # Reconciled-only account: a reconciliation row, no transactions
        db.execute(
            "INSERT INTO trust_reconciliations (account_id, statement_date, "
            "statement_balance_cents, book_balance_cents, status, "
            "reconciled_by, reconciled_at, notes, created_at) VALUES (?, "
            "'2026-10-31', 0, 0, 'matched', ?, '2026-10-31T00:00:00+00:00', "
            "'', '2026-10-31T00:00:00+00:00')", (recon_id, admin_id))
        db.commit()

        # --- 5. Balance helper ------------------------------------------
        print("balance helper:")
        check("unused account balance is 0",
              m.account_trust_balance(db, fresh_id) == 0)
        check("used account balance is exact cents",
              m.account_trust_balance(db, used_id) == 50000)

    admin = login(m.app.test_client(), "admin", "changeme123")
    admin.post("/change-password", data={
        "csrf_token": csrf(admin), "current_password": "changeme123",
        "new_password": "Newpass123!", "confirm_password": "Newpass123!"},
        follow_redirects=True)
    atty = login(m.app.test_client(), "atty", "testpass123!")
    staffer = login(m.app.test_client(), "staffer", "testpass123!")
    acct = login(m.app.test_client(), "acct", "testpass123!")

    def ta_exists(aid):
        with m.app.app_context():
            return m.get_db().execute(
                "SELECT COUNT(*) AS c FROM trust_accounts WHERE id = ?",
                (aid,)).fetchone()["c"] == 1

    def audit_count(action, needle=""):
        with m.app.app_context():
            return m.get_db().execute(
                "SELECT COUNT(*) AS c FROM audit_log WHERE action = ? "
                "AND details LIKE ?", (action, f"%{needle}%")).fetchone()["c"]

    def delete(aid, client):
        return client.post(f"/trust/accounts/{aid}/delete",
                           data={"csrf_token": csrf(client)},
                           follow_redirects=False)

    # --- 6. Danger zone rendering ---------------------------------------
    print("danger zone rendering:")
    r = admin.get(f"/trust/accounts/{fresh_id}")
    check("admin sees delete button on unused account",
          r.status_code == 200 and b"Delete this account" in r.data)
    r = admin.get(f"/trust/accounts/{used_id}")
    check("admin sees blocker explanation on used account",
          r.status_code == 200 and b"cannot be deleted" in r.data
          and b"Delete this account" not in r.data)
    r = atty.get(f"/trust/accounts/{fresh_id}")
    check("attorney sees no danger zone",
          r.status_code == 200 and b"Delete this account" not in r.data
          and b"danger zone" not in r.data)
    r = acct.get(f"/trust/accounts/{fresh_id}")
    check("accountant sees no danger zone",
          r.status_code == 200 and b"Delete this account" not in r.data
          and b"danger zone" not in r.data)

    # --- 4. Non-admins refused ------------------------------------------
    print("non-admin refusals:")
    for label, client in (("staff", staffer), ("attorney", atty),
                          ("accountant", acct)):
        r = delete(fresh_id, client)
        check(f"{label} POST delete -> 403, account intact",
              r.status_code == 403 and ta_exists(fresh_id),
              f"got {r.status_code}")

    # --- 2. Account with a transaction refused --------------------------
    print("used account refusal:")
    n_refused0 = audit_count("trust_account_delete_refused")
    r = admin.post(f"/trust/accounts/{used_id}/delete",
                   data={"csrf_token": csrf(admin)}, follow_redirects=True)
    body = r.data.decode("utf-8", "replace")
    check("used account delete refused (redirect, intact)",
          r.status_code == 200 and ta_exists(used_id))
    check("refusal message names transactions + balance",
          "1 transaction" in body and "$500.00 balance" in body)
    check("refusal audit-logged",
          audit_count("trust_account_delete_refused") == n_refused0 + 1)

    # --- 3. Account with a reconciliation only refused ------------------
    print("reconciled-only refusal:")
    n_refused0 = audit_count("trust_account_delete_refused")
    r = admin.post(f"/trust/accounts/{recon_id}/delete",
                   data={"csrf_token": csrf(admin)}, follow_redirects=True)
    body = r.data.decode("utf-8", "replace")
    check("reconciled account delete refused, intact",
          r.status_code == 200 and ta_exists(recon_id))
    check("refusal message names the reconciliation",
          "1 reconciliation" in body)
    check("reconciliation refusal audit-logged",
          audit_count("trust_account_delete_refused") == n_refused0 + 1)

    # --- 1. Admin deletes the fresh account -----------------------------
    print("admin delete of unused account:")
    r = delete(fresh_id, admin)
    check("admin delete redirects to overview",
          r.status_code in (301, 302)
          and "/trust" in r.headers.get("Location", ""),
          f"got {r.status_code} {r.headers.get('Location')}")
    check("account row is gone", not ta_exists(fresh_id))
    check("delete audit row written with snapshot",
          audit_count("trust_account_delete", "Fresh Unused") == 1)
    with m.app.app_context():
        row = m.get_db().execute(
            "SELECT details FROM audit_log WHERE action = "
            "'trust_account_delete'").fetchone()
    details = row["details"] if row else ""
    check("snapshot never contains the plaintext account number",
          plain_acct_no not in details)
    check("snapshot marks number as Fernet-encrypted",
          "Fernet-encrypted" in details)
    check("snapshot records the zero-activity facts",
          "0 transactions" in details and "0 reconciliations" in details)

    print()
    if FAILURES:
        print(f"FAILURES ({len(FAILURES)}):")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
