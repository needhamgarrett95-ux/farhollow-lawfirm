#!/usr/bin/env python3
"""v2.12.0 checks — radio/checkbox bubble fix, staff live notifications,
and the light/dark theme readability pass.

Against a scratch copy of the app:
  * BUBBLES: the giant confirm-card radio discs came from unscoped
    bare-input sizing rules (.p-form input {width:100%} tied the global
    18px bubble rule on specificity and won on source order; the phone
    band's label-input rule added padding/min-height on top). Checks:
    every generic input-sizing rule in style.css now excludes
    checkbox/radio; the bubble rules (global 18px, component 20px,
    phone band 22px) exist; the confirm-choice pills are >=44px with a
    wrapping flex layout; a rendered wizard confirm card carries its
    radios inside the .p-confirm-choice labels.
  * LIVE NOTIFICATIONS: GET /api/notifications/summary returns the
    same counts the page-load badges/widget show (seeded unread
    message + pending submission + quarantined upload), drops when
    items are handled, is permission-filtered (no view_clients -> no
    portal counts; no view_all_timeclocks -> no corrections), rejects
    anonymous and portal-realm sessions with 401 (never counts),
    403s during a forced password change, enforces the idle timeout
    WITHOUT refreshing it (a background poll is not user activity),
    and the poller + toast markup ships in the staff shell only.
  * THEMES: parse the shipped token blocks (light + dark) and assert
    WCAG contrast for the pairs the UI actually uses — body/muted/
    navy text on the real surfaces, white + link colors on the brand
    bars, semantic text on semantic backgrounds, placeholder
    (full-strength muted), input borders >= 3:1 — plus structural
    checks that no component uses var(--navy) as a background (it is a
    TEXT token; it flips light in dark mode) and the portal firm name
    is white on the navy bar.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap

TEST_CODE = r'''
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.getcwd())
import app as appmod
import crypto as cryptomod

appmod.app.config.update(TESTING=True)
with appmod.app.app_context():
    appmod.init_db()

FAILURES = []

def check(name, cond, detail=""):
    if cond:
        print("PASS -", name)
    else:
        FAILURES.append(name)
        print("FAIL -", name, detail)

CSS = open(os.path.join("static", "style.css")).read()

def dbx(sql, args=()):
    with appmod.app.app_context():
        db = appmod.get_db()
        db.execute(sql, args)
        db.commit()

def enc(v):
    return cryptomod.encrypt_value(v)

NOW = datetime.now(timezone.utc).isoformat()
PW0 = "changeme" + "123"

def csrf(cl):
    with cl.session_transaction() as s:
        return s.get("csrf_token", "")

# ======================================================================
# A. Bubbles — static CSS: generic input rules must exclude bubbles
# ======================================================================
for pat, label in [
    ('.p-form input:not([type="checkbox"]):not([type="radio"])',
     ".p-form input scoped"),
    ('label input:not([type="checkbox"]):not([type="radio"])',
     "label input scoped"),
    ('.child-form input:not([type="checkbox"]):not([type="radio"])',
     ".child-form input scoped"),
    ('.stacked-form input:not([type="checkbox"]):not([type="radio"])',
     ".stacked-form input scoped"),
    ('.compose-row input:not([type="checkbox"]):not([type="radio"])',
     ".compose-row input scoped"),
    ('.search-row input:not([type="checkbox"]):not([type="radio"])',
     ".search-row input scoped"),
]:
    check("bubbles: " + label, pat in CSS)

# No unscoped generic selector survives anywhere in the sheet.
for bad in ['.p-form input,', '.p-form input {',
            '.child-form input {', '.stacked-form input {',
            '.compose-row input,', '.search-row input {']:
    check("bubbles: unscoped selector gone: " + bad, bad not in CSS)
check("bubbles: unscoped selector gone: label input",
      not re.search(r"(?<![\w.-])label input\s*[,{]", CSS))

# The bubble sizing rules themselves.
m = re.search(r'input\[type=checkbox\], input\[type=radio\] \{\s*'
              r'width: 18px; height: 18px;', CSS)
check("bubbles: global desktop bubble rule is 18px fixed", bool(m))
m = re.search(r'\.p-confirm-choice input\[type="radio"\] \{\s*'
              r'width: 20px; height: 20px; flex: none;', CSS)
check("bubbles: confirm-choice bubble rule is 20px fixed", bool(m))
m = re.search(r'\.p-type-card input\[type="radio"\], '
              r'\.p-type-card input\[type="checkbox"\] \{\s*'
              r'width: 20px; height: 20px;', CSS)
check("bubbles: type-card rule covers radio AND checkbox at 20px",
      bool(m))
m = re.search(r'\.p-confirm-choice input\[type="radio"\] '
              r'\{ width: 22px; height: 22px; \}', CSS)
check("bubbles: phone band sizes all bubbles at 22px", bool(m))
m = re.search(r'\.p-confirm-choice \{(.*?)\}', CSS, re.S)
check("bubbles: confirm pills are >=44px and wrap instead of squeezing",
      bool(m) and 'min-height: 44px' in m.group(1)
      and 'flex: 1 1 150px' in m.group(1))
m = re.search(r'\.p-attest-check input \{ width: 22px; height: 22px;',
              CSS)
check("bubbles: attestation checkbox stays 22px", bool(m))

# ======================================================================
# B. Themes — token contrast, computed from the shipped stylesheet
# ======================================================================
def parse_block(pat):
    mm = re.search(pat + r"\s*\{([^}]*)\}", CSS)
    out = {}
    for name, val in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", mm.group(1)):
        out[name[2:]] = val.strip()
    return out

LIGHT = parse_block(r":root")
DARK = parse_block(r'html\[data-theme="dark"\]')

def hexrgb(h):
    h = h.lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def parse_color(spec, tokens):
    if spec in tokens:
        spec = tokens[spec]
    spec = spec.strip()
    if spec.startswith('#'):
        return hexrgb(spec), 1.0
    mm = re.match(r"rgba?\(([^)]*)\)", spec)
    parts = [p.strip() for p in mm.group(1).split(',')]
    return (tuple(int(float(p)) for p in parts[:3]),
            float(parts[3]) if len(parts) > 3 else 1.0)

def composite(fg, a, bg):
    return tuple(round(a * f + (1 - a) * b) for f, b in zip(fg, bg))

def lum(rgb):
    def f(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)

def ratio(fg_spec, bg_spec, tokens):
    bg_rgb, bg_a = parse_color(bg_spec, tokens)
    if bg_a < 1.0:
        base, _ = parse_color("card", tokens)
        bg_rgb = composite(bg_rgb, bg_a, base)
    fg_rgb, fg_a = parse_color(fg_spec, tokens)
    if fg_a < 1.0:
        fg_rgb = composite(fg_rgb, fg_a, bg_rgb)
    l1, l2 = lum(fg_rgb), lum(bg_rgb)
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)

PAIRS_45 = [
    ("text", "card"), ("text", "bg"), ("text", "surface-soft"),
    ("muted", "card"), ("muted", "bg"), ("muted", "surface-soft"),
    ("muted", "input-bg"), ("muted", "today-bg"),
    ("navy", "card"), ("#ffffff", "brand"),
    ("error", "error-bg"), ("error", "card"),
    ("success", "success-bg"), ("success", "card"),
    ("warning-text", "warning-bg"), ("warning-text", "card"),
    ("info-text", "info-bg"),
    ("gold-light", "brand"), ("#dbe4f0", "brand"), ("#c8d4e6", "brand"),
    ("navy-dark", "gold"), ("navy-dark", "gold-light"),
]
PAIRS_30 = [
    ("input-border", "input-bg"), ("input-border", "card"),
    ("gold-deep", "surface-soft"), ("gold-deep", "card"),
]
for tname, toks in (("light", LIGHT), ("dark", DARK)):
    for fg, bg in PAIRS_45:
        r = ratio(fg, bg, toks)
        check(f"theme {tname}: {fg} on {bg} >= 4.5", r >= 4.5,
              f"got {r:.2f}")
    for fg, bg in PAIRS_30:
        r = ratio(fg, bg, toks)
        check(f"theme {tname}: {fg} on {bg} >= 3.0", r >= 3.0,
              f"got {r:.2f}")
check("theme dark: white on the dark danger-button red >= 4.5",
      ratio("#ffffff", "#b91c1c", DARK) >= 4.5)

# Structural theme rules. --navy is a TEXT token (it flips light in
# dark mode); a component may only sit on it if it carries an explicit
# dark override (integration icon, tab badge, own-message bubble do).
navy_bg = re.findall(r"([^{}]+)\{\s*background: var\(--navy\)", CSS)
uncovered = [s.strip() for s in navy_bg
             if 'html[data-theme="dark"] ' + s.strip().split("{")[0]
             not in CSS]
check("theme: every var(--navy) background has a dark override",
      not uncovered, str(uncovered))
check("theme: portal firm name is white on the navy bar",
      bool(re.search(r"\.p-topbar \.firm-name \{ color: #fff; \}", CSS)))
check("theme: portal topbar sits on --brand (dark-safe)",
      bool(re.search(r"\.p-topbar \{[^}]*background: var\(--brand\)",
                     CSS)))
check("theme: step counter uses the navy TEXT token, not --brand",
      bool(re.search(r"\.p-progress \{[^}]*color: var\(--navy\)", CSS)))
check("theme: 'due soon' text uses --warning-text",
      bool(re.search(r"\.mini \.r\.soon \{ color: var\(--warning-text\)",
                     CSS)))
check("theme: placeholders render at full muted strength",
      "::placeholder { color: var(--muted); opacity: 1; }" in CSS)
check("theme: dark danger button has its deep-red override",
      'html[data-theme="dark"] .btn-modal-danger' in CSS
      and "#b91c1c" in CSS)
check("theme: gold-deep token exists in both themes",
      "gold-deep" in LIGHT and "gold-deep" in DARK)

# ======================================================================
# Seed: admin, restricted users, a portal client with vault facts
# ======================================================================
dbx("INSERT INTO clients (first_name,last_name,email,phone,address,"
    "date_of_birth,spouse_name,spouse_dob,ssn,created_at,updated_at)"
    " VALUES ('Alice','Anderson','alice@example.com','360-555-0100',"
    "'12 Harbor Way',?,?,?,?,?,?)",
    (enc("1988-04-02"), "Andrew Anderson", enc("1986-09-14"),
     enc("123-45-6789"), NOW, NOW))
dbx("INSERT INTO cases (client_id,title,case_number,case_type,status,"
    "created_at,updated_at) VALUES (1,'Anderson v. Anderson',"
    "'26-2-00101','dissolution','open',?,?)", (NOW, NOW))

admin = appmod.app.test_client()
admin.get("/login")
admin.post("/login", data={"username": "admin", "password": PW0,
                           "csrf_token": csrf(admin)})
admin.post("/change-password", data={
    "current_password": PW0, "new_password": "Admin" + "Pass123!",
    "confirm_password": "Admin" + "Pass123!",
    "csrf_token": csrf(admin)})

from werkzeug.security import generate_password_hash

def make_user(username, role, perms=None, must_change=0):
    if perms is None:
        perms = appmod.role_default_permissions(role)
    dbx("INSERT INTO users (username,password_hash,full_name,"
        "role,permissions,is_active,must_change_password,created_at)"
        " VALUES (?,?,?,?,?,1,?,?)",
        (username, generate_password_hash("Password" + "123!"),
         username.title(), role, json.dumps(perms), must_change, NOW))
    cl = appmod.app.test_client()
    cl.get("/login")
    cl.post("/login", data={"username": username,
                            "password": "Password" + "123!",
                            "csrf_token": csrf(cl)})
    return cl

acct = make_user("acct", "accountant")   # view_clients, NO view_all_timeclocks
nobody_perms = {k: False for k in appmod.role_default_permissions("staff")}
nobody_perms["view_dashboard"] = True
nobody = make_user("nobody", "staff", perms=nobody_perms)
changer = make_user("changer", "staff", must_change=1)

# Portal client A
admin.post("/clients/1/portal/invite", data={"csrf_token": csrf(admin)})
r = admin.get("/clients/1")
tok = re.search(rb"/portal/accept-invite/([A-Za-z0-9_\-]+)",
                r.data).group(1).decode()
A = appmod.app.test_client()
A.get(f"/portal/accept-invite/{tok}")
A.post(f"/portal/accept-invite/{tok}", data={
    "password": "Alice" + "Pass123",
    "confirm_password": "Alice" + "Pass123",
    "csrf_token": csrf(A)})
A.get("/portal/login")
A.post("/portal/login", data={"email": "alice@example.com",
                              "password": "Alice" + "Pass123",
                              "csrf_token": csrf(A)})

# ======================================================================
# B2. Bubbles — the rendered confirm card
# ======================================================================
r = A.get("/portal/library/confidential-information?step=0")
check("bubbles: CIF step renders confirm cards",
      r.status_code == 200 and b"We have:" in r.data
      and b"Still right" in r.data and b"It changed" in r.data)
check("bubbles: radios live inside the .p-confirm-choice pills",
      bool(re.search(rb'<label class="p-confirm-choice">\s*'
                     rb'<input type="radio"', r.data)))
check("bubbles: both choices render (keep + change)",
      r.data.count(b'class="p-confirm-choice"') >= 4)

# ======================================================================
# C. Live notifications endpoint
# ======================================================================
anon = appmod.app.test_client()
r = anon.get("/api/notifications/summary")
check("notif: anonymous gets 401 and no counts",
      r.status_code == 401 and b'"portal"' not in r.data
      and b'"deadlines"' not in r.data)
r = A.get("/api/notifications/summary")
check("notif: portal-realm session gets 401 and no counts",
      r.status_code == 401 and b'"portal"' not in r.data)
r = changer.get("/api/notifications/summary")
check("notif: forced password change gets 403",
      r.status_code == 403)

r = admin.get("/api/notifications/summary")
j = r.get_json()
check("notif: empty state is all zeros for a full-permission user",
      r.status_code == 200
      and j["portal"] == {"uploads": 0, "forms": 0, "messages": 0,
                          "total": 0}
      and j["corrections"] == 0 and isinstance(j["deadlines"], int))

# Seed one of each portal item (+ handled decoys that must NOT count)
dbx("INSERT INTO portal_messages (client_id,sender_type,body,created_at)"
    " VALUES (1,'client','hello?',?)", (NOW,))
dbx("INSERT INTO portal_messages (client_id,sender_type,body,created_at,"
    "read_by_staff_at) VALUES (1,'client','already read',?,?)",
    (NOW, NOW))
dbx("INSERT INTO portal_messages (client_id,sender_type,body,created_at)"
    " VALUES (1,'staff','our reply',?)", (NOW,))
dbx("INSERT INTO portal_uploads (client_id,doc_type,original_name,"
    "stored_name,status,uploaded_at) VALUES (1,'other','x.pdf','x.pdf',"
    "'pending',?)", (NOW,))
dbx("INSERT INTO portal_uploads (client_id,doc_type,original_name,"
    "stored_name,status,uploaded_at) VALUES (1,'other','y.pdf','y.pdf',"
    "'accepted',?)", (NOW,))
dbx("INSERT INTO portal_form_submissions (client_id,form_key,status,"
    "created_at,updated_at) VALUES (1,'intake','submitted',?,?)",
    (NOW, NOW))
dbx("INSERT INTO portal_form_submissions (client_id,form_key,status,"
    "created_at,updated_at) VALUES (1,'intake','draft',?,?)",
    (NOW, NOW))
dbx("INSERT INTO employees (full_name,pay_rate_cents,created_at)"
    " VALUES ('Emp One',2500,?)", (NOW,))
dbx("INSERT INTO timeclock_corrections (employee_id,correction_date,"
    "correction_type,reason,status,requested_by,requested_at,created_at)"
    " VALUES (1,'2026-10-19','missed_clock_in','forgot','pending',1,?,?)",
    (NOW, NOW))
tomorrow = (datetime.now(timezone.utc).date()
            + timedelta(days=1)).isoformat()
dbx("INSERT INTO calendar_events (title,event_type,event_date,completed,"
    "created_at)"
    " VALUES ('Hearing','court_date',?,0,?)", (tomorrow, NOW))

r = admin.get("/api/notifications/summary")
j = r.get_json()
check("notif: seeded counts are exact (decoys excluded)",
      j["portal"] == {"uploads": 1, "forms": 1, "messages": 1,
                      "total": 3}
      and j["corrections"] == 1 and j["deadlines"] >= 1, str(j))

# Endpoint agrees with the page-load numbers (nav badge + widget).
r = admin.get("/dashboard")
html = r.data.decode()
m = re.search(r'data-notif-num="uploads">(\d+)<', html)
check("notif: dashboard widget uploads matches endpoint",
      m and int(m.group(1)) == j["portal"]["uploads"])
m = re.search(r'data-notif-num="messages">(\d+)<', html)
check("notif: dashboard widget messages matches endpoint",
      m and int(m.group(1)) == j["portal"]["messages"])
m = re.search(r'data-badge-for="nav_portal_count"[^>]*>(\d+)<', html)
check("notif: rendered nav badge matches endpoint total",
      m and int(m.group(1)) == j["portal"]["total"])
check("notif: staff shell ships poller + toast + badge hooks",
      "notifToast" in html and "/api/notifications/summary" in html
      and "visibilitychange" in html and "data-badge-sum" in html)
r = A.get("/portal/home")
check("notif: portal shell has NO poller or toast",
      b"notifToast" not in r.data
      and b"/api/notifications/summary" not in r.data)
r = anon.get("/login")
check("notif: login page has NO poller or toast",
      b"notifToast" not in r.data
      and b"/api/notifications/summary" not in r.data)

# Permission filtering.
r = acct.get("/api/notifications/summary")
j2 = r.get_json()
check("notif: view_clients without view_all_timeclocks keeps portal, "
      "loses corrections",
      j2["portal"] is not None and j2["portal"]["total"] == 3
      and j2["corrections"] is None, str(j2))
r = nobody.get("/api/notifications/summary")
j3 = r.get_json()
check("notif: no view_clients -> portal counts withheld entirely",
      j3["portal"] is None and j3["corrections"] is None
      and isinstance(j3["deadlines"], int), str(j3))

# Counts drop as items are handled.
dbx("UPDATE portal_messages SET read_by_staff_at = ?"
    " WHERE sender_type = 'client' AND read_by_staff_at IS NULL",
    (NOW,))
dbx("UPDATE portal_uploads SET status = 'accepted'"
    " WHERE status = 'pending'")
r = admin.get("/api/notifications/summary")
j = r.get_json()
check("notif: counts fall when items are handled",
      j["portal"] == {"uploads": 0, "forms": 1, "messages": 0,
                      "total": 1}, str(j))

# Idle timeout: enforced, but polling must NOT refresh activity.
with admin.session_transaction() as s:
    s["last_activity"] = (datetime.now(timezone.utc)
                          - timedelta(minutes=20)).isoformat()
    before = s["last_activity"]
r = admin.get("/api/notifications/summary")
with admin.session_transaction() as s:
    after = s.get("last_activity")
check("notif: poll inside the window works and does NOT extend it",
      r.status_code == 200 and after == before,
      f"{r.status_code} {before} -> {after}")
with admin.session_transaction() as s:
    s["last_activity"] = (datetime.now(timezone.utc)
                          - timedelta(minutes=31)).isoformat()
r = admin.get("/api/notifications/summary")
check("notif: poll past the idle timeout is refused (401)",
      r.status_code == 401)

print()
if FAILURES:
    print("FAILURES:", FAILURES)
    raise SystemExit(1)
print("ALL V212 CHECKS PASSED")
'''


def main():
    tmp = tempfile.mkdtemp(prefix="lawfirm-v212-")
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        root = os.path.dirname(here)
        for name in ("app.py", "crypto.py", "deadlines.py",
                     "integrations.py", "invoice_pdf.py", "payroll.py",
                     "paystub_pdf.py", "template_defs.py",
                     "template_pdf.py", "form_library.py"):
            shutil.copy(os.path.join(root, name), tmp)
        shutil.copytree(os.path.join(root, "templates"),
                        os.path.join(tmp, "templates"))
        shutil.copytree(os.path.join(root, "static"),
                        os.path.join(tmp, "static"))
        os.makedirs(os.path.join(tmp, "instance"))
        testfile = os.path.join(tmp, "run_v212_checks.py")
        with open(testfile, "w") as fh:
            fh.write(textwrap.dedent(TEST_CODE))
        proc = subprocess.run([sys.executable, testfile], cwd=tmp,
                              capture_output=True, text=True,
                              timeout=600)
        sys.stdout.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        return proc.returncode
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
