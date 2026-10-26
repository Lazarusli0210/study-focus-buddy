"""
gui.py — the tkinter interface. It owns no logic of its own: it connects the timer, guard,
site blocker, notifier and session log, and shows their state.

How each part of the window maps to the distraction problem (full table in docs/DESIGN.md):
    task box        BEFORE a session — commit to one concrete task (start is disabled without it)
    timer           DURING — a fixed, visible end point makes it easier to keep going
    website block   DURING — removes the easiest distractions before temptation happens
    warning banner  DURING — catches app distractions the moment they start, and reminds the
                    user of the task they committed to
    reflection      AFTER — one-click self-rating turns each session into feedback
    footer/history  OVER TIME — shows streaks and the most common distraction

tkinter references: the official docs (https://docs.python.org/3/library/tkinter.html,
https://docs.python.org/3/library/tkinter.ttk.html). The repeating root.after() "game loop"
pattern is the standard tkinter way to run periodic code without threads — it is also how
the GeeksforGeeks Pomodoro tutorial cited in the pitch updates its clock
(https://www.geeksforgeeks.org/python/create-a-pomodoro-using-python-tkinter/). Only the
pattern was reused; this file's code is original.
"""

import tkinter as tk
from datetime import datetime
from tkinter import ttk, messagebox

from .config import Settings, save_settings, GUARD_MODES
from .guard import DistractionGuard
from .history import SessionLog, SessionRecord
from .notifier import Notifier
from .site_blocker import HostsBlocker
from .timer import FocusTimer, Phase, FOCUS_COMPLETE, BREAK_COMPLETE, format_seconds

TICK_MS = 250                               # how often the main loop runs (4x per second)

# Colours for each phase, so the state is readable from across the room.
PHASE_STYLE = {
    Phase.IDLE:        {"bg": "#f4f1ea", "fg": "#2d2a26", "label": "Ready when you are"},
    Phase.FOCUS:       {"bg": "#e3efe6", "fg": "#1f4d34", "label": "Focus"},
    Phase.SHORT_BREAK: {"bg": "#e4edf5", "fg": "#1f3f5c", "label": "Short break"},
    Phase.LONG_BREAK:  {"bg": "#e4edf5", "fg": "#1f3f5c", "label": "Long break"},
}
BANNER_BG = "#fbe3d6"                       # soft orange: noticeable, not alarming
BANNER_FG = "#7a2e12"


class StudyFocusApp:
    """The main window.

    Args:
        root: the tk.Tk() window.
        settings: a validated Settings object.
        log: SessionLog to record sessions into.
        settings_path: where to save settings when changed (None = default location).
        time_scale: divide all durations by this (60 = minutes become seconds, for demos).
        blocker: HostsBlocker; injectable so tests never touch the real hosts file.
    """

    def __init__(self, root: tk.Tk, settings: Settings, log: SessionLog,
                 settings_path=None, time_scale: float = 1.0, blocker: HostsBlocker = None):
        self.root = root
        self.settings = settings
        self.log = log
        self.settings_path = settings_path
        self.time_scale = time_scale
        self.blocker = blocker or HostsBlocker()
        self.notifier = Notifier(settings.notifications, fallback=root.bell)
        self.current = None                 # dict describing the focus session in progress
        self.sites_blocked = False          # True while our hosts-file block is active
        self._settings_dirty = False        # settings changed mid-session; apply when idle
        self._next_scan_at = 0.0            # timer clock value when the guard scans next
        self._build_timer_and_guard()

        # Crash recovery: if a previous run died mid-session, its website block is still in
        # the hosts file. Remove it now so the user is never left blocked by accident.
        if self.blocker.is_blocking():
            self.blocker.unblock()

        self._build_ui()
        self._refresh_footer()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(TICK_MS, self._loop)

    # ======================================================================= setup

    def _build_timer_and_guard(self):
        """(Re)create the timer and guard from the current settings."""
        s, k = self.settings, 60 / self.time_scale      # k = seconds per "minute"
        self.timer = FocusTimer(s.focus_minutes * k, s.short_break_minutes * k,
                                s.long_break_minutes * k, s.sessions_before_long_break)
        self.guard = DistractionGuard(s.blocked_apps, mode=s.guard_mode,
                                      grace_seconds=s.grace_seconds,
                                      clock=self.timer.clock)
        self.notifier.enabled = s.notifications

    def _build_ui(self):
        """Create every widget. Layout: task row, phase label, big clock, buttons,
        hidden warning banner, status line, footer stats."""
        self.root.title("Study Focus Buddy")
        self.root.minsize(420, 430)
        self.frame = tk.Frame(self.root, padx=24, pady=18)
        self.frame.pack(fill="both", expand=True)

        # --- task commitment -------------------------------------------------------
        self.task_prompt = tk.Label(self.frame, text="What will you work on this session?",
                                    font=("Helvetica", 11), anchor="w")
        self.task_prompt.pack(fill="x")
        self.task_var = tk.StringVar()
        self.task_var.trace_add("write", lambda *_: self._update_buttons())
        self.task_entry = ttk.Entry(self.frame, textvariable=self.task_var, font=("Helvetica", 12))
        self.task_entry.pack(fill="x", pady=(4, 12))
        self.task_entry.bind("<Return>", lambda _e: self.start())
        self.task_entry.focus_set()

        # --- phase + clock -----------------------------------------------------------
        self.phase_label = tk.Label(self.frame, font=("Helvetica", 13, "bold"))
        self.phase_label.pack()
        self.clock_label = tk.Label(self.frame, font=("Helvetica", 56, "bold"))
        self.clock_label.pack(pady=(0, 6))
        self.cycle_label = tk.Label(self.frame, font=("Helvetica", 10))
        self.cycle_label.pack()

        # --- controls ------------------------------------------------------------------
        buttons = tk.Frame(self.frame)
        buttons.pack(pady=12)
        self.start_btn = ttk.Button(buttons, text="Start focus", command=self.start)
        self.pause_btn = ttk.Button(buttons, text="Pause", command=self.toggle_pause)
        self.stop_btn = ttk.Button(buttons, text="Stop", command=self.stop)
        self.skip_btn = ttk.Button(buttons, text="Skip break", command=self.skip_break)
        for b in (self.start_btn, self.pause_btn, self.stop_btn, self.skip_btn):
            b.pack(side="left", padx=4)

        # --- distraction banner (packed only when needed) ------------------------------
        self.banner = tk.Label(self.frame, bg=BANNER_BG, fg=BANNER_FG, wraplength=360,
                               justify="left", font=("Helvetica", 11), padx=10, pady=8)

        # --- status + footer -------------------------------------------------------------
        self.status_var = tk.StringVar(value=self._guard_status_text())
        self.status_label = tk.Label(self.frame, textvariable=self.status_var,
                                     font=("Helvetica", 9), fg="#6b665e", wraplength=380)
        self.status_label.pack(side="bottom", pady=(6, 0))
        self.footer_var = tk.StringVar()
        self.footer = tk.Label(self.frame, textvariable=self.footer_var, font=("Helvetica", 10))
        self.footer.pack(side="bottom")

        # --- menu ------------------------------------------------------------------------
        menubar = tk.Menu(self.root)
        app_menu = tk.Menu(menubar, tearoff=False)
        app_menu.add_command(label="Settings…", command=self.open_settings)
        app_menu.add_command(label="History…", command=self.open_history)
        app_menu.add_separator()
        app_menu.add_command(label="Quit", command=self.on_close)
        menubar.add_cascade(label="Study Focus Buddy", menu=app_menu)
        self.root.config(menu=menubar)

        self._render()

    # ======================================================================= actions

    def start(self):
        """Start a focus session. Requires a task: naming the task is the commitment step."""
        task = self.task_var.get().strip()
        if self.timer.phase is not Phase.IDLE:
            return
        if not task:
            self.task_prompt.config(fg=BANNER_FG)   # gently highlight what is missing
            self.task_entry.focus_set()
            return
        self.task_prompt.config(fg="black")
        self.timer.start_focus()
        self.guard.reset()
        self._next_scan_at = 0.0                     # scan immediately
        self.current = {
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "task": task,
            "planned": int(self.timer.durations[Phase.FOCUS]),
            "distractions": [],
            "pauses": 0,
        }
        if self.settings.block_websites:
            ok, message = self.blocker.block(self.settings.blocked_sites)
            self.sites_blocked = ok
            self.status_var.set(message)
        self._render()

    def toggle_pause(self):
        """Pause or resume. Each pause during focus is counted in the session record."""
        if self.timer.phase is Phase.IDLE:
            return
        if self.timer.paused:
            self.timer.resume()
        else:
            self.timer.pause()
            if self.timer.phase is Phase.FOCUS and self.current:
                self.current["pauses"] += 1
        self._render()

    def stop(self):
        """Abandon the current focus session (recorded as unfinished) or end a break."""
        if self.timer.phase is Phase.FOCUS:
            focused = self.timer.stop()
            self._finish_focus(completed=False, focused_seconds=focused)
        else:
            self.timer.stop()
        self._back_to_idle()

    def skip_break(self):
        self.timer.skip_break()
        self._back_to_idle()

    # ======================================================================= main loop

    def _loop(self):
        """Runs every TICK_MS milliseconds for the whole life of the window."""
        event = self.timer.tick()
        if event == FOCUS_COMPLETE:
            self._on_focus_complete()
        elif event == BREAK_COMPLETE:
            self._on_break_complete()

        # The guard only works during an un-paused focus session.
        if (self.timer.phase is Phase.FOCUS and not self.timer.paused
                and self.guard.mode != "off" and self.timer.clock() >= self._next_scan_at):
            self._next_scan_at = self.timer.clock() + self.settings.scan_interval_seconds
            self._handle_guard(self.guard.scan())

        self._render()
        self.root.after(TICK_MS, self._loop)

    def _on_focus_complete(self):
        """Timer ran out: unblock, notify (a phase boundary, so allowed), ask for a rating."""
        task = self.current["task"] if self.current else ""
        self._end_focus_side_effects()
        minutes = round(self.timer.durations[self.timer.phase] / 60 * self.time_scale)
        self.notifier.notify("focus_complete", task=task, minutes=minutes)
        rating = ReflectionDialog(self.root, task).result      # waits for the user
        self._finish_focus(completed=True,
                           focused_seconds=self.timer.durations[Phase.FOCUS], rating=rating)

    def _on_break_complete(self):
        """Break ended: one notification, and bring the window forward ready for a new task."""
        self.notifier.notify("break_complete")
        self._back_to_idle()
        self.root.deiconify()
        self.root.lift()

    def _handle_guard(self, actions):
        """React to the guard's scan results: log new distractions and update the banner."""
        for action in actions:
            if action.kind == "new" and self.current is not None:
                self.current["distractions"].append({
                    "app": action.entry,
                    "after_sec": int(self.timer.elapsed()),
                    "closed": False,
                })
                # The user is already distracted at this moment, so interrupting the
                # *distraction* is the point: bring the app window in front of it.
                self.root.deiconify()
                self.root.lift()
                self.root.attributes("-topmost", True)
                self.root.after(1500, lambda: self.root.attributes("-topmost", False))
            elif action.kind == "closed" and self.current is not None:
                for d in reversed(self.current["distractions"]):
                    if d["app"] == action.entry:
                        d["closed"] = True
                        break
        self._update_banner(actions)

    # ======================================================================= helpers

    def _update_banner(self, actions):
        """Show one banner line per distraction that is still open."""
        open_now = [a for a in actions if a.kind in ("new", "ongoing")]
        closed = [a for a in actions if a.kind == "closed"]
        lines = []
        for a in open_now:
            if a.seconds_left is None:
                lines.append(f"{a.process_name} is open.")
            else:
                lines.append(f"{a.process_name} is open — it will be closed in "
                             f"{int(-(-a.seconds_left // 1))}s. Save anything you need.")
        for a in closed:
            lines.append(f"{a.process_name} was closed.")
        if lines and self.current:
            lines.append(f"You said you'd work on: “{self.current['task']}”.")
            self.banner.config(text="\n".join(lines))
            self.banner.pack(fill="x", pady=(4, 4), before=self.footer)
        else:
            self.banner.pack_forget()

    def _end_focus_side_effects(self):
        """Things that must happen whenever a focus session ends, however it ends."""
        self.guard.reset()
        self.banner.pack_forget()
        if self.sites_blocked:
            ok, message = self.blocker.unblock()
            self.sites_blocked = not ok
            self.status_var.set(message)

    def _finish_focus(self, completed: bool, focused_seconds: float, rating: int = None):
        """Write the session to the log."""
        self._end_focus_side_effects()
        if self.current is None:
            return
        self.log.append(SessionRecord(
            started_at=self.current["started_at"],
            ended_at=datetime.now().isoformat(timespec="seconds"),
            task=self.current["task"],
            planned_seconds=self.current["planned"],
            focused_seconds=int(focused_seconds),
            completed=completed,
            distractions=self.current["distractions"],
            pauses=self.current["pauses"],
            rating=rating,
        ))
        self.current = None
        self._refresh_footer()

    def _back_to_idle(self):
        """Return to the start screen; apply settings changed during the session."""
        if self.timer.phase is not Phase.IDLE:
            return
        if self._settings_dirty:
            done = self.timer.completed_focus_sessions
            self._build_timer_and_guard()
            self.timer.completed_focus_sessions = done   # keep the long-break cycle position
            self._settings_dirty = False
            self.status_var.set(self._guard_status_text())
        self.task_var.set("")
        self.task_entry.focus_set()
        self._render()

    def _render(self):
        """Update colours, labels and buttons to match the timer state."""
        phase = self.timer.phase
        style = PHASE_STYLE[phase]
        for w in (self.root, self.frame, self.phase_label, self.clock_label, self.cycle_label,
                  self.task_prompt, self.footer, self.status_label):
            w.config(bg=style["bg"])
        self.clock_label.config(fg=style["fg"])
        label = style["label"] + (" (paused)" if self.timer.paused else "")
        self.phase_label.config(text=label, fg=style["fg"])
        shown = self.timer.remaining() if phase is not Phase.IDLE else \
            self.timer.durations[Phase.FOCUS]
        self.clock_label.config(text=format_seconds(shown))
        n = self.settings.sessions_before_long_break
        pos = self.timer.completed_focus_sessions % n
        self.cycle_label.config(text="●" * pos + "○" * (n - pos) + "   until long break")
        self.task_entry.config(state="normal" if phase is Phase.IDLE else "disabled")
        self._update_buttons()

    def _update_buttons(self):
        """Enable only the buttons that make sense right now."""
        phase = self.timer.phase
        idle = phase is Phase.IDLE
        on_break = phase in (Phase.SHORT_BREAK, Phase.LONG_BREAK)
        self.start_btn.state(["!disabled"] if idle and self.task_var.get().strip() else ["disabled"])
        self.pause_btn.state(["disabled"] if idle else ["!disabled"])
        self.pause_btn.config(text="Resume" if self.timer.paused else "Pause")
        self.stop_btn.state(["disabled"] if idle else ["!disabled"])
        self.skip_btn.state(["!disabled"] if on_break else ["disabled"])

    def _refresh_footer(self):
        """Today's totals and streak, read from the log."""
        s = self.log.summary()
        parts = [f"Today: {s['today_minutes']} min · {s['today_sessions']} sessions",
                 f"Streak: {s['streak']} day{'s' if s['streak'] != 1 else ''}"]
        if s["top_distraction"]:
            parts.append(f"Top distraction: {s['top_distraction']}")
        self.footer_var.set("   |   ".join(parts))

    def _guard_status_text(self):
        if self.settings.guard_mode == "off":
            return "App guard is off."
        if not DistractionGuard.available():
            return "App guard unavailable: install psutil (pip install psutil)."
        mode = "warn only" if self.settings.guard_mode == "warn" else \
            f"close after {self.settings.grace_seconds}s"
        return f"App guard on ({mode}) · watching {len(self.settings.blocked_apps)} apps"

    # ======================================================================= windows

    def open_settings(self):
        SettingsDialog(self.root, self.settings, self._apply_settings)

    def _apply_settings(self, new: Settings):
        """Called by SettingsDialog after the user presses Save."""
        self.settings = new.validate()
        save_settings(self.settings, self.settings_path)
        if self.timer.phase is Phase.IDLE:
            self._settings_dirty = True
            self._back_to_idle()
        else:
            self._settings_dirty = True
            self.status_var.set("Settings saved — they apply from the next session.")

    def open_history(self):
        HistoryWindow(self.root, self.log)

    def on_close(self):
        """Closing mid-session records the session as unfinished and always unblocks sites."""
        if self.timer.phase is Phase.FOCUS:
            if not messagebox.askyesno("Quit?", "A focus session is running. Quit anyway?\n"
                                       "It will be saved as unfinished.", parent=self.root):
                return
            self._finish_focus(completed=False, focused_seconds=self.timer.stop())
        self._end_focus_side_effects()
        self.root.destroy()


# ============================================================================ dialogs

class ReflectionDialog:
    """Small modal window after each completed session: 'Did you do what you planned?'
    One click, three options, so reflecting costs almost no effort. result = 3, 2, 1 or None."""

    CHOICES = [(3, "Got it done"), (2, "Partly"), (1, "Not really")]

    def __init__(self, parent, task: str):
        self.result = None
        self.win = tk.Toplevel(parent)
        self.win.title("Session complete")
        self.win.transient(parent)
        self.win.resizable(False, False)
        tk.Label(self.win, text="Session complete — break time!",
                 font=("Helvetica", 13, "bold")).pack(padx=20, pady=(16, 4))
        tk.Label(self.win, text=f"Did you finish “{task}”?", wraplength=300).pack(padx=20)
        row = tk.Frame(self.win)
        row.pack(padx=20, pady=16)
        for value, text in self.CHOICES:
            ttk.Button(row, text=text, command=lambda v=value: self._choose(v)).pack(side="left", padx=3)
        self.win.protocol("WM_DELETE_WINDOW", self.win.destroy)   # closing = no rating
        self.win.grab_set()
        parent.wait_window(self.win)            # the main after() loop keeps running meanwhile

    def _choose(self, value):
        self.result = value
        self.win.destroy()


class SettingsDialog:
    """Edit durations, guard strictness, blocklists and website blocking."""

    def __init__(self, parent, settings: Settings, on_save):
        self.on_save = on_save
        self.win = tk.Toplevel(parent)
        self.win.title("Settings")
        self.win.transient(parent)
        body = tk.Frame(self.win, padx=16, pady=12)
        body.pack(fill="both", expand=True)

        # Each entry: (attribute name, label, min, max) — built in a loop to avoid repetition.
        self.int_vars = {}
        numbers = [("focus_minutes", "Focus (minutes)", 1, 180),
                   ("short_break_minutes", "Short break (minutes)", 1, 60),
                   ("long_break_minutes", "Long break (minutes)", 1, 90),
                   ("sessions_before_long_break", "Sessions before long break", 1, 12),
                   ("grace_seconds", "Grace period before closing (s)", 0, 300)]
        for row, (attr, text, low, high) in enumerate(numbers):
            tk.Label(body, text=text, anchor="w").grid(row=row, column=0, sticky="w", pady=2)
            var = tk.IntVar(value=getattr(settings, attr))
            ttk.Spinbox(body, from_=low, to=high, textvariable=var, width=6).grid(row=row, column=1, sticky="w")
            self.int_vars[attr] = var

        row = len(numbers)
        tk.Label(body, text="App guard", anchor="w").grid(row=row, column=0, sticky="w", pady=2)
        self.mode_var = tk.StringVar(value=settings.guard_mode)
        ttk.Combobox(body, textvariable=self.mode_var, values=GUARD_MODES, state="readonly",
                     width=8).grid(row=row, column=1, sticky="w")

        self.apps_text = self._list_box(body, row + 1, "Blocked apps (one per line)", settings.blocked_apps)
        self.sites_text = self._list_box(body, row + 3, "Blocked websites (one per line)", settings.blocked_sites)

        self.block_var = tk.BooleanVar(value=settings.block_websites)
        ttk.Checkbutton(body, text="Block websites during focus (needs admin rights)",
                        variable=self.block_var).grid(row=row + 5, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.notify_var = tk.BooleanVar(value=settings.notifications)
        ttk.Checkbutton(body, text="Notify me when a session or break ends",
                        variable=self.notify_var).grid(row=row + 6, column=0, columnspan=2, sticky="w")

        btns = tk.Frame(body)
        btns.grid(row=row + 7, column=0, columnspan=2, pady=(12, 0), sticky="e")
        ttk.Button(btns, text="Cancel", command=self.win.destroy).pack(side="right", padx=4)
        ttk.Button(btns, text="Save", command=self._save).pack(side="right")

    @staticmethod
    def _list_box(parent, row, label, items):
        """A label plus a small multi-line Text box pre-filled with one item per line."""
        tk.Label(parent, text=label, anchor="w").grid(row=row, column=0, columnspan=2, sticky="w", pady=(8, 2))
        box = tk.Text(parent, height=4, width=36)
        box.insert("1.0", "\n".join(items))
        box.grid(row=row + 1, column=0, columnspan=2, sticky="we")
        return box

    def _save(self):
        values = {}
        for attr, var in self.int_vars.items():
            try:
                values[attr] = var.get()
            except tk.TclError:                 # the user typed letters into a number box
                values[attr] = None             # validate() will restore the default
        new = Settings(
            **values,
            guard_mode=self.mode_var.get(),
            blocked_apps=self.apps_text.get("1.0", "end").splitlines(),
            blocked_sites=self.sites_text.get("1.0", "end").splitlines(),
            block_websites=self.block_var.get(),
            notifications=self.notify_var.get(),
        )
        self.on_save(new)
        self.win.destroy()


class HistoryWindow:
    """7-day chart plus summary numbers. matplotlib is optional: without it, text only."""

    def __init__(self, parent, log: SessionLog):
        self.win = tk.Toplevel(parent)
        self.win.title("Your focus history")
        s = log.summary()
        facts = [
            f"Current streak: {s['streak']} day(s)",
            f"Sessions finished: {s['completion_rate']}% of those started"
            if s["completion_rate"] is not None else "No sessions yet — start one!",
        ]
        if s["top_distraction"]:
            facts.append(f"Most common distraction: {s['top_distraction']}")
        if s["average_minutes_to_first_distraction"] is not None:
            facts.append(f"First distraction usually after {s['average_minutes_to_first_distraction']} min "
                         "— if that's early, try shorter focus sessions.")
        tk.Label(self.win, text="\n".join(facts), justify="left", padx=16, pady=10).pack(anchor="w")

        try:
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            from .charts import build_history_figure
        except ImportError:
            tk.Label(self.win, text="Install matplotlib to see the chart.").pack(pady=10)
            return
        canvas = FigureCanvasTkAgg(build_history_figure(log.daily_totals(7)), master=self.win)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=(0, 8))
