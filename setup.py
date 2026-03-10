"""
py2app build script for ClaudeWatch.

Usage:
    pip install py2app
    python setup.py py2app

Output: dist/ClaudeWatch.app
"""

from setuptools import setup

APP = ["claude_monitor.py"]

DATA_FILES = [
    "TrayIconTemplate.png",
    "TrayIconTemplate@2x.png",
]

OPTIONS = {
    "argv_emulation": False,
    "iconfile": "ClaudeWatch.icns",
    "plist": {
        "CFBundleName": "ClaudeWatch",
        "CFBundleDisplayName": "ClaudeWatch",
        "CFBundleIdentifier": "com.katespurr.claudewatch",
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
        "LSUIElement": True,          # menu bar only — no Dock icon
        "NSHumanReadableCopyright": "MIT",
    },
    "packages": ["rumps", "Crypto"],
    "includes": ["requests", "sqlite3", "hashlib", "subprocess"],
}

setup(
    name="ClaudeWatch",
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
