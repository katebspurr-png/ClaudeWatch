"""
py2app build script for ClaudeMonitor.

Usage:
    pip install py2app
    python setup.py py2app

Output: dist/ClaudeMonitor.app
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
        "CFBundleName": "ClaudeMonitor",
        "CFBundleDisplayName": "ClaudeMonitor",
        "CFBundleIdentifier": "com.katespurr.claudemonitor",
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
        "LSUIElement": True,          # menu bar only — no Dock icon
        "NSHumanReadableCopyright": "MIT",
    },
    "packages": ["rumps", "Crypto", "requests", "zstandard", "urllib3", "certifi", "charset_normalizer", "idna"],
    "includes": ["sqlite3", "hashlib", "subprocess"],
}

setup(
    name="ClaudeMonitor",
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
