"""
Field-level encryption for sensitive client data (RCW 19.255.010 / RPC 1.6).

Sensitive fields (SSNs, dates of birth) are encrypted with Fernet
(AES-128-CBC + HMAC) before being stored in SQLite. The data key lives in
instance/data.key and is generated once on first run.

Why this matters: under RCW 19.255.010, a breach of *encrypted* personal
information may not trigger the 30-day notification duty. Encryption at rest
is a legal shield, not just best practice.

WARNING: If data.key is lost, encrypted fields CANNOT be recovered.
Back it up alongside the database (see MAINTENANCE.md).
"""
import os

from cryptography.fernet import Fernet, InvalidToken

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KEY_PATH = os.path.join(BASE_DIR, "instance", "data.key")

_fernet = None


def _load_or_create_key():
    if os.path.exists(KEY_PATH):
        with open(KEY_PATH, "rb") as f:
            return f.read().strip()
    key = Fernet.generate_key()
    fd = os.open(KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(key)
    except Exception:
        os.close(fd)
        raise
    return key


def _get_fernet():
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_load_or_create_key())
    return _fernet


def encrypt_value(plaintext):
    """Encrypt a string for storage. Empty/None stays empty."""
    if plaintext is None or plaintext == "":
        return ""
    if not isinstance(plaintext, str):
        plaintext = str(plaintext)
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_value(ciphertext):
    """Decrypt a stored value. Empty/None stays empty.

    If the value is not valid ciphertext (e.g. legacy plaintext from before
    encryption was enabled), it is returned as-is so the migration step in
    app.init_db() can convert it. All current writes go through encrypt_value.

    Non-string values are coerced first (v2.11.0): a column declared
    INTEGER can hand back a raw int for legacy rows, and .encode() on it
    crashed the accounting pages with AttributeError instead of falling
    back to the plaintext path this function promises.
    """
    if ciphertext is None or ciphertext == "":
        return ""
    if not isinstance(ciphertext, str):
        ciphertext = str(ciphertext)
    try:
        return _get_fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ciphertext


def looks_encrypted(value):
    """Heuristic: Fernet tokens are base64 starting with 'gAAAAA'."""
    return isinstance(value, str) and value.startswith("gAAAAA")
