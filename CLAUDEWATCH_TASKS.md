# ClaudeWatch — Claude Code Implementation Instructions

Read CLAUDEWATCH_HANDOFF.md first for full context on the project, API endpoints, auth, and architecture. This file contains the specific implementation tasks.

---

## Context

ClaudeWatch is a working Python macOS menu bar app (`claude_monitor.py`). The core loop — cookie decryption, usage fetch, menu bar display — already works. You are adding new features on top of it, not rewriting it.

Do not refactor working code unless a task explicitly requires it. Make the smallest change that implements each feature correctly.

---

## Before You Start

1. Read `claude_monitor.py` in full
2. Read `CLAUDEWATCH_HANDOFF.md` in full
3. Add `zstandard` to the install deps in `setup.sh` and to the import block in `claude_monitor.py` — it is required for the conversation endpoint and should be added before any other work

---

## Task 1 — Fix zstd Response Decoding

All API requests should use a shared decode helper that handles zstd-compressed responses. The conversation endpoint returns `Content-Encoding: zstd` and will silently return empty content without this.

Add this helper and use it everywhere `resp.json()` is currently called:

```python
def _decode_response(resp):
    """Decode API response, handling zstd compression."""
    if resp.headers.get("Content-Encoding") == "zstd":
        import zstandard
        dctx = zstandard.ZstdDecompressor()
        return json.loads(dctx.decompress(resp.content))
    return resp.json()
```

---

## Task 2 — Upgrade the Request Session

The current session in `fetch_claude_usage()` only sends 3 cookies and a basic User-Agent. Some endpoints (notably single-conversation detail) require the full cookie jar and browser-like headers to pass Cloudflare.

Replace the session setup in `fetch_claude_usage()` with a shared `_make_session(cookies)` function that:

1. Sets ALL cookies from the decrypted cookie dict (not just the 3 auth ones)
2. Sets these headers:

```python
{
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
```

Use `s.cookies.set(name, value, domain="claude.ai")` for each cookie, not `s.cookies.update()`.

---

## Task 3 — Per-Model Usage in Menu

The usage endpoint already returns `seven_day_sonnet` and `seven_day_opus` fields. They are `null` when not applicable and a dict `{"utilization": float, "resets_at": str}` when populated.

Update `_update_ui()` to show per-model breakdown in the weekly section when these fields are non-null. Example display:

```
⬤  Weekly (7d) — 9.0%
   Sonnet: 34.1%  ·  Opus: 12.3%
   resets in 5d 14h
```

If both are null, show the existing display unchanged. Do not add new menu items for this — update the existing detail line or add a sub-line within the weekly section.

Also expose these fields from `fetch_claude_usage()`:

```python
"sonnet_pct": seven_day_sonnet.get("utilization") if seven_day_sonnet else None,
"opus_pct":   seven_day_opus.get("utilization")   if seven_day_opus   else None,
```

---

## Task 4 — Notifications

Use `rumps.notification()` to alert the user when usage crosses thresholds. 

**Thresholds to notify:**
- Session (5h): 75%, 90%
- Weekly (7d): 75%, 90%
- Extra credits: 80%, 95%

**Rules:**
- Each threshold fires once per crossing — do not re-notify on every refresh once past a threshold
- Store fired thresholds in an instance variable `self._notified = set()` with keys like `"session_75"`, `"weekly_90"`, `"extra_80"`
- Reset `session_*` keys when the session resets (i.e. when `resets_at` timestamp changes)
- Notifications should be concise:
  - Title: `"ClaudeWatch"`
  - Subtitle: `"Session usage at 75%"` / `"Extra credits at 95%"`
  - Message: `"Resets in 2h 14m"` / `"5000 credits used"`

Add a "Notifications" toggle to the menu (default on). Store preference in `config.json` as `"notifications_enabled": true`.

---

## Task 5 — Extra Credits Alert in Menu Bar Title

Currently the menu bar title only shows `"34% | 64%"`. When extra credits utilization exceeds 80%, append a warning indicator:

```
34% | 64% ⚠️
```

When it exceeds 95%:

```
34% | 64% 🚨
```

When extra credits are not enabled (`extra_usage` is null or `is_enabled` is false), show nothing extra.

---

## Task 6 — Recent Conversations Window

Add a "Recent Conversations" menu item that opens a native window listing the last 20 conversations.

Use `rumps.Window` or a `webview`-based approach — whichever is simpler to implement cleanly. If neither is clean, use `subprocess` to open a temporary HTML file in the default browser.

**The HTML/display should show a table with:**
- Conversation name (truncated to 60 chars)
- Model used (e.g. `claude-sonnet-4-6` → display as `Sonnet 4.6`)
- Project name (or `—` if none)
- Last updated (relative: "2h ago", "yesterday", "Mar 15")
- Link to open the conversation: `https://claude.ai/chat/{uuid}`

**Data source:** `GET /api/organizations/{org_id}/chat_conversations?limit=20`

This fetch happens on demand (when the menu item is clicked), not on every refresh. Show a loading state in the menu item title while fetching ("Loading..."), then restore it.

**Model name normalisation:**
```python
MODEL_DISPLAY = {
    "claude-sonnet-4-6":    "Sonnet 4.6",
    "claude-opus-4-6":      "Opus 4.6",
    "claude-haiku-4-5":     "Haiku 4.5",
    "claude-sonnet-4-5":    "Sonnet 4.5",
    "claude-opus-4-5":      "Opus 4.5",
}
# Fallback: strip "claude-" prefix and title-case
```

---

## Task 7 — Refresh Interval Setting

Currently the refresh interval is hardcoded from config. Add a submenu "Refresh every…" with options:

- 1 minute
- 5 minutes (default, marked with ✓)
- 15 minutes
- 30 minutes

Selecting an option updates `config.json` and restarts the timer. Mark the active option with ✓.

---

## Implementation Order

Do these in order. Test each before moving to the next:

1. Task 1 (zstd fix) — foundational, unblocks conversation endpoint
2. Task 2 (session upgrade) — foundational, required for reliability
3. Task 3 (per-model usage) — pure display, low risk
4. Task 5 (extra credits warning in title) — one-liner essentially
5. Task 4 (notifications) — most complex, do after display work is stable
6. Task 6 (conversations window) — new surface, do last
7. Task 7 (refresh interval submenu) — polish, lowest priority

---

## Testing Checklist

After all tasks, verify:

- [ ] App launches and shows usage % in menu bar
- [ ] Extra credits warning appears in title when > 80%
- [ ] Per-model breakdown shows in weekly section (may be null on your plan — log the raw values to confirm)
- [ ] Clicking "Recent Conversations" fetches and displays the list
- [ ] Notifications fire once when crossing a threshold, not repeatedly
- [ ] Changing refresh interval persists after restart
- [ ] No crashes when Claude desktop app is not running (should show error state, not crash)
- [ ] No crashes when offline

---

## Open Questions (Do Not Block On These)

- **Token counts per conversation:** The single-conversation endpoint (`/chat_conversations/{uuid}`) returns ~59KB. Full message history is likely in the payload. Explore the response shape and add token display to the conversations window if the data is there. If not, omit.
- **Claude Code usage:** `/api/organizations/{org_id}/claude_code/usage` returns 404 with desktop app cookies. May require Claude Code CLI credentials. Skip for now.
