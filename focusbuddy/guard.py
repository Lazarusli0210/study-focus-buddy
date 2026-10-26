"""
guard.py — detects distracting apps during a focus session, and can close them.

This answers the question "what happens after psutil finds a distracting app?":

    1. DETECT  – every few seconds, list running processes and compare them to the blocklist.
    2. WARN    – a newly found app produces a "new" action; the GUI shows an in-app banner
                 (NOT a system notification, which would itself be a distraction) and the
                 event is written to the session log, so the user sees their pattern later.
    3. ESCALATE (only in "close" mode) – if the app is still open after grace_seconds, the
                 guard asks it to quit (psutil terminate = a polite SIGTERM / WM_CLOSE),
                 producing a "closed" action. The grace period lets the user save work first.
    4. CLEAR   – when the app disappears, a "cleared" action removes the banner.

The guard only runs during FOCUS, never during breaks (breaks are free time).

psutil usage follows the official docs:
    process_iter(['pid', 'name']) and exception handling —
    https://psutil.readthedocs.io/en/latest/#psutil.process_iter
    Process.terminate() — https://psutil.readthedocs.io/en/latest/#psutil.Process.terminate
All other code here is original.
"""

import os
import time
from dataclasses import dataclass, field

try:
    import psutil                               # optional: the app still runs without it
except ImportError:                              # pragma: no cover - depends on environment
    psutil = None


def normalise(name: str) -> str:
    """'Discord.exe' -> 'discord', 'Spotify.app' -> 'spotify' so names compare reliably
    across Windows, macOS and Linux."""
    name = (name or "").strip().lower()
    for suffix in (".exe", ".app"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name


@dataclass
class Detection:
    """One blocklisted app that is currently open."""
    entry: str                  # the blocklist entry it matched, e.g. "discord"
    process_name: str           # the real process name, e.g. "Discord.exe"
    pids: list                  # every matching process id (apps often run several)
    first_seen: float           # clock time when it was first noticed this session


@dataclass
class GuardAction:
    """What the GUI should react to after a scan.

    kind is one of:
        "new"      – a distraction was just opened
        "ongoing"  – still open; seconds_left counts down to auto-close in "close" mode
        "closed"   – the guard closed it
        "cleared"  – the user closed it themselves
    """
    kind: str
    entry: str
    process_name: str
    seconds_left: float = None


@dataclass
class DistractionGuard:
    """Scans running processes against a blocklist.

    process_source and terminator are injectable so the tests can simulate processes
    without actually opening or killing anything.
    """
    blocked: list
    mode: str = "warn"                          # "off" | "warn" | "close"
    grace_seconds: float = 20
    clock: callable = time.monotonic
    process_source: callable = None             # returns iterable of (pid, name)
    terminator: callable = None                 # called with a list of pids to close
    active: dict = field(default_factory=dict)  # entry -> Detection currently open

    def __post_init__(self):
        self.blocked = [normalise(b) for b in self.blocked if normalise(b)]
        self._own_pid = os.getpid()             # never match ourselves
        if self.process_source is None:
            self.process_source = self._psutil_processes
        if self.terminator is None:
            self.terminator = self._psutil_terminate

    @staticmethod
    def available() -> bool:
        """True if psutil is installed, i.e. real detection is possible."""
        return psutil is not None

    def match(self, process_name: str):
        """Return the blocklist entry that matches process_name, or None.

        An entry matches if the normalised name equals it or starts with it, so the entry
        'discord' also catches 'DiscordPTB' and 'discordcanary'."""
        name = normalise(process_name)
        for entry in self.blocked:
            if name == entry or name.startswith(entry):
                return entry
        return None

    def scan(self) -> list:
        """Look at running processes once and return a list of GuardAction."""
        if self.mode == "off":
            return []
        now = self.clock()
        found = {}                              # entry -> (process_name, [pids]) this scan
        for pid, name in self.process_source():
            if pid == self._own_pid:
                continue
            entry = self.match(name)
            if entry:
                found.setdefault(entry, (name, []))[1].append(pid)

        actions = []
        # 1) apps that were open last scan but are gone now
        for entry in list(self.active):
            if entry not in found:
                gone = self.active.pop(entry)
                actions.append(GuardAction("cleared", entry, gone.process_name))

        # 2) apps that are open now
        for entry, (name, pids) in found.items():
            det = self.active.get(entry)
            if det is None:                     # just appeared
                self.active[entry] = Detection(entry, name, pids, now)
                actions.append(GuardAction("new", entry, name, self._left(now, now)))
                continue
            det.pids = pids                     # pids can change (app restarted a helper)
            left = self._left(det.first_seen, now)
            if self.mode == "close" and left <= 0:
                self.terminator(pids)
                self.active.pop(entry)
                actions.append(GuardAction("closed", entry, name, 0))
            else:
                actions.append(GuardAction("ongoing", entry, name, left))
        return actions

    def reset(self):
        """Forget everything; called at the start and end of each focus session."""
        self.active.clear()

    def _left(self, first_seen, now):
        """Seconds until auto-close (None in "warn" mode, where nothing is closed)."""
        if self.mode != "close":
            return None
        return max(0.0, self.grace_seconds - (now - first_seen))

    # ----- real implementations (psutil) ------------------------------------------

    @staticmethod
    def _psutil_processes():
        """Yield (pid, name) for every running process. Pattern from the psutil docs:
        passing attrs to process_iter() pre-fetches them and skips processes we may not read."""
        if psutil is None:
            return
        for proc in psutil.process_iter(["pid", "name"]):
            info = proc.info
            if info.get("name"):
                yield info["pid"], info["name"]

    @staticmethod
    def _psutil_terminate(pids):
        """Politely ask each process to quit. A process can vanish or be protected
        between the scan and this call, so both errors are expected and ignored."""
        if psutil is None:
            return
        for pid in pids:
            try:
                psutil.Process(pid).terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
