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
