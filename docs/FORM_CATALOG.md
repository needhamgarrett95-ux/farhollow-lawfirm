# Form Catalog — Washington Family Law (verified October 2026)

This is the human-readable companion to `form_library.py`, the registry
the Document Library runs on. It records **what was verified, against
what source, and what could not be verified** — accuracy over
completeness. If a number here ever disagrees with the official
Washington Courts forms list, the official list wins and this file
(and the registry) should be corrected.

**Primary sources used for the verification pass (October 2026):**

- The Washington Courts forms index and the official form PDFs hosted
  at **courts.wa.gov/forms** (form numbers and titles read off the
  PDFs themselves where possible).
- **Northwest Justice Project** form packets (WashingtonLawHelp.org),
  which reproduce the official packets with instructions.
- County superior-court instruction packets and local rules that cite
  the official numbers — King, Clark (incl. LCR 4.1), Cowlitz, Skagit,
  and Clallam counties.
- The firm's own Clallam County research (`clallam-research.md`),
  already encoded in the deadline rules since v1.9.0.

## A correction worth stating plainly

An early draft of this project listed the Certificate of Dissolution
as "FL Divorce 211." **That is wrong.** FL Divorce 211 is the
**Response to Petition about a Marriage**. The Certificate of
Dissolution, Declaration of Invalidity of Marriage, or Legal
Separation is **Washington State Department of Health form
DOH 422-027** — a vital-statistics form, not an FL form at all.

## Common tier — implemented in v2.8.0 (portal wizards live)

| Form | Title | Client completes |
|---|---|---|
| FL Divorce 201 | Petition for Divorce (Dissolution) | Partial — data capture; attorney drafts |
| FL Divorce 200 | Summons: Notice About a Marriage or Domestic Partnership | No (catalog) |
| FL All Family 119 | Agreement to Join Petition (Joinder) | No (catalog) |
| FL All Family 001 | Confidential Information Form | **Full wizard** |
| FL All Family 002 | Attachment to Confidential Information | **Full wizard** (v2.9.0) — client flags protected facts/documents |
| DOH 422-027 | Certificate of Dissolution / Invalidity / Legal Separation | **Full wizard** (data) |
| FL All Family 131 | Financial Declaration | **Full wizard** |
| FL All Family 135 | Declaration | **Full wizard** (the flagship) |
| FL All Family 140 | Parenting Plan | Partial — client portions; attorney completes |
| WSCSS Worksheets | WA Child Support Schedule Worksheets | Partial — input confirmation |
| FL All Family 130 | Child Support Order | No (attorney/court) |
| FL All Family 011 | Sealed Financial Source Documents (Cover Sheet) | No (catalog) |
| FL All Family 139 | Information for Temporary Parenting Plan | No (catalog) |
| FL Divorce 243 | Residential Time Summary Report | **Confirm wizard** (v2.10.0) — overnights tally + holiday split from the parenting-plan answers |
| FL Divorce 231 | Findings and Conclusions About a Marriage | **Confirm wizard** (v2.10.0) — the Final Review: client confirms the vault + case facts; the attorney drafts the Findings |
| FL Divorce 241 | Final Divorce Order (also Legal Separation / Invalid Marriage orders) | No (catalog) — its facts are confirmed in the FL Divorce 231 Final Review; the attorney prepares the order itself |
| FL All Family 101 | Proof of Personal Service | No (catalog) |
| FL All Family 117 | Service Accepted | No (catalog) |
| FL All Family 112 | Proof of Mailing or Hand Delivery | No (catalog) |
| FL All Family 185 | Notice of Hearing | No (catalog) |
| FL Divorce 223 / 224 | Motion for Temporary Family Law Order / Temporary Family Law Order | Partial — data capture wizard |
| CCS — Family | Family Case Information Cover Sheet (clerk) | No (catalog) |

**Legal separation and invalidity are not separate packets.** The
Divorce series (200/201/211/231/241) covers dissolution, legal
separation, and invalidity by its own titles — verified against the
official form titles.

**Legal separation and invalidity are not separate packets.** The
Divorce series (200/201/211/231/241) covers dissolution, legal
separation, and invalidity by its own titles — verified against the
official form titles. *(v2.9.0: the petition wizard asks which of
the three the client is filing as its first question; the variant
rides the same capture and is named on the generated petition and
data sheet.)*

## Uncommon tier — implemented in v2.9.0 (portal wizards live)

**Implemented in v2.9.0** (client data capture + DRAFT data sheets,
on the same vault/wizard machinery as the Common tier):

| Form | Title | Notes |
|---|---|---|
| FL Divorce 211 | Response to Petition About a Marriage | Per-topic agree/disagree + counter-requests |
| FL Modify 501 | Petition to Modify Child Support Order | Reuses Financial Declaration figures as confirm cards |
| FL Modify 601 | Petition to Modify Parenting Plan | Substantial-change narrative is the core |
| FL Relocate 701 | Notice of Intent to Relocate | Verified on the official PDF |
| FL Relocate 721 | Objection to Relocation | Other-side capture; ~30-day statutory deadline flagged |
| FL Parentage 301 | Petition to Decide Parentage | Verified on the official PDF |
| DOH 422-159 | Acknowledgment of Parentage | Vital-records form (Dept. of Health, rev. 03/2021) — a confirm-flow from vault facts; NOT an FL form |
| GR 34.0300 | Financial Statement (fee waiver / IFP) | Vault-financials confirm-flow; sheet states the court decides |

*Number corrections pinned by the registry:* the Modify series is
**501 = child support, 601 = parenting plan** (an earlier plan draft
had them swapped). The **Acknowledgment of Parentage is DOH 422-159**
— it is not FL Parentage 303 (see the discrepancy note below).

The rest of the tier remains catalog-only:

Responses: FL Divorce 211 (marriage), FL Divorce 212 (registered
domestic partnership). Temporary/safety: FL Divorce 224, FL Divorce 221
(Immediate Restraining Order, ex parte), FL All Family 150 (Restraining
Order). Fee waiver: GR 34.0100 / GR 34.0300 / GR 34.0500. Also:
FL All Family 132 (Public Assistance Declaration), FL All Family 120
(Notice of Address Change — same-district moves), FL All Family 161/162
(Default), FL All Family 103 (Military Dependent), FL All Family 141
(Supervised Visitation Acknowledgment), FL All Family 012/013 (sealed
cover sheets), All Civil 006 (Email Service Agreement).

**Modification (FL Modify):** 501 (child support), 600 (summons), 601
(petition to change parenting plan), 603/604 (adequate cause), 610
(final order), 623 (temporary orders in modification cases).

**Relocation (FL Relocate):** 701 (Notice of Intent to Move — number
and title verified on the official PDF), 720 (objection summons), 721
(objection + petition), 725 (motion to prevent move).

**Parentage (FL Parentage):** 301 (Petition to Decide Parentage —
verified on the official PDF), 303 (Residential Schedule — verified on
the official PDF), 331/332 (parenting plan/support petition +
response). *Discrepancy noted:* older parentage filings call the
Residential Schedule "FL Parentage 304"; the current official PDF is
303. The registry carries 303 and notes the conflict.

**Contempt:** FL All Family 165 (Motion for Contempt Hearing) —
verified as cited in superior-court local rules (e.g., Clark County
LCR 4.1(d)). **Implemented in v2.10.0** as a client data capture
(which order, what it required, what happened, what the court
should do) generating a DRAFT data sheet.

## Rare tier — implemented in v2.10.0 where a client can honestly help; the rest catalog-only, with reasons

**Implemented in v2.10.0** (client capture or intake; DRAFT data
sheets like every other wizard):

- **FL Parentage 323 — Motion for Temporary Family Law Order
  (Parentage).** Client capture: the temporary decisions needed,
  the schedule in place now, safety facts.
- **Petition for Visits (RCW 26.11)** — nonparent/grandparent
  visitation intake. The office prepares the petition from the
  client's answers. The registry shows the form number as **"—"
  (unconfirmed)**: secondary catalogs list "FL Visits 476," but
  that number is **NOT confirmed** against the official list and
  is carried only as an unverified lead in the registry note (see
  below).
- **De facto parentage (RCW 26.26A.440)** — attorney-drafting
  intake. No standard state form exists; the portal and the
  generated intake sheet both say so plainly.
- **Committed intimate relationship** — attorney-drafting intake.
  No Washington state form exists; labeled as such in the portal
  and on the output.
- **QDRO / retirement division** — attorney-drafting intake. No
  Washington state QDRO form exists; each order is drafted to the
  plan's own requirements. Portal and output say so plainly.

**Still catalog-only — deliberately, each with its reason recorded
in the registry (the staff Library view shows the reason):**

- **PO 001 — Petition for Protection Order (RCW 7.105).** Protection
  orders are the **PO series**, not "FL Protect." Number and title
  verified on the official PDF (rev. 01/2024). No wizard on
  purpose: a person in danger needs staff help immediately, not
  homework. The Protection checklist routes the client to call the
  office instead.
- FL Parentage 321 (immediate restraining order — emergency ex
  parte attorney motion), FL Parentage 324 (the temporary ORDER —
  court-signed; its facts are captured in the 323 wizard),
  FL Parentage 365 (Sexual Assault Allegation — attorney completes
  it with the client alongside the 301 petition).
- FL All Family 146 (Guardian Ad Litem order) and FL All Family
  148 (Parenting Evaluator order) — court appointment orders; the
  judge issues them and the attorney handles the nomination.

**Marked UNVERIFIED in the registry (shown with a warning in the staff
library view — do not rely on these numbers until checked against the
official list):**

- FL Relocate 706 / 707 (ex parte final-order pair) — secondary
  form catalogs only; also attorney ex parte documents, so they
  stay catalog-only even once verified.
- FL Visits 476, Petition for Visits (RCW 26.11) — the Visits series
  exists, but this exact number came from secondary catalogs only.
  The v2.10.0 visits intake is live; the number itself remains an
  unverified lead, shown as "—" in the registry.
- De facto parentage (RCW 26.26A.440) — no dedicated mandatory state
  form number verified; pleaded through the parentage series.
- Committed intimate relationship — no mandatory Washington state form
  verified; locally drafted pleading.
- QDRO — no Washington state form exists; orders are drafted to the
  retirement plan's own requirements.

## Clallam County reconciliation

The app already encodes Clallam's local rules (deadline engine,
v1.9.0) — the library reconciles rather than duplicates them:

- Family-law motions: Friday 9:00 AM calendar; child support: 1st and
  3rd Tuesdays 9:00 AM; bench copies by noon the day before; **phone
  confirmation of family-law motions is required**; ex parte at
  1:00 PM with an 11:00 AM filing cutoff.
- Dissolution filing fee: $364.
- New family cases file with the county **Case Cover Sheet, Family**
  (case types 3 and 5) — cataloged as "CCS — Family."
- Hearings are noted with **FL All Family 185** — never by phone.
- Clallam's own pro se packets (Superior Court, county DocumentCenter)
  are built around the same state FL forms (e.g., the Response packet
  around FL Divorce 211) — there are no Clallam-specific form numbers
  beyond the county cover sheet.

## How the tiers map to releases

- **v2.8.0:** Common tier implemented end-to-end — vault, wizard
  engine, staff library with per-document portal switches.
  Uncommon/Rare are catalog-only (staff-visible, labeled "in a
  later release," never client-facing).
- **v2.9.0:** scenario packets (8 guided checklists —
  starting a divorce, responding to service, uncontested, temporary
  orders, changing an order, relocation, protection, parentage)
  with staff assignment from the client record or the Library, plus
  the Uncommon tier wizards listed above and the FL All Family 002
  sealed-attachment wizard. Rare stays catalog-only.
- **v2.10.0 (this release) — the library is complete.** Rare tier:
  FL Parentage 323 capture, the RCW 26.11 visits intake, and the
  three no-state-form attorney-drafting intakes (de facto
  parentage, committed intimate relationship, QDRO). Common tier
  finished: FL Divorce 243 and the FL Divorce 231 Final Review
  (241 rides it as a pointer). Contempt (FL All Family 165)
  implemented. What remains catalog-only is catalog-only on
  purpose — court-signed orders, service proofs, summonses, cover
  sheets, emergency ex parte documents, and the protection-order
  petition — and every such entry states its reason in the
  registry and in the staff Library view. 25 of the catalog's
  documents are live portal wizards across all three tiers.
