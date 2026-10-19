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
from payroll import (
    calculate_paycheck, weekly_hours, entry_hours, get_rate,
    PAY_PERIODS_PER_YEAR,
)
from paystub_pdf import build_paystub_pdf
from deadlines import (
    DEADLINE_RULES,
    TRIGGER_CHOICES,
    DISCLAIMER as DEADLINE_DISCLAIMER,
    calculate_deadlines,
    clallam_warnings,
    CLALLAM_CALENDARS_URL,
)

# ----------------------------------------------------------------------------
# App setup
# ----------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
os.makedirs(INSTANCE_DIR, exist_ok=True)

DB_PATH = os.path.join(INSTANCE_DIR, "lawfirm.db")
app = Flask(__name__)

# Session secret: generated fresh on EVERY server start (ephemeral, never
# written to disk). Restarting the server — including updates — invalidates
# all sessions, so everyone must log back in. This is intentional (security).
# NOTE: This is NOT the data encryption key (instance/data.key, see crypto.py),
# which must NEVER be rotated or encrypted client data becomes unrecoverable.
app.secret_key = secrets.token_hex(32)

SESSION_TIMEOUT_MINUTES = 30
# Browser-session cookie: no explicit expiry, dies when the browser closes.
app.config["SESSION_PERMANENT"] = False
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=SESSION_TIMEOUT_MINUTES)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
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
    source TEXT NOT NULL DEFAULT 'app',
    external_id TEXT NOT NULL DEFAULT '',
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
-- Dashboard widget customization. Each user can reorder / hide the
-- dashboard widgets; the layout is stored as a JSON list of
-- {"id": "<widget-id>", "visible": true} dicts in display order.
CREATE TABLE IF NOT EXISTS user_preferences (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    dashboard_layout TEXT,  -- JSON: [{"id": "deadlines", "visible": true}, ...] in display order
    theme TEXT NOT NULL DEFAULT 'light'  -- 'light' or 'dark'
);
-- Operating bookkeeping (firm's own money — separate from client trust funds).
-- Amounts stored as INTEGER cents, signed: income positive, expenses negative.
-- Balances always computed via SUM(); never stored.
CREATE TABLE IF NOT EXISTS coa_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    type TEXT NOT NULL,  -- income | expense | asset | liability | equity
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS op_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES coa_accounts(id),
    txn_date TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,  -- signed: + income/asset, - expense
    description TEXT NOT NULL,
    client_id INTEGER REFERENCES clients(id),
    case_id INTEGER REFERENCES cases(id),
    reference TEXT,
    receipt_path TEXT,
    invoice_id INTEGER REFERENCES invoices(id),  -- auto-created from paid invoices
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS op_reconciliations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES coa_accounts(id),
    statement_date TEXT NOT NULL,
    statement_balance_cents INTEGER NOT NULL,
    book_balance_cents INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    reconciled_by INTEGER REFERENCES users(id),
    reconciled_at TEXT,
    notes TEXT,
    created_at TEXT NOT NULL
);
-- Payroll. WA has no state income tax. Employee wage data is sensitive:
-- pay_rate_cents is encrypted at rest via crypto.py.
CREATE TABLE IF NOT EXISTS employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    full_name TEXT NOT NULL,
    pay_type TEXT NOT NULL DEFAULT 'hourly',  -- hourly | salary
    pay_rate_cents INTEGER NOT NULL,  -- hourly rate in cents, or ANNUAL salary in cents; encrypted
    pay_frequency TEXT NOT NULL DEFAULT 'biweekly',  -- weekly|biweekly|semimonthly|monthly
    filing_status TEXT NOT NULL DEFAULT 'single',  -- single | married
    allowances INTEGER NOT NULL DEFAULT 0,
    hire_date TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS timeclock_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    clock_in TEXT NOT NULL,   -- ISO datetime
    clock_out TEXT,           -- ISO datetime, NULL = currently clocked in
    manual_hours REAL,        -- set for manual entries instead of clock in/out
    entry_date TEXT NOT NULL, -- YYYY-MM-DD (for manual entries / grouping)
    notes TEXT,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS paychecks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    pay_period_start TEXT NOT NULL,
    pay_period_end TEXT NOT NULL,
    pay_date TEXT NOT NULL,
    reg_hours REAL NOT NULL DEFAULT 0,
    ot_hours REAL NOT NULL DEFAULT 0,
    gross_cents INTEGER NOT NULL,
    federal_cents INTEGER NOT NULL DEFAULT 0,
    ss_cents INTEGER NOT NULL DEFAULT 0,
    medicare_cents INTEGER NOT NULL DEFAULT 0,
    pfml_cents INTEGER NOT NULL DEFAULT 0,
    wacares_cents INTEGER NOT NULL DEFAULT 0,
    other_deductions_cents INTEGER NOT NULL DEFAULT 0,
    net_cents INTEGER NOT NULL,
    ytd_gross_cents INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL
);
-- Configurable tax rates. Rates change annually — the owner MUST verify
-- these against current IRS / WA ESD / WA L&I publications before running
-- payroll. Editable via the Tax Settings page (admin only).
CREATE TABLE IF NOT EXISTS tax_rates (
    key TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    value TEXT NOT NULL,
    help TEXT,
    effective_year INTEGER NOT NULL DEFAULT 2026,
    updated_at TEXT NOT NULL
);
-- Integrations (v2.2): OAuth-connected email + calendar providers.
-- Tokens are Fernet-encrypted at rest (see crypto.py). Firm-wide connection.
CREATE TABLE IF NOT EXISTS integrations (
    provider TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'disconnected',
    client_id TEXT NOT NULL DEFAULT '',
    client_secret_enc TEXT NOT NULL DEFAULT '',
    tokens_enc TEXT NOT NULL DEFAULT '',
    settings TEXT NOT NULL DEFAULT '{}',
    last_sync_at TEXT,
    last_error TEXT,
    fail_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
-- Synced email messages. case links live in email_case_links (many-to-many:
-- one email can relate to several cases for the same client).
CREATE TABLE IF NOT EXISTS synced_emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    external_id TEXT NOT NULL,
    thread_id TEXT,
    subject TEXT NOT NULL DEFAULT '',
    from_addr TEXT NOT NULL DEFAULT '',
    to_addr TEXT NOT NULL DEFAULT '',
    sent_at TEXT,
    snippet TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    direction TEXT NOT NULL DEFAULT 'inbound',
    synced_at TEXT NOT NULL,
    UNIQUE(provider, external_id)
);
CREATE TABLE IF NOT EXISTS email_case_links (
    email_id INTEGER NOT NULL REFERENCES synced_emails(id) ON DELETE CASCADE,
    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    link_type TEXT NOT NULL DEFAULT 'auto',
    created_at TEXT NOT NULL,
    PRIMARY KEY (email_id, case_id)
);
-- Maps app calendar events to their Google Calendar counterparts so the
-- two-way sync can update/delete instead of duplicating.
CREATE TABLE IF NOT EXISTS calendar_sync_map (
    app_event_id INTEGER PRIMARY KEY REFERENCES calendar_events(id)
        ON DELETE CASCADE,
    google_event_id TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
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


DEFAULT_COA = [
    # (code, name, type)
    ("4000", "Legal Fees", "income"),
    ("4010", "Consultation Fees", "income"),
    ("4020", "Other Income", "income"),
    ("1000", "Operating Checking", "asset"),
    ("1010", "Petty Cash", "asset"),
    ("1100", "Accounts Receivable", "asset"),
    ("1500", "Equipment", "asset"),
    ("2000", "Accounts Payable", "liability"),
    ("2010", "Credit Card", "liability"),
    ("2100", "Payroll Liabilities", "liability"),
    ("5000", "Rent", "expense"),
    ("5010", "Utilities", "expense"),
    ("5020", "Office Supplies", "expense"),
    ("5030", "Insurance", "expense"),
    ("5040", "Bar Dues", "expense"),
    ("5050", "CLE / Education", "expense"),
    ("5060", "Software & Subscriptions", "expense"),
    ("5070", "Marketing", "expense"),
    ("5080", "Travel", "expense"),
    ("5090", "Meals & Entertainment", "expense"),
    ("5100", "Professional Services", "expense"),
    ("5110", "Bank Fees", "expense"),
    ("5120", "Payroll Wages", "expense"),
    ("5130", "Payroll Taxes (Employer)", "expense"),
    ("5990", "Other Expenses", "expense"),
    ("3000", "Owner's Capital", "equity"),
    ("3100", "Owner's Draw", "equity"),
    ("3200", "Capital Contributions", "equity"),
]

# Default tax rates. THESE ARE ESTIMATES — the owner MUST verify against
# current IRS Publication 15-T, WA ESD, and WA L&I publications before
# running payroll. All editable via Tax Settings (admin only).
DEFAULT_TAX_RATES = [
    # key, label, value, help
    ("fed_std_ded_single", "Federal standard deduction — Single (annual $)",
     "15750", "IRS 2026 estimate. Subtracted from annualized wages before applying withholding brackets."),
    ("fed_std_ded_married", "Federal standard deduction — Married (annual $)",
     "31500", "IRS 2026 estimate."),
    ("fed_brackets_single", "Federal withholding brackets — Single",
     "12275:10,49900:12,106450:22,203250:24,258050:32,645250:35,99999999:37",
     "Percentage-method brackets (2026 estimate). Format: upper_bound:rate_pct, ... Applied to annualized taxable wages."),
    ("fed_brackets_married", "Federal withholding brackets — Married",
     "24550:10,99800:12,212900:22,406500:24,516100:32,99999999:37",
     "Percentage-method brackets (2026 estimate)."),
    ("ss_rate", "Social Security rate — employee (%)", "6.2",
     "Withheld from paycheck."),
    ("ss_wage_base", "Social Security wage base (annual $)", "184500",
     "2026 estimate. No SS withheld above this YTD amount."),
    ("ss_rate_employer", "Social Security rate — employer (%)", "6.2",
     "Employer cost, not deducted from paycheck."),
    ("medicare_rate", "Medicare rate — employee (%)", "1.45", "Withheld from paycheck."),
    ("medicare_rate_employer", "Medicare rate — employer (%)", "1.45",
     "Employer cost, not deducted from paycheck."),
    ("medicare_addl_rate", "Additional Medicare rate over $200k (%)", "0.9",
     "Employee-paid on wages over $200,000."),
    ("pfml_total_rate", "WA PFML total premium rate (%)", "0.92",
     "WA Paid Family & Medical Leave. Verify current ESD rate annually."),
    ("pfml_employee_share", "WA PFML employee share of total (%)", "71.43",
     "Small employers (<50 staff) do not pay the employer share; employee pays this share of the total."),
    ("pfml_employer_pays", "WA PFML employer pays its share (1=yes, 0=no)", "0",
     "Set to 1 only if the firm has 50+ employees."),
    ("wacares_rate", "WA Cares (long-term care) rate — employee (%)", "0.58",
     "Employee-paid. Verify current rate annually."),
    ("sui_rate", "WA unemployment (SUI) rate — employer (%)", "1.5",
     "Employer-paid. Actual rate varies by employer experience rating — verify with ESD."),
    ("sui_wage_base", "WA SUI taxable wage base (annual $)", "74000",
     "Verify current ESD wage base annually."),
    ("li_rate_per_hour", "WA workers' comp (L&I) — employer cost per hour ($)", "0.25",
     "Employer-paid. Actual rate depends on risk class — verify with L&I. Office work is low; this is a placeholder."),
]


def _seed_coa(db):
    """Insert the default chart of accounts if the table is empty."""
    row = db.execute("SELECT COUNT(*) AS c FROM coa_accounts").fetchone()
    if row["c"] > 0:
        return
    now = datetime.now(timezone.utc).isoformat()
    for code, name, atype in DEFAULT_COA:
        db.execute(
            "INSERT INTO coa_accounts (code, name, type, is_active, created_at)"
            " VALUES (?, ?, ?, 1, ?)",
            (code, name, atype, now),
        )
    db.commit()


def _seed_tax_rates(db):
    """Insert default tax rates for any missing keys (never overwrites)."""
    now = datetime.now(timezone.utc).isoformat()
    for key, label, value, help_text in DEFAULT_TAX_RATES:
        row = db.execute("SELECT 1 FROM tax_rates WHERE key = ?", (key,)).fetchone()
        if not row:
            db.execute(
                "INSERT INTO tax_rates (key, label, value, help, effective_year, updated_at)"
                " VALUES (?, ?, ?, ?, 2026, ?)",
                (key, label, value, help_text, now),
            )
    db.commit()


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
    # Granular permissions (v2.1): JSON dict on users.permissions. Backfill
    # from the role preset for existing users.
    if "permissions" not in ucols:
        db.execute("ALTER TABLE users ADD COLUMN permissions TEXT")
        db.commit()
    for urow in db.execute("SELECT id, role, permissions FROM users").fetchall():
        if not urow["permissions"]:
            preset = role_default_permissions(urow["role"] or "staff")
            db.execute(
                "UPDATE users SET permissions = ? WHERE id = ?",
                (json.dumps(preset), urow["id"]),
            )
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

    # Migration for v2.0: dashboard widget customization + theme preference.
    # SCHEMA's CREATE TABLE IF NOT EXISTS only runs at full init, so make
    # sure existing databases get the table too. Also backfill the theme
    # column for databases created before it was added.
    db.execute(
        """CREATE TABLE IF NOT EXISTS user_preferences (
            user_id INTEGER PRIMARY KEY REFERENCES users(id),
            dashboard_layout TEXT,
            theme TEXT NOT NULL DEFAULT 'light'
        )"""
    )
    pcols = [r["name"] for r in db.execute("PRAGMA table_info(user_preferences)").fetchall()]
    if "theme" not in pcols:
        db.execute("ALTER TABLE user_preferences ADD COLUMN theme TEXT NOT NULL DEFAULT 'light'")
    db.commit()

    # Migration for v2.1: operating bookkeeping + payroll tables. CREATE TABLE
    # IF NOT EXISTS in SCHEMA handles fresh installs; ensure existing DBs
    # get the new tables too.
    for _ddl in (
        """CREATE TABLE IF NOT EXISTS coa_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL, type TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS op_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL REFERENCES coa_accounts(id),
            txn_date TEXT NOT NULL, amount_cents INTEGER NOT NULL,
            description TEXT NOT NULL, client_id INTEGER REFERENCES clients(id),
            case_id INTEGER REFERENCES cases(id), reference TEXT,
            receipt_path TEXT, invoice_id INTEGER REFERENCES invoices(id),
            created_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS op_reconciliations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL REFERENCES coa_accounts(id),
            statement_date TEXT NOT NULL, statement_balance_cents INTEGER NOT NULL,
            book_balance_cents INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            reconciled_by INTEGER REFERENCES users(id), reconciled_at TEXT,
            notes TEXT, created_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id), full_name TEXT NOT NULL,
            pay_type TEXT NOT NULL DEFAULT 'hourly', pay_rate_cents INTEGER NOT NULL,
            pay_frequency TEXT NOT NULL DEFAULT 'biweekly',
            filing_status TEXT NOT NULL DEFAULT 'single',
            allowances INTEGER NOT NULL DEFAULT 0, hire_date TEXT,
            is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS timeclock_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL REFERENCES employees(id),
            clock_in TEXT NOT NULL, clock_out TEXT, manual_hours REAL,
            entry_date TEXT NOT NULL, notes TEXT,
            created_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS paychecks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL REFERENCES employees(id),
            pay_period_start TEXT NOT NULL, pay_period_end TEXT NOT NULL,
            pay_date TEXT NOT NULL, reg_hours REAL NOT NULL DEFAULT 0,
            ot_hours REAL NOT NULL DEFAULT 0, gross_cents INTEGER NOT NULL,
            federal_cents INTEGER NOT NULL DEFAULT 0, ss_cents INTEGER NOT NULL DEFAULT 0,
            medicare_cents INTEGER NOT NULL DEFAULT 0, pfml_cents INTEGER NOT NULL DEFAULT 0,
            wacares_cents INTEGER NOT NULL DEFAULT 0,
            other_deductions_cents INTEGER NOT NULL DEFAULT 0,
            net_cents INTEGER NOT NULL, ytd_gross_cents INTEGER NOT NULL DEFAULT 0,
            created_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS tax_rates (
            key TEXT PRIMARY KEY, label TEXT NOT NULL, value TEXT NOT NULL,
            help TEXT, effective_year INTEGER NOT NULL DEFAULT 2026,
            updated_at TEXT NOT NULL)""",
    ):
        db.execute(_ddl)
    db.commit()

    _seed_coa(db)
    _seed_tax_rates(db)

    # Migration for v2.2: integrations tables. CREATE TABLE IF NOT EXISTS in
    # SCHEMA handles fresh installs; ensure existing DBs get them too.
    # Also add source/external tracking columns to calendar_events for the
    # Google Calendar two-way sync.
    for _ddl in (
        """CREATE TABLE IF NOT EXISTS integrations (
            provider TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'disconnected',
            client_id TEXT NOT NULL DEFAULT '', client_secret_enc TEXT NOT NULL DEFAULT '',
            tokens_enc TEXT NOT NULL DEFAULT '', settings TEXT NOT NULL DEFAULT '{}',
            last_sync_at TEXT, last_error TEXT, fail_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS synced_emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT NOT NULL,
            external_id TEXT NOT NULL, thread_id TEXT,
            subject TEXT NOT NULL DEFAULT '', from_addr TEXT NOT NULL DEFAULT '',
            to_addr TEXT NOT NULL DEFAULT '', sent_at TEXT,
            snippet TEXT NOT NULL DEFAULT '', body TEXT NOT NULL DEFAULT '',
            direction TEXT NOT NULL DEFAULT 'inbound', synced_at TEXT NOT NULL,
            UNIQUE(provider, external_id))""",
        """CREATE TABLE IF NOT EXISTS email_case_links (
            email_id INTEGER NOT NULL REFERENCES synced_emails(id) ON DELETE CASCADE,
            case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
            link_type TEXT NOT NULL DEFAULT 'auto', created_at TEXT NOT NULL,
            PRIMARY KEY (email_id, case_id))""",
        """CREATE TABLE IF NOT EXISTS calendar_sync_map (
            app_event_id INTEGER PRIMARY KEY REFERENCES calendar_events(id)
                ON DELETE CASCADE,
            google_event_id TEXT NOT NULL, updated_at TEXT NOT NULL)""",
    ):
        db.execute(_ddl)
    _ce_cols = [r["name"] for r in
                db.execute("PRAGMA table_info(calendar_events)").fetchall()]
    if "source" not in _ce_cols:
        db.execute("ALTER TABLE calendar_events ADD COLUMN source TEXT"
                   " NOT NULL DEFAULT 'app'")
    if "external_id" not in _ce_cols:
        db.execute("ALTER TABLE calendar_events ADD COLUMN external_id TEXT"
                   " NOT NULL DEFAULT ''")
    db.commit()

    # Seed default admin on first run
    row = db.execute("SELECT COUNT(*) AS c FROM users").fetchone()
    if row["c"] == 0:
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO users (username, password_hash, full_name, "
            "must_change_password, role, is_active, permissions, created_at)"
            " VALUES (?, ?, ?, 1, 'admin', 1, ?, ?)",
            ("admin", generate_password_hash("changeme123"), "Administrator",
             json.dumps(role_default_permissions("admin")), now),
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
    try:
        user_id = session.get("user_id")
        username = session.get("username")
    except RuntimeError:
        # Background threads (backup scheduler, schedule monitor) have no
        # request context — log as the system instead of crashing.
        user_id, username = None, "system"
    db.execute(
        "INSERT INTO audit_log (timestamp, user_id, username, action, details)"
        " VALUES (?, ?, ?, ?, ?)",
        (
            datetime.now(timezone.utc).isoformat(),
            user_id,
            username,
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


# ----------------------------------------------------------------------------
# Clallam County court schedule monitor
#
# Weekly poll of the Friday Judge Bench Assignments spreadsheet published by
# Clallam County Superior Court. The county marks changes with "*" and an
# "Updated MM/DD/YY" header. We fetch the document, compare a content hash
# (plus the parsed "Updated" date when present) against the stored baseline,
# and raise a dashboard alert + audit entry when it changes. We never modify
# deadlines automatically — the attorney reviews and decides.
# ----------------------------------------------------------------------------
CLALLAM_SCHEDULE_CHECK_INTERVAL = 7 * 24 * 3600  # weekly
CLALLAM_MAX_FETCH_FAILURES = 4  # then warn the schedule is unreachable


def _meta_get(key, default=""):
    db = get_db()
    row = db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def _meta_set(key, value):
    db = get_db()
    db.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
        (key, str(value)),
    )
    db.commit()


def _fetch_clallam_schedule():
    """Return (updated_str, content_hash) or raise."""
    import hashlib
    import re
    import urllib.request

    from deadlines import CLALLAM_JUDGE_CALENDAR_URL

    req = urllib.request.Request(
        CLALLAM_JUDGE_CALENDAR_URL,
        headers={"User-Agent": "LawFirmCaseManagement/schedule-monitor"},
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        raw = resp.read()
    content_hash = hashlib.sha256(raw).hexdigest()
    # The document header shows "Updated MM/DD/YY". The file is an xlsx served
    # through DocumentCenter; when it comes back as HTML the date is parseable.
    # If it's binary, we fall back to hash-only comparison.
    updated_str = ""
    try:
        text = raw.decode("utf-8", errors="ignore")
        m = re.search(r"Updated\s+(\d{1,2}/\d{1,2}/\d{2,4})", text, re.IGNORECASE)
        if m:
            updated_str = m.group(1)
    except Exception:
        pass
    return updated_str, content_hash


def clallam_schedule_check():
    """One poll of the Clallam Friday judge calendar. Returns a status string."""
    try:
        updated_str, content_hash = _fetch_clallam_schedule()
    except Exception as e:  # noqa: BLE001 — network failure is expected sometimes
        fails = int(_meta_get("clallam_cal_failures", "0") or 0) + 1
        _meta_set("clallam_cal_failures", fails)
        _meta_set("clallam_cal_last_check",
                  datetime.now(timezone.utc).isoformat())
        if fails >= CLALLAM_MAX_FETCH_FAILURES and not _meta_get("clallam_cal_alert"):
            msg = (
                "Could not reach the Clallam County Friday judge calendar "
                f"({fails} failed checks). Verify the schedule manually at "
                f"{CLALLAM_CALENDARS_URL}."
            )
            _meta_set("clallam_cal_alert", "1")
            _meta_set("clallam_cal_alert_msg", msg)
            audit("clallam_schedule_unreachable", msg)
            return "unreachable-alert"
        return f"fetch-failed ({e})"
    _meta_set("clallam_cal_failures", "0")
    _meta_set("clallam_cal_last_check", datetime.now(timezone.utc).isoformat())
    prev_hash = _meta_get("clallam_cal_hash")
    prev_updated = _meta_get("clallam_cal_updated")
    if not prev_hash:
        # First successful check: establish the baseline, no alert.
        _meta_set("clallam_cal_hash", content_hash)
        _meta_set("clallam_cal_updated", updated_str)
        return "baseline-established"
    changed = (content_hash != prev_hash) or (
        updated_str and prev_updated and updated_str != prev_updated
    )
    if changed:
        msg = (
            "The Clallam County Friday judge calendar may have changed "
            f"(was '{prev_updated or 'unknown'}', now '{updated_str or 'unknown'}'). "
            f"Review judge assignments at {CLALLAM_CALENDARS_URL} before your "
            "next Friday hearing."
        )
        _meta_set("clallam_cal_hash", content_hash)
        _meta_set("clallam_cal_updated", updated_str)
        _meta_set("clallam_cal_alert", "1")
        _meta_set("clallam_cal_alert_msg", msg)
        audit("clallam_schedule_change", msg)
        return "changed-alert"
    return "no-change"


def clallam_schedule_monitor():
    """Background thread: weekly poll of the Clallam court schedule."""
    time.sleep(120)  # let the server finish starting first
    while True:
        try:
            with app.app_context():
                status = clallam_schedule_check()
                print(f"  [clallam-schedule] {status}")
        except Exception as e:  # noqa: BLE001 — monitor must never die loudly
            print(f"  [clallam-schedule] monitor error: {e}")
        time.sleep(CLALLAM_SCHEDULE_CHECK_INTERVAL)


def start_clallam_schedule_monitor():
    t = threading.Thread(target=clallam_schedule_monitor, daemon=True,
                         name="clallam-schedule-monitor")
    t.start()


def get_clallam_schedule_alert():
    """Return the active schedule-change alert message, or '' if none."""
    if _meta_get("clallam_cal_alert") == "1":
        return _meta_get("clallam_cal_alert_msg")
    return ""


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
        # Refresh role + active status + permissions from the database on
        # every request so admin changes take effect immediately.
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
        session["permissions"] = get_user_permissions(db, session["user_id"])
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


# ----------------------------------------------------------------------------
# Granular permissions (v2.1). Roles are presets/templates — the admin can
# customize individual permissions per user on the user edit page.
# Stored as JSON in users.permissions; refreshed into the session on every
# request by login_required, so changes take effect immediately.
# ----------------------------------------------------------------------------
PERMISSIONS = [
    # (key, group, label)
    ("view_dashboard", "General", "View dashboard"),
    ("view_clients", "Clients", "View client list and details"),
    ("manage_clients", "Clients", "Add and edit clients"),
    ("view_client_ssn", "Clients", "View sensitive fields (SSN, DOB)"),
    ("view_cases", "Cases", "View cases"),
    ("manage_cases", "Cases", "Add and edit cases"),
    ("view_calendar", "Calendar", "View calendar"),
    ("manage_calendar", "Calendar", "Add and edit events"),
    ("view_documents", "Documents", "View and download documents"),
    ("manage_documents", "Documents", "Upload documents"),
    ("view_billing", "Billing", "View invoices"),
    ("manage_billing", "Billing", "Create and manage invoices"),
    ("view_trust", "Trust", "View trust accounts and ledgers"),
    ("manage_trust", "Trust", "Record trust transactions and reconcile"),
    ("use_templates", "Templates", "Use document templates"),
    ("calculate_deadlines", "Deadlines", "Use the deadline calculator"),
    ("push_deadlines", "Deadlines", "Push deadlines to the calendar"),
    ("view_accounting", "Accounting", "View bookkeeping reports"),
    ("manage_accounting", "Accounting", "Record transactions, manage accounts"),
    ("run_payroll", "Payroll", "Manage employees and run payroll"),
    ("view_paystubs", "Payroll", "View and print paystubs"),
    ("use_timeclock", "Timeclock", "Clock in and out"),
    ("view_audit_log", "Audit Log", "View the audit log"),
    ("manage_backups", "Backups", "Run and view backups"),
    ("manage_users", "Users", "Manage users and permissions"),
    ("delete_records", "General", "Delete records (clients, cases, etc.)"),
]

PERM_GROUPS = ["General", "Clients", "Cases", "Calendar", "Documents", "Billing",
               "Trust", "Templates", "Deadlines", "Accounting", "Payroll",
               "Timeclock", "Audit Log", "Backups", "Users"]

# manage_* implies the corresponding view_* (expanded at load time).
PERM_IMPLICATIONS = {
    "manage_clients": ("view_clients",),
    "manage_cases": ("view_cases",),
    "manage_calendar": ("view_calendar",),
    "manage_documents": ("view_documents",),
    "manage_billing": ("view_billing",),
    "manage_trust": ("view_trust",),
    "manage_accounting": ("view_accounting",),
    "run_payroll": ("view_paystubs",),
    "push_deadlines": ("calculate_deadlines",),
}

_ALL_PERM_KEYS = [p[0] for p in PERMISSIONS]


def role_default_permissions(role):
    """Default permission set for a role preset. Returns {perm: bool}."""
    if role == "admin":
        return {k: True for k in _ALL_PERM_KEYS}
    if role == "attorney":
        excluded = {"manage_users", "manage_accounting", "run_payroll"}
        return {k: (k not in excluded) for k in _ALL_PERM_KEYS}
    if role == "accountant":
        granted = {
            "view_dashboard", "view_clients",
            "view_billing", "manage_billing",
            "view_trust", "manage_trust",
            "view_accounting", "manage_accounting",
            "run_payroll", "view_paystubs",
            "use_timeclock",
        }
        return {k: (k in granted) for k in _ALL_PERM_KEYS}
    # staff (default)
    granted = {
        "view_dashboard",
        "view_clients", "manage_clients",
        "view_cases", "manage_cases",
        "view_calendar", "manage_calendar",
        "view_documents", "manage_documents",
        "calculate_deadlines",
        "use_timeclock",
    }
    return {k: (k in granted) for k in _ALL_PERM_KEYS}


def expand_permissions(raw):
    """Expand manage_* implications so checks are simple lookups."""
    perms = dict(raw)
    for granter, implied in PERM_IMPLICATIONS.items():
        if perms.get(granter):
            for p in implied:
                perms[p] = True
    # Ensure every known key exists
    for k in _ALL_PERM_KEYS:
        perms.setdefault(k, False)
    return perms


# ----------------------------------------------------------------------------
# Navigation — SINGLE SOURCE OF TRUTH. Every tab maps 1:1 to a permission.
# If the user has the permission, the tab shows; the tab's target route
# checks that same permission. No tab may lead to a 403.
# ----------------------------------------------------------------------------
NAV_ITEMS = [
    {"label": "Dashboard", "icon": "dashboard", "endpoint": "dashboard",
     "permission": "view_dashboard", "active_prefixes": ["dashboard"]},
    {"label": "Clients", "icon": "clients", "endpoint": "client_list",
     "permission": "view_clients", "active_prefixes": ["client"]},
    {"label": "Cases", "icon": "cases", "endpoint": "case_list",
     "permission": "view_cases", "active_prefixes": ["case"]},
    {"label": "Calendar", "icon": "calendar", "endpoint": "calendar_view",
     "permission": "view_calendar", "active_prefixes": ["calendar", "event"]},
    {"label": "Deadlines", "icon": "deadlines", "endpoint": "deadline_calculator",
     "permission": "calculate_deadlines", "active_prefixes": ["deadline", "clallam"],
     "badge": "nav_deadline_count"},
    {"label": "Templates", "icon": "templates", "endpoint": "template_gallery",
     "permission": "use_templates", "active_prefixes": ["template"]},
    {"label": "Billing", "icon": "billing", "endpoint": "invoice_list",
     "permission": "view_billing", "active_prefixes": ["invoice", "time"]},
    {"label": "Trust", "icon": "trust", "endpoint": "trust_overview",
     "permission": "view_trust", "active_prefixes": ["trust"]},
    {"label": "Accounting", "icon": "billing", "endpoint": "accounting_overview",
     "permission": "view_accounting",
     "active_prefixes": ["accounting", "op_", "employee", "payroll", "timeclock",
                         "report_", "coa_", "tax_"]},
    {"label": "Audit Log", "icon": "documents", "endpoint": "audit_view",
     "permission": "view_audit_log", "active_prefixes": ["audit"]},
    {"label": "Users", "icon": "users", "endpoint": "user_list",
     "permission": "manage_users", "active_prefixes": ["user"]},
    {"label": "Integrations", "icon": "plug", "endpoint": "integration_list",
     "permission": "manage_users", "active_prefixes": ["integration"]},
]


def first_allowed_endpoint(user_perms):
    """First nav tab the user can access (for post-login redirect)."""
    for item in NAV_ITEMS:
        if user_has_perm(user_perms, item["permission"]):
            return item["endpoint"]
    return "dashboard"  # fallback; will 403 only if admin revoked everything


def get_user_permissions(db, user_id):
    """Load and expand a user's permission dict. Falls back to role preset."""
    row = db.execute(
        "SELECT role, permissions FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    if not row:
        return expand_permissions(role_default_permissions("staff"))
    raw = {}
    if row["permissions"]:
        try:
            raw = json.loads(row["permissions"])
        except (ValueError, TypeError):
            raw = {}
    if not raw:
        raw = role_default_permissions(row["role"] or "staff")
    # Only keep known keys
    raw = {k: bool(v) for k, v in raw.items() if k in _ALL_PERM_KEYS}
    return expand_permissions(raw)


def user_has_perm(perms, perm):
    """True if the (expanded) permission dict grants perm."""
    return bool(perms.get(perm))


def permission_required(*perms):
    """Route requires ANY of the given permissions. Includes login check."""

    def decorator(f):
        @wraps(f)
        @login_required
        def decorated(*args, **kwargs):
            user_perms = session.get("permissions", {})
            if not any(user_has_perm(user_perms, p) for p in perms):
                abort(403, description="You do not have permission to access this page.")
            return f(*args, **kwargs)

        return decorated

    return decorator


def count_manage_users_holders(db, exclude_user_id=None):
    """Count active users with the manage_users permission (for safety checks)."""
    count = 0
    q = "SELECT id, is_active, permissions, role FROM users WHERE is_active = 1"
    for row in db.execute(q).fetchall():
        if exclude_user_id and row["id"] == exclude_user_id:
            continue
        perms = get_user_permissions(db, row["id"])
        if perms.get("manage_users"):
            count += 1
    return count


@app.template_filter("cents")
def _cents_filter(value):
    """Format integer cents as dollars in templates: {{ 123456|cents }} -> 1,234.56"""
    return cents_to_str(value)


@app.context_processor
def inject_update_info():
    """Make the app version and update status available in every template."""
    with _update_lock:
        info = dict(UPDATE_INFO)
    # Theme preference (per-user, defaults to light)
    theme = "light"
    nav_deadline_count = 0
    uid = session.get("user_id")
    if uid:
        try:
            theme = get_user_theme(uid)
        except Exception:
            pass
        try:
            db = get_db()
            soon = (date.today() + timedelta(days=7)).isoformat()
            nav_deadline_count = db.execute(
                "SELECT COUNT(*) AS c FROM calendar_events"
                " WHERE completed = 0 AND event_date <= ?",
                (soon,),
            ).fetchone()["c"]
        except Exception:
            pass
    # Build nav items with active flags (single source of truth: NAV_ITEMS)
    endpoint = request.endpoint or ""
    nav_items = []
    for item in NAV_ITEMS:
        nav_items.append({
            **item,
            "active": any(endpoint.startswith(p) for p in item["active_prefixes"]),
        })
    return {
        "app_version": APP_VERSION,
        "is_admin": is_admin(),
        "user_role": session.get("role", "staff"),
        "perms": session.get("permissions", {}),
        "nav_items": nav_items,
        "theme": theme,
        "nav_deadline_count": nav_deadline_count,
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
            session["permissions"] = get_user_permissions(db, user["id"])
            return redirect(url_for(first_allowed_endpoint(session["permissions"])))
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
VALID_ROLES = ("admin", "attorney", "accountant", "staff")


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
@permission_required("manage_users")
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
@permission_required("manage_users")
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
            # Permissions: start from the role preset, apply checkbox overrides.
            perms = _permissions_from_form(role)
            now = datetime.now(timezone.utc).isoformat()
            db.execute(
                "INSERT INTO users (username, password_hash, full_name, "
                "must_change_password, role, is_active, permissions, created_at)"
                " VALUES (?, ?, ?, 1, ?, 1, ?, ?)",
                (username, generate_password_hash(password), full_name, role,
                 json.dumps(perms), now),
            )
            db.commit()
            audit("user_created", f"Created user '{username}' with role '{role}'")
            flash(f"User '{username}' created. They must change their password on first login.", "success")
            return redirect(url_for("user_list"))
    return render_template(
        "user_form.html", user=None, roles=VALID_ROLES,
        permissions=PERMISSIONS, perm_groups=PERM_GROUPS,
        role_presets={r: role_default_permissions(r) for r in VALID_ROLES},
        current_perms=role_default_permissions("staff"),
    )


def _permissions_from_form(default_role):
    """Build a permission dict from submitted checkboxes, falling back to
    the role preset when no checkbox data was submitted."""
    perms = {}
    any_submitted = False
    for key in _ALL_PERM_KEYS:
        if f"perm_{key}" in request.form:
            any_submitted = True
            perms[key] = True
    if not any_submitted:
        return role_default_permissions(default_role)
    # Unchecked boxes are False; expand implications
    full = {k: (k in perms) for k in _ALL_PERM_KEYS}
    return expand_permissions(full)


@app.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@permission_required("manage_users")
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
        new_perms = _permissions_from_form(role)
        is_self = user["id"] == session["user_id"]
        if not full_name:
            flash("Full name is required.", "error")
        elif role not in VALID_ROLES:
            flash("Invalid role selected.", "error")
        elif is_self and not is_active:
            flash("You cannot deactivate your own account.", "error")
        elif is_self and not new_perms.get("manage_users"):
            flash("You cannot remove your own user-management permission.", "error")
        elif (not new_perms.get("manage_users")
                and count_manage_users_holders(db, exclude_user_id=user["id"]) < 1):
            flash("You cannot remove the last user with user-management permission.", "error")
        else:
            changes = []
            if full_name != user["full_name"]:
                changes.append(f"name -> '{full_name}'")
            if role != user["role"]:
                changes.append(f"role {user['role']} -> {role}")
            if is_active != user["is_active"]:
                changes.append("deactivated" if not is_active else "reactivated")
            old_perms = get_user_permissions(db, user["id"])
            perm_changes = [k for k in _ALL_PERM_KEYS
                            if bool(old_perms.get(k)) != bool(new_perms.get(k))]
            if perm_changes:
                changes.append(f"permissions changed: {', '.join(perm_changes)}")
            db.execute(
                "UPDATE users SET full_name = ?, role = ?, is_active = ?, permissions = ?"
                " WHERE id = ?",
                (full_name, role, is_active, json.dumps(new_perms), user["id"]),
            )
            db.commit()
            audit("user_updated", f"Updated user '{user['username']}': " + (", ".join(changes) or "no changes"))
            flash(f"User '{user['username']}' updated.", "success")
            return redirect(url_for("user_list"))
        # Re-fetch so the form re-renders with submitted values on error
        user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    current_perms = get_user_permissions(db, user["id"])
    return render_template(
        "user_form.html", user=user, roles=VALID_ROLES,
        permissions=PERMISSIONS, perm_groups=PERM_GROUPS,
        role_presets={r: role_default_permissions(r) for r in VALID_ROLES},
        current_perms=current_perms,
    )


@app.route("/users/<int:user_id>/reset-password", methods=["POST"])
@permission_required("manage_users")
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
@permission_required("manage_users")
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
@permission_required("manage_users")
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
# Dashboard widget customization (v2.0)
# ----------------------------------------------------------------------------
# The default widget order/visibility for the dashboard. Each widget dict is
# {"id": <widget-id>, "visible": bool}. The frontend renders widgets in the
# order of this list (or the user's saved override).
DEFAULT_DASHBOARD_WIDGETS = [
    {"id": "alerts", "visible": True},      # overdue + schedule alerts
    {"id": "deadlines", "visible": True},   # filing deadlines timeline
    {"id": "schedule", "visible": True},    # today's schedule
    {"id": "actions", "visible": True},     # quick actions
    {"id": "trust", "visible": True},       # trust balance (attorney/admin only)
    {"id": "caseload", "visible": True},    # caseload donut
    {"id": "clients", "visible": True},     # recent clients
    {"id": "week", "visible": True},        # this week events
    {"id": "backup", "visible": True},      # backup status (attorney/admin only)
]
KNOWN_DASHBOARD_WIDGETS = {w["id"] for w in DEFAULT_DASHBOARD_WIDGETS}


def get_dashboard_layout(user_id):
    """Return the user's dashboard widget layout: list of {id, visible} dicts
    in display order. Falls back to DEFAULT_DASHBOARD_WIDGETS when the user
    has not saved a customization."""
    db = get_db()
    row = db.execute(
        "SELECT dashboard_layout FROM user_preferences WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if row and row["dashboard_layout"]:
        try:
            saved = json.loads(row["dashboard_layout"])
            if isinstance(saved, list) and saved:
                cleaned = []
                seen = set()
                for w in saved:
                    wid = (w or {}).get("id")
                    if wid in KNOWN_DASHBOARD_WIDGETS and wid not in seen:
                        cleaned.append({"id": wid, "visible": bool(w.get("visible", True))})
                        seen.add(wid)
                # Append any new widgets the user never saw (added since save).
                for wid in [d["id"] for d in DEFAULT_DASHBOARD_WIDGETS]:
                    if wid not in seen:
                        cleaned.append({"id": wid, "visible": True})
                if cleaned:
                    return cleaned
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass
    return [{"id": w["id"], "visible": w["visible"]} for w in DEFAULT_DASHBOARD_WIDGETS]


def save_dashboard_layout(user_id, layout):
    """Validate and persist a user's dashboard widget layout.

    layout: list of {"id": ..., "visible": bool} dicts. Unknown widget ids
    are rejected (ValueError). Unknowns aside, any missing known widgets are
    appended as visible, and order follows the given list.
    """
    if not isinstance(layout, list) or not layout:
        raise ValueError("layout must be a non-empty list")
    cleaned = []
    seen = set()
    for w in layout:
        if not isinstance(w, dict):
            raise ValueError("each widget must be an object with id and visible")
        wid = w.get("id")
        if wid not in KNOWN_DASHBOARD_WIDGETS:
            raise ValueError(f"unknown widget id: {wid!r}")
        if wid in seen:
            raise ValueError(f"duplicate widget id: {wid!r}")
        cleaned.append({"id": wid, "visible": bool(w.get("visible", True))})
        seen.add(wid)
    for wid in [d["id"] for d in DEFAULT_DASHBOARD_WIDGETS]:
        if wid not in seen:
            cleaned.append({"id": wid, "visible": True})
    db = get_db()
    db.execute(
        "INSERT INTO user_preferences (user_id, dashboard_layout)"
        " VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET dashboard_layout = excluded.dashboard_layout",
        (user_id, json.dumps(cleaned)),
    )
    db.commit()
    return cleaned


# ----------------------------------------------------------------------------
# Theme preference (v2.0)
# ----------------------------------------------------------------------------
THEMES = ("light", "dark")


def get_user_theme(user_id):
    """Return the user's theme preference: 'light' or 'dark'."""
    db = get_db()
    row = db.execute(
        "SELECT theme FROM user_preferences WHERE user_id = ?", (user_id,)
    ).fetchone()
    theme = (row["theme"] if row and row["theme"] else "light")
    return theme if theme in THEMES else "light"


def set_user_theme(user_id, theme):
    """Validate and save the user's theme ('light' or 'dark'). Only updates
    the theme column so the saved dashboard layout is never clobbered."""
    if theme not in THEMES:
        raise ValueError(f"unknown theme: {theme!r}; must be 'light' or 'dark'")
    db = get_db()
    db.execute(
        "INSERT INTO user_preferences (user_id, theme)"
        " VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET theme = excluded.theme",
        (user_id, theme),
    )
    db.commit()
    return theme


# ----------------------------------------------------------------------------
# Dashboard
# ----------------------------------------------------------------------------
@app.route("/dashboard")
@permission_required("view_dashboard")
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
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
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
    # v2.0 widgets: today's schedule and the rest of this week.
    today_events = db.execute(
        "SELECT e.*, c.case_number, c.title FROM calendar_events e"
        " LEFT JOIN cases c ON e.case_id = c.id"
        " WHERE e.completed = 0 AND e.event_date = ?"
        " ORDER BY e.event_time",
        (today,),
    ).fetchall()
    week_events = db.execute(
        "SELECT e.*, c.case_number, c.title FROM calendar_events e"
        " LEFT JOIN cases c ON e.case_id = c.id"
        " WHERE e.completed = 0 AND e.event_date >= ? AND e.event_date <= ?"
        " ORDER BY e.event_date, e.event_time",
        (tomorrow, soon),
    ).fetchall()
    # Last backup status — shown prominently; a missing backup is a red flag.
    last_backup = db.execute(
        "SELECT * FROM backups ORDER BY id DESC LIMIT 1"
    ).fetchone()
    urgent_cutoff = (date.today() + timedelta(days=7)).isoformat()
    schedule_alert = get_clallam_schedule_alert()

    # --- v2.0 widget data ------------------------------------------------
    # v2.1: widget visibility is permission-based (see dashboard.html,
    # which checks perms directly). Trust data only loaded for view_trust.
    _perms = session.get("permissions", {})

    # Trust summary: only for users with view_trust. Others get None (no
    # trust data at all in the template context) — the frontend hides it.
    trust_summary = None
    if user_has_perm(_perms, "view_trust"):
        accounts = []
        total_cents = 0
        for a in db.execute(
            "SELECT id, name FROM trust_accounts WHERE is_active = 1 ORDER BY name"
        ).fetchall():
            bal = account_trust_balance(db, a["id"])
            total_cents += bal
            accounts.append({
                "id": a["id"],
                "name": a["name"],
                "balance_cents": bal,
            })
        ledger_count = db.execute(
            "SELECT COUNT(DISTINCT account_id || ':' || client_id) AS c"
            " FROM trust_transactions"
        ).fetchone()["c"]
        trust_summary = {
            "total_cents": total_cents,
            "accounts": accounts,
            "ledger_count": ledger_count,
        }

    # Caseload donut: active cases grouped by case type.
    caseload_by_type = [
        {"case_type": r["case_type"], "count": r["count"]}
        for r in db.execute(
            "SELECT case_type, COUNT(*) AS count FROM cases"
            " WHERE status = 'active' GROUP BY case_type ORDER BY count DESC"
        ).fetchall()
    ]

    # Recent clients widget: 8 most recently updated.
    recent_clients = [
        {"id": r["id"], "first_name": r["first_name"], "last_name": r["last_name"]}
        for r in db.execute(
            "SELECT id, first_name, last_name FROM clients"
            " ORDER BY updated_at DESC LIMIT 8"
        ).fetchall()
    ]

    layout = get_dashboard_layout(session["user_id"])
    theme = get_user_theme(session["user_id"])

    return render_template(
        "dashboard.html", stats=stats, active_cases=active_cases,
        recent=recent, deadlines=deadlines, overdue=overdue,
        last_backup=last_backup, today=today, urgent_cutoff=urgent_cutoff,
        schedule_alert=schedule_alert,
        calendars_url=CLALLAM_CALENDARS_URL,
        today_events=today_events, week_events=week_events,
        trust_summary=trust_summary, caseload_by_type=caseload_by_type,
        recent_clients=recent_clients, layout=layout,
        theme=theme,
    )


@app.route("/dashboard/customize", methods=["POST"])
@login_required
def dashboard_customize():
    """Save the user's dashboard widget layout.

    Accepts JSON {"widgets": [{"id": ..., "visible": bool}, ...]}.
    Returns {"ok": true} on success, {"ok": false, "error": ...} on 400.
    """
    data = request.get_json(silent=True) or {}
    widgets = data.get("widgets")
    try:
        save_dashboard_layout(session["user_id"], widgets)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True})


@app.route("/dashboard/customize/reset", methods=["POST"])
@login_required
def dashboard_customize_reset():
    """Revert the user's dashboard layout to the default (theme untouched)."""
    db = get_db()
    db.execute(
        "INSERT INTO user_preferences (user_id, dashboard_layout)"
        " VALUES (?, NULL) ON CONFLICT(user_id) DO UPDATE SET dashboard_layout = NULL",
        (session["user_id"],),
    )
    db.commit()
    return jsonify({"ok": True})


@app.route("/dashboard/theme", methods=["POST"])
@login_required
def dashboard_theme():
    """Save the user's theme preference ('light' or 'dark').

    Accepts JSON {"theme": "dark"}. Returns {"ok": true} on success,
    {"ok": false, "error": ...} on 400. Does not touch the saved
    dashboard layout.
    """
    data = request.get_json(silent=True) or {}
    try:
        set_user_theme(session["user_id"], data.get("theme"))
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True})


# ----------------------------------------------------------------------------
# Clients
# ----------------------------------------------------------------------------
@app.route("/clients")
@permission_required("view_clients")
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
@permission_required("manage_clients")
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
@permission_required("view_clients")
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
@permission_required("manage_clients")
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
@permission_required("delete_records")
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
@permission_required("manage_clients")
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
@permission_required("delete_records")
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
@permission_required("view_cases")
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
@permission_required("manage_cases")
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
@permission_required("view_cases")
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
    emails = db.execute(
        "SELECT e.* FROM synced_emails e"
        " JOIN email_case_links l ON l.email_id = e.id"
        " WHERE l.case_id = ?"
        " ORDER BY e.sent_at DESC, e.id DESC LIMIT 30",
        (case_id,)).fetchall()
    unlinked = db.execute(
        "SELECT e.* FROM synced_emails e WHERE NOT EXISTS"
        " (SELECT 1 FROM email_case_links l WHERE l.email_id = e.id"
        "  AND l.case_id = ?)"
        " ORDER BY e.sent_at DESC, e.id DESC LIMIT 20",
        (case_id,)).fetchall()
    email_connected = db.execute(
        "SELECT COUNT(*) AS c FROM integrations WHERE status = 'connected'"
        " AND provider IN ('gmail', 'outlook')").fetchone()["c"] > 0
    audit("case_view", f"Viewed case {case['case_number']} (id={case_id})")
    return render_template("case_detail.html", case=case, parties=parties,
                           doc_count=doc_count, upcoming=upcoming,
                           time_totals=time_totals, emails=emails,
                           unlinked=unlinked,
                           email_connected=email_connected)


@app.route("/cases/<int:case_id>/edit", methods=["GET", "POST"])
@permission_required("manage_cases")
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
@permission_required("manage_cases")
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
@permission_required("delete_records")
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
@permission_required("manage_cases")
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
@permission_required("delete_records")
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
@permission_required("view_documents")
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
@permission_required("view_documents")
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
@permission_required("delete_records")
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
@permission_required("view_calendar")
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
@permission_required("manage_calendar")
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
@permission_required("manage_calendar")
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
@permission_required("delete_records")
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
@permission_required("calculate_deadlines")
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
    cal_warnings = (
        clallam_warnings(trigger_type, trigger_date)
        if (not error and trigger_date)
        else []
    )
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
        clallam_warnings=cal_warnings,
    )


@app.route("/deadlines/push", methods=["POST"])
@permission_required("push_deadlines")
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


@app.route("/clallam/schedule/dismiss", methods=["POST"])
@permission_required("push_deadlines")
def clallam_schedule_dismiss():
    """Dismiss the Clallam schedule-change alert after reviewing."""
    check_csrf()
    _meta_set("clallam_cal_alert", "")
    _meta_set("clallam_cal_alert_msg", "")
    audit("clallam_schedule_acknowledged",
          "Attorney reviewed and dismissed the court schedule change alert.")
    flash("Schedule alert dismissed.", "success")
    return redirect(url_for("dashboard"))


# ----------------------------------------------------------------------------
# Billing & time tracking
# ----------------------------------------------------------------------------
@app.route("/cases/<int:case_id>/time", methods=["GET", "POST"])
@permission_required("manage_billing")
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
@permission_required("manage_billing")
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
@permission_required("view_billing")
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
@permission_required("manage_billing")
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
@permission_required("view_billing")
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
@permission_required("manage_billing")
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
        was_paid = inv["status"] == "paid"
        db.execute("UPDATE invoices SET status = ? WHERE id = ?",
                   (status, invoice_id))
        # Auto-book income when an invoice is first marked paid.
        if status == "paid" and not was_paid:
            existing = db.execute(
                "SELECT id FROM op_transactions WHERE invoice_id = ?", (invoice_id,)
            ).fetchone()
            if not existing:
                fees_acct = _get_account_by_code(db, "4000")
                if fees_acct:
                    total_cents = _invoice_total_cents(db, invoice_id)
                    now = datetime.now(timezone.utc).isoformat()
                    db.execute(
                        """INSERT INTO op_transactions (account_id, txn_date, amount_cents,
                            description, client_id, invoice_id, created_by, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (fees_acct["id"], inv["issue_date"] or date.today().isoformat(),
                         total_cents,
                         f"Payment received — Invoice {inv['invoice_number']}",
                         inv["client_id"], invoice_id, session.get("user_id"), now),
                    )
                    audit("op_txn_auto",
                          f"Auto-booked income ${cents_to_str(total_cents)} for paid invoice"
                          f" {inv['invoice_number']}")
        db.commit()
        audit("invoice_status",
              f"Set invoice {inv['invoice_number']} to {status}")
        flash(f"Invoice marked {status}.", "success")
    return redirect(url_for("invoice_detail", invoice_id=invoice_id))


@app.route("/invoices/<int:invoice_id>/delete", methods=["POST"])
@permission_required("manage_billing")
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
@permission_required("view_billing")
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
@permission_required("use_templates")
def template_gallery():
    return render_template("templates.html", templates=template_list())


@app.route("/templates/<key>")
@permission_required("use_templates")
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
@permission_required("use_templates")
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
@permission_required("use_templates")
def template_generate(key):
    tmpl = get_template(key)
    if not tmpl:
        abort(404)
    check_csrf()
    client_id = request.form.get("client_id", type=int)
    case_id = request.form.get("case_id", type=int)
    client, children, case = _template_party_context(client_id, case_id)
    values = _gather_template_values(tmpl, request.form, client, children, case)
    # Clallam County AI disclosure (effective Sept 2025)
    ai_assisted = request.form.get("ai_assisted") == "on"
    # Enrich data for the PDF builders
    data = dict(values)
    data["ai_disclosure"] = ai_assisted
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
            f"Generated from template: {tmpl['name']}"
            + (" (AI-assisted)" if ai_assisted else ""))
        audit("template_generate",
              f"Generated {tmpl['name']} (v{version}) for case"
              f" {case['case_number']} (id={case['id']})"
              + (" [AI-assisted]" if ai_assisted else ""))
    else:
        who = f"{client['first_name']} {client['last_name']}" if client else "no client"
        audit("template_generate",
              f"Generated {tmpl['name']} for {who} (not filed to a case)"
              + (" [AI-assisted]" if ai_assisted else ""))
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
@permission_required("view_trust")
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
@permission_required("manage_trust")
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
@permission_required("view_trust")
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
@permission_required("manage_trust")
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
@permission_required("view_trust")
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
@permission_required("manage_trust")
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
@permission_required("view_trust")
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
@permission_required("view_trust")
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
# Operating bookkeeping + payroll (v2.1). Admin and accountant roles via
# granular permissions: view_accounting / manage_accounting / run_payroll /
# view_paystubs / use_timeclock.
# ----------------------------------------------------------------------------

def _coa_balance(db, account_id, from_date=None, to_date=None):
    q = "SELECT COALESCE(SUM(amount_cents), 0) AS b FROM op_transactions WHERE account_id = ?"
    args = [account_id]
    if from_date:
        q += " AND txn_date >= ?"
        args.append(from_date)
    if to_date:
        q += " AND txn_date <= ?"
        args.append(to_date)
    return db.execute(q, args).fetchone()["b"]


def _get_account_by_code(db, code):
    return db.execute(
        "SELECT * FROM coa_accounts WHERE code = ? AND is_active = 1", (code,)
    ).fetchone()


def _employee_rate_cents(row):
    """Decrypt the employee's pay rate (stored encrypted)."""
    try:
        return int(decrypt_value(row["pay_rate_cents"]) or 0)
    except (ValueError, TypeError):
        return 0


def _employee_dict(row):
    d = dict(row)
    d["pay_rate_cents"] = _employee_rate_cents(row)
    return d


def _invoice_total_cents(db, invoice_id):
    row = db.execute(
        "SELECT COALESCE(SUM(amount), 0) AS t FROM invoice_items WHERE invoice_id = ?",
        (invoice_id,),
    ).fetchone()
    return int(round((row["t"] or 0) * 100))


@app.route("/accounting")
@permission_required("view_accounting")
def accounting_overview():
    db = get_db()
    year = date.today().strftime("%Y")
    ytd_from = f"{year}-01-01"
    income = db.execute(
        """SELECT COALESCE(SUM(t.amount_cents), 0) AS s FROM op_transactions t
           JOIN coa_accounts a ON t.account_id = a.id
           WHERE a.type = 'income' AND t.txn_date >= ?""",
        (ytd_from,),
    ).fetchone()["s"]
    expenses = db.execute(
        """SELECT COALESCE(SUM(t.amount_cents), 0) AS s FROM op_transactions t
           JOIN coa_accounts a ON t.account_id = a.id
           WHERE a.type = 'expense' AND t.txn_date >= ?""",
        (ytd_from,),
    ).fetchone()["s"]
    ar_acct = _get_account_by_code(db, "1100")
    cash_acct = _get_account_by_code(db, "1000")
    # Unreconciled = asset accounts with no reconciliation in the last 40 days
    unreconciled = []
    for a in db.execute(
        "SELECT * FROM coa_accounts WHERE type = 'asset' AND is_active = 1 ORDER BY code"
    ).fetchall():
        last = db.execute(
            "SELECT MAX(statement_date) AS d FROM op_reconciliations WHERE account_id = ?",
            (a["id"],),
        ).fetchone()["d"]
        if not last or last < (date.today() - timedelta(days=40)).isoformat():
            unreconciled.append({
                "id": a["id"], "name": a["name"],
                "book_cents": _coa_balance(db, a["id"]),
            })
    recent = db.execute(
        """SELECT t.*, a.name AS account_name FROM op_transactions t
           JOIN coa_accounts a ON t.account_id = a.id
           ORDER BY t.txn_date DESC, t.id DESC LIMIT 10"""
    ).fetchall()
    summary = {
        "income_ytd_cents": income,
        "expenses_ytd_cents": -expenses,
        "net_ytd_cents": income + expenses,
        "ar_cents": _coa_balance(db, ar_acct["id"]) if ar_acct else 0,
        "cash_cents": _coa_balance(db, cash_acct["id"]) if cash_acct else 0,
    }
    return render_template(
        "accounting.html", summary=summary, recent_txns=recent,
        unreconciled=unreconciled, active_tab="overview",
    )


@app.route("/accounting/transactions")
@permission_required("view_accounting")
def op_txn_list():
    db = get_db()
    f_account = request.args.get("account", "")
    f_from = request.args.get("from", "")
    f_to = request.args.get("to", "")
    q = """SELECT t.*, a.name AS account_name, a.type AS account_type,
                  c.first_name, c.last_name
           FROM op_transactions t
           JOIN coa_accounts a ON t.account_id = a.id
           LEFT JOIN clients c ON t.client_id = c.id
           WHERE 1=1"""
    args = []
    if f_account:
        q += " AND t.account_id = ?"
        args.append(f_account)
    if f_from:
        q += " AND t.txn_date >= ?"
        args.append(f_from)
    if f_to:
        q += " AND t.txn_date <= ?"
        args.append(f_to)
    q += " ORDER BY t.txn_date DESC, t.id DESC"
    txns = db.execute(q, args).fetchall()
    accounts = db.execute(
        "SELECT id, code, name FROM coa_accounts WHERE is_active = 1 ORDER BY code"
    ).fetchall()
    return render_template(
        "op_transactions.html", txns=txns, accounts=accounts,
        f_account=f_account, f_from=f_from, f_to=f_to,
        active_tab="transactions",
    )


@app.route("/accounting/transactions/new", methods=["GET", "POST"])
@permission_required("manage_accounting")
def op_txn_new():
    db = get_db()
    if request.method == "POST":
        check_csrf()
        txn_date = request.form.get("txn_date", "").strip() or date.today().isoformat()
        account_id = request.form.get("account_id", "").strip()
        kind = request.form.get("txn_kind", "expense")
        amount = dollars_to_cents(request.form.get("amount", ""))
        description = request.form.get("description", "").strip()
        client_id = request.form.get("client_id", "").strip() or None
        reference = request.form.get("reference", "").strip() or None
        if not account_id or amount is None or not description:
            flash("Account, amount, and description are required.", "error")
        else:
            if kind == "expense" and amount > 0:
                amount = -amount
            if kind == "income" and amount < 0:
                amount = -amount
            now = datetime.now(timezone.utc).isoformat()
            db.execute(
                """INSERT INTO op_transactions (account_id, txn_date, amount_cents,
                    description, client_id, reference, created_by, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (account_id, txn_date, amount, description, client_id, reference,
                 session.get("user_id"), now),
            )
            db.commit()
            audit("op_txn_new", f"Recorded {kind} of ${cents_to_str(abs(amount))}: {description}")
            flash("Transaction recorded.", "success")
            return redirect(url_for("op_txn_list"))
    accounts = db.execute(
        "SELECT id, code, name, type FROM coa_accounts WHERE is_active = 1 ORDER BY code"
    ).fetchall()
    clients = db.execute(
        "SELECT id, first_name, last_name FROM clients ORDER BY last_name, first_name"
    ).fetchall()
    return render_template(
        "op_transaction_form.html", accounts=accounts, clients=clients,
        txn=None, today=date.today().isoformat(), active_tab="transactions",
    )


@app.route("/accounting/transactions/<int:txn_id>/delete", methods=["POST"])
@permission_required("manage_accounting")
def op_txn_delete(txn_id):
    check_csrf()
    db = get_db()
    txn = db.execute("SELECT * FROM op_transactions WHERE id = ?", (txn_id,)).fetchone()
    if not txn:
        abort(404)
    if txn["invoice_id"]:
        flash("This transaction was auto-created from a paid invoice and cannot be deleted.", "error")
        return redirect(url_for("op_txn_list"))
    db.execute("DELETE FROM op_transactions WHERE id = ?", (txn_id,))
    db.commit()
    audit("op_txn_delete", f"Deleted operating transaction #{txn_id}: {txn['description']}")
    flash("Transaction deleted.", "success")
    return redirect(url_for("op_txn_list"))


@app.route("/accounting/accounts", methods=["GET", "POST"])
@permission_required("view_accounting")
def coa_list():
    db = get_db()
    if request.method == "POST":
        if not user_has_perm(session.get("permissions", {}), "manage_accounting"):
            abort(403)
        check_csrf()
        code = request.form.get("code", "").strip()
        name = request.form.get("name", "").strip()
        atype = request.form.get("type", "").strip()
        if not code or not name or atype not in ("income", "expense", "asset", "liability", "equity"):
            flash("Code, name, and a valid account type are required.", "error")
        else:
            try:
                db.execute(
                    "INSERT INTO coa_accounts (code, name, type, is_active, created_at)"
                    " VALUES (?, ?, ?, 1, ?)",
                    (code, name, atype, datetime.now(timezone.utc).isoformat()),
                )
                db.commit()
                audit("coa_add", f"Added account {code} — {name} ({atype})")
                flash("Account added.", "success")
            except sqlite3.IntegrityError:
                flash("That account code is already in use.", "error")
        return redirect(url_for("coa_list"))
    accounts = []
    for a in db.execute("SELECT * FROM coa_accounts ORDER BY type, code").fetchall():
        d = dict(a)
        d["balance_cents"] = _coa_balance(db, a["id"])
        accounts.append(d)
    return render_template("coa_accounts.html", accounts=accounts, active_tab="accounts")


@app.route("/accounting/accounts/<int:account_id>/toggle", methods=["POST"])
@permission_required("manage_accounting")
def coa_toggle(account_id):
    check_csrf()
    db = get_db()
    acct = db.execute("SELECT * FROM coa_accounts WHERE id = ?", (account_id,)).fetchone()
    if not acct:
        abort(404)
    new_state = 0 if acct["is_active"] else 1
    db.execute("UPDATE coa_accounts SET is_active = ? WHERE id = ?", (new_state, account_id))
    db.commit()
    audit("coa_toggle", f"{'Deactivated' if new_state == 0 else 'Reactivated'} account {acct['code']}")
    flash("Account updated.", "success")
    return redirect(url_for("coa_list"))


@app.route("/accounting/reports/pl")
@permission_required("view_accounting")
def report_pl():
    db = get_db()
    f_from = request.args.get("from", f"{date.today().strftime('%Y')}-01-01")
    f_to = request.args.get("to", date.today().isoformat())
    income_rows = db.execute(
        """SELECT a.name, COALESCE(SUM(t.amount_cents), 0) AS total
           FROM coa_accounts a LEFT JOIN op_transactions t
             ON t.account_id = a.id AND t.txn_date >= ? AND t.txn_date <= ?
           WHERE a.type = 'income' AND a.is_active = 1
           GROUP BY a.id ORDER BY a.code""",
        (f_from, f_to),
    ).fetchall()
    expense_rows = db.execute(
        """SELECT a.name, COALESCE(SUM(t.amount_cents), 0) AS total
           FROM coa_accounts a LEFT JOIN op_transactions t
             ON t.account_id = a.id AND t.txn_date >= ? AND t.txn_date <= ?
           WHERE a.type = 'expense' AND a.is_active = 1
           GROUP BY a.id ORDER BY a.code""",
        (f_from, f_to),
    ).fetchall()
    total_income = sum(r["total"] for r in income_rows)
    total_expenses = sum(r["total"] for r in expense_rows)
    return render_template(
        "report_pl.html", from_date=f_from, to_date=f_to,
        period_label=f"{f_from} to {f_to}",
        income_rows=income_rows, expense_rows=expense_rows,
        total_income_cents=total_income, total_expenses_cents=-total_expenses,
        net_cents=total_income + total_expenses, active_tab="reports",
    )


@app.route("/accounting/reports/balance-sheet")
@permission_required("view_accounting")
def report_balance_sheet():
    db = get_db()
    as_of = request.args.get("as_of", date.today().isoformat())
    def section(atype):
        return db.execute(
            """SELECT a.name, COALESCE(SUM(t.amount_cents), 0) AS total
               FROM coa_accounts a LEFT JOIN op_transactions t
                 ON t.account_id = a.id AND t.txn_date <= ?
               WHERE a.type = ? AND a.is_active = 1
               GROUP BY a.id ORDER BY a.code""",
            (as_of, atype),
        ).fetchall()
    assets = section("asset")
    liabilities = section("liability")
    equity = section("equity")
    # Net income to date flows into equity
    net_income = db.execute(
        """SELECT COALESCE(SUM(CASE WHEN a.type = 'income' THEN t.amount_cents
                                    ELSE t.amount_cents END), 0) AS n
           FROM op_transactions t JOIN coa_accounts a ON t.account_id = a.id
           WHERE a.type IN ('income', 'expense') AND t.txn_date <= ?""",
        (as_of,),
    ).fetchone()["n"]
    total_assets = sum(r["total"] for r in assets)
    total_liab = sum(r["total"] for r in liabilities)
    total_equity = sum(r["total"] for r in equity) + net_income
    return render_template(
        "report_balance_sheet.html", as_of=as_of,
        assets=assets, liabilities=liabilities, equity=equity,
        net_income_cents=net_income,
        total_assets_cents=total_assets,
        total_liab_equity_cents=total_liab + total_equity,
        balanced=(total_assets == total_liab + total_equity),
        active_tab="reports",
    )


@app.route("/accounting/reports/ledger")
@permission_required("view_accounting")
def report_ledger():
    db = get_db()
    f_from = request.args.get("from", f"{date.today().strftime('%Y')}-01-01")
    f_to = request.args.get("to", date.today().isoformat())
    accounts = []
    for a in db.execute(
        "SELECT * FROM coa_accounts WHERE is_active = 1 ORDER BY type, code"
    ).fetchall():
        txns = db.execute(
            """SELECT txn_date, description, amount_cents FROM op_transactions
               WHERE account_id = ? AND txn_date >= ? AND txn_date <= ?
               ORDER BY txn_date, id""",
            (a["id"], f_from, f_to),
        ).fetchall()
        accounts.append({
            "code": a["code"], "name": a["name"], "type": a["type"],
            "txns": txns,
            "total_cents": sum(t["amount_cents"] for t in txns),
        })
    return render_template(
        "report_ledger.html", accounts=accounts,
        from_date=f_from, to_date=f_to, active_tab="reports",
    )


@app.route("/accounting/reports/export")
@permission_required("view_accounting")
def report_export_csv():
    import csv
    db = get_db()
    report = request.args.get("report", "pl")
    f_from = request.args.get("from", f"{date.today().strftime('%Y')}-01-01")
    f_to = request.args.get("to", date.today().isoformat())
    buf = io.StringIO()
    w = csv.writer(buf)
    if report == "pl":
        w.writerow(["Profit & Loss", f_from, f_to])
        w.writerow(["Account", "Amount"])
        for r in db.execute(
            """SELECT a.name, COALESCE(SUM(t.amount_cents),0) AS total
               FROM coa_accounts a LEFT JOIN op_transactions t ON t.account_id = a.id
                 AND t.txn_date >= ? AND t.txn_date <= ?
               WHERE a.type IN ('income','expense') AND a.is_active = 1
               GROUP BY a.id ORDER BY a.type, a.code""",
            (f_from, f_to),
        ).fetchall():
            w.writerow([r["name"], f"{r['total'] / 100:.2f}"])
    elif report == "ledger":
        w.writerow(["General Ledger", f_from, f_to])
        w.writerow(["Date", "Account", "Description", "Amount"])
        for r in db.execute(
            """SELECT t.txn_date, a.name, t.description, t.amount_cents
               FROM op_transactions t JOIN coa_accounts a ON t.account_id = a.id
               WHERE t.txn_date >= ? AND t.txn_date <= ?
               ORDER BY t.txn_date, t.id""",
            (f_from, f_to),
        ).fetchall():
            w.writerow([r["txn_date"], r["name"], r["description"], f"{r['amount_cents'] / 100:.2f}"])
    else:
        w.writerow(["Balance Sheet", request.args.get("as_of", date.today().isoformat())])
        w.writerow(["Account", "Type", "Balance"])
        for r in db.execute(
            """SELECT a.name, a.type, COALESCE(SUM(t.amount_cents),0) AS total
               FROM coa_accounts a LEFT JOIN op_transactions t ON t.account_id = a.id
               WHERE a.is_active = 1 GROUP BY a.id ORDER BY a.type, a.code"""
        ).fetchall():
            w.writerow([r["name"], r["type"], f"{r['total'] / 100:.2f}"])
    audit("report_export", f"Exported {report} report to CSV")
    return app.response_class(
        buf.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={report}-{f_from}-to-{f_to}.csv"},
    )


@app.route("/accounting/reconcile/<int:account_id>", methods=["GET", "POST"])
@permission_required("manage_accounting")
def op_reconcile(account_id):
    db = get_db()
    acct = db.execute("SELECT * FROM coa_accounts WHERE id = ?", (account_id,)).fetchone()
    if not acct:
        abort(404)
    book_cents = _coa_balance(db, account_id)
    history = db.execute(
        """SELECT r.*, u.username AS reconciled_by_name FROM op_reconciliations r
           LEFT JOIN users u ON r.reconciled_by = u.id
           WHERE r.account_id = ? ORDER BY r.statement_date DESC LIMIT 12""",
        (account_id,),
    ).fetchall()
    if request.method == "POST":
        check_csrf()
        statement_date = request.form.get("statement_date", "").strip()
        statement_bal = dollars_to_cents(request.form.get("statement_balance", ""))
        notes = request.form.get("notes", "").strip()
        if not statement_date or statement_bal is None:
            flash("Enter the statement date and ending balance.", "error")
        else:
            now = datetime.now(timezone.utc).isoformat()
            status = "matched" if statement_bal == book_cents else "unmatched"
            db.execute(
                """INSERT INTO op_reconciliations (account_id, statement_date,
                    statement_balance_cents, book_balance_cents, status,
                    reconciled_by, reconciled_at, notes, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (account_id, statement_date, statement_bal, book_cents, status,
                 session.get("user_id"), now, notes, now),
            )
            db.commit()
            audit("op_reconcile",
                  f"Reconciled {acct['name']}: statement ${cents_to_str(statement_bal)}"
                  f" vs book ${cents_to_str(book_cents)} -> {status}")
            flash("Reconciliation recorded: " + ("matched." if status == "matched"
                  else "balances do NOT match — investigate."), 
                  "success" if status == "matched" else "warning")
            return redirect(url_for("op_reconcile", account_id=account_id))
    return render_template(
        "op_reconcile.html", account=acct, book_cents=book_cents,
        history=history, active_tab="reconcile",
    )


# --- Employees ---
@app.route("/accounting/employees")
@permission_required("run_payroll")
def employee_list():
    db = get_db()
    employees = [_employee_dict(r) for r in db.execute(
        "SELECT e.*, u.username FROM employees e LEFT JOIN users u ON e.user_id = u.id"
        " ORDER BY e.is_active DESC, e.full_name"
    ).fetchall()]
    return render_template("employees.html", employees=employees, active_tab="employees")


@app.route("/accounting/employees/new", methods=["GET", "POST"])
@permission_required("run_payroll")
def employee_new():
    db = get_db()
    if request.method == "POST":
        check_csrf()
        full_name = request.form.get("full_name", "").strip()
        pay_type = request.form.get("pay_type", "hourly")
        rate_str = request.form.get("pay_rate", "").strip()
        pay_frequency = request.form.get("pay_frequency", "biweekly")
        filing_status = request.form.get("filing_status", "single")
        try:
            allowances = int(request.form.get("allowances", "0") or 0)
        except ValueError:
            allowances = 0
        user_id = request.form.get("user_id", "").strip() or None
        hire_date = request.form.get("hire_date", "").strip() or None
        try:
            rate_cents = int(round(float(rate_str) * 100))
        except ValueError:
            rate_cents = None
        if (not full_name or rate_cents is None or rate_cents <= 0
                or pay_type not in ("hourly", "salary")
                or pay_frequency not in PAY_PERIODS_PER_YEAR
                or filing_status not in ("single", "married")):
            flash("Enter a name, valid pay rate, pay type, frequency, and filing status.", "error")
        else:
            db.execute(
                """INSERT INTO employees (user_id, full_name, pay_type, pay_rate_cents,
                    pay_frequency, filing_status, allowances, hire_date, is_active, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
                (user_id, full_name, pay_type, encrypt_value(str(rate_cents)),
                 pay_frequency, filing_status, allowances, hire_date,
                 datetime.now(timezone.utc).isoformat()),
            )
            db.commit()
            audit("employee_new", f"Added employee {full_name}")
            flash("Employee added.", "success")
            return redirect(url_for("employee_list"))
    users = db.execute(
        "SELECT id, username, full_name FROM users WHERE is_active = 1 ORDER BY username"
    ).fetchall()
    return render_template(
        "employee_form.html", employee=None, users=users,
        today=date.today().isoformat(), active_tab="employees",
    )


@app.route("/accounting/employees/<int:employee_id>/edit", methods=["GET", "POST"])
@permission_required("run_payroll")
def employee_edit(employee_id):
    db = get_db()
    emp = db.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
    if not emp:
        abort(404)
    emp_d = _employee_dict(emp)
    if request.method == "POST":
        check_csrf()
        full_name = request.form.get("full_name", "").strip()
        pay_type = request.form.get("pay_type", "hourly")
        rate_str = request.form.get("pay_rate", "").strip()
        pay_frequency = request.form.get("pay_frequency", "biweekly")
        filing_status = request.form.get("filing_status", "single")
        try:
            allowances = int(request.form.get("allowances", "0") or 0)
        except ValueError:
            allowances = 0
        user_id = request.form.get("user_id", "").strip() or None
        hire_date = request.form.get("hire_date", "").strip() or None
        try:
            rate_cents = int(round(float(rate_str) * 100))
        except ValueError:
            rate_cents = None
        if (not full_name or rate_cents is None or rate_cents <= 0
                or pay_type not in ("hourly", "salary")
                or pay_frequency not in PAY_PERIODS_PER_YEAR):
            flash("Enter a name, valid pay rate, pay type, and frequency.", "error")
        else:
            db.execute(
                """UPDATE employees SET user_id = ?, full_name = ?, pay_type = ?,
                    pay_rate_cents = ?, pay_frequency = ?, filing_status = ?,
                    allowances = ?, hire_date = ? WHERE id = ?""",
                (user_id, full_name, pay_type, encrypt_value(str(rate_cents)),
                 pay_frequency, filing_status, allowances, hire_date, employee_id),
            )
            db.commit()
            audit("employee_edit", f"Updated employee {full_name}")
            flash("Employee updated.", "success")
            return redirect(url_for("employee_list"))
    users = db.execute(
        "SELECT id, username, full_name FROM users WHERE is_active = 1 ORDER BY username"
    ).fetchall()
    return render_template(
        "employee_form.html", employee=emp_d, users=users,
        today=date.today().isoformat(), active_tab="employees",
    )


@app.route("/accounting/employees/<int:employee_id>/toggle", methods=["POST"])
@permission_required("run_payroll")
def employee_toggle(employee_id):
    check_csrf()
    db = get_db()
    emp = db.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
    if not emp:
        abort(404)
    new_state = 0 if emp["is_active"] else 1
    db.execute("UPDATE employees SET is_active = ? WHERE id = ?", (new_state, employee_id))
    db.commit()
    audit("employee_toggle", f"{'Deactivated' if not new_state else 'Reactivated'} employee {emp['full_name']}")
    flash("Employee updated.", "success")
    return redirect(url_for("employee_list"))


# --- Timeclock ---
@app.route("/accounting/timeclock", methods=["GET", "POST"])
@permission_required("use_timeclock")
def timeclock():
    db = get_db()
    if request.method == "POST":
        # Manual entry requires payroll permission
        if not user_has_perm(session.get("permissions", {}), "run_payroll"):
            abort(403)
        check_csrf()
        employee_id = request.form.get("employee_id", "").strip()
        entry_date = request.form.get("entry_date", "").strip() or date.today().isoformat()
        try:
            hours = float(request.form.get("hours", "0") or 0)
        except ValueError:
            hours = 0
        notes = request.form.get("notes", "").strip()
        if not employee_id or hours <= 0 or hours > 168:
            flash("Select an employee and enter valid hours (0–168).", "error")
        else:
            now = datetime.now(timezone.utc).isoformat()
            db.execute(
                """INSERT INTO timeclock_entries (employee_id, clock_in, manual_hours,
                    entry_date, notes, created_by, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (employee_id, entry_date + "T00:00:00", hours, entry_date, notes,
                 session.get("user_id"), now),
            )
            db.commit()
            audit("timeclock_manual", f"Manual time entry: employee {employee_id}, {hours}h on {entry_date}")
            flash("Hours recorded.", "success")
        return redirect(url_for("timeclock"))
    employees = [_employee_dict(r) for r in db.execute(
        "SELECT * FROM employees WHERE is_active = 1 ORDER BY full_name"
    ).fetchall()]
    open_entries = db.execute(
        """SELECT t.id, t.clock_in, e.full_name AS employee_name
           FROM timeclock_entries t JOIN employees e ON t.employee_id = e.id
           WHERE t.clock_out IS NULL AND t.manual_hours IS NULL
           ORDER BY t.clock_in"""
    ).fetchall()
    recent = db.execute(
        """SELECT t.*, e.full_name AS employee_name
           FROM timeclock_entries t JOIN employees e ON t.employee_id = e.id
           ORDER BY t.entry_date DESC, t.id DESC LIMIT 30"""
    ).fetchall()
    recent_list = []
    for r in recent:
        d = dict(r)
        d["hours"] = entry_hours(r)
        recent_list.append(d)
    return render_template(
        "timeclock.html", employees=employees, open_entries=open_entries,
        recent=recent_list, today=date.today().isoformat(), active_tab="timeclock",
    )


@app.route("/accounting/timeclock/clock-in/<int:employee_id>", methods=["POST"])
@permission_required("use_timeclock")
def timeclock_clockin(employee_id):
    check_csrf()
    db = get_db()
    emp = db.execute("SELECT * FROM employees WHERE id = ? AND is_active = 1",
                     (employee_id,)).fetchone()
    if not emp:
        abort(404)
    # Prevent double clock-in
    existing = db.execute(
        "SELECT id FROM timeclock_entries WHERE employee_id = ? AND clock_out IS NULL"
        " AND manual_hours IS NULL",
        (employee_id,),
    ).fetchone()
    if existing:
        flash(f"{emp['full_name']} is already clocked in.", "warning")
        return redirect(url_for("timeclock"))
    now = datetime.now(timezone.utc)
    db.execute(
        """INSERT INTO timeclock_entries (employee_id, clock_in, entry_date,
            created_by, created_at) VALUES (?, ?, ?, ?, ?)""",
        (employee_id, now.isoformat(), now.date().isoformat(),
         session.get("user_id"), now.isoformat()),
    )
    db.commit()
    audit("timeclock_in", f"{emp['full_name']} clocked in")
    flash(f"{emp['full_name']} clocked in.", "success")
    return redirect(url_for("timeclock"))


@app.route("/accounting/timeclock/clock-out/<int:entry_id>", methods=["POST"])
@permission_required("use_timeclock")
def timeclock_clockout(entry_id):
    check_csrf()
    db = get_db()
    entry = db.execute(
        """SELECT t.*, e.full_name FROM timeclock_entries t
           JOIN employees e ON t.employee_id = e.id WHERE t.id = ?""",
        (entry_id,),
    ).fetchone()
    if not entry or entry["clock_out"]:
        abort(404)
    now = datetime.now(timezone.utc).isoformat()
    db.execute("UPDATE timeclock_entries SET clock_out = ? WHERE id = ?", (now, entry_id))
    db.commit()
    hours = entry_hours(dict(entry, clock_out=now))
    audit("timeclock_out", f"{entry['full_name']} clocked out ({hours}h)")
    flash(f"{entry['full_name']} clocked out — {hours} hours.", "success")
    return redirect(url_for("timeclock"))


@app.route("/accounting/timeclock/manual", methods=["POST"])
@permission_required("run_payroll")
def timeclock_manual():
    # Alias that posts back to the timeclock view's manual-entry handler
    return timeclock()


# --- Payroll ---
@app.route("/accounting/payroll", methods=["GET", "POST"])
@permission_required("run_payroll")
def payroll_run():
    db = get_db()
    employees = [_employee_dict(r) for r in db.execute(
        "SELECT * FROM employees WHERE is_active = 1 ORDER BY full_name"
    ).fetchall()]
    period_start = request.values.get("period_start", "")
    period_end = request.values.get("period_end", "")
    pay_date = request.values.get("pay_date", date.today().isoformat())
    preview = None
    action = request.values.get("action", "")

    if period_start and period_end and action in ("preview", "generate"):
        if action == "generate":
            check_csrf()
        preview = []
        for emp in employees:
            entries = db.execute(
                """SELECT entry_date, manual_hours, clock_in, clock_out
                   FROM timeclock_entries
                   WHERE employee_id = ? AND entry_date >= ? AND entry_date <= ?""",
                (emp["id"], period_start, period_end),
            ).fetchall()
            if emp["pay_type"] == "hourly":
                hours_list = [{"entry_date": e["entry_date"],
                               "hours": entry_hours(e)} for e in entries]
                reg_h, ot_h = weekly_hours(hours_list)
            else:
                reg_h, ot_h = 0.0, 0.0
            calc = calculate_paycheck(db, emp, reg_h, ot_h)
            calc["employee_id"] = emp["id"]
            calc["full_name"] = emp["full_name"]
            preview.append(calc)
        if action == "generate":
            now = datetime.now(timezone.utc).isoformat()
            for calc in preview:
                emp_id = calc["employee_id"]
                ytd_before = db.execute(
                    "SELECT COALESCE(SUM(gross_cents), 0) AS g FROM paychecks WHERE employee_id = ?",
                    (emp_id,),
                ).fetchone()["g"]
                gross_c = int(round(calc["gross"] * 100))
                db.execute(
                    """INSERT INTO paychecks (employee_id, pay_period_start, pay_period_end,
                        pay_date, reg_hours, ot_hours, gross_cents, federal_cents, ss_cents,
                        medicare_cents, pfml_cents, wacares_cents, net_cents,
                        ytd_gross_cents, created_by, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (emp_id, period_start, period_end, pay_date,
                     calc["reg_hours"], calc["ot_hours"], gross_c,
                     int(round(calc["federal"] * 100)), int(round(calc["ss"] * 100)),
                     int(round(calc["medicare"] * 100)), int(round(calc["pfml"] * 100)),
                     int(round(calc["wacares"] * 100)), int(round(calc["net"] * 100)),
                     ytd_before + gross_c, session.get("user_id"), now),
                )
                # Book the payroll: wages expense + payroll tax expense
                wages_acct = _get_account_by_code(db, "5120")
                tax_acct = _get_account_by_code(db, "5130")
                liab_acct = _get_account_by_code(db, "2100")
                emp_name = calc["full_name"]
                if wages_acct:
                    db.execute(
                        """INSERT INTO op_transactions (account_id, txn_date, amount_cents,
                            description, created_by, created_at)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (wages_acct["id"], pay_date, -gross_c,
                         f"Payroll wages — {emp_name} ({period_start} to {period_end})",
                         session.get("user_id"), now),
                    )
                if tax_acct:
                    er_cost_c = int(round(calc["employer_total"] * 100))
                    db.execute(
                        """INSERT INTO op_transactions (account_id, txn_date, amount_cents,
                            description, created_by, created_at)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (tax_acct["id"], pay_date, -er_cost_c,
                         f"Employer payroll taxes — {emp_name}",
                         session.get("user_id"), now),
                    )
                if liab_acct:
                    ded_c = (int(round(calc["federal"] * 100)) + int(round(calc["ss"] * 100))
                             + int(round(calc["medicare"] * 100)) + int(round(calc["pfml"] * 100))
                             + int(round(calc["wacares"] * 100)))
                    db.execute(
                        """INSERT INTO op_transactions (account_id, txn_date, amount_cents,
                            description, created_by, created_at)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (liab_acct["id"], pay_date, ded_c,
                         f"Payroll tax liabilities — {emp_name}",
                         session.get("user_id"), now),
                    )
            db.commit()
            audit("payroll_generate",
                  f"Ran payroll for {period_start} to {period_end} ({len(preview)} employees)")
            flash(f"Payroll generated for {len(preview)} employee(s).", "success")
            return redirect(url_for("payroll_run"))

    generated = db.execute(
        """SELECT p.*, e.full_name AS employee_name FROM paychecks p
           JOIN employees e ON p.employee_id = e.id
           ORDER BY p.pay_date DESC, p.id DESC LIMIT 20"""
    ).fetchall()
    return render_template(
        "payroll.html", employees=employees, period_start=period_start,
        period_end=period_end, pay_date=pay_date, preview=preview,
        generated=generated, active_tab="payroll",
    )


@app.route("/accounting/paychecks/<int:paycheck_id>/paystub")
@permission_required("view_paystubs", "run_payroll")
def paystub_pdf(paycheck_id):
    db = get_db()
    pc = db.execute("SELECT * FROM paychecks WHERE id = ?", (paycheck_id,)).fetchone()
    if not pc:
        abort(404)
    # Employees with only view_paystubs can only see their own paystub
    perms = session.get("permissions", {})
    if not user_has_perm(perms, "run_payroll"):
        me = db.execute("SELECT id FROM users WHERE id = ?", (session.get("user_id"),)).fetchone()
        emp = db.execute("SELECT id FROM employees WHERE user_id = ?",
                         (session.get("user_id"),)).fetchone()
        if not emp or emp["id"] != pc["employee_id"]:
            abort(403, description="You can only view your own paystubs.")
    emp = _employee_dict(db.execute("SELECT * FROM employees WHERE id = ?",
                                    (pc["employee_id"],)).fetchone())
    ytd = db.execute(
        """SELECT COALESCE(SUM(gross_cents),0) AS gross,
                  COALESCE(SUM(federal_cents),0) AS federal,
                  COALESCE(SUM(ss_cents),0) AS ss,
                  COALESCE(SUM(medicare_cents),0) AS medicare,
                  COALESCE(SUM(pfml_cents),0) AS pfml,
                  COALESCE(SUM(wacares_cents),0) AS wacares,
                  COALESCE(SUM(other_deductions_cents),0) AS other
           FROM paychecks WHERE employee_id = ? AND pay_date <= ?""",
        (pc["employee_id"], pc["pay_date"]),
    ).fetchone()
    ytd_d = {k: ytd[k] for k in ("gross", "federal", "ss", "medicare", "pfml", "wacares", "other")}
    logo_path = os.path.join(BASE_DIR, "static", "dgm-logo.png")
    pdf = build_paystub_pdf(pc, emp, ytd_d, logo_path if os.path.exists(logo_path) else None)
    audit("paystub_view", f"Generated paystub PDF for paycheck #{paycheck_id}")
    return app.response_class(
        pdf, mimetype="application/pdf",
        headers={"Content-Disposition":
                 f"attachment; filename=paystub-{pc['pay_date']}-{emp['full_name'].replace(' ', '_')}.pdf"},
    )


@app.route("/accounting/payroll/reports")
@permission_required("run_payroll")
def payroll_reports():
    db = get_db()
    periods = db.execute(
        """SELECT pay_period_start, pay_period_end, pay_date,
                  COUNT(*) AS n,
                  COALESCE(SUM(gross_cents),0) AS gross,
                  COALESCE(SUM(federal_cents + ss_cents + medicare_cents + pfml_cents
                               + wacares_cents + other_deductions_cents),0) AS tax,
                  COALESCE(SUM(net_cents),0) AS net
           FROM paychecks GROUP BY pay_period_start, pay_period_end
           ORDER BY pay_period_start DESC LIMIT 12"""
    ).fetchall()
    period_list = []
    for p in periods:
        d = dict(p)
        d["label"] = f"{p['pay_period_start']} to {p['pay_period_end']}"
        # Employer cost estimate for the period
        d["employer_cost_cents"] = 0
        period_list.append(d)
    ytd = db.execute(
        """SELECT e.full_name,
                  COALESCE(SUM(p.gross_cents),0) AS ytd_gross_cents,
                  COALESCE(SUM(p.federal_cents),0) AS ytd_federal_cents,
                  COALESCE(SUM(p.ss_cents),0) AS ytd_ss_cents,
                  COALESCE(SUM(p.medicare_cents),0) AS ytd_medicare_cents,
                  COALESCE(SUM(p.net_cents),0) AS ytd_net_cents
           FROM employees e LEFT JOIN paychecks p ON p.employee_id = e.id
           WHERE strftime('%Y', p.pay_date) = strftime('%Y', 'now') OR p.pay_date IS NULL
           GROUP BY e.id ORDER BY e.full_name"""
    ).fetchall()
    # Employer liability YTD (employer share of FICA estimated from gross)
    er = db.execute(
        """SELECT COALESCE(SUM(gross_cents),0) AS g FROM paychecks
           WHERE strftime('%Y', pay_date) = strftime('%Y', 'now')"""
    ).fetchone()
    gross_ytd = er["g"]
    ss_er_rate = get_rate(db, "ss_rate_employer", 6.2) / 100.0
    med_er_rate = get_rate(db, "medicare_rate_employer", 1.45) / 100.0
    employer = {
        "ytd_ss_employer_cents": int(round(gross_ytd * ss_er_rate)),
        "ytd_medicare_employer_cents": int(round(gross_ytd * med_er_rate)),
        "ytd_sui_cents": 0,
        "ytd_li_cents": 0,
    }
    return render_template(
        "payroll_reports.html", periods=period_list, ytd=ytd,
        employer=employer, active_tab="payroll",
    )


@app.route("/accounting/settings", methods=["GET", "POST"])
@permission_required("manage_accounting")
def tax_settings():
    db = get_db()
    if request.method == "POST":
        check_csrf()
        now = datetime.now(timezone.utc).isoformat()
        for key, label, value, help_text in DEFAULT_TAX_RATES:
            new_val = request.form.get(f"rate_{key}")
            if new_val is not None and new_val.strip() != "":
                db.execute(
                    "UPDATE tax_rates SET value = ?, updated_at = ? WHERE key = ?",
                    (new_val.strip(), now, key),
                )
        db.commit()
        audit("tax_settings", "Updated payroll tax rates")
        flash("Tax rates updated. Verify them against current IRS/WA publications before running payroll.",
              "warning")
        return redirect(url_for("tax_settings"))
    rates = db.execute(
        "SELECT key, label, value, help, effective_year FROM tax_rates ORDER BY key"
    ).fetchall()
    return render_template("tax_settings.html", rates=rates, active_tab="settings")




# ----------------------------------------------------------------------------
# Backups (manual trigger + history)
# ----------------------------------------------------------------------------
@app.route("/backup/now", methods=["POST"])
@permission_required("manage_backups")
def backup_now():
    check_csrf()
    ok, msg = do_backup(manual=True)
    audit("backup_manual", msg)
    flash(msg, "success" if ok else "error")
    return redirect(url_for("dashboard"))


@app.route("/backup/history")
@permission_required("manage_backups")
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
@permission_required("manage_users")
def update_page():
    with _update_lock:
        info = dict(UPDATE_INFO)
    frozen = getattr(sys, "frozen", False)
    return render_template(
        "update.html", info=info, frozen=frozen,
        current_version=APP_VERSION,
    )


@app.route("/admin/update/check", methods=["POST"])
@permission_required("manage_users")
def update_check_now():
    check_csrf()
    check_for_updates()
    audit("update_check", "Manual update check requested.")
    return redirect(url_for("update_page"))


@app.route("/admin/update/apply", methods=["POST"])
@permission_required("manage_users")
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
@permission_required("view_audit_log")
def audit_view():
    db = get_db()
    entries = db.execute(
        "SELECT * FROM audit_log ORDER BY id DESC LIMIT 200"
    ).fetchall()
    return render_template("audit.html", entries=entries)


# ----------------------------------------------------------------------------
# Error pages
# ----------------------------------------------------------------------------
# ----------------------------------------------------------------------------
# Integrations: email sync (Gmail/Outlook) + calendar sync (Google Calendar)
# ----------------------------------------------------------------------------
import integrations as integ


def _get_integration(db, provider):
    row = db.execute(
        "SELECT * FROM integrations WHERE provider = ?", (provider,)
    ).fetchone()
    if not row:
        now = integ.now_iso()
        db.execute(
            "INSERT INTO integrations (provider, status, created_at,"
            " updated_at) VALUES (?, 'disconnected', ?, ?)",
            (provider, now, now),
        )
        db.commit()
        row = db.execute(
            "SELECT * FROM integrations WHERE provider = ?", (provider,)
        ).fetchone()
    return row


def _integration_settings(row):
    try:
        return json.loads(row["settings"] or "{}")
    except (ValueError, TypeError):
        return {}


def _save_integration(db, provider, **fields):
    fields["updated_at"] = integ.now_iso()
    sets = ", ".join(f"{k} = ?" for k in fields)
    db.execute(f"UPDATE integrations SET {sets} WHERE provider = ?",
               (*fields.values(), provider))
    db.commit()


def _integration_access_token(db, provider):
    """Return a valid access token, refreshing if needed.

    Raises integ.IntegrationAuthError when the admin must reconnect.
    """
    row = _get_integration(db, provider)
    tokens = integ.unpack_tokens(row["tokens_enc"])
    if not tokens.get("refresh_token"):
        raise integ.IntegrationAuthError("Not connected")
    if not tokens.get("access_token") or integ.tokens_expired(tokens):
        data = integ.refresh_access_token(
            provider, row["client_id"],
            decrypt_value(row["client_secret_enc"]),
            tokens["refresh_token"])
        merged = {
            "access_token": data["access_token"],
            "refresh_token": data.get("refresh_token")
                             or tokens["refresh_token"],
            "expires_at": int(__import__("time").time())
                           + int(data.get("expires_in", 3600)),
        }
        _save_integration(
            db, provider,
            tokens_enc=encrypt_value(json.dumps(merged)),
            status="connected", last_error="", fail_count=0)
        return merged["access_token"]
    return tokens["access_token"]


def _mark_integration_error(db, provider, message, auth_broken=False):
    """Record a sync failure. Auth failures flip status to needs_reauth."""
    row = _get_integration(db, provider)
    status = "needs_reauth" if auth_broken else row["status"]
    if row["status"] == "connected" and not auth_broken:
        status = "connected"  # transient error; stay connected
    _save_integration(db, provider, status=status, last_error=message[:500],
                      fail_count=(row["fail_count"] or 0) + 1)


@app.route("/integrations")
@permission_required("manage_users")
def integration_list():
    db = get_db()
    cards = []
    for key, cfg in integ.PROVIDERS.items():
        row = _get_integration(db, key)
        email_count = 0
        if cfg["kind"] == "email":
            email_count = db.execute(
                "SELECT COUNT(*) AS c FROM synced_emails WHERE provider = ?",
                (key,)).fetchone()["c"]
        cards.append({
            "provider": key, "label": cfg["label"], "kind": cfg["kind"],
            "icon": cfg["icon"], "description": cfg["description"],
            "status": row["status"], "last_sync_at": row["last_sync_at"],
            "last_error": row["last_error"],
            "has_credentials": bool(row["client_id"]),
            "settings": _integration_settings(row),
            "email_count": email_count,
        })
    return render_template("integrations.html", cards=cards,
                           redirect_uri=integ.redirect_uri())


@app.route("/integrations/<provider>/credentials", methods=["POST"])
@permission_required("manage_users")
def integration_credentials(provider):
    if provider not in integ.PROVIDERS:
        abort(404)
    check_csrf()
    db = get_db()
    client_id = request.form.get("client_id", "").strip()
    client_secret = request.form.get("client_secret", "").strip()
    if not client_id or not client_secret:
        flash("Client ID and client secret are both required.", "error")
        return redirect(url_for("integration_list"))
    _save_integration(db, provider, client_id=client_id,
                      client_secret_enc=encrypt_value(client_secret))
    audit("integration_credentials",
          f"Saved OAuth credentials for {integ.PROVIDERS[provider]['label']}")
    flash("Credentials saved. Click Connect to authorize.", "success")
    return redirect(url_for("integration_list"))


@app.route("/integrations/<provider>/connect")
@permission_required("manage_users")
def integration_connect(provider):
    if provider not in integ.PROVIDERS:
        abort(404)
    db = get_db()
    row = _get_integration(db, provider)
    if not row["client_id"]:
        flash("Save your OAuth client ID and secret first.", "error")
        return redirect(url_for("integration_list"))
    state = json.dumps({"provider": provider,
                        "nonce": os.urandom(8).hex()})
    session["oauth_state"] = state
    url = integ.build_authorize_url(provider, row["client_id"], state)
    return redirect(url)


@app.route("/integrations/oauth/callback")
def integration_callback():
    # OAuth must complete from the server machine (http://localhost).
    if request.host.split(":")[0] not in ("localhost", "127.0.0.1"):
        return render_template(
            "error.html", code=400,
            message="OAuth must be completed from the server computer itself"
                    " (open http://localhost:5000/integrations in a browser"
                    " on that machine)."), 400
    if not session.get("user_id"):
        return redirect(url_for("login"))
    if not user_has_perm(session.get("permissions", {}), "manage_users"):
        abort(403)
    state_raw = request.args.get("state", "")
    if not state_raw or state_raw != session.pop("oauth_state", None):
        flash("OAuth state mismatch — please try connecting again.", "error")
        return redirect(url_for("integration_list"))
    try:
        provider = json.loads(state_raw)["provider"]
    except (ValueError, KeyError):
        flash("Invalid OAuth state.", "error")
        return redirect(url_for("integration_list"))
    if request.args.get("error"):
        flash(f"Authorization declined: {request.args.get('error')}", "error")
        return redirect(url_for("integration_list"))
    code = request.args.get("code", "")
    if not code:
        flash("No authorization code received.", "error")
        return redirect(url_for("integration_list"))
    db = get_db()
    row = _get_integration(db, provider)
    try:
        data = integ.exchange_code(
            provider, row["client_id"],
            decrypt_value(row["client_secret_enc"]), code)
    except integ.IntegrationError as e:
        flash(str(e), "error")
        return redirect(url_for("integration_list"))
    _save_integration(
        db, provider,
        tokens_enc=integ.pack_tokens(data["access_token"],
                                     data.get("refresh_token", ""),
                                     data.get("expires_in", 3600)),
        status="connected", last_error="", fail_count=0,
        last_sync_at=integ.now_iso())
    audit("integration_connected",
          f"Connected {integ.PROVIDERS[provider]['label']}")
    flash(f"{integ.PROVIDERS[provider]['label']} connected.", "success")
    # Kick off an immediate sync so the UI populates right away.
    try:
        _sync_provider(provider)
    except Exception as e:  # noqa: BLE001 — first sync failure is non-fatal
        print(f"  [integrations] initial sync failed: {e}")
    return redirect(url_for("integration_list"))


@app.route("/integrations/<provider>/disconnect", methods=["POST"])
@permission_required("manage_users")
def integration_disconnect(provider):
    if provider not in integ.PROVIDERS:
        abort(404)
    check_csrf()
    db = get_db()
    if integ.PROVIDERS[provider]["kind"] == "email":
        db.execute("DELETE FROM email_case_links WHERE email_id IN"
                   " (SELECT id FROM synced_emails WHERE provider = ?)",
                   (provider,))
        db.execute("DELETE FROM synced_emails WHERE provider = ?",
                   (provider,))
    if integ.PROVIDERS[provider]["kind"] == "calendar":
        db.execute("DELETE FROM calendar_sync_map")
        # Imported Google events stay in the calendar but are marked app-side;
        # the mapping is gone so they will not be pushed back on reconnect.
    _save_integration(db, provider, status="disconnected", tokens_enc="",
                      last_error="", fail_count=0)
    audit("integration_disconnected",
          f"Disconnected {integ.PROVIDERS[provider]['label']}")
    flash(f"{integ.PROVIDERS[provider]['label']} disconnected.", "success")
    return redirect(url_for("integration_list"))


@app.route("/integrations/<provider>/sync", methods=["POST"])
@permission_required("manage_users")
def integration_sync_now(provider):
    if provider not in integ.PROVIDERS:
        abort(404)
    check_csrf()
    try:
        count = _sync_provider(provider)
    except integ.IntegrationAuthError as e:
        flash(f"Reconnection needed: {e}", "warning")
        return redirect(url_for("integration_list"))
    except integ.IntegrationError as e:
        flash(f"Sync failed: {e}", "error")
        return redirect(url_for("integration_list"))
    flash(f"Sync complete ({count} items).", "success")
    return redirect(url_for("integration_list"))


@app.route("/integrations/<provider>/settings", methods=["POST"])
@permission_required("manage_users")
def integration_settings(provider):
    if provider not in integ.PROVIDERS:
        abort(404)
    check_csrf()
    db = get_db()
    row = _get_integration(db, provider)
    settings = _integration_settings(row)
    # Only known toggles are accepted.
    if integ.PROVIDERS[provider]["kind"] == "calendar":
        settings["import_enabled"] = \
            request.form.get("import_enabled") == "on"
    _save_integration(db, provider, settings=json.dumps(settings))
    flash("Settings saved.", "success")
    return redirect(url_for("integration_list"))


# ----------------------------------------------------------------------------
# Sync engine
# ----------------------------------------------------------------------------

def _sync_provider(provider):
    """Run one sync for a provider. Returns items synced. Runs inside an
    app context (works from the background thread too)."""
    with app.app_context():
        db = get_db()
        kind = integ.PROVIDERS[provider]["kind"]
        try:
            token = _integration_access_token(db, provider)
        except integ.IntegrationAuthError as e:
            _mark_integration_error(db, provider, str(e), auth_broken=True)
            raise
        try:
            if kind == "email":
                count = _sync_emails(db, provider, token)
            else:
                count = _sync_calendar(db, provider, token)
        except integ.IntegrationAuthError as e:
            _mark_integration_error(db, provider, str(e), auth_broken=True)
            raise
        except integ.IntegrationError as e:
            _mark_integration_error(db, provider, str(e))
            raise
        _save_integration(db, provider, status="connected", last_error="",
                          fail_count=0, last_sync_at=integ.now_iso())
        return count


def _sync_emails(db, provider, token):
    """Pull recent messages, store them, auto-link to cases."""
    now = integ.now_iso()
    new_count = 0
    if provider == "gmail":
        listing = integ.gmail_list_messages(token, max_results=25)
        ids = [m["id"] for m in listing.get("messages", [])]
        fetch = lambda mid: integ.gmail_get_message(token, mid)  # noqa: E731
    else:  # outlook
        listing = integ.graph_list_messages(token, max_results=25)
        fetched = {m["id"]: integ.graph_normalize(m)
                   for m in listing.get("value", [])}
        ids = list(fetched.keys())
        fetch = fetched.get
    for mid in ids:
        exists = db.execute(
            "SELECT id FROM synced_emails WHERE provider = ? AND"
            " external_id = ?", (provider, mid)).fetchone()
        if exists:
            continue
        try:
            msg = fetch(mid)
        except integ.IntegrationError:
            continue
        cur = db.execute(
            "INSERT INTO synced_emails (provider, external_id, thread_id,"
            " subject, from_addr, to_addr, sent_at, snippet, body,"
            " direction, synced_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (provider, msg["external_id"], msg.get("thread_id", ""),
             msg["subject"][:300], msg["from_addr"][:200],
             msg["to_addr"][:500], msg.get("sent_at", "")[:60],
             msg.get("snippet", "")[:500], msg.get("body", "")[:8000],
             "inbound", now))
        email_id = cur.lastrowid
        for case_id in integ.match_email_to_cases(
                db, msg["from_addr"], msg["to_addr"], msg["subject"]):
            db.execute(
                "INSERT OR IGNORE INTO email_case_links"
                " (email_id, case_id, link_type, created_at)"
                " VALUES (?,?, 'auto', ?)", (email_id, case_id, now))
        new_count += 1
    db.commit()
    return new_count


def _event_to_gcal_dt(event_date, event_time):
    """App event -> ISO datetime for Google Calendar (assumes local day)."""
    t = (event_time or "09:00").strip() or "09:00"
    if len(t) == 5:
        t += ":00"
    return f"{event_date}T{t}"


def _sync_calendar(db, provider, token):
    """Two-way sync with Google Calendar. Returns items changed."""
    from datetime import timedelta
    changed = 0
    settings = _integration_settings(_get_integration(db, provider))

    # --- App -> Google: push upcoming app events -------------------------
    upcoming = db.execute(
        "SELECT * FROM calendar_events WHERE completed = 0 AND source = 'app'"
        " AND event_date >= ? ORDER BY event_date LIMIT 100",
        (date.today().isoformat(),)).fetchall()
    for ev in upcoming:
        mapped = db.execute(
            "SELECT google_event_id FROM calendar_sync_map"
            " WHERE app_event_id = ?", (ev["id"],)).fetchone()
        case = db.execute("SELECT case_number FROM cases WHERE id = ?",
                          (ev["case_id"],)).fetchone() if ev["case_id"] else None
        title = ev["title"]
        if case:
            title = f"[{case['case_number']}] {title}"
        desc = (ev["description"] or "") + "\n\n— synced from Law Office app"
        start = _event_to_gcal_dt(ev["event_date"], ev["event_time"])
        try:
            if mapped:
                integ.gcal_update_event(token, mapped["google_event_id"],
                                        title, start, start, desc)
            else:
                gid = integ.gcal_insert_event(token, title, start, start,
                                              desc, app_event_id=ev["id"])
                db.execute(
                    "INSERT INTO calendar_sync_map (app_event_id,"
                    " google_event_id, updated_at) VALUES (?,?,?)",
                    (ev["id"], gid, integ.now_iso()))
            changed += 1
        except integ.IntegrationError:
            continue  # one bad event must not kill the whole sync

    # --- Google -> App: import (only when the toggle is on) --------------
    if settings.get("import_enabled"):
        now = datetime.now(timezone.utc)
        tmin = now.isoformat()
        tmax = (now + timedelta(days=60)).isoformat()
        try:
            listing = integ.gcal_list_events(token, time_min=tmin,
                                             time_max=tmax, max_results=50)
        except integ.IntegrationError:
            listing = {"items": []}
        for item in listing.get("items", []):
            norm = integ.gcal_normalize(item)
            if norm["app_event_id"]:
                continue  # it came from us; skip
            exists = db.execute(
                "SELECT id FROM calendar_events WHERE source = 'google'"
                " AND external_id = ?", (norm["external_id"],)).fetchone()
            if exists:
                continue
            start = norm["start"][:10]
            if not start:
                continue
            db.execute(
                "INSERT INTO calendar_events (case_id, title, event_type,"
                " event_date, event_time, description, completed, source,"
                " external_id, created_at) VALUES (NULL,?, 'reminder', ?, ?,"
                " ?, 0, 'google', ?, ?)",
                (norm["title"][:200], start,
                 norm["start"][11:16] if len(norm["start"]) > 12 else "",
                 (norm["description"] or "")[:1000], norm["external_id"],
                 integ.now_iso()))
            changed += 1
    db.commit()
    return changed


def integration_scheduler():
    """Background loop: sync every connected provider every 15 minutes."""
    import time as _time
    while True:
        _time.sleep(15 * 60)
        try:
            with app.app_context():
                db = get_db()
                rows = db.execute(
                    "SELECT provider FROM integrations"
                    " WHERE status = 'connected'").fetchall()
            for r in rows:
                try:
                    _sync_provider(r["provider"])
                except Exception as e:  # noqa: BLE001 — never kill scheduler
                    print(f"  [integrations] sync error"
                          f" ({r['provider']}): {e}")
        except Exception as e:  # noqa: BLE001
            print(f"  [integrations] scheduler error: {e}")


def start_integration_scheduler():
    import threading as _th
    t = _th.Thread(target=integration_scheduler, daemon=True,
                   name="integration-scheduler")
    t.start()


# ----------------------------------------------------------------------------
# Case email views: list, manual link/unlink, compose
# ----------------------------------------------------------------------------

@app.route("/cases/<int:case_id>/emails")
@permission_required("view_cases")
def case_emails(case_id):
    # Emails live as a tab on the case detail page.
    return redirect(url_for("case_detail", case_id=case_id, tab="emails"))


@app.route("/cases/<int:case_id>/emails/<int:email_id>/link",
           methods=["POST"])
@permission_required("manage_cases")
def case_email_link(case_id, email_id):
    check_csrf()
    db = get_db()
    if not db.execute("SELECT id FROM cases WHERE id = ?",
                      (case_id,)).fetchone():
        abort(404)
    if not db.execute("SELECT id FROM synced_emails WHERE id = ?",
                      (email_id,)).fetchone():
        abort(404)
    db.execute(
        "INSERT OR IGNORE INTO email_case_links"
        " (email_id, case_id, link_type, created_at) VALUES (?,?, 'manual', ?)",
        (email_id, case_id, integ.now_iso()))
    db.commit()
    audit("email_link", f"Manually linked email {email_id} to case {case_id}")
    flash("Email linked to this case.", "success")
    return redirect(url_for("case_detail", case_id=case_id, tab="emails"))


@app.route("/cases/<int:case_id>/emails/<int:email_id>/unlink",
           methods=["POST"])
@permission_required("manage_cases")
def case_email_unlink(case_id, email_id):
    check_csrf()
    db = get_db()
    db.execute("DELETE FROM email_case_links WHERE email_id = ? AND"
               " case_id = ?", (email_id, case_id))
    db.commit()
    audit("email_unlink",
          f"Unlinked email {email_id} from case {case_id}")
    flash("Email unlinked.", "success")
    return redirect(url_for("case_detail", case_id=case_id, tab="emails"))


@app.route("/cases/<int:case_id>/compose", methods=["GET", "POST"])
@permission_required("manage_cases")
def case_compose(case_id):
    db = get_db()
    case = db.execute(
        "SELECT c.*, cl.first_name, cl.last_name, cl.email FROM cases c"
        " LEFT JOIN clients cl ON c.client_id = cl.id WHERE c.id = ?",
        (case_id,)).fetchone()
    if not case:
        abort(404)
    connected = [r["provider"] for r in db.execute(
        "SELECT provider FROM integrations WHERE status = 'connected'"
    ).fetchall()]
    email_providers = [p for p in connected
                       if integ.PROVIDERS[p]["kind"] == "email"]
    if request.method == "POST":
        check_csrf()
        provider = request.form.get("provider", "")
        to_addr = request.form.get("to", "").strip()
        subject = request.form.get("subject", "").strip()
        body = request.form.get("body", "").strip()
        if provider not in email_providers:
            flash("Select a connected email account.", "error")
            return redirect(url_for("case_compose", case_id=case_id))
        if not to_addr or not subject or not body:
            flash("To, subject, and message are all required.", "error")
            return redirect(url_for("case_compose", case_id=case_id))
        try:
            token = _integration_access_token(db, provider)
            if provider == "gmail":
                integ.gmail_send(token, to_addr, subject, body)
            else:
                integ.graph_send(token, to_addr, subject, body)
        except integ.IntegrationAuthError as e:
            flash(f"Email account needs reconnecting: {e}", "warning")
            return redirect(url_for("integration_list"))
        except integ.IntegrationError as e:
            flash(f"Send failed: {e}", "error")
            return redirect(url_for("case_compose", case_id=case_id))
        # Log the sent message to the case
        now = integ.now_iso()
        cur = db.execute(
            "INSERT INTO synced_emails (provider, external_id, subject,"
            " from_addr, to_addr, sent_at, snippet, body, direction,"
            " synced_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (provider, f"sent-{now}-{os.urandom(4).hex()}",
             subject[:300], "me", to_addr[:500], now, body[:500],
             body[:8000], "outbound", now))
        db.execute(
            "INSERT OR IGNORE INTO email_case_links"
            " (email_id, case_id, link_type, created_at) VALUES (?,?,?,?)",
            (cur.lastrowid, case_id, "sent", now))
        db.commit()
        audit("email_send",
              f"Sent email via {provider} for case {case['case_number']}")
        flash("Email sent and logged to this case.", "success")
        return redirect(url_for("case_detail", case_id=case_id, tab="emails"))
    default_subject = f"Re: {case['case_number']} — {case['title']}"
    return render_template("email_compose.html", case=case,
                           email_providers=email_providers,
                           default_subject=default_subject)


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
    start_clallam_schedule_monitor()
    start_integration_scheduler()

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
