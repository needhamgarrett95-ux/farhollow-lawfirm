#!/usr/bin/env python3
"""v2.12.1 checks — filled-button label contrast sweep.

The v2.12.0 theme pass audited theme TOKEN pairs. Garrett's screenshot
proved that insufficient: the Portal Review queue's "Review" button
(<a class="btn btn-primary"> inside a .table cell) rendered navy text
on the navy button fill — .btn-primary declares color:#fff at
specificity (0,1,0), but the context rule `.table a { color: var(--navy) }`
at (0,1,1) overrode it. 1.00:1 in light, 2.37:1 in dark. The "Open"
button in the portal message inbox had the identical defect.

This suite is the component-level net the token audit lacked: it parses
the shipped stylesheet, and for a maintained list of filled components
(buttons, badges, pills, chips, toasts, banner actions, tab/sheet chrome,
portal components) resolves each one's EFFECTIVE background and label
color as rendered — component rules merged in cascade order, dark-theme
overrides applied, gradients taken at their worst stop, rgba and
color-mix composited over the real backdrop, hover brightness filters
applied to both sides, and known context overrides modelled — then
asserts WCAG AA >= 4.5:1 in BOTH themes.

Rules going forward (MAINTENANCE §57):
  * a component that fills its own background owns its label color;
  * context rules (e.g. table link styling) must never restyle buttons —
    `.table a` is scoped `:not(.btn)`.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap

TEST_CODE = r'''
import os
import re
import sys

FAILURES = []

def check(name, cond, detail=""):
    if cond:
        print("PASS -", name)
    else:
        FAILURES.append(name)
        print("FAIL -", name, detail)

CSS = open(os.path.join("static", "style.css")).read()

# ----------------------------------------------------------------------
# CSS parsing: rules in source order, with theme/media context flags
# ----------------------------------------------------------------------
def strip_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)

def parse_decls(body):
    d = {}
    for part in body.split(";"):
        if ":" in part:
            p, v = part.split(":", 1)
            d[p.strip()] = v.strip()
    return d

RULES = []  # (selector, decls, is_dark, is_media)
def walk(text, dark, media):
    i = 0
    while i < len(text):
        j = text.find("{", i)
        if j == -1:
            break
        prelude = text[i:j].strip()
        depth, k = 1, j + 1
        while k < len(text) and depth:
            if text[k] == "{":
                depth += 1
            elif text[k] == "}":
                depth -= 1
            k += 1
        body = text[j + 1:k - 1]
        if prelude.startswith("@media"):
            walk(body, dark, True)
        elif prelude.startswith("@"):
            pass
        elif 'html[data-theme="dark"]' in prelude:
            core = prelude.replace('html[data-theme="dark"]', "").strip()
            RULES.append((core, parse_decls(body), True, media))
        else:
            RULES.append((prelude, parse_decls(body), dark, media))
        i = k

walk(strip_comments(CSS), False, False)

def parse_tokens():
    light, dark = {}, {}
    for sel, decls, is_dark, _m in RULES:
        if sel == ":root" and not is_dark:
            light.update({k: v for k, v in decls.items()
                          if k.startswith("--")})
        if sel == "" and is_dark:
            dark.update({k: v for k, v in decls.items()
                         if k.startswith("--")})
    merged = dict(light)
    merged.update(dark)
    return light, merged

LIGHT, DARK = parse_tokens()

def resolve(value, tokens, depth=0):
    if value is None or depth > 8:
        return value
    def sub(m):
        name, fallback = m.group(1), m.group(2)
        if name in tokens:
            return resolve(tokens[name], tokens, depth + 1)
        return fallback.strip() if fallback else m.group(0)
    return re.sub(r"var\(\s*(--[a-z0-9-]+)\s*(?:,\s*([^)]*))?\)",
                  sub, value)

def parse_rgb(spec):
    """-> (r,g,b,alpha) floats 0..1, or None."""
    if spec is None:
        return None
    spec = spec.strip()
    m = re.fullmatch(r"#([0-9a-f]{3}|[0-9a-f]{6})", spec, flags=re.I)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)) + (1.0,)
    m = re.fullmatch(r"rgba?\(([^)]*)\)", spec, flags=re.I)
    if m:
        parts = [p.strip() for p in m.group(1).split(",")]
        rgb = tuple(int(float(p)) / 255 for p in parts[:3])
        return rgb + (float(parts[3]) if len(parts) > 3 else 1.0,)
    if spec.lower() == "white":
        return (1.0, 1.0, 1.0, 1.0)
    if spec.lower() == "black":
        return (0.0, 0.0, 0.0, 1.0)
    return None

def composite(fg_rgba, bg_rgb):
    r, g, b, a = fg_rgba
    return tuple(a * c + (1 - a) * bc for c, bc in zip((r, g, b), bg_rgb))

def split_top(s):
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return [p.strip() for p in out]

def bg_colors(bg_value, tokens, backdrop_rgb):
    """All effective background colors (gradient -> every stop)."""
    if bg_value is None:
        return [backdrop_rgb]
    v = resolve(bg_value, tokens).strip()
    if v in ("none", "transparent"):
        return [backdrop_rgb]
    if v.startswith("color-mix"):
        inner = v[v.index("(") + 1:v.rindex(")")]
        parts = split_top(inner)
        cols = []
        for p in parts[1:]:
            m = re.match(r"(.+?)\s+([\d.]+)%$", p)
            if m:
                cols.append((m.group(1), float(m.group(2)) / 100.0))
            elif p and p != "in srgb":
                cols.append((p, None))
        known = [(c, pct) for c, pct in cols if pct is not None]
        if len(known) == 1 and len(cols) == 2:
            c, pct = known[0]
            rgba = parse_rgb(resolve(c, tokens))
            other = [c2 for c2, p2 in cols if p2 is None][0]
            if other == "transparent":
                return [composite(rgba[:3] + (pct,), backdrop_rgb)]
            orgb = parse_rgb(resolve(other, tokens))
            return [tuple(pct * a + (1 - pct) * b
                          for a, b in zip(rgba[:3], orgb[:3]))]
        return [backdrop_rgb]
    found = re.findall(r"#[0-9a-f]{3,6}\b|rgba?\([^)]*\)", v, flags=re.I)
    out = []
    for f in found:
        rgba = parse_rgb(f)
        if rgba:
            out.append(composite(rgba, backdrop_rgb)
                       if rgba[3] < 1.0 else rgba[:3])
    return out or [backdrop_rgb]

def lum(rgb):
    def f(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (f(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b

def contrast(c1, c2):
    l1, l2 = lum(c1), lum(c2)
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)

def merged(selectors, dark, media_ok=True):
    d = {}
    for sel, decls, is_dark, is_media in RULES:
        if is_dark:
            continue
        if is_media and not media_ok:
            continue
        sels = [s.strip() for s in sel.split(",")]
        if any(w in sels for w in selectors):
            d.update(decls)
    if dark:
        for sel, decls, is_dark, is_media in RULES:
            if not is_dark:
                continue
            if is_media and not media_ok:
                continue
            sels = [s.strip() for s in sel.split(",")]
            if any(w in sels for w in selectors):
                d.update(decls)
    return d

def evaluate(entry, theme):
    (name, selectors, color_override, bg_override,
     backdrop, media_ok) = entry
    tokens = LIGHT if theme == "light" else DARK
    dark = theme == "dark"
    decls = merged(selectors, dark, media_ok)
    bd_spec = backdrop[0] if theme == "light" else backdrop[1]
    bd = parse_rgb(resolve(bd_spec, tokens))
    backdrop_rgb = bd[:3] if bd else (1.0, 1.0, 1.0)
    bgv = bg_override or decls.get("background") \
        or decls.get("background-color")
    bgs = bg_colors(bgv, tokens, backdrop_rgb)
    colv = color_override or decls.get("color")
    if colv is None:
        return None, "no color resolved"
    col_rgba = parse_rgb(resolve(colv, tokens))
    if col_rgba is None:
        return None, "unparseable color " + str(colv)
    bright = 1.0
    filt = decls.get("filter", "")
    m = re.search(r"brightness\(([\d.]+)\)", filt or "")
    if m:
        bright = float(m.group(1))
    worst = None
    for b in bgs:
        fg = composite(col_rgba, b) if col_rgba[3] < 1.0 else col_rgba[:3]
        fg = tuple(min(1.0, c * bright) for c in fg)
        bb = tuple(min(1.0, c * bright) for c in b)
        r = contrast(fg, bb)
        if worst is None or r < worst:
            worst = r
    return worst, ""

CARD = ("var(--card)", "var(--card)")
BG = ("var(--bg)", "var(--bg)")
BRAND = ("var(--brand)", "var(--brand)")
SOFT = ("var(--surface-soft)", "var(--surface-soft)")
CAPSULE = ("#14263f", "#22334e")   # staff .mtab-bar floating capsule

# (name, selectors in cascade order, color override, bg override,
#  (backdrop light, backdrop dark), include media rules)
E = []
def add(name, sels, color=None, bg=None, backdrop=CARD, media=True):
    E.append((name, sels, color, bg, backdrop, media))

# ---------------- buttons ----------------
add(".btn", [".btn"])
add(".btn:hover", [".btn", ".btn:hover"])
add(".btn-primary", [".btn", ".btn-primary"])
add(".btn-primary:hover", [".btn", ".btn-primary", ".btn-primary:hover"])
add(".btn-danger", [".btn", ".btn-danger"])
add(".btn-danger:hover", [".btn", ".btn-danger", ".btn-danger:hover"])
add(".btn-modal-danger", [".btn", ".btn-modal-danger"])
add(".btn-modal-danger:hover", [".btn", ".btn-modal-danger",
                                ".btn-modal-danger:hover"])
add(".btn-link (phone pill)", [".btn", ".btn-link"])
# The reported bug, modelled: an anchor button inside a table. The
# structural checks below prove .table can no longer override it; the
# pairing asserted is therefore .btn-primary's own.
add(".btn-primary in table (Review/Open)",
    [".btn", ".btn-primary"])

# ---------------- badges / pills / chips ----------------
for v in ("active", "pending", "danger", "closed",
          "role-admin", "role-attorney", "role-staff"):
    add(".badge-" + v, [".badge", ".badge-" + v])
for v in ("pending", "approved", "denied"):
    add(".status-" + v, [".status-" + v])
for v in ("connected", "disconnected", "needs_reauth"):
    add(".status-pill " + v, [".status-pill", ".status-" + v])
add(".layout-saved-pill", [".layout-saved-pill"])
add(".layout-saved-pill.err",
    [".layout-saved-pill", ".layout-saved-pill.err"])
add(".chip", [".chip"])
add(".chip:hover", [".chip", ".chip:hover"])
add(".act", [".act"])
add(".act:hover", [".act", ".act:hover"])
add(".w-btn", [".w-btn"], backdrop=BG)
add(".customize-btn", [".customize-btn"])
add(".client-chip", [".client-chip"])
add(".status-select", [".status-select"])
add(".tab-badge", [".tab-badge"])
add(".tlink .bdg", [".tlink .bdg"])
add(".mtab-bdg", [".mtab-bdg"], backdrop=CAPSULE)
add(".msheet-row .bdg", [".msheet-row .bdg"])
add(".avatar", [".avatar"])
add(".tc-member .tc-av", [".tc-member .tc-av"])
add(".monogram", [".monogram"], backdrop=BRAND)
add(".c-av on brand (tc-chip)", [".c-av"], bg="var(--brand)")

# ---------------- nav / tabs / segmented ----------------
add(".topbar nav a", [".topbar nav a"], backdrop=BRAND)
add(".topbar nav a:hover", [".topbar nav a", ".topbar nav a:hover"],
    backdrop=BRAND)
add(".topbar nav a.active", [".topbar nav a", ".topbar nav a.active"],
    backdrop=BRAND)
add(".userbox a", [".userbox a"], backdrop=BRAND)
add(".nav-drop-item:hover",
    [".nav-drop-item", ".nav-drop-item:hover"])
add(".nav-drop-item.active",
    [".nav-drop-item", ".nav-drop-item.active"])
add(".nav-dropdown.active > .nav-drop-btn",
    [".nav-dropdown.active > .nav-drop-btn"])
add(".tlink:hover", [".tlink", ".tlink:hover"])
add(".tlink.active", [".tlink", ".tlink.active"])
add(".user-dropdown a:hover",
    [".user-dropdown a", ".user-dropdown a:hover"])
add(".seg-btn", [".seg-btn"], backdrop=SOFT)
add(".seg-btn.on", [".seg-btn", ".seg-btn.on"], backdrop=SOFT)
add(".view-tab.active", [".view-tab", ".view-tab.active"], backdrop=SOFT)
add(".tabs a (desktop)", [".tabs a"], media=False)
add(".tabs a:hover (desktop)", [".tabs a", ".tabs a:hover"], media=False)
add(".tabs a (phone pill)", [".tabs a"])
add(".tabs a.active (phone pill)", [".tabs a", ".tabs a.active"])
add(".tabs a.active .tab-badge",
    [".tabs a.active .tab-badge"], backdrop=BRAND)
add(".mtab (inactive label)", [".mtab"], backdrop=CAPSULE)
add(".mtab.on (active pill)", [".mtab", ".mtab.on"], backdrop=CAPSULE)
add(".msheet-ric", [".msheet-ric"])
add(".msheet-row.active .msheet-ric",
    [".msheet-row.active .msheet-ric"])
add(".msheet-signout .msheet-ric", [".msheet-signout .msheet-ric"])
add(".msheet-role-pill", [".msheet-role-pill"])

# ---------------- alerts / banners / toast ----------------
for v in ("error", "success", "warning"):
    add(".flash-" + v, [".flash-" + v], backdrop=BG)
for v in ("danger", "success", "warning"):
    add(".alert-" + v, [".alert", ".alert-" + v])
add(".update-banner", [".update-banner"])
add(".footer .lan-warning", [".footer .lan-warning"], backdrop=BG)
add(".notif-toast", [".notif-toast"])
for v in ("info", "danger", "success", "warning"):
    add(".modal-icon-" + v, [".modal-icon-" + v])
add(".integration-icon", [".integration-icon"])

# ---------------- calendar / timeclock / misc staff ----------------
add(".cal-event", [".cal-event"])
add(".cal-event.type-court_date",
    [".cal-event", ".cal-event.type-court_date"])
add(".cal-event.type-filing_deadline",
    [".cal-event", ".cal-event.type-filing_deadline"])
add(".tc-status", [".tc-status"])
add(".tc-status.on", [".tc-status", ".tc-status.on"])
add(".tc-entry .tc-hours", [".tc-entry .tc-hours"])
add(".email-inbound", [".email-inbound"])
add(".email-outbound", [".email-outbound"])
add(".note-del-btn:hover", [".note-del-btn:hover"])
add(".m-action / .row-action (phone)", [".m-action"])

# ---------------- portal ----------------
add(".p-topbar text", [".p-topbar"], backdrop=BRAND)
add(".p-topnav a", [".p-topnav a"], backdrop=BRAND)
add(".p-topnav a:hover", [".p-topnav a", ".p-topnav a:hover"],
    backdrop=BRAND)
add(".p-topnav a.active", [".p-topnav a", ".p-topnav a.active"],
    backdrop=BRAND)
add(".p-theme-btn", [".p-theme-btn"], backdrop=BRAND)
add(".p-status", [".p-status"])
add(".p-status-pending", [".p-status", ".p-status-pending"])
add(".p-status-accepted", [".p-status", ".p-status-accepted"])
add(".p-status-rejected", [".p-status", ".p-status-rejected"])
add(".p-status-submitted", [".p-status", ".p-status-submitted"])
add(".p-bubble (theirs)", [".p-bubble"])
add(".p-bubble (mine)", [".p-bubble", ".p-bubble-row.mine .p-bubble"])
add(".p-bubble-time on mine",
    [".p-bubble-row.mine .p-bubble",
     ".p-bubble-row.mine .p-bubble .p-bubble-time"])
add(".p-bubble-time on theirs", [".p-bubble-time"], backdrop=SOFT)
add(".ptab (inactive)", [".ptab"], backdrop=BRAND)
add(".ptab.on", [".ptab", ".ptab.on"], backdrop=BRAND)
add(".p-confirm-choice checked",
    [".p-confirm-choice:has(input:checked)"])
add(".p-type-card checked", [".p-type-card:has(input:checked)"],
    color="var(--text)")
add(".p-att on theirs bubble", [".p-att"], color="var(--text)",
    backdrop=SOFT)
add(".p-att on mine bubble", [".p-att"], color="#ffffff",
    backdrop=("var(--navy)", "var(--brand)"))

for entry in E:
    for theme in ("light", "dark"):
        r, why = evaluate(entry, theme)
        check("component %s: %s >= 4.5:1" % (theme, entry[0]),
              r is not None and r >= 4.5,
              why or ("got %.2f" % r if r is not None else ""))

# Dashboard team-avatar palette (inline template colors, white initials)
dash = open(os.path.join("templates", "dashboard.html")).read()
m = re.search(r"avatar_colors = \[([^\]]*)\]", dash)
palette = re.findall(r"#[0-9a-f]{6}", m.group(1)) if m else []
check("avatar palette found in dashboard template", len(palette) >= 4,
      str(palette))
for theme, toks in (("light", LIGHT), ("dark", DARK)):
    for hexv in palette:
        r = contrast((1.0, 1.0, 1.0), parse_rgb(hexv)[:3])
        check("component %s: avatar initials on %s >= 4.5:1"
              % (theme, hexv), r >= 4.5, "got %.2f" % r)

# ----------------------------------------------------------------------
# Structural guards — the mechanisms, not just today's numbers
# ----------------------------------------------------------------------
check("structure: table link rule excludes buttons (.table a:not(.btn))",
      bool(re.search(r"\.table a:not\(\.btn\)\s*\{\s*color: var\(--navy\)",
                     CSS)))
check("structure: no unscoped .table a color rule remains",
      not re.search(r"\.table a\s*\{\s*color:", CSS))
check("structure: dark primary hover has its own gradient, no filter",
      bool(re.search(r'html\[data-theme="dark"\] \.btn-primary:hover \{'
                     r"[^}]*background: linear-gradient\([^}]*"
                     r"filter: none", CSS)))
m = re.search(r'html\[data-theme="dark"\] \.status-disconnected '
              r"\{([^}]*)\}", CSS)
check("structure: dark status-disconnected uses --surface-soft",
      bool(m) and "background: var(--surface-soft)" in m.group(1))
check("structure: dark active-tab badge uses the gold pairing",
      bool(re.search(r'html\[data-theme="dark"\] \.tabs a\.active '
                     r"\.tab-badge \{[^}]*background: var\(--gold\)"
                     r"[^}]*color: var\(--navy-dark\)", CSS)))
m = re.search(r"\.modal-icon-info\s*\{([^}]*)\}", CSS)
check("structure: modal info icon uses --info-text",
      bool(m) and "color: var(--info-text)" in m.group(1))
check("structure: tabs hover strengthens text to --navy",
      bool(re.search(r"\.tabs a:hover \{[^}]*color: var\(--navy\)",
                     CSS)))
check("structure: portal topnav hover strengthens text to white",
      bool(re.search(r"\.p-topnav a:hover \{[^}]*color: #fff", CSS)))
check("structure: dark own-bubble timestamp uses solid #dbe4f0",
      bool(re.search(r'html\[data-theme="dark"\] \.p-bubble-row\.mine '
                     r"\.p-bubble \.p-bubble-time \{ color: #dbe4f0; \}",
                     CSS)))
for name, pat in (
        (".btn", r"\.btn \{([^}]*)\}"),
        (".btn-primary", r"\.btn-primary \{([^}]*)\}"),
        (".btn-danger", r"\.btn-danger \{([^}]*)\}"),
        (".btn-modal-danger", r"\.btn-modal-danger \{([^}]*)\}")):
    m = re.search(pat, CSS)
    check("structure: %s declares its label color explicitly" % name,
          bool(m) and "color:" in m.group(1))
# The two reported screens still ship their in-table primary buttons —
# they are the scenario this suite protects.
pr = open(os.path.join("templates", "portal_review.html")).read()
check("scenario: portal review queue still has its Review button",
      'class="btn btn-small btn-primary"' in pr and ">Review</a>" in pr)
pi = open(os.path.join("templates",
                       "portal_messages_inbox.html")).read()
check("scenario: portal inbox still has its Open button",
      'class="btn btn-small btn-primary"' in pi and ">Open</a>" in pi)

print()
if FAILURES:
    print("FAILURES:", FAILURES)
    raise SystemExit(1)
print("ALL V2121 CHECKS PASSED")
'''


def main():
    tmp = tempfile.mkdtemp(prefix="lawfirm-v2121-")
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        root = os.path.dirname(here)
        shutil.copytree(os.path.join(root, "templates"),
                        os.path.join(tmp, "templates"))
        shutil.copytree(os.path.join(root, "static"),
                        os.path.join(tmp, "static"))
        testfile = os.path.join(tmp, "run_v2121_checks.py")
        with open(testfile, "w") as fh:
            fh.write(textwrap.dedent(TEST_CODE))
        proc = subprocess.run([sys.executable, testfile], cwd=tmp,
                              capture_output=True, text=True,
                              timeout=300)
        sys.stdout.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        return proc.returncode
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
