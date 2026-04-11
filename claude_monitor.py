#!/usr/bin/env python3
"""
Claude Monitor — Mac Menu Bar App
===================================
Shows Claude.ai usage % in the menu bar and a local analytics dashboard.
"""

import rumps
import webbrowser
import json
import threading
import hashlib
import sqlite3
import subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta

try:
    import warnings as _warnings
    _warnings.filterwarnings("ignore", message="Unable to find acceptable character detection")
    import requests
    from Crypto.Cipher import AES
    DEPS_OK = True
except ImportError:
    DEPS_OK = False

try:
    import zstandard
    ZSTD_OK = True
except ImportError:
    ZSTD_OK = False

# ─── Configuration ───────────────────────────────────────────────────────────

CONFIG_DIR  = Path.home() / ".claude_monitor"
CONFIG_FILE = CONFIG_DIR / "config.json"
DB_PATH     = CONFIG_DIR / "history.db"
DASH_PATH   = CONFIG_DIR / "dashboard.html"
COOKIES_DB  = Path.home() / "Library/Application Support/Claude/Cookies"

# When running as a py2app bundle the icon lives inside the .app Resources
# directory; otherwise it's copied to ~/.claude_monitor/ by setup.sh.
import sys as _sys
if getattr(_sys, 'frozen', False):
    ICON_PATH = str(Path(_sys.executable).parent.parent / "Resources" / "TrayIconTemplate.png")
else:
    ICON_PATH = str(CONFIG_DIR / "TrayIconTemplate.png")

CLAUDE_USAGE_URL = "https://claude.ai/settings/usage"

DEFAULT_CONFIG = {
    "refresh_interval_minutes": 5,
    "show_session_pct":   True,
    "show_weekly_pct":    True,
    "show_reset_time":    False,
    "show_hover_tooltip": True,
    "notifications_enabled": True,
    "display_size":       "full",       # "full", "compact", or "minimal"
    "show_sparkline":     True,
}

DISPLAY_SIZE_OPTIONS = ["full", "compact", "minimal", "custom"]

CREDITS_PER_DOLLAR = 100   # 1 credit = $0.01 (confirmed against billing)
SESSION_THRESHOLDS = [75, 90]   # % session usage to notify at
WEEKLY_THRESHOLDS  = [75, 90]   # % weekly usage to notify at
EXTRA_THRESHOLDS   = [80, 95]   # % extra credits to notify at

REFRESH_OPTIONS = [1, 5, 15, 30]  # minutes

MODEL_DISPLAY = {
    "claude-sonnet-4-6":          "Sonnet 4.6",
    "claude-opus-4-6":            "Opus 4.6",
    "claude-haiku-4-5":           "Haiku 4.5",
    "claude-sonnet-4-5":          "Sonnet 4.5",
    "claude-opus-4-5":            "Opus 4.5",
    # Versioned IDs sometimes returned by message-level API
    "claude-sonnet-4-6-20250514": "Sonnet 4.6",
    "claude-opus-4-6-20250514":   "Opus 4.6",
    "claude-haiku-4-5-20251001":  "Haiku 4.5",
    "claude-sonnet-4-5-20241022": "Sonnet 4.5",
    "claude-sonnet-4-5-20250929": "Sonnet 4.5",
    "claude-opus-4-5-20250115":   "Opus 4.5",
    "claude-opus-4-5-20251101":   "Opus 4.5",
    # Older model IDs
    "claude-3-5-sonnet-20241022": "Sonnet 3.5",
    "claude-3-5-haiku-20241022":  "Haiku 3.5",
    "claude-3-opus-20240229":     "Opus 3",
}


def _get_conversation_model(conv):
    """
    Extract the most accurate model from a conversation object.
    The API 'model' field is often the org/project default, not what was
    actually used. Check several fields in priority order.
    """
    # 1. Enriched actual model from last assistant message (set by _fetch_conversations_data)
    model_id = conv.get("_actual_model") or ""
    # 2. model_override — set when user explicitly picks a different model
    if not model_id:
        model_id = conv.get("model_override") or ""
    # 3. settings.model or settings.preview_model
    if not model_id:
        settings = conv.get("settings") or {}
        model_id = settings.get("model") or settings.get("preview_model") or ""
    # 4. active_model — some API versions include this
    if not model_id:
        model_id = conv.get("active_model") or ""
    # 5. Fall back to conversation-level default
    if not model_id:
        model_id = conv.get("model") or ""

    if not model_id:
        return model_id, "—"
    if model_id in MODEL_DISPLAY:
        return model_id, MODEL_DISPLAY[model_id]
    # Strip trailing date suffix (YYYYMMDD) and try again
    import re as _re
    base = _re.sub(r"-\d{8}$", "", model_id)
    if base in MODEL_DISPLAY:
        return model_id, MODEL_DISPLAY[base]
    return model_id, model_id.split("-")[-1].title()


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

def _decode_response(resp):
    """Decode API response, handling zstd compression."""
    # Try standard JSON first — requests/urllib3 may have already decompressed
    try:
        return resp.json()
    except (ValueError, Exception):
        pass
    # Fall back to manual zstd decompression
    if ZSTD_OK:
        dctx = zstandard.ZstdDecompressor()
        return json.loads(dctx.decompress(resp.content))
    raise RuntimeError(
        "Could not decode API response. Install zstandard: pip install zstandard"
    )


def _make_session(cookies):
    """Create a requests.Session with full cookie jar and browser headers."""
    s = requests.Session()
    for name, value in cookies.items():
        s.cookies.set(name, value, domain="claude.ai")
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/131.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://claude.ai/",
        "Origin": "https://claude.ai",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "anthropic-client-platform": "web_claude_ai",
    })
    return s


def fetch_claude_usage():
    cookies = get_claude_cookies()
    org_id  = cookies.get("lastActiveOrg", "")
    if not org_id:
        raise RuntimeError("Could not determine org ID from cookies")

    session = _make_session(cookies)

    resp = session.get(
        f"https://claude.ai/api/organizations/{org_id}/usage", timeout=15
    )
    resp.raise_for_status()
    data = _decode_response(resp)

    five_hour = data.get("five_hour")  or {}
    seven_day = data.get("seven_day")  or {}
    extra     = data.get("extra_usage") or {}

    # Per-model breakdowns (non-null only for Max plan users)
    per_model = {}
    for key in ("seven_day_opus", "seven_day_sonnet", "seven_day_cowork"):
        val = data.get(key)
        if val and isinstance(val, dict) and val.get("utilization") is not None:
            label = key.replace("seven_day_", "").capitalize()
            per_model[label] = {
                "utilization": val["utilization"],
                "resets_at":   val.get("resets_at", ""),
            }

    return {
        "session_pct":       five_hour.get("utilization", 0.0),
        "weekly_pct":        seven_day.get("utilization",  0.0),
        "session_resets_at": five_hour.get("resets_at", ""),
        "weekly_resets_at":  seven_day.get("resets_at",  ""),
        "extra_used":        extra.get("used_credits"),
        "extra_limit":       extra.get("monthly_limit"),
        "extra_enabled":     extra.get("is_enabled", False),
        "extra_pct":         extra.get("utilization"),
        "per_model":         per_model,
        "sonnet_pct": data["seven_day_sonnet"]["utilization"] if data.get("seven_day_sonnet") else None,
        "opus_pct":   data["seven_day_opus"]["utilization"]   if data.get("seven_day_opus")   else None,
    }


# ─── History DB ──────────────────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS usage_log (
            ts               TEXT PRIMARY KEY,
            session_pct      REAL,
            weekly_pct       REAL,
            session_resets_at TEXT,
            weekly_resets_at TEXT,
            extra_used       REAL,
            extra_limit      REAL
        )
    """)
    conn.commit()
    conn.close()


def log_usage(usage):
    ts = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute("""
            INSERT OR IGNORE INTO usage_log
              (ts, session_pct, weekly_pct, session_resets_at, weekly_resets_at,
               extra_used, extra_limit)
            VALUES (?,?,?,?,?,?,?)
        """, (
            ts,
            usage["session_pct"],
            usage["weekly_pct"],
            usage.get("session_resets_at", ""),
            usage.get("weekly_resets_at",  ""),
            usage.get("extra_used"),
            usage.get("extra_limit"),
        ))
        conn.commit()
    finally:
        conn.close()


def load_history(days=14):
    """Return rows from the last N days, oldest first."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    conn  = sqlite3.connect(str(DB_PATH))
    try:
        rows = conn.execute(
            "SELECT ts, session_pct, weekly_pct, weekly_resets_at, extra_used, extra_limit "
            "FROM usage_log WHERE ts >= ? ORDER BY ts ASC",
            (since,)
        ).fetchall()
    finally:
        conn.close()
    return rows


# ─── Analytics ───────────────────────────────────────────────────────────────

DOW_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DOW_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def calc_day_patterns(rows):
    """
    Calculate average % burned per day of week from all history.
    Returns {0: avg_mon, 1: avg_tue, ...} or None if < 7 unique days available.
    """
    from collections import defaultdict

    date_increments = defaultdict(float)
    prev_pct = None

    for row in rows:
        ts, _, w_pct = row[0], row[1], row[2]
        try:
            local_date = datetime.fromisoformat(ts).astimezone().date()
        except Exception:
            continue
        if prev_pct is not None:
            inc = w_pct - prev_pct
            if 0 < inc < 20:          # plausible positive increment, skip resets
                date_increments[local_date] += inc
        prev_pct = w_pct

    if len(date_increments) < 7:
        return None                   # need at least one full week

    dow_groups = defaultdict(list)
    for date, inc in date_increments.items():
        dow_groups[date.weekday()].append(inc)

    return {dow: sum(vals) / len(vals) for dow, vals in dow_groups.items()}


def calculate_stats(usage, rows):
    """
    Derive burn rate, projection, and daily budget from history.
    `usage` is the latest reading dict.
    `rows`  is [(ts, session_pct, weekly_pct, weekly_resets_at, extra_used, extra_limit), ...]
    """
    weekly_resets_at = usage.get("weekly_resets_at", "")
    try:
        reset_dt     = datetime.fromisoformat(weekly_resets_at.replace("Z", "+00:00"))
        period_start = reset_dt - timedelta(days=7)
    except Exception:
        return None

    now = datetime.now(timezone.utc)

    # Filter to current weekly period, detect & drop resets
    period_rows = []
    prev_pct    = None
    for ts, s_pct, w_pct, *_ in rows:
        try:
            dt = datetime.fromisoformat(ts)
        except Exception:
            continue
        if dt < period_start:
            continue
        if prev_pct is not None and w_pct < prev_pct - 5:
            # Usage dropped — weekly reset happened mid-history, restart
            period_rows = []
        period_rows.append((dt, w_pct))
        prev_pct = w_pct

    if len(period_rows) < 2:
        return None

    # Burn rate — compare first and last reading in current period
    first_dt, first_pct = period_rows[0]
    last_dt,  last_pct  = period_rows[-1]
    hours_elapsed = max((last_dt - first_dt).total_seconds() / 3600, 0.01)
    burn_per_hour = (last_pct - first_pct) / hours_elapsed
    burn_per_day  = burn_per_hour * 24

    # Days until weekly reset
    days_until_reset = max((reset_dt - now).total_seconds() / 86400, 0.01)

    # Projection: hours until 100%
    remaining = max(100 - last_pct, 0)
    if burn_per_hour > 0:
        hours_until_full = remaining / burn_per_hour
        projected_full   = now + timedelta(hours=hours_until_full)
        hits_limit       = hours_until_full < days_until_reset * 24
    else:
        projected_full = None
        hits_limit     = False

    # Daily budget to stay within limit
    daily_budget = remaining / days_until_reset

    # Chart series — one point per hour (max per hour bucket)
    buckets = {}
    for dt, pct in period_rows:
        key = dt.strftime("%Y-%m-%dT%H:00")
        buckets[key] = max(buckets.get(key, 0), pct)
    chart_labels = sorted(buckets)
    chart_values = [buckets[k] for k in chart_labels]

    day_patterns = calc_day_patterns(rows)

    return {
        "burn_per_hour":    burn_per_hour,
        "burn_per_day":     burn_per_day,
        "days_until_reset": days_until_reset,
        "projected_full":   projected_full,
        "hits_limit":       hits_limit,
        "daily_budget":     daily_budget,
        "chart_labels":     chart_labels,
        "chart_values":     chart_values,
        "readings_count":   len(period_rows),
        "day_patterns":     day_patterns,
    }


def _tip(usage, stats):
    wpct     = usage["weekly_pct"]
    spct     = usage["session_pct"]
    today    = datetime.now().weekday()

    if stats is None:
        return "Keep using Claude and your dashboard will fill in over the next few hours."

    patterns = stats.get("day_patterns") or {}

    # Pattern-aware tip: warn if today is historically heavy
    if patterns and today in patterns and len(patterns) >= 5:
        heaviest = max(patterns, key=patterns.get)
        today_avg = patterns[today]
        overall_avg = sum(patterns.values()) / len(patterns)
        if today == heaviest and today_avg > overall_avg * 1.3:
            day_name = DOW_NAMES[today]
            return (f"Heads up — {day_name} is historically your heaviest usage day "
                    f"(avg {today_avg:.1f}% burned). Consider saving complex tasks for later "
                    f"in the week if you're running low.")

    if stats["hits_limit"]:
        days = stats["days_until_reset"]
        return (f"⚠️ At this burn rate you'll hit your weekly limit before the reset "
                f"({days:.1f} days away). Switch to Haiku for lighter tasks to stretch your credits.")
    if wpct > 80:
        return "You're running high on weekly credits. Save Opus and Sonnet for complex tasks — use Haiku for Q&A and quick lookups."
    if spct > 70:
        return "Your 5-hour session is getting full. It resets automatically — consider pausing heavy work until it refreshes."
    if stats["burn_per_day"] > stats["daily_budget"] * 1.3:
        return "You're burning faster than your daily budget. Consider batching smaller questions into single prompts to save credits."
    if wpct < 30 and stats["days_until_reset"] < 2:
        return "You have plenty of credits with only a couple of days until reset — great time to tackle that complex project with Opus."

    # Lightest day coming up?
    if patterns and len(patterns) >= 5:
        lightest = min(patterns, key=patterns.get)
        days_ahead = (lightest - today) % 7
        if 1 <= days_ahead <= 3:
            return (f"{DOW_NAMES[lightest]} is typically your lightest day "
                    f"— good time to save heavier Opus work for then.")

    return "You're on track. Keep using the right model for the job: Haiku for quick tasks, Sonnet for most work, Opus for deep reasoning."


# ─── Model Guide (context-aware) ─────────────────────────────────────────────

def _model_guide_html(usage, stats):
    wpct = usage["weekly_pct"]
    days_left = stats["days_until_reset"] if stats else None

    # Decide which model to recommend
    if wpct >= 80:
        rec = "haiku"
        reason = "You're above 80% weekly usage — stick to Haiku for lighter tasks to stretch your remaining credits."
    elif wpct >= 60:
        rec = "sonnet"
        reason = "Usage is moderate. Sonnet covers most tasks well — save Opus for problems that truly need it."
    elif days_left is not None and days_left < 2 and wpct < 30:
        rec = "opus"
        reason = "Plenty of credits left with the reset around the corner — great time to tackle complex work with Opus."
    elif stats and stats.get("hits_limit"):
        rec = "haiku"
        reason = "At your current burn rate you'll hit the limit before reset — conserve with Haiku where you can."
    else:
        rec = "sonnet"
        reason = "You're on track. Sonnet is the best default — upgrade to Opus only when you need deep reasoning."

    models = [
        ("haiku", "Haiku", "Fast & light", [
            "Quick Q&A and lookups",
            "Summarisation & translation",
            "Simple edits & rewrites",
            "High-volume / repetitive tasks",
        ]),
        ("sonnet", "Sonnet", "Best all-rounder", [
            "Coding & debugging",
            "Writing & long-form editing",
            "Data analysis & research",
            "Most everyday tasks",
        ]),
        ("opus", "Opus", "Deep reasoning", [
            "Hard math & logic problems",
            "Multi-step planning",
            "Architecture & system design",
            "Novel / open-ended problems",
        ]),
    ]

    cards = ""
    for key, name, subtitle, tasks in models:
        is_rec = key == rec
        border = "border:2px solid var(--accent)" if is_rec else "border:1px solid var(--border)"
        badge = '<span style="background:var(--accent);color:#fff;font-size:.65rem;padding:2px 8px;border-radius:99px;margin-left:8px;vertical-align:middle">RECOMMENDED</span>' if is_rec else ""
        task_list = "".join(f"<li>{t}</li>" for t in tasks)
        cards += f"""
        <div class="model-card" style="{border}">
          <div class="model-name">{name}{badge}</div>
          <div class="model-sub">{subtitle}</div>
          <ul class="model-tasks">{task_list}</ul>
        </div>"""

    return f"""
    <div class="card" style="margin-top:16px">
      <h2>Model Guide — Right Tool for the Job</h2>
      <p style="font-size:.85rem;color:var(--muted);margin-bottom:14px">{reason}</p>
      <div class="model-grid">{cards}</div>
    </div>"""


def _per_model_html(usage):
    """Render per-model usage bars (Max plan only). Returns '' if no data."""
    pm = usage.get("per_model")
    if not pm:
        return ""
    rows = ""
    for name, info in sorted(pm.items()):
        pct = info.get("utilization", 0)
        reset = _fmt_reset(info.get("resets_at", ""))
        if pct >= 85:
            color = "#ef4444"
        elif pct >= 60:
            color = "#f59e0b"
        else:
            color = "#0D9488"
        rows += f"""
        <div style="margin-bottom:12px">
          <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:4px">
            <span style="font-weight:600">{name}</span>
            <span style="font-size:1.1rem;font-weight:700;color:{color}">{pct:.0f}%</span>
          </div>
          <div class="bar-wrap"><div class="bar" style="width:{min(pct,100):.1f}%;background:{color}"></div></div>
          {f'<div class="reset-badge">resets in {reset}</div>' if reset else ''}
        </div>"""
    return f"""
    <div class="card">
      <h2>Per-Model Usage (7d)</h2>
      {rows}
    </div>"""


# ─── Power-user analytics ────────────────────────────────────────────────────

def calc_velocity(rows, window_minutes=30):
    """
    Calculate burn velocity over the last `window_minutes`.
    Returns dict with session and weekly velocity (% per hour),
    delta since last reading, and raw deltas.
    """
    if len(rows) < 2:
        return None

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=window_minutes)

    # Find readings within the window
    window_rows = []
    for ts, s_pct, w_pct, *_ in rows:
        try:
            dt = datetime.fromisoformat(ts)
        except Exception:
            continue
        if dt >= cutoff:
            window_rows.append((dt, s_pct, w_pct))

    # Delta since last refresh (last two readings regardless of window)
    last_ts, last_s, last_w, *_ = rows[-1]
    prev_ts, prev_s, prev_w, *_ = rows[-2]
    session_delta = last_s - prev_s
    weekly_delta = last_w - prev_w

    if len(window_rows) >= 2:
        first_dt, first_s, first_w = window_rows[0]
        last_dt, last_s_w, last_w_w = window_rows[-1]
        hours = max((last_dt - first_dt).total_seconds() / 3600, 0.001)
        session_velocity = (last_s_w - first_s) / hours  # % per hour
        weekly_velocity = (last_w_w - first_w) / hours
    else:
        session_velocity = 0
        weekly_velocity = 0

    return {
        "session_velocity": session_velocity,  # % per hour
        "weekly_velocity": weekly_velocity,
        "session_delta": session_delta,        # change since last refresh
        "weekly_delta": weekly_delta,
        "window_minutes": window_minutes,
    }


def calc_runway(usage, velocity):
    """
    Estimate time until session/weekly limits at current pace.
    Returns dict with runway estimates in minutes, or None if not burning.
    """
    result = {}

    spct = usage["session_pct"]
    wpct = usage["weekly_pct"]

    # Session runway
    s_vel = velocity["session_velocity"] if velocity else 0
    if s_vel > 0.1:  # meaningful burn rate (>0.1%/hr)
        remaining = 100 - spct
        hours_left = remaining / s_vel
        result["session_runway_min"] = hours_left * 60
    else:
        result["session_runway_min"] = None

    # Weekly runway
    w_vel = velocity["weekly_velocity"] if velocity else 0
    if w_vel > 0.1:
        remaining = 100 - wpct
        hours_left = remaining / w_vel
        result["weekly_runway_min"] = hours_left * 60
    else:
        result["weekly_runway_min"] = None

    return result


def estimate_messages_remaining(usage, rows):
    """
    Estimate how many messages remain based on average % cost per interaction.
    Looks at positive session_pct deltas (each one ~ a message or burst).
    Returns dict with estimates per model, or None if not enough data.
    """
    if len(rows) < 5:
        return None

    # Collect positive session deltas (each represents usage from a message/burst)
    deltas = []
    prev_s = None
    prev_reset = None
    for ts, s_pct, w_pct, reset_at, *_ in rows:
        if prev_s is not None:
            # Skip if session reset happened (reset_at changed)
            if reset_at != prev_reset and s_pct < prev_s:
                prev_s = s_pct
                prev_reset = reset_at
                continue
            inc = s_pct - prev_s
            if 0.1 < inc < 30:  # plausible single interaction (0.1% to 30%)
                deltas.append(inc)
        prev_s = s_pct
        prev_reset = reset_at

    if len(deltas) < 3:
        return None

    avg_cost = sum(deltas) / len(deltas)
    median_cost = sorted(deltas)[len(deltas) // 2]

    session_remaining = max(100 - usage["session_pct"], 0)
    weekly_remaining = max(100 - usage["weekly_pct"], 0)

    # Use median for more robust estimate (outliers from big prompts)
    cost = median_cost if median_cost > 0 else avg_cost
    if cost <= 0:
        return None

    return {
        "avg_cost_per_msg": avg_cost,
        "median_cost_per_msg": median_cost,
        "session_msgs_left": int(session_remaining / cost),
        "weekly_msgs_left": int(weekly_remaining / cost),
        "sample_size": len(deltas),
    }


def smart_suggestion(usage, stats, velocity):
    """
    Generate a single actionable suggestion string for the menu bar.
    Returns (emoji, text) or None.
    """
    spct = usage["session_pct"]
    wpct = usage["weekly_pct"]

    # Urgent: session almost full
    if spct >= 85:
        sr = _fmt_reset(usage.get("session_resets_at", ""))
        return ("🔴", f"Session nearly full — resets in {sr}" if sr else "Session nearly full — pause and wait for reset")

    # Burning fast right now
    if velocity and velocity["session_velocity"] > 20:
        return ("🔥", f"Burning {velocity['session_velocity']:.0f}%/hr — switch to Haiku for lighter tasks")

    # Weekly getting high, suggest conservation
    if wpct >= 70:
        if stats and stats["days_until_reset"] > 2:
            return ("⚠️", f"Weekly at {wpct:.0f}% with {stats['days_until_reset']:.0f}d left — use Haiku where possible")
        elif stats:
            return ("⚠️", f"Weekly at {wpct:.0f}% — resets in {stats['days_until_reset']:.1f}d, conserve Opus")

    # Will hit limit before reset
    if stats and stats.get("hits_limit"):
        return ("⚠️", "On track to hit weekly limit — switch to Haiku for routine tasks")

    # Session heating up
    if spct >= 60:
        return ("🟡", f"Session at {spct:.0f}% — consider batching questions or switching to Haiku")

    # Everything's fine, encourage Opus if lots of headroom
    if wpct < 20 and spct < 30:
        return ("🟢", "Plenty of headroom — good time for Opus on complex tasks")

    if wpct < 40:
        return ("🟢", "Usage healthy — Sonnet for most tasks, Opus when needed")

    return None


def _fmt_runway(minutes):
    """Format runway minutes into readable string."""
    if minutes is None:
        return None
    if minutes < 1:
        return "<1 min"
    if minutes < 60:
        return f"{minutes:.0f} min"
    hours = minutes / 60
    if hours < 24:
        return f"{hours:.1f}h"
    days = hours / 24
    return f"{days:.1f}d"


def load_session_history():
    """Return recent session data points with reset boundaries from DB."""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        rows = conn.execute(
            "SELECT ts, session_pct, session_resets_at "
            "FROM usage_log ORDER BY ts DESC LIMIT 200"
        ).fetchall()
    finally:
        conn.close()
    return list(reversed(rows))


def _detect_sessions(rows):
    """Detect session boundaries and return summaries of recent sessions."""
    if not rows:
        return []
    sessions = []
    current_reset = rows[0][2]
    session_start = rows[0][0]
    peak_pct = rows[0][1]

    for ts, pct, reset_at in rows[1:]:
        if reset_at != current_reset:
            sessions.append({
                "start": session_start,
                "peak_pct": peak_pct,
            })
            current_reset = reset_at
            session_start = ts
            peak_pct = pct
        else:
            peak_pct = max(peak_pct, pct)

    # Add the current (ongoing) session
    sessions.append({
        "start": session_start,
        "peak_pct": peak_pct,
    })

    return sessions[-10:]  # last 10 sessions


def _session_history_html(sessions):
    """Render a compact session history log."""
    if not sessions or len(sessions) < 2:
        return """
        <div class="card muted">
          <h2>Recent Sessions</h2>
          <p>Session history will appear after a few session resets.</p>
        </div>"""

    rows = ""
    for s in reversed(sessions):
        pct = s["peak_pct"]
        if pct >= 80:
            dot_color = "#ef4444"
        elif pct >= 50:
            dot_color = "#f59e0b"
        else:
            dot_color = "#22c55e"
        try:
            ts = datetime.fromisoformat(s["start"])
            time_str = _relative_time(s["start"])
        except Exception:
            time_str = s["start"][:16]
        rows += f"""
        <div class="session-row">
          <div class="session-dot" style="background:{dot_color}"></div>
          <div style="flex:1;font-size:.85rem">{time_str}</div>
          <div style="font-weight:600;font-size:.9rem;color:{dot_color}">{pct:.0f}%</div>
          <div style="font-size:.75rem;color:var(--muted);width:60px;text-align:right">peak</div>
        </div>"""
    return f"""
    <div class="card">
      <h2>Recent Sessions</h2>
      {rows}
    </div>"""


def _conversations_dashboard_html(conversations):
    """Render recent conversations as an embedded dashboard table."""
    if not conversations:
        return """
        <div class="card muted">
          <h2>Recent Conversations</h2>
          <p>Conversation data will appear on next refresh.</p>
        </div>"""

    rows_html = ""
    for c in conversations[:10]:
        name = c.get("name") or "Untitled"
        if len(name) > 60:
            name = name[:57] + "..."
        uuid = c.get("uuid", "")
        _, model = _get_conversation_model(c)
        project = (c.get("project") or {}).get("name") or "—"
        updated = _relative_time(c.get("updated_at", ""))
        link = f"https://claude.ai/chat/{uuid}" if uuid else "#"
        rows_html += f"""
        <tr>
          <td><a href="{link}" target="_blank">{name}</a></td>
          <td>{model}</td>
          <td>{project}</td>
          <td>{updated}</td>
        </tr>"""

    return f"""
    <div class="card">
      <h2>Recent Conversations</h2>
      <table class="conv-table">
        <thead><tr><th>Name</th><th>Model</th><th>Project</th><th>Updated</th></tr></thead>
        <tbody>{rows_html}</tbody>
      </table>
    </div>"""


# ─── Dashboard HTML ──────────────────────────────────────────────────────────

# Rough cost weights per model (relative to Sonnet = 1.0)
MODEL_COST_WEIGHT = {
    "claude-sonnet-4-6": 1.0,
    "claude-sonnet-4-5": 1.0,
    "claude-haiku-4-5":  0.15,
    "claude-opus-4-6":   5.0,
    "claude-opus-4-5":   5.0,
}


def _conversation_insights_html(conversations):
    """Rank conversations by estimated cost and show insights."""
    if not conversations or len(conversations) < 2:
        return ""

    # Estimate relative cost from model and recency (more recent = more active = higher cost)
    ranked = []
    now = datetime.now(timezone.utc)
    for c in conversations[:20]:
        model_id, model_label = _get_conversation_model(c)
        weight = MODEL_COST_WEIGHT.get(model_id, 1.0)
        name = c.get("name") or "Untitled"
        uuid = c.get("uuid", "")
        updated = c.get("updated_at", "")

        # Estimate "size" from created_at vs updated_at span
        created = c.get("created_at", updated)
        try:
            created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            updated_dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            duration_hrs = max((updated_dt - created_dt).total_seconds() / 3600, 0.1)
        except Exception:
            duration_hrs = 1.0

        # Longer conversations on heavier models = more expensive
        # This is a rough heuristic but directionally useful
        estimated_cost = weight * min(duration_hrs, 24)  # cap at 24h

        if len(name) > 45:
            name = name[:42] + "..."

        ranked.append({
            "name": name,
            "uuid": uuid,
            "model": model_label,
            "weight": weight,
            "duration_hrs": duration_hrs,
            "cost": estimated_cost,
        })

    ranked.sort(key=lambda x: x["cost"], reverse=True)
    max_cost = ranked[0]["cost"] if ranked else 1

    rows = ""
    for i, c in enumerate(ranked[:8]):
        bar_width = c["cost"] / max_cost * 100
        bar_color = "#ef4444" if c["weight"] >= 5 else "#f59e0b" if c["weight"] >= 1 else "#22c55e"
        link = f"https://claude.ai/chat/{c['uuid']}" if c["uuid"] else "#"
        label = "Heavy" if c["weight"] >= 5 else "Medium" if c["weight"] >= 1 else "Light"
        rows += f"""
        <div style="display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--border)">
          <span style="font-size:.75rem;color:var(--muted);width:16px;text-align:right">{i+1}</span>
          <div style="flex:1;min-width:0">
            <a href="{link}" target="_blank" style="color:var(--accent);text-decoration:none;font-size:.85rem;
               white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:block">{c['name']}</a>
            <div style="font-size:.7rem;color:var(--muted)">{c['model']} · {c['duration_hrs']:.1f}h · {label}</div>
          </div>
          <div style="width:80px;background:var(--border);border-radius:4px;height:6px;flex-shrink:0">
            <div style="width:{bar_width:.0f}%;background:{bar_color};border-radius:4px;height:100%"></div>
          </div>
        </div>"""

    # Model mix breakdown
    model_counts = {}
    for c in conversations[:20]:
        _, m = _get_conversation_model(c)
        model_counts[m] = model_counts.get(m, 0) + 1
    total = sum(model_counts.values())
    mix_parts = " · ".join(f"{m}: {n}" for m, n in sorted(model_counts.items(), key=lambda x: -x[1]))

    return f"""
    <div class="card">
      <h2>Conversation Cost Ranking (Estimated)</h2>
      <p style="font-size:.75rem;color:var(--muted);margin-bottom:10px">
        Ranked by model weight x duration. Longer Opus conversations cost more.
      </p>
      {rows}
      <div style="font-size:.75rem;color:var(--muted);margin-top:12px;padding-top:8px;border-top:1px solid var(--border)">
        Model mix (last {total}): {mix_parts}
      </div>
    </div>"""


def _optimal_timing_html(stats):
    """Show optimal timing insights based on day-of-week and burn patterns."""
    if not stats:
        return ""
    patterns = stats.get("day_patterns")
    if not patterns or len(patterns) < 5:
        return ""

    today = datetime.now().weekday()
    sorted_days = sorted(patterns.items(), key=lambda x: x[1])
    lightest_dow, lightest_val = sorted_days[0]
    heaviest_dow, heaviest_val = sorted_days[-1]

    overall_avg = sum(patterns.values()) / len(patterns)

    # Build heatmap-style row
    cells = ""
    for dow in range(7):
        val = patterns.get(dow, 0)
        if val > overall_avg * 1.4:
            bg = "rgba(239,68,68,0.2)"
            border = "#ef4444"
        elif val > overall_avg * 0.8:
            bg = "rgba(245,158,11,0.15)"
            border = "#f59e0b"
        else:
            bg = "rgba(34,197,94,0.15)"
            border = "#22c55e"
        is_today = "2px solid var(--accent)" if dow == today else f"1px solid {border}"
        today_label = "<div style='font-size:.55rem;color:var(--accent)'>TODAY</div>" if dow == today else ""
        cells += f"""
        <div style="flex:1;text-align:center;padding:8px 4px;background:{bg};border:{is_today};border-radius:6px">
          <div style="font-size:.7rem;color:var(--muted)">{DOW_SHORT[dow]}</div>
          <div style="font-size:1rem;font-weight:700">{val:.1f}%</div>
          {today_label}
        </div>"""

    # Actionable insight
    days_to_lightest = (lightest_dow - today) % 7
    days_to_heaviest = (heaviest_dow - today) % 7

    insights = []
    if days_to_lightest == 0:
        insights.append("Today is typically your lightest day — great time for complex Opus work.")
    elif days_to_lightest <= 2:
        insights.append(f"{DOW_NAMES[lightest_dow]} is your lightest day — save Opus-heavy work for then.")

    if days_to_heaviest == 0:
        insights.append("Today is typically your heaviest day — consider front-loading important work early.")
    elif days_to_heaviest == 1:
        insights.append(f"Tomorrow ({DOW_NAMES[heaviest_dow]}) is typically heavy — plan accordingly.")

    # Budget recommendation based on today's pattern
    today_expected = patterns.get(today, overall_avg)
    burn_rate = stats.get("burn_per_day", 0)
    budget = stats.get("daily_budget", 0)
    if today_expected > overall_avg * 1.3 and budget > 0:
        insights.append(f"Today's typical burn ({today_expected:.1f}%) exceeds your avg ({overall_avg:.1f}%). Budget: {budget:.1f}%/day to stay safe.")

    insights_html = "".join(f"<li style='margin-bottom:4px'>{i}</li>" for i in insights) if insights else "<li>Your usage is evenly distributed — no strong patterns yet.</li>"

    return f"""
    <div class="card">
      <h2>Optimal Timing</h2>
      <p style="font-size:.75rem;color:var(--muted);margin-bottom:10px">
        Average daily burn rate by day of week. Plan heavy work on green days.
      </p>
      <div style="display:flex;gap:4px;margin-bottom:14px">
        {cells}
      </div>
      <ul style="font-size:.85rem;padding-left:18px;line-height:1.7;color:var(--text)">
        {insights_html}
      </ul>
    </div>"""


def _power_user_dashboard_html(usage, stats, velocity, runway, msg_est):
    """Render the power-user analytics section of the dashboard."""
    sections = []

    # Live Pace card
    if velocity and velocity["session_velocity"] > 0.1:
        s_vel = velocity["session_velocity"]
        w_vel = velocity["weekly_velocity"]
        s_delta = velocity["session_delta"]
        w_delta = velocity["weekly_delta"]

        # Pace indicator
        if s_vel > 20:
            pace_icon, pace_label, pace_color = "🔥", "Sprinting", "#ef4444"
        elif s_vel > 8:
            pace_icon, pace_label, pace_color = "🟡", "Moderate", "#f59e0b"
        else:
            pace_icon, pace_label, pace_color = "🟢", "Cruising", "#22c55e"

        delta_s_str = f"+{s_delta:.1f}%" if s_delta > 0 else f"{s_delta:.1f}%"
        delta_w_str = f"+{w_delta:.1f}%" if w_delta > 0 else f"{w_delta:.1f}%"

        sections.append(f"""
        <div class="card">
          <h2>Live Pace</h2>
          <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px">
            <span style="font-size:2rem">{pace_icon}</span>
            <div>
              <div class="big" style="font-size:1.6rem;color:{pace_color}">{pace_label}</div>
              <div class="label">{s_vel:.1f}%/hr session · {w_vel:.1f}%/hr weekly</div>
            </div>
          </div>
          <div style="display:flex;gap:24px;font-size:.85rem;color:var(--muted)">
            <span>Session delta: <b style="color:var(--text)">{delta_s_str}</b></span>
            <span>Weekly delta: <b style="color:var(--text)">{delta_w_str}</b></span>
          </div>
        </div>""")

    # Runway card
    if runway:
        sr = _fmt_runway(runway.get("session_runway_min"))
        wr = _fmt_runway(runway.get("weekly_runway_min"))
        if sr or wr:
            items = []
            if sr:
                sr_min = runway["session_runway_min"]
                sr_color = "#ef4444" if sr_min < 30 else "#f59e0b" if sr_min < 120 else "#22c55e"
                items.append(f"""
                <div style="flex:1;text-align:center;padding:12px;background:var(--bg);border-radius:8px">
                  <div style="font-size:1.6rem;font-weight:700;color:{sr_color}">~{sr}</div>
                  <div class="label">until session limit</div>
                </div>""")
            if wr:
                wr_min = runway["weekly_runway_min"]
                wr_color = "#ef4444" if wr_min < 1440 else "#f59e0b" if wr_min < 4320 else "#22c55e"
                items.append(f"""
                <div style="flex:1;text-align:center;padding:12px;background:var(--bg);border-radius:8px">
                  <div style="font-size:1.6rem;font-weight:700;color:{wr_color}">~{wr}</div>
                  <div class="label">until weekly limit</div>
                </div>""")
            sections.append(f"""
            <div class="card">
              <h2>Runway — At Current Pace</h2>
              <div style="display:flex;gap:12px">{"".join(items)}</div>
              <p style="font-size:.75rem;color:var(--muted);margin-top:10px">Based on your burn rate over the last 30 minutes</p>
            </div>""")

    # Messages remaining card
    if msg_est:
        s_msgs = msg_est["session_msgs_left"]
        w_msgs = msg_est["weekly_msgs_left"]
        samples = msg_est["sample_size"]
        avg_cost = msg_est["avg_cost_per_msg"]

        s_color = "#ef4444" if s_msgs < 5 else "#f59e0b" if s_msgs < 15 else "#22c55e"
        w_color = "#ef4444" if w_msgs < 10 else "#f59e0b" if w_msgs < 30 else "#22c55e"

        sections.append(f"""
        <div class="card">
          <h2>Messages Remaining (Estimate)</h2>
          <div style="display:flex;gap:12px">
            <div style="flex:1;text-align:center;padding:12px;background:var(--bg);border-radius:8px">
              <div style="font-size:2rem;font-weight:700;color:{s_color}">~{s_msgs}</div>
              <div class="label">this session</div>
            </div>
            <div style="flex:1;text-align:center;padding:12px;background:var(--bg);border-radius:8px">
              <div style="font-size:2rem;font-weight:700;color:{w_color}">~{w_msgs}</div>
              <div class="label">this week</div>
            </div>
          </div>
          <p style="font-size:.75rem;color:var(--muted);margin-top:10px">
            Based on {samples} recent interactions (avg {avg_cost:.1f}% per message).
            Actual count varies by message length and model.
          </p>
        </div>""")

    if not sections:
        return ""

    return f"""
    <div style="margin-bottom:16px">
      <h2 style="font-size:.8rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:12px">
        Live Intelligence
      </h2>
      {"".join(sections)}
    </div>"""


def generate_dashboard(usage, stats, conversations=None):
    spct     = usage["session_pct"]
    wpct     = usage["weekly_pct"]
    sreset   = _fmt_reset(usage.get("session_resets_at", ""))
    wreset   = _fmt_reset(usage.get("weekly_resets_at",  ""))
    eu       = usage.get("extra_used")
    el       = usage.get("extra_limit")
    tip      = _tip(usage, stats)
    now_str  = datetime.now().strftime("%b %d, %Y  %I:%M %p")

    # Colour for weekly bar
    if wpct >= 85:
        w_color = "#ef4444"
    elif wpct >= 60:
        w_color = "#f59e0b"
    else:
        w_color = "#0D9488"

    # Projection line
    if stats and stats["projected_full"]:
        pf = stats["projected_full"]
        days_away = (pf - datetime.now(timezone.utc)).total_seconds() / 86400
        if days_away < 1:
            proj_str = f"⚠️ Weekly limit projected in <b>{days_away*24:.0f} hours</b>"
        else:
            proj_str = f"Weekly limit projected in <b>{days_away:.1f} days</b> ({pf.strftime('%A %b %d')})"
        proj_color = "#ef4444" if stats["hits_limit"] else "#6b7280"
    else:
        proj_str   = "Not enough data for projection yet"
        proj_color = "#6b7280"

    # Chart data
    if stats and len(stats["chart_labels"]) > 1:
        chart_labels = json.dumps(
            [datetime.fromisoformat(l).strftime("%-I%p %-m/%-d") for l in stats["chart_labels"]]
        )
        chart_values = json.dumps(stats["chart_values"])
        chart_html = f"""
        <div class="card">
          <h2>Weekly Usage Over Time</h2>
          <canvas id="chart" height="90"></canvas>
        </div>
        <script>
        try {{ new Chart(document.getElementById('chart'), {{
          type: 'line',
          data: {{
            labels: {chart_labels},
            datasets: [{{
              label: 'Weekly %',
              data: {chart_values},
              borderColor: '#0D9488',
              backgroundColor: 'rgba(13,148,136,0.1)',
              borderWidth: 2,
              pointRadius: 2,
              fill: true,
              tension: 0.3,
            }}]
          }},
          options: {{
            plugins: {{ legend: {{ display: false }} }},
            scales: {{
              y: {{ min: 0, max: 100, ticks: {{ callback: v => v + '%' }} }},
              x: {{ ticks: {{ maxTicksLimit: 8 }} }}
            }}
          }}
        }}); }} catch(e) {{ console.warn('Chart error:', e); }}
        </script>"""
    else:
        chart_html = """
        <div class="card muted">
          <h2>Weekly Usage Over Time</h2>
          <p>Chart will appear after a few hours of data collection.</p>
        </div>"""

    # Stats cards
    if stats:
        burn_str   = f"{stats['burn_per_day']:.1f}% / day"
        budget_str = f"{stats['daily_budget']:.1f}% / day"
        reset_str  = f"{stats['days_until_reset']:.1f} days"
    else:
        burn_str = budget_str = reset_str = "—"

    # Day-of-week pattern chart
    patterns = stats.get("day_patterns") if stats else None
    if patterns and len(patterns) >= 5:
        today = datetime.now().weekday()
        dow_labels = json.dumps([DOW_SHORT[i] for i in range(7)])
        dow_values = json.dumps([round(patterns.get(i, 0), 2) for i in range(7)])
        dow_colors = json.dumps([
            "#0D9488" if i == max(patterns, key=patterns.get)
            else "#93c5fd" if i == today
            else "#e5e7eb"
            for i in range(7)
        ])
        heaviest_day = DOW_NAMES[max(patterns, key=patterns.get)]
        pattern_html = f"""
        <div class="card">
          <h2>Usage by Day of Week <span style="font-weight:400;color:var(--muted)">(avg % burned)</span></h2>
          <canvas id="dowchart" height="80"></canvas>
          <p style="font-size:.8rem;color:var(--muted);margin-top:12px">
            Heaviest day: <b>{heaviest_day}</b> &nbsp;·&nbsp; Blue bar = today
          </p>
        </div>
        <script>
        try {{ new Chart(document.getElementById('dowchart'), {{
          type: 'bar',
          data: {{
            labels: {dow_labels},
            datasets: [{{
              data: {dow_values},
              backgroundColor: {dow_colors},
              borderRadius: 6,
            }}]
          }},
          options: {{
            plugins: {{ legend: {{ display: false }} }},
            scales: {{
              y: {{ min: 0, ticks: {{ callback: v => v + '%' }} }},
              x: {{ grid: {{ display: false }} }}
            }}
          }}
        }}); }} catch(e) {{ console.warn('Chart error:', e); }}
        </script>"""
    else:
        days_needed = 7 - (len(patterns) if patterns else 0)
        pattern_html = f"""
        <div class="card muted">
          <h2>Usage by Day of Week</h2>
          <p>Pattern chart appears after {days_needed} more day{"s" if days_needed != 1 else ""} of data.</p>
        </div>"""

    extra_html = ""
    if eu is not None and el:
        epct     = eu / el * 100
        eu_usd   = eu / CREDITS_PER_DOLLAR
        el_usd   = el / CREDITS_PER_DOLLAR
        extra_html = f"""
        <div class="card">
          <h2>Extra Usage</h2>
          <div class="big" style="font-size:1.6rem">${eu_usd:.2f}</div>
          <div class="label">of ${el_usd:.2f} monthly cap</div>
          <div class="bar-wrap" style="margin-top:10px">
            <div class="bar" style="width:{min(epct,100):.1f}%;background:#6366f1"></div>
          </div>
          <div class="bar-labels">
            <span>{epct:.1f}% used</span><span>${el_usd:.2f} max</span>
          </div>
        </div>"""

    per_model_html = _per_model_html(usage)

    session_rows = load_session_history()
    sessions = _detect_sessions(session_rows)
    session_html = _session_history_html(sessions)

    conversations_html = _conversations_dashboard_html(conversations)

    # Power-user analytics
    history_rows = load_history()
    velocity = calc_velocity(history_rows)
    runway = calc_runway(usage, velocity)
    msg_est = estimate_messages_remaining(usage, history_rows)
    power_user_html = _power_user_dashboard_html(usage, stats, velocity, runway, msg_est)

    # Smart suggestion banner
    suggestion = smart_suggestion(usage, stats, velocity)
    if suggestion:
        s_emoji, s_text = suggestion
        suggestion_html = f"""
        <div style="background:var(--surface);border:1px solid var(--border);border-left:3px solid var(--accent);
                    border-radius:var(--radius);padding:14px 16px;margin-bottom:16px;font-size:.9rem;
                    display:flex;align-items:center;gap:10px">
          <span style="font-size:1.3rem">{s_emoji}</span>
          <span>{s_text}</span>
        </div>"""
    else:
        suggestion_html = ""

    # Conversation insights and optimal timing
    conv_insights_html = _conversation_insights_html(conversations)
    timing_html = _optimal_timing_html(stats)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ClaudeWatch Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  :root{{
    --bg:#f5f5f5;--surface:#fff;--text:#1a1a1a;--muted:#6b7280;
    --accent:#0D9488;--border:#e5e7eb;--radius:12px;
  }}
  @media(prefers-color-scheme:dark){{
    :root{{--bg:#111;--surface:#1c1c1e;--text:#f5f5f5;--muted:#9ca3af;--border:#2d2d2d}}
  }}
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
        background:var(--bg);color:var(--text);padding:24px;max-width:720px;margin:0 auto}}
  h1{{font-size:1.4rem;font-weight:700;display:flex;align-items:center;gap:8px;margin-bottom:4px}}
  .sub{{color:var(--muted);font-size:.85rem;margin-bottom:24px}}
  .grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px}}
  @media(max-width:500px){{.grid{{grid-template-columns:1fr}}}}
  .card{{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
         padding:18px}}
  .card h2{{font-size:.8rem;font-weight:600;color:var(--muted);text-transform:uppercase;
            letter-spacing:.05em;margin-bottom:12px}}
  .big{{font-size:2.2rem;font-weight:700;line-height:1;margin-bottom:4px}}
  .label{{font-size:.8rem;color:var(--muted)}}
  .bar-wrap{{background:var(--border);border-radius:99px;height:8px;overflow:hidden;margin:10px 0 6px}}
  .bar{{height:100%;border-radius:99px;transition:width .4s ease}}
  .bar-labels{{display:flex;justify-content:space-between;font-size:.75rem;color:var(--muted)}}
  .stats{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:16px}}
  @media(max-width:500px){{.stats{{grid-template-columns:1fr 1fr}}}}
  .stat{{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
         padding:14px}}
  .stat .val{{font-size:1.4rem;font-weight:700;margin-bottom:2px}}
  .stat .lbl{{font-size:.75rem;color:var(--muted)}}
  .tip{{background:var(--surface);border:1px solid var(--border);border-left:3px solid var(--accent);
        border-radius:var(--radius);padding:16px;margin-bottom:16px;font-size:.9rem;line-height:1.5}}
  .proj{{font-size:.85rem;color:{proj_color};margin-top:4px}}
  .muted p{{color:var(--muted);font-size:.9rem;padding:12px 0}}
  .footer{{text-align:center;font-size:.75rem;color:var(--muted);margin-top:24px}}
  .reset-badge{{font-size:.75rem;color:var(--muted);margin-top:4px}}
  .model-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}
  @media(max-width:500px){{.model-grid{{grid-template-columns:1fr}}}}
  .model-card{{background:var(--surface);border-radius:var(--radius);padding:14px}}
  .model-name{{font-size:.95rem;font-weight:700;margin-bottom:2px}}
  .model-sub{{font-size:.75rem;color:var(--muted);margin-bottom:10px}}
  .model-tasks{{font-size:.8rem;padding-left:18px;line-height:1.7;color:var(--text)}}
  .model-tasks li{{margin-bottom:2px}}
  .session-row{{display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--border)}}
  .session-row:last-child{{border-bottom:none}}
  .session-dot{{width:8px;height:8px;border-radius:50%;flex-shrink:0}}
  .conv-table{{width:100%;border-collapse:collapse;font-size:.85rem}}
  .conv-table th{{text-align:left;color:var(--muted);font-weight:600;padding:8px 6px;border-bottom:2px solid var(--border)}}
  .conv-table td{{padding:8px 6px;border-bottom:1px solid var(--border)}}
  .conv-table tr:hover td{{background:rgba(13,148,136,0.05)}}
  .conv-table a{{color:var(--accent);text-decoration:none}}
  .conv-table a:hover{{text-decoration:underline}}
</style>
</head>
<body>
<h1>
  <svg width="20" height="20" viewBox="0 0 100 100" fill="none">
    <circle cx="50" cy="50" r="48" fill="#0D9488"/>
    <text x="50" y="67" text-anchor="middle" font-size="52" fill="white" font-family="-apple-system">◈</text>
  </svg>
  ClaudeWatch
</h1>
<p class="sub">Updated {now_str}</p>

<div class="tip">{tip}</div>

<div class="grid">
  <div class="card">
    <h2>Session Usage (5h)</h2>
    <div class="big">{spct:.0f}%</div>
    <div class="bar-wrap"><div class="bar" style="width:{min(spct,100):.1f}%;background:#0D9488"></div></div>
    <div class="bar-labels"><span>used</span><span>100%</span></div>
    <div class="reset-badge">{f"resets in {sreset}" if sreset else ""}</div>
  </div>
  <div class="card">
    <h2>Weekly Usage (7d)</h2>
    <div class="big" style="color:{w_color}">{wpct:.0f}%</div>
    <div class="bar-wrap"><div class="bar" style="width:{min(wpct,100):.1f}%;background:{w_color}"></div></div>
    <div class="bar-labels"><span>used</span><span>100%</span></div>
    <div class="reset-badge">{f"resets in {wreset}" if wreset else ""}</div>
    <div class="proj">{proj_str}</div>
  </div>
</div>

<div class="stats">
  <div class="stat">
    <div class="val">{burn_str}</div>
    <div class="lbl">Burn rate</div>
  </div>
  <div class="stat">
    <div class="val">{budget_str}</div>
    <div class="lbl">Daily budget to stay safe</div>
  </div>
  <div class="stat">
    <div class="val">{reset_str}</div>
    <div class="lbl">Days until weekly reset</div>
  </div>
</div>

{suggestion_html}
{power_user_html}
{extra_html}
{per_model_html}
{session_html}
{chart_html}
{pattern_html}
{timing_html}
{conv_insights_html}
{conversations_html}
{_model_guide_html(usage, stats)}

<div class="footer">ClaudeWatch · data from Claude desktop app · <a href="{CLAUDE_USAGE_URL}" style="color:var(--accent)">open claude.ai</a></div>
</body>
</html>"""

    DASH_PATH.write_text(html, encoding="utf-8")
    return str(DASH_PATH)


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
        dt   = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
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


def _relative_time(iso_str):
    """Convert ISO timestamp to relative time like '2h ago', 'yesterday', 'Mar 15'."""
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = now - dt
        secs = int(diff.total_seconds())
        if secs < 60:
            return "just now"
        if secs < 3600:
            return f"{secs // 60}m ago"
        if secs < 86400:
            return f"{secs // 3600}h ago"
        if secs < 172800:
            return "yesterday"
        if secs < 604800:
            return f"{secs // 86400}d ago"
        return dt.strftime("%b %d")
    except Exception:
        return ""


def _build_conversations_html(conversations):
    """Generate styled HTML table of recent conversations."""
    rows_html = ""
    for c in conversations:
        name = c.get("name", "Untitled") or "Untitled"
        if len(name) > 60:
            name = name[:57] + "..."
        _, model = _get_conversation_model(c)
        project = (c.get("project") or {}).get("name", "—") or "—"
        updated = _relative_time(c.get("updated_at", ""))
        uuid = c.get("uuid", "")
        link = f"https://claude.ai/chat/{uuid}"
        rows_html += f"""<tr>
            <td><a href="{link}" target="_blank">{name}</a></td>
            <td>{model}</td>
            <td>{project}</td>
            <td>{updated}</td>
        </tr>\n"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>ClaudeWatch — Recent Conversations</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       margin: 2rem; background: #1a1a2e; color: #e0e0e0; }}
h1 {{ color: #d4a574; font-size: 1.4rem; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 1rem; }}
th {{ text-align: left; padding: 0.6rem 1rem; background: #16213e;
     color: #d4a574; font-size: 0.85rem; text-transform: uppercase; }}
td {{ padding: 0.6rem 1rem; border-bottom: 1px solid #2a2a4a; font-size: 0.9rem; }}
tr:hover {{ background: #16213e; }}
a {{ color: #7eb8da; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
</style></head><body>
<h1>Recent Conversations</h1>
<table>
<thead><tr><th>Name</th><th>Model</th><th>Project</th><th>Updated</th></tr></thead>
<tbody>{rows_html}</tbody>
</table></body></html>"""


SPARKLINE_CHARS = "▁▂▃▄▅▆▇█"


def _sparkline(values, width=6):
    """Build a tiny sparkline string from a list of numeric values."""
    if not values or len(values) < 2:
        return ""
    recent = values[-width:]
    lo, hi = min(recent), max(recent)
    spread = hi - lo
    if spread < 0.5:
        # Flat line — all same level
        idx = min(int(lo / 100 * (len(SPARKLINE_CHARS) - 1)), len(SPARKLINE_CHARS) - 1)
        return SPARKLINE_CHARS[idx] * len(recent)
    return "".join(
        SPARKLINE_CHARS[min(int((v - lo) / spread * (len(SPARKLINE_CHARS) - 1)), len(SPARKLINE_CHARS) - 1)]
        for v in recent
    )


def _build_title(usage, config, velocity=None, recent_session_pcts=None):
    if usage is None:
        return "!"
    display_size = config.get("display_size", "full")
    # Minimal mode: icon only, no text
    if display_size == "minimal":
        return ""
    full_detail = display_size in ("full", "custom")
    parts = []
    if config.get("show_session_pct"):
        s_str = f"{usage['session_pct']:.0f}%"
        if full_detail:
            if velocity and abs(velocity["session_delta"]) >= 0.1:
                d = velocity["session_delta"]
                s_str += f"+{d:.0f}" if d > 0 else f"{d:.0f}"
        parts.append(s_str)
    if config.get("show_weekly_pct"):
        w_str = f"{usage['weekly_pct']:.0f}%"
        if full_detail:
            if velocity and abs(velocity["weekly_delta"]) >= 0.1:
                d = velocity["weekly_delta"]
                w_str += f"+{d:.0f}" if d > 0 else f"{d:.0f}"
        parts.append(w_str)
    title = " | ".join(parts) if parts else "◈"
    if full_detail:
        if config.get("show_reset_time"):
            reset = _fmt_reset(usage.get("session_resets_at", ""))
            if reset:
                title += f"  ↺{reset}"
        # Sparkline appended last so it doesn't push reset time off screen
        if config.get("show_sparkline", True) and config.get("show_session_pct") and recent_session_pcts and len(recent_session_pcts) >= 3:
            title += _sparkline(recent_session_pcts)
        extra_pct = usage.get("extra_pct")
        if extra_pct is not None and usage.get("extra_enabled"):
            if extra_pct >= 95:
                title += " 🚨"
            elif extra_pct >= 80:
                title += " ⚠️"
    return title


def _build_tooltip(usage, velocity=None, runway=None, msg_est=None):
    if usage is None:
        return "ClaudeWatch — no data"
    spct = usage.get("session_pct", 0)
    wpct = usage.get("weekly_pct",  0)
    sr   = _fmt_reset(usage.get("session_resets_at", ""))
    wr   = _fmt_reset(usage.get("weekly_resets_at",  ""))
    lines = [
        "ClaudeWatch",
        f"Session (5h):  {spct:.0f}%" + (f"  —  resets in {sr}" if sr else ""),
        f"Weekly  (7d):  {wpct:.0f}%" + (f"  —  resets in {wr}" if wr else ""),
    ]
    # Velocity
    if velocity and velocity["session_velocity"] > 0.1:
        lines.append(f"Pace:  {velocity['session_velocity']:.1f}%/hr session, {velocity['weekly_velocity']:.1f}%/hr weekly")
    # Runway
    if runway:
        parts = []
        sr_run = _fmt_runway(runway.get("session_runway_min"))
        wr_run = _fmt_runway(runway.get("weekly_runway_min"))
        if sr_run:
            parts.append(f"session limit in ~{sr_run}")
        if wr_run:
            parts.append(f"weekly limit in ~{wr_run}")
        if parts:
            lines.append("Runway:  " + ", ".join(parts))
    # Messages remaining
    if msg_est:
        lines.append(f"~{msg_est['session_msgs_left']} msgs left in session, ~{msg_est['weekly_msgs_left']} this week")
    # Per-model breakdowns
    for label, info in usage.get("per_model", {}).items():
        pct = info["utilization"]
        lines.append(f"  {label}:  {pct:.0f}%")
    # Extra credits
    eu = usage.get("extra_used")
    el = usage.get("extra_limit")
    if eu is not None and el:
        extra_pct = usage.get("extra_pct") or 0
        warn = "⚠️ " if extra_pct >= 90 else ""
        lines.append(f"{warn}Extra usage:  ${eu/CREDITS_PER_DOLLAR:.2f} / ${el/CREDITS_PER_DOLLAR:.2f} ({extra_pct:.0f}%)")
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

        self.config          = load_config()
        self._usage          = None
        self._stats          = None
        self._conversations  = None
        self._notified = set()            # keys like "session_75", "weekly_90", "extra_80"
        self._last_session_reset = None   # track session resets_at to clear session keys

        if DEPS_OK:
            init_db()

        # Settings checkmark items
        self._s_session   = rumps.MenuItem("Session % (5h)", callback=self._toggle("show_session_pct"))
        self._s_weekly    = rumps.MenuItem("Weekly % (7d)",  callback=self._toggle("show_weekly_pct"))
        self._s_reset     = rumps.MenuItem("Reset time",     callback=self._toggle("show_reset_time"))
        self._s_sparkline = rumps.MenuItem("Sparkline",      callback=self._toggle("show_sparkline"))
        self._s_tooltip   = rumps.MenuItem("Hover tooltip",  callback=self._toggle("show_hover_tooltip"))
        self._s_notif     = rumps.MenuItem("Notifications",  callback=self._toggle("notifications_enabled"))
        self._sync_checkmarks()

        # Display size submenu
        self._display_size_items = {}
        display_size_menu = rumps.MenuItem("Display size")
        size_labels = {"full": "Full — all details", "compact": "Compact — % only", "minimal": "Minimal — icon only", "custom": "Custom"}
        for size_key in DISPLAY_SIZE_OPTIONS:
            cb = None if size_key == "custom" else self._set_display_size(size_key)
            item = rumps.MenuItem(size_labels[size_key], callback=cb)
            self._display_size_items[size_key] = item
            display_size_menu.add(item)
        self._sync_display_size_checkmark()

        settings = rumps.MenuItem("Settings")
        settings.update([
            rumps.MenuItem("Show in menu bar:", callback=None),
            self._s_session,
            self._s_weekly,
            self._s_reset,
            self._s_sparkline,
            None,
            display_size_menu,
            None,
            self._s_tooltip,
            self._s_notif,
        ])

        # Model guide submenu
        def _info(label):
            return rumps.MenuItem(label, callback=None)

        haiku = rumps.MenuItem("Haiku — fast & cheap")
        haiku.update([
            _info("  • Quick Q&A and lookups"),
            _info("  • Summarisation"),
            _info("  • Translation"),
            _info("  • Simple edits & rewrites"),
            _info("  • High-volume / repetitive tasks"),
        ])

        sonnet = rumps.MenuItem("Sonnet — best for most tasks  ★")
        sonnet.update([
            _info("  • Coding & debugging"),
            _info("  • Writing & long-form editing"),
            _info("  • Data analysis & research"),
            _info("  • Complex instructions"),
            _info("  • Most everyday tasks"),
        ])

        opus = rumps.MenuItem("Opus — deep reasoning")
        opus.update([
            _info("  • Hard math & logic"),
            _info("  • Multi-step planning"),
            _info("  • Novel / open-ended problems"),
            _info("  • Architecture & system design"),
            _info("  • When Sonnet isn't cutting it"),
        ])

        model_guide = rumps.MenuItem("Model Guide")
        model_guide.update([haiku, sonnet, opus])

        # Refresh interval submenu
        self._refresh_items = {}
        refresh_menu = rumps.MenuItem("Refresh every…")
        for mins in REFRESH_OPTIONS:
            label = f"{mins} minute{'s' if mins > 1 else ''}"
            item = rumps.MenuItem(label, callback=self._set_refresh(mins))
            self._refresh_items[mins] = item
            refresh_menu.add(item)
        self._sync_refresh_checkmark()

        self.menu = [
            rumps.MenuItem("Open Claude Usage",      callback=self.open_usage),
            rumps.MenuItem("View Dashboard",         callback=self.open_dashboard),
            rumps.MenuItem("Recent Conversations",   callback=self.open_conversations),
            None,
            rumps.MenuItem("⬤  Session (5h)",   callback=None),
            rumps.MenuItem("   —",               callback=None),
            rumps.MenuItem("   session_runway",  callback=None),
            rumps.MenuItem("⬤  Weekly (7d)",    callback=None),
            rumps.MenuItem("   —  ",             callback=None),
            rumps.MenuItem("   weekly_runway",   callback=None),
            rumps.MenuItem("   per_model_line",  callback=None),
            rumps.MenuItem("   extra_credits",   callback=None),
            None,
            rumps.MenuItem("   velocity_line",   callback=None),
            rumps.MenuItem("   msgs_remaining",  callback=None),
            rumps.MenuItem("   suggestion_line", callback=None),
            None,
            model_guide,
            settings,
            refresh_menu,
            rumps.MenuItem("Refresh Now",        callback=self.manual_refresh),
            None,
            rumps.MenuItem("Restart",            callback=self.restart_app),
            rumps.MenuItem("Quit",               callback=self.quit_app),
        ]

        # Hide dynamic items initially
        for key in ("   per_model_line", "   extra_credits",
                    "   session_runway", "   weekly_runway",
                    "   velocity_line", "   msgs_remaining", "   suggestion_line"):
            self.menu[key].hidden = True

        if DEPS_OK:
            self._start_timer()
            threading.Thread(target=self._refresh, daemon=True).start()

        # First-run: offer login item when running as bundled .app
        if getattr(_sys, 'frozen', False):
            _plist = Path.home() / "Library/LaunchAgents/com.katespurr.claudewatch.plist"
            if not _plist.exists():
                self._first_run_timer = rumps.Timer(self._prompt_login_item, 1.5)
                self._first_run_timer.start()

    def _prompt_login_item(self, timer):
        timer.stop()
        response = rumps.alert(
            title="Welcome to ClaudeWatch",
            message="Start ClaudeWatch automatically when you log in?",
            ok="Yes, start at login",
            cancel="Not now",
        )
        if response == 1:
            executable = Path(_sys.executable).parent / "ClaudeWatch"
            plist_file = Path.home() / "Library/LaunchAgents/com.katespurr.claudewatch.plist"
            plist_file.parent.mkdir(parents=True, exist_ok=True)
            plist_file.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.katespurr.claudewatch</string>
    <key>ProgramArguments</key>
    <array>
        <string>{executable}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{CONFIG_DIR}/stdout.log</string>
    <key>StandardErrorPath</key>
    <string>{CONFIG_DIR}/stderr.log</string>
</dict>
</plist>""")
            subprocess.run(["launchctl", "load", str(plist_file)], check=False)
            rumps.notification("ClaudeWatch", "Login item installed",
                               "ClaudeWatch will start automatically at login.")

    # ── Settings ──

    def _toggle(self, key):
        def callback(_):
            self.config[key] = not self.config.get(key, True)
            # Auto-detect preset match, or fall back to "custom"
            _preset_keys = ("show_session_pct", "show_weekly_pct", "show_reset_time", "show_sparkline")
            current = {k: bool(self.config.get(k)) for k in _preset_keys}
            matched = next((s for s, p in self._DISPLAY_SIZE_PRESETS.items() if p == current), "custom")
            self.config["display_size"] = matched
            save_config(self.config)
            self._sync_checkmarks()
            self._sync_display_size_checkmark()
            if self._usage:
                self._apply_ui(self._usage)
        return callback

    def _sync_checkmarks(self):
        self._s_session.state   = int(bool(self.config.get("show_session_pct",   True)))
        self._s_weekly.state    = int(bool(self.config.get("show_weekly_pct",    True)))
        self._s_reset.state     = int(bool(self.config.get("show_reset_time",    False)))
        self._s_sparkline.state = int(bool(self.config.get("show_sparkline",     True)))
        self._s_tooltip.state   = int(bool(self.config.get("show_hover_tooltip", True)))
        self._s_notif.state     = int(bool(self.config.get("notifications_enabled", True)))

    # ── Display size ──

    _DISPLAY_SIZE_PRESETS = {
        "full":    {"show_session_pct": True,  "show_weekly_pct": True,  "show_reset_time": True,  "show_sparkline": True},
        "compact": {"show_session_pct": True,  "show_weekly_pct": True,  "show_reset_time": False, "show_sparkline": False},
        "minimal": {"show_session_pct": False, "show_weekly_pct": False, "show_reset_time": False, "show_sparkline": False},
    }

    def _set_display_size(self, size_key):
        def callback(_):
            self.config["display_size"] = size_key
            self.config.update(self._DISPLAY_SIZE_PRESETS[size_key])
            save_config(self.config)
            self._sync_display_size_checkmark()
            self._sync_checkmarks()
            if self._usage:
                self._apply_ui(self._usage)
        return callback

    def _sync_display_size_checkmark(self):
        current = self.config.get("display_size", "full")
        for key, item in self._display_size_items.items():
            item.state = int(key == current)

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

    @rumps.clicked("View Dashboard")
    def open_dashboard(self, _):
        if self._usage:
            path = generate_dashboard(self._usage, self._stats, getattr(self, "_conversations", None))
            webbrowser.open(f"file://{path}")
        else:
            rumps.notification("ClaudeWatch", "No data yet", "Fetching usage now…")
            threading.Thread(target=self._refresh, daemon=True).start()

    @rumps.clicked("Recent Conversations")
    def open_conversations(self, sender):
        sender.title = "Loading..."
        threading.Thread(target=self._fetch_conversations, args=(sender,), daemon=True).start()

    def _fetch_conversations(self, sender):
        try:
            data = self._fetch_conversations_data()
            html = _build_conversations_html(data)
            path = CONFIG_DIR / "conversations.html"
            path.write_text(html)
            webbrowser.open(f"file://{path}")
        except Exception as e:
            rumps.notification("ClaudeWatch", "Error loading conversations", str(e)[:100])
        finally:
            sender.title = "Recent Conversations"

    @rumps.clicked("Refresh Now")
    def manual_refresh(self, _):
        threading.Thread(target=self._refresh, daemon=True).start()

    @rumps.clicked("Quit")
    def quit_app(self, _):
        rumps.quit_application()

    def restart_app(self, _):
        rumps.notification("ClaudeWatch", "Restarting…", "")
        rumps.quit_application()

    # ── Refresh interval ──

    def _set_refresh(self, minutes):
        def callback(_):
            self.config["refresh_interval_minutes"] = minutes
            save_config(self.config)
            self._sync_refresh_checkmark()
            self._restart_timer()
        return callback

    def _sync_refresh_checkmark(self):
        current = self.config.get("refresh_interval_minutes", 5)
        for mins, item in self._refresh_items.items():
            item.state = int(mins == current)

    def _restart_timer(self):
        if hasattr(self, "_timer") and self._timer:
            self._timer.stop()
        interval = self.config.get("refresh_interval_minutes", 5) * 60
        self._timer = rumps.Timer(self._on_timer, interval)
        self._timer.start()

    def _on_timer(self, _):
        threading.Thread(target=self._refresh, daemon=True).start()

    def _start_timer(self):
        self._restart_timer()

    @staticmethod
    def _extract_actual_model(detail):
        """Extract the actual model used from a conversation detail response.

        Checks the last assistant message for a model field, then falls back
        to conversation-level fields like model_override or settings.model.
        """
        # Check last assistant message first (most accurate)
        msgs = detail.get("chat_messages") or []
        for msg in reversed(msgs):
            if msg.get("sender") == "assistant":
                m = msg.get("model")
                if m:
                    return m
                break

        # Conversation-level overrides
        m = detail.get("model_override")
        if m:
            return m
        settings = detail.get("settings") or {}
        m = settings.get("model") or settings.get("preview_model")
        if m:
            return m
        m = detail.get("active_model")
        if m:
            return m
        # Top-level model field (most common in current API)
        m = detail.get("model")
        if m:
            return m
        return ""

    def _fetch_conversations_data(self):
        """Fetch conversation list from Claude API, enriched with actual model used."""
        import json as _json
        import traceback as _tb
        from concurrent.futures import ThreadPoolExecutor, as_completed

        debug_log = CONFIG_DIR / "model_debug.json"
        debug_info = {"stage": "init"}

        try:
            cookies = get_claude_cookies()
            org_id = cookies.get("lastActiveOrg", "")
            session = _make_session(cookies)
            debug_info["stage"] = "fetching_list"
            resp = session.get(
                f"https://claude.ai/api/organizations/{org_id}/chat_conversations?limit=20",
                timeout=15,
            )
            resp.raise_for_status()
            conversations = _decode_response(resp)
            debug_info["stage"] = "list_fetched"
            debug_info["num_conversations"] = len(conversations) if conversations else 0

            if not conversations:
                debug_info["stage"] = "done_empty"
                return conversations

            # Log debug info from the list-level response
            first = conversations[0]
            debug_info["list_keys"] = list(first.keys())
            debug_info["list_model"] = first.get("model")
            debug_info["list_model_override"] = first.get("model_override")
            debug_info["list_settings"] = first.get("settings")
            debug_info["list_active_model"] = first.get("active_model")

            # Fetch detail for each conversation to get the actual model used.
            # Use sequential requests with a fresh session per batch to avoid
            # thread-safety issues and rate limiting.
            debug_info["stage"] = "fetching_details"
            enriched = {}  # uuid -> actual_model
            detail_errors = []

            # Only fetch detail for first conversation to diagnose, then apply to all
            first_uuid = conversations[0].get("uuid")
            if first_uuid:
                try:
                    detail_session = _make_session(cookies)
                    detail_resp = detail_session.get(
                        f"https://claude.ai/api/organizations/{org_id}/chat_conversations/{first_uuid}?tree=True&rendering_mode=messages",
                        timeout=15,
                    )
                    debug_info["detail_status"] = detail_resp.status_code
                    if detail_resp.status_code == 200:
                        detail = _decode_response(detail_resp)
                        debug_info["detail_keys"] = list(detail.keys())
                        debug_info["detail_model"] = detail.get("model")
                        debug_info["detail_model_override"] = detail.get("model_override")
                        debug_info["detail_settings_model"] = (detail.get("settings") or {}).get("model")
                        debug_info["detail_active_model"] = detail.get("active_model")

                        msgs = detail.get("chat_messages") or []
                        debug_info["num_messages"] = len(msgs)

                        # Log info about last assistant message
                        for msg in reversed(msgs):
                            if msg.get("sender") == "assistant":
                                debug_info["last_asst_keys"] = list(msg.keys())
                                debug_info["last_asst_model"] = msg.get("model")
                                debug_info["last_asst_model_slug"] = msg.get("model_slug")
                                # Check content for model info
                                content = msg.get("content")
                                if isinstance(content, list) and content:
                                    debug_info["last_asst_content_0_keys"] = list(content[0].keys()) if isinstance(content[0], dict) else type(content[0]).__name__
                                break

                        model = self._extract_actual_model(detail)
                        if model:
                            enriched[first_uuid] = model
                            debug_info["extracted_model"] = model
                        else:
                            debug_info["extracted_model"] = "(empty)"
                    else:
                        debug_info["detail_body_preview"] = detail_resp.text[:500]
                except Exception as e:
                    debug_info["detail_error"] = str(e)

            # For remaining conversations, fetch details sequentially
            for conv in conversations[1:]:
                uuid = conv.get("uuid")
                if not uuid:
                    continue
                try:
                    detail_session = _make_session(cookies)
                    detail_resp = detail_session.get(
                        f"https://claude.ai/api/organizations/{org_id}/chat_conversations/{uuid}?tree=True&rendering_mode=messages",
                        timeout=15,
                    )
                    if detail_resp.status_code == 200:
                        detail = _decode_response(detail_resp)
                        model = self._extract_actual_model(detail)
                        if model:
                            enriched[uuid] = model
                except Exception as e:
                    detail_errors.append({"uuid": uuid[:8], "error": str(e)})

            debug_info["enriched_count"] = len(enriched)
            debug_info["enriched_models"] = {k[:8]: v for k, v in enriched.items()}
            if detail_errors:
                debug_info["detail_errors"] = detail_errors[:5]

            # Set _actual_model on each conversation object
            for conv in conversations:
                uuid = conv.get("uuid", "")
                if uuid in enriched:
                    conv["_actual_model"] = enriched[uuid]

            debug_info["stage"] = "done"
            return conversations

        except Exception as exc:
            debug_info["error"] = str(exc)
            debug_info["traceback"] = _tb.format_exc()
            raise
        finally:
            try:
                debug_log.write_text(_json.dumps(debug_info, indent=2, default=str))
            except Exception:
                pass

    def _refresh(self):
        try:
            usage        = fetch_claude_usage()
            self._usage  = usage
            log_usage(usage)
            rows         = load_history()
            self._stats  = calculate_stats(usage, rows)
            self._velocity = calc_velocity(rows)
            self._runway   = calc_runway(usage, self._velocity)
            self._msg_est  = estimate_messages_remaining(usage, rows)
            self._suggestion = smart_suggestion(usage, self._stats, self._velocity)
            # Recent session pcts for sparkline (last ~8 readings)
            self._recent_session_pcts = [r[1] for r in rows[-8:]] if rows else []
            try:
                self._conversations = self._fetch_conversations_data()
            except Exception:
                self._conversations = None
            self._apply_ui(usage)
            self._check_limits(usage)
        except Exception as e:
            self._apply_ui(None, error=str(e))

    def _check_limits(self, usage):
        if not self.config.get("notifications_enabled", True):
            return

        spct   = usage["session_pct"]
        wpct   = usage["weekly_pct"]
        sreset = usage.get("session_resets_at", "")

        # Reset session keys when session resets_at changes
        if sreset != self._last_session_reset:
            old_reset = self._last_session_reset
            self._notified = {k for k in self._notified if not k.startswith("session_")}
            self._last_session_reset = sreset
            # Notify on new session (but not on first launch)
            if old_reset is not None and sreset:
                rumps.notification(
                    "ClaudeWatch",
                    "New session started",
                    "Fresh 5-hour window — slate is clean.",
                )

        sr = _fmt_reset(sreset)
        wr = _fmt_reset(usage.get("weekly_resets_at", ""))

        for t in SESSION_THRESHOLDS:
            key = f"session_{t}"
            if spct >= t and key not in self._notified:
                self._notified.add(key)
                rumps.notification("ClaudeWatch", f"Session usage at {t}%",
                                   f"Resets in {sr}." if sr else "")

        for t in WEEKLY_THRESHOLDS:
            key = f"weekly_{t}"
            if wpct >= t and key not in self._notified:
                self._notified.add(key)
                rumps.notification("ClaudeWatch", f"Weekly usage at {t}%",
                                   f"Resets in {wr}." if wr else "")

        extra_pct = usage.get("extra_pct")
        if extra_pct is not None:
            eu = usage.get("extra_used", 0)
            for t in EXTRA_THRESHOLDS:
                key = f"extra_{t}"
                if extra_pct >= t and key not in self._notified:
                    self._notified.add(key)
                    rumps.notification("ClaudeWatch", f"Extra credits at {t}%",
                                       f"{eu:.0f} credits used")

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

        velocity = getattr(self, "_velocity", None)
        runway   = getattr(self, "_runway", None)
        msg_est  = getattr(self, "_msg_est", None)
        suggestion = getattr(self, "_suggestion", None)
        recent_pcts = getattr(self, "_recent_session_pcts", None)

        self.title = _build_title(usage, self.config, velocity, recent_pcts)

        if self.config.get("show_hover_tooltip", True):
            self._set_tooltip(_build_tooltip(usage, velocity, runway, msg_est))
        else:
            self._set_tooltip("")

        spct   = usage["session_pct"]
        wpct   = usage["weekly_pct"]
        sreset = _fmt_reset(usage["session_resets_at"])
        wreset = _fmt_reset(usage["weekly_resets_at"])

        self.menu[session_header].title = f"⬤  Session (5h) — {spct:.1f}%"
        self.menu[session_detail].title = f"   resets in {sreset}" if sreset else "   —"

        # Session runway
        if runway and runway.get("session_runway_min") is not None:
            sr_run = _fmt_runway(runway["session_runway_min"])
            self.menu["   session_runway"].title = f"   ⏱ limit in ~{sr_run} at this pace"
            self.menu["   session_runway"].hidden = False
        else:
            self.menu["   session_runway"].hidden = True

        self.menu[weekly_header].title  = f"⬤  Weekly (7d) — {wpct:.1f}%"

        if wreset:
            self.menu[weekly_detail].title = f"   resets in {wreset}"
        else:
            self.menu[weekly_detail].title = "   —  "

        # Weekly runway
        if runway and runway.get("weekly_runway_min") is not None:
            wr_run = _fmt_runway(runway["weekly_runway_min"])
            self.menu["   weekly_runway"].title = f"   ⏱ limit in ~{wr_run} at this pace"
            self.menu["   weekly_runway"].hidden = False
        else:
            self.menu["   weekly_runway"].hidden = True

        # Per-model breakdowns (combined sub-line in weekly section)
        per_model = usage.get("per_model", {})
        parts = []
        if "Sonnet" in per_model:
            parts.append(f"Sonnet: {per_model['Sonnet']['utilization']:.1f}%")
        if "Opus" in per_model:
            parts.append(f"Opus: {per_model['Opus']['utilization']:.1f}%")
        if parts:
            self.menu["   per_model_line"].title = "   " + "  ·  ".join(parts)
            self.menu["   per_model_line"].hidden = False
        else:
            self.menu["   per_model_line"].hidden = True

        # Extra credits
        eu = usage.get("extra_used")
        el = usage.get("extra_limit")
        extra_pct = usage.get("extra_pct")
        if eu is not None and el:
            eu_usd = eu / CREDITS_PER_DOLLAR
            el_usd = el / CREDITS_PER_DOLLAR
            warn = "⚠️ " if extra_pct and extra_pct >= 90 else ""
            self.menu["   extra_credits"].title = (
                f"   {warn}Extra: ${eu_usd:.2f}/${el_usd:.2f} ({extra_pct:.0f}%)"
            )
            self.menu["   extra_credits"].hidden = False
        else:
            self.menu["   extra_credits"].hidden = True

        # Velocity line
        if velocity and velocity["session_velocity"] > 0.1:
            self.menu["   velocity_line"].title = (
                f"   🔥 Burning {velocity['session_velocity']:.1f}%/hr session"
                f" · {velocity['weekly_velocity']:.1f}%/hr weekly"
            )
            self.menu["   velocity_line"].hidden = False
        else:
            self.menu["   velocity_line"].hidden = True

        # Messages remaining
        if msg_est:
            self.menu["   msgs_remaining"].title = (
                f"   ~{msg_est['session_msgs_left']} msgs left in session"
                f" · ~{msg_est['weekly_msgs_left']} this week"
            )
            self.menu["   msgs_remaining"].hidden = False
        else:
            self.menu["   msgs_remaining"].hidden = True

        # Smart suggestion
        if suggestion:
            emoji, text = suggestion
            self.menu["   suggestion_line"].title = f"   {emoji} {text}"
            self.menu["   suggestion_line"].hidden = False
        else:
            self.menu["   suggestion_line"].hidden = True


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ClaudeMonitorApp().run()
