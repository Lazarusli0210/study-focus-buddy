"""
main.py — start Study Focus Buddy.

Usage:
    python main.py            normal use
    python main.py --quick    demo mode: every "minute" lasts one second (25-min focus = 25 s)
    python main.py --check    print which optional features work on this computer, then exit
"""

import argparse
import atexit
import sys

from focusbuddy.config import load_settings, SETTINGS_FILE, HISTORY_FILE
from focusbuddy.guard import DistractionGuard
from focusbuddy.history import SessionLog
from focusbuddy.notifier import _plyer_notification
from focusbuddy.site_blocker import HostsBlocker


def check_environment() -> int:
    """Report optional features, so a tester knows what to expect before launching."""
    blocker = HostsBlocker()
    rows = [
        ("tkinter (window)", _has_module("tkinter")),
        ("psutil (app guard)", DistractionGuard.available()),
        ("plyer (notifications)", _plyer_notification is not None),
        ("matplotlib (history chart)", _has_module("matplotlib")),
        (f"hosts file writable ({blocker.hosts_path})", blocker.can_write()),
    ]
    for name, ok in rows:
        print(f"  [{'x' if ok else ' '}] {name}")
    print(f"\nSettings: {SETTINGS_FILE}\nHistory:  {HISTORY_FILE}")
    if not rows[-1][1]:
        print("Website blocking needs admin rights — see README 'Website blocking'.")
    return 0


def _has_module(name: str) -> bool:
    try:
        __import__(name)
        return True
    except ImportError:
        return False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Study Focus Buddy")
    parser.add_argument("--quick", action="store_true", help="demo mode: minutes become seconds")
    parser.add_argument("--check", action="store_true", help="check optional features and exit")
    args = parser.parse_args(argv)

    if args.check:
        return check_environment()

    import tkinter as tk                        # imported here so --check works without a display
    from focusbuddy.gui import StudyFocusApp

    # Last line of defence: whatever happens, never leave websites blocked after exit.
    blocker = HostsBlocker()
    atexit.register(lambda: blocker.unblock() if blocker.is_blocking() else None)

    root = tk.Tk()
    StudyFocusApp(root, load_settings(), SessionLog(HISTORY_FILE),
                  time_scale=60 if args.quick else 1, blocker=blocker)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
