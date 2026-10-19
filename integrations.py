"""
Email + calendar integrations for the law firm app.

Providers:
  - gmail:    Google Gmail (read + send) via Gmail REST API
  - outlook:  Microsoft Outlook (read + send) via Microsoft Graph
  - gcal:     Google Calendar (read + write) via Google Calendar API v3

OAuth 2.0 authorization-code flow is implemented with plain urllib (no extra
dependencies). Tokens are encrypted at rest with the app's Fernet data key.

IMPORTANT — redirect URI constraint: Google and Microsoft only accept
https:// redirect URIs, EXCEPT http://localhost (any port). This server is
LAN-only, so the OAuth callback MUST be completed from a browser on the
server machine itself via http://localhost:5000. The Integrations page
shows this guidance when a provider is not yet connected.

Background sync runs every 15 minutes (see start_integration_scheduler()
in app.py), syncing all connected providers. Failures are recorded on the
integration row and surface as an amber "reconnect" state in the UI —
never as an error dump.
"""

import base64
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from crypto import encrypt_value, decrypt_value

# ----------------------------------------------------------------------------
# Provider definitions
# ----------------------------------------------------------------------------

PROVIDERS = {
    "gmail": {
        "label": "Gmail",
        "kind": "email",
        "icon": "mail",
        "description": "Sync firm email. Messages auto-attach to cases by "
                       "client address or case number in the subject.",
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "scopes": [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
        ],
        "extra_auth_params": {"access_type": "offline", "prompt": "consent"},
    },
    "outlook": {
        "label": "Outlook",
        "kind": "email",
        "icon": "mail",
        "description": "Sync firm email via Microsoft 365. Same case-matching "
                       "as Gmail.",
        "auth_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "scopes": ["Mail.Read", "Mail.Send", "offline_access"],
        "extra_auth_params": {},
    },
    "gcal": {
        "label": "Google Calendar",
        "kind": "calendar",
        "icon": "calendar",
        "description": "Two-way sync. Deadlines and hearings appear on your "
                       "phone's calendar; Google events can import back.",
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "scopes": ["https://www.googleapis.com/auth/calendar"],
        "extra_auth_params": {"access_type": "offline", "prompt": "consent"},
    },
}

# Case numbers look like 2026-001. Used to match emails by subject line.
CASE_NUMBER_RE = re.compile(r"\b(\d{4})-(\d{3,})\b")


def redirect_uri(port=5000):
    """OAuth callback. MUST be http://localhost (see module docstring)."""
    return f"http://localhost:{port}/integrations/oauth/callback"


# ----------------------------------------------------------------------------
# Low-level HTTP helpers (urllib, JSON in/out)
# ----------------------------------------------------------------------------

def _http_json(method, url, headers=None, data=None, timeout=25):
    """JSON request helper. Returns (status, parsed_body)."""
    body = None
    req_headers = {"Accept": "application/json"}
    if headers:
        req_headers.update(headers)
    if data is not None:
        body = urllib.parse.urlencode(data).encode("utf-8")
        req_headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, headers=req_headers,
                                 method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            try:
                return resp.status, json.loads(raw) if raw else {}
            except ValueError:
                return resp.status, {"_raw": raw}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw) if raw else {}
        except ValueError:
            return e.code, {"error": raw[:500]}
    except Exception as e:  # network down, DNS, timeout…
        return 0, {"error": f"network error: {e}"}


def _api_json(method, url, access_token, payload=None, timeout=25):
    """Authenticated JSON API call (Bearer token)."""
    body = None
    headers = {"Authorization": f"Bearer {access_token}",
               "Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers,
                                 method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            try:
                return resp.status, json.loads(raw) if raw else {}
            except ValueError:
                return resp.status, {"_raw": raw}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw) if raw else {}
        except ValueError:
            return e.code, {"error": raw[:500]}
    except Exception as e:
        return 0, {"error": f"network error: {e}"}


# ----------------------------------------------------------------------------
# OAuth flow
# ----------------------------------------------------------------------------

def build_authorize_url(provider, client_id, state, port=5000):
    """URL the admin visits to grant access."""
    cfg = PROVIDERS[provider]
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri(port),
        "response_type": "code",
        "scope": " ".join(cfg["scopes"]),
        "state": state,
    }
    params.update(cfg.get("extra_auth_params", {}))
    return cfg["auth_url"] + "?" + urllib.parse.urlencode(params)


def exchange_code(provider, client_id, client_secret, code, port=5000):
    """Trade the authorization code for access + refresh tokens."""
    cfg = PROVIDERS[provider]
    status, data = _http_json("POST", cfg["token_url"], data={
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri(port),
    })
    if status != 200 or "access_token" not in data:
        err = data.get("error_description") or data.get("error") or "unknown"
        raise IntegrationError(f"Token exchange failed: {err}")
    return data  # access_token, refresh_token, expires_in


def refresh_access_token(provider, client_id, client_secret, refresh_token):
    """Use the refresh token to get a new access token."""
    cfg = PROVIDERS[provider]
    status, data = _http_json("POST", cfg["token_url"], data={
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    })
    if status != 200 or "access_token" not in data:
        err = data.get("error_description") or data.get("error") or "unknown"
        raise IntegrationAuthError(f"Token refresh failed: {err}")
    return data


class IntegrationError(Exception):
    """General integration failure (network, API error, config)."""


class IntegrationAuthError(IntegrationError):
    """Auth is broken — the admin must reconnect (re-run OAuth)."""


# ----------------------------------------------------------------------------
# Gmail API
# ----------------------------------------------------------------------------

_GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


def _gmail_headers(access_token, msg):
    """Extract From/To/Subject/Date from a Gmail message resource."""
    headers = {h["name"].lower(): h.get("value", "")
               for h in msg.get("payload", {}).get("headers", [])}
    return {
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "subject": headers.get("subject", "(no subject)"),
        "date": headers.get("date", ""),
    }


def gmail_list_messages(access_token, query="", max_results=25,
                        page_token=None):
    params = {"q": query, "maxResults": max_results}
    if page_token:
        params["pageToken"] = page_token
    url = _GMAIL_BASE + "/messages?" + urllib.parse.urlencode(params)
    status, data = _api_json("GET", url, access_token)
    if status == 401:
        raise IntegrationAuthError("Gmail access token rejected")
    if status != 200:
        raise IntegrationError(f"Gmail list failed: {data}")
    return data


def gmail_get_message(access_token, msg_id):
    url = f"{_GMAIL_BASE}/messages/{msg_id}?format=full"
    status, data = _api_json("GET", url, access_token)
    if status == 401:
        raise IntegrationAuthError("Gmail access token rejected")
    if status != 200:
        raise IntegrationError(f"Gmail fetch failed: {data}")
    meta = _gmail_headers(access_token, data)
    # Snippet + best-effort plain-text body
    snippet = data.get("snippet", "")
    body = _gmail_extract_body(data.get("payload", {}))
    return {
        "provider": "gmail",
        "external_id": data.get("id", ""),
        "thread_id": data.get("threadId", ""),
        "subject": meta["subject"],
        "from_addr": _strip_name(meta["from"]),
        "to_addr": _strip_name(meta["to"]),
        "sent_at": meta["date"],
        "snippet": snippet,
        "body": body,
    }


def _gmail_extract_body(payload):
    """Walk MIME parts for the first text/plain body (base64url)."""
    mime = payload.get("mimeType", "")
    data_b64 = (payload.get("body") or {}).get("data", "")
    if mime.startswith("text/plain") and data_b64:
        try:
            return base64.urlsafe_b64decode(data_b64 + "==").decode(
                "utf-8", "replace")[:8000]
        except Exception:
            return ""
    for part in payload.get("parts", []) or []:
        found = _gmail_extract_body(part)
        if found:
            return found
    return ""


def gmail_send(access_token, to_addr, subject, body_text, from_name=""):
    raw = (f"To: {to_addr}\r\n"
           f"Subject: {subject}\r\n"
           "Content-Type: text/plain; charset=utf-8\r\n\r\n" + body_text)
    encoded = base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")
    status, data = _api_json("POST", _GMAIL_BASE + "/messages/send",
                             access_token, {"raw": encoded})
    if status == 401:
        raise IntegrationAuthError("Gmail access token rejected")
    if status not in (200, 201):
        raise IntegrationError(f"Gmail send failed: {data}")
    return data.get("id", "")


# ----------------------------------------------------------------------------
# Microsoft Graph (Outlook)
# ----------------------------------------------------------------------------

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def graph_list_messages(access_token, max_results=25, skip=0):
    params = {
        "$top": max_results,
        "$skip": skip,
        "$orderby": "receivedDateTime desc",
        "$select": "id,conversationId,subject,from,toRecipients,"
                   "receivedDateTime,sentDateTime,bodyPreview,body",
    }
    url = _GRAPH_BASE + "/me/messages?" + urllib.parse.urlencode(params)
    status, data = _api_json("GET", url, access_token)
    if status == 401:
        raise IntegrationAuthError("Graph access token rejected")
    if status != 200:
        raise IntegrationError(f"Graph list failed: {data}")
    return data


def _graph_addr(obj):
    rec = (obj or {}).get("emailAddress", {})
    return rec.get("address", "")


def graph_normalize(msg):
    to_list = ", ".join(_graph_addr(r) for r in msg.get("toRecipients", []))
    body = (msg.get("body") or {}).get("content", "")[:8000]
    return {
        "provider": "outlook",
        "external_id": msg.get("id", ""),
        "thread_id": msg.get("conversationId", ""),
        "subject": msg.get("subject") or "(no subject)",
        "from_addr": _graph_addr(msg.get("from")),
        "to_addr": to_list,
        "sent_at": msg.get("receivedDateTime") or msg.get("sentDateTime") or "",
        "snippet": msg.get("bodyPreview", "")[:300],
        "body": body,
    }


def graph_send(access_token, to_addr, subject, body_text):
    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": body_text},
            "toRecipients": [{"emailAddress": {"address": to_addr}}],
        },
        "saveToSentItems": True,
    }
    status, data = _api_json("POST", _GRAPH_BASE + "/me/sendMail",
                             access_token, payload)
    if status == 401:
        raise IntegrationAuthError("Graph access token rejected")
    if status not in (200, 201, 202):
        raise IntegrationError(f"Graph send failed: {data}")
    return True


# ----------------------------------------------------------------------------
# Google Calendar API
# ----------------------------------------------------------------------------

_GCAL_BASE = "https://www.googleapis.com/calendar/v3/calendars/primary/events"


def gcal_list_events(access_token, time_min=None, time_max=None,
                     max_results=50, page_token=None):
    params = {"maxResults": max_results, "singleEvents": "true",
              "orderBy": "startTime"}
    if time_min:
        params["timeMin"] = time_min
    if time_max:
        params["timeMax"] = time_max
    if page_token:
        params["pageToken"] = page_token
    url = _GCAL_BASE + "?" + urllib.parse.urlencode(params)
    status, data = _api_json("GET", url, access_token)
    if status == 401:
        raise IntegrationAuthError("Calendar access token rejected")
    if status != 200:
        raise IntegrationError(f"Calendar list failed: {data}")
    return data


def gcal_normalize(item):
    start = (item.get("start") or {})
    return {
        "external_id": item.get("id", ""),
        "title": item.get("summary") or "(no title)",
        "description": item.get("description") or "",
        "start": start.get("dateTime") or start.get("date") or "",
        "end": ((item.get("end") or {}).get("dateTime")
                or (item.get("end") or {}).get("date") or ""),
        "location": item.get("location") or "",
        "app_event_id": ((item.get("extendedProperties") or {})
                         .get("private") or {}).get("lawfirm_event_id", ""),
    }


def gcal_insert_event(access_token, title, start_dt, end_dt=None,
                      description="", app_event_id=None):
    """Create a Google Calendar event. start_dt/end_dt are ISO strings."""
    payload = {
        "summary": title,
        "description": description,
        "start": {"dateTime": start_dt},
        "end": {"dateTime": end_dt or start_dt},
    }
    if app_event_id:
        payload["extendedProperties"] = {
            "private": {"lawfirm_event_id": str(app_event_id)}}
    status, data = _api_json("POST", _GCAL_BASE, access_token, payload)
    if status == 401:
        raise IntegrationAuthError("Calendar access token rejected")
    if status not in (200, 201):
        raise IntegrationError(f"Calendar insert failed: {data}")
    return data.get("id", "")


def gcal_update_event(access_token, google_event_id, title, start_dt,
                      end_dt=None, description=""):
    payload = {
        "summary": title,
        "description": description,
        "start": {"dateTime": start_dt},
        "end": {"dateTime": end_dt or start_dt},
    }
    status, data = _api_json("PUT", f"{_GCAL_BASE}/{google_event_id}",
                             access_token, payload)
    if status == 401:
        raise IntegrationAuthError("Calendar access token rejected")
    if status != 200:
        raise IntegrationError(f"Calendar update failed: {data}")
    return True


def gcal_delete_event(access_token, google_event_id):
    status, data = _api_json("DELETE", f"{_GCAL_BASE}/{google_event_id}",
                             access_token)
    if status == 401:
        raise IntegrationAuthError("Calendar access token rejected")
    if status not in (200, 204):
        raise IntegrationError(f"Calendar delete failed: {data}")
    return True


# ----------------------------------------------------------------------------
# Email <-> case matching
# ----------------------------------------------------------------------------

def _strip_name(addr):
    """'Jane Doe <jane@x.com>' -> 'jane@x.com'."""
    m = re.search(r"<([^<>]+)>", addr or "")
    if m:
        return m.group(1).strip().lower()
    return (addr or "").strip().lower()


def normalize_email(addr):
    return _strip_name(addr)


def match_email_to_cases(db, from_addr, to_addrs, subject):
    """Return a list of case ids this email likely belongs to.

    Matches by (1) client email address on any party field, then
    (2) case number in the subject line. De-duplicated, active first.
    """
    matched = []

    # 1) Client email -> their cases
    addrs = {normalize_email(from_addr)}
    for a in (to_addrs or "").split(","):
        if a.strip():
            addrs.add(normalize_email(a))
    addrs.discard("")
    if addrs:
        placeholders = ",".join("?" for _ in addrs)
        rows = db.execute(
            f"SELECT DISTINCT c.id, c.status FROM cases c"
            f" JOIN clients cl ON c.client_id = cl.id"
            f" WHERE LOWER(cl.email) IN ({placeholders})",
            tuple(addrs),
        ).fetchall()
        matched.extend(r["id"] for r in rows)

    # 2) Case number in subject, e.g. "Re: 2026-001"
    for m in CASE_NUMBER_RE.finditer(subject or ""):
        number = f"{m.group(1)}-{m.group(2)}"
        row = db.execute(
            "SELECT id FROM cases WHERE case_number = ?", (number,)
        ).fetchone()
        if row and row["id"] not in matched:
            matched.append(row["id"])

    # Active cases first for deterministic ordering
    if matched:
        placeholders = ",".join("?" for _ in matched)
        order = {r["id"]: i for i, r in enumerate(db.execute(
            f"SELECT id FROM cases WHERE id IN ({placeholders})"
            f" ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END, id",
            tuple(matched)).fetchall())}
        matched.sort(key=lambda cid: order.get(cid, 999))
    return matched


# ----------------------------------------------------------------------------
# Token storage helpers (encrypted at rest)
# ----------------------------------------------------------------------------

def pack_tokens(access_token, refresh_token, expires_in):
    return encrypt_value(json.dumps({
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": int(time.time()) + int(expires_in or 3600),
    }))


def unpack_tokens(packed):
    try:
        return json.loads(decrypt_value(packed) or "{}")
    except (ValueError, TypeError):
        return {}


def tokens_expired(tokens, leeway=120):
    return int(tokens.get("expires_at", 0)) <= int(time.time()) + leeway


def now_iso():
    return datetime.now(timezone.utc).isoformat()
