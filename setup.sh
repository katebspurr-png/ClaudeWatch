#!/bin/bash
# ─────────────────────────────────────────────────
# Claude Monitor — Quick Setup Script
# ─────────────────────────────────────────────────
# Run this script to install dependencies and
# optionally set it to launch at login.
# Uses a virtual environment (no system conflicts).
# ─────────────────────────────────────────────────

set -e

echo ""
echo "◈  Claude Monitor — Setup"
echo "─────────────────────────"
echo ""

# Step 1: Check Python 3
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Install it from python.org or via Homebrew:"
    echo "   brew install python3"
    exit 1
fi
echo "✅ Python 3 found: $(python3 --version)"

# Step 2: Create the app directory
APP_DIR="$HOME/.claude_monitor"
VENV_DIR="$APP_DIR/venv"
mkdir -p "$APP_DIR"

# Copy the main script
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$SCRIPT_DIR/claude_monitor.py" ]; then
    cp "$SCRIPT_DIR/claude_monitor.py" "$APP_DIR/claude_monitor.py"
    echo "✅ App copied to $APP_DIR/"
fi

# Step 3: Create virtual environment and install dependencies
echo ""
echo "📦 Creating virtual environment..."
python3 -m venv "$VENV_DIR"
echo "✅ Virtual environment created"

echo ""
echo "📦 Installing dependencies..."
"$VENV_DIR/bin/pip" install --upgrade pip --quiet
"$VENV_DIR/bin/pip" install rumps requests pycryptodome zstandard --quiet
echo "✅ Dependencies installed (rumps, requests, pycryptodome, zstandard)"

# Copy Claude tray icon (used for the menu bar icon)
CLAUDE_APP="/Applications/Claude.app/Contents/Resources"
if [ -f "$CLAUDE_APP/TrayIconTemplate.png" ]; then
    cp "$CLAUDE_APP/TrayIconTemplate.png" "$APP_DIR/TrayIconTemplate.png"
    cp "$CLAUDE_APP/TrayIconTemplate@2x.png" "$APP_DIR/TrayIconTemplate@2x.png"
    echo "✅ Claude tray icon copied"
else
    echo "⚠️  Claude desktop app not found — icon will fall back to text"
fi

# The python binary we'll use everywhere
PYTHON_BIN="$VENV_DIR/bin/python3"

# Step 4: Offer to create a Launch Agent (auto-start at login)
echo ""
read -p "🚀 Start Claude Monitor at login? (y/n): " AUTO_START

if [ "$AUTO_START" = "y" ] || [ "$AUTO_START" = "Y" ]; then
    PLIST_DIR="$HOME/Library/LaunchAgents"
    PLIST_FILE="$PLIST_DIR/com.katespurr.claudewatch.plist"
    mkdir -p "$PLIST_DIR"

    cat > "$PLIST_FILE" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.katespurr.claudewatch</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_BIN</string>
        <string>$APP_DIR/claude_monitor.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>$APP_DIR/stdout.log</string>
    <key>StandardErrorPath</key>
    <string>$APP_DIR/stderr.log</string>
</dict>
</plist>
EOF

    echo "✅ Launch Agent created at $PLIST_FILE"
    echo "   Claude Monitor will start automatically at login."
    echo ""
    echo "   To remove auto-start later, run:"
    echo "   launchctl unload $PLIST_FILE && rm $PLIST_FILE"
fi

# Step 5: Launch now
echo ""
read -p "▶  Start Claude Monitor now? (y/n): " START_NOW

if [ "$START_NOW" = "y" ] || [ "$START_NOW" = "Y" ]; then
    echo "Starting Claude Monitor..."
    "$PYTHON_BIN" "$APP_DIR/claude_monitor.py" &
    echo "✅ Running! Look for ◈ in your menu bar."
else
    echo ""
    echo "To start manually, run:"
    echo "   ~/.claude_monitor/venv/bin/python3 ~/.claude_monitor/claude_monitor.py"
fi

echo ""
echo "─────────────────────────"
echo "◈  Setup complete!"
echo ""
echo "Quick reference:"
echo "  Start:  ~/.claude_monitor/venv/bin/python3 ~/.claude_monitor/claude_monitor.py"
echo "  Config: ~/.claude_monitor/config.json"
echo "  Logs:   ~/.claude_monitor/stderr.log"
echo "─────────────────────────"
echo ""
