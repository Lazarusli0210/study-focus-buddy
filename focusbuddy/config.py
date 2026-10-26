"""
config.py — user settings for Study Focus Buddy.

Settings are stored as JSON in the user's home folder (~/.study_focus_buddy/settings.json)
so they survive between runs. Everything here is original code; the dataclass + asdict()
pattern follows the Python docs: https://docs.python.org/3/library/dataclasses.html
"""

import json
import os
from dataclasses import dataclass, field, asdict, fields
from pathlib import Path

# Folder where all app data lives. The SFB_HOME environment variable lets tests (or a
# user who wants a portable install) redirect it somewhere else.
APP_DIR = Path(os.environ.get("SFB_HOME", Path.home() / ".study_focus_buddy"))
SETTINGS_FILE = APP_DIR / "settings.json"   # user preferences
HISTORY_FILE = APP_DIR / "history.jsonl"    # one JSON object per finished session

# Starting blocklists. Process names are matched case-insensitively and without ".exe",
# so "discord" matches Discord.exe on Windows and Discord on macOS.
DEFAULT_BLOCKED_APPS = ["discord", "steam", "wechat", "qq", "spotify", "netflix", "tiktok"]
DEFAULT_BLOCKED_SITES = ["youtube.com", "bilibili.com", "tiktok.com", "instagram.com",
                         "reddit.com", "x.com", "weibo.com"]

# The three strictness levels for the distraction guard (see guard.py):
#   "off"   – no checking at all
#   "warn"  – show an in-app warning and log the distraction
#   "close" – warn, then close the app if it is still open after a grace period
GUARD_MODES = ("off", "warn", "close")


@dataclass
class Settings:
    """All user-adjustable options. Default values are the classic Pomodoro numbers."""
    focus_minutes: int = 25
    short_break_minutes: int = 5
    long_break_minutes: int = 15
    sessions_before_long_break: int = 4      # every 4th break is a long one
    guard_mode: str = "warn"
    grace_seconds: int = 20                  # time to close a distraction yourself before "close" mode does it
    scan_interval_seconds: int = 3           # how often the guard looks at running processes
    blocked_apps: list = field(default_factory=lambda: list(DEFAULT_BLOCKED_APPS))
    block_websites: bool = False             # off by default: needs admin rights (see site_blocker.py)
    blocked_sites: list = field(default_factory=lambda: list(DEFAULT_BLOCKED_SITES))
    notifications: bool = True               # only ever fired at phase boundaries (see notifier.py)

    def validate(self) -> "Settings":
        """Clamp numbers to sensible ranges and tidy the lists. Returns self for chaining.

        This protects the rest of the program from a hand-edited or corrupted settings
        file (e.g. a 0-minute focus session would end instantly forever)."""
        self.focus_minutes = _clamp(self.focus_minutes, 1, 180, 25)
        self.short_break_minutes = _clamp(self.short_break_minutes, 1, 60, 5)
        self.long_break_minutes = _clamp(self.long_break_minutes, 1, 90, 15)
        self.sessions_before_long_break = _clamp(self.sessions_before_long_break, 1, 12, 4)
        self.grace_seconds = _clamp(self.grace_seconds, 0, 300, 20)
        self.scan_interval_seconds = _clamp(self.scan_interval_seconds, 1, 60, 3)
        if self.guard_mode not in GUARD_MODES:
            self.guard_mode = "warn"
        self.blocked_apps = _clean_list(self.blocked_apps)
        self.blocked_sites = [_clean_domain(s) for s in _clean_list(self.blocked_sites)]
        self.blocked_sites = [s for s in self.blocked_sites if s]
        self.block_websites = bool(self.block_websites)
        self.notifications = bool(self.notifications)
        return self


def _clamp(value, low, high, default):
    """Convert value to int and keep it inside [low, high]; fall back to default if invalid."""
    try:
        value = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


def _clean_list(items):
    """Lower-case, strip, drop blanks and duplicates while keeping the user's order."""
    if not isinstance(items, (list, tuple)):
        return []
    seen, result = set(), []
    for item in items:
        text = str(item).strip().lower()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _clean_domain(text: str) -> str:
    """Turn 'https://www.YouTube.com/watch?v=1' into 'youtube.com' for the hosts file."""
    text = text.strip().lower()
    for prefix in ("https://", "http://"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    text = text.split("/")[0].split(":")[0]
    if text.startswith("www."):
        text = text[4:]
    # A domain must contain a dot and only safe characters; anything else is rejected so it
    # can never inject extra lines into the hosts file.
    if "." not in text or not all(c.isalnum() or c in ".-" for c in text):
        return ""
    return text


def load_settings(path: Path = None) -> Settings:
    """Read settings from disk. Unknown keys are ignored and missing keys get defaults,
    so old settings files keep working after new options are added."""
    path = Path(path) if path else SETTINGS_FILE
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()                      # first run, or unreadable file
    known = {f.name for f in fields(Settings)}
    return Settings(**{k: v for k, v in raw.items() if k in known}).validate()


def save_settings(settings: Settings, path: Path = None) -> None:
    """Write settings to disk as pretty-printed JSON."""
    path = Path(path) if path else SETTINGS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
