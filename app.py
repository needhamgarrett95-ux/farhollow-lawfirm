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
    session, g, flash, abort, send_file,
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from crypto import encrypt_value, decrypt_value, looks_encrypted

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
            "must_change_password, created_at) VALUES (?, ?, ?, 1, ?)",
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
    """The packaged app has a single administrator account (username 'admin')."""
    return session.get("username") == "admin"


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not is_admin():
            abort(403)
        return f(*args, **kwargs)
    return decorated


@app.context_processor
def inject_update_info():
    """Make the app version and update status available in every template."""
    with _update_lock:
        info = dict(UPDATE_INFO)
    return {
        "app_version": APP_VERSION,
        "is_admin": is_admin(),
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
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
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
@login_required
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
@login_required
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
    if request.method == "POST":
        check_csrf()
        now = datetime.now(timezone.utc).isoformat()
        case_number = request.form.get("case_number", "").strip()
        if not case_number:
            flash("Case number is required.", "error")
            return render_template(
                "case_form.html", case=None, clients=clients,
                case_types=CASE_TYPES, statuses=CASE_STATUSES,
            )
        exists = db.execute(
            "SELECT id FROM cases WHERE case_number = ?", (case_number,)
        ).fetchone()
        if exists:
            flash("That case number is already in use.", "error")
            return render_template(
                "case_form.html", case=None, clients=clients,
                case_types=CASE_TYPES, statuses=CASE_STATUSES,
            )
        client_id = request.form.get("client_id", "").strip() or None
        cur = db.execute(
            "INSERT INTO cases (case_number, title, client_id, case_type, status,"
            " date_opened, notes, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                case_number,
                request.form.get("title", "").strip(),
                client_id,
                request.form.get("case_type", "other"),
                request.form.get("status", "active"),
                request.form.get("date_opened", "").strip(),
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


@app.route("/cases/<int:case_id>/delete", methods=["POST"])
@login_required
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
@login_required
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
@login_required
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
@login_required
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
# Billing & time tracking
# ----------------------------------------------------------------------------
@app.route("/cases/<int:case_id>/time", methods=["GET", "POST"])
@login_required
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
    return render_template(
        "time_entries.html", case=case, entries=entries,
        total_hours=total_hours, total_amount=total_amount,
        uninvoiced=uninvoiced, today=date.today().isoformat(),
    )


@app.route("/time/<int:entry_id>/delete", methods=["POST"])
@login_required
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
@login_required
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
@login_required
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
    return render_template(
        "invoice_form.html", clients=clients, preset_client=preset_client,
        uninvoiced=uninvoiced,
    )


@app.route("/invoices/<int:invoice_id>")
@login_required
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
@login_required
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
@login_required
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
@login_required
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
# Backups (manual trigger + history)
# ----------------------------------------------------------------------------
@app.route("/backup/now", methods=["POST"])
@login_required
def backup_now():
    check_csrf()
    ok, msg = do_backup(manual=True)
    audit("backup_manual", msg)
    flash(msg, "success" if ok else "error")
    return redirect(url_for("dashboard"))


@app.route("/backup/history")
@login_required
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
@login_required
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
@login_required
@admin_required
def update_check_now():
    check_csrf()
    check_for_updates()
    audit("update_check", "Manual update check requested.")
    return redirect(url_for("update_page"))


@app.route("/admin/update/apply", methods=["POST"])
@login_required
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
@login_required
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
