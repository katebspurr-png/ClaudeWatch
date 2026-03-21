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
    import requests
    from Crypto.Cipher import AES
    DEPS_OK = True
except ImportError:
    DEPS_OK = False

# ─── Configuration ───────────────────────────────────────────────────────────

CONFIG_DIR  = Path.home() / ".claude_monitor"
CONFIG_FILE = CONFIG_DIR / "config.json"
DB_PATH     = CONFIG_DIR / "history.db"
DASH_PATH   = CONFIG_DIR / "dashboard.html"
COOKIES_DB  = Path.home() / "Library/Application Support/Claude/Cookies"
ICON_PATH   = str(CONFIG_DIR / "TrayIconTemplate.png")

CLAUDE_USAGE_URL = "https://claude.ai/settings/usage"

DEFAULT_CONFIG = {
    "refresh_interval_minutes": 5,
    "show_session_pct":   True,
    "show_weekly_pct":    True,
    "show_reset_time":    False,
    "show_hover_tooltip": True,
    "notifications_enabled": True,
}

CREDITS_PER_DOLLAR = 100   # 1 credit = $0.01 (confirmed against billing)
SESSION_THRESHOLDS = [75, 90]   # % session usage to notify at
WEEKLY_THRESHOLDS  = [75, 90]   # % weekly usage to notify at
EXTRA_THRESHOLDS   = [80, 95]   # % extra credits to notify at

REFRESH_OPTIONS = [1, 5, 15, 30]  # minutes

MODEL_DISPLAY = {
    "claude-sonnet-4-6": "Sonnet 4.6",
    "claude-opus-4-6":   "Opus 4.6",
    "claude-haiku-4-5":  "Haiku 4.5",
    "claude-sonnet-4-5": "Sonnet 4.5",
    "claude-opus-4-5":   "Opus 4.5",
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

def _decode_response(resp):
    """Decode API response, handling zstd compression."""
    if resp.headers.get("Content-Encoding") == "zstd":
        import zstandard
        dctx = zstandard.ZstdDecompressor()
        return json.loads(dctx.decompress(resp.content))
    return resp.json()


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
    </div>
    <style>
      .model-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}
      @media(max-width:500px){{.model-grid{{grid-template-columns:1fr}}}}
      .model-card{{background:var(--surface);border-radius:var(--radius);padding:14px}}
      .model-name{{font-size:.95rem;font-weight:700;margin-bottom:2px}}
      .model-sub{{font-size:.75rem;color:var(--muted);margin-bottom:10px}}
      .model-tasks{{font-size:.8rem;padding-left:18px;line-height:1.7;color:var(--text)}}
      .model-tasks li{{margin-bottom:2px}}
    </style>"""


# ─── Dashboard HTML ──────────────────────────────────────────────────────────

def generate_dashboard(usage, stats):
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
        w_color = "#D97757"

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
        new Chart(document.getElementById('chart'), {{
          type: 'line',
          data: {{
            labels: {chart_labels},
            datasets: [{{
              label: 'Weekly %',
              data: {chart_values},
              borderColor: '#D97757',
              backgroundColor: 'rgba(217,119,87,0.1)',
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
        }});
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
            "#D97757" if i == max(patterns, key=patterns.get)
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
        new Chart(document.getElementById('dowchart'), {{
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
        }});
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
    --accent:#D97757;--border:#e5e7eb;--radius:12px;
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
</style>
</head>
<body>
<h1>
  <svg width="20" height="20" viewBox="0 0 100 100" fill="none">
    <circle cx="50" cy="50" r="48" fill="#D97757"/>
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
    <div class="bar-wrap"><div class="bar" style="width:{min(spct,100):.1f}%;background:#D97757"></div></div>
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

{extra_html}
{chart_html}
{pattern_html}
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
            name = name[:57] + "…"
        model_id = c.get("model", "")
        model = MODEL_DISPLAY.get(model_id, model_id.replace("claude-", "").title())
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
    extra_pct = usage.get("extra_pct")
    if extra_pct is not None and usage.get("extra_enabled"):
        if extra_pct >= 95:
            title += " 🚨"
        elif extra_pct >= 80:
            title += " ⚠️"
    return title


def _build_tooltip(usage):
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
    # Per-model breakdowns
    for label, info in usage.get("per_model", {}).items():
        pct = info["utilization"]
        lines.append(f"  {label}:  {pct:.0f}%")
    # Extra credits
    eu = usage.get("extra_used")
    el = usage.get("extra_limit")
    if eu is not None and el:
        extra_pct = usage.get("extra_pct", 0)
        warn = "⚠️ " if extra_pct and extra_pct >= 90 else ""
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
        self._notified = set()            # keys like "session_75", "weekly_90", "extra_80"
        self._last_session_reset = None   # track session resets_at to clear session keys

        if DEPS_OK:
            init_db()

        # Settings checkmark items
        self._s_session = rumps.MenuItem("Session % (5h)", callback=self._toggle("show_session_pct"))
        self._s_weekly  = rumps.MenuItem("Weekly % (7d)",  callback=self._toggle("show_weekly_pct"))
        self._s_reset   = rumps.MenuItem("Reset time",     callback=self._toggle("show_reset_time"))
        self._s_tooltip = rumps.MenuItem("Hover tooltip",  callback=self._toggle("show_hover_tooltip"))
        self._s_notif   = rumps.MenuItem("Notifications",  callback=self._toggle("notifications_enabled"))
        self._sync_checkmarks()

        settings = rumps.MenuItem("Settings")
        settings.update([
            rumps.MenuItem("Show in menu bar:", callback=None),
            self._s_session,
            self._s_weekly,
            self._s_reset,
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
            rumps.MenuItem("⬤  Weekly (7d)",    callback=None),
            rumps.MenuItem("   —  ",             callback=None),
            rumps.MenuItem("   per_model_line",  callback=None),
            rumps.MenuItem("   extra_credits",   callback=None),
            None,
            model_guide,
            settings,
            refresh_menu,
            rumps.MenuItem("Refresh Now",        callback=self.manual_refresh),
            None,
            rumps.MenuItem("Quit",               callback=self.quit_app),
        ]

        # Hide per-model and extra items initially
        for key in ("   per_model_line", "   extra_credits"):
            self.menu[key].hidden = True

        if DEPS_OK:
            self._start_timer()
            threading.Thread(target=self._refresh, daemon=True).start()

    # ── Settings ──

    def _toggle(self, key):
        def callback(_):
            self.config[key] = not self.config.get(key, True)
            save_config(self.config)
            self._sync_checkmarks()
            if self._usage:
                self._apply_ui(self._usage)
        return callback

    def _sync_checkmarks(self):
        self._s_session.state = int(bool(self.config.get("show_session_pct",   True)))
        self._s_weekly.state  = int(bool(self.config.get("show_weekly_pct",    True)))
        self._s_reset.state   = int(bool(self.config.get("show_reset_time",    False)))
        self._s_tooltip.state = int(bool(self.config.get("show_hover_tooltip", True)))
        self._s_notif.state   = int(bool(self.config.get("notifications_enabled", True)))

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
            path = generate_dashboard(self._usage, self._stats)
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
            cookies = get_claude_cookies()
            org_id = cookies.get("lastActiveOrg", "")
            session = _make_session(cookies)
            resp = session.get(
                f"https://claude.ai/api/organizations/{org_id}/chat_conversations?limit=20",
                timeout=15,
            )
            resp.raise_for_status()
            data = _decode_response(resp)
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
        self._refresh()

    def _start_timer(self):
        self._restart_timer()

    def _refresh(self):
        try:
            usage        = fetch_claude_usage()
            self._usage  = usage
            log_usage(usage)
            rows         = load_history()
            self._stats  = calculate_stats(usage, rows)
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
            self._notified = {k for k in self._notified if not k.startswith("session_")}
            self._last_session_reset = sreset

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

        self.title = _build_title(usage, self.config)

        if self.config.get("show_hover_tooltip", True):
            self._set_tooltip(_build_tooltip(usage))
        else:
            self._set_tooltip("")

        spct   = usage["session_pct"]
        wpct   = usage["weekly_pct"]
        sreset = _fmt_reset(usage["session_resets_at"])
        wreset = _fmt_reset(usage["weekly_resets_at"])

        self.menu[session_header].title = f"⬤  Session (5h) — {spct:.1f}%"
        self.menu[session_detail].title = f"   resets in {sreset}" if sreset else "   —"
        self.menu[weekly_header].title  = f"⬤  Weekly (7d) — {wpct:.1f}%"

        if wreset:
            self.menu[weekly_detail].title = f"   resets in {wreset}"
        else:
            self.menu[weekly_detail].title = "   —  "

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


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ClaudeMonitorApp().run()
