"""
Farhollow Law Firm - Case Management System (v1 Foundation)
Self-hosted, single-process Flask app for a solo family law practice.

Run:  python app.py
Then open: http://localhost:5000
"""
import os
import sqlite3
import secrets
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, g, flash, abort,
)
from werkzeug.security import generate_password_hash, check_password_hash

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

CASE_TYPES = ["divorce", "custody", "support", "adoption", "other"]
CASE_STATUSES = ["active", "pending", "closed"]

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
    age = datetime.utcnow() - record_date
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
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
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

    # One-time migration: encrypt any plaintext sensitive fields written
    # before field-level encryption was enabled.
    _migrate_field_encryption(db)

    # Seed default admin on first run
    row = db.execute("SELECT COUNT(*) AS c FROM users").fetchone()
    if row["c"] == 0:
        now = datetime.utcnow().isoformat()
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
            datetime.utcnow().isoformat(),
            session.get("user_id"),
            session.get("username"),
            action,
            details,
        ),
    )
    db.commit()


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
            idle = datetime.utcnow() - datetime.fromisoformat(last)
            if idle > timedelta(minutes=SESSION_TIMEOUT_MINUTES):
                session.clear()
                flash("You were logged out due to inactivity.", "warning")
                return redirect(url_for("login"))
        session["last_activity"] = datetime.utcnow().isoformat()
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
            session["last_activity"] = datetime.utcnow().isoformat()
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
    }
    recent = db.execute(
        "SELECT * FROM audit_log ORDER BY id DESC LIMIT 10"
    ).fetchall()
    return render_template(
        "dashboard.html", stats=stats, active_cases=active_cases, recent=recent
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


@app.route("/clients/new", methods=["GET", "POST"])
@login_required
def client_new():
    if request.method == "POST":
        check_csrf()
        now = datetime.utcnow().isoformat()
        db = get_db()
        cur = db.execute(
            "INSERT INTO clients (first_name, last_name, email, phone, address,"
            " date_of_birth, spouse_name, spouse_dob, ssn, notes, created_at,"
            " updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
        now = datetime.utcnow().isoformat()
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
        now = datetime.utcnow().isoformat()
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
    audit("case_view", f"Viewed case {case['case_number']} (id={case_id})")
    return render_template("case_detail.html", case=case)


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
        now = datetime.utcnow().isoformat()
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
    with app.app_context():
        init_db()
    print("\n  Farhollow Law Firm - Case Management")
    print("  Open your browser to:  http://localhost:5000\n")
    # Bind to localhost only by default — the app is meant for this machine.
    # Change host to "0.0.0.0" only if you need office-network access and
    # understand the security implications.
    app.run(host="127.0.0.1", port=5000, debug=False)
