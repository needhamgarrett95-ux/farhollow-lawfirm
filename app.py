"""
Farhollow Law Firm - Case Management System (v1 Foundation)
Self-hosted, single-process Flask app for a solo family law practice.

Run:  python app.py
Then open: http://localhost:5000
"""
import os
import re
import io
import json
import sqlite3
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from datetime import datetime, timedelta, date, timezone
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, g, flash, abort, send_file, jsonify,
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from crypto import encrypt_value, decrypt_value, looks_encrypted
from deadlines import (
    DEADLINE_RULES,
    TRIGGER_CHOICES,
    DISCLAIMER as DEADLINE_DISCLAIMER,
    calculate_deadlines,
)

# ----------------------------------------------------------------------------
# App setup
# ----------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
os.makedirs(INSTANCE_DIR, exist_ok=True)

DB_PATH = os.path.join(INSTANCE_DIR, "lawfirm.db")
SECRET_PATH = os.path.join(INSTANCE_DIR, "secret.key")

app = Flask(__name__)

# Secret key: generated once, stored on disk so sessions survive restarts.
if os.path.exists(SECRET_PATH):
    with open(SECRET_PATH, "r") as f:
        app.secret_key = f.read().strip()
else:
    app.secret_key = secrets.token_hex(32)
    with open(SECRET_PATH, "w") as f:
        f.write(app.secret_key)

SESSION_TIMEOUT_MINUTES = 30
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=SESSION_TIMEOUT_MINUTES)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB upload cap

CASE_TYPES = ["divorce", "custody", "support", "adoption", "other"]
CASE_STATUSES = ["active", "pending", "closed"]

DOC_CATEGORIES = ["pleadings", "correspondence", "discovery", "evidence", "other"]
EVENT_TYPES = ["court_date", "filing_deadline", "meeting", "reminder"]
INVOICE_STATUSES = ["draft", "sent", "paid", "overdue"]

# Uploaded documents live on disk (not in the DB), namespaced per case.
DOCUMENTS_DIR = os.path.join(INSTANCE_DIR, "documents")
os.makedirs(DOCUMENTS_DIR, exist_ok=True)

# Never allow executable uploads — a law office cannot risk malware.
BLOCKED_EXTENSIONS = {
    "exe", "bat", "cmd", "com", "scr", "msi", "ps1", "vbs", "js", "jar",
    "dll", "sys", "reg", "lnk",
}

# Backups: database + encryption key copied to BACKUP_DIR. The office should
# ALSO copy backups offsite (USB drive taken home weekly — see MAINTENANCE.md).
BACKUP_DIR_FILE = os.path.join(INSTANCE_DIR, "backup_dir.txt")


def get_backup_dir():
    """Backup directory: configurable, defaults to instance/backups/."""
    if os.path.exists(BACKUP_DIR_FILE):
        with open(BACKUP_DIR_FILE, "r") as f:
            d = f.read().strip()
        if d:
            os.makedirs(d, exist_ok=True)
            return d
    default = os.path.join(INSTANCE_DIR, "backups")
    os.makedirs(default, exist_ok=True)
    return default


BACKUP_KEEP_COUNT = 30  # keep the 30 most recent backups, delete older ones

# RPC 1.15A/B: trust account and financial records must be retained a minimum
# of 7 years. No financial/billing records may be destroyed before then.
# (v1 has no billing module yet — the billing build MUST call retention_ok()
# before allowing any financial record deletion.)
RETENTION_YEARS_FINANCIAL = 7


def retention_ok(record_date_iso):
    """True only if a financial record is old enough to be destroyed.

    record_date_iso: ISO date string of the record (e.g. '2019-03-04').
    Returns False for missing/unparseable dates (fail closed: do not delete).
    """
    if not record_date_iso:
        return False
    try:
        record_date = datetime.fromisoformat(str(record_date_iso)[:10])
    except ValueError:
        return False
    age = datetime.now(timezone.utc) - record_date
    return age >= timedelta(days=365 * RETENTION_YEARS_FINANCIAL)


# ----------------------------------------------------------------------------
# Database
# ----------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    full_name TEXT,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    role TEXT NOT NULL DEFAULT 'staff',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    address TEXT,
    date_of_birth TEXT,
    spouse_name TEXT,
    spouse_dob TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS children (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    date_of_birth TEXT
);
CREATE TABLE IF NOT EXISTS cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_number TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    client_id INTEGER REFERENCES clients(id),
    case_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    date_opened TEXT,
    date_closed TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    user_id INTEGER,
    username TEXT,
    action TEXT NOT NULL,
    details TEXT
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
-- Opposing parties, per case. Used by the conflict checker (RPC 1.7):
-- before a new client is added, their name is searched against all clients
-- AND all opposing parties. A match triggers a hard-stop warning.
CREATE TABLE IF NOT EXISTS opposing_parties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    role TEXT,
    notes TEXT,
    created_at TEXT NOT NULL
);
-- Document metadata. Files live on disk under instance/documents/<case_id>/;
-- only metadata lives here. Uploading a new version of the same file keeps
-- the old file (version column increments).
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    original_name TEXT NOT NULL,
    stored_name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'other',
    file_size INTEGER NOT NULL DEFAULT 0,
    version INTEGER NOT NULL DEFAULT 1,
    uploaded_by TEXT,
    notes TEXT,
    uploaded_at TEXT NOT NULL
);
-- Calendar events. Filing deadlines and court dates are malpractice-critical:
-- the dashboard surfaces anything due within 7 days.
CREATE TABLE IF NOT EXISTS calendar_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER REFERENCES cases(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    event_type TEXT NOT NULL DEFAULT 'reminder',
    event_date TEXT NOT NULL,
    event_time TEXT,
    description TEXT,
    completed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
-- Time entries (billable hours). Financial records: RPC 1.15B requires
-- 7-year retention. Deletion MUST go through retention_ok() — fail closed.
CREATE TABLE IF NOT EXISTS time_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    entry_date TEXT NOT NULL,
    hours REAL NOT NULL,
    description TEXT NOT NULL,
    rate REAL NOT NULL DEFAULT 0,
    user_id INTEGER,
    invoiced INTEGER NOT NULL DEFAULT 0,
    invoice_id INTEGER REFERENCES invoices(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_number TEXT UNIQUE NOT NULL,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    issue_date TEXT NOT NULL,
    due_date TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    notes TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS invoice_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    entry_date TEXT,
    description TEXT NOT NULL,
    hours REAL NOT NULL DEFAULT 0,
    rate REAL NOT NULL DEFAULT 0,
    amount REAL NOT NULL DEFAULT 0
);
-- Backup log. Each automated or manual backup records here.
CREATE TABLE IF NOT EXISTS backups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    filename TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'ok',
    notes TEXT
);
-- Trust accounting (IOLTA / RPC 1.15A/B). Amounts are stored as INTEGER
-- cents — never floats — to avoid rounding errors. Balances are ALWAYS
-- computed from transactions; no balance is ever stored. Transactions are
-- IMMUTABLE: there is no UI to edit or delete them. Corrections are made
-- via reversing entries (a new transaction with reverses_id pointing at
-- the original). Trust transactions are financial records: 7-year retention
-- (retention_ok) applies; deletion is refused, period.
CREATE TABLE IF NOT EXISTS trust_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    bank_name TEXT,
    account_number TEXT,
    notes TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trust_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES trust_accounts(id),
    client_id INTEGER NOT NULL REFERENCES clients(id),
    case_id INTEGER REFERENCES cases(id),
    txn_date TEXT NOT NULL,
    txn_type TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    description TEXT NOT NULL,
    reference TEXT,
    reverses_id INTEGER REFERENCES trust_transactions(id),
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL
);
-- txn_type values:
--   deposit       : money in for a client (+balance)
--   disbursement  : money out for a client (-balance)
--   transfer_out  : moved to another client's ledger (-balance, linked via transfer_group)
--   transfer_in   : moved from another client's ledger (+balance, linked via transfer_group)
--   reversal      : corrects an earlier transaction (reverses_id set; signed to offset it)
-- Monthly reconciliation records (WSBA requires reconciliation records).
CREATE TABLE IF NOT EXISTS trust_reconciliations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES trust_accounts(id),
    statement_date TEXT NOT NULL,
    statement_balance_cents INTEGER NOT NULL,
    book_balance_cents INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    reconciled_by INTEGER REFERENCES users(id),
    reconciled_at TEXT,
    notes TEXT,
    created_at TEXT NOT NULL
);
-- Tamper-evident audit log (RPC 1.6 / WSBA Op 2215): the audit trail is
-- append-only. These triggers make UPDATE/DELETE on audit_log fail at the
-- database level, so no code path or SQL console can alter history.
CREATE TRIGGER IF NOT EXISTS audit_no_update
BEFORE UPDATE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only: updates are not allowed');
END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete
BEFORE DELETE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only: deletes are not allowed');
END;
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, timeout=30)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        # WAL mode: better concurrent read/write for multi-machine office use.
        # (Solo firm, 2-4 machines — SQLite + WAL is fine here.)
        g.db.execute("PRAGMA journal_mode = WAL")
        g.db.execute("PRAGMA synchronous = NORMAL")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript(SCHEMA)
    db.commit()

    # Ensure role / is_active exist on users (added in v1.4.0 for RBAC).
    ucols = [r["name"] for r in db.execute("PRAGMA table_info(users)").fetchall()]
    if "role" not in ucols:
        db.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'staff'")
        db.execute("UPDATE users SET role = 'admin' WHERE username = 'admin'")
        db.execute("UPDATE users SET role = 'staff' WHERE role IS NULL OR role = ''")
        db.commit()
    if "is_active" not in ucols:
        db.execute("ALTER TABLE users ADD COLUMN is_active INTEGER DEFAULT 1")
        db.execute("UPDATE users SET is_active = 1 WHERE is_active IS NULL")
        db.commit()

    # Ensure SSN column exists on older databases (encrypted at rest, RCW 19.255.010)
    cols = [r["name"] for r in db.execute("PRAGMA table_info(clients)").fetchall()]
    if "ssn" not in cols:
        db.execute("ALTER TABLE clients ADD COLUMN ssn TEXT DEFAULT ''")
        db.commit()

    # Ensure entry_date exists on invoice_items (for PDF line-item dates).
    # Backfill: time-entry items had the date baked into the description
    # as "YYYY-MM-DD — description"; split it out.
    icols = [r["name"] for r in db.execute("PRAGMA table_info(invoice_items)").fetchall()]
    if "entry_date" not in icols:
        db.execute("ALTER TABLE invoice_items ADD COLUMN entry_date TEXT")
        for row in db.execute("SELECT id, description FROM invoice_items").fetchall():
            desc = row["description"] or ""
            m = re.match(r"^(\d{4}-\d{2}-\d{2})\s*[—–-]\s*(.*)$", desc, re.DOTALL)
            if m:
                db.execute(
                    "UPDATE invoice_items SET entry_date = ?, description = ? WHERE id = ?",
                    (m.group(1), m.group(2), row["id"]),
                )
        db.commit()

    # One-time migration: encrypt any plaintext sensitive fields written
    # before field-level encryption was enabled.
    _migrate_field_encryption(db)

    # Seed default admin on first run
    row = db.execute("SELECT COUNT(*) AS c FROM users").fetchone()
    if row["c"] == 0:
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO users (username, password_hash, full_name, "
            "must_change_password, role, is_active, created_at) VALUES (?, ?, ?, 1, 'admin', 1, ?)",
            ("admin", generate_password_hash("changeme123"), "Administrator", now),
        )
        db.commit()
        print("=" * 60)
        print("  FIRST RUN: default admin account created")
        print("  Username: admin")
        print("  Password: changeme123")
        print("  You will be forced to change this password on first login.")
        print("=" * 60)


def _migrate_field_encryption(db):
    """Encrypt any plaintext sensitive fields.

    Runs on every startup (idempotent): any value that does not look like a
    Fernet token gets encrypted. This covers databases created before
    field-level encryption existed, and any plaintext that slipped in through
    a manual SQL edit or backup restore.
    """
    # (table, column, id-column) — names are internal constants, not user input.
    targets = [
        ("clients", "date_of_birth", "id"),
        ("clients", "spouse_dob", "id"),
        ("clients", "ssn", "id"),
        ("children", "date_of_birth", "id"),
    ]
    migrated = 0
    for table, col, idcol in targets:
        for r in db.execute(
            f"SELECT {idcol} AS i, {col} AS v FROM {table}"
        ).fetchall():
            v = r["v"]
            if v and not looks_encrypted(v):
                db.execute(
                    f"UPDATE {table} SET {col} = ? WHERE {idcol} = ?",
                    (encrypt_value(v), r["i"]),
                )
                migrated += 1
    db.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('field_encryption', '1')"
    )
    db.commit()
    if migrated:
        print(f"  Encrypted {migrated} plaintext field(s).")


# ----------------------------------------------------------------------------
# Audit logging
# ----------------------------------------------------------------------------
def audit(action, details=""):
    """Record an action in the audit log. Never put DOBs/SSNs in details."""
    db = get_db()
    db.execute(
        "INSERT INTO audit_log (timestamp, user_id, username, action, details)"
        " VALUES (?, ?, ?, ?, ?)",
        (
            datetime.now(timezone.utc).isoformat(),
            session.get("user_id"),
            session.get("username"),
            action,
            details,
        ),
    )
    db.commit()


# ----------------------------------------------------------------------------
# Trust accounting helpers (IOLTA / RPC 1.15A/B)
# ----------------------------------------------------------------------------
def dollars_to_cents(s):
    """Parse a dollar string like '1,234.56' into integer cents. Returns None on bad input."""
    if s is None:
        return None
    s = str(s).strip().replace(",", "").replace("$", "")
    if not s:
        return None
    try:
        # Reject anything that isn't a plain number with at most 2 decimals
        if not re.match(r"^\d+(\.\d{1,2})?$", s):
            return None
        whole, _, frac = s.partition(".")
        cents = int(whole) * 100 + int((frac + "00")[:2])
        return cents
    except (ValueError, TypeError):
        return None


def cents_to_str(cents):
    """Format integer cents as a dollar string, e.g. 123456 -> '1,234.56'."""
    cents = int(cents or 0)
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}{cents // 100:,}.{cents % 100:02d}"


# Transaction types that ADD to a client's balance vs REMOVE from it.
TRUST_CREDIT_TYPES = ("deposit", "transfer_in", "reversal_credit")
TRUST_DEBIT_TYPES = ("disbursement", "transfer_out", "reversal_debit")


def client_trust_balance(db, account_id, client_id):
    """Current balance (cents) for one client in one trust account. Computed, never stored."""
    row = db.execute(
        "SELECT COALESCE(SUM(CASE WHEN txn_type IN ('deposit','transfer_in','reversal_credit')"
        " THEN amount_cents ELSE -amount_cents END), 0) AS bal"
        " FROM trust_transactions WHERE account_id = ? AND client_id = ?",
        (account_id, client_id),
    ).fetchone()
    return int(row["bal"])


def account_trust_balance(db, account_id):
    """Total book balance (cents) of a trust account = sum of all client ledgers."""
    row = db.execute(
        "SELECT COALESCE(SUM(CASE WHEN txn_type IN ('deposit','transfer_in','reversal_credit')"
        " THEN amount_cents ELSE -amount_cents END), 0) AS bal"
        " FROM trust_transactions WHERE account_id = ?",
        (account_id,),
    ).fetchone()
    return int(row["bal"])


def trust_client_balances(db, account_id):
    """Per-client balances for an account: list of dicts with client info + balance cents."""
    rows = db.execute(
        "SELECT t.client_id, cl.first_name, cl.last_name,"
        " COALESCE(SUM(CASE WHEN t.txn_type IN ('deposit','transfer_in','reversal_credit')"
        " THEN t.amount_cents ELSE -t.amount_cents END), 0) AS bal"
        " FROM trust_transactions t"
        " JOIN clients cl ON t.client_id = cl.id"
        " WHERE t.account_id = ?"
        " GROUP BY t.client_id, cl.first_name, cl.last_name"
        " ORDER BY cl.last_name, cl.first_name",
        (account_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def log_trust_txn(db, account_id, client_id, case_id, txn_date, txn_type,
                 amount_cents, description, reference="", reverses_id=None):
    """Insert an immutable trust transaction. Returns the new id."""
    now = datetime.now(timezone.utc).isoformat()
    cur = db.execute(
        "INSERT INTO trust_transactions (account_id, client_id, case_id, txn_date,"
        " txn_type, amount_cents, description, reference, reverses_id, created_by,"
        " created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            account_id, client_id, case_id or None, txn_date, txn_type,
            amount_cents, description, reference or "", reverses_id,
            session.get("user_id"), now,
        ),
    )
    return cur.lastrowid


# ----------------------------------------------------------------------------
# Backups
# ----------------------------------------------------------------------------
def do_backup(manual=False):
    """Copy the database + encryption key to the backup directory.

    Returns (ok, message). Keeps the newest BACKUP_KEEP_COUNT backups and
    deletes older ones. Logs the result to the backups table and audit log.
    """
    backup_dir = get_backup_dir()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    kind = "manual" if manual else "auto"
    base = f"lawfirm-backup-{stamp}-{kind}"
    db_backup = os.path.join(backup_dir, base + ".db")
    key_backup = os.path.join(backup_dir, base + ".key")
    notes = ""
    try:
        # SQLite online backup: copy via the backup API so we get a
        # consistent snapshot even if the app is running.
        src = sqlite3.connect(DB_PATH)
        dst = sqlite3.connect(db_backup)
        src.backup(dst)
        src.close()
        dst.close()
        # The encryption key MUST travel with the database, or encrypted
        # fields (SSNs, DOBs) become unrecoverable.
        key_src = os.path.join(INSTANCE_DIR, "data.key")
        if os.path.exists(key_src):
            shutil.copy2(key_src, key_backup)
        else:
            notes = "WARNING: data.key not found — encrypted fields may be unrecoverable!"
        size = os.path.getsize(db_backup)
        ok, msg = True, f"Backup saved to {db_backup}"
    except Exception as e:  # noqa: BLE001 — report, don't crash the app
        ok, msg = False, f"Backup FAILED: {e}"
        size = 0

    # Prune old backups (keep newest N)
    try:
        files = sorted(
            f for f in os.listdir(backup_dir)
            if f.startswith("lawfirm-backup-") and f.endswith(".db")
        )
        for old in files[:-BACKUP_KEEP_COUNT]:
            try:
                os.remove(os.path.join(backup_dir, old))
                kb = os.path.join(backup_dir, old[:-3] + ".key")
                if os.path.exists(kb):
                    os.remove(kb)
            except OSError:
                pass
    except OSError:
        pass

    # Log it
    try:
        db = get_db()
        db.execute(
            "INSERT INTO backups (timestamp, filename, size_bytes, status, notes)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                os.path.basename(db_backup) if ok else base + ".db",
                size,
                "ok" if ok else "failed",
                (msg + " " + notes).strip(),
            ),
        )
        db.commit()
    except Exception:  # noqa: BLE001 — backup must not break the app
        pass
    return ok, msg


def backup_scheduler():
    """Background thread: ensure at least one backup per 24 hours."""
    while True:
        try:
            time.sleep(3600)  # check hourly
            with app.app_context():
                db = get_db()
                row = db.execute(
                    "SELECT timestamp FROM backups WHERE status='ok'"
                    " ORDER BY id DESC LIMIT 1"
                ).fetchone()
                needs_backup = True
                if row and row["timestamp"]:
                    try:
                        last = datetime.fromisoformat(row["timestamp"])
                        if last.tzinfo is None:
                            last = last.replace(tzinfo=timezone.utc)
                        needs_backup = (
                            datetime.now(timezone.utc) - last > timedelta(hours=24)
                        )
                    except ValueError:
                        pass
                if needs_backup:
                    ok, msg = do_backup(manual=False)
                    print(f"  [backup] {msg}")
        except Exception as e:  # noqa: BLE001 — scheduler must never die loudly
            print(f"  [backup] scheduler error: {e}")


def start_backup_scheduler():
    t = threading.Thread(target=backup_scheduler, daemon=True,
                         name="backup-scheduler")
    t.start()


# ----------------------------------------------------------------------------
# Software updates
# ----------------------------------------------------------------------------
def get_app_version():
    """Read the bundled VERSION file. Falls back to 'dev' when running unpackaged."""
    try:
        with open(os.path.join(BASE_DIR, "VERSION"), "r") as f:
            return f.read().strip()
    except OSError:
        return "0.0-dev"


APP_VERSION = get_app_version()

GITHUB_REPO = "needhamgarrett95-ux/farhollow-lawfirm"
UPDATE_CHECK_INTERVAL = 6 * 3600  # every 6 hours
INSTALLER_ASSET_NAME = "LawFirmHostSetup.exe"
# Minimum plausible installer size (bytes). Anything smaller failed verification.
INSTALLER_MIN_SIZE = 5_000_000

UPDATE_INFO = {
    "available": False,
    "latest_version": None,
    "release_url": None,
    "release_notes": "",
    "asset_url": None,
    "asset_size": None,
    "checked_at": None,
    "error": None,
}
_update_lock = threading.Lock()


def parse_version(v):
    """Extract a comparable numeric tuple from 'v1.2.0', '1.2.0', '1.0-dev+abc'."""
    import re
    m = re.search(r"(\d+(?:\.\d+)*)", v or "")
    if not m:
        return ()
    return tuple(int(x) for x in m.group(1).split("."))


def _versions_equal_or_newer(current, latest):
    """True if current >= latest, treating '1.2' and '1.2.0' as equal."""
    c, l = parse_version(current), parse_version(latest)
    if not l:
        return True  # unparseable latest: don't offer a phantom update
    n = max(len(c), len(l))
    c += (0,) * (n - len(c))
    l += (0,) * (n - len(l))
    return c >= l


def check_for_updates():
    """Query the GitHub Releases API once and refresh UPDATE_INFO. Never raises."""
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
            headers={
                "User-Agent": "FarhollowLawFirm-Updater",
                "Accept": "application/vnd.github+json",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        latest_tag = (data.get("tag_name") or "").strip()
        asset_url, asset_size = None, None
        for asset in data.get("assets", []) or []:
            if asset.get("name") == INSTALLER_ASSET_NAME:
                asset_url = asset.get("browser_download_url")
                asset_size = asset.get("size")
                break
        with _update_lock:
            UPDATE_INFO.update({
                "latest_version": latest_tag.lstrip("v") or None,
                "release_url": data.get("html_url"),
                "release_notes": data.get("body") or "",
                "asset_url": asset_url,
                "asset_size": asset_size,
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "error": None,
            })
            cur = parse_version(APP_VERSION)
            lat = parse_version(latest_tag)
            UPDATE_INFO["available"] = bool(lat) and not _versions_equal_or_newer(
                APP_VERSION, latest_tag)
        if UPDATE_INFO["available"]:
            print(f"  [update] v{UPDATE_INFO['latest_version']} available "
                  f"(running v{APP_VERSION})")
    except Exception as e:  # noqa: BLE001 — offline office? just record it
        with _update_lock:
            UPDATE_INFO["error"] = str(e)[:200]
        print(f"  [update] check failed: {e}")


def update_check_scheduler():
    """Background thread: check for updates on startup, then every 6 hours."""
    time.sleep(60)  # let the server finish starting first
    while True:
        check_for_updates()
        time.sleep(UPDATE_CHECK_INTERVAL)


def start_update_checker():
    t = threading.Thread(target=update_check_scheduler, daemon=True,
                         name="update-checker")
    t.start()


def run_self_update(asset_url):
    """Download the new installer, back up first, then relaunch via a helper.

    Only used when running as a packaged Windows exe. Returns (ok, message).
    On success the current process exits shortly after returning — the helper
    batch file waits, installs silently, and restarts the server.
    instance/ (database, keys, documents, backups) is never touched.
    """
    update_dir = os.path.join(INSTANCE_DIR, "update")
    os.makedirs(update_dir, exist_ok=True)
    installer_path = os.path.join(update_dir, INSTALLER_ASSET_NAME)

    # 1. Pre-update backup — data safety first. If this fails, stop.
    ok, msg = do_backup(manual=True)
    try:
        audit("update_backup", f"Pre-update backup before self-update: {msg}")
    except Exception:
        pass
    if not ok:
        return False, (
            "Update cancelled: the pre-update backup failed, so nothing was "
            f"changed. ({msg})"
        )

    # 2. Download the installer with sanity checks.
    try:
        req = urllib.request.Request(
            asset_url, headers={"User-Agent": "FarhollowLawFirm-Updater"})
        with urllib.request.urlopen(req, timeout=180) as resp:
            with open(installer_path, "wb") as f:
                shutil.copyfileobj(resp, f, length=1024 * 256)
    except Exception as e:  # noqa: BLE001
        return False, (
            "Update cancelled: the download failed, so nothing was changed. "
            f"({e})"
        )
    try:
        size = os.path.getsize(installer_path)
        with open(installer_path, "rb") as f:
            magic = f.read(2)
    except OSError as e:
        return False, f"Update cancelled: could not verify download ({e})."
    if size < INSTALLER_MIN_SIZE or magic != b"MZ":
        try:
            os.remove(installer_path)
        except OSError:
            pass
        return False, (
            "Update cancelled: the downloaded file failed verification "
            "(wrong size or not a Windows installer). Nothing was changed."
        )

    # 3. Helper batch file: wait for this process to exit, install silently,
    #    restart the server. The installer upgrades in place (same AppId);
    #    instance/ is never removed on upgrade.
    install_dir = os.path.dirname(os.path.abspath(sys.executable))
    server_exe = os.path.join(install_dir, "LawFirmServer.exe")
    bat_path = os.path.join(update_dir, "apply-update.bat")
    log_path = os.path.join(update_dir, "update.log")
    latest = UPDATE_INFO.get("latest_version") or "new version"
    with open(bat_path, "w") as f:
        f.write(
            "@echo off\r\n"
            f'echo [%date% %time%] Updating to v{latest} >> "{log_path}"\r\n'
            "echo [%date% %time%] Waiting for server to stop... "
            f'>> "{log_path}"\r\n'
            "timeout /t 12 /nobreak >nul\r\n"
            'echo [%date% %time%] Running installer... '
            f'>> "{log_path}"\r\n'
            f'start "" /wait "{installer_path}" /VERYSILENT /NORESTART '
            f'/SUPPRESSMSGBOXES >> "{log_path}" 2>&1\r\n'
            f'echo [%date% %time%] Installer finished (code %errorlevel%) '
            f'>> "{log_path}"\r\n'
            'echo [%date% %time%] Restarting server... '
            f'>> "{log_path}"\r\n'
            f'start "" "{server_exe}"\r\n'
            f'del "{installer_path}"\r\n'
            'del "%~f0"\r\n'
        )
    try:
        audit("update_started",
              f"Self-update to v{latest} started; installer verified "
              f"({size} bytes). Server restarting.")
    except Exception:
        pass

    # 4. Launch the helper detached, then get out of the installer's way.
    try:
        subprocess.Popen(
            ["cmd", "/c", bat_path],
            creationflags=(subprocess.DETACHED_PROCESS
                           | subprocess.CREATE_NEW_PROCESS_GROUP),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, cwd=update_dir,
        )
    except Exception as e:  # noqa: BLE001
        return False, (
            "Update cancelled: could not start the installer "
            f"({e}). Nothing was changed."
        )
    threading.Timer(2.0, lambda: os._exit(0)).start()
    return True, (
        "Update started — the server will shut down and restart with the new "
        "version in about a minute. Your data is safe (a backup was made first)."
    )


# ----------------------------------------------------------------------------
# Auth helpers
# ----------------------------------------------------------------------------
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        # Refresh role + active status from the database on every request so
        # admin changes (role change, deactivation) take effect immediately.
        db = get_db()
        me = db.execute(
            "SELECT role, is_active FROM users WHERE id = ?",
            (session["user_id"],),
        ).fetchone()
        if not me or not me["is_active"]:
            session.clear()
            flash("Your account is no longer active. Please contact the administrator.", "warning")
            return redirect(url_for("login"))
        session["role"] = me["role"] or "staff"
        # Inactivity timeout
        last = session.get("last_activity")
        if last:
            last_dt = datetime.fromisoformat(last)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            idle = datetime.now(timezone.utc) - last_dt
            if idle > timedelta(minutes=SESSION_TIMEOUT_MINUTES):
                session.clear()
                flash("You were logged out due to inactivity.", "warning")
                return redirect(url_for("login"))
        session["last_activity"] = datetime.now(timezone.utc).isoformat()
        # Forced password change
        if session.get("must_change_password") and request.endpoint not in (
            "change_password",
            "logout",
            "static",
        ):
            return redirect(url_for("change_password"))
        return f(*args, **kwargs)

    return decorated


def new_csrf_token():
    token = secrets.token_hex(16)
    session["csrf_token"] = token
    return token


def check_csrf():
    form_token = request.form.get("csrf_token", "")
    session_token = session.get("csrf_token", "")
    if not form_token or not session_token or form_token != session_token:
        abort(400, description="Invalid form submission. Please try again.")


@app.before_request
def ensure_csrf():
    if "csrf_token" not in session:
        new_csrf_token()


def is_admin():
    """True when the logged-in user has the admin role."""
    return session.get("role") == "admin"


def admin_required(f):
    """Admin-only route. Includes the login check."""

    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if session.get("role") != "admin":
            abort(403, description="Only administrators can access this page.")
        return f(*args, **kwargs)

    return decorated


def role_required(*roles):
    """Route restricted to the given roles (e.g. 'admin', 'attorney')."""

    def decorator(f):
        @wraps(f)
        @login_required
        def decorated(*args, **kwargs):
            if session.get("role") not in roles:
                abort(403, description="Your role does not have access to this page.")
            return f(*args, **kwargs)

        return decorated

    return decorator


def can_delete(f):
    """Only admin and attorney roles may delete records. Staff is blocked."""

    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if session.get("role") not in ("admin", "attorney"):
            abort(403, description="Your role does not allow deleting records.")
        return f(*args, **kwargs)

    return decorated


@app.template_filter("cents")
def _cents_filter(value):
    """Format integer cents as dollars in templates: {{ 123456|cents }} -> 1,234.56"""
    return cents_to_str(value)


@app.context_processor
def inject_update_info():
    """Make the app version and update status available in every template."""
    with _update_lock:
        info = dict(UPDATE_INFO)
    return {
        "app_version": APP_VERSION,
        "is_admin": is_admin(),
        "user_role": session.get("role", "staff"),
        # The banner is admin-only; the footer version tag is for everyone
        # (it doubles as the "server updated" notice for office computers).
        "update_available": bool(info.get("available")) and is_admin(),
        "update_info": info,
    }


# ----------------------------------------------------------------------------
# PWA routes (service worker needs root scope; offline fallback page)
# ----------------------------------------------------------------------------
@app.route("/sw.js")
def service_worker():
    resp = send_file("static/sw.js")
    resp.headers["Content-Type"] = "application/javascript"
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.route("/offline.html")
def offline_page():
    return send_file("static/offline.html")


@app.route("/api/version")
def api_version():
    """Return the running server version. No login required — the desktop
    launcher polls this to detect available updates."""
    return jsonify({"version": APP_VERSION})


# ----------------------------------------------------------------------------
# Auth routes
# ----------------------------------------------------------------------------
@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        check_csrf()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            if not user["is_active"]:
                flash("This account has been deactivated. Please contact the administrator.", "error")
                return render_template("login.html")
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"] or "staff"
            session["must_change_password"] = bool(user["must_change_password"])
            session["last_activity"] = datetime.now(timezone.utc).isoformat()
            new_csrf_token()
            audit("login", "User logged in")
            if user["must_change_password"]:
                flash("Please change your password before continuing.", "warning")
                return redirect(url_for("change_password"))
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    if "user_id" in session:
        audit("logout", "User logged out")
    session.clear()
    return redirect(url_for("login"))


@app.route("/change-password", methods=["GET", "POST"])
def change_password():
    if "user_id" not in session:
        return redirect(url_for("login"))
    if request.method == "POST":
        check_csrf()
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE id = ?", (session["user_id"],)
        ).fetchone()
        if not check_password_hash(user["password_hash"], current):
            flash("Current password is incorrect.", "error")
        elif len(new) < 8:
            flash("New password must be at least 8 characters.", "error")
        elif new != confirm:
            flash("New passwords do not match.", "error")
        else:
            db.execute(
                "UPDATE users SET password_hash = ?, must_change_password = 0"
                " WHERE id = ?",
                (generate_password_hash(new), user["id"]),
            )
            db.commit()
            session["must_change_password"] = False
            audit("password_change", "User changed their password")
            flash("Password changed successfully.", "success")
            return redirect(url_for("dashboard"))
    return render_template("change_password.html")


# ----------------------------------------------------------------------------
# User management (admin only)
# ----------------------------------------------------------------------------
VALID_ROLES = ("admin", "attorney", "staff")


def _user_last_login(db, user_id):
    row = db.execute(
        "SELECT MAX(timestamp) AS t FROM audit_log WHERE user_id = ? AND action = 'login'",
        (user_id,),
    ).fetchone()
    return row["t"] if row else None


def _gen_temp_password():
    import secrets as _secrets
    import string as _string
    alphabet = _string.ascii_letters + _string.digits
    return "DGM-" + "".join(_secrets.choice(alphabet) for _ in range(8))


@app.route("/users")
@admin_required
def user_list():
    db = get_db()
    users = db.execute(
        "SELECT * FROM users ORDER BY is_active DESC, username"
    ).fetchall()
    users = [
        dict(u, last_login=_user_last_login(db, u["id"])) for u in users
    ]
    return render_template("users.html", users=users)


@app.route("/users/new", methods=["GET", "POST"])
@admin_required
def user_new():
    if request.method == "POST":
        check_csrf()
        username = request.form.get("username", "").strip().lower()
        full_name = request.form.get("full_name", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "staff")
        db = get_db()
        if not username or not password or not full_name:
            flash("Username, full name, and password are all required.", "error")
        elif role not in VALID_ROLES:
            flash("Invalid role selected.", "error")
        elif len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
        elif db.execute(
            "SELECT 1 FROM users WHERE username = ?", (username,)
        ).fetchone():
            flash("That username is already taken.", "error")
        else:
            now = datetime.now(timezone.utc).isoformat()
            db.execute(
                "INSERT INTO users (username, password_hash, full_name, "
                "must_change_password, role, is_active, created_at)"
                " VALUES (?, ?, ?, 1, ?, 1, ?)",
                (username, generate_password_hash(password), full_name, role, now),
            )
            db.commit()
            audit("user_created", f"Created user '{username}' with role '{role}'")
            flash(f"User '{username}' created. They must change their password on first login.", "success")
            return redirect(url_for("user_list"))
    return render_template("user_form.html", user=None, roles=VALID_ROLES)


@app.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@admin_required
def user_edit(user_id):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        abort(404)
    if request.method == "POST":
        check_csrf()
        full_name = request.form.get("full_name", "").strip()
        role = request.form.get("role", "staff")
        is_active = 1 if request.form.get("is_active") else 0
        if not full_name:
            flash("Full name is required.", "error")
        elif role not in VALID_ROLES:
            flash("Invalid role selected.", "error")
        elif user["id"] == session["user_id"] and role != "admin":
            flash("You cannot remove your own admin role.", "error")
        elif user["id"] == session["user_id"] and not is_active:
            flash("You cannot deactivate your own account.", "error")
        elif (
            user["role"] == "admin"
            and role != "admin"
            and _count_active_admins(db) <= 1
        ):
            flash("You cannot demote the last active admin.", "error")
        else:
            changes = []
            if full_name != user["full_name"]:
                changes.append(f"name -> '{full_name}'")
            if role != user["role"]:
                changes.append(f"role {user['role']} -> {role}")
            if is_active != user["is_active"]:
                changes.append("deactivated" if not is_active else "reactivated")
            db.execute(
                "UPDATE users SET full_name = ?, role = ?, is_active = ? WHERE id = ?",
                (full_name, role, is_active, user["id"]),
            )
            db.commit()
            audit("user_updated", f"Updated user '{user['username']}': " + (", ".join(changes) or "no changes"))
            flash(f"User '{user['username']}' updated.", "success")
            return redirect(url_for("user_list"))
        # Re-fetch so the form re-renders with submitted values on error
        user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return render_template("user_form.html", user=user, roles=VALID_ROLES)


@app.route("/users/<int:user_id>/reset-password", methods=["POST"])
@admin_required
def user_reset_password(user_id):
    check_csrf()
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        abort(404)
    temp = _gen_temp_password()
    db.execute(
        "UPDATE users SET password_hash = ?, must_change_password = 1 WHERE id = ?",
        (generate_password_hash(temp), user["id"]),
    )
    db.commit()
    audit("user_password_reset", f"Reset password for user '{user['username']}'")
    flash(
        f"Temporary password for '{user['username']}': {temp} — "
        "write it down now, it will not be shown again. They must change it on next login.",
        "warning",
    )
    return redirect(url_for("user_list"))


@app.route("/users/<int:user_id>/deactivate", methods=["POST"])
@admin_required
def user_deactivate(user_id):
    check_csrf()
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        abort(404)
    if user["id"] == session["user_id"]:
        flash("You cannot deactivate your own account.", "error")
        return redirect(url_for("user_list"))
    if user["role"] == "admin" and _count_active_admins(db) <= 1:
        flash("You cannot deactivate the last active admin.", "error")
        return redirect(url_for("user_list"))
    db.execute("UPDATE users SET is_active = 0 WHERE id = ?", (user["id"],))
    db.commit()
    audit("user_deactivated", f"Deactivated user '{user['username']}'")
    flash(f"User '{user['username']}' deactivated.", "success")
    return redirect(url_for("user_list"))


@app.route("/users/<int:user_id>/reactivate", methods=["POST"])
@admin_required
def user_reactivate(user_id):
    check_csrf()
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        abort(404)
    db.execute("UPDATE users SET is_active = 1 WHERE id = ?", (user["id"],))
    db.commit()
    audit("user_reactivated", f"Reactivated user '{user['username']}'")
    flash(f"User '{user['username']}' reactivated.", "success")
    return redirect(url_for("user_list"))


def _count_active_admins(db):
    row = db.execute(
        "SELECT COUNT(*) AS c FROM users WHERE role = 'admin' AND is_active = 1"
    ).fetchone()
    return row["c"]


# ----------------------------------------------------------------------------
# Dashboard
# ----------------------------------------------------------------------------
@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    active_cases = db.execute(
        "SELECT c.*, cl.first_name, cl.last_name FROM cases c"
        " LEFT JOIN clients cl ON c.client_id = cl.id"
        " WHERE c.status = 'active' ORDER BY c.updated_at DESC LIMIT 10"
    ).fetchall()
    stats = {
        "active_cases": db.execute(
            "SELECT COUNT(*) AS c FROM cases WHERE status='active'"
        ).fetchone()["c"],
        "pending_cases": db.execute(
            "SELECT COUNT(*) AS c FROM cases WHERE status='pending'"
        ).fetchone()["c"],
        "total_clients": db.execute(
            "SELECT COUNT(*) AS c FROM clients"
        ).fetchone()["c"],
        "unpaid_invoices": db.execute(
            "SELECT COUNT(*) AS c FROM invoices WHERE status IN ('sent','overdue')"
        ).fetchone()["c"],
    }
    recent = db.execute(
        "SELECT * FROM audit_log ORDER BY id DESC LIMIT 10"
    ).fetchall()
    # Upcoming deadlines: not completed, due within 14 days. Anything within
    # 7 days is malpractice-critical and rendered red in the template.
    today = date.today().isoformat()
    soon = (date.today() + timedelta(days=14)).isoformat()
    deadlines = db.execute(
        "SELECT e.*, c.case_number, c.title FROM calendar_events e"
        " LEFT JOIN cases c ON e.case_id = c.id"
        " WHERE e.completed = 0 AND e.event_date >= ? AND e.event_date <= ?"
        " ORDER BY e.event_date, e.event_time",
        (today, soon),
    ).fetchall()
    overdue = db.execute(
        "SELECT e.*, c.case_number, c.title FROM calendar_events e"
        " LEFT JOIN cases c ON e.case_id = c.id"
        " WHERE e.completed = 0 AND e.event_date < ?"
        " ORDER BY e.event_date",
        (today,),
    ).fetchall()
    # Last backup status — shown prominently; a missing backup is a red flag.
    last_backup = db.execute(
        "SELECT * FROM backups ORDER BY id DESC LIMIT 1"
    ).fetchone()
    urgent_cutoff = (date.today() + timedelta(days=7)).isoformat()
    return render_template(
        "dashboard.html", stats=stats, active_cases=active_cases,
        recent=recent, deadlines=deadlines, overdue=overdue,
        last_backup=last_backup, today=today, urgent_cutoff=urgent_cutoff,
    )


# ----------------------------------------------------------------------------
# Clients
# ----------------------------------------------------------------------------
@app.route("/clients")
@login_required
def client_list():
    q = request.args.get("q", "").strip()
    db = get_db()
    if q:
        like = f"%{q}%"
        clients = db.execute(
            "SELECT * FROM clients WHERE first_name LIKE ? OR last_name LIKE ?"
            " ORDER BY last_name, first_name",
            (like, like),
        ).fetchall()
    else:
        clients = db.execute(
            "SELECT * FROM clients ORDER BY last_name, first_name"
        ).fetchall()
    return render_template("clients.html", clients=clients, q=q)


def find_conflicts(first_name, last_name, exclude_client_id=None):
    """Search existing clients and opposing parties for a name match.

    Returns a list of dicts: {kind, name, detail}. kind is 'client' or
    'opposing_party'. Matching is case-insensitive on first+last name.
    """
    fn = (first_name or "").strip().lower()
    ln = (last_name or "").strip().lower()
    if not fn and not ln:
        return []
    db = get_db()
    hits = []
    for c in db.execute("SELECT id, first_name, last_name FROM clients").fetchall():
        if exclude_client_id and c["id"] == exclude_client_id:
            continue
        if c["first_name"].strip().lower() == fn and c["last_name"].strip().lower() == ln:
            hits.append({
                "kind": "client",
                "name": f"{c['first_name']} {c['last_name']}",
                "detail": f"Existing client (id={c['id']})",
            })
    for p in db.execute(
        "SELECT p.first_name, p.last_name, p.role, c.case_number, c.title"
        " FROM opposing_parties p JOIN cases c ON p.case_id = c.id"
    ).fetchall():
        if p["first_name"].strip().lower() == fn and p["last_name"].strip().lower() == ln:
            hits.append({
                "kind": "opposing_party",
                "name": f"{p['first_name']} {p['last_name']}",
                "detail": f"Opposing party ({p['role'] or 'party'}) in case"
                          f" {p['case_number']}: {p['title']}",
            })
    return hits


@app.route("/clients/new", methods=["GET", "POST"])
@login_required
def client_new():
    if request.method == "POST":
        check_csrf()
        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()
        # RPC 1.7 conflict check: hard stop if the name matches an existing
        # client or an opposing party in any case. The user must explicitly
        # confirm before the record is created.
        if not request.form.get("conflict_confirmed"):
            hits = find_conflicts(first_name, last_name)
            if hits:
                form_data = {k: request.form.get(k, "") for k in (
                    "first_name", "last_name", "email", "phone", "address",
                    "date_of_birth", "spouse_name", "spouse_dob", "ssn",
                    "notes",
                )}
                audit("conflict_warning",
                      f"Conflict check flagged {len(hits)} match(es) for"
                      f" {first_name} {last_name}")
                return render_template(
                    "conflict_warning.html", conflicts=hits,
                    form_data=form_data,
                )
        now = datetime.now(timezone.utc).isoformat()
        db = get_db()
        cur = db.execute(
            "INSERT INTO clients (first_name, last_name, email, phone, address,"
            " date_of_birth, spouse_name, spouse_dob, ssn, notes, created_at,"
            " updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                first_name,
                last_name,
                request.form.get("email", "").strip(),
                request.form.get("phone", "").strip(),
                request.form.get("address", "").strip(),
                encrypt_value(request.form.get("date_of_birth", "").strip()),
                request.form.get("spouse_name", "").strip(),
                encrypt_value(request.form.get("spouse_dob", "").strip()),
                encrypt_value(request.form.get("ssn", "").strip()),
                request.form.get("notes", "").strip(),
                now,
                now,
            ),
        )
        db.commit()
        client_id = cur.lastrowid
        audit("client_create", f"Created client record (id={client_id})")
        flash("Client added.", "success")
        return redirect(url_for("client_detail", client_id=client_id))
    return render_template("client_form.html", client=None)


def _decrypt_client(row):
    """Return a dict copy of a client row with encrypted fields decrypted."""
    d = dict(row)
    for field in ("date_of_birth", "spouse_dob", "ssn"):
        d[field] = decrypt_value(d.get(field))
    return d


def _decrypt_child(row):
    d = dict(row)
    d["date_of_birth"] = decrypt_value(d.get("date_of_birth"))
    return d


@app.route("/clients/<int:client_id>")
@login_required
def client_detail(client_id):
    db = get_db()
    client = db.execute(
        "SELECT * FROM clients WHERE id = ?", (client_id,)
    ).fetchone()
    if not client:
        abort(404)
    client = _decrypt_client(client)
    kids = [
        _decrypt_child(k)
        for k in db.execute(
            "SELECT * FROM children WHERE client_id = ? ORDER BY name",
            (client_id,),
        ).fetchall()
    ]
    cases = db.execute(
        "SELECT * FROM cases WHERE client_id = ? ORDER BY updated_at DESC",
        (client_id,),
    ).fetchall()
    audit("client_view", f"Viewed client record (id={client_id})")
    return render_template(
        "client_detail.html", client=client, children=kids, cases=cases
    )


@app.route("/clients/<int:client_id>/edit", methods=["GET", "POST"])
@login_required
def client_edit(client_id):
    db = get_db()
    client = db.execute(
        "SELECT * FROM clients WHERE id = ?", (client_id,)
    ).fetchone()
    if not client:
        abort(404)
    if request.method == "POST":
        check_csrf()
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "UPDATE clients SET first_name=?, last_name=?, email=?, phone=?,"
            " address=?, date_of_birth=?, spouse_name=?, spouse_dob=?, ssn=?,"
            " notes=?, updated_at=? WHERE id=?",
            (
                request.form.get("first_name", "").strip(),
                request.form.get("last_name", "").strip(),
                request.form.get("email", "").strip(),
                request.form.get("phone", "").strip(),
                request.form.get("address", "").strip(),
                encrypt_value(request.form.get("date_of_birth", "").strip()),
                request.form.get("spouse_name", "").strip(),
                encrypt_value(request.form.get("spouse_dob", "").strip()),
                encrypt_value(request.form.get("ssn", "").strip()),
                request.form.get("notes", "").strip(),
                now,
                client_id,
            ),
        )
        db.commit()
        audit("client_update", f"Updated client record (id={client_id})")
        flash("Client updated.", "success")
        return redirect(url_for("client_detail", client_id=client_id))
    return render_template(
        "client_form.html", client=_decrypt_client(client))


@app.route("/clients/<int:client_id>/delete", methods=["POST"])
@can_delete
def client_delete(client_id):
    check_csrf()
    db = get_db()
    # Don't delete a client that still has cases
    n = db.execute(
        "SELECT COUNT(*) AS c FROM cases WHERE client_id = ?", (client_id,)
    ).fetchone()["c"]
    if n > 0:
        flash(
            "Cannot delete this client — they still have cases on file. "
            "Close or reassign the cases first.",
            "error",
        )
        return redirect(url_for("client_detail", client_id=client_id))
    db.execute("DELETE FROM children WHERE client_id = ?", (client_id,))
    db.execute("DELETE FROM clients WHERE id = ?", (client_id,))
    db.commit()
    audit("client_delete", f"Deleted client record (id={client_id})")
    flash("Client deleted.", "success")
    return redirect(url_for("client_list"))


@app.route("/clients/<int:client_id>/children/add", methods=["POST"])
@login_required
def child_add(client_id):
    check_csrf()
    name = request.form.get("name", "").strip()
    dob = request.form.get("date_of_birth", "").strip()
    if not name:
        flash("Child name is required.", "error")
    else:
        db = get_db()
        db.execute(
            "INSERT INTO children (client_id, name, date_of_birth)"
            " VALUES (?, ?, ?)",
            (client_id, name, encrypt_value(dob)),
        )
        db.commit()
        audit("child_add", f"Added child to client (id={client_id})")
        flash("Child added.", "success")
    return redirect(url_for("client_detail", client_id=client_id))


@app.route("/children/<int:child_id>/delete", methods=["POST"])
@can_delete
def child_delete(child_id):
    check_csrf()
    db = get_db()
    row = db.execute(
        "SELECT client_id FROM children WHERE id = ?", (child_id,)
    ).fetchone()
    if not row:
        abort(404)
    db.execute("DELETE FROM children WHERE id = ?", (child_id,))
    db.commit()
    audit("child_delete", f"Removed child (id={child_id})")
    flash("Child removed.", "success")
    return redirect(url_for("client_detail", client_id=row["client_id"]))


# ----------------------------------------------------------------------------
# Cases / matters
# ----------------------------------------------------------------------------
@app.route("/cases")
@login_required
def case_list():
    status = request.args.get("status", "active")
    db = get_db()
    if status == "all":
        cases = db.execute(
            "SELECT c.*, cl.first_name, cl.last_name FROM cases c"
            " LEFT JOIN clients cl ON c.client_id = cl.id"
            " ORDER BY c.updated_at DESC"
        ).fetchall()
    else:
        cases = db.execute(
            "SELECT c.*, cl.first_name, cl.last_name FROM cases c"
            " LEFT JOIN clients cl ON c.client_id = cl.id"
            " WHERE c.status = ? ORDER BY c.updated_at DESC",
            (status,),
        ).fetchall()
    return render_template("cases.html", cases=cases, status=status)


@app.route("/cases/new", methods=["GET", "POST"])
@login_required
def case_new():
    db = get_db()
    clients = db.execute(
        "SELECT id, first_name, last_name FROM clients"
        " ORDER BY last_name, first_name"
    ).fetchall()
    # Quick-add: pre-select client when coming from a client page (?client_id=N)
    preset_client = request.args.get("client_id", "").strip()
    # Suggest the next case number for the current year (YYYY-NNN)
    year = date.today().year
    last_num = db.execute(
        "SELECT case_number FROM cases WHERE case_number LIKE ?"
        " ORDER BY case_number DESC LIMIT 1",
        (f"{year}-%",),
    ).fetchone()
    if last_num:
        try:
            seq = int(last_num["case_number"].split("-", 1)[1]) + 1
        except (ValueError, IndexError):
            seq = 1
    else:
        seq = 1
    suggested_number = f"{year}-{seq:03d}"
    today = date.today().isoformat()
    if request.method == "POST":
        check_csrf()
        now = datetime.now(timezone.utc).isoformat()
        case_number = request.form.get("case_number", "").strip()
        if not case_number:
            flash("Case number is required.", "error")
            return render_template(
                "case_form.html", case=None, clients=clients,
                case_types=CASE_TYPES, statuses=CASE_STATUSES,
                preset_client=preset_client,
                suggested_number=suggested_number, today=today,
            )
        exists = db.execute(
            "SELECT id FROM cases WHERE case_number = ?", (case_number,)
        ).fetchone()
        if exists:
            flash("That case number is already in use.", "error")
            return render_template(
                "case_form.html", case=None, clients=clients,
                case_types=CASE_TYPES, statuses=CASE_STATUSES,
                preset_client=preset_client,
                suggested_number=suggested_number, today=today,
            )
        client_id = request.form.get("client_id", "").strip() or None
        case_type = request.form.get("case_type", "other")
        # Auto-generate a title if left blank: "Smith — Divorce"
        title = request.form.get("title", "").strip()
        if not title:
            if client_id:
                cl = db.execute(
                    "SELECT last_name FROM clients WHERE id = ?",
                    (client_id,),
                ).fetchone()
                cname = cl["last_name"] if cl else "New matter"
            else:
                cname = "New matter"
            title = f"{cname} — {case_type.capitalize()}"
        cur = db.execute(
            "INSERT INTO cases (case_number, title, client_id, case_type, status,"
            " date_opened, notes, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                case_number,
                title,
                client_id,
                case_type,
                request.form.get("status", "active"),
                request.form.get("date_opened", "").strip() or today,
                request.form.get("notes", "").strip(),
                now,
                now,
            ),
        )
        db.commit()
        case_id = cur.lastrowid
        audit("case_create", f"Created case {case_number} (id={case_id})")
        flash("Case added.", "success")
        return redirect(url_for("case_detail", case_id=case_id))
    return render_template(
        "case_form.html", case=None, clients=clients,
        case_types=CASE_TYPES, statuses=CASE_STATUSES,
        preset_client=preset_client, suggested_number=suggested_number,
        today=today,
    )


@app.route("/cases/<int:case_id>")
@login_required
def case_detail(case_id):
    db = get_db()
    case = db.execute(
        "SELECT c.*, cl.first_name, cl.last_name FROM cases c"
        " LEFT JOIN clients cl ON c.client_id = cl.id WHERE c.id = ?",
        (case_id,),
    ).fetchone()
    if not case:
        abort(404)
    parties = db.execute(
        "SELECT * FROM opposing_parties WHERE case_id = ?"
        " ORDER BY last_name, first_name",
        (case_id,),
    ).fetchall()
    doc_count = db.execute(
        "SELECT COUNT(*) AS c FROM documents WHERE case_id = ?",
        (case_id,),
    ).fetchone()["c"]
    upcoming = db.execute(
        "SELECT * FROM calendar_events WHERE case_id = ? AND completed = 0"
        " AND event_date >= ? ORDER BY event_date LIMIT 5",
        (case_id, date.today().isoformat()),
    ).fetchall()
    time_totals = db.execute(
        "SELECT COALESCE(SUM(hours),0) AS h, COALESCE(SUM(hours*rate),0) AS a"
        " FROM time_entries WHERE case_id = ?",
        (case_id,),
    ).fetchone()
    audit("case_view", f"Viewed case {case['case_number']} (id={case_id})")
    return render_template("case_detail.html", case=case, parties=parties,
                           doc_count=doc_count, upcoming=upcoming,
                           time_totals=time_totals)


@app.route("/cases/<int:case_id>/edit", methods=["GET", "POST"])
@login_required
def case_edit(case_id):
    db = get_db()
    case = db.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    if not case:
        abort(404)
    clients = db.execute(
        "SELECT id, first_name, last_name FROM clients"
        " ORDER BY last_name, first_name"
    ).fetchall()
    if request.method == "POST":
        check_csrf()
        now = datetime.now(timezone.utc).isoformat()
        client_id = request.form.get("client_id", "").strip() or None
        db.execute(
            "UPDATE cases SET title=?, client_id=?, case_type=?, status=?,"
            " date_opened=?, date_closed=?, notes=?, updated_at=? WHERE id=?",
            (
                request.form.get("title", "").strip(),
                client_id,
                request.form.get("case_type", "other"),
                request.form.get("status", "active"),
                request.form.get("date_opened", "").strip(),
                request.form.get("date_closed", "").strip(),
                request.form.get("notes", "").strip(),
                now,
                case_id,
            ),
        )
        db.commit()
        audit("case_update", f"Updated case {case['case_number']} (id={case_id})")
        flash("Case updated.", "success")
        return redirect(url_for("case_detail", case_id=case_id))
    return render_template(
        "case_form.html", case=case, clients=clients,
        case_types=CASE_TYPES, statuses=CASE_STATUSES,
    )


@app.route("/cases/<int:case_id>/status", methods=["POST"])
@role_required("admin", "attorney")
def case_set_status(case_id):
    """Inline status change from the case detail page (no full edit form)."""
    check_csrf()
    db = get_db()
    case = db.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    if not case:
        abort(404)
    new_status = request.form.get("status", "").strip()
    if new_status not in CASE_STATUSES:
        flash("Invalid status.", "error")
        return redirect(url_for("case_detail", case_id=case_id))
    if new_status != case["status"]:
        db.execute(
            "UPDATE cases SET status = ?, updated_at = ? WHERE id = ?",
            (new_status, datetime.now(timezone.utc).isoformat(), case_id),
        )
        db.commit()
        audit("case_status",
              f"Changed case {case['case_number']} status"
              f" {case['status']} -> {new_status}")
        flash(f"Status changed to {new_status}.", "success")
    return redirect(url_for("case_detail", case_id=case_id))


@app.route("/cases/<int:case_id>/delete", methods=["POST"])
@can_delete
def case_delete(case_id):
    check_csrf()
    db = get_db()
    case = db.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    if not case:
        abort(404)
    db.execute("DELETE FROM cases WHERE id = ?", (case_id,))
    db.commit()
    audit("case_delete", f"Deleted case {case['case_number']} (id={case_id})")
    flash("Case deleted.", "success")
    return redirect(url_for("case_list"))


# ----------------------------------------------------------------------------
# Opposing parties (conflict checking support)
# ----------------------------------------------------------------------------
@app.route("/cases/<int:case_id>/parties/add", methods=["POST"])
@login_required
def party_add(case_id):
    check_csrf()
    db = get_db()
    case = db.execute("SELECT id FROM cases WHERE id = ?", (case_id,)).fetchone()
    if not case:
        abort(404)
    first_name = request.form.get("first_name", "").strip()
    last_name = request.form.get("last_name", "").strip()
    if not first_name or not last_name:
        flash("Opposing party needs a first and last name.", "error")
    else:
        db.execute(
            "INSERT INTO opposing_parties (case_id, first_name, last_name, role,"
            " notes, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                case_id, first_name, last_name,
                request.form.get("role", "").strip(),
                request.form.get("notes", "").strip(),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        db.commit()
        audit("party_add",
              f"Added opposing party {first_name} {last_name} to case"
              f" (id={case_id})")
        flash("Opposing party added.", "success")
    return redirect(url_for("case_detail", case_id=case_id))


@app.route("/parties/<int:party_id>/delete", methods=["POST"])
@can_delete
def party_delete(party_id):
    check_csrf()
    db = get_db()
    row = db.execute(
        "SELECT case_id, first_name, last_name FROM opposing_parties"
        " WHERE id = ?", (party_id,)
    ).fetchone()
    if not row:
        abort(404)
    db.execute("DELETE FROM opposing_parties WHERE id = ?", (party_id,))
    db.commit()
    audit("party_delete",
          f"Removed opposing party {row['first_name']} {row['last_name']}"
          f" from case (id={row['case_id']})")
    flash("Opposing party removed.", "success")
    return redirect(url_for("case_detail", case_id=row["case_id"]))


# ----------------------------------------------------------------------------
# Documents
# ----------------------------------------------------------------------------
def _case_doc_dir(case_id):
    d = os.path.join(DOCUMENTS_DIR, str(case_id))
    os.makedirs(d, exist_ok=True)
    return d


@app.route("/cases/<int:case_id>/documents", methods=["GET", "POST"])
@login_required
def document_list(case_id):
    db = get_db()
    case = db.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    if not case:
        abort(404)
    if request.method == "POST":
        check_csrf()
        f = request.files.get("file")
        if not f or not f.filename:
            flash("Choose a file to upload.", "error")
            return redirect(url_for("document_list", case_id=case_id))
        ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
        if ext in BLOCKED_EXTENSIONS:
            flash(f"Files of type .{ext} are not allowed (security policy).",
                  "error")
            return redirect(url_for("document_list", case_id=case_id))
        original = secure_filename(f.filename)
        category = request.form.get("category", "other")
        if category not in DOC_CATEGORIES:
            category = "other"
        notes = request.form.get("notes", "").strip()
        # Versioning: same original name + category => bump version, keep old.
        row = db.execute(
            "SELECT MAX(version) AS v FROM documents"
            " WHERE case_id = ? AND original_name = ? AND category = ?",
            (case_id, original, category),
        ).fetchone()
        version = (row["v"] or 0) + 1
        stored = f"{uuid.uuid4().hex}_{original}"
        path = os.path.join(_case_doc_dir(case_id), stored)
        f.save(path)
        size = os.path.getsize(path)
        db.execute(
            "INSERT INTO documents (case_id, original_name, stored_name,"
            " category, file_size, version, uploaded_by, notes, uploaded_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                case_id, original, stored, category, size, version,
                session.get("username"), notes,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        db.commit()
        audit("document_upload",
              f"Uploaded {original} (v{version}, {category}) to case"
              f" {case['case_number']} (id={case_id})")
        flash(f"Uploaded {original} (version {version}).", "success")
        return redirect(url_for("document_list", case_id=case_id))
    docs = db.execute(
        "SELECT * FROM documents WHERE case_id = ?"
        " ORDER BY original_name, version DESC",
        (case_id,),
    ).fetchall()
    return render_template(
        "documents.html", case=case, documents=docs,
        categories=DOC_CATEGORIES,
    )


@app.route("/documents/<int:doc_id>/download")
@login_required
def document_download(doc_id):
    db = get_db()
    doc = db.execute(
        "SELECT d.*, c.case_number FROM documents d"
        " JOIN cases c ON d.case_id = c.id WHERE d.id = ?",
        (doc_id,),
    ).fetchone()
    if not doc:
        abort(404)
    path = os.path.join(_case_doc_dir(doc["case_id"]), doc["stored_name"])
    if not os.path.exists(path):
        flash("File is missing from disk. Check backups.", "error")
        return redirect(url_for("document_list", case_id=doc["case_id"]))
    audit("document_download",
          f"Downloaded {doc['original_name']} (v{doc['version']}) from case"
          f" {doc['case_number']}")
    return send_file(path, as_attachment=True,
                     download_name=doc["original_name"])


@app.route("/documents/<int:doc_id>/delete", methods=["POST"])
@can_delete
def document_delete(doc_id):
    check_csrf()
    db = get_db()
    doc = db.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if not doc:
        abort(404)
    path = os.path.join(_case_doc_dir(doc["case_id"]), doc["stored_name"])
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
    db.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    db.commit()
    audit("document_delete",
          f"Deleted {doc['original_name']} (v{doc['version']}) from case"
          f" (id={doc['case_id']})")
    flash("Document deleted.", "success")
    return redirect(url_for("document_list", case_id=doc["case_id"]))


# ----------------------------------------------------------------------------
# Calendar & deadlines
# ----------------------------------------------------------------------------
@app.route("/calendar")
@login_required
def calendar_view():
    db = get_db()
    # Month navigation: ?y=2026&m=10
    try:
        year = int(request.args.get("y", date.today().year))
        month = int(request.args.get("m", date.today().month))
        first = date(year, month, 1)
    except ValueError:
        first = date.today()
        year, month = first.year, first.month
    # Build a 6x7 grid starting Monday
    start = first - timedelta(days=first.weekday())
    cells = []
    for i in range(42):
        d = start + timedelta(days=i)
        cells.append(d)
    month_start = first.isoformat()
    if month == 12:
        month_end = date(year + 1, 1, 1).isoformat()
    else:
        month_end = date(year, month + 1, 1).isoformat()
    # Events overlapping the grid
    grid_start = cells[0].isoformat()
    grid_end = cells[-1].isoformat()
    events = db.execute(
        "SELECT e.*, c.case_number FROM calendar_events e"
        " LEFT JOIN cases c ON e.case_id = c.id"
        " WHERE e.event_date >= ? AND e.event_date <= ?"
        " ORDER BY e.event_date, e.event_time",
        (grid_start, grid_end),
    ).fetchall()
    by_date = {}
    for e in events:
        by_date.setdefault(e["event_date"], []).append(e)
    # Prev/next month links
    prev_m = month - 1 or 12
    prev_y = year - (1 if month == 1 else 0)
    next_m = month + 1 if month < 12 else 1
    next_y = year + (1 if month == 12 else 0)
    month_name = first.strftime("%B %Y")
    return render_template(
        "calendar.html", cells=cells, by_date=by_date, year=year, month=month,
        month_name=month_name, prev_y=prev_y, prev_m=prev_m,
        next_y=next_y, next_m=next_m, today=date.today().isoformat(),
    )


@app.route("/events/new", methods=["GET", "POST"])
@login_required
def event_new():
    db = get_db()
    cases = db.execute(
        "SELECT id, case_number, title FROM cases WHERE status IN"
        " ('active','pending') ORDER BY case_number"
    ).fetchall()
    preset_case = request.args.get("case_id", "")
    if request.method == "POST":
        check_csrf()
        title = request.form.get("title", "").strip()
        event_date = request.form.get("event_date", "").strip()
        if not title or not event_date:
            flash("Title and date are required.", "error")
            return render_template(
                "event_form.html", cases=cases, event=None,
                event_types=EVENT_TYPES, preset_case=preset_case,
                today=date.today().isoformat(),
            )
        event_type = request.form.get("event_type", "reminder")
        if event_type not in EVENT_TYPES:
            event_type = "reminder"
        case_id = request.form.get("case_id", "").strip() or None
        db.execute(
            "INSERT INTO calendar_events (case_id, title, event_type,"
            " event_date, event_time, description, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                case_id, title, event_type, event_date,
                request.form.get("event_time", "").strip(),
                request.form.get("description", "").strip(),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        db.commit()
        audit("event_create", f"Created {event_type} '{title}' on {event_date}")
        flash("Event added.", "success")
        return redirect(url_for("calendar_view"))
    return render_template(
        "event_form.html", cases=cases, event=None,
        event_types=EVENT_TYPES, preset_case=preset_case,
        today=date.today().isoformat(),
    )


@app.route("/events/<int:event_id>/toggle", methods=["POST"])
@login_required
def event_toggle(event_id):
    check_csrf()
    db = get_db()
    ev = db.execute(
        "SELECT * FROM calendar_events WHERE id = ?", (event_id,)
    ).fetchone()
    if not ev:
        abort(404)
    new_val = 0 if ev["completed"] else 1
    db.execute(
        "UPDATE calendar_events SET completed = ? WHERE id = ?",
        (new_val, event_id),
    )
    db.commit()
    audit("event_toggle",
          f"Marked '{ev['title']}' ({ev['event_date']}) as"
          f" {'done' if new_val else 'not done'}")
    return redirect(request.referrer or url_for("calendar_view"))


@app.route("/events/<int:event_id>/delete", methods=["POST"])
@can_delete
def event_delete(event_id):
    check_csrf()
    db = get_db()
    ev = db.execute(
        "SELECT * FROM calendar_events WHERE id = ?", (event_id,)
    ).fetchone()
    if not ev:
        abort(404)
    db.execute("DELETE FROM calendar_events WHERE id = ?", (event_id,))
    db.commit()
    audit("event_delete", f"Deleted event '{ev['title']}' ({ev['event_date']})")
    flash("Event deleted.", "success")
    return redirect(request.referrer or url_for("calendar_view"))


# ----------------------------------------------------------------------------
# Court deadline calculator (WA Superior Court rules)
# ----------------------------------------------------------------------------
@app.route("/deadlines", methods=["GET"])
@login_required
def deadline_calculator():
    """Deadline calculator form + results. All roles may calculate."""
    db = get_db()
    cases = db.execute(
        "SELECT id, case_number, title FROM cases WHERE status IN"
        " ('active','pending') ORDER BY case_number"
    ).fetchall()
    trigger_type = request.args.get("trigger", "")
    date_str = request.args.get("date", "")
    case_id = request.args.get("case_id", "")
    results = None
    trigger_date = None
    rule_info = None
    error = None
    if trigger_type or date_str:
        if trigger_type not in DEADLINE_RULES:
            error = "Pick a trigger type (hearing, trial, or service date)."
        else:
            try:
                trigger_date = date.fromisoformat(date_str)
            except (ValueError, TypeError):
                error = "Enter a valid trigger date."
        if not error:
            rule_info = DEADLINE_RULES[trigger_type]
            results = calculate_deadlines(trigger_type, trigger_date)
    can_push = session.get("role") in ("admin", "attorney")
    return render_template(
        "deadlines.html",
        trigger_choices=TRIGGER_CHOICES,
        trigger_type=trigger_type,
        date_str=date_str,
        case_id=case_id,
        cases=cases,
        results=results,
        trigger_date=trigger_date,
        rule_info=rule_info,
        error=error,
        can_push=can_push,
        disclaimer=DEADLINE_DISCLAIMER,
        today=date.today(),
    )


@app.route("/deadlines/push", methods=["POST"])
@role_required("admin", "attorney")
def deadline_push():
    """Push calculated deadlines to the case calendar. Attorney/admin only."""
    check_csrf()
    trigger_type = request.form.get("trigger", "")
    date_str = request.form.get("date", "")
    case_id = request.form.get("case_id", "").strip()
    if trigger_type not in DEADLINE_RULES:
        flash("Invalid trigger type.", "error")
        return redirect(url_for("deadline_calculator"))
    try:
        trigger_date = date.fromisoformat(date_str)
    except (ValueError, TypeError):
        flash("Invalid trigger date.", "error")
        return redirect(url_for("deadline_calculator"))
    if not case_id:
        flash("Pick a case to add the deadlines to.", "error")
        return redirect(url_for(
            "deadline_calculator", trigger=trigger_type, date=date_str,
        ))
    db = get_db()
    case = db.execute(
        "SELECT id, case_number FROM cases WHERE id = ?", (case_id,)
    ).fetchone()
    if not case:
        flash("Case not found.", "error")
        return redirect(url_for("deadline_calculator"))
    # Recompute server-side (never trust client-supplied dates)
    computed = {r["key"]: r for r in calculate_deadlines(trigger_type, trigger_date)}
    only = request.form.get("only", "")
    if only:
        keys = [only] if only in computed else []
    else:
        keys = [k for k in request.form.getlist("keys") if k in computed]
    if not keys:
        flash("Select at least one deadline to add.", "error")
        return redirect(url_for(
            "deadline_calculator", trigger=trigger_type, date=date_str,
            case_id=case_id,
        ))
    rule_info = DEADLINE_RULES[trigger_type]
    added = 0
    for key in keys:
        r = computed[key]
        db.execute(
            "INSERT INTO calendar_events (case_id, title, event_type,"
            " event_date, event_time, description, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                case_id,
                f"DEADLINE: {r['label']}",
                "filing_deadline",
                r["due"].isoformat(),
                "",
                f"{r['basis']} — {rule_info['label']} on"
                f" {trigger_date.isoformat()}. Verify against current court"
                " rules and case-specific orders.",
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        added += 1
    db.commit()
    audit(
        "deadline_push",
        f"Added {added} calculated deadline(s) to case"
        f" {case['case_number']} ({rule_info['label']} on"
        f" {trigger_date.isoformat()})",
    )
    flash(f"Added {added} deadline(s) to the case calendar.", "success")
    return redirect(url_for("calendar_view"))


# ----------------------------------------------------------------------------
# Billing & time tracking
# ----------------------------------------------------------------------------
@app.route("/cases/<int:case_id>/time", methods=["GET", "POST"])
@role_required("admin", "attorney")
def time_list(case_id):
    db = get_db()
    case = db.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    if not case:
        abort(404)
    if request.method == "POST":
        check_csrf()
        try:
            hours = float(request.form.get("hours", "0"))
        except ValueError:
            hours = 0
        description = request.form.get("description", "").strip()
        entry_date = request.form.get("entry_date", "").strip() or date.today().isoformat()
        try:
            rate = float(request.form.get("rate", "0"))
        except ValueError:
            rate = 0
        if hours <= 0 or not description:
            flash("Hours (greater than 0) and a description are required.",
                  "error")
        else:
            db.execute(
                "INSERT INTO time_entries (case_id, entry_date, hours,"
                " description, rate, user_id, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    case_id, entry_date, hours, description, rate,
                    session.get("user_id"), datetime.now(timezone.utc).isoformat(),
                ),
            )
            db.commit()
            audit("time_add",
                  f"Logged {hours}h on case {case['case_number']} (id={case_id})")
            flash("Time entry added.", "success")
        return redirect(url_for("time_list", case_id=case_id))
    entries = db.execute(
        "SELECT * FROM time_entries WHERE case_id = ? ORDER BY entry_date DESC",
        (case_id,),
    ).fetchall()
    total_hours = sum(e["hours"] for e in entries)
    total_amount = sum(e["hours"] * e["rate"] for e in entries)
    uninvoiced = [e for e in entries if not e["invoiced"]]
    # Pre-fill the rate with this user's most recent rate (less typing)
    last_rate = db.execute(
        "SELECT rate FROM time_entries WHERE user_id = ? AND rate > 0"
        " ORDER BY id DESC LIMIT 1",
        (session.get("user_id"),),
    ).fetchone()
    return render_template(
        "time_entries.html", case=case, entries=entries,
        total_hours=total_hours, total_amount=total_amount,
        uninvoiced=uninvoiced, today=date.today().isoformat(),
        last_rate=(last_rate["rate"] if last_rate else ""),
    )


@app.route("/time/<int:entry_id>/delete", methods=["POST"])
@role_required("admin", "attorney")
def time_delete(entry_id):
    check_csrf()
    db = get_db()
    e = db.execute("SELECT * FROM time_entries WHERE id = ?", (entry_id,)).fetchone()
    if not e:
        abort(404)
    # RPC 1.15B: financial records cannot be destroyed before 7 years.
    # Fail closed: if the date is missing or too recent, refuse.
    if not retention_ok(e["entry_date"]):
        flash(
            "Cannot delete this time entry: financial records must be retained"
            f" for {RETENTION_YEARS_FINANCIAL} years (RPC 1.15B).",
            "error",
        )
        audit("time_delete_blocked",
              f"Blocked deletion of time entry (id={entry_id}) — retention")
        return redirect(url_for("time_list", case_id=e["case_id"]))
    if e["invoiced"]:
        flash("Cannot delete a time entry that is on an invoice.", "error")
        return redirect(url_for("time_list", case_id=e["case_id"]))
    db.execute("DELETE FROM time_entries WHERE id = ?", (entry_id,))
    db.commit()
    audit("time_delete", f"Deleted time entry (id={entry_id})")
    flash("Time entry deleted.", "success")
    return redirect(url_for("time_list", case_id=e["case_id"]))


@app.route("/invoices")
@role_required("admin", "attorney")
def invoice_list():
    db = get_db()
    invoices = db.execute(
        "SELECT i.*, cl.first_name, cl.last_name FROM invoices i"
        " JOIN clients cl ON i.client_id = cl.id"
        " ORDER BY i.created_at DESC"
    ).fetchall()
    # Compute totals
    out = []
    for inv in invoices:
        total = db.execute(
            "SELECT COALESCE(SUM(amount),0) AS t FROM invoice_items"
            " WHERE invoice_id = ?", (inv["id"],)
        ).fetchone()["t"]
        d = dict(inv)
        d["total"] = total
        out.append(d)
    return render_template("invoices.html", invoices=out)


@app.route("/invoices/new", methods=["GET", "POST"])
@role_required("admin", "attorney")
def invoice_new():
    db = get_db()
    clients = db.execute(
        "SELECT id, first_name, last_name FROM clients"
        " ORDER BY last_name, first_name"
    ).fetchall()
    preset_client = request.args.get("client_id", "")
    # Uninvoiced time entries for the selected client (for quick-add)
    sel_client = request.args.get("client_id", "") or (
        request.form.get("client_id", "") if request.method == "POST" else "")
    uninvoiced = []
    if sel_client:
        uninvoiced = db.execute(
            "SELECT t.*, c.case_number FROM time_entries t"
            " JOIN cases c ON t.case_id = c.id"
            " WHERE c.client_id = ? AND t.invoiced = 0"
            " ORDER BY t.entry_date",
            (sel_client,),
        ).fetchall()
    if request.method == "POST":
        check_csrf()
        client_id = request.form.get("client_id", "").strip()
        if not client_id:
            flash("Choose a client.", "error")
            return render_template(
                "invoice_form.html", clients=clients,
                preset_client=preset_client, uninvoiced=uninvoiced,
            )
        now = datetime.now(timezone.utc).isoformat()
        inv_no = f"INV-{datetime.now().strftime('%Y%m%d')}-{secrets.token_hex(3).upper()}"
        cur = db.execute(
            "INSERT INTO invoices (invoice_number, client_id, issue_date,"
            " due_date, status, notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                inv_no, client_id,
                request.form.get("issue_date", "").strip() or date.today().isoformat(),
                request.form.get("due_date", "").strip(),
                "draft",
                request.form.get("notes", "").strip(),
                now,
            ),
        )
        invoice_id = cur.lastrowid
        # Pull selected uninvoiced time entries onto the invoice
        entry_ids = request.form.getlist("entry_ids")
        for eid in entry_ids:
            e = db.execute(
                "SELECT t.*, c.client_id FROM time_entries t"
                " JOIN cases c ON t.case_id = c.id WHERE t.id = ?",
                (eid,),
            ).fetchone()
            if e and str(e["client_id"]) == str(client_id) and not e["invoiced"]:
                amount = e["hours"] * e["rate"]
                db.execute(
                    "INSERT INTO invoice_items (invoice_id, entry_date, description,"
                    " hours, rate, amount) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        invoice_id,
                        e["entry_date"],
                        e["description"],
                        e["hours"], e["rate"], amount,
                    ),
                )
                db.execute(
                    "UPDATE time_entries SET invoiced = 1, invoice_id = ?"
                    " WHERE id = ?", (invoice_id, eid),
                )
        # Manual line items
        descs = request.form.getlist("item_desc")
        amounts = request.form.getlist("item_amount")
        item_dates = request.form.getlist("item_date")
        for idx, (desc, amt) in enumerate(zip(descs, amounts)):
            desc, amt = desc.strip(), amt.strip()
            if desc and amt:
                try:
                    amount = float(amt)
                except ValueError:
                    continue
                entry_date = item_dates[idx].strip() if idx < len(item_dates) else ""
                db.execute(
                    "INSERT INTO invoice_items (invoice_id, entry_date, description,"
                    " hours, rate, amount) VALUES (?, ?, ?, 0, 0, ?)",
                    (invoice_id, entry_date or None, desc, amount),
                )
        db.commit()
        audit("invoice_create", f"Created invoice {inv_no} (id={invoice_id})")
        flash(f"Invoice {inv_no} created.", "success")
        return redirect(url_for("invoice_detail", invoice_id=invoice_id))
    today = date.today()
    return render_template(
        "invoice_form.html", clients=clients, preset_client=preset_client,
        uninvoiced=uninvoiced,
        default_issue=today.isoformat(),
        default_due=(today + timedelta(days=30)).isoformat(),
    )


@app.route("/invoices/<int:invoice_id>")
@role_required("admin", "attorney")
def invoice_detail(invoice_id):
    db = get_db()
    inv = db.execute(
        "SELECT i.*, cl.first_name, cl.last_name, cl.email, cl.phone, cl.address"
        " FROM invoices i JOIN clients cl ON i.client_id = cl.id"
        " WHERE i.id = ?", (invoice_id,)
    ).fetchone()
    if not inv:
        abort(404)
    items = db.execute(
        "SELECT * FROM invoice_items WHERE invoice_id = ?", (invoice_id,)
    ).fetchall()
    total = sum(i["amount"] for i in items)
    audit("invoice_view", f"Viewed invoice {inv['invoice_number']} (id={invoice_id})")
    return render_template(
        "invoice_detail.html", invoice=inv, items=items, total=total,
        statuses=INVOICE_STATUSES,
    )


@app.route("/invoices/<int:invoice_id>/status", methods=["POST"])
@role_required("admin", "attorney")
def invoice_status(invoice_id):
    check_csrf()
    db = get_db()
    inv = db.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
    if not inv:
        abort(404)
    status = request.form.get("status", "draft")
    if status not in INVOICE_STATUSES:
        flash("Invalid status.", "error")
    else:
        db.execute("UPDATE invoices SET status = ? WHERE id = ?",
                   (status, invoice_id))
        db.commit()
        audit("invoice_status",
              f"Set invoice {inv['invoice_number']} to {status}")
        flash(f"Invoice marked {status}.", "success")
    return redirect(url_for("invoice_detail", invoice_id=invoice_id))


@app.route("/invoices/<int:invoice_id>/delete", methods=["POST"])
@role_required("admin", "attorney")
def invoice_delete(invoice_id):
    check_csrf()
    db = get_db()
    inv = db.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
    if not inv:
        abort(404)
    # RPC 1.15B: invoices are financial records — 7-year retention, fail closed.
    if not retention_ok(inv["issue_date"]):
        flash(
            "Cannot delete this invoice: financial records must be retained"
            f" for {RETENTION_YEARS_FINANCIAL} years (RPC 1.15B).",
            "error",
        )
        audit("invoice_delete_blocked",
              f"Blocked deletion of invoice {inv['invoice_number']} — retention")
        return redirect(url_for("invoice_detail", invoice_id=invoice_id))
    # Unlink time entries first
    db.execute(
        "UPDATE time_entries SET invoiced = 0, invoice_id = NULL"
        " WHERE invoice_id = ?", (invoice_id,),
    )
    db.execute("DELETE FROM invoice_items WHERE invoice_id = ?", (invoice_id,))
    db.execute("DELETE FROM invoices WHERE id = ?", (invoice_id,))
    db.commit()
    audit("invoice_delete", f"Deleted invoice {inv['invoice_number']}")
    flash("Invoice deleted.", "success")
    return redirect(url_for("invoice_list"))


@app.route("/invoices/<int:invoice_id>/pdf")
@role_required("admin", "attorney")
def invoice_pdf(invoice_id):
    """Download a professionally formatted PDF of the invoice."""
    db = get_db()
    inv = db.execute(
        "SELECT i.*, cl.first_name, cl.last_name, cl.email, cl.phone, cl.address"
        " FROM invoices i JOIN clients cl ON i.client_id = cl.id"
        " WHERE i.id = ?", (invoice_id,),
    ).fetchone()
    if not inv:
        abort(404)
    items = db.execute(
        "SELECT * FROM invoice_items WHERE invoice_id = ? ORDER BY id",
        (invoice_id,),
    ).fetchall()
    total = sum(i["amount"] for i in items)
    try:
        from invoice_pdf import build_invoice_pdf
        logo_path = os.path.join(BASE_DIR, "static", "dgm-logo.png")
        pdf_bytes = build_invoice_pdf(inv, items, total, logo_path=logo_path)
    except Exception as e:
        flash(f"Could not generate PDF: {e}", "error")
        return redirect(url_for("invoice_detail", invoice_id=invoice_id))
    audit("invoice_pdf",
          f"Generated PDF for invoice {inv['invoice_number']} (id={invoice_id})")
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"{inv['invoice_number']}.pdf",
    )


# ----------------------------------------------------------------------------
# Document templates — attorney and admin only. Staff is blocked.
# Templates auto-fill from client/case data and generate PDFs that are
# saved to the case's documents with versioning.
# ----------------------------------------------------------------------------
from template_defs import get_template, template_list
from template_pdf import build_template_pdf, calc_support


def _template_party_context(client_id, case_id):
    """Return (client_dict|None, children_list, case_row|None)."""
    db = get_db()
    client = None
    children = []
    case = None
    if client_id:
        row = db.execute(
            "SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
        if row:
            client = _decrypt_client(row)
            children = [
                _decrypt_child(k) for k in db.execute(
                    "SELECT * FROM children WHERE client_id = ? ORDER BY name",
                    (client_id,)).fetchall()
            ]
    if case_id:
        case = db.execute(
            "SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    return client, children, case


def _resolve_placeholders(text, client, children, case):
    """Replace {{placeholders}} in template text from DB records."""
    if not text:
        return ""
    out = str(text)
    today = date.today().isoformat()
    subs = {"{{today}}": today}
    if client:
        full = f"{client.get('first_name', '')} {client.get('last_name', '')}".strip()
        subs["{{client.name}}"] = full
        subs["{{client.first_name}}"] = client.get("first_name", "") or ""
        subs["{{client.last_name}}"] = client.get("last_name", "") or ""
        subs["{{client.spouse_name}}"] = client.get("spouse_name", "") or ""
        subs["{{client.role}}"] = "Petitioner"
    if children:
        names = "; ".join(
            f"{c.get('name', '')} (DOB: {c.get('date_of_birth') or 'unknown'})"
            for c in children)
        subs["{{client.children}}"] = names
    else:
        subs["{{client.children}}"] = ""
    if case:
        subs["{{case.number}}"] = case["case_number"] or ""
        subs["{{case.title}}"] = case["title"] or ""
    else:
        subs["{{case.number}}"] = ""
        subs["{{case.title}}"] = ""
    # recipient_name is a form field, not DB — leave for later pass
    for ph, val in subs.items():
        out = out.replace(ph, val)
    return out


def _prefill_value(field, client, children, case):
    """Compute the pre-filled value for a template field."""
    src = field.get("source")
    if src == "client.name" and client:
        return f"{client.get('first_name', '')} {client.get('last_name', '')}".strip()
    if src == "client.spouse_name" and client:
        return client.get("spouse_name", "") or ""
    if src == "case.number" and case:
        return case["case_number"] or ""
    if src == "case.title" and case:
        return case["title"] or ""
    default = field.get("default", "")
    return _resolve_placeholders(default, client, children, case)


def _gather_template_values(tmpl, form, client, children, case):
    """Read submitted form values for a template's fields, resolving placeholders."""
    values = {}
    for f in tmpl["fields"]:
        if f["type"] in ("info", "child-list"):
            continue
        raw = form.get(f["name"], "")
        # Resolve any placeholders the user left in (e.g. {{today}})
        values[f["name"]] = _resolve_placeholders(raw, client, children, case)
        # Also resolve recipient_name-style placeholders used inside body text
        values[f["name"]] = values[f["name"]].replace(
            "{{recipient_name}}", form.get("recipient_name", ""))
    # Second pass: allow {{field_name}} cross-references (e.g. body uses {{recipient_name}})
    for f in tmpl["fields"]:
        if f["type"] in ("info", "child-list"):
            continue
        v = values[f["name"]]
        for g in tmpl["fields"]:
            if g["type"] in ("info", "child-list"):
                continue
            v = v.replace("{{%s}}" % g["name"], values.get(g["name"], ""))
        values[f["name"]] = v
    return values


def _save_generated_doc(case_id, original_name, pdf_bytes, category, notes):
    """Save generated PDF bytes into a case's documents with versioning."""
    db = get_db()
    row = db.execute(
        "SELECT MAX(version) AS v FROM documents"
        " WHERE case_id = ? AND original_name = ? AND category = ?",
        (case_id, original_name, category),
    ).fetchone()
    version = (row["v"] or 0) + 1
    stored = f"{uuid.uuid4().hex}_{original_name}"
    path = os.path.join(_case_doc_dir(case_id), stored)
    with open(path, "wb") as fh:
        fh.write(pdf_bytes)
    size = os.path.getsize(path)
    db.execute(
        "INSERT INTO documents (case_id, original_name, stored_name,"
        " category, file_size, version, uploaded_by, notes, uploaded_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (case_id, original_name, stored, category, size, version,
         session.get("username"), notes,
         datetime.now(timezone.utc).isoformat()),
    )
    db.commit()
    return version


@app.route("/templates")
@role_required("admin", "attorney")
def template_gallery():
    return render_template("templates.html", templates=template_list())


@app.route("/templates/<key>")
@role_required("admin", "attorney")
def template_fill(key):
    tmpl = get_template(key)
    if not tmpl:
        abort(404)
    db = get_db()
    client_id = request.args.get("client_id", type=int)
    case_id = request.args.get("case_id", type=int)
    client, children, case = _template_party_context(client_id, case_id)
    clients = db.execute(
        "SELECT id, first_name, last_name FROM clients ORDER BY last_name, first_name"
    ).fetchall()
    if client_id:
        cases = db.execute(
            "SELECT id, case_number, title FROM cases WHERE client_id = ?"
            " ORDER BY case_number", (client_id,)).fetchall()
    else:
        cases = db.execute(
            "SELECT id, case_number, title FROM cases ORDER BY case_number"
        ).fetchall()
    prefill = {}
    for f in tmpl["fields"]:
        if f["type"] not in ("info", "child-list"):
            prefill[f["name"]] = _prefill_value(f, client, children, case)
    return render_template(
        "template_fill.html", template=tmpl, clients=clients, cases=cases,
        client=client, children=children, case=case, prefill=prefill)


@app.route("/templates/<key>/preview", methods=["POST"])
@role_required("admin", "attorney")
def template_preview(key):
    tmpl = get_template(key)
    if not tmpl:
        abort(404)
    check_csrf()
    client_id = request.form.get("client_id", type=int)
    case_id = request.form.get("case_id", type=int)
    client, children, case = _template_party_context(client_id, case_id)
    values = _gather_template_values(tmpl, request.form, client, children, case)
    support_calc = None
    if key == "support_worksheet":
        support_calc = calc_support(
            values.get("parent_a_income"), values.get("parent_b_income"),
            len(children), values.get("daycare"), values.get("health_insurance"))
    audit("template_preview",
          f"Previewed {tmpl['name']} for "
          f"{client['first_name']} {client['last_name']}" if client else f"Previewed {tmpl['name']}")
    return render_template(
        "template_preview.html", template=tmpl, values=values,
        client=client, children=children, case=case,
        support_calc=support_calc)


@app.route("/templates/<key>/generate", methods=["POST"])
@role_required("admin", "attorney")
def template_generate(key):
    tmpl = get_template(key)
    if not tmpl:
        abort(404)
    check_csrf()
    client_id = request.form.get("client_id", type=int)
    case_id = request.form.get("case_id", type=int)
    client, children, case = _template_party_context(client_id, case_id)
    values = _gather_template_values(tmpl, request.form, client, children, case)
    # Enrich data for the PDF builders
    data = dict(values)
    data["children"] = [{"name": c.get("name", ""),
                         "date_of_birth": c.get("date_of_birth", "")}
                        for c in children]
    data["case_number"] = case["case_number"] if case else ""
    try:
        logo_path = os.path.join(BASE_DIR, "static", "dgm-logo.png")
        pdf_bytes = build_template_pdf(tmpl["layout"], data, logo_path=logo_path)
    except Exception as e:
        flash(f"Could not generate document: {e}", "error")
        return redirect(url_for("template_fill", key=key))
    filename = f"{tmpl['file_stem']}.pdf"
    if case:
        version = _save_generated_doc(
            case["id"], filename, pdf_bytes, tmpl["doc_category"],
            f"Generated from template: {tmpl['name']}")
        audit("template_generate",
              f"Generated {tmpl['name']} (v{version}) for case"
              f" {case['case_number']} (id={case['id']})")
    else:
        who = f"{client['first_name']} {client['last_name']}" if client else "no client"
        audit("template_generate",
              f"Generated {tmpl['name']} for {who} (not filed to a case)")
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
    )


# ----------------------------------------------------------------------------
# Trust accounting (IOLTA / RPC 1.15A/B) — attorney and admin only.
# Staff is blocked: trust funds are never visible to the staff role.
# ----------------------------------------------------------------------------
@app.route("/trust")
@role_required("admin", "attorney")
def trust_overview():
    db = get_db()
    accounts = db.execute(
        "SELECT * FROM trust_accounts WHERE is_active = 1 ORDER BY name"
    ).fetchall()
    out = []
    for a in accounts:
        d = dict(a)
        d["balance_cents"] = account_trust_balance(db, a["id"])
        d["client_count"] = db.execute(
            "SELECT COUNT(DISTINCT client_id) AS c FROM trust_transactions"
            " WHERE account_id = ?", (a["id"],)
        ).fetchone()["c"]
        d["acct_display"] = decrypt_value(a["account_number"]) if a["account_number"] else ""
        out.append(d)
    return render_template("trust.html", accounts=out)


@app.route("/trust/accounts/new", methods=["GET", "POST"])
@role_required("admin", "attorney")
def trust_account_new():
    if request.method == "POST":
        check_csrf()
        name = request.form.get("name", "").strip()
        if not name:
            flash("Account name is required.", "error")
            return render_template("trust_account_form.html")
        db = get_db()
        now = datetime.now(timezone.utc).isoformat()
        acct_num = request.form.get("account_number", "").strip()
        db.execute(
            "INSERT INTO trust_accounts (name, bank_name, account_number, notes,"
            " is_active, created_at) VALUES (?, ?, ?, ?, 1, ?)",
            (
                name,
                request.form.get("bank_name", "").strip(),
                encrypt_value(acct_num) if acct_num else "",
                request.form.get("notes", "").strip(),
                now,
            ),
        )
        db.commit()
        audit("trust_account_create", f"Created trust account '{name}'")
        flash(f"Trust account '{name}' created.", "success")
        return redirect(url_for("trust_overview"))
    return render_template("trust_account_form.html")


@app.route("/trust/accounts/<int:account_id>")
@role_required("admin", "attorney")
def trust_account_detail(account_id):
    db = get_db()
    acct = db.execute(
        "SELECT * FROM trust_accounts WHERE id = ?", (account_id,)
    ).fetchone()
    if not acct:
        abort(404)
    d = dict(acct)
    d["balance_cents"] = account_trust_balance(db, account_id)
    d["acct_display"] = decrypt_value(acct["account_number"]) if acct["account_number"] else ""
    client_bals = trust_client_balances(db, account_id)
    recent = db.execute(
        "SELECT t.*, cl.first_name, cl.last_name, u.username AS created_by_name"
        " FROM trust_transactions t"
        " JOIN clients cl ON t.client_id = cl.id"
        " LEFT JOIN users u ON t.created_by = u.id"
        " WHERE t.account_id = ? ORDER BY t.txn_date DESC, t.id DESC LIMIT 50",
        (account_id,),
    ).fetchall()
    last_recon = db.execute(
        "SELECT * FROM trust_reconciliations WHERE account_id = ?"
        " ORDER BY statement_date DESC LIMIT 1",
        (account_id,),
    ).fetchone()
    return render_template(
        "trust_account.html", account=d, client_balances=client_bals,
        transactions=recent, last_recon=last_recon,
    )


@app.route("/trust/transactions/new", methods=["GET", "POST"])
@role_required("admin", "attorney")
def trust_transaction_new():
    """Record a deposit, disbursement, transfer, or reversal. Immutable once saved."""
    db = get_db()
    accounts = db.execute(
        "SELECT id, name FROM trust_accounts WHERE is_active = 1 ORDER BY name"
    ).fetchall()
    clients = db.execute(
        "SELECT id, first_name, last_name FROM clients ORDER BY last_name, first_name"
    ).fetchall()
    preset_account = request.args.get("account_id", "")
    preset_client = request.args.get("client_id", "")
    reverse_id = request.args.get("reverse_id", "") or request.form.get("reverse_id", "")
    reverse_of = None
    if reverse_id:
        reverse_of = db.execute(
            "SELECT t.*, cl.first_name, cl.last_name FROM trust_transactions t"
            " JOIN clients cl ON t.client_id = cl.id WHERE t.id = ?",
            (reverse_id,),
        ).fetchone()
        if not reverse_of:
            flash("Original transaction not found.", "error")
            return redirect(url_for("trust_overview"))

    if request.method == "POST":
        check_csrf()
        account_id = request.form.get("account_id", "").strip()
        client_id = request.form.get("client_id", "").strip()
        txn_type = request.form.get("txn_type", "").strip()
        amount = dollars_to_cents(request.form.get("amount", ""))
        txn_date = request.form.get("txn_date", "").strip() or date.today().isoformat()
        description = request.form.get("description", "").strip()
        reference = request.form.get("reference", "").strip()
        case_id = request.form.get("case_id", "").strip() or None
        errors = []
        if not account_id:
            errors.append("Choose a trust account.")
        if not client_id:
            errors.append("Choose a client.")
        if txn_type not in ("deposit", "disbursement", "transfer"):
            errors.append("Choose a transaction type.")
        if amount is None or amount <= 0:
            errors.append("Enter a valid amount greater than $0.00.")
        if not description:
            errors.append("A description is required (RPC 1.15A record-keeping).")

        # Validate the account and client exist
        acct = db.execute(
            "SELECT id FROM trust_accounts WHERE id = ?", (account_id,)
        ).fetchone() if account_id else None
        cli = db.execute(
            "SELECT id FROM clients WHERE id = ?", (client_id,)
        ).fetchone() if client_id else None
        if account_id and not acct:
            errors.append("Trust account not found.")
        if client_id and not cli:
            errors.append("Client not found.")

        target_client_id = request.form.get("target_client_id", "").strip()
        confirmed = request.form.get("confirm_transfer", "") == "yes"

        if not errors and txn_type == "disbursement":
            # HARD BLOCK: cannot disburse more than the client's balance.
            bal = client_trust_balance(db, int(account_id), int(client_id))
            if amount > bal:
                errors.append(
                    f"Insufficient trust funds: this client has ${cents_to_str(bal)}"
                    f" available in this account. Cannot disburse ${cents_to_str(amount)}."
                )
        if not errors and txn_type == "transfer":
            if not target_client_id or target_client_id == client_id:
                errors.append("Choose a different client to transfer to.")
            elif not confirmed:
                errors.append(
                    "Transfers between clients require the confirmation checkbox."
                )
            else:
                bal = client_trust_balance(db, int(account_id), int(client_id))
                if amount > bal:
                    errors.append(
                        f"Insufficient trust funds: source client has ${cents_to_str(bal)}"
                        f" available. Cannot transfer ${cents_to_str(amount)}."
                    )

        cases = []
        if not errors and client_id:
            cases = db.execute(
                "SELECT id, case_number, title FROM cases WHERE client_id = ?"
                " ORDER BY date_opened DESC", (client_id,)
            ).fetchall()

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template(
                "trust_transaction_form.html", accounts=accounts, clients=clients,
                cases=cases, preset_account=preset_account or account_id,
                preset_client=preset_client or client_id, reverse_of=reverse_of,
                today=date.today().isoformat(),
            )

        # --- All validations passed: write the immutable transaction(s) ---
        if txn_type == "transfer":
            # Two linked entries: money out of the source client, in to the target.
            desc_out = f"Transfer to client #{target_client_id}: {description}"
            desc_in = f"Transfer from client #{client_id}: {description}"
            out_id = log_trust_txn(
                db, int(account_id), int(client_id), case_id, txn_date,
                "transfer_out", amount, desc_out, reference)
            in_id = log_trust_txn(
                db, int(account_id), int(target_client_id), None, txn_date,
                "transfer_in", amount, desc_in, reference)
            db.commit()
            audit("trust_transfer",
                  f"Trust transfer ${cents_to_str(amount)} client {client_id} ->"
                  f" client {target_client_id} (account {account_id}, txns {out_id}/{in_id})")
            flash(f"Transfer of ${cents_to_str(amount)} recorded.", "success")
        elif reverse_of:
            # Reversal: create an offsetting entry linked to the original.
            orig_type = reverse_of["txn_type"]
            if orig_type in ("deposit", "transfer_in", "reversal_credit"):
                rev_type = "reversal_debit"
            else:
                rev_type = "reversal_credit"
            rev_id = log_trust_txn(
                db, int(account_id), int(client_id), case_id, txn_date,
                rev_type, amount,
                f"REVERSAL of txn #{reverse_of['id']}: {description}",
                reference, reverses_id=reverse_of["id"])
            db.commit()
            audit("trust_reversal",
                  f"Reversed trust txn #{reverse_of['id']} with txn #{rev_id}"
                  f" (${cents_to_str(amount)}, account {account_id})")
            flash("Reversing entry recorded. The original transaction is unchanged.", "success")
        else:
            txn_id = log_trust_txn(
                db, int(account_id), int(client_id), case_id, txn_date,
                txn_type, amount, description, reference)
            db.commit()
            audit(f"trust_{txn_type}",
                  f"Trust {txn_type} ${cents_to_str(amount)} for client {client_id}"
                  f" (account {account_id}, txn {txn_id})")
            flash(f"{txn_type.capitalize()} of ${cents_to_str(amount)} recorded.", "success")
        return redirect(url_for("trust_account_detail", account_id=int(account_id)))

    cases = []
    if preset_client:
        cases = db.execute(
            "SELECT id, case_number, title FROM cases WHERE client_id = ?"
            " ORDER BY date_opened DESC", (preset_client,)
        ).fetchall()
    return render_template(
        "trust_transaction_form.html", accounts=accounts, clients=clients,
        cases=cases, preset_account=preset_account,
        preset_client=preset_client, reverse_of=reverse_of,
        today=date.today().isoformat(),
    )


@app.route("/trust/ledger/<int:client_id>")
@role_required("admin", "attorney")
def trust_client_ledger(client_id):
    """Per-client trust ledger across all accounts, with date-range filter."""
    db = get_db()
    client = db.execute(
        "SELECT * FROM clients WHERE id = ?", (client_id,)
    ).fetchone()
    if not client:
        abort(404)
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    q = ("SELECT t.*, ta.name AS account_name, u.username AS created_by_name"
         " FROM trust_transactions t"
         " JOIN trust_accounts ta ON t.account_id = ta.id"
         " LEFT JOIN users u ON t.created_by = u.id"
         " WHERE t.client_id = ?")
    params = [client_id]
    if start:
        q += " AND t.txn_date >= ?"
        params.append(start)
    if end:
        q += " AND t.txn_date <= ?"
        params.append(end)
    q += " ORDER BY t.txn_date, t.id"
    txns = db.execute(q, params).fetchall()
    # Running balance
    rows = []
    bal = 0
    for t in txns:
        if t["txn_type"] in ("deposit", "transfer_in", "reversal_credit"):
            bal += t["amount_cents"]
        else:
            bal -= t["amount_cents"]
        d = dict(t)
        d["running_cents"] = bal
        rows.append(d)
    return render_template(
        "trust_ledger.html", client=client, transactions=rows,
        balance_cents=bal, start=start, end=end,
    )


@app.route("/trust/reconcile/<int:account_id>", methods=["GET", "POST"])
@role_required("admin", "attorney")
def trust_reconcile(account_id):
    """Monthly reconciliation: bank statement balance vs book balance."""
    db = get_db()
    acct = db.execute(
        "SELECT * FROM trust_accounts WHERE id = ?", (account_id,)
    ).fetchone()
    if not acct:
        abort(404)
    book_cents = account_trust_balance(db, account_id)
    history = db.execute(
        "SELECT r.*, u.username AS reconciled_by_name FROM trust_reconciliations r"
        " LEFT JOIN users u ON r.reconciled_by = u.id"
        " WHERE r.account_id = ? ORDER BY r.statement_date DESC LIMIT 12",
        (account_id,),
    ).fetchall()

    if request.method == "POST":
        check_csrf()
        statement_date = request.form.get("statement_date", "").strip()
        statement_bal = dollars_to_cents(request.form.get("statement_balance", ""))
        notes = request.form.get("notes", "").strip()
        if not statement_date:
            flash("Enter the bank statement date.", "error")
            return render_template(
                "trust_reconcile.html", account=acct, book_cents=book_cents,
                history=history)
        if statement_bal is None:
            flash("Enter a valid statement ending balance.", "error")
            return render_template(
                "trust_reconcile.html", account=acct, book_cents=book_cents,
                history=history)
        now = datetime.now(timezone.utc).isoformat()
        status = "matched" if statement_bal == book_cents else "unmatched"
        db.execute(
            "INSERT INTO trust_reconciliations (account_id, statement_date,"
            " statement_balance_cents, book_balance_cents, status, reconciled_by,"
            " reconciled_at, notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (account_id, statement_date, statement_bal, book_cents, status,
             session.get("user_id"), now, notes, now),
        )
        db.commit()
        audit("trust_reconcile",
              f"Reconciled trust account {account_id}: statement ${cents_to_str(statement_bal)}"
              f" vs book ${cents_to_str(book_cents)} -> {status}")
        if status == "matched":
            flash("Reconciliation complete: statement matches book balance.", "success")
        else:
            flash(
                f"Balances do NOT match: statement ${cents_to_str(statement_bal)} vs"
                f" book ${cents_to_str(book_cents)} (difference"
                f" ${cents_to_str(abs(statement_bal - book_cents))}). Recorded as"
                " unmatched — investigate before month-end.", "warning")
        return redirect(url_for("trust_reconcile", account_id=account_id))

    return render_template(
        "trust_reconcile.html", account=acct, book_cents=book_cents,
        history=history)


@app.route("/trust/reports/trial-balance")
@role_required("admin", "attorney")
def trust_trial_balance():
    """Trial balance: every client ledger per account; totals must equal account balances."""
    db = get_db()
    accounts = db.execute(
        "SELECT * FROM trust_accounts WHERE is_active = 1 ORDER BY name"
    ).fetchall()
    report = []
    for a in accounts:
        bals = trust_client_balances(db, a["id"])
        total = sum(b["bal"] for b in bals)
        book = account_trust_balance(db, a["id"])
        report.append({
            "account": dict(a),
            "client_balances": bals,
            "ledger_total_cents": total,
            "book_cents": book,
            "balanced": total == book,
        })
    return render_template("trust_trial_balance.html", report=report)


@app.route("/trust/reports/three-way")
@role_required("admin", "attorney")
def trust_three_way():
    """Three-way reconciliation: bank balance = book balance = sum of client ledgers."""
    db = get_db()
    accounts = db.execute(
        "SELECT * FROM trust_accounts WHERE is_active = 1 ORDER BY name"
    ).fetchall()
    report = []
    for a in accounts:
        book = account_trust_balance(db, a["id"])
        bals = trust_client_balances(db, a["id"])
        ledger_total = sum(b["bal"] for b in bals)
        last_recon = db.execute(
            "SELECT * FROM trust_reconciliations WHERE account_id = ?"
            " ORDER BY statement_date DESC LIMIT 1", (a["id"],)
        ).fetchone()
        bank = last_recon["statement_balance_cents"] if last_recon else None
        report.append({
            "account": dict(a),
            "bank_cents": bank,
            "book_cents": book,
            "ledger_total_cents": ledger_total,
            "bank_matches_book": bank is not None and bank == book,
            "book_matches_ledgers": book == ledger_total,
            "last_recon": dict(last_recon) if last_recon else None,
        })
    return render_template("trust_three_way.html", report=report)


# ----------------------------------------------------------------------------
# Backups (manual trigger + history)
# ----------------------------------------------------------------------------
@app.route("/backup/now", methods=["POST"])
@role_required("admin", "attorney")
def backup_now():
    check_csrf()
    ok, msg = do_backup(manual=True)
    audit("backup_manual", msg)
    flash(msg, "success" if ok else "error")
    return redirect(url_for("dashboard"))


@app.route("/backup/history")
@role_required("admin", "attorney")
def backup_history():
    db = get_db()
    rows = db.execute(
        "SELECT * FROM backups ORDER BY id DESC LIMIT 60"
    ).fetchall()
    return render_template(
        "backups.html", backups=rows, backup_dir=get_backup_dir(),
    )


# ----------------------------------------------------------------------------
# Software update (admin only)
# ----------------------------------------------------------------------------
@app.route("/admin/update")
@admin_required
def update_page():
    with _update_lock:
        info = dict(UPDATE_INFO)
    frozen = getattr(sys, "frozen", False)
    return render_template(
        "update.html", info=info, frozen=frozen,
        current_version=APP_VERSION,
    )


@app.route("/admin/update/check", methods=["POST"])
@admin_required
def update_check_now():
    check_csrf()
    check_for_updates()
    audit("update_check", "Manual update check requested.")
    return redirect(url_for("update_page"))


@app.route("/admin/update/apply", methods=["POST"])
@admin_required
def apply_update():
    check_csrf()
    if not getattr(sys, "frozen", False):
        flash(
            "This server is running from source code, not the installed "
            "version — update it with 'git pull' and restart instead.",
            "warning",
        )
        return redirect(url_for("update_page"))
    with _update_lock:
        asset_url = UPDATE_INFO.get("asset_url")
        available = UPDATE_INFO.get("available")
    if not available or not asset_url:
        flash("No update is available right now.", "warning")
        return redirect(url_for("update_page"))
    ok, msg = run_self_update(asset_url)
    flash(msg, "success" if ok else "error")
    # On success the process exits ~2s after the response is sent; the
    # helper batch file installs the new version and restarts the server.
    return redirect(url_for("update_page"))


# ----------------------------------------------------------------------------
# Audit log viewer
# ----------------------------------------------------------------------------
@app.route("/audit")
@role_required("admin", "attorney")
def audit_view():
    db = get_db()
    entries = db.execute(
        "SELECT * FROM audit_log ORDER BY id DESC LIMIT 200"
    ).fetchall()
    return render_template("audit.html", entries=entries)


# ----------------------------------------------------------------------------
# Error pages
# ----------------------------------------------------------------------------
@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404,
                           message="Page not found."), 404


@app.errorhandler(400)
def bad_request(e):
    return render_template("error.html", code=400,
                           message=str(e.description or "Bad request.")), 400


if __name__ == "__main__":
    import argparse
    import socket

    parser = argparse.ArgumentParser(
        description="Farhollow Law Firm - Case Management Server")
    parser.add_argument(
        "--local-only", "--host-only", dest="local_only",
        action="store_true",
        help="Bind to 127.0.0.1 only (this computer). "
             "Default is network mode: other office computers can connect.")
    parser.add_argument(
        "--port", type=int, default=5000,
        help="Port to listen on (default: 5000).")
    args = parser.parse_args()

    def get_lan_ip():
        """Best-effort LAN IP of this machine for the startup banner."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            # No traffic is sent; this just asks the OS which interface
            # would route outward.
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except OSError:
            return "127.0.0.1"

    with app.app_context():
        init_db()
    start_backup_scheduler()
    start_update_checker()

    if args.local_only:
        host = "127.0.0.1"
        print("\n  Farhollow Law Firm - Case Management  v%s" % APP_VERSION)
        print("  LOCAL-ONLY mode: this computer only.")
        print("  Open your browser to:  http://localhost:%d\n" % args.port)
    else:
        host = "0.0.0.0"
        lan_ip = get_lan_ip()
        print("\n" + "=" * 60)
        print("  Farhollow Law Firm - Case Management  v%s" % APP_VERSION)
        print("  NETWORK mode: office computers can connect.")
        print("")
        print("  This computer:        http://localhost:%d" % args.port)
        print("  Other office computers can connect at:")
        print("      http://%s:%d" % (lan_ip, args.port))
        print("")
        print("  WARNING: office network ONLY. Do NOT expose port %d" % args.port)
        print("  to the internet. See MAINTENANCE.md for firewall guidance.")
        print("=" * 60 + "\n")

    app.run(host=host, port=args.port, debug=False, threaded=True)
