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
ICON_PATH = str(CONFIG_DIR / "TrayIconTemplate.png")

CLAUDE_USAGE_URL = "https://claude.ai/settings/usage"

DEFAULT_CONFIG = {
    "refresh_interval_minutes": 5,
    "show_session_pct": True,
    "show_weekly_pct": True,
    "show_reset_time": False,
    "show_hover_tooltip": True,
}


# ─── Cookie decryption ───────────────────────────────────────────────────────

def _get_aes_key():
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
    if not encrypted_value.startswith(b"v10"):
        return encrypted_value.decode("utf-8", errors="replace")
    ciphertext = encrypted_value[3:]
    cipher = AES.new(key, AES.MODE_CBC, b" " * 16)
    decrypted = cipher.decrypt(ciphertext)
    pad_len = decrypted[-1]
    return decrypted[32:-pad_len].decode("utf-8")


def get_claude_cookies():
    if not COOKIES_DB.exists():
        raise FileNotFoundError(f"Claude cookies DB not found: {COOKIES_DB}")
    key = _get_aes_key()
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
    cookies = get_claude_cookies()
    org_id = cookies.get("lastActiveOrg", "")
    if not org_id:
        raise RuntimeError("Could not determine org ID from cookies")

    session = requests.Session()
    session.cookies.update({
        "sessionKey":          cookies.get("sessionKey", ""),
        "lastActiveOrg":       org_id,
        "anthropic-device-id": cookies.get("anthropic-device-id", ""),
    })
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Claude/1.0",
        "Accept": "application/json",
        "Referer": "https://claude.ai/",
    })

    resp = session.get(
        f"https://claude.ai/api/organizations/{org_id}/usage", timeout=15
    )
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
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        mins = int((dt - datetime.now(timezone.utc)).total_seconds() / 60)
        if mins <= 0:
            return "now"
        if mins < 60:
            return f"{mins}m"
        h, m = divmod(mins, 60)
        if h < 24:
            return f"{h}h {m:02d}m"
        d, h = divmod(h, 24)
        return f"{d}d {h}h"
    except Exception:
        return ""


def _build_title(usage, config):
    if usage is None:
        return "!"
    parts = []
    if config.get("show_session_pct"):
        parts.append(f"{usage['session_pct']:.0f}%")
    if config.get("show_weekly_pct"):
        parts.append(f"{usage['weekly_pct']:.0f}%")
    title = " | ".join(parts) if parts else "◈"
    if config.get("show_reset_time"):
        reset = _fmt_reset(usage.get("session_resets_at", ""))
        if reset:
            title += f"  ↺{reset}"
    return title


def _build_tooltip(usage):
    if usage is None:
        return "ClaudeWatch — no data"
    spct  = usage.get("session_pct", 0)
    wpct  = usage.get("weekly_pct", 0)
    sr    = _fmt_reset(usage.get("session_resets_at", ""))
    wr    = _fmt_reset(usage.get("weekly_resets_at", ""))
    lines = [
        "ClaudeWatch",
        f"Session (5h):  {spct:.0f}%" + (f"  —  resets in {sr}" if sr else ""),
        f"Weekly  (7d):  {wpct:.0f}%" + (f"  —  resets in {wr}" if wr else ""),
    ]
    eu = usage.get("extra_used")
    el = usage.get("extra_limit")
    if eu is not None and el:
        lines.append(f"Extra credits: {eu:.0f} / {el:.0f}")
    return "\n".join(lines)


# ─── Menu Bar App ────────────────────────────────────────────────────────────

class ClaudeMonitorApp(rumps.App):
    def __init__(self):
        super().__init__(
            "Claude",
            title="…" if DEPS_OK else "missing deps",
            icon=ICON_PATH,
            template=True,
            quit_button=None,
        )

        self.config = load_config()
        self._usage = None

        # Settings — toggleable checkmark items
        self._s_session = rumps.MenuItem("Session % (5h)", callback=self._toggle("show_session_pct"))
        self._s_weekly  = rumps.MenuItem("Weekly % (7d)",  callback=self._toggle("show_weekly_pct"))
        self._s_reset   = rumps.MenuItem("Reset time",     callback=self._toggle("show_reset_time"))
        self._s_tooltip = rumps.MenuItem("Hover tooltip",  callback=self._toggle("show_hover_tooltip"))
        self._sync_checkmarks()

        settings = rumps.MenuItem("Settings")
        settings.update([
            rumps.MenuItem("Show in menu bar:", callback=None),
            self._s_session,
            self._s_weekly,
            self._s_reset,
            None,
            self._s_tooltip,
        ])

        self.menu = [
            rumps.MenuItem("Open Claude Usage", callback=self.open_usage),
            None,
            rumps.MenuItem("⬤  Session (5h)", callback=None),
            rumps.MenuItem("   —", callback=None),
            rumps.MenuItem("⬤  Weekly (7d)", callback=None),
            rumps.MenuItem("   —  ", callback=None),
            None,
            settings,
            rumps.MenuItem("Refresh Now", callback=self.manual_refresh),
            None,
            rumps.MenuItem("Quit", callback=self.quit_app),
        ]

        if DEPS_OK:
            self._start_timer()
            threading.Thread(target=self._refresh, daemon=True).start()

    # ── Settings toggles ──

    def _toggle(self, key):
        """Return a callback that flips a boolean config key and refreshes the UI."""
        def callback(_):
            self.config[key] = not self.config.get(key, True)
            save_config(self.config)
            self._sync_checkmarks()
            if self._usage:
                self._apply_ui(self._usage)
        return callback

    def _sync_checkmarks(self):
        self._s_session.state = int(bool(self.config.get("show_session_pct", True)))
        self._s_weekly.state  = int(bool(self.config.get("show_weekly_pct",  True)))
        self._s_reset.state   = int(bool(self.config.get("show_reset_time",  False)))
        self._s_tooltip.state = int(bool(self.config.get("show_hover_tooltip", True)))

    # ── Tooltip ──

    def _set_tooltip(self, text):
        try:
            self._status_item.setToolTip_(text)
        except Exception:
            pass

    # ── Menu actions ──

    @rumps.clicked("Open Claude Usage")
    def open_usage(self, _):
        webbrowser.open(CLAUDE_USAGE_URL)

    @rumps.clicked("Refresh Now")
    def manual_refresh(self, _):
        threading.Thread(target=self._refresh, daemon=True).start()

    @rumps.clicked("Quit")
    def quit_app(self, _):
        rumps.quit_application()

    # ── Refresh ──

    def _start_timer(self):
        interval = self.config.get("refresh_interval_minutes", 5) * 60

        @rumps.timer(interval)
        def _auto(timer):
            self._refresh()

    def _refresh(self):
        try:
            usage = fetch_claude_usage()
            self._usage = usage
            self._apply_ui(usage)
        except Exception as e:
            self._apply_ui(None, error=str(e))

    def _apply_ui(self, usage, error=None):
        session_header = "⬤  Session (5h)"
        session_detail = "   —"
        weekly_header  = "⬤  Weekly (7d)"
        weekly_detail  = "   —  "

        if error:
            self.title = "!"
            self.menu[session_detail].title = f"   {error[:60]}"
            self._set_tooltip(f"ClaudeWatch — error\n{error[:120]}")
            return

        # Menu bar title
        self.title = _build_title(usage, self.config)

        # Hover tooltip
        if self.config.get("show_hover_tooltip", True):
            self._set_tooltip(_build_tooltip(usage))
        else:
            self._set_tooltip("")

        # Menu items
        spct   = usage["session_pct"]
        wpct   = usage["weekly_pct"]
        sreset = _fmt_reset(usage["session_resets_at"])
        wreset = _fmt_reset(usage["weekly_resets_at"])

        self.menu[session_header].title = f"⬤  Session (5h) — {spct:.1f}%"
        self.menu[session_detail].title = f"   resets in {sreset}" if sreset else "   —"
        self.menu[weekly_header].title  = f"⬤  Weekly (7d) — {wpct:.1f}%"

        eu = usage.get("extra_used")
        el = usage.get("extra_limit")
        if eu is not None and el:
            self.menu[weekly_detail].title = (
                f"   resets in {wreset}  ·  extra {eu:.0f}/{el:.0f} cr"
                if wreset else f"   extra {eu:.0f}/{el:.0f} cr"
            )
        elif wreset:
            self.menu[weekly_detail].title = f"   resets in {wreset}"
        else:
            self.menu[weekly_detail].title = "   —  "


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ClaudeMonitorApp().run()
