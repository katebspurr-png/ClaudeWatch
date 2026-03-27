# ClaudeWatch — Mac Menu Bar Usage Monitor

A lightweight Mac menu bar app that shows your Claude.ai usage percentages in real time, using the Claude desktop app's session cookies for authentication.

---

## What It Shows

```
[Claude icon]  34% | 64%
```

- **34%** — 5-hour session usage (resets every 5 hours)
- **64%** — 7-day weekly usage

Click the icon to see reset times, extra credit usage, and a link to the full usage page.

---

## Requirements

- macOS (Apple Silicon or Intel)
- Python 3.9+
- **Claude desktop app** must be installed and you must be logged in (the app reads its session cookies)

---

## Installing the DMG

> **Gatekeeper warning:** ClaudeWatch is not signed with an Apple Developer certificate, so macOS will block it on first launch.
>
> To open it: **right-click** (or Control-click) `ClaudeWatch.app` → **Open** → **Open** again in the dialog. You only need to do this once.

---

## Setup

```bash
chmod +x setup.sh
./setup.sh
```

The setup script will:
1. Create `~/.claude_monitor/` with a virtual environment
2. Install dependencies (`rumps`, `requests`, `pycryptodome`)
3. Copy the Claude tray icon from the desktop app
4. Optionally install a Launch Agent so it starts at login

---

## How It Works

The Claude desktop app is an Electron app that stores session cookies in a Chromium SQLite database:

```
~/Library/Application Support/Claude/Cookies
```

Cookies are encrypted with AES-128-CBC. The key is derived via PBKDF2-SHA1 from a password stored in Keychain under **"Claude Safe Storage"** / account **"Claude Key"**.

**Decryption notes (Chromium v10 format on macOS):**
- Strip the `v10` prefix (3 bytes)
- Derive AES key: `PBKDF2(password, salt=b"saltysalt", iterations=1003, dklen=16, hash=SHA1)`
- Decrypt with `IV = b" " * 16` (16 space chars)
- The plaintext has a **32-byte internal Chromium header** prepended — skip it: `plaintext[32:-pkcs7_pad]`

**Usage endpoint:**
```
GET https://claude.ai/api/organizations/{org_id}/usage
Cookie: sessionKey=...; lastActiveOrg=...; anthropic-device-id=...
```

Response:
```json
{
  "five_hour":  { "utilization": 34.0, "resets_at": "..." },
  "seven_day":  { "utilization": 64.0, "resets_at": "..." },
  "extra_usage": { "used_credits": 194, "monthly_limit": 3300 }
}
```

---

## Management

```bash
# Stop
launchctl unload ~/Library/LaunchAgents/com.katespurr.claudewatch.plist

# Start
launchctl load ~/Library/LaunchAgents/com.katespurr.claudewatch.plist

# Logs
tail -f ~/.claude_monitor/stderr.log
```

---

## Files

| File | Purpose |
|------|---------|
| `claude_monitor.py` | Main app — copy to `~/.claude_monitor/` |
| `setup.sh` | One-time setup script |
| `~/.claude_monitor/config.json` | Refresh interval (default: 5 min) |
