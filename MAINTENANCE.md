# MAINTENANCE MANUAL — "How to Fix It for Dummies"

This manual is for the office staff who keep the Case Management app running.
You do not need to be technical. Follow the steps exactly as written.

**The golden rule: if you are unsure about a step, stop and call Garrett.**

---

## Table of contents

1. [How to start the app](#1-how-to-start-the-app)
2. [How to stop the app](#2-how-to-stop-the-app)
3. [How to back up the database](#3-how-to-back-up-the-database)
4. [How to restore from a backup](#4-how-to-restore-from-a-backup)
5. [How to update the software](#5-how-to-update-the-software)
6. [How to add a new user account](#6-how-to-add-a-new-user-account)
7. [How to reset a forgotten password](#7-how-to-reset-a-forgotten-password)
8. [What to do if the app won't start](#8-what-to-do-if-the-app-wont-start)
9. [What to do if you forget the admin password](#9-what-to-do-if-you-forget-the-admin-password)
10. [How to check that backups are working](#10-how-to-check-that-backups-are-working)
11. [When to call Garrett vs. what you can fix yourself](#11-when-to-call-garrett-vs-what-you-can-fix-yourself)
12. [What to do if you suspect a data breach](#12-what-to-do-if-you-suspect-a-data-breach)
13. [Documents: uploading, downloading, versions](#13-documents-uploading-downloading-versions)
14. [Calendar and deadlines](#14-calendar-and-deadlines)
15. [Conflict checking: what the red warning means](#15-conflict-checking-what-the-red-warning-means)
16. [Billing: time entries and invoices](#16-billing-time-entries-and-invoices)
17. [Automated backups: how they work](#17-automated-backups-how-they-work)
18. [Network setup: host computer and office computers](#18-network-setup-host-computer-and-office-computers)
19. [Installing on the host vs. office computers](#19-installing-on-the-host-vs-office-computers)
20. [What to do if office computers can't connect](#20-what-to-do-if-office-computers-cant-connect)
21. [Single-computer mode (no network)](#21-single-computer-mode-no-network)
32. [What's new in v2.0.0](#32-whats-new-in-v200--new-dashboard-dark-mode-custom-icons)

---

## 1. How to start the app

Do this every morning (or whenever the office computer has been restarted).

**Step 1.** Click the **Start** button (Windows icon, bottom-left of the screen).

**Step 2.** Type `cmd` and press **Enter**. A black window called "Command Prompt" opens.

**Step 3.** Type this command exactly and press **Enter**:

```
cd C:\lawfirm
```

> **Note:** If the app folder is somewhere else on your computer, use that
> location instead of `C:\lawfirm`. Ask Garrett if you are not sure where it is.

**Step 4.** Type this command exactly and press **Enter**:

```
python app.py
```

**Step 5.** Wait a few seconds. You should see text like this:

```
  Farhollow Law Firm - Case Management
  Open your browser to:  http://localhost:5000
```

That means the app is running. **Leave the black window open** — closing it
stops the app.

**Step 6.** Open your web browser (Chrome, Edge, or Firefox) and go to:

```
http://localhost:5000
```

You should see the login screen.

---

## 2. How to stop the app

**Step 1.** Go to the black Command Prompt window where the app is running.

**Step 2.** Hold down the **Ctrl** key and press **C**. (This is written as
**Ctrl+C**.)

**Step 3.** The app stops. You can now close the black window.

> **When to stop the app:** At the end of the day, or before updating the
> software (see Section 5). There is no harm in leaving it running overnight,
> but restarting it each morning keeps things fresh.

---

## 3. How to back up the database

**All of your client and case data lives in ONE file:**

```
C:\lawfirm\instance\lawfirm.db
```

**There is a second critical file — the encryption key:**

```
C:\lawfirm\instance\data.key
```

This small file unlocks the encrypted data (Social Security numbers, dates
of birth). **If you lose this file, the encrypted information can NEVER be
recovered — not even by Garrett.** Always back it up together with the
database.

Backing up means making a copy of this file and storing it somewhere safe.

### How often?

- **At minimum: once a week** (pick a day, e.g. every Friday).
- **Ideally: every day** at closing time. It takes 30 seconds.

### Where to keep backups?

Keep copies in **at least two** of these places:

1. A **USB flash drive** that you take home with you (not left in the office).
2. A secure cloud folder you already use (OneDrive, Google Drive, Dropbox).
3. A second computer in the office.

**Never keep your only backup in the same room as the main computer.**
If there is a fire, flood, or theft, you lose both.

### How to back up (step by step)

**Step 1.** Open **File Explorer** (the yellow folder icon on the taskbar).

**Step 2.** Go to `C:\lawfirm\instance`. You will see files including
`lawfirm.db` and `data.key`.

**Step 3.** Right-click `lawfirm.db` and choose **Copy**. Then hold **Ctrl**
and click `data.key` so **both** files are selected, right-click, and choose
**Copy**.

**Step 4.** Go to your backup location (for example, your USB drive).

**Step 5.** Right-click in the empty space and choose **Paste**.

**Step 6.** Rename the pasted file so you know when it was made. Right-click
it, choose **Rename**, and name it like this:

```
lawfirm-backup-2026-10-19.db
```

(Use today's date in year-month-day order so the files sort correctly.)

**Step 7.** Done. Eject the USB drive safely (click the USB icon near the
clock, choose "Eject").

> **Tip:** If you use OneDrive or Google Drive, you can copy the file into
> that folder instead, and it uploads automatically.

---

## 4. How to restore from a backup

Use this if the database gets corrupted, deleted, or the computer dies and
you are setting up on a new machine.

**Step 1.** **Stop the app** if it is running (see Section 2).

**Step 2.** Find your most recent backup file (e.g.
`lawfirm-backup-2026-10-19.db` on your USB drive).

**Step 3.** Copy it (right-click → **Copy**).

**Step 4.** Open File Explorer and go to `C:\lawfirm\instance`.

**Step 5.** If there is a file called `lawfirm.db` there already, rename it
to `lawfirm-broken.db` first (right-click → **Rename**). This keeps the
broken one in case you need it later.

**Step 6.** Paste your backup file into the `instance` folder
(right-click → **Paste**).

**Step 7.** Rename the pasted file to exactly:

```
lawfirm.db
```

(It must be named exactly this, with no date in the name.)

**Step 8.** **Start the app** (see Section 1) and log in. Your data should
be back as of the date of the backup.

> **Important:** You will lose any changes made after the backup was taken.
> This is why daily backups matter.

---

## 5. How to update the software

When Garrett releases a new version, follow these steps.

**Step 1.** **Stop the app** (see Section 2).

**Step 2.** **Back up the database first** (see Section 3). Always back up
before updating.

**Step 3.** Open Command Prompt (`Start` → type `cmd` → **Enter**).

**Step 4.** Go to the app folder:

```
cd C:\lawfirm
```

**Step 5.** Download the update:

```
git pull
```

**Step 6.** Wait for it to finish. You should see something like:

```
Updating abc1234..def5678
Fast-forward
```

If you see an error, **stop and call Garrett**.

**Step 7.** **Start the app** (see Section 1).

**Step 8.** Log in and check that everything looks normal.

> **What if you don't have `git`?** If the `git pull` command says "not
> recognized," Garrett will need to install Git on the office computer first.
> Call him.

---

## 6. How to add a new user account

> **Note:** In version 1, there is no "add user" button in the app itself.
> Adding a user requires running one command. This will be simpler in a
> future version.

**Step 1.** **Stop the app** (see Section 2).

**Step 2.** Open Command Prompt and go to the app folder:

```
cd C:\lawfirm
```

**Step 3.** Run this command, replacing `newusername`, `New Password Here`,
and `Full Name` with the real values:

```
python -c "from app import get_db, init_db; from flask import Flask; from werkzeug.security import generate_password_hash; from datetime import datetime; import app as a; ctx = a.app.app_context(); ctx.push(); a.init_db(); db = a.get_db(); db.execute('INSERT INTO users (username, password_hash, full_name, must_change_password, created_at) VALUES (?, ?, ?, 1, ?)', ('newusername', generate_password_hash('Temp Password 123'), 'Full Name', datetime.utcnow().isoformat())); db.commit(); print('User created.')"
```

That is a long command. **It is easier to ask Garrett to do this for you.**
The new user will be forced to change their password on first login.

**Step 4.** **Start the app** (see Section 1).

**Step 5.** Tell the new user their temporary username and password. They
must change the password when they first log in.

---

## 7. How to reset a forgotten password

If someone forgets their password (but you still have admin access),
the simplest fix is:

**Step 1.** Log in as the admin user.

**Step 2.** There is no password-reset button in version 1. **Call Garrett**
and he can reset it for you in under a minute.

> **Why not just make a new account?** You could, but then the old account
> still exists. It is cleaner to reset the existing one. Call Garrett.

---

## 8. What to do if the app won't start

Try these in order. **Stop after the first one that works.**

### Problem: "python is not recognized"

**What it means:** Python is not installed, or Windows can't find it.

**What to do:**

1. Open Command Prompt and type:
   ```
   python --version
   ```
2. If it says "not recognized," Python needs to be (re)installed.
3. Download Python from https://www.python.org/downloads/ and install it.
4. **Important:** During installation, check the box that says
   **"Add python.exe to PATH"** before clicking Install.
5. Close Command Prompt, open a new one, and try `python app.py` again.
6. If it still doesn't work, **call Garrett**.

### Problem: "Address already in use" or "Port 5000 is in use"

**What it means:** The app is already running somewhere (maybe in another
black window you forgot about).

**What to do:**

1. Look for any other black Command Prompt windows. If you find one running
   the app, that's fine — just use it. You don't need to start another one.
2. If you can't find one, restart the computer. That clears it.
3. After restarting, start the app normally (see Section 1).

### Problem: "database is locked"

**What it means:** Something else is using the database file at the same
time.

**What to do:**

1. Make sure only **one** copy of the app is running. Close any extra
   Command Prompt windows.
2. Wait 30 seconds and try starting the app again.
3. If it still says "database is locked," restart the computer and try again.
4. If it *still* doesn't work, **call Garrett**. (Do NOT delete the
   database file.)

### Problem: A long error message with the word "Traceback"

**What to do:**

1. Take a photo of the screen with your phone.
2. Send the photo to Garrett.
3. Do not try to fix it yourself — Traceback errors need a developer.

### Problem: The browser says "This site can't be reached"

**What it means:** The app isn't running, or you're going to the wrong address.

**What to do:**

1. Check that the black Command Prompt window is still open and shows the
   "Open your browser to: http://localhost:5000" message.
2. Make sure you typed the address exactly: `http://localhost:5000`
   (not Google, not a search — type it in the address bar at the top).
3. If the black window closed or shows an error, go to
   [What to do if the app won't start](#8-what-to-do-if-the-app-wont-start).

---

## 9. What to do if you forget the admin password

This is the "break glass" procedure. It requires access to the office
computer.

**Step 1.** **Stop the app** (see Section 2).

**Step 2.** Open Command Prompt and go to the app folder:

```
cd C:\lawfirm
```

**Step 3.** Run this command to reset the admin password to `changeme123`:

```
python -c "from werkzeug.security import generate_password_hash; import sqlite3; db = sqlite3.connect('instance/lawfirm.db'); db.execute('UPDATE users SET password_hash = ?, must_change_password = 1 WHERE username = ?', (generate_password_hash('changeme123'), 'admin')); db.commit(); print('Admin password reset to: changeme123')"
```

**Step 4.** **Start the app** (see Section 1).

**Step 5.** Log in as `admin` with password `changeme123`. You will be
forced to set a new password immediately.

> **Security note:** Anyone with access to the office computer can do this.
> That is by design — physical access to the server means full access. This
> is why the office computer itself must be secured (locked room, Windows
> password, screen lock when away).

---

## 10. How to check that backups are working

Do this **once a month**. It takes two minutes.

**Step 1.** Look at your backup location (USB drive, cloud folder, etc.).

**Step 2.** Check:
- [ ] Is there a backup file from **this week**?
- [ ] Is the file **not zero bytes**? (Right-click → Properties → Size.
      It should be more than 0 KB. A healthy database is usually at least
      50–100 KB.)
- [ ] Can you see **multiple** backup files with different dates?
      (If you only ever see one file, something is wrong with your routine.)

**Step 3.** If all three checks pass, your backups are working.

**Step 4.** If any check fails, fix your backup routine immediately (see
Section 3) and tell Garrett at your next check-in.

> **The one test that really matters:** Once every few months, try
> restoring a backup on a *different* computer (see Section 4). A backup
> you have never tested is a backup you cannot trust.

---

## 11. When to call Garrett vs. what you can fix yourself

### You can handle this yourself ✅

- Starting and stopping the app (Sections 1–2)
- Backing up the database (Section 3)
- Restoring from a backup (Section 4)
- Updating the software with `git pull` (Section 5)
- "Port in use" errors (restart the computer)
- "Site can't be reached" (check the app is running)
- Logging in, adding clients and cases (normal daily use)

### Call Garrett for this 📞

- Any error message with the word **"Traceback"**
- "Database is locked" that doesn't go away after a restart
- `git pull` shows an error or conflict
- You need a **new user account** created
- You need a **password reset** for someone
- The app starts but pages look broken or show errors
- You want a **new feature** or something changed
- You are **unsure about any step** in this manual

### Call Garrett IMMEDIATELY (don't wait) 🚨

- You suspect someone **unauthorized** accessed the system
- The database file is **missing** and you have no backup
- You see client data that **you did not enter**
- The office computer was **stolen** or broken into
- **Ransomware** or virus warning on the office computer

---

*Last updated: October 2026. If anything in this manual doesn't match what
you see on screen, stop and call Garrett — the software may have been
updated.*

---

## 12. What to do if you suspect a data breach

A "breach" means you believe someone who should not have access got (or may
have gotten) client information. Examples: the office computer was stolen,
you see logins you don't recognize in the Audit Log, a phishing email was
clicked, ransomware appeared.

**Washington law (RCW 19.255.010) sets a 30-DAY clock.** If unencrypted
personal information was breached and people are likely to be harmed, you
must notify the affected Washington residents within 30 days. If more than
500 Washington residents are affected, you must ALSO notify the Washington
Attorney General within 30 days. **These are legal deadlines — the attorney
must treat them as urgent.**

**Step 1. Do not panic, and do not delete anything.**
Do not wipe the computer or delete files — the Audit Log is evidence of
what happened. (The audit log cannot be edited or deleted through the app,
but preserve the whole machine as-is.)

**Step 2. Contain it.**
- If the computer is actively compromised (ransomware on screen, remote
  intruder), disconnect it from the internet (unplug the network cable or
  turn off Wi-Fi) but **leave it powered on**.
- Change the app passwords once you are on a clean machine (see Section 9
  for the admin reset).

**Step 3. Figure out what happened (with Garrett's help).**
- Open the **Audit Log** page in the app and look for unfamiliar usernames,
  logins at odd hours, or records you don't recognize being viewed.
- Write down: when you first noticed it, what you saw, and what you did.
  Dates and times matter.

**Step 4. The attorney decides on notification — immediately.**
- Washington's 30-day clock is short. The attorney (with their own counsel
  if needed) must decide quickly whether RCW 19.255.010 notification is
  required.
- Important: sensitive fields in this app (SSNs, dates of birth) are
  **encrypted at rest**. Under RCW 19.255.010, a breach of encrypted data
  may not trigger the notification duty — but that is a legal judgment call,
  not an IT one.
- If more than 500 Washington residents may be affected, the Attorney
  General must also be notified within 30 days.

**Step 5. Document everything.**
Keep a written record: what happened, when, who was affected, what you did
about it, and when. Store it somewhere safe (not only on the compromised
computer).

**Step 6. Call Garrett immediately** — do not wait for the next check-in.
Then the attorney should consult their own counsel about notification
obligations. When in doubt, notify.

> **Bottom line:** the software gives you encryption and an audit trail to
> limit damage and prove what happened. The legal response — who to notify
> and when — is the attorney's call, on a 30-day clock.

---

## 13. Documents: uploading, downloading, versions

Each case has its own document library. Open a case, then click **Documents**.

**To upload a file:**

**Step 1.** Click **Choose File** and pick the file from your computer.

**Step 2.** Choose a **Category**: Pleadings, Correspondence, Discovery, Evidence, or Other.

**Step 3.** Optionally type a short note (e.g. "Final version filed with court").

**Step 4.** Click **Upload**.

**Versions:** If you upload a file with the same name and category twice, the app
keeps both — the new one becomes "Version 2", the old one stays as "Version 1".
Nothing is ever silently overwritten. Download any version at any time.

**Where files live:** Documents are stored on disk in the `instance/documents`
folder (inside the app folder), organized by case. They are **not** inside the
database file. This means:
- When you back up the database (Section 3), **also back up the documents folder**.
  The automated backup (Section 17) covers the database and encryption key only.
- If you ever move the app to a new computer, copy the whole app folder —
  database, documents, and everything.

**Blocked file types:** For security, the app refuses to upload programs
(`.exe`, `.bat`, `.ps1`, etc.). If you legitimately need to store one, call Garrett.

---

## 14. Calendar and deadlines

Click **Calendar** in the top menu to see the month view. Click **Add event** to
create one.

**Event types:**
- **Court date** — hearings, trials, appearances (shown in red on the calendar)
- **Filing deadline** — shown in bold red; these are the most important
- **Meeting** — client meetings, depositions
- **Reminder** — anything else

**The dashboard is your safety net.** Every time you log in, the dashboard shows:
- 🔴 **Overdue items** in a red box at the top — things whose date has passed
  and are not marked done. Deal with these first.
- **Upcoming deadlines** (next 14 days) — anything due within **7 days** is
  highlighted in red.

**To mark something done:** click **Mark done** next to it. It disappears from
the deadline lists but stays in the calendar history.

**Malpractice warning:** A missed filing deadline can lose a case and trigger a
bar complaint. Check the dashboard every morning. If the red box appears, stop
what you are doing and handle it.

---

## 15. Conflict checking: what the red warning means

When you add a new client, the app automatically searches:
1. All existing clients, **and**
2. All opposing parties in every case

by first and last name. If it finds a match, you see a big red
**POTENTIAL CONFLICT OF INTEREST** warning.

**What to do:**

**Step 1.** Read the matches carefully. Is it the same person, or just the same name?

**Step 2.** If it is the **same person** and they are an opposing party in another
case — **stop**. Do not add this client. Talk to the attorney before doing anything.
Taking on a client when you already represent (or previously opposed) them can be
an ethical violation (RPC 1.7, 1.9).

**Step 3.** If it is a **different person** with the same name, check the box that
says you have reviewed the warning and click **Add client anyway**.

**Step 4.** Your decision is recorded in the audit log either way — including
when you override the warning. This protects the firm if the conflict is ever
questioned later.

**To make conflict checking work, you must add opposing parties to every case.**
Open a case → scroll to **Opposing parties** → add everyone on the other side
(name + role, e.g. "respondent", "co-parent"). The checker is only as good as
the data you put in.

---

## 16. Billing: time entries and invoices

### Logging time

Open a case → click **Time entries** → fill in the date, hours (e.g. 1.5),
hourly rate, and a description of the work → click **Add entry**.

**Rules to know:**
- Time entries **cannot be deleted** once they are more than 7 years old — actually,
  it is the opposite: they cannot be deleted *until* they are 7 years old
  (RPC 1.15B, financial record retention). If you try, the app will refuse and
  explain why.
- A time entry that has been put on an invoice cannot be deleted at all. Delete
  the invoice first (subject to the same 7-year rule).

### Creating an invoice

**Step 1.** Click **Billing** in the top menu → **New invoice**.

**Step 2.** Choose the client. The page reloads and shows all **unbilled time**
for that client — checked by default.

**Step 3.** Uncheck any time entries you do *not* want on this invoice.

**Step 4.** Add extra line items if needed (filing fees, copies, etc.) with
**+ Add line**.

**Step 5.** Fill in issue date and due date → **Create invoice**.

**Step 6.** On the invoice page, change the status as things happen:
**Draft → Sent → Paid** (or **Overdue**).

**The dashboard** shows how many invoices are unpaid (Sent or Overdue).

---

## 17. Automated backups: how they work

The app now backs itself up **automatically once a day** while it is running.
You do not need to do anything for this to work — but you do need to keep the
app running (see Section 1).

**What gets backed up:**
- The database (`lawfirm.db`) — all clients, cases, documents metadata, calendar, billing
- The encryption key (`data.key`) — **without this, encrypted fields (SSNs, birth dates) cannot be read**

**Where:** The `instance/backups` folder inside the app folder, unless Garrett
configured a different location.

**How many:** The 30 most recent backups are kept. Older ones are deleted
automatically.

**What YOU still need to do:**
1. **Check the dashboard.** It shows the last backup date and time prominently.
   If it says "No backups yet" or shows a failure, tell Garrett.
2. **Copy backups offsite weekly.** The automated backup protects against
   database corruption — it does **not** protect against fire, flood, or theft.
   Once a week, copy the newest backup files to a USB drive and take it home.
   (Or ask Garrett to set up an automatic offsite copy.)
3. **The documents folder is NOT in the automated backup.** Copy
   `instance/documents` to your USB drive too (see Section 13).

**"Back Up Now" button:** On the dashboard, click this any time you want an
immediate backup — for example, right before updating the software (Section 5)
or after entering a large amount of data.

**Backup history:** Click **Backup history** on the dashboard to see every backup
the app has taken, when, and whether it succeeded.

---

## 18. Network setup: host computer and office computers

The system is designed so **one computer** (the "host") runs the server, and
**other office computers** connect to it through their web browser. Everyone
sees the same live data.

**Which computer is the host?** Pick one computer that stays in the office
and is turned on during work hours. It should be reliable — if the host is
off, nobody can connect.

**Finding the host's address:** When the server starts, it prints a message
like this:

```
Other office computers can connect at:
    http://192.168.1.100:5000
```

That address (the numbers) is what office computers type into their browser.
**Write it down and keep it near the host computer.** If the host's address
changes (for example, after a router restart), start the server again and
check the new address.

**Firewall:** The first time the server runs in network mode, Windows may ask
"Allow this app through the firewall?" Click **Allow**. If you installed with
the host installer, this was handled during setup.

> ⚠️ **IMPORTANT:** This software is for your **office network only**.
> Never expose port 5000 to the internet (no port forwarding on your router,
> no public IP). Client data must stay inside the office.

---

## 19. Installing on the host vs. office computers

**Host computer (one time):**
1. Run `LawFirmHostSetup.exe` (from Garrett).
2. Follow the prompts. Check the box for "Allow office computers to connect"
   (opens the Windows Firewall for port 5000).
3. Optionally check "Start the server automatically when Windows starts" —
   recommended, so nobody has to remember to start it.
4. A "Law Firm Case Management" shortcut appears on the desktop and Start Menu.
   Double-click it to start the server. A black window opens showing the
   address other computers use — **leave this window open** while the office
   needs access. Closing it stops the server.

**Office computers / laptops (each one):**
- No software to install. Just run `client-setup.bat` (from Garrett).
- Type in the host computer's IP address when asked.
- A "Law Firm" icon appears on the desktop. Double-click it — the system
  opens in your browser.
- If the shortcut stops working, the host's IP address may have changed.
  Run `client-setup.bat` again with the new address (see Section 18).

---

## 20. What to do if office computers can't connect

Work through these in order:

1. **Is the host computer on, and is the server running?** Look for the black
   server window on the host. If it's closed, double-click the desktop shortcut
   to start it again.
2. **Is the IP address correct?** Compare the address in the browser with the
   address shown in the host's server window. If they don't match, update the
   shortcut (run `client-setup.bat` again).
3. **Are both computers on the same network?** Both must be on the office Wi-Fi
   (or plugged into the office network). A laptop on a phone hotspot will NOT
   connect.
4. **Firewall:** On the host, open Windows Settings → Privacy & Security →
   Windows Security → Firewall → Allow an app. Make sure the Law Firm Server
   (or Python, if running from source) is allowed on **Private** networks.
5. **Try the host itself:** On the host computer, open `http://localhost:5000`.
   If that works but other computers can't connect, it's a network/firewall
   issue (steps 2–4). If localhost doesn't work either, the server isn't
   running properly — see Section 8.
6. **Still stuck?** Call Garrett. Tell him: the host's IP address, what error
   the browser shows (take a photo), and whether localhost works on the host.

---

## 21. Single-computer mode (no network)

If you ever want the system to run on **one computer only** (no office
network access), start it with the `--local-only` flag:

```
python app.py --local-only
```

Or with the installed exe, create a shortcut and add `--local-only` after
the program path in the shortcut's Target field. In this mode, other
computers cannot connect even if they know the address.

## 22. Using the software on your phone

You can open the case management system on your phone when connected to the office WiFi.

**To open it:**
1. Make sure your phone is connected to the office WiFi (not cellular data).
2. Open your phone's web browser (Safari on iPhone, Chrome on Android).
3. Type the host computer's address in the address bar — the same address office computers use (for example: `http://192.168.1.100:5000`). The host computer shows this address when the server starts.
4. Log in with your usual username and password.

**To add it to your home screen (so it works like an app):**
- **iPhone:** Open the page in Safari, tap the Share button (square with arrow), then tap "Add to Home Screen."
- **Android:** Open the page in Chrome, tap the three-dot menu, then tap "Add to Home screen" or "Install app."

**What works on the phone:** Everything — dashboard, clients, cases, calendar, documents, billing. The layout adjusts to fit your screen. Tables become stacked cards you scroll through.

**What does NOT work on the phone:** Nothing is missing, but keep in mind:
- If you lose WiFi connection, you'll see an "offline" message. Your data is safe on the host computer — just reconnect to WiFi.
- The phone does not store any case data. Everything stays on the host computer in the office.

## 23. Phone troubleshooting

**"I can't reach the server from my phone":**
1. Check your phone is on the office WiFi — look for the WiFi symbol at the top of your screen. If you're on cellular (4G/5G/LTE), it won't work.
2. Make sure you typed the address exactly right, including `http://` at the start and `:5000` at the end.
3. Make sure the host computer is turned on and the server is running.
4. Some office WiFi networks block devices from talking to each other. If nothing works, ask Garrett — the WiFi router may need a setting changed ("client isolation" must be OFF).

**"The page looks too small / I have to pinch to zoom":**
- This shouldn't happen. If it does, make sure you're using Safari (iPhone) or Chrome (Android) — not an in-app browser from an email or text message link.
- Try removing the home screen icon and re-adding it following the steps above.

**"It says I'm offline but my WiFi is on":**
- Your phone may have connected to a different WiFi network (for example, a guest network). Check Settings → WiFi and make sure you're on the office network.
- Try closing the browser completely and reopening it.

## 24. Automatic software updates

**How it works:** The server checks for new versions by itself every 6 hours (it asks GitHub, nothing else). When a new version is out, the admin sees a yellow **"Update available"** banner at the top of every page, with a link to what's new.

**To install an update (admin only):**
1. Click **Review & Install** in the yellow banner (or go to the update page from the banner).
2. Read what's new. If it looks good, click **Download and Install**.
3. The server will:
   - **Make a backup first** — automatically, before anything else.
   - Download the new installer and check it's genuine (correct size, correct file type).
   - Install the update and restart itself. You'll be logged out for about a minute.
4. Log back in. The yellow banner will be gone, and the footer will show the new version number (for example: "Server v1.2.0").

**Your data is never touched by an update.** Clients, cases, documents, billing, and settings live in the `instance` folder, and the installer is built to never delete or modify that folder — not during updates, and not even during uninstall. If an update ever fails halfway, the old version keeps running and nothing is lost.

**"Server vX.X.X" in the footer:** Every page shows the server version at the bottom. Office computers don't need to update anything themselves — they just use the server. If the footer version changes, that means the host was updated. Nothing to do on your end.

**If the automatic update fails:**
1. Don't panic — your data is safe, and the old version is still running.
2. The server made a backup right before trying. You can find it on the Dashboard under backups, or in the backup folder.
3. To update manually: download the latest `LawFirmHostSetup.exe` from the Releases page (https://github.com/needhamgarrett95-ux/farhollow-lawfirm/releases), close the server, and run the installer yourself. It will upgrade in place without touching your data.
4. If the server won't start after a manual update either: restore from the pre-update backup (see section 13 on backups), then ask Garrett for help.

**If the update check itself isn't working** (it says it can't check, or never finds updates):
- The host computer needs internet access for the check. If the office computer is offline, the check just waits and tries again later — the software works fine without it.
- You can always check manually at the Releases page link above.

## 25. Printing invoices as PDF

Every invoice page has a **Print / PDF** button at the top. Clicking it downloads a professionally formatted PDF invoice with the firm's DGM logo, invoice details, line items, and totals — ready to email or print for the client.

**What's on the PDF:**
- DGM logo and "Law Office of Derek G. Medina" header
- Invoice number, issue date, due date, and status
- Bill-to block with the client's name, address, email, and phone
- Line items table: date, description, hours, rate, amount
- Total due, any notes, and payment terms in the footer

**Line-item dates:** When you add time entries to an invoice, their dates carry over automatically. For manual line items, you can enter a date when creating the invoice (optional — leave blank if it doesn't apply).

## 26. Managing users (admin only)

The software supports three kinds of accounts. Only an **Admin** can add or manage users — look for the **Users** tab at the top of the screen (it only appears for admins).

**The three roles:**

- **Admin** — full access to everything, including adding/removing users and installing software updates. There must always be at least one active admin.
- **Attorney** — can do everything except manage users. Sees clients, cases, documents, calendar, billing, and the audit log.
- **Staff** — for paralegals and assistants. Can view and edit clients, cases, documents, and the calendar, but **cannot** see billing or invoices, **cannot** delete any records, and **cannot** see the audit log. The menu simply won't show those items.

**To add a new user:**

1. Click **Users**, then **+ New user**.
2. Enter a username (lowercase, no spaces), their full name, a starting password (at least 8 characters), and pick their role.
3. Click **Save**. The new user must change their password the first time they log in.

**To change someone's role or name:** Click **Edit** next to their name, make the changes, and **Save**. Role changes take effect immediately — even if that person is currently logged in.

**If someone forgets their password:** Click **Reset password** next to their name. You'll get a one-time temporary password on screen — write it down or copy it, because it won't be shown again. Give it to them; they'll be forced to pick a new password when they log in.

**To remove someone's access:** Click **Deactivate**. They immediately can't log in anymore, but their name stays on the list (so old audit log entries still make sense). To bring them back, click **Reactivate**.

**Safety rules built into the software:**

- You cannot deactivate your own account.
- You cannot remove admin rights from yourself.
- You cannot deactivate or demote the last remaining admin — the software will refuse and tell you why.
- Deactivated users cannot log in, even with a correct password.

## 27. Trust accounting (IOLTA) — attorney/admin only

**What this is:** When a client gives you money to hold (a retainer, settlement funds, etc.), that money is NOT yours — it belongs to the client until you earn it. Washington's ethics rules (RPC 1.15A) are extremely strict about this. Mishandling client money is the #1 reason lawyers get disciplined. This part of the software helps you do it right.

**Only attorneys and admins can see the Trust tab.** Assistants and paralegals (the "staff" role) cannot see trust accounts at all.

**The three rules that matter most:**

1. **Never disburse before funds clear.** If a client writes you a $5,000 check, do NOT pay anything out of it until your bank confirms the check cleared. The software cannot check this for you — that's on you.
2. **Reconcile every account every month.** Compare your bank statement to what the software says. If they don't match, find out why before the month ends. This is not optional.
3. **Transactions are permanent.** Once you record a deposit or payment, it cannot be edited or deleted. If you make a mistake, you create a *reversing entry* (the software has a "Reverse" button for this) — the original stays, and a new entry cancels it out. This is how real accounting works.

**To set up a trust account:**

1. Click **Trust**, then **New trust account**.
2. Enter the account name (e.g. "IOLTA Checking"), the bank name, and the account number. The account number is stored encrypted.
3. Click **Create account**.

**To record a client deposit:**

1. Click **Trust**, open the account, then **Record transaction**.
2. Choose the client and **Deposit (money in)**.
3. Enter the amount, date, and a clear description (e.g. "Retainer per fee agreement dated 10/1/2026"). A description is required — the bar requires complete records.
4. Enter a check or reference number if you have one.
5. Read the confirmation prompt carefully — this entry is permanent. Click to save.

**To pay money out (disbursement):**

Same steps, but choose **Disbursement (money out)**. The software will **refuse** the payment if the client doesn't have enough money in their trust balance. This is a hard block, not a warning — you cannot overdraw a client's trust funds.

**To move money between clients:**

Choose **Transfer to another client**, pick the receiving client, and **check the confirmation box**. The software creates two linked entries (out of one client, into the other) so the paper trail is complete.

**To fix a mistake:**

Find the transaction on the account page and click **Reverse**. Enter what went wrong in the description. The software creates an offsetting entry. The original is never touched.

**Monthly reconciliation (do this every month):**

1. Click **Trust**, open the account, then **Reconcile**.
2. Look at your bank statement. Enter the **statement date** and the **ending balance** from the statement.
3. Click **Save reconciliation**.
4. If the statement matches what the software says: you're done. You'll see "Reconciliation complete."
5. If they DON'T match: the software will tell you the difference and mark it "unmatched." Find the discrepancy (outstanding checks, deposits in transit, data entry errors) before month-end. Do not ignore an unmatched reconciliation.

**Reports (for your records and any bar audit):**

- **Trial balance** (from the Trust page): every client's balance per account. The totals must equal the account balance.
- **Three-way reconciliation** (from the Trust page): the gold standard — bank statement balance = software balance = sum of all client ledgers. All three must agree. Print or save this monthly.
- **Client ledger** (click "Ledger" next to any client): every transaction for that client with a running balance. You can filter by date range.

**What NOT to do:**

- Do NOT disburse funds before they clear the bank.
- Do NOT skip monthly reconciliation.
- Do NOT try to edit or delete a trust transaction — use a reversing entry.
- Do NOT let staff access trust accounts (the software blocks this, but don't share your login either).
- Do NOT commingle: client money and firm money must never mix in the same account.

---

## 28. Document templates — attorney/admin only

Document templates let you generate common legal documents with client and case information filled in automatically.

**How to use a template:**

1. Click **Templates** in the top menu.
2. Pick the document you need (Petition for Dissolution, Parenting Plan, Child Support Worksheet, Declaration, or Cover Letter).
3. Choose the **client** at the top. Names, spouse, and children fill in automatically.
4. Optionally choose a **case**. If you pick a case, the finished PDF is saved to that case's documents automatically.
5. Fill in the remaining fields. Anything you don't know can be edited later.
6. Click **Preview** to review what the document will say.
7. Click **Generate PDF** to create the finished document. It downloads to your computer (and is saved to the case, if you picked one).

**Important things to know:**

- These are **starting drafts, not finished legal documents**. Always review every word before filing or sending anything.
- The **Child Support Worksheet is an estimate**. It uses a simplified version of the Washington support schedule. Always verify the numbers with the official state schedule before relying on them.
- Generated documents are saved under the case's **Documents** tab with version numbers, just like uploaded files. Generating the same template twice creates version 2, 3, and so on — nothing is overwritten.
- Only attorneys and admins can use templates. Staff accounts do not see the Templates menu.
- Every generated document is recorded in the audit log.

## 29. Deadline calculator

The deadline calculator figures out filing deadlines under Washington Superior Court rules. You give it a trigger date (like a hearing date), and it tells you every related deadline.

**How to use it:**

1. Click **Deadlines** in the top menu.
2. Pick the **trigger type**:
   - **Motion Hearing** — deadlines for filing motions, responses, and replies before a hearing (CR 6).
   - **Trial** — trial briefs, witness/exhibit lists, and discovery cutoff before trial.
   - **Service of Petition (in-state)** — the 20-day response deadline after serving someone in Washington.
   - **Service of Petition (out of state)** — the 60-day response deadline after out-of-state service.
3. Enter the **trigger date** (the hearing date, trial date, or date of service).
4. Optionally pick a **case** — this preselects it for the calendar step below.
5. Click **Calculate deadlines**.

**Reading the results:**

- Each deadline shows the **due date**, which rule it comes from, and how many days are left.
- **Red** means the deadline has already passed. **Yellow** means it's due within 3 days.
- "Court days" skip weekends and Washington court holidays. "Calendar days" count every day.

**Adding deadlines to the calendar (attorneys and admins only):**

1. After calculating, pick the **case** in the dropdown above the results.
2. Check the boxes next to the deadlines you want (or click **Add all**).
3. Click **Add selected to calendar**. Each deadline becomes a calendar event on the case, marked as a filing deadline.
4. To add just one, click the **Add** button on its row.

Staff accounts can use the calculator but cannot add deadlines to the calendar — they'll see a note saying to ask an attorney.

**Important things to know:**

- These calculations use **standard** Washington Superior Court rules. Your judge's scheduling order or a case-specific order can change them. **Always double-check before relying on a calculated deadline.**
- If a deadline looks wrong, don't use it — verify it by hand or ask the attorney. This tool does not replace legal judgment.
- Every deadline added to the calendar is recorded in the audit log.

## 30. Speed tips (v1.8.0 ease-of-use update)

The software now fills in a lot of things for you so you type less:

- **New case:** the case number is suggested automatically (like 2026-001, 2026-002). If you leave the title blank, it fills in "Smith — Divorce" from the client name and case type. The open date defaults to today.
- **New case from a client page:** click "+ New case for this client" on any client page and the client is already selected.
- **Case status:** change it right on the case page with the dropdown — no need to open the edit form.
- **Calendar events:** the date defaults to today.
- **Time entries:** tap 0.5 / 1.0 / 1.5 / 2.0 instead of typing hours. Your hourly rate is remembered from last time.
- **Invoices:** issue date defaults to today, due date to 30 days out. Type in the box above the client list to filter it.
- **Trust transactions:** the date defaults to today.
- **Client search:** start typing a name and matching clients appear as suggestions.

## 31. Clallam County court integration (v1.9.0)

The deadline calculator now knows Clallam County Superior Court's local calendar:

- **New deadline types** in the calculator dropdown:
  - *Clallam Co. Motion Hearing (Friday 9:00 AM)* — family law motions are only heard Fridays at 9 AM. If you enter a different day, the calculator warns you.
  - *Clallam Co. Child Support (1st/3rd Tue 9:00 AM)* — child support is only heard the 1st and 3rd Tuesdays. Other dates get a warning.
  - *Clallam Co. Ex Parte (daily 1:00 PM)* — includes the 11:00 AM same-day filing cutoff. Warns if you pick a weekend.
  - *LCR 2 — Response to Motion for Revision* — 10 days after service, per Clallam County LCR 2(c).
- **When you push a Clallam motion's deadlines to the calendar**, two extra reminders are added automatically:
  - *Bench copies due (by NOON)* the day before the hearing — Clallam requires paper bench copies by noon.
  - *Telephone confirmation of motion calendar* the day before — the court requires a confirmation call.
- **Court schedule monitor:** once a week, the software quietly checks the county's published Friday judge calendar. If it changed (different judge assigned, holiday added), you'll see a yellow alert at the top of the dashboard: "Clallam County court schedule may have changed — review here." Click through to the county calendars page, then Dismiss the alert. Nothing in your deadlines changes automatically — you decide what to do.
- **AI disclosure on documents:** Clallam County requires AI-use disclosure in filings (effective Sept 2025). When generating a document from a template, check the box "This document was prepared with AI assistance" and a disclosure footnote is added to the PDF. When in doubt, check with the attorney — the exact required wording should be verified against the current local rule.

## 32. What's new in v2.0.0 — new dashboard, dark mode, custom icons

This is a major visual update. Everything still works the same way — it just looks better and is easier to use.

**New dashboard (home page):**
- Instead of long lists, the home page now shows **cards** with charts and visual summaries: upcoming deadlines on a timeline, trust balance as a bar chart, caseload as a donut chart, today's schedule, recent clients, and quick-action buttons.
- Click **"Edit layout"** (top-right) to customize your dashboard: show/hide any card, drag them into your preferred order with the up/down arrows. Your layout is saved — it's per-user, so each person in the office can have their own arrangement.
- **"Reset to default"** puts everything back the way it was.

**Dark mode:**
- Click your initials (top-right) → **Dark mode** to switch to a dark theme that's easier on the eyes. Click again to switch back to Light mode.
- Your choice is remembered — it stays the way you left it next time you log in.

**New icons:** All the little pictures throughout the app (menu, buttons, warnings) are now clean matching icons instead of emojis.

**Notification badge:** The Deadlines menu item now shows a red count badge when you have deadlines due within 7 days (including overdue ones). It updates automatically.

**Login screen:** The sign-in page has a fresh look matching the new dashboard. Your username and password work exactly the same.

## 33. Bookkeeping — Accounting tab (admin/accountant)

The Accounting tab tracks the firm's own money (separate from client trust funds).

**Chart of Accounts** — pre-loaded with standard law-firm categories (income, expenses,
assets, liabilities, equity). You can add your own accounts or deactivate ones you don't use.

**Recording transactions** — date, account, amount, description. Mark each as income or
expense. When you mark an invoice as "paid," the income is recorded automatically.

**Reports** — Profit & Loss, Balance Sheet, and General Ledger, all exportable to CSV
for your CPA.

**Reconciliation** — like trust reconciliation: enter your bank statement balance each
month and confirm it matches the books.

## 34. Payroll (admin/accountant)

**Setup (do this first):**
1. Go to Accounting → Tax Settings. **Verify every rate** against current IRS Publication 15-T,
   WA Employment Security Department, and WA Labor & Industries publications. Rates change
   every year — this is the most important step.
2. Add employees: name, hourly wage or annual salary, pay frequency, filing status.

**Timeclock** — employees click Clock In / Clock Out. You can also enter hours manually.
Overtime (over 40 hours/week) is calculated at 1.5x automatically for hourly staff.

**Running payroll:**
1. Go to Accounting → Payroll, enter the pay period and pay date.
2. Click Preview — check every number carefully.
3. Click Generate — this creates paychecks, books the wage/tax expenses, and records
   payroll tax liabilities.

**Paystubs** — click any paycheck to download a printable PDF paystub.

**Washington notes:** WA has no state income tax. Deductions include federal income tax,
Social Security, Medicare, WA Paid Family & Medical Leave, and WA Cares. Unemployment
insurance and workers' comp are employer-paid (tracked as employer costs, not deducted
from paychecks).

**IMPORTANT:** This tool calculates payroll using the rates you enter in Tax Settings.
It does not replace a CPA. Verify rates annually before running payroll.

## 35. User permissions (admin only)

Roles (Admin, Attorney, Accountant, Staff) are starting presets. On the user edit page,
you can customize individual permissions with checkboxes — for example, letting an
assistant print paystubs while they're covering for a sick accountant.

**Safety rules:**
- Only users with "Manage users" permission can edit permissions.
- You cannot remove your own "Manage users" permission.
- The system prevents removing the last user with "Manage users" permission.

**"Reset to role defaults"** restores the checkboxes to the selected role's preset.
Changes take effect immediately — no re-login needed.

## 36. Integrations — email & calendar sync (v2.2.0, admin only)

The app can connect to the firm's Gmail and/or Outlook account, plus Google
Calendar. Once connected:

- **Email sync:** every 15 minutes the app pulls recent messages. They are
  automatically attached to cases — matched by the client's email address,
  or by a case number (like 2026-001) in the subject line. Anything the app
  can't match can be linked by hand from the case's Emails tab.
- **Send email from a case:** the "Send email" button on any case sends
  through the connected account and logs the message to that case.
- **Calendar sync:** upcoming deadlines and hearings are pushed to Google
  Calendar (with the case number in the title), so they show up on your
  phone. You can also turn on importing Google events back into the app.

### One-time setup (per provider)

1. **Get OAuth credentials:**
   - *Gmail / Google Calendar:* go to console.cloud.google.com, create a
     project, create an OAuth client (type: Web application), and add this
     exact redirect URI: `http://localhost:5000/integrations`. Enable the
     Gmail API (for Gmail) and/or the Google Calendar API.
   - *Outlook:* go to portal.azure.com, register an application, add a Web
     redirect URI of `http://localhost:5000/integrations`, and grant the
     `Mail.Read` and `Mail.Send` delegated permissions.
2. On the **Integrations** page (admin only), paste the client ID and client
   secret, click Save, then click **Connect**.
3. **Important:** the Connect step must be done from the server computer
   itself — open `http://localhost:5000/integrations` in a browser on that
   machine. Google and Microsoft only allow `http://localhost` addresses
   without HTTPS.

### If a connection breaks

The Integrations page will show an amber "Needs reauth" badge with a
**Reconnect** button. Click it and approve access again — nothing is lost;
synced emails stay in their cases.

### Disconnecting

Disconnecting removes the connection. Synced emails stay attached to their
cases. Calendar links are removed (pushed Google events stay on Google but
won't update further).

## 37. Login sessions (v2.2.1 security update)

**How logins work now:**
- When you close your browser completely, you are logged out. Opening the app again asks you to log in.
- When the server restarts (including after a software update), **everyone** is logged out and must log back in. This is intentional — it keeps client data safe.
- If you don't touch the app for 30 minutes, you are logged out automatically (inactivity timeout).

**This is normal — don't worry if:**
- You just updated and it asks you to log in again. That's supposed to happen.
- You closed the browser and have to log in again. That's supposed to happen.

**Your data is NOT affected.** Logging out never deletes or changes any clients, cases, documents, or settings. It only ends your login session.

## 38. Timeclock (v2.3.0)

**The Timeclock is now its own section** — it has its own tab in the top bar (alarm clock icon), separate from Accounting. Payroll stays under Accounting.

**Clocking in and out:**
- Open the Timeclock tab (or use the Timeclock widget on your dashboard for one-click access).
- Click **Clock in** when you start work, **Clock out** when you finish. That's it.
- The dashboard widget shows your current status at a glance.

**Who sees what:**
- **Regular staff:** you only see YOUR OWN time entries. You cannot see anyone else's hours.
- **Admins and attorneys:** see everyone's entries, plus a "Who's at work now" view.
- If your login isn't linked to an employee record, ask an admin to link it on the Employees page (Accounting → Employees).

**For admins — permissions:**
- `use_timeclock` — lets someone clock in/out (all roles have this by default).
- `view_all_timeclocks` — lets someone see everyone's entries (admins and attorneys only by default). Grant it in Users → edit user → Permissions if needed.

## 39. Navigation dropdowns + UI permission audit (v2.3.2)

**Navigation:** The top bar now uses grouped dropdown menus instead of 13 individual tabs:
- **Dashboard** — standalone (no dropdown)
- **Practice** — Clients, Cases, Calendar, Deadlines
- **Documents** — Templates
- **Financial** — Billing, Trust, Accounting
- **Team** — Timeclock, Users
- **System** — Audit Log, Integrations

Each dropdown only shows items you have permission for. If you have zero items in a group, the whole dropdown is hidden. Click the group name to open/close; click an item to go there. Press Escape to close.

**UI permission audit:** Every button and link in the app now checks your permissions before showing. If you can't do something, you won't see the button for it — no more "Forbidden" pages from clicking visible buttons.

## 40. UI polish + timeclock correction requests (v2.4.0)

**Premium UI overhaul.** The whole app now uses one consistent design system:
- **Form fields** — every input, dropdown, date picker, and text area is themed to the app (dark slate fields in dark mode, warm gray in light mode) with a gold focus ring. No more stark white boxes.
- **Segmented pills** — short choices (pay type, pay frequency, filing status, user role) now use tap-friendly pill selectors instead of dropdowns.
- **Tables** — hover highlighting, quieter header text, consistent padding.
- **Empty states** — every list page shows a designed card with an icon, a headline, and a "first action" button instead of plain text.
- **Page headers** — every page leads with an icon + title, and card headers match.

**Timeclock redesign.** The Timeclock page now opens with a large live clock card: current time, today's date, your clocked-in status (with a soft pulsing green dot), and one big Clock In / Clock Out button. Below it:
- **Who's at work** — avatar chips with green dots showing everyone currently clocked in.
- **Team** — one card per employee with their status and a clock in/out button (admin/attorney).
- **Recent entries** — a timeline instead of a raw table.
- **Manual entry** — collapsed by default; it's a secondary tool now.

**Correction requests (new).** Staff who can't enter time manually can fix a bad punch properly:
1. On the Timeclock page, use **Request a correction** — pick the date, what's wrong (missed clock-in / missed clock-out / wrong time), the correct time(s), and a short reason.
2. The request lands in the admin/attorney review queue on the Timeclock page, and the **Team** menu shows a badge with the number waiting.
3. Reviewer can **Approve** (the correction is applied to the time entry right then) or **Deny** (a reason is required, and the employee sees it).
4. The employee's own requests are listed on their Timeclock page with their status (pending / approved / denied).
5. Every request, approval, and denial is written to the Audit Log.

## 41. Timeclock day view + quick notes (v2.4.1)

**Day view:** On the Timeclock page, the **Day view** tab shows every punch for one date. Flip days with the arrow buttons, pick a date from the calendar, or jump back with **Today**. Each employee gets a card with their punches, total hours for the day, and a visual timeline bar (6 AM–8 PM) showing when they were clocked in. A summary footer shows total hours across everyone and who's currently clocked in. Staff/accountants only ever see their own day; admin/attorney see everyone.

**Print:** The **Print** button on the day view opens a clean, letterheaded daily time sheet (DGM logo, firm name and address, date) in a new tab — black on white, signature lines at the bottom, ready to file or hand to an employee. Staff printing see only their own punches.

**Quick notes:** Client, case, and invoice pages now have a **Notes** section — click **Add note**, type, save. Notes appear in a timeline with the author and timestamp. Notes are append-only (no editing); only an admin can delete one (with a confirmation), and every add/delete goes to the Audit Log. Individual timeclock punches can also get notes, right from the day view — click the note chip under any punch.

**Admin retention override (v2.4.1):** Financial records (invoices, time entries) normally cannot be deleted until 7 years after their date — that's RPC 1.15A/B, and the app blocks it. If a record was created *by mistake* (a duplicate invoice, a time entry on the wrong case), the **admin account only** can override the lock. On a locked record, the admin sees a red **Admin retention override** box where the delete button would be. To use it: type a clear reason ("duplicate invoice entered in error") and type the word **DELETE**, then click the button. Non-admins never see any delete option on locked records. Every override deletion is written to the **Audit Log** with a full copy of the deleted record, who deleted it, and the reason — so there is always a paper trail. Use this only for genuine errors.

## 42. Confirmation dialogs, designed error pages, employee day pages (v2.4.3)

**"Generate paychecks" fix:** The payroll page's **Generate paychecks** button used to show its confirmation, then silently do nothing. The cause was in the app's shared confirmation dialogs: after you confirmed, the form was submitted without the button's information, so the server never knew you meant "generate". Fixed in the shared helper — every confirmation dialog in the app (delete, deactivate, reset password, update install, generate) now submits exactly what the clicked button meant. If you ever confirm a dialog and nothing seems to happen, report it immediately — that's a bug, not a feature.

**Designed error pages:** If something goes wrong on the server, you now see a clean error page with a **Back to dashboard** button instead of a bare technical error screen. Access-denied pages (403) look the same way. Your data is never harmed by an error page — it's just a notification.

**Employee day pages:** On the Timeclock **Day view**, admin/attorney can now click any employee's name to open **that employee's own day page** — same timeline bar, punches, and notes, with an employee picker at the top to switch between people. Date navigation works the same (arrows, date picker, Today), and the **Print** button prints just that employee's day sheet. Staff/accountants can only ever open their *own* day — if someone guesses the URL for another employee's page, they're blocked (this is enforced by the server, not just by hiding the link).

## 43. Deleting a paid invoice (v2.4.4)

When an invoice is marked paid, the accounting system automatically creates
an income record linked to that invoice. In earlier versions, deleting the
invoice (including the admin retention override) failed with an error page
because that link blocked the deletion. Fixed: deleting an invoice now
first unlinks the income record — the income record itself is kept (it
represents money that was actually received), only the link to the deleted
invoice is removed. The audit log still records the deletion as before.

## 44. Full audit sweep — many small fixes (v2.4.5)

A full system-by-system audit was done in this version and every bug found
was fixed. The most important items:

**Trust corrections (reversals) are now safe.** Reversing a trust entry
used to let you pick a different account, client, or amount — a typo could
move money between clients. Now the reversal form is locked to the original
entry: same account, same client, exact same amount. Reversing the same
entry twice is refused, and a reversal can't overdraw a client.

**Deleting operating transactions from paid invoices.** An income record
that was created automatically from a paid invoice previously could never be
deleted on its own. Admins now get an "Override" toggle on those rows: with
a written reason and typing DELETE, the admin-only override (with the usual
full audit snapshot) removes it. Non-admins still can't touch it.

**Payroll fixes.** Three real math/process bugs: (1) Social Security tax on
a half-cent amount was rounding down one cent — it now rounds properly;
(2) running payroll twice for the same period created duplicate paychecks —
the second run is now refused; (3) the employer's share of WA PFML was never
added to employer costs even when the tax setting said the firm pays it —
now it is. Salaried employees' L&I now uses their actual timeclock hours
(40 hours/week assumed only when no hours exist).

**Blocked deletes no longer show error pages.** Deleting a client or case
that still has invoices, trust entries, or accounting transactions now shows
a clear message listing what must be cleared first. Deleting a case also
removes its document files and notes; deleting a client or case that doesn't
exist is now a proper "not found" page instead of a fake success.

**Form validation.** Empty client names are refused; creating a case, event,
trust transaction, accounting transaction, employee, or timeclock entry with
a deleted/nonexistent client, case, account, or employee is now refused with
a message instead of an error page. Time entries reject zero, negative, or
nonsense hours and negative rates. Invoice line amounts must be positive
numbers. A one-cent rounding error on tiny time entries (a 0.02-hour line at
$275.25 came out as 550 cents instead of 551) is fixed — line amounts are
stored exactly. Tax-rate settings reject nonsense (typing a word where a
number goes). Case creation now saves the closing date.

**Filters that didn't filter.** The date filter on the P&L, General ledger,
and CSV export, and the account filter on the operating transactions list,
looked like they worked but were ignored — the wrong parameter names were
sent. They filter correctly now.

**Links that led to "access denied."** The "Open" link next to cases on the
client page no longer shows for roles that can't open cases; the
"Integrations page" link on the email compose page no longer shows for
roles that can't open integrations.

**Smaller items.** Reconnection warnings on the Integrations page now
actually display when a Google/Microsoft login expires. Uploading a file
that's too large now shows the app's designed error page. Success and
danger banners in light and dark mode are properly themed; light-mode text
contrast improved; the "Saved" pill in dark mode is themed; the download
icon renders everywhere; empty states added for the trust reports.
