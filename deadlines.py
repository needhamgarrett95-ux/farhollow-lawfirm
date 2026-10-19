"""Court deadline calculator — Washington Superior Court, family law.

Rules are data-driven in DEADLINE_RULES so they can be added or adjusted
without touching the calculation engine.

IMPORTANT: These are standard WA Superior Court rules (CR 6 and common
family-law practice). Always verify against current court rules and any
case-specific orders. This tool does not replace legal judgment.
"""

import calendar as _calendar
from datetime import date, timedelta

# ----------------------------------------------------------------------------
# Washington state holidays (courts closed)
# ----------------------------------------------------------------------------


def _nth_weekday(year, month, weekday, n):
    """Return the nth (1-5) or last (-1) `weekday` (Mon=0..Sun=6) of a month."""
    if n > 0:
        d = date(year, month, 1)
        offset = (weekday - d.weekday()) % 7
        return d + timedelta(days=offset + 7 * (n - 1))
    last_day = _calendar.monthrange(year, month)[1]
    d = date(year, month, last_day)
    offset = (d.weekday() - weekday) % 7
    return d - timedelta(days=offset)


def _observed(d):
    """If a holiday falls on a weekend, courts observe Fri (Sat) or Mon (Sun)."""
    if d.weekday() == 5:  # Saturday -> observed Friday before
        return d - timedelta(days=1)
    if d.weekday() == 6:  # Sunday -> observed Monday after
        return d + timedelta(days=1)
    return d


_holiday_cache = {}


def wa_holidays(year):
    """Set of dates WA courts are closed in `year` (actual + observed)."""
    if year in _holiday_cache:
        return _holiday_cache[year]
    fixed = [
        date(year, 1, 1),    # New Year's Day
        date(year, 6, 19),   # Juneteenth
        date(year, 7, 4),    # Independence Day
        date(year, 11, 11),  # Veterans Day
        date(year, 12, 25),  # Christmas Day
    ]
    floating = [
        _nth_weekday(year, 1, 0, 3),    # MLK Day — 3rd Monday Jan
        _nth_weekday(year, 2, 0, 3),    # Presidents' Day — 3rd Monday Feb
        _nth_weekday(year, 5, 0, -1),   # Memorial Day — last Monday May
        _nth_weekday(year, 9, 0, 1),    # Labor Day — 1st Monday Sep
        _nth_weekday(year, 11, 3, 4),   # Thanksgiving — 4th Thursday Nov
    ]
    days = set()
    for d in fixed + floating:
        days.add(d)
        obs = _observed(d)
        if obs != d:
            days.add(obs)
    # Day after Thanksgiving (courts closed)
    thanksgiving = _nth_weekday(year, 11, 3, 4)
    days.add(thanksgiving + timedelta(days=1))
    _holiday_cache[year] = days
    return days


def is_court_day(d):
    """A court day is Mon-Fri that is not a WA court holiday."""
    return d.weekday() < 5 and d not in wa_holidays(d.year)


def add_court_days(d, n):
    """Add n court days to d (trigger day excluded, per CR 6(a))."""
    result = d
    while n > 0:
        result += timedelta(days=1)
        if is_court_day(result):
            n -= 1
    return result


def subtract_court_days(d, n):
    """Go back n court days from d (trigger day excluded, per CR 6(a))."""
    result = d
    while n > 0:
        result -= timedelta(days=1)
        if is_court_day(result):
            n -= 1
    return result


# ----------------------------------------------------------------------------
# Data-driven deadline rules
#
# Each rule set: trigger type -> list of deadlines.
#   days:      number of days
#   unit:      "court" (excludes weekends + WA holidays) or "calendar"
#   direction: "before" (deadline precedes trigger) or "after"
#   basis:     rule citation shown to the user
# ----------------------------------------------------------------------------

DEADLINE_RULES = {
    "hearing": {
        "label": "Motion Hearing",
        "description": (
            "Filing deadlines under CR 6 for a motion hearing. "
            "A response to a motion follows these same deadlines."
        ),
        "deadlines": [
            {
                "key": "motion_docs",
                "label": "Motion + supporting documents due",
                "days": 9,
                "unit": "court",
                "direction": "before",
                "basis": "CR 6 — 9 court days before hearing",
            },
            {
                "key": "responsive_docs",
                "label": "Responsive documents due",
                "days": 4,
                "unit": "court",
                "direction": "before",
                "basis": "CR 6 — 4 court days before hearing",
            },
            {
                "key": "reply_docs",
                "label": "Reply documents due",
                "days": 2,
                "unit": "court",
                "direction": "before",
                "basis": "CR 6 — 2 court days before hearing",
            },
        ],
    },
    "trial": {
        "label": "Trial",
        "description": "Common pre-trial deadlines. Confirm against the trial scheduling order.",
        "deadlines": [
            {
                "key": "trial_briefs",
                "label": "Trial briefs due",
                "days": 7,
                "unit": "calendar",
                "direction": "before",
                "basis": "7 calendar days before trial",
            },
            {
                "key": "witness_exhibit",
                "label": "Witness & exhibit lists due",
                "days": 14,
                "unit": "calendar",
                "direction": "before",
                "basis": "14 calendar days before trial",
            },
            {
                "key": "discovery_cutoff",
                "label": "Discovery cutoff",
                "days": 30,
                "unit": "calendar",
                "direction": "before",
                "basis": "30 calendar days before trial",
            },
        ],
    },
    "service_in_state": {
        "label": "Service of Petition (in-state)",
        "description": "Response deadline after in-state personal service.",
        "deadlines": [
            {
                "key": "response",
                "label": "Response to petition due",
                "days": 20,
                "unit": "calendar",
                "direction": "after",
                "basis": "20 calendar days after service",
            },
        ],
    },
    "service_out_of_state": {
        "label": "Service of Petition (out of state)",
        "description": "Response deadline after out-of-state service.",
        "deadlines": [
            {
                "key": "response",
                "label": "Response to petition due",
                "days": 60,
                "unit": "calendar",
                "direction": "after",
                "basis": "60 calendar days after service",
            },
        ],
    },
}

# ----------------------------------------------------------------------------
# Clallam County Superior Court overlay
#
# Research (clallam-research.md, 2026-10-19): Clallam does not modify the
# state CR 6 briefing timelines, but adds procedural requirements and holds
# family law motions on specific calendar days:
#   - Family law motions: Fridays at 9:00 AM
#   - Child support: 1st & 3rd Tuesdays at 9:00 AM
#   - Ex parte (civil): Mon-Fri at 1:00 PM, 11:00 AM filing cutoff same day
#   - LCR 2(c): response to motion for revision of commissioner's ruling,
#     10 days after service
# The attorney must verify all of this against current local rules.
# ----------------------------------------------------------------------------

CLALLAM_MOTION_WEEKDAY = 4  # Friday (Mon=0)
CLALLAM_JUDGE_CALENDAR_URL = (
    "https://www.clallamcountywa.gov/DocumentCenter/View/17465/"
    "Friday-Superior-Court-Judges-Calendar-PDF?bidId="
)
CLALLAM_CALENDARS_URL = "https://www.clallamcountywa.gov/1520/Calendars"


def _nth_tuesday_of_month(d):
    """Return which Tuesday of the month `d` is (1-5), or 0 if not a Tuesday."""
    if d.weekday() != 1:  # Tuesday
        return 0
    return (d.day - 1) // 7 + 1


def is_clallam_child_support_tuesday(d):
    """Child support calendar: 1st & 3rd Tuesdays at 9:00 AM."""
    return _nth_tuesday_of_month(d) in (1, 3)


def clallam_warnings(trigger_type, trigger_date):
    """Return a list of Clallam-specific warnings for a trigger date.

    Empty list means the date passes Clallam calendar validation.
    """
    warnings = []
    day_name = trigger_date.strftime("%A")
    if trigger_type == "clallam_motion":
        if trigger_date.weekday() != CLALLAM_MOTION_WEEKDAY:
            warnings.append(
                "Clallam County family law motions are heard Fridays at 9:00 AM. "
                f"{trigger_date.strftime('%B %d, %Y')} is a {day_name}."
            )
    elif trigger_type == "clallam_child_support":
        if not is_clallam_child_support_tuesday(trigger_date):
            warnings.append(
                "Clallam County child support matters are heard the 1st and 3rd "
                f"Tuesdays at 9:00 AM. {trigger_date.strftime('%B %d, %Y')} is a "
                f"{day_name} and is not a child-support Tuesday."
            )
    elif trigger_type == "clallam_ex_parte":
        if not is_court_day(trigger_date):
            warnings.append(
                "Clallam County ex parte is heard Monday–Friday at 1:00 PM. "
                f"{trigger_date.strftime('%B %d, %Y')} is not a court day."
            )
    return warnings


CLALLAM_RULES = {
    "clallam_motion": {
        "label": "Clallam Co. Motion Hearing (Friday 9:00 AM)",
        "description": (
            "State CR 6 briefing deadlines plus Clallam County procedural "
            "requirements: bench copies by NOON the day before, and telephone "
            "confirmation of the motion calendar. Family law motions are heard "
            "Fridays at 9:00 AM."
        ),
        "deadlines": [
            {
                "key": "motion_docs",
                "label": "Motion + supporting documents due",
                "days": 9,
                "unit": "court",
                "direction": "before",
                "basis": "CR 6 — 9 court days before hearing",
            },
            {
                "key": "responsive_docs",
                "label": "Responsive documents due",
                "days": 4,
                "unit": "court",
                "direction": "before",
                "basis": "CR 6 — 4 court days before hearing",
            },
            {
                "key": "reply_docs",
                "label": "Reply documents due",
                "days": 2,
                "unit": "court",
                "direction": "before",
                "basis": "CR 6 — 2 court days before hearing",
            },
            {
                "key": "bench_copies",
                "label": "Bench copies due (by NOON)",
                "days": 1,
                "unit": "court",
                "direction": "before",
                "basis": "Clallam Co. — bench copies by noon the day before hearing",
            },
            {
                "key": "phone_confirm",
                "label": "Telephone confirmation of motion calendar",
                "days": 1,
                "unit": "court",
                "direction": "before",
                "basis": "Clallam Co. — phone confirmation required for motion calendar",
            },
        ],
    },
    "clallam_child_support": {
        "label": "Clallam Co. Child Support (1st/3rd Tue 9:00 AM)",
        "description": (
            "State CR 6 briefing deadlines for child support matters, heard "
            "the 1st and 3rd Tuesdays of each month at 9:00 AM, plus Clallam "
            "procedural requirements."
        ),
        "deadlines": [
            {
                "key": "motion_docs",
                "label": "Motion + supporting documents due",
                "days": 9,
                "unit": "court",
                "direction": "before",
                "basis": "CR 6 — 9 court days before hearing",
            },
            {
                "key": "responsive_docs",
                "label": "Responsive documents due",
                "days": 4,
                "unit": "court",
                "direction": "before",
                "basis": "CR 6 — 4 court days before hearing",
            },
            {
                "key": "reply_docs",
                "label": "Reply documents due",
                "days": 2,
                "unit": "court",
                "direction": "before",
                "basis": "CR 6 — 2 court days before hearing",
            },
            {
                "key": "bench_copies",
                "label": "Bench copies due (by NOON)",
                "days": 1,
                "unit": "court",
                "direction": "before",
                "basis": "Clallam Co. — bench copies by noon the day before hearing",
            },
            {
                "key": "phone_confirm",
                "label": "Telephone confirmation of motion calendar",
                "days": 1,
                "unit": "court",
                "direction": "before",
                "basis": "Clallam Co. — phone confirmation required for motion calendar",
            },
        ],
    },
    "clallam_ex_parte": {
        "label": "Clallam Co. Ex Parte (daily 1:00 PM)",
        "description": (
            "Ex parte matters are heard Monday–Friday at 1:00 PM. Filings must "
            "be submitted by 11:00 AM the same day."
        ),
        "deadlines": [
            {
                "key": "ex_parte_filing",
                "label": "Ex parte filing cutoff (11:00 AM, day of hearing)",
                "days": 0,
                "unit": "court",
                "direction": "before",
                "basis": "Clallam Co. — ex parte filings due by 11:00 AM day of the 1:00 PM calendar",
            },
        ],
    },
    "lcr2_revision": {
        "label": "LCR 2 — Response to Motion for Revision",
        "description": (
            "Response to a motion for revision of a court commissioner's "
            "ruling, per Clallam County LCR 2(c)."
        ),
        "deadlines": [
            {
                "key": "revision_response",
                "label": "Response to motion for revision due",
                "days": 10,
                "unit": "calendar",
                "direction": "after",
                "basis": "Clallam Co. LCR 2(c) — 10 days after service",
            },
        ],
    },
}

# Merge the Clallam overlay into the main rule table so the calculator,
# push-to-calendar, and trigger dropdown all pick them up.
DEADLINE_RULES.update(CLALLAM_RULES)

TRIGGER_CHOICES = [(k, v["label"]) for k, v in DEADLINE_RULES.items()]

DISCLAIMER = (
    "Deadline calculations are based on standard WA Superior Court rules. "
    "Always verify against current court rules and any case-specific orders "
    "— this tool does not replace legal judgment."
)


def calculate_deadlines(trigger_type, trigger_date):
    """Return a list of dicts: key, label, due (date), unit, basis, days_remaining."""
    rules = DEADLINE_RULES.get(trigger_type)
    if rules is None:
        raise ValueError(f"Unknown trigger type: {trigger_type!r}")
    today = date.today()
    results = []
    for rule in rules["deadlines"]:
        if rule["unit"] == "court":
            if rule["direction"] == "before":
                due = subtract_court_days(trigger_date, rule["days"])
            else:
                due = add_court_days(trigger_date, rule["days"])
        else:
            if rule["direction"] == "before":
                due = trigger_date - timedelta(days=rule["days"])
            else:
                due = trigger_date + timedelta(days=rule["days"])
        results.append(
            {
                "key": rule["key"],
                "label": rule["label"],
                "due": due,
                "unit": rule["unit"],
                "basis": rule["basis"],
                "days_remaining": (due - today).days,
            }
        )
    # Earliest deadline first
    results.sort(key=lambda r: r["due"])
    return results
