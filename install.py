"""
TokenBurn LaunchAgent installer.
Installs com.tokenburn.app as a macOS LaunchAgent so it starts with the system.
Run once: python3 install.py
To uninstall: python3 install.py --uninstall
"""

import os
import sys
import subprocess
import argparse
from pathlib import Path

LABEL       = "com.tokenburn.app"
PLIST_DIR   = Path.home() / "Library" / "LaunchAgents"
PLIST_PATH  = PLIST_DIR / f"{LABEL}.plist"
SCRIPT      = Path(__file__).resolve().parent / "tokenburn.py"
PYTHON      = "/opt/homebrew/bin/python3.12"
LOG_DIR     = Path.home() / "Library" / "Logs"
STDOUT_LOG  = str(LOG_DIR / "tokenburn.log")
STDERR_LOG  = str(LOG_DIR / "tokenburn.err")

PLIST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>

    <key>ProgramArguments</key>
    <array>
        <string>{python}</string>
        <string>{script}</string>
    </array>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <false/>

    <key>StandardOutPath</key>
    <string>{stdout}</string>

    <key>StandardErrorPath</key>
    <string>{stderr}</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
"""


def _launchctl(*args):
    result = subprocess.run(["launchctl", *args], capture_output=True, text=True)
    if result.returncode != 0 and result.stderr.strip():
        print(f"  launchctl warning: {result.stderr.strip()}")
    return result.returncode


def install():
    PLIST_DIR.mkdir(parents=True, exist_ok=True)

    plist = PLIST_TEMPLATE.format(
        label=LABEL,
        python=PYTHON,
        script=str(SCRIPT),
        stdout=STDOUT_LOG,
        stderr=STDERR_LOG,
    )
    PLIST_PATH.write_text(plist)
    print(f"  wrote {PLIST_PATH}")

    # Unload first in case an old version is running
    _launchctl("unload", str(PLIST_PATH))
    rc = _launchctl("load", str(PLIST_PATH))
    if rc == 0:
        print(f"  loaded  {LABEL}")
    else:
        print(f"  load returned {rc} — check ~/Library/Logs/tokenburn.err")

    print()
    print("TokenBurn will now start automatically on login.")
    print(f"Logs: {STDOUT_LOG}")
    print(f"      {STDERR_LOG}")
    print()
    print("To start now:")
    print(f"  launchctl start {LABEL}")
    print()
    print("To stop:")
    print(f"  launchctl stop {LABEL}")
    print()
    print("To uninstall:")
    print(f"  python3 {__file__} --uninstall")


def uninstall():
    if not PLIST_PATH.exists():
        print(f"  {PLIST_PATH} not found — nothing to uninstall")
        return
    _launchctl("unload", str(PLIST_PATH))
    PLIST_PATH.unlink()
    print(f"  removed {PLIST_PATH}")
    print(f"  unloaded {LABEL}")
    print("TokenBurn uninstalled.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Install or remove TokenBurn LaunchAgent")
    parser.add_argument("--uninstall", action="store_true", help="Remove the LaunchAgent")
    args = parser.parse_args()

    if args.uninstall:
        uninstall()
    else:
        install()
