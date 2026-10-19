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

- v1 of this software has **no billing or trust-accounting module**, so no
  financial records exist yet.
- The codebase includes `RETENTION_YEARS_FINANCIAL = 7` and a
  `retention_ok()` helper in `app.py` that fails closed (returns False for
  missing or unparseable dates).
- **Requirement for the billing build:** every financial-record deletion
  path MUST call `retention_ok()` and refuse deletion before 7 years, with a
  clear warning to the user. This is non-negotiable.

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
2. **Backups.** The software does not back itself up. Someone must copy
   `instance/lawfirm.db` **and** `instance/data.key` offsite on a regular
   schedule (see `MAINTENANCE.md` Section 3). Losing `data.key` means
   encrypted fields can never be decrypted again.
3. **Updates.** Security patches to Python, Flask, and this app must be
   applied (see `MAINTENANCE.md` Section 5).
4. **Breach notification decisions.** The software encrypts data and logs
   access, but *whether a given incident triggers RCW 19.255.010
   notification* — and drafting the notices — is a legal judgment for the
   attorney and their counsel.
5. **Retention policy enforcement.** Beyond the 7-year financial minimum
   enforced in code (once billing exists), the attorney sets the firm's
   document retention and destruction policies.
6. **Verifying compliance.** Rules change. The attorney must periodically
   confirm with counsel and the WSBA that the firm's practices (including
   this software) still satisfy current obligations.
7. **Malware / network security.** Keep Windows updated, use reputable
   antivirus, and do not install untrusted software on the office computer.

---

## 3. Data map (for counsel's review)

| Data | Stored where | Protected how |
|---|---|---|
| Passwords | `users.password_hash` | Hashed (PBKDF2 via Werkzeug), never plain text |
| Client SSNs | `clients.ssn` | Encrypted at rest (Fernet) |
| Client/spouse/child DOBs | `clients.date_of_birth`, `clients.spouse_dob`, `children.date_of_birth` | Encrypted at rest (Fernet) |
| Names, contact info, notes | `clients`, `cases` tables | Access-controlled (login required), not encrypted at rest in v1 |
| Audit history | `audit_log` | Append-only (DB triggers block edit/delete) |
| Encryption key | `instance/data.key` | File permissions 0600; must be backed up offsite |
| Session signing key | `instance/secret.key` | File on server; sessions expire after 30 min idle |

> **Note for counsel:** names and contact details are access-controlled but
> not field-encrypted in v1. If the firm's risk assessment requires it,
> field encryption can be extended to additional columns following the
> existing `crypto.py` pattern.
