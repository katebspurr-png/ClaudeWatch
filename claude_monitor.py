#!/usr/bin/env python3
"""
Claude Monitor — Mac Menu Bar App
===================================
Shows Claude.ai usage % (5-hour session and 7-day) in the menu bar,
read directly from the Claude desktop app's decrypted cookies.

Setup:
    pip install rumps requests pycryptodome

Run:
    python3 claude_monitor.py
"""

import rumps
import webbrowser
import os
import json
import threading
import hashlib
import sqlite3
import subprocess
from pathlib import Path
from datetime import datetime, timezone

try:
    import requests
    from Crypto.Cipher import AES
    DEPS_OK = True
except ImportError:
    DEPS_OK = False

# ─── Configuration ───────────────────────────────────────────────────────────

CONFIG_DIR = Path.home() / ".claude_monitor"
CONFIG_FILE = CONFIG_DIR / "config.json"
COOKIES_DB = Path.home() / "Library/Application Support/Claude/Cookies"

CLAUDE_USAGE_URL = "https://claude.ai/settings/usage"

DEFAULT_CONFIG = {
    "refresh_interval_minutes": 5,
}


# ─── Cookie decryption ───────────────────────────────────────────────────────

def _get_aes_key():
    """Derive the AES key from the Keychain-stored password (Chromium v10 format)."""
    result = subprocess.run(
        ["security", "find-generic-password",
         "-s", "Claude Safe Storage", "-a", "Claude Key", "-w"],
        capture_output=True, text=True,
    )
    password = result.stdout.strip()
    if not password:
        raise RuntimeError("Could not read 'Claude Safe Storage' from Keychain")
    return hashlib.pbkdf2_hmac("sha1", password.encode(), b"saltysalt", 1003, dklen=16)


def _decrypt_cookie(encrypted_value, key):
    """
    Decrypt a Chromium v10 AES-CBC cookie.

    Format: b"v10" + ciphertext
    The plaintext layout is: [32-byte Chromium header][cookie value][PKCS7 padding]
    IV is always 16 space chars (Chromium default on macOS).
    """
    if not encrypted_value.startswith(b"v10"):
        return encrypted_value.decode("utf-8", errors="replace")
    ciphertext = encrypted_value[3:]
    cipher = AES.new(key, AES.MODE_CBC, b" " * 16)
    decrypted = cipher.decrypt(ciphertext)
    pad_len = decrypted[-1]
    # Skip the 32-byte Chromium internal header prepended before encryption
    return decrypted[32:-pad_len].decode("utf-8")


def get_claude_cookies():
    """
    Read and decrypt cookies from the Claude desktop app's Chromium cookie store.
    Returns a dict of {name: value} for claude.ai cookies.
    Raises if the cookies DB or keychain entry can't be accessed.
    """
    if not COOKIES_DB.exists():
        raise FileNotFoundError(f"Claude cookies DB not found: {COOKIES_DB}")

    key = _get_aes_key()

    # Copy the DB path to avoid locking issues with the live Claude app
    conn = sqlite3.connect(str(COOKIES_DB))
    try:
        rows = conn.execute(
            "SELECT name, encrypted_value FROM cookies WHERE host_key LIKE '%claude.ai%'"
        ).fetchall()
    finally:
        conn.close()

    return {name: _decrypt_cookie(val, key) for name, val in rows}


# ─── Usage API ───────────────────────────────────────────────────────────────

def fetch_claude_usage():
    """
    Fetch Claude.ai usage data using the desktop app's session cookies.

    Returns a dict:
        {
            "session_pct":  float,   # 5-hour window utilisation %
            "weekly_pct":   float,   # 7-day window utilisation %
            "session_resets_at": str,
            "weekly_resets_at":  str,
            "extra_used":   float | None,
            "extra_limit":  float | None,
        }
    or raises on error.
    """
    cookies = get_claude_cookies()

    org_id = cookies.get("lastActiveOrg", "")
    if not org_id:
        raise RuntimeError("Could not determine org ID from cookies")

    session = requests.Session()
    session.cookies.update({
        "sessionKey":         cookies.get("sessionKey", ""),
        "lastActiveOrg":      org_id,
        "anthropic-device-id": cookies.get("anthropic-device-id", ""),
    })
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Claude/1.0",
        "Accept": "application/json",
        "Referer": "https://claude.ai/",
    })

    url = f"https://claude.ai/api/organizations/{org_id}/usage"
    resp = session.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    five_hour = data.get("five_hour") or {}
    seven_day  = data.get("seven_day")  or {}
    extra      = data.get("extra_usage") or {}

    return {
        "session_pct":       five_hour.get("utilization", 0.0),
        "weekly_pct":        seven_day.get("utilization",  0.0),
        "session_resets_at": five_hour.get("resets_at", ""),
        "weekly_resets_at":  seven_day.get("resets_at",  ""),
        "extra_used":        extra.get("used_credits"),
        "extra_limit":       extra.get("monthly_limit"),
    }


# ─── Helpers ─────────────────────────────────────────────────────────────────

def load_config():
    CONFIG_DIR.mkdir(exist_ok=True)
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return {**DEFAULT_CONFIG, **json.load(f)}
    save_config(DEFAULT_CONFIG)
    return DEFAULT_CONFIG.copy()


def save_config(config):
    CONFIG_DIR.mkdir(exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def _fmt_reset(iso_str):
    """Format an ISO timestamp as a human-friendly relative string."""
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = dt - now
        mins = int(delta.total_seconds() / 60)
        if mins <= 0:
            return "now"
        if mins < 60:
            return f"{mins}m"
        return f"{mins // 60}h {mins % 60:02d}m"
    except Exception:
        return ""


# ─── Menu Bar App ────────────────────────────────────────────────────────────

ICON_PATH = str(CONFIG_DIR / "TrayIconTemplate.png")


class ClaudeMonitorApp(rumps.App):
    def __init__(self):
        title = "missing deps" if not DEPS_OK else "…"

        super().__init__(
            "Claude",
            title=title,
            icon=ICON_PATH,
            template=True,   # adapts to light/dark menu bar
            quit_button=None,
        )

        self.config = load_config()
        self._usage = None
        self._timer = None

        self.menu = [
            rumps.MenuItem("Open Claude Usage", callback=self.open_usage),
            None,
            rumps.MenuItem("⬤  Session (5h)", callback=None),
            rumps.MenuItem("   —", callback=None),
            rumps.MenuItem("⬤  Weekly (7d)", callback=None),
            rumps.MenuItem("   —  ", callback=None),
            None,
            rumps.MenuItem("Refresh Now", callback=self.manual_refresh),
            None,
            rumps.MenuItem("Quit", callback=self.quit_app),
        ]

        if not DEPS_OK:
            self.menu["   —"].title = "   Install: pip install requests pycryptodome"
        else:
            self._start_timer()
            threading.Thread(target=self._refresh, daemon=True).start()

    @rumps.clicked("Open Claude Usage")
    def open_usage(self, _):
        webbrowser.open(CLAUDE_USAGE_URL)

    @rumps.clicked("Refresh Now")
    def manual_refresh(self, _):
        threading.Thread(target=self._refresh, daemon=True).start()

    @rumps.clicked("Quit")
    def quit_app(self, _):
        rumps.quit_application()

    def _start_timer(self):
        interval = self.config.get("refresh_interval_minutes", 5) * 60

        @rumps.timer(interval)
        def _auto(timer):
            self._refresh()

    def _refresh(self):
        try:
            usage = fetch_claude_usage()
            self._usage = usage
            self._update_ui(usage, error=None)
        except Exception as e:
            self._update_ui(None, error=str(e))

    def _update_ui(self, usage, error):
        session_header = "⬤  Session (5h)"
        session_detail = "   —"
        weekly_header  = "⬤  Weekly (7d)"
        weekly_detail  = "   —  "

        if error:
            self.title = "!"
            self.menu[session_detail].title = f"   {error[:60]}"
            return

        spct = usage["session_pct"]
        wpct = usage["weekly_pct"]

        # Menu bar title: show both percentages (icon is shown separately)
        self.title = f"{spct:.0f}% | {wpct:.0f}%"

        sreset = _fmt_reset(usage["session_resets_at"])
        wreset = _fmt_reset(usage["weekly_resets_at"])

        self.menu[session_header].title = f"⬤  Session (5h) — {spct:.1f}%"
        self.menu[session_detail].title = (
            f"   resets in {sreset}" if sreset else "   —"
        )

        self.menu[weekly_header].title  = f"⬤  Weekly (7d) — {wpct:.1f}%"

        extra_used  = usage.get("extra_used")
        extra_limit = usage.get("extra_limit")
        if extra_used is not None and extra_limit:
            self.menu[weekly_detail].title = (
                f"   resets in {wreset}  ·  extra {extra_used:.0f}/{extra_limit:.0f} cr"
                if wreset else
                f"   extra {extra_used:.0f}/{extra_limit:.0f} cr"
            )
        elif wreset:
            self.menu[weekly_detail].title = f"   resets in {wreset}"
        else:
            self.menu[weekly_detail].title = "   —  "


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ClaudeMonitorApp().run()
