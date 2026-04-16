#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# ClaudeMonitor — Build Script
#
# Builds ClaudeMonitor.app via py2app and packages it as a DMG.
#
# Usage:
#   ./build_dmg.sh              Build app + DMG
#   ./build_dmg.sh --app-only   Build app only (skip DMG)
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_VENV="$SCRIPT_DIR/.build_venv"
APP_NAME="ClaudeMonitor"
DMG_NAME="$APP_NAME.dmg"
APP_ONLY=false

[ "${1:-}" = "--app-only" ] && APP_ONLY=true

# ── Helpers ───────────────────────────────────────────────────────────────────

ok()   { printf '\033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '\033[33m⚠\033[0m  %s\n' "$*"; }
fail() { printf '\033[31m✗\033[0m %s\n' "$*"; exit 1; }
bold() { printf '\033[1m%s\033[0m\n' "$*"; }

# ── Pre-flight ────────────────────────────────────────────────────────────────

echo ""
bold "◈  ClaudeMonitor — Build"
echo "─────────────────────────────────────"
echo ""

[ "$(uname)" = "Darwin" ] || fail "macOS required."
command -v python3 &>/dev/null || fail "Python 3 not found."

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
ok "Python $PY_VER"

# ── Copy icon from Claude.app if not already present ─────────────────────────

CLAUDE_RES="/Applications/Claude.app/Contents/Resources"
if [ ! -f "$SCRIPT_DIR/TrayIconTemplate.png" ]; then
    if [ -f "$CLAUDE_RES/TrayIconTemplate.png" ]; then
        cp "$CLAUDE_RES/TrayIconTemplate.png"    "$SCRIPT_DIR/"
        cp "$CLAUDE_RES/TrayIconTemplate@2x.png" "$SCRIPT_DIR/"
        ok "Icon copied from Claude.app"
    else
        warn "TrayIconTemplate.png not found — app will show text fallback in menu bar"
    fi
else
    ok "Icon present"
fi

# ── Build venv ────────────────────────────────────────────────────────────────

if [ ! -d "$BUILD_VENV" ]; then
    echo "  Creating build environment..."
    python3 -m venv "$BUILD_VENV"
fi
"$BUILD_VENV/bin/pip" install --upgrade pip --quiet
"$BUILD_VENV/bin/pip" install py2app rumps requests pycryptodome zstandard --quiet
ok "Build dependencies ready"

# ── py2app ────────────────────────────────────────────────────────────────────

echo ""
echo "  Building $APP_NAME.app..."
cd "$SCRIPT_DIR"
rm -rf build dist
"$BUILD_VENV/bin/python3" setup.py py2app 2>&1 | grep -v "^$" | grep -v "^running\|^creating\|^copying\|^stripping\|^byte-compiling" || true

APP_PATH="$SCRIPT_DIR/dist/$APP_NAME.app"
[ -d "$APP_PATH" ] || fail "Build failed — dist/$APP_NAME.app not found"
ok "Built dist/$APP_NAME.app"

# ── DMG ───────────────────────────────────────────────────────────────────────

if [ "$APP_ONLY" = true ]; then
    echo ""
    bold "◈  Build complete!"
    echo ""
    echo "  App: dist/$APP_NAME.app"
    echo "  Test: open \"$APP_PATH\""
    echo ""
    exit 0
fi

echo ""
echo "  Creating $DMG_NAME..."

DMG_PATH="$SCRIPT_DIR/$DMG_NAME"
TMP_DIR="$(mktemp -d)"

# Stage the .app and a symlink to /Applications for drag-install UX
cp -r "$APP_PATH" "$TMP_DIR/"
ln -s /Applications "$TMP_DIR/Applications"

hdiutil create \
    -volname "$APP_NAME" \
    -srcfolder "$TMP_DIR" \
    -ov -format UDZO \
    "$DMG_PATH" \
    > /dev/null

rm -rf "$TMP_DIR"
ok "Created $DMG_NAME ($(du -sh "$DMG_PATH" | cut -f1))"

# ── Summary ───────────────────────────────────────────────────────────────────

echo ""
echo "─────────────────────────────────────"
bold "◈  Build complete!"
echo ""
echo "  App: dist/$APP_NAME.app"
echo "  DMG: $DMG_NAME"
echo ""
echo "Test:      open \"$APP_PATH\""
echo "Distribute: attach $DMG_NAME to a GitHub Release"
echo ""
echo "Gatekeeper note: unsigned builds require users to right-click → Open"
echo "on first launch. To avoid this, sign with: codesign --deep --force"
echo "--sign 'Developer ID Application: Your Name' dist/$APP_NAME.app"
echo ""
