# Farhollow Law Firm — Case Management System

Self-hosted case management for a solo family law practice. Runs on the office
computer, no cloud, no subscription. Other office computers connect over the
local network through their browser.

> ⚠️ **Office network only.** This software is designed for your office LAN.
> Do NOT expose port 5000 to the internet.

## Installation

There are two roles: **host** (one computer runs the server) and **client**
(other computers connect via browser).

### Host computer (easiest: use the installer)

1. Run `LawFirmHostSetup.exe` (built from `installer/host-setup.iss`).
2. Follow the prompts:
   - Allow office computers to connect (opens Windows Firewall for port 5000).
   - Optionally start the server automatically when Windows starts.
3. Double-click the **Law Firm Case Management** desktop shortcut.
4. A window opens showing the address other computers use, e.g.
   `http://192.168.1.100:5000`. **Leave this window open** while the office
   needs access.

### Host computer (manual: from source)

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
4. Start the server (network mode — office computers can connect):
   ```
   python app.py
   ```
5. Note the LAN address printed on startup. Other computers use that address.

For single-computer mode (no network access): `python app.py --local-only`

### Office computers / laptops (clients)

No software to install — just a browser.

1. Run `installer\client-setup.bat`.
2. Enter the host computer's IP address when asked.
3. A **Law Firm** icon appears on the desktop. Double-click it.

If the shortcut stops working, the host's IP may have changed — run
`client-setup.bat` again with the new address.

## First login

On first run a default admin account is created:
- Username: `admin`
- Password: `changeme123`

You will be forced to change the password on first login.

## What it does

- Secure login with password hashing and 30-minute inactivity timeout
- Client management (contact info, spouse/partner, children)
- Case/matter management (divorce, custody, support, adoption, other)
- Document storage with versioning
- Calendar with court dates and filing-deadline warnings
- Conflict checking (warns on potential conflicts of interest)
- Billing: time tracking and invoicing
- Automated daily backups (database + encryption key)
- Tamper-evident audit log of every login and record change

## Data

The database is a single file: `instance/lawfirm.db`. It is backed up
automatically once a day (see MAINTENANCE.md), but copy backups offsite
weekly.

Sensitive fields (SSNs, dates of birth) are **encrypted at rest** using
Fernet (AES). The encryption key is `instance/data.key` — back it up with
the database. If the key is lost, encrypted fields cannot be recovered.

The `instance/` folder (database + keys) is never committed to git.

## Building the installers (for Garrett)

**Host exe** (on Windows):
```
installer\build-exe.bat
```
Produces `dist\LawFirmServer\`. Requires Python + `pip install pyinstaller`.

**Host installer** (on Windows):
1. Install Inno Setup 6 from https://jrsoftware.org/isinfo.php
2. Run `installer\build-exe.bat` first
3. Open `installer\host-setup.iss` in Inno Setup → Compile (Ctrl+F9)
4. Output: `installer\output\LawFirmHostSetup.exe`

**Client installer** (optional): open `installer\client-setup.iss` in
Inno Setup → Compile. Or just distribute `installer\client-setup.bat`.

## Security notes

- The app listens on `0.0.0.0:5000` by default (office network). Use
  `--local-only` for single-computer mode.
- Passwords are hashed with Werkzeug (PBKDF2). Never stored in plain text.
- All database queries are parameterized.
- SQLite runs in WAL mode for safe concurrent access from 2–4 machines.
- For the full maintenance manual (backups, restores, troubleshooting,
  network setup), read **MAINTENANCE.md**.
- For Washington State compliance details, read **COMPLIANCE.md**.
