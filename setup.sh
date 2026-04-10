#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# ClaudeWatch — Installer / Updater / Uninstaller
#
# Usage:
#   ./setup.sh             Install or update
#   ./setup.sh --uninstall Remove everything
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Constants ─────────────────────────────────────────────────────────────────

APP_DIR="$HOME/.claude_monitor"
VENV_DIR="$APP_DIR/venv"
PLIST_LABEL="com.katespurr.claudewatch"
PLIST_FILE="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── Formatting helpers ────────────────────────────────────────────────────────

bold()   { printf '\033[1m%s\033[0m\n' "$*"; }
ok()     { printf '\033[32m✓\033[0m %s\n' "$*"; }
warn()   { printf '\033[33m⚠\033[0m  %s\n' "$*"; }
fail()   { printf '\033[31m✗\033[0m %s\n' "$*"; exit 1; }
ask()    { printf '\033[1m?\033[0m  %s ' "$*"; }

# ── Uninstall ─────────────────────────────────────────────────────────────────

if [ "${1:-}" = "--uninstall" ]; then
    echo ""
    bold "ClaudeWatch — Uninstall"
    echo "─────────────────────────────────────"
    echo ""

    if launchctl list "$PLIST_LABEL" &>/dev/null 2>&1; then
        launchctl unload "$PLIST_FILE" 2>/dev/null || true
        ok "Stopped ClaudeWatch"
    fi

    if [ -f "$PLIST_FILE" ]; then
        rm "$PLIST_FILE"
        ok "Removed login item"
    fi

    if [ -d "$APP_DIR" ]; then
        ask "Remove app data at $APP_DIR? (history + config will be deleted) (y/n):"
        read -r REMOVE_DATA
        if [ "$REMOVE_DATA" = "y" ] || [ "$REMOVE_DATA" = "Y" ]; then
            rm -rf "$APP_DIR"
            ok "Removed $APP_DIR"
        else
            ok "Kept $APP_DIR (history and config preserved)"
        fi
    fi

    echo ""
    bold "Uninstall complete."
    echo ""
    exit 0
fi

# ── Header ────────────────────────────────────────────────────────────────────

echo ""
bold "◈  ClaudeWatch — Setup"
echo "─────────────────────────────────────"
echo ""

# ── Pre-flight checks ─────────────────────────────────────────────────────────

# macOS only
if [ "$(uname)" != "Darwin" ]; then
    fail "ClaudeWatch requires macOS."
fi

# Python 3.9+
if ! command -v python3 &>/dev/null; then
    fail "Python 3 not found. Install via Homebrew: brew install python3"
fi
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 9 ]; }; then
    fail "Python 3.9 or later required (found $PY_VER). Upgrade: brew install python3"
fi
ok "Python $PY_VER"

# Claude desktop app
if [ ! -d "/Applications/Claude.app" ]; then
    warn "Claude desktop app not found at /Applications/Claude.app"
    echo "     ClaudeWatch reads your session data from the Claude desktop app."
    echo "     Download it from https://claude.ai/download then re-run this installer."
    echo ""
    ask "Continue anyway? (y/n):"
    read -r CONTINUE_NO_CLAUDE
    [ "$CONTINUE_NO_CLAUDE" = "y" ] || [ "$CONTINUE_NO_CLAUDE" = "Y" ] || exit 0
else
    ok "Claude desktop app found"
fi

# ── Detect existing install ───────────────────────────────────────────────────

REINSTALL=false
if [ -d "$APP_DIR" ] && [ -f "$APP_DIR/claude_monitor.py" ]; then
    echo ""
    warn "Existing install found at $APP_DIR"
    ask "Update it? (y/n):"
    read -r DO_UPDATE
    [ "$DO_UPDATE" = "y" ] || [ "$DO_UPDATE" = "Y" ] || { echo "Aborted."; exit 0; }
    REINSTALL=true
    # Stop the running instance before updating
    if launchctl list "$PLIST_LABEL" &>/dev/null 2>&1; then
        launchctl unload "$PLIST_FILE" 2>/dev/null || true
        ok "Stopped running instance"
    fi
fi

echo ""

# ── Install ───────────────────────────────────────────────────────────────────

mkdir -p "$APP_DIR"

# Copy app script
cp "$SCRIPT_DIR/claude_monitor.py" "$APP_DIR/claude_monitor.py"
ok "App files copied to $APP_DIR/"

# Create or update virtual environment
if [ "$REINSTALL" = true ] && [ -d "$VENV_DIR" ]; then
    echo "  Updating Python dependencies..."
else
    echo "  Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/pip" install --upgrade pip --quiet
"$VENV_DIR/bin/pip" install rumps requests pycryptodome zstandard --quiet
ok "Dependencies installed"

# Copy menu bar icon from Claude app
CLAUDE_RES="/Applications/Claude.app/Contents/Resources"
if [ -f "$CLAUDE_RES/TrayIconTemplate.png" ]; then
    cp "$CLAUDE_RES/TrayIconTemplate.png"    "$APP_DIR/TrayIconTemplate.png"
    cp "$CLAUDE_RES/TrayIconTemplate@2x.png" "$APP_DIR/TrayIconTemplate@2x.png"
    ok "Menu bar icon copied"
else
    warn "Could not find Claude icon — menu bar will show text fallback"
fi

PYTHON_BIN="$VENV_DIR/bin/python3"

# ── LaunchAgent ───────────────────────────────────────────────────────────────

echo ""
ask "Start ClaudeWatch automatically at login? (y/n):"
read -r AUTO_START

if [ "$AUTO_START" = "y" ] || [ "$AUTO_START" = "Y" ]; then
    mkdir -p "$HOME/Library/LaunchAgents"
    cat > "$PLIST_FILE" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PLIST_LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_BIN</string>
        <string>$APP_DIR/claude_monitor.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$APP_DIR/stdout.log</string>
    <key>StandardErrorPath</key>
    <string>$APP_DIR/stderr.log</string>
</dict>
</plist>
PLIST
    ok "Login item configured"
fi

# ── Start now ─────────────────────────────────────────────────────────────────

echo ""
ask "Start ClaudeWatch now? (y/n):"
read -r START_NOW

if [ "$START_NOW" = "y" ] || [ "$START_NOW" = "Y" ]; then
    if [ -f "$PLIST_FILE" ]; then
        launchctl load "$PLIST_FILE"
    else
        "$PYTHON_BIN" "$APP_DIR/claude_monitor.py" &
        disown
    fi

    # Give it a moment, then verify
    sleep 2
    if launchctl list "$PLIST_LABEL" &>/dev/null 2>&1 || pgrep -f "claude_monitor.py" &>/dev/null; then
        ok "ClaudeWatch is running — look for the icon in your menu bar"
        echo "     (If the icon is hidden, hold ⌘ and drag other menu bar icons to make space)"
    else
        warn "App may not have started. Check logs: $APP_DIR/stderr.log"
    fi
fi

# ── Summary ───────────────────────────────────────────────────────────────────

echo ""
echo "─────────────────────────────────────"
bold "◈  Setup complete!"
echo ""
echo "Manage ClaudeWatch:"
echo "  Start:     launchctl load $PLIST_FILE"
echo "  Stop:      launchctl unload $PLIST_FILE"
echo "  Logs:      $APP_DIR/stderr.log"
echo "  Config:    $APP_DIR/config.json"
echo "  Uninstall: bash \"$SCRIPT_DIR/setup.sh\" --uninstall"
echo ""
