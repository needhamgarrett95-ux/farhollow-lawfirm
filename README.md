# Farhollow Law Firm — Case Management System

Self-hosted case management for a solo family law practice. Runs on the office
computer, no cloud, no subscription.

## Setup (Windows)

1. Install **Python 3.11 or newer** from https://www.python.org/downloads/
   - During install, check **"Add python.exe to PATH"**.
2. Open **Command Prompt** and go to this folder:
   ```
   cd C:\path\to\lawfirm
   ```
3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
4. Start the app:
   ```
   python app.py
   ```
5. Open your browser to: **http://localhost:5000**

On first run a default admin account is created:
- Username: `admin`
- Password: `changeme123`

You will be forced to change the password on first login.

## What it does (v1)

- Secure login with password hashing and 30-minute inactivity timeout
- Client management (contact info, spouse/partner, children)
- Case/matter management (divorce, custody, support, adoption, other)
- Dashboard with active cases and recent activity
- Audit log of every login and every record viewed/created/changed/deleted

## Data

The database is a single file: `instance/lawfirm.db`. Back it up regularly —
see MAINTENANCE.md.

Sensitive fields (SSNs, dates of birth) are **encrypted at rest** using
Fernet (AES). The encryption key is `instance/data.key` — back it up with
the database. If the key is lost, encrypted fields cannot be recovered.

The `instance/` folder (database + keys) is never committed to git.

## Security notes

- The app listens on `127.0.0.1` (this computer only) by default.
- Passwords are hashed with Werkzeug (PBKDF2). They are never stored in plain text.
- All database queries are parameterized.
- For the full maintenance manual (backups, restores, troubleshooting),
  read **MAINTENANCE.md**.
