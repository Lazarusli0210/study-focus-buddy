"""
=============================================================================
VERSION 0 — kept for reference only. Do not run this as the app; run main.py.
=============================================================================

What this is: the design exactly as scoped in the A1 pitch, written out as code —
a 25/5 Pomodoro timer with plyer notifications and an optional psutil warning.
It documents the starting point so the changes in v1 can be compared against it.

Why it was replaced (A1 pitch feedback, and problems visible in the code itself):

  [PROBLEM 1] Notifications contradicted the goal.
      notify() below fires a system pop-up whenever a distracting app is found, i.e.
      DURING focus. A pop-up is itself an interruption. -> In v1, notifications are only
      allowed at phase boundaries, and this rule is enforced in focusbuddy/notifier.py.

  [PROBLEM 2] Detecting an app did nothing useful.
      check_apps() printed a warning and the user could simply ignore it. Nothing was
      logged, nothing escalated. -> v1 guard.py has warn/close modes with a grace period,
      and every distraction is logged for the history view.

  [PROBLEM 3] Too small and all in one file.
      Timer, GUI and checks were tangled together, so nothing could be tested. The timer
      counted down with after(1000) and drifted by several seconds per session.
      -> v1 splits the logic into modules with unit tests, and uses a deadline-based timer.

  [PROBLEM 4] Website blocking was only a "stretch goal".
      -> v1 implements it as a core feature (site_blocker.py).

Lines marked  # v0-ISSUE  show where each problem lives.
"""

import tkinter as tk
from plyer import notification
import psutil

WORK_MIN = 25
BREAK_MIN = 5
DISTRACTING = ["Discord.exe", "steam.exe"]   # v0-ISSUE: exact names only; misses "Discord" on macOS

seconds_left = WORK_MIN * 60
on_break = False


def notify(msg):
    # v0-ISSUE (PROBLEM 1): called mid-session from check_apps()
    notification.notify(title="Study Focus Buddy", message=msg, timeout=5)


def check_apps():
    # v0-ISSUE (PROBLEM 2): warns, but nothing else happens and nothing is recorded
    for p in psutil.process_iter(["name"]):
        if p.info["name"] in DISTRACTING:
            notify(p.info["name"] + " is open! Get back to work.")
    root.after(10000, check_apps)


def tick():
    global seconds_left, on_break
    if seconds_left > 0:
        seconds_left -= 1                     # v0-ISSUE (PROBLEM 3): drifts; after() is never exactly 1000 ms
    else:
        on_break = not on_break
        seconds_left = (BREAK_MIN if on_break else WORK_MIN) * 60
        notify("Break time!" if on_break else "Back to work!")
    label.config(text=f"{seconds_left // 60:02d}:{seconds_left % 60:02d}")
    root.after(1000, tick)


if __name__ == "__main__":
    root = tk.Tk()
    root.title("Study Focus Buddy v0")
    label = tk.Label(root, font=("Helvetica", 48))
    label.pack(padx=40, pady=40)
    tick()
    check_apps()
    root.mainloop()
