"""JWT authentication for remote Praxys API."""
import json
import os
import getpass

import requests

# Config dir migrated from ~/.trainsight to ~/.praxys for the rebrand. We
# read both during the deprecation window so existing CLI users keep their
# cached token; new writes always go to ~/.praxys.
CONFIG_DIR = os.path.expanduser("~/.praxys")
LEGACY_CONFIG_DIR = os.path.expanduser("~/.trainsight")
TOKEN_PATH = os.path.join(CONFIG_DIR, "token")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
_LEGACY_TOKEN_PATH = os.path.join(LEGACY_CONFIG_DIR, "token")
_LEGACY_CONFIG_PATH = os.path.join(LEGACY_CONFIG_DIR, "config.json")


def get_config() -> dict:
    """Load stored remote API config (url, email)."""
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            return json.load(f)
    if os.path.exists(_LEGACY_CONFIG_PATH):
        with open(_LEGACY_CONFIG_PATH) as f:
            return json.load(f)
    return {}


def save_config(config: dict):
    """Persist remote API config."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


def get_token() -> str | None:
    """Read cached JWT token."""
    if os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH) as f:
            return f.read().strip()
    if os.path.exists(_LEGACY_TOKEN_PATH):
        with open(_LEGACY_TOKEN_PATH) as f:
            return f.read().strip()
    return None


def save_token(token: str):
    """Cache JWT token to disk."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(TOKEN_PATH, "w") as f:
        f.write(token)


def login(base_url: str, email: str = None, password: str = None) -> str:
    """Login to Praxys API and cache token. Returns access_token."""
    if not email:
        email = input("Email: ")
    if not password:
        password = getpass.getpass("Password: ")

    res = requests.post(
        f"{base_url}/api/auth/login",
        data={"username": email, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    res.raise_for_status()
    token = res.json()["access_token"]
    save_token(token)
    save_config({"url": base_url, "email": email})
    return token


def ensure_authenticated(base_url: str) -> str:
    """Get a valid token, logging in if needed."""
    token = get_token()
    if token:
        # Test if token is still valid
        res = requests.get(
            f"{base_url}/api/health",
            headers={"Authorization": f"Bearer {token}"},
        )
        if res.ok:
            return token
    # Token expired or missing — re-login
    config = get_config()
    return login(base_url, email=config.get("email"))
