#!/usr/bin/env python3
"""
DRAFT — demo-data cleanup for the Derek demo. Review before running.

Removes a test employee (e.g. "Admin Testing") plus their whole chain:
timeclock entries, paychecks, the employee row, and the linked login user.

Usage (on the PC, from the folder that holds lawfirm.db):
    python demo-cleanup.py "Admin Testing"

It backs up lawfirm.db to lawfirm.db.demo-backup-<timestamp> first.
Run from the app folder so it finds instance/lawfirm.db, or pass --db PATH.
"""
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

TABLES_IN_ORDER = ["timeclock_entries", "paychecks"]  # employees last, users last


def find_db(explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit)
        if p.is_file():
            return p
        raise SystemExit(f"DB not found: {p}")
    candidates = [
        Path("instance/lawfirm.db"),
        Path("lawfirm.db"),
    ]
    for c in candidates:
        if c.is_file():
            return c
    raise SystemExit("Could not find lawfirm.db — run from the app folder or pass --db PATH")


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    db_arg = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--db=")), None)
    db_path = find_db(db_arg)
    name = args[0] if args else input("Employee full name to remove: ").strip()
    if not name:
        raise SystemExit("No name given — nothing done.")

    # 1. Backup first.
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = db_path.with_name(f"{db_path.name}.demo-backup-{stamp}")
    shutil.copy2(db_path, backup)
    print(f"Backed up to: {backup}")

    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys=OFF")
    cur = con.cursor()

    emp = cur.execute(
        "SELECT id, user_id, pay_type FROM employees WHERE full_name = ?", (name,)
    ).fetchone()
    if not emp:
        names = [r[0] for r in cur.execute("SELECT full_name FROM employees").fetchall()]
        con.close()
        raise SystemExit(f"No employee named {name!r}. Current employees: {names}")
    emp_id, user_id, pay_type = emp

    counts = {
        t: cur.execute(f"SELECT COUNT(*) FROM {t} WHERE employee_id = ?", (emp_id,)).fetchone()[0]
        for t in TABLES_IN_ORDER
    }
    linked_user = None
    if user_id:
        linked_user = cur.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
    linked_user = linked_user[0] if linked_user else None

    print(f"\nWill remove employee {name!r} (id={emp_id}, {pay_type}):")
    for t, n in counts.items():
        print(f"  {t}: {n}")
    print(f"  employees row: 1")
    print(f"  linked login user: {linked_user!r}" if linked_user else "  linked login user: none")

    confirm = input("\nType DELETE to confirm: ").strip()
    if confirm != "DELETE":
        con.close()
        print("Aborted — nothing changed (backup kept).")
        return

    for t in TABLES_IN_ORDER:
        cur.execute(f"DELETE FROM {t} WHERE employee_id = ?", (emp_id,))
    cur.execute("DELETE FROM employees WHERE id = ?", (emp_id,))
    if user_id:
        cur.execute("DELETE FROM users WHERE id = ?", (user_id,))
    con.commit()

    remaining = cur.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
    con.close()
    print(f"\nDone. {name!r} and their test data are gone. {remaining} employee(s) left.")
    print("Note: this bypasses the app's audit log — fine for pre-go-live test data,")
    print("not for real records after Derek signs off.")


if __name__ == "__main__":
    main()
