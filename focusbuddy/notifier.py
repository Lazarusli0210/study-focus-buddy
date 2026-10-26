"""
notifier.py — system notifications, with a strict rule about WHEN they may appear.

The problem raised in feedback: a focus app that pops up notifications interrupts the very
focus it is meant to protect. The rule adopted here is:

    A system notification is only allowed at a phase boundary — the moment a focus session
    ends or a break ends. At those moments the user's attention is *supposed* to move, so
    the notification guides the transition instead of breaking concentration.

    During a focus session nothing is ever sent to the system tray. Distraction warnings are
    shown inside the app window only (see gui.py), so they are visible when the user comes
    back to the window but do not pull them out of the task.

The rule is enforced in code, not just by convention: notify() refuses any event name that is
not in ALLOWED_EVENTS, so a future change cannot accidentally add mid-session pop-ups.

plyer call signature from the plyer docs: https://plyer.readthedocs.io/en/latest/api.html
(notification.notify(title, message, app_name, timeout)). The rest is original code.
"""

try:
    from plyer import notification as _plyer_notification   # optional dependency
except ImportError:                                           # pragma: no cover
    _plyer_notification = None

# The ONLY notifications the app is allowed to send. Messages are format strings.
ALLOWED_EVENTS = {
    "focus_complete": ("Focus session complete",
                       "Nice work on \"{task}\". Take a {minutes}-minute break — step away from the screen."),
    "break_complete": ("Break over",
                       "Ready for the next session? Open Study Focus Buddy and set your next task."),
}


class Notifier:
    """Sends the allowed notifications through plyer, falling back to a sound.

    Args:
        enabled: user setting; when False nothing is sent.
        fallback: function called if plyer is missing or fails (the GUI passes root.bell).
        backend: object with a notify(...) method; injectable for tests.
    """

    def __init__(self, enabled=True, fallback=None, backend=_plyer_notification):
        self.enabled = enabled
        self.fallback = fallback
        self.backend = backend
        self.sent = []                          # history of (event, title) — handy for tests

    def notify(self, event: str, **details) -> bool:
        """Send one notification. Returns True if it went through plyer."""
        if event not in ALLOWED_EVENTS:
            raise ValueError(f"'{event}' is not an allowed notification moment")
        if not self.enabled:
            return False
        title, template = ALLOWED_EVENTS[event]
        try:
            message = template.format(**details)
        except (KeyError, IndexError):          # a detail was missing: send the plain text
            message = template.replace("{", "").replace("}", "")
        self.sent.append((event, title))
        if self.backend is not None:
            try:
                self.backend.notify(title=title, message=message,
                                    app_name="Study Focus Buddy", timeout=8)
                return True
            except Exception:                   # plyer raises different errors per platform
                pass
        if self.fallback:
            self.fallback()
        return False
