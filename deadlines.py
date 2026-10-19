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
