# Clallam County Superior Court — Research for Deadline Calculator Integration

Researched 2026-10-19. This is factual research only; the attorney must verify
all deadlines against current court rules before relying on them in practice.

## 1. Motion Calendar Schedule

### Family Law / Domestic (the firm's practice area)
- **Family law motions: Fridays at 9:00 AM** (Courtroom 1, generally)
- **Adoptions: Fridays at 8:30 AM**
- **Domestic violence hearings: Fridays at 1:30 PM**
- **Child support matters: 1st and 3rd Tuesday of each month at 9:00 AM**
- **Non-family protection orders: Tuesdays at 9:30 AM**
- **Ex parte (civil): Monday–Friday at 1:00 PM**, with an **11:00 AM filing deadline** same day
- **Trial settings: Friday mornings at 8:45 AM**

### Judge Rotation
Friday civil/criminal motion calendars **rotate between three judges**:
- Judge Brent Basden (Chief Judge through Jan 2026)
- Judge Simon Barnhart (Chief Judge starting Jan 2026, 2-year term)
- Judge Elizabeth Stanley (elevated from Family Court Commissioner, Jan 2025)

The rotation is published in the **Friday Judge Bench Assignments** document
(see §4 below). Changes are marked with `*` and a date.

### Family Court Commissioner — IMPORTANT 2026 DEVELOPMENT
- Commissioner Brian Parker was **terminated February 10, 2026**.
- Until a new commissioner is appointed (estimated 1–3 months), **Superior
  Court judges rotate through Family Court matters**.
- Per the Clallam County Bar: **"Changes to the Family Court schedule are not
  expected."** — but the attorney should confirm this holds true.

### Settlement Conferences
- Handled by the Family Court Commissioner (or judge/pro tem).
- **2.5 hours** per conference (bar association recommends thorough preparation;
  1.5 hours was deemed too short).
- Under Clallam County Local Rules: **one settlement conference per case**;
  a second requires both parties' agreement.
- Free (vs. private mediation, which costs money but can be scheduled sooner).

## 2. Local Rules vs. State CR Deadlines

### Finding: No evidence Clallam modifies the state CR 6 briefing schedule.
The Clerk's page directs filers to the Clallam County Superior Court Local Rules
for "Filing and Motion deadlines," but the courts.wa.gov link is currently
broken, and no published source was found showing Clallam deviating from the
state CR 6 schedule:
- Motion + supporting documents: **9 court days** before hearing
- Responsive documents: **4 court days** before hearing
- Reply documents: **2 court days** before hearing

The current LCRs were revised effective **September 1, 2024** (submitted to AOC
July 1, 2024). The 2022 local rules (via secondary sources) covered motion
calendar *procedures* (how to note motions, 10-minute oral argument limit per
side, continuance rules) but did not alter briefing *timelines*.

**Recommendation:** Keep the state CR 6 rules in `deadlines.py` as the default.
Add a Clallam-specific overlay (see §6) for calendar-aware and procedural
deadlines, not briefing-timeline changes.

### Clallam-Specific Procedural Deadlines Found
These are NOT in the current `deadlines.py` and should be added as Clallam
overlay rules:

| Deadline | Rule | Source |
|---|---|---|
| **Bench copies due by NOON the day before hearing** | All contested motions | Clerk's pro se guide; Superior Court page |
| **Bench copies required if pleading filed within 5 days of hearing** | Deliver to clerk's office box; no electronic bench copies accepted | Clerk's office notice (post-pandemic procedures) |
| **Telephone confirmation required** for motion calendar cases | Call before the Friday calendar | Calendars page (clallamcountywa.gov/1520/Calendars) |
| **Ex parte filing cutoff: 11:00 AM** day of hearing (1:00 PM calendar) | Daily ex parte | Clerk's page |
| **Response to motion for revision of commissioner's ruling: 10 days after service** | LCR 2(c) | Clallam County Bar (LCR 2, rev. 4/1/2020) |
| **Proposed orders delivered to Court Administrator before hearing** (not electronic); mark date/time on order | All proposed orders | Clerk's office notice |
| **Oral argument limited to 10 minutes per side** unless extended | All motions | 2022 LCR (verify still current) |

### Filing Methods
- **E-filing available** for Superior Court (clerk's e-filing page). Was
  briefly down April 6–10, 2026 for a system transition — resolved.
- **No fax or email filings** accepted by the Clerk's office for new pleadings.
- Grey drop box in front of courthouse available for physical delivery.

## 3. Clallam-Specific Filing Requirements (Family Law)

- **Dissolution filing fee: $364** (vs. $290 general civil).
- **Case cover sheets** required: Family cases use "Case Cover Sheet, Family
  (case types 3 and 5)."
- **Family Court Facilitator** (Room 212, 360-417-2588): procedural help for
  self-represented parties; sells family law forms. Not a lawyer, no legal advice.
- **Note for hearing** must be done by document (FL All Family 185 for family
  law), never by phone. Trial settings: Friday 8:45 AM; currently by telephone
  appearance through the Court Administrator.

## 4. Published Calendar & Schedule-Change Detection

### Friday Judge Bench Assignments (BEST auto-detection candidate)
- **URL:** https://www.clallamcountywa.gov/DocumentCenter/View/17465/Friday-Superior-Court-Judges-Calendar-PDF?bidId=
- **Format:** XLSX served through the county DocumentCenter; browser renders it
  as an HTML table when opened.
- **Update cadence:** "Updated as Needed — Please Refer Back Often for Most
  Up-To-Date Information." Last observed update: **10/05/26**. Changes flagged
  with `*` and the change date.
- **Coverage:** Currently published through **01/01/27**, including holiday
  closures (11/27/26, 12/25/26, 01/01/27 marked "HOLIDAY NO CALENDARS").
- **Auto-detection feasibility: YES, with polling.** The document has a visible
  "Updated MM/DD/YY" header. A scheduled job can:
  1. Fetch the URL weekly (or twice weekly).
  2. Parse the "Updated" date and/or hash the content.
  3. If the update date or hash changed since last check, flag "Court calendar
     updated — review changes" in the app dashboard.
  4. Optionally diff the table rows to highlight which Fridays changed judges.
- **Caveat:** DocumentCenter URLs can change when the county uploads a new
  version (the `17465` ID may rotate). The poller should handle HTTP errors
  gracefully and alert if the document disappears.

### Today's Court Calendar (NOT scrapeable)
- **URL:** via https://www.clallamcountywa.gov/1520/Calendars → "Today's Court
  Calendar" → reachcm.com link.
- **Format:** Third-party JavaScript calendar app (reachcm.com). Not fetchable
  via HTTP; requires a browser session.
- **Note on page:** "Calendars are subject to change throughout the day; please
  check regularly for updates. Calendars are usually finalized by 5:00pm for the
  next business day."
- **Auto-detection feasibility: NO.** Manual check required. The app should link
  to the Calendars page and remind users to confirm the day before a hearing.

### Odyssey Portal (case dockets — NOT scrapeable)
- **URL:** https://odysseyportal.courts.wa.gov/ (select Clallam, search by
  courtroom + date range).
- Interactive portal with pop-ups; not suitable for automated polling.
- Useful for manual docket verification; link it from the case detail page.

### Recommended App Design
1. **Automated:** Weekly poll of the Friday Judge Calendar document → dashboard
   alert on change ("Court calendar updated 10/05/26 — 2 Fridays changed").
2. **Manual:** "Verify calendar" checklist item auto-added to every hearing
   deadline pushed to the case calendar: "Confirm judge assignment at
   clallamcountywa.gov/1520/Calendars the day before."
3. **Telephone confirmation reminder:** auto-added as a task 1 court day before
   every Friday motion hearing ("Call court to confirm motion calendar appearance").

## 5. Administrative Orders Affecting 2026–2027

- **No active emergency orders found.** COVID-era Emergency Order #1 is
  superseded; procedures have returned to pre-pandemic norms.
- **E-filing transition (April 6–10, 2026):** completed; e-filing operational.
- **Commissioner vacancy (Feb 2026 – ~Apr/May 2026):** judges covering Family
  Court; schedule reportedly unchanged but worth verifying per-case.
- **AI disclosure rules:** Clallam adopted AI-use disclosure requirements
  effective September 1, 2025 (certification of AI assistance in filings).
  Relevant if the firm uses AI-assisted drafting — the document templates
  feature should include a reminder.
- **Weapons-free courthouse / single-point entry:** facility change (Sept 2025),
  no calendar impact.
- **Jamestown Treatment Center (opens early 2026):** may add two court calendars
  per week for Assisted Outpatient Treatment hearings — watch for calendar
  expansion affecting courtroom availability.

## 6. Recommended `deadlines.py` Adjustments

### A. New "clallam" overlay rule set (additive, not replacing state rules)
```python
# Pseudocode — for the developer implementing this:
DEADLINE_RULES["clallam_hearing"] = {
    "label": "Clallam County Motion Hearing (Friday calendar)",
    "description": "State CR 6 briefing deadlines + Clallam procedural requirements.",
    "deadlines": [
        # existing 9/4/2 court-day briefing deadlines (unchanged),
        # PLUS:
        {"key": "bench_copies", "label": "Bench copies due (NOON)",
         "days": 1, "unit": "court", "direction": "before",
         "basis": "Clallam Co. — bench copies by noon day before hearing"},
        {"key": "phone_confirm", "label": "Telephone confirmation of motion calendar",
         "days": 1, "unit": "court", "direction": "before",
         "basis": "Clallam Co. Calendars page — phone confirmation required"},
        {"key": "ex_parte_cutoff", ...},  # for ex parte trigger type
    ],
}
```

### B. New trigger types to add
- **Ex parte hearing:** filing cutoff 11:00 AM same court day (0 court days
  before, time-of-day aware — store as a same-day task with 11 AM time).
- **Child support calendar:** constrain hearing dates to 1st/3rd Tuesdays;
  warn if the entered date is not a child-support Tuesday.
- **Friday motion calendar:** warn if the entered hearing date is not a Friday;
  suggest the nearest Friday.

### C. Calendar-aware validation (not just calculation)
- When user enters a hearing date, check: is it a Friday? If child support,
  is it a 1st/3rd Tuesday? Show a warning otherwise.
- Note which judge is assigned per the Friday calendar data (if the app caches
  the judge rotation table, it can display "Judge Barnhart (per 10/05/26
  calendar)" — with a freshness warning if the cached data is >14 days old).

### D. Auto-generated checklist items with every pushed hearing
1. "Bench copies to clerk by NOON day before hearing"
2. "Telephone confirmation of motion calendar appearance"
3. "Verify judge assignment — check clallamcountywa.gov/1520/Calendars"

### E. What NOT to change
- The 9/4/2 court-day briefing math stays as-is (no local deviation found).
- WA holiday list stays as-is (matches observed county holiday closures:
  11/27/26, 12/25/26, 01/01/27 all in the judge calendar as "NO CALENDARS").

## 7. Sources

- Clerk of Superior Court, "Timelines for Filing & Ex Parte or Motion Calendars":
  https://www.clallamcountywa.gov/200/County-Clerk-of-Superior-Court
- Superior Court calendars page: https://www.ClallamCountyWA.gov/502/Superior-Court
- Calendars (daily/weekly): https://www.clallamcountywa.gov/1520/Calendars
- Friday Judge Bench Assignments (xlsx, updated as needed):
  https://www.clallamcountywa.gov/DocumentCenter/View/17465/Friday-Superior-Court-Judges-Calendar-PDF?bidId=
- Clallam County Bar — Courts page (Zoom IDs, calendar links):
  https://clallamcountybar.com/courts/
- Clallam County Bar — LCR 2 (Revision of Commissioner's Ruling):
  https://clallamcountybar.com/category/practice-areas/litigation/
- Clallam County Bar — Settlement conferences:
  https://clallamcountybar.com/ (Family Law section)
- Odyssey Portal (dockets): https://odysseyportal.courts.wa.gov/
- WA Courts local rules (Clallam page; Superior Court LCR link currently broken,
  District Court II LCR readable):
  https://www.courts.wa.gov/court_rules/pdf/LCR/05/DIS/LCR_Clallam_II_DIS.pdf

## 8. Open Questions for the Attorney
1. Confirm the state CR 6 briefing schedule is what he follows in Clallam
   County practice (no local deviation found, but he knows the courtroom).
2. Confirm bench-copy practice (noon day-before) is still current.
3. Whether he wants the Friday judge-rotation table cached in the app, and how
   often to re-poll it.
4. Whether child-support Tuesday validation would be useful or annoying.
5. AI-disclosure certification: does he want a reminder/checkbox on generated
   documents given the Sept 2025 AI rule?
