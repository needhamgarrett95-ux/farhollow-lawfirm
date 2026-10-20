#!/usr/bin/env python3
"""Static audit for v2.5.1 (mobile sheet motion + bottom-bar sizing),
extended in v2.5.2 with the filled mobile nav icons (section 7).

Run with the app's Python env: /tmp/lawfirm-test-venv/bin/python tests/test_v251.py

Garrett's v2.5.0 feedback was a FEEL bug: the bottom sheet opened too
snappy/clunky ("ripped out of your hand") and its rows ghosted while it
moved; the bottom-bar buttons were too small to hit. Browser rendering
can't be exercised from here, so this suite audits the shipped CSS/JS
for the properties that produce the fix:

  1. Every transition that moves the sheet (transform) or fades its
     scrim lasts >= 250ms — outside of the prefers-reduced-motion
     blocks, and except the deliberate `transition: none` that applies
     only while a drag is in progress (selector mentions .dragging).
  2. A real drag handler exists: pointer events with pointer capture,
     a .dragging state that kills the transition, and NO scrollIntoView
     anywhere (the v2.5.0 programmatic anchor scroll that raced the
     open animation is gone).
  3. The sheet background is effectively opaque: the winning .msheet
     background declaration is a solid theme variable (or an rgba with
     alpha >= 0.98), and the sheet uses no backdrop-filter.
  4. The inner scroll box is momentum-scrolling + overscroll-contained
     so the page behind never scrolls or shows through.
  5. Tap targets: the floating bar is >= 66px tall and a 999px capsule;
     sheet rows are >= 56px; bar tabs and sheet rows carry
     touch-action: manipulation.
  6. Markup: two distinct sheets exist (full menu + Practice-only),
     each with a grab zone.

Pure file audit — no server, no DB.
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSS = open(os.path.join(REPO, "static", "style.css")).read()
HTML = open(os.path.join(REPO, "templates", "base.html")).read()
ICONS = open(os.path.join(REPO, "templates", "_icons.html")).read()
APP = open(os.path.join(REPO, "app.py")).read()

FAILURES = []


def check(name, cond, extra=""):
    if cond:
        print(f"  PASS {name}")
    else:
        print(f"  FAIL {name} {extra}")
        FAILURES.append(name)


def parse_rules(css):
    """Yield (selector, body, media_context) for every style rule."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    rules = []

    def walk(text, context):
        i = 0
        while i < len(text):
            j = text.find("{", i)
            if j == -1:
                break
            header = text[i:j].strip()
            depth, k = 1, j + 1
            while k < len(text) and depth:
                if text[k] == "{":
                    depth += 1
                elif text[k] == "}":
                    depth -= 1
                k += 1
            body = text[j + 1:k - 1]
            if header.startswith("@media"):
                walk(body, context + [header])
            elif not header.startswith("@"):
                rules.append((header, body, context))
            i = k

    walk(css, [])
    return rules


RULES = parse_rules(CSS)
# Motion rules the user actually feels (reduced-motion blocks excluded:
# transition:none there is an accessibility setting, not the design).
LIVE = [(s, b) for (s, b, ctx) in RULES
        if not any("prefers-reduced-motion" in c for c in ctx)]

STANDALONE_MSHEET = re.compile(r"\.msheet(?![\w-])")


def declarations(body):
    out = {}
    for part in body.split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def durations(value):
    """All time values in a transition shorthand, in seconds."""
    return [float(n) / (1000.0 if u == "ms" else 1.0)
            for n, u in re.findall(r"(\d*\.?\d+)(ms|s)\b", value)]


def main():
    # === 1. Sheet/sc sheet motion is never snappy =======================
    saw_sheet_transition = False
    for sel, body in LIVE:
        decls = declarations(body)
        if "transition" not in decls:
            continue
        is_sheet = bool(STANDALONE_MSHEET.search(sel))
        is_scrim = ".msheet-scrim" in sel
        if not (is_sheet or is_scrim):
            continue
        val = decls["transition"]
        if val == "none":
            check(f"transition:none only while dragging ({sel})",
                  "dragging" in sel)
            continue
        saw_sheet_transition = True
        durs = durations(val)
        check(f"sheet transition >= 250ms ({sel}: {val})",
              bool(durs) and all(d >= 0.25 for d in durs[::2] or durs),
              f"durations={durs}")
    check("a sheet transform transition exists", saw_sheet_transition)

    # Winning (last live) .msheet transition is the ~320ms ease
    sheet_vals = [declarations(b)["transition"] for s, b in LIVE
                  if STANDALONE_MSHEET.search(s)
                  and "transition" in declarations(b)
                  and declarations(b)["transition"] != "none"]
    if sheet_vals:
        last = sheet_vals[-1]
        durs = durations(last)
        check("winning sheet transition is ~320ms cubic-bezier ease",
              bool(durs) and 0.30 <= durs[0] <= 0.34
              and "cubic-bezier(.32" in last.replace(" ", ""),
              f"got: {last}")

    # === 2. Drag handler, no racing anchor scroll ========================
    check("JS: pointerdown drag handler present", "pointerdown" in HTML)
    check("JS: pointer capture used", "setPointerCapture" in HTML)
    check("JS: .dragging state toggled",
          "classList.add('dragging')" in HTML
          and "classList.remove('dragging')" in HTML)
    check("JS: sheet follows finger via inline translateY",
          "style.transform = 'translateY('" in HTML)
    check("JS: dismiss threshold ~35% of sheet height",
          "offsetHeight * 0.35" in HTML)
    check("JS: NO scrollIntoView (anchor-scroll race removed)",
          "scrollIntoView" not in HTML)
    drag_rules = [(s, b) for s, b in LIVE
                  if "dragging" in s and STANDALONE_MSHEET.search(s)]
    check("CSS: .dragging kills the sheet transition",
          any(declarations(b).get("transition") == "none"
              for s, b in drag_rules))
    # Wrap stays visible until the close animation finishes
    wrap_rules = [declarations(b) for s, b in LIVE if s == ".msheet-wrap"]
    check("CSS: wrap visibility delayed until close animation ends",
          any("visibility" in d.get("transition", "") for d in wrap_rules))

    # === 3. Sheet is effectively opaque ==================================
    bgs = [declarations(b)["background"] for s, b in LIVE
           if s == ".msheet" and "background" in declarations(b)]
    check(".msheet background declarations found", bool(bgs))
    if bgs:
        win = bgs[-1]
        opaque = win in ("var(--bg)", "var(--card)")
        m = re.match(r"rgba?\(([^)]*)\)", win)
        if m:
            parts = [p.strip() for p in m.group(1).split(",")]
            opaque = len(parts) == 3 or float(parts[3]) >= 0.98
        if win.startswith("#"):
            opaque = True
        check(f"winning .msheet background is opaque ({win})", opaque)
    sheet_all = " ".join(b for s, b in LIVE if s == ".msheet")
    check(".msheet uses no backdrop-filter", "backdrop-filter" not in sheet_all)

    # === 4. Scroll containment ===========================================
    scroll_rules = [declarations(b) for s, b in LIVE if s == ".msheet-scroll"]
    check(".msheet-scroll: momentum scrolling on",
          any(d.get("-webkit-overflow-scrolling") == "touch"
              for d in scroll_rules))
    check(".msheet-scroll: overscroll contained",
          any(d.get("overscroll-behavior") == "contain" for d in scroll_rules))

    # === 5. Tap targets ====================================================
    bar_rules = [declarations(b) for s, b in LIVE if s == ".mtab-bar"]
    heights = [d["height"] for d in bar_rules if "height" in d]
    check(".mtab-bar height declared", bool(heights))
    if heights:
        h = heights[-1]
        check(f".mtab-bar is >= 66px tall ({h})",
              h.endswith("px") and float(h[:-2]) >= 66)
    check(".mtab-bar is a floating capsule (border-radius 999px)",
          any(d.get("border-radius") == "999px" for d in bar_rules))
    check(".mtab-bar floats with side margins",
          any(d.get("left") == "14px" and d.get("right") == "14px"
              for d in bar_rules))
    check(".mtab has touch-action: manipulation",
          any(d.get("touch-action") == "manipulation"
              for s, b in LIVE if s == ".mtab"
              for d in [declarations(b)]))
    row_rules = [declarations(b) for s, b in LIVE if s == ".msheet-row"]
    row_heights = [d["min-height"] for d in row_rules if "min-height" in d]
    check(".msheet-row min-height declared", bool(row_heights))
    if row_heights:
        h = row_heights[-1]
        check(f".msheet-row is >= 56px tall ({h})",
              h.endswith("px") and float(h[:-2]) >= 56)
    check(".msheet-row has touch-action: manipulation",
          any(d.get("touch-action") == "manipulation" for d in row_rules))
    check("grab zone owns its touches (touch-action: none)",
          any(d.get("touch-action") == "none"
              for s, b in LIVE if s == ".msheet-grabzone"
              for d in [declarations(b)]))

    # === 6. Two distinct sheets ============================================
    check("markup: full sheet present", 'id="msheetWrap"' in HTML)
    check("markup: Practice-only sheet present",
          'id="msheetPracticeWrap"' in HTML)
    check("markup: Practice tab opens the practice sheet",
          'data-msheet-open="practice"' in HTML)
    check("markup: More tab opens the full sheet",
          'data-msheet-open="all"' in HTML)
    check("markup: grab zones present (both sheets)",
          HTML.count('class="msheet-grabzone"') == 2)

    # === 7. Filled nav icons (v2.5.2) =======================================
    # The mobile bar + sheets use SOLID glyphs from a separate macro,
    # icon_filled, in _icons.html. The desktop nav must keep the stroke
    # set untouched — the filled macro is new names, not a replacement.
    mstart = ICONS.index("macro icon_filled")
    mend = ICONS.index("endmacro", mstart)
    filled_macro = ICONS[mstart:mend]
    check("icon_filled svg is solid (fill=currentColor, stroke=none)",
          'fill="currentColor"' in filled_macro
          and 'stroke="none"' in filled_macro
          and "icon-filled" in filled_macro)
    check("original stroke macro is untouched",
          'fill="none" stroke="currentColor"' in ICONS)

    # Every icon the nav can reference has a filled variant: all
    # NAV_GROUPS item/group icons from app.py, plus the names base.html
    # hardcodes into the mobile markup.
    nav_block = APP[APP.index("NAV_GROUPS"):APP.index("NAV_ITEMS")]
    nav_icons = sorted(set(re.findall(r'"icon":\s*"([a-z-]+)"', nav_block)))
    hardcoded = ["alarm", "billing", "grip", "password", "logout",
                 "chevron-right"]
    for name in sorted(set(nav_icons) | set(hardcoded)):
        check(f"filled variant exists: {name}",
              f"name == '{name}'" in filled_macro)

    # Template wiring: everything from the first sheet onward is the
    # mobile block; the desktop header above it must not call the
    # filled macro at all.
    midx = HTML.index('id="msheetWrap"')
    desktop_src, mobile_src = HTML[:midx], HTML[midx:]
    check("desktop markup calls no filled icons",
          "icon_filled(" not in desktop_src)
    check("both sheets render row icons filled",
          mobile_src.count("icon_filled(item.icon, 20)") == 2)
    check("bar icons are filled (alarm/grip/billing at 25px)",
          all(f"icon_filled('{n}', 25)" in mobile_src
              for n in ("alarm", "grip", "billing")))
    check("account rows use filled icons (password/logout)",
          "icon_filled('password', 20)" in mobile_src
          and "icon_filled('logout', 20)" in mobile_src)
    check("no stroke icon() calls left in the mobile block",
          re.search(r"(?<![\w])icon\(", mobile_src) is None)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURES: {FAILURES}")
        sys.exit(1)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
