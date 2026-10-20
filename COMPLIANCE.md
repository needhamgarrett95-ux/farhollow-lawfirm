# COMPLIANCE NOTES — Washington State

> **DISCLAIMER — READ THIS FIRST**
>
> This document describes what the software does to *support* legal
> compliance. It is **not legal advice**. The authors are not lawyers.
> The attorney using this software must verify all compliance obligations
> with their own counsel and with the Washington State Bar Association
> (WSBA). Laws and ethics opinions change; this document reflects the
> authors' understanding as of October 2026 and may become outdated.
> **The software is a tool. Compliance is the attorney's responsibility.**

---

## 1. What the software does

### RPC 1.6 — Duty to safeguard client information

Washington's Rule of Professional Conduct 1.6 requires lawyers to safeguard
**all** information relating to the representation of a client against
inadvertent or unauthorized disclosure.

Software controls addressing this:

| Control | Where |
|---|---|
| Passwords hashed with Werkzeug (PBKDF2), never stored in plain text | `app.py` — login, change-password |
| Login required for every page except the login screen | `login_required` decorator |
| Automatic logout after 30 minutes of inactivity | `login_required` inactivity check |
| CSRF tokens on all state-changing forms | `check_csrf()` |
| All database queries parameterized (no SQL injection) | every `db.execute()` call |
| Sensitive fields encrypted at rest (SSNs, dates of birth) | `crypto.py`, `encrypt_value`/`decrypt_value` |
| Tamper-evident audit log (see below) | `audit_log` table + DB triggers |
| Role-based access control: Admin / Attorney / Staff roles; staff cannot see billing, delete records, or view the audit log; user management is admin-only | `role_required` / `can_delete` / `admin_required` decorators, `users` table |
| Binds to `127.0.0.1` by default (this machine only) | `app.run(...)` in `app.py` |

### WSBA Advisory Opinion 2215 — Ongoing duty of data security

Opinion 2215 confirms the lawyer's duty to stay current on data security is
**ongoing**, not one-time. The software supports this through:

- The append-only audit log, which records every login and every record
  viewed, created, changed, or deleted — giving the attorney a complete
  picture of who touched what.
- `MAINTENANCE.md`, which documents backups, updates, and breach response
  as recurring operational duties.

### RCW 19.255.010 — Data breach notification (Washington)

If **unencrypted** personal information is breached and the breach is
reasonably likely to subject consumers to a risk of harm:

- The business must notify affected Washington residents **within 30 days**.
- If **more than 500** Washington residents are affected, the business must
  **also notify the Washington Attorney General** within 30 days.

**Key point:** information that is *encrypted* may not trigger the
notification duty. That is why this software encrypts sensitive fields at
rest (SSNs, dates of birth) with Fernet (AES-128-CBC + HMAC) — see
`crypto.py`. Encryption is a legal shield under this statute, not just best
practice.

**Breach response procedure is documented in `MAINTENANCE.md`, Section 12.**
The 30-day clock and the 500-person AG threshold are called out there.

### RPC 1.15A / 1.15B — Client property; 7-year retention

Trust account and related financial records must be retained for a minimum
of **7 years**.

- **v2 (current): the billing module is now built.** Time entries and invoices
  are financial records. Every deletion path calls `retention_ok()` and
  **refuses deletion** before 7 years with a clear warning to the user.
  `retention_ok()` fails closed: missing or unparseable dates → no deletion.
- Invoiced time entries cannot be deleted while on an invoice.
- **v1.5.0 (current): full trust accounting (IOLTA) ledger.** Trust account
  handling is the #1 source of attorney discipline, so the software is
  deliberately strict:
  - **Multiple trust accounts** supported (e.g. IOLTA checking, retainer
    trust). Account numbers are encrypted at rest.
  - **Per-client sub-ledgers**: every client's balance is computed from
    transactions, never stored. Balances cannot drift.
  - **Integer cents**: all amounts stored as INTEGER cents — no float
    rounding errors, ever.
  - **Immutable transactions**: there is no edit or delete path for trust
    transactions anywhere in the code. Corrections are reversing entries
    (a new offsetting transaction linked to the original via `reverses_id`).
    Trust transactions can NEVER be deleted — `retention_ok()` is not even
    consulted because deletion is not offered.
  - **Hard overdraft block**: a disbursement or transfer exceeding the
    client's available balance is refused (not warned — refused).
  - **Transfer confirmation**: moving funds between clients requires an
    explicit confirmation checkbox.
  - **Role-gated**: trust routes require the `admin` or `attorney` role.
    The staff role gets 403 on every trust URL and the Trust tab is hidden
    from the navigation.
  - **Monthly reconciliation workflow**: record the bank statement balance;
    the software compares it to the book balance and flags mismatches.
    Reconciliation records are stored (WSBA requires them).
  - **Trial balance report**: sum of all client ledgers per account, must
    equal the account balance.
  - **Three-way reconciliation report**: bank balance = book balance = sum
    of client ledgers, the gold standard of trust accounting.
  - Every trust action (account created, deposit, disbursement, transfer,
    reversal, reconciliation) is written to the tamper-evident audit log.
  - **What the software cannot do**: it cannot verify that funds have
    actually cleared the bank before you disburse them. "Never disburse
    before funds clear" remains the attorney's duty.

### RPC 1.7 / 1.9 — Conflict of interest

The software now includes a **conflict checker** (RPC 1.7 concurrent
conflicts, RPC 1.9 duties to former clients):

- Before a new client is created, the entered name is searched against **all
  existing clients** and **all opposing parties** in every case.
- On a match, the user sees a hard-stop **POTENTIAL CONFLICT OF INTEREST**
  warning listing every match and must explicitly check a confirmation box
  to proceed. The warning, and any override, is written to the audit log.
- The checker depends on opposing parties being entered per case (case
  detail → Opposing parties). The software cannot detect conflicts it has
  not been told about — entering opposing parties is the attorney's duty.

### Automated backups (operational safeguard)

The software now performs **automatic daily backups** (database + encryption
key) while running, keeps the 30 most recent, and shows last-backup status
on the dashboard. A **"Back Up Now"** button allows manual backups.

**What this does not replace:** offsite copies (fire/flood/theft) and the
documents folder (`instance/documents/` is not in the automated backup).
These remain the office's responsibility — see MAINTENANCE.md Sections 13
and 17.

### Tamper-evident audit log

The `audit_log` table is protected by SQLite triggers
(`audit_no_update`, `audit_no_delete`) that abort any UPDATE or DELETE
against it. History can only be appended, never rewritten — including by
someone with direct database access. (A person with full file access could
still delete the whole database file, which is why offsite backups and
physical office security remain the attorney's responsibility.)

---

## 2. What remains the attorney's (and office's) responsibility

The software cannot do these things. They are operational and legal duties:

1. **Physical security.** The office computer must be in a locked room or
   area, require a Windows login password, and lock its screen when
   unattended. Anyone with physical access to the machine can reset the
   admin password (see `MAINTENANCE.md` Section 9) — that is inherent to
   self-hosting.
2. **Backups.** The software now backs itself up automatically once a day
   (database + encryption key, 30 kept) and shows status on the dashboard.
   What it does NOT do: copy backups **offsite** (fire/flood/theft), or back
   up the **documents folder** (`instance/documents/`). Someone must copy
   backups and documents to a USB drive weekly and take it offsite
   (see `MAINTENANCE.md` Sections 13 and 17). Losing `data.key` means
   encrypted fields can never be decrypted again.
3. **Updates.** Security patches to Python, Flask, and this app must be
   applied (see `MAINTENANCE.md` Section 5).
4. **Breach notification decisions.** The software encrypts data and logs
   access, but *whether a given incident triggers RCW 19.255.010
   notification* — and drafting the notices — is a legal judgment for the
   attorney and their counsel.
5. **Retention policy enforcement.** The 7-year financial minimum is enforced
   in code for time entries and invoices. The attorney sets the firm's broader
   document retention and destruction policies.
6. **Verifying compliance.** Rules change. The attorney must periodically
   confirm with counsel and the WSBA that the firm's practices (including
   this software) still satisfy current obligations.
7. **Malware / network security.** Keep Windows updated, use reputable
   antivirus, and do not install untrusted software on the office computer.
8. **Payroll tax accuracy.** The payroll module calculates withholdings using
   the rates entered in Tax Settings. Those rates change annually — the owner
   must verify them against current IRS (Publication 15-T), WA Employment
   Security Department, and WA Labor & Industries publications before each
   year's first payroll run. Incorrect withholdings are the employer's legal
   liability. This software does not replace a CPA or payroll professional.
9. **User permission assignments.** The admin decides who gets which
   permissions. Granting overly broad access (e.g., giving billing access to
   someone who doesn't need it) is an administrative decision with
   confidentiality consequences under RPC 1.6.

---

## 3. Data map (for counsel's review)

| Data | Stored where | Protected how |
|---|---|---|
| Passwords | `users.password_hash` | Hashed (PBKDF2 via Werkzeug), never plain text |
| User roles, active status | `users.role`, `users.is_active` | Admin-only management; deactivated users cannot log in |
| Client SSNs | `clients.ssn` | Encrypted at rest (Fernet) |
| Client/spouse/child DOBs | `clients.date_of_birth`, `clients.spouse_dob`, `children.date_of_birth` | Encrypted at rest (Fernet) |
| Names, contact info, notes | `clients`, `cases` tables | Access-controlled (login required), not encrypted at rest in v1 |
| Opposing parties | `opposing_parties` | Access-controlled; drives conflict checker |
| Document files | `instance/documents/<case_id>/` on disk | Access-controlled (login required); metadata in DB |
| Calendar events | `calendar_events` | Access-controlled |
| Time entries, invoices | `time_entries`, `invoices`, `invoice_items` | Access-controlled; 7-year deletion lock (RPC 1.15B) |
| Trust accounts, transactions, reconciliations | `trust_accounts`, `trust_transactions`, `trust_reconciliations` | Attorney/admin only; immutable transactions (no edit/delete path); integer cents; encrypted account numbers; 7-year retention (RPC 1.15A/B) |
| Backup log | `backups` | Access-controlled |
| Audit history | `audit_log` | Append-only (DB triggers block edit/delete) |
| Encryption key | `instance/data.key` | File permissions 0600; must be backed up offsite |
| Session signing key | `instance/secret.key` | File on server; sessions expire after 30 min idle |
| Backup copies | `instance/backups/` (or configured dir) | Same protections as source files; 30 kept |

> **Note for counsel:** names and contact details are access-controlled but
> not field-encrypted in v1. If the firm's risk assessment requires it,
> field encryption can be extended to additional columns following the
> existing `crypto.py` pattern.

## 4. Addendum (v2.6.0) — client portal

The client portal gives each client a login that shows only their own
case status, document requests, uploads, forms, and messages. Notes for
counsel's review:

- **Confidentiality (RPC 1.6).** Portal accounts are bound one-to-one
  to a single client record and are invite-only; every portal query is
  scoped server-side to the authenticated client's own record, and the
  boundary is covered by automated tests (one client cannot retrieve
  another's documents, forms, messages, or requests by any URL).
  Client uploads are quarantined and never enter the case file until a
  staff member accepts them; file contents are verified by type
  inspection, not file name. All portal activity — including logins —
  is written to the same append-only audit log as staff activity.
  Portal authentication is a separate realm from staff authentication;
  neither credential opens the other side. Reasonable efforts against
  unauthorized disclosure still depend on deployment: the portal must
  be served over an encrypted connection (the firm's private network /
  secure remote access) and never exposed directly to the open
  internet, and invite links should be delivered to the client through
  a channel the firm trusts.
- **Communication (RPC 1.4).** The portal shows case status and the
  next court date only; it is not a substitute for attorney advice.
  The messaging composer carries a standing notice that messages are
  reviewed during office hours and that emergencies go to 911.
- **Opposing parties.** Where both parties to a matter are firm
  clients with portal access, accounts remain fully segregated; the
  software additionally warns staff on the client record. Whether to
  invite an opposing party at all remains the attorney's judgment
  under RPC 1.7.

## 5. Addendum (v2.8.0) — Document Library, profile vault, and client wizards

The Document Library lets clients complete guided wizards for common
Washington family-law documents (declaration, financial declaration,
confidential information form, vital-statistics certificate, and
client-data capture for the petition, parenting plan, support
worksheets, and temporary orders). Points for counsel's review:

- **Drafts are drafts — attorney review before filing.** Everything a
  client completes is a draft. Wizard submissions enter the same
  staff review queue as other portal forms; nothing is imported into
  the client record, and no document is generated, until a staff
  member approves it, and every generated document is banner-marked
  DRAFT for attorney completion. No client action in the portal files
  anything with any court, and the software makes no representation
  that generated drafts conform to the official forms — figures and
  text must be verified against the official Washington Courts forms
  (the catalog's verification sources and its explicitly *unverified*
  entries are documented in `docs/FORM_CATALOG.md`).
- **Perjury attestation language.** The Declaration wizard collects a
  draft attestation in the portal (an explicit checkbox plus the
  client's typed name) under the statement: "I declare under penalty
  of perjury under the laws of the state of Washington that the
  foregoing is true and correct." The generated declaration carries
  that attestation block and signature/date lines and is labeled a
  draft; a verified/wet signature in the manner the court requires
  remains necessary before filing, and counsel should confirm the
  attestation procedure (cf. GR 13 / RCW 9A.72.085) for each filing.
- **No silent overwrite of confirmed client facts.** Facts the firm
  already holds (the "profile vault": client record, children, case
  financials, and a key/value fact store) are shown to clients as
  confirmations. A client-changed value is held as a pending update
  and takes effect only when staff import the submission; dismissing
  the submission rejects the change. The prior value remains visible
  to staff side-by-side throughout.
- **Confidentiality (RPC 1.6).** Vault access is scoped server-side
  to the authenticated client's own record, under the same tested
  boundary as the rest of the portal (one client cannot read or
  affect another's facts, drafts, or submissions by any URL).
  Sensitive facts (SSN, dates of birth, protected account details)
  are encrypted at rest with the firm's existing field encryption,
  and SSN/ID values are masked (last four only) wherever the portal
  displays them for confirmation. The Confidential Information Form
  data (FL All Family 001) is GR 22 material: it is collected for the
  sealed filing, and clients are instructed in the wizard to provide
  account institutions with last-four digits only.
- **Safety.** The Declaration wizard's optional safety section and
  the catalog's protection-order entry are worded to route urgent
  safety needs to the office (and, in the portal generally, to 911)
  rather than into a document queue; protection filings remain a
  staff-handled, same-day matter.
