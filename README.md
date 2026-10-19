# Farhollow Law Firm — Case Management System

Self-hosted case management for a solo family law practice. Runs on the office
computer, no cloud, no subscription. Other office computers connect over the
local network through their browser.

> ⚠️ **Office network only.** This software is designed for your office LAN.
> Do NOT expose port 5000 to the internet.

## Installation (easiest — download the installer)

**You don't need the command line or Python for this.**

1. Go to the **Releases** page:
   https://github.com/needhamgarrett95-ux/farhollow-lawfirm/releases
2. Download the latest release's files:
   - **Host computer** (the one in the office that runs everything):
     download **`LawFirmHostSetup.exe`** and run it. Follow the prompts —
     it installs the server, opens the Windows Firewall, and can start
     automatically when Windows starts.
   - **Office computers / laptops**: download **`LawFirmClientSetup.exe`**
     and run it. Enter the host computer's IP address when asked, and a
     "Law Firm" icon appears on the desktop. (Prefer the simple route?
     `LawFirmClientFiles.zip` contains `client-setup.bat` — same result,
     no installer.)
3. On the host, double-click the desktop shortcut. A window opens showing
   the address other computers use, e.g. `http://192.168.1.100:5000`.
   **Leave this window open** while the office needs access.

New releases are built automatically — every version tag (e.g. `v1.0.0`)
produces fresh installers on the Releases page.

### Manual install from source (advanced)

If you'd rather run from Python directly:

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

## Building the installers

Installers are built automatically by GitHub Actions — see
`.github/workflows/build-installer.yml`. Every push to `main` produces
installer artifacts; every version tag produces a GitHub Release.

**Cutting a release:**
```
git tag v1.0.0
git push origin v1.0.0
```
The tag name becomes the installer version. Download from the Releases page.

**Manual build** (advanced, on Windows only):
1. `installer\build-exe.bat` — produces `dist\LawFirmServer\`
   (requires Python + `pip install pyinstaller`)
2. Install Inno Setup 6 from https://jrsoftware.org/isinfo.php
3. Open `installer\host-setup.iss` → Compile (Ctrl+F9)
   → `installer\output\LawFirmHostSetup.exe`
4. Client installer (optional): open `installer\client-setup.iss` → Compile,
   or just distribute `installer\client-setup.bat`.

## Security notes

- The app listens on `0.0.0.0:5000` by default (office network). Use
  `--local-only` for single-computer mode.
- Passwords are hashed with Werkzeug (PBKDF2). Never stored in plain text.
- All database queries are parameterized.
- SQLite runs in WAL mode for safe concurrent access from 2–4 machines.
- For the full maintenance manual (backups, restores, troubleshooting,
  network setup), read **MAINTENANCE.md**.
- For Washington State compliance details, read **COMPLIANCE.md**.
