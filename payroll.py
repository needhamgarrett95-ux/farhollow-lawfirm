"""
Payroll calculation engine for the law firm app.

Washington State has NO state income tax, which simplifies things. Required
withholdings per paycheck:

  Employee-paid (deducted from gross):
    - Federal income tax (IRS percentage method, Pub 15-T style)
    - Social Security 6.2% up to the annual wage base
    - Medicare 1.45% (+ 0.9% additional over $200k)
    - WA Paid Family & Medical Leave (PFML) — employee share
    - WA Cares (long-term care) — employee-paid

  Employer-paid (tracked as employer cost, NOT deducted from paycheck):
    - Social Security 6.2% / Medicare 1.45% (employer match)
    - WA unemployment insurance (SUI / ESD)
    - WA workers' comp (L&I)

Overtime: WA law requires 1.5x for hours over 40 per week (hourly staff).
Salaried staff are treated as exempt (no overtime) — the owner should confirm
exempt status with a CPA.

All rates come from the tax_rates table and are configurable via Tax Settings.
The DEFAULT_TAX_RATES in app.py are ESTIMATES. The owner MUST verify them
against current IRS / WA ESD / WA L&I publications before running payroll.
"""

from decimal import Decimal, ROUND_HALF_UP

PAY_PERIODS_PER_YEAR = {
    "weekly": 52,
    "biweekly": 26,
    "semimonthly": 24,
    "monthly": 12,
}


def _r(value):
    """Round a money amount to cents with ROUND_HALF_UP.

    Python's built-in round() rounds exact half-cents to even, which
    systematically under-withholds (e.g. $73.625 -> $73.62). Money
    must round half-up.
    """
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def get_rate(db, key, default):
    """Read a numeric tax rate from the tax_rates table."""
    row = db.execute("SELECT value FROM tax_rates WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    try:
        return float(row["value"])
    except (ValueError, TypeError):
        return default


def parse_brackets(s):
    """Parse 'upper:rate,upper:rate' into [(upper, rate_pct), ...]."""
    out = []
    for part in (s or "").split(","):
        part = part.strip()
        if ":" not in part:
            continue
        upper, rate = part.split(":", 1)
        try:
            out.append((float(upper), float(rate)))
        except ValueError:
            continue
    return sorted(out)


def federal_withholding_per_period(annual_taxable, filing_status, db):
    """
    IRS percentage-method withholding. annual_taxable = annualized gross
    minus the standard deduction. Returns the withholding for ONE pay period.
    """
    key = "fed_brackets_married" if filing_status == "married" else "fed_brackets_single"
    default_brackets = (
        "24550:10,99800:12,212900:22,406500:24,516100:32,99999999:37"
        if filing_status == "married"
        else "12275:10,49900:12,106450:22,203250:24,258050:32,645250:35,99999999:37"
    )
    row = db.execute("SELECT value FROM tax_rates WHERE key = ?", (key,)).fetchone()
    brackets = parse_brackets(row["value"] if row else default_brackets)

    if annual_taxable <= 0:
        return 0.0

    tax = 0.0
    lower = 0.0
    for upper, rate in brackets:
        if annual_taxable <= lower:
            break
        taxable_at_bracket = min(annual_taxable, upper) - lower
        tax += taxable_at_bracket * (rate / 100.0)
        lower = upper
    # annual_taxable is per year; caller divides by periods per year
    return tax


def calculate_paycheck(db, employee, reg_hours, ot_hours, li_hours=None):
    """
    Calculate one paycheck. employee is a dict-like row from the employees
    table. reg_hours/ot_hours are floats for the pay period.

    li_hours: hours WA workers' comp (L&I) is charged on. Defaults to
    reg_hours + ot_hours (correct for hourly). For salaried employees the
    caller passes their actual timeclock hours (or standard full-time
    hours) since reg/ot are zeroed for exempt staff.

    Returns a dict with all line items in DOLLARS (floats); the route
    converts to integer cents for storage.
    """
    periods = PAY_PERIODS_PER_YEAR.get(employee["pay_frequency"], 26)
    if li_hours is None:
        li_hours = reg_hours + ot_hours

    if employee["pay_type"] == "salary":
        # pay_rate_cents holds ANNUAL salary in cents
        annual_salary = employee["pay_rate_cents"] / 100.0
        gross = annual_salary / periods
        reg_hours = 0.0
        ot_hours = 0.0
    else:
        hourly = employee["pay_rate_cents"] / 100.0
        gross = reg_hours * hourly + ot_hours * hourly * 1.5

    gross = _r(gross)

    # --- Federal income tax (percentage method on annualized wages) ---
    std_key = "fed_std_ded_married" if employee["filing_status"] == "married" else "fed_std_ded_single"
    std_ded = get_rate(db, std_key, 31500 if employee["filing_status"] == "married" else 15750)
    # Allowances reduce taxable wages (simplified: $4,300 per allowance, 2025 figure)
    allowance_amt = (employee["allowances"] or 0) * 4300
    annual_taxable = gross * periods - std_ded - allowance_amt
    annual_fed = federal_withholding_per_period(max(annual_taxable, 0), employee["filing_status"], db)
    federal = _r(annual_fed / periods)

    # --- FICA ---
    ss_rate = get_rate(db, "ss_rate", 6.2) / 100.0
    ss_base = get_rate(db, "ss_wage_base", 184500)
    ytd = db.execute(
        "SELECT COALESCE(SUM(gross_cents), 0) AS g FROM paychecks WHERE employee_id = ?",
        (employee["id"],),
    ).fetchone()["g"] / 100.0
    ss_taxable = max(0.0, min(gross, ss_base - ytd))
    ss = _r(ss_taxable * ss_rate)

    med_rate = get_rate(db, "medicare_rate", 1.45) / 100.0
    med_addl = get_rate(db, "medicare_addl_rate", 0.9) / 100.0
    medicare = _r(gross * med_rate)
    if ytd + gross > 200000:
        addl_taxable = min(gross, ytd + gross - 200000)
        medicare = _r(medicare + addl_taxable * med_addl)

    # --- WA PFML (employee share) ---
    pfml_total = get_rate(db, "pfml_total_rate", 0.92) / 100.0
    pfml_emp_share = get_rate(db, "pfml_employee_share", 71.43) / 100.0
    pfml = _r(gross * pfml_total * pfml_emp_share)

    # --- WA Cares ---
    wacares = _r(gross * get_rate(db, "wacares_rate", 0.58) / 100.0)

    total_deductions = _r(federal + ss + medicare + pfml + wacares)
    net = _r(gross - total_deductions)

    # --- Employer costs (not deducted) ---
    ss_er = _r(ss_taxable * get_rate(db, "ss_rate_employer", 6.2) / 100.0)
    med_er = _r(gross * get_rate(db, "medicare_rate_employer", 1.45) / 100.0)
    sui_rate = get_rate(db, "sui_rate", 1.5) / 100.0
    sui_base = get_rate(db, "sui_wage_base", 74000)
    sui_taxable = max(0.0, min(gross, sui_base - ytd))
    sui = _r(sui_taxable * sui_rate)
    li_per_hour = get_rate(db, "li_rate_per_hour", 0.25)
    li_cost = _r(li_hours * li_per_hour)
    # WA PFML employer share (only when the firm pays it — 50+ employees)
    pfml_er = 0.0
    if get_rate(db, "pfml_employer_pays", 0) == 1:
        pfml_er = _r(gross * pfml_total * (1.0 - pfml_emp_share))

    return {
        "reg_hours": _r(reg_hours),
        "ot_hours": _r(ot_hours),
        "gross": gross,
        "federal": federal,
        "ss": ss,
        "medicare": medicare,
        "pfml": pfml,
        "wacares": wacares,
        "total_deductions": total_deductions,
        "net": net,
        "employer_ss": ss_er,
        "employer_medicare": med_er,
        "employer_sui": sui,
        "employer_li": li_cost,
        "employer_pfml": pfml_er,
        "employer_total": _r(ss_er + med_er + sui + li_cost + pfml_er),
    }


def weekly_hours(entries):
    """
    Group timeclock entries by ISO week and compute regular vs overtime
    hours per week. entries: list of dicts with entry_date (YYYY-MM-DD)
    and hours (float). Returns (total_reg, total_ot).
    """
    from datetime import date

    by_week = {}
    for e in entries:
        d = date.fromisoformat(e["entry_date"])
        iso_year, iso_week, _ = d.isocalendar()
        key = (iso_year, iso_week)
        by_week[key] = by_week.get(key, 0.0) + float(e["hours"] or 0)

    reg = 0.0
    ot = 0.0
    for hours in by_week.values():
        if hours > 40:
            reg += 40.0
            ot += hours - 40.0
        else:
            reg += hours
    return round(reg, 2), round(ot, 2)


def entry_hours(entry):
    """Hours for a single timeclock entry (clock in/out or manual).

    Rows are a mix of timezone-aware UTC (live clock-ins) and naive
    wall-clock (correction-approved rows). Both parse as UTC so mixed
    rows can never raise on subtraction (used to 500 payroll previews).
    Negative spans are clamped to 0.
    """
    from datetime import datetime, timezone

    if entry["manual_hours"] is not None:
        return float(entry["manual_hours"])
    if not entry["clock_out"]:
        return 0.0

    def _norm(value):
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    start = _norm(entry["clock_in"])
    end = _norm(entry["clock_out"])
    hours = (end - start).total_seconds() / 3600.0
    return round(max(0.0, hours), 2)
