"""
Study Focus Buddy — a desktop app that protects a study session from distraction.

Package layout (each module has one job, so the logic can be tested without the GUI):
    config.py        settings dataclass + load/save to JSON
    timer.py         FocusTimer: the focus/break state machine (no GUI code)
    guard.py         DistractionGuard: detects (and optionally closes) blocked apps via psutil
    site_blocker.py  HostsBlocker: blocks websites by editing the system hosts file
    notifier.py      Notifier: system notifications, restricted to phase boundaries only
    history.py       SessionLog: stores every session and computes statistics
    charts.py        builds the matplotlib history chart
    gui.py           StudyFocusApp: the tkinter interface that wires everything together
"""

__version__ = "1.0.0"
