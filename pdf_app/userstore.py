"""Persistent user store for the PDF App.

Users are stored in a JSON file (default: ./data/users.json) so accounts can be
created and passwords reset at runtime, unlike the read-only secrets.toml.

Passwords are salted PBKDF2-SHA256 hashes; MFA uses TOTP (authenticator app).
"""
import hashlib
import hmac
import json
import os
import secrets as _secrets
from pathlib import Path

import pyotp

DATA_DIR = Path(os.environ.get("PDF_APP_DATA_DIR", "data"))
USERS_FILE = DATA_DIR / "users.json"

PBKDF2_ITERATIONS = 260000
ISSUER = "PDF App"


def hash_password(password, salt=None, iterations=PBKDF2_ITERATIONS):
    """Return a salted PBKDF2-SHA256 hash: pbkdf2_sha256$iters$salt$digest."""
    if salt is None:
        salt = _secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${dk.hex()}"


def verify_password(password, stored):
    """Verify a password against a stored pbkdf2_sha256$iters$salt$digest string."""
    try:
        algo, iterations, salt, digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations))
        return hmac.compare_digest(dk.hex(), digest)
    except Exception:
        return False


def verify_totp(secret, code):
    """Verify a 6-digit TOTP code against a base32 secret."""
    if not secret or not code:
        return False
    try:
        return pyotp.TOTP(secret).verify(code.strip(), valid_window=1)
    except Exception:
        return False


def totp_uri(username, secret):
    """Build an otpauth:// URI for enrolling an authenticator app."""
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=ISSUER)


def load_users():
    """Load the users dict from the JSON store (empty dict if none)."""
    if not USERS_FILE.exists():
        return {}
    try:
        data = json.loads(USERS_FILE.read_text(encoding="utf-8"))
        return data.get("users", {})
    except Exception:
        return {}


def save_users(users):
    """Persist the users dict to the JSON store."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = USERS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"users": users}, indent=2), encoding="utf-8")
    tmp.replace(USERS_FILE)


def create_user(username, password, name=None, email=None):
    """Create a new unverified user with a generated TOTP secret and email verification token; return (secret, token)."""
    users = load_users()
    if username in users:
        raise ValueError("User already exists")
    secret = pyotp.random_base32()
    token = _secrets.token_urlsafe(32)
    users[username] = {
        "name": name or username,
        "email": email or "",
        "password": hash_password(password),
        "totp_secret": secret,
        "verified": False,
        "verification_token": token,
    }
    save_users(users)
    return secret, token


def verify_email(username, token):
    """Verify a user's email using the verification token. Returns True on success."""
    users = load_users()
    if username not in users:
        return False
    record = users[username]
    if record.get("verification_token") != token:
        return False
    record["verified"] = True
    record.pop("verification_token", None)
    save_users(users)
    return True


def is_verified(username):
    """Return True if the user's email has been verified."""
    users = load_users()
    return bool(users.get(username, {}).get("verified"))


def reset_password(username, new_password):
    """Set a new password for an existing user."""
    users = load_users()
    if username not in users:
        raise ValueError("Unknown user")
    users[username]["password"] = hash_password(new_password)
    save_users(users)