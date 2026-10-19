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
