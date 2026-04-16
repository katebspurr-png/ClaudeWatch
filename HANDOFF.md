# ClaudeMonitor — Claude Code Handoff

## What this is
A macOS menu bar app that shows Claude.ai usage percentages in real time, reading directly from the Claude desktop app's encrypted session cookies. No manual cookie setup required — this is the key differentiator vs. competitors.

Currently shows: `39% | 9%` (5-hour session % | 7-day weekly %)

---

## Repo structure
```
claude_monitor.py   # Main rumps menu bar app — copy to ~/.claude_monitor/
setup.sh            # One-time install script (venv, deps, LaunchAgent)
~/.claude_monitor/config.json   # refresh_interval_minutes (default: 5)
```

**Dependencies:** `rumps`, `requests`, `pycryptodome`

---

## How auth works
The Claude desktop app is Electron/Chromium and stores cookies at:
```
~/Library/Application Support/Claude/Cookies
```
Cookies are AES-128-CBC encrypted (Chromium v10 format). Key is derived via:
```
PBKDF2(password, salt=b"saltysalt", iterations=1003, dklen=16, hash=SHA1)
```
Password comes from macOS Keychain: service=`"Claude Safe Storage"`, account=`"Claude Key"`.

Decryption: strip 3-byte `v10` prefix → decrypt → skip 32-byte Chromium header → strip PKCS7 padding.

The working decryption code is already in `claude_monitor.py` (`_get_aes_key`, `_decrypt_cookie`, `get_claude_cookies`).

---

## API endpoints discovered (authenticated via cookies)

### ✅ Working endpoints

| Endpoint | Notes |
|----------|-------|
| `GET /api/organizations/{org_id}/usage` | Core usage data |
| `GET /api/organizations/{org_id}/chat_conversations?limit=N&offset=N` | Paginated conversation list |
| `GET /api/organizations/{org_id}/chat_conversations/{uuid}` | Single conversation with messages |
| `GET /api/organizations/{org_id}/projects` | Project list |
| `GET /api/organizations/{org_id}` | Org info (plan, billing_type, rate_limit_tier) |
| `GET /api/account` | User account info |

### ❌ Not available (404/403)
`usage_stats`, `billing`, `plan`, `models`, `claude_code/usage`, `api_keys`, `stats`, `analytics`

---

## Key API response shapes

### Usage endpoint
```json
{
  "five_hour":  { "utilization": 39.0, "resets_at": "2026-03-21T20:00:00Z" },
  "seven_day":  { "utilization": 9.0,  "resets_at": "2026-03-27T16:00:00Z" },
  "seven_day_opus":    null,
  "seven_day_sonnet":  null,
  "seven_day_cowork":  null,
  "seven_day_oauth_apps": null,
  "iguana_necktie": null,
  "extra_usage": {
    "is_enabled": true,
    "monthly_limit": 5000,
    "used_credits": 4926.0,
    "utilization": 98.52
  }
}
```
Note: `seven_day_opus`, `seven_day_sonnet` etc. are null when not used but will populate with per-model utilization data. `iguana_necktie` is an unreleased internal feature — ignore.

### Conversation list item
```json
{
  "uuid": "...",
  "name": "Building a Claude productivity tool",
  "summary": "",
  "model": "claude-sonnet-4-6",
  "created_at": "2026-03-21T17:09:14Z",
  "updated_at": "2026-03-21T17:24:41Z",
  "is_starred": false,
  "is_temporary": false,
  "platform": "CLAUDE_AI",
  "project_uuid": "...",
  "project": { "uuid": "...", "name": "ClaudeMonitor" },
  "settings": { "enabled_web_search": true, "enabled_mcp_tools": {...}, ... }
}
```
No token counts at the list level. Single conversation endpoint (`/chat_conversations/{uuid}`) returns full message data — token counts TBD (zstd decompression required, see below).

### Important: zstd decompression required
The single-conversation endpoint returns `Content-Encoding: zstd`. Standard `requests` does not handle this automatically. Must decompress manually:
```python
import zstandard
def decode_response(r):
    if r.headers.get("Content-Encoding") == "zstd":
        dctx = zstandard.ZstdDecompressor()
        return json.loads(dctx.decompress(r.content))
    return r.json()
```

### Important: Cloudflare requires full browser headers
Simple requests with only auth cookies get 403'd by Cloudflare on the single-conversation endpoint. Must send full browser header set:
```python
headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
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
}
# Also pass ALL cookies (not just the 3 auth ones) — cf_clearance is required
for name, value in all_cookies.items():
    session.cookies.set(name, value, domain="claude.ai")
```

---

## What's been built
- [x] Cookie decryption from desktop app (zero user setup)
- [x] Basic usage fetch (5h %, 7d %, extra credits)
- [x] Menu bar display with reset timers
- [x] Auto-refresh on configurable interval
- [x] Manual refresh
- [x] LaunchAgent for login startup

---

## Immediate next tasks (prioritized)

### 1. Notifications (high priority — table stakes vs competitors)
Trigger macOS notifications at 25%, 50%, 75%, 90% thresholds for both 5h and 7d usage. Also trigger on extra_usage approaching limit. Use `rumps.notification()`.

### 2. Per-model usage display
`seven_day_opus` and `seven_day_sonnet` fields already exist in the usage endpoint. When non-null, surface them in the menu dropdown. Useful for Max plan users.

### 3. Extra credits alert
`extra_usage.utilization` is already in the API response. Currently at 98.52% in dev's account — clearly needs a prominent warning UI.

### 4. Conversation history window (Pro feature candidate)
`chat_conversations` endpoint provides: name, model, created_at, updated_at, project. Can build a native window showing recent conversations grouped by model, project, or date. Token counts may be available in single-conversation endpoint — needs verification (zstd decompression not yet tested end-to-end).

### 5. Monetization
- Free tier: basic 5h/7d display (current state)
- Pro ($9 one-time via Gumroad/Stripe): notifications + conversation history + per-model breakdown
- No subscription — solo dev, keep it simple

---

## Competitive context

| Product | Auth method | Token counts | Notifications | Price |
|---------|-------------|--------------|---------------|-------|
| **ClaudeMonitor** | Auto (desktop app cookies) ✅ | TBD | Not yet | TBD |
| ClaudeUsageBar | Manual cookie paste | No | Yes (25/50/75/90%) | Free |
| Usagebar | Claude Code keychain | No | Yes (50/75/90%) | PWYW |
| ClaudeTuner | Unknown | Yes | Yes | Freemium |

ClaudeMonitor's moat: **zero setup**. Every competitor requires manual cookie copying. This is the headline feature for marketing.

---

## Dev environment
- macOS (Apple Silicon)
- Python 3.14 via Homebrew
- Install deps: `python3 -m pip install rumps requests pycryptodome zstandard --break-system-packages`
- Run: `python3 claude_monitor.py`
