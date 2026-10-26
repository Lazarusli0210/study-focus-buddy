"""
timer.py — the focus/break cycle as a small state machine.

Kept completely separate from tkinter so it can be unit-tested with a fake clock.

Design decisions (original code):
* The timer stores a *deadline* (clock time when the phase ends) instead of counting down
  one second at a time. Counting down with repeated after(1000) calls drifts, because each
  callback runs slightly late; comparing against a deadline never drifts.
* time.monotonic() is used instead of time.time() so changing the system clock cannot
  shorten or lengthen a session. (Python docs: https://docs.python.org/3/library/time.html#time.monotonic)
* After a break ends the timer goes back to IDLE instead of starting the next focus
  session automatically. Starting again requires the user to type what they will work on,
  which is a deliberate "re-commitment" step (see docs/DESIGN.md).
"""

import time
from enum import Enum


class Phase(Enum):
    """The four states the timer can be in."""
    IDLE = "idle"
    FOCUS = "focus"
    SHORT_BREAK = "short_break"
    LONG_BREAK = "long_break"


# Events returned by FocusTimer.tick() so the GUI knows something happened.
FOCUS_COMPLETE = "focus_complete"
BREAK_COMPLETE = "break_complete"


class FocusTimer:
    """Runs focus sessions and the breaks between them.

    Args:
        focus_sec, short_break_sec, long_break_sec: phase lengths in seconds.
        sessions_before_long_break: e.g. 4 means every 4th completed focus earns a long break.
        clock: a function returning the current time in seconds. Tests pass a fake one.
    """

    def __init__(self, focus_sec, short_break_sec, long_break_sec,
                 sessions_before_long_break=4, clock=time.monotonic):
        self.durations = {                      # seconds each phase lasts
            Phase.FOCUS: float(focus_sec),
            Phase.SHORT_BREAK: float(short_break_sec),
            Phase.LONG_BREAK: float(long_break_sec),
        }
        self.sessions_before_long_break = sessions_before_long_break
        self.clock = clock
        self.phase = Phase.IDLE
        self.paused = False
        self.completed_focus_sessions = 0       # counts towards the long-break cycle
        self._deadline = None                   # clock time when the current phase ends
        self._remaining_at_pause = None         # frozen remaining time while paused

    # ----- starting / stopping -------------------------------------------------------

    def start_focus(self):
        """Begin a new focus session (only allowed from IDLE)."""
        if self.phase is not Phase.IDLE:
            raise RuntimeError("A session is already running")
        self._enter(Phase.FOCUS)

    def stop(self) -> float:
        """Abandon whatever is running and return how many seconds of focus were done
        (0 if we were on a break). The GUI records this as an unfinished session."""
        done = self.elapsed() if self.phase is Phase.FOCUS else 0.0
        self.phase = Phase.IDLE
        self.paused = False
        self._deadline = self._remaining_at_pause = None
        return done

    def skip_break(self):
        """End a break early and return to IDLE. Ignored outside a break."""
        if self.phase in (Phase.SHORT_BREAK, Phase.LONG_BREAK):
            self.stop()

    def pause(self):
        """Freeze the countdown. Pausing is allowed, but the GUI counts pauses as
        distractions because a paused focus session is time not spent studying."""
        if self.phase is not Phase.IDLE and not self.paused:
            self._remaining_at_pause = self.remaining()
            self.paused = True

    def resume(self):
        """Continue after pause() by setting a new deadline from the frozen remaining time."""
        if self.paused:
            self._deadline = self.clock() + self._remaining_at_pause
            self._remaining_at_pause = None
            self.paused = False

    # ----- reading the state ----------------------------------------------------------

    def remaining(self) -> float:
        """Seconds left in the current phase (0 when idle)."""
        if self.phase is Phase.IDLE:
            return 0.0
        if self.paused:
            return self._remaining_at_pause
        return max(0.0, self._deadline - self.clock())

    def elapsed(self) -> float:
        """Seconds already spent in the current phase."""
        if self.phase is Phase.IDLE:
            return 0.0
        return self.durations[self.phase] - self.remaining()

    def next_break_phase(self) -> Phase:
        """Which break follows the focus session that is running now."""
        upcoming = self.completed_focus_sessions + 1
        if upcoming % self.sessions_before_long_break == 0:
            return Phase.LONG_BREAK
        return Phase.SHORT_BREAK

    # ----- the heartbeat ------------------------------------------------------------

    def tick(self):
        """Call this regularly (the GUI does it every 250 ms). Returns FOCUS_COMPLETE,
        BREAK_COMPLETE, or None, and moves to the next phase when time is up."""
        if self.phase is Phase.IDLE or self.paused or self.remaining() > 0:
            return None
        if self.phase is Phase.FOCUS:
            next_phase = self.next_break_phase()
            self.completed_focus_sessions += 1
            self._enter(next_phase)             # the break starts straight away
            return FOCUS_COMPLETE
        # a break just ended: wait for the user to start the next session themselves
        self.stop()
        return BREAK_COMPLETE

    def _enter(self, phase: Phase):
        """Switch to a phase and set its deadline."""
        self.phase = phase
        self.paused = False
        self._remaining_at_pause = None
        self._deadline = self.clock() + self.durations[phase]


def format_seconds(seconds: float) -> str:
    """Format 1499.2 as '25:00' (rounds up so the display never shows 00:00 too early)."""
    whole = int(-(-seconds // 1))               # ceiling without importing math
    minutes, secs = divmod(max(0, whole), 60)
    return f"{minutes:02d}:{secs:02d}"
