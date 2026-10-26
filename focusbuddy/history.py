"""
history.py — remembers every session and turns the log into feedback for the user.

Why this matters for the "distraction" problem: blocking stops distraction in the moment,
but the history shows the *pattern* afterwards — which app pulls you away most, at what point
in a session, and whether your streak is growing. That reflection is what changes habits.

Storage format: JSON Lines (one JSON object per line) in ~/.study_focus_buddy/history.jsonl.
Appending one line per session is safe even if the app is closed suddenly, and a damaged line
only loses that one session (load() skips it). Format description: https://jsonlines.org/
All code here is original.
"""

import json
from collections import Counter
from dataclasses import dataclass, field, asdict, fields
from datetime import datetime, date, timedelta
from pathlib import Path


@dataclass
class SessionRecord:
    """One focus session, finished or abandoned."""
    started_at: str                     # ISO timestamp, e.g. "2026-10-26T09:00:00"
    ended_at: str
    task: str                           # what the user said they would work on
    planned_seconds: int                # length the session was set to
    focused_seconds: int                # time actually spent in focus (excludes pauses)
    completed: bool                     # True if the timer ran out, False if stopped early
    distractions: list = field(default_factory=list)  # [{"app": .., "after_sec": .., "closed": ..}]
    pauses: int = 0                     # how many times the user paused
    rating: int = None                  # self-rating after the session: 3 done, 2 partly, 1 not really

    @property
    def day(self) -> date:
        """Calendar day the session started on."""
        return datetime.fromisoformat(self.started_at).date()


class SessionLog:
    """Reads and writes SessionRecords and computes statistics from them."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def append(self, record: SessionRecord) -> None:
        """Add one session to the end of the file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")

    def load(self) -> list:
        """Return all sessions, oldest first. Broken lines are skipped, not fatal."""
        if not self.path.exists():
            return []
        known = {f.name for f in fields(SessionRecord)}
        records = []
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    raw = json.loads(line)
                    records.append(SessionRecord(**{k: v for k, v in raw.items() if k in known}))
                except (ValueError, TypeError):
                    continue
        return records

    # ----- statistics ---------------------------------------------------------------

    def daily_totals(self, days: int = 7, today: date = None) -> list:
        """List of (day, focused_minutes, distraction_count) for the last `days` days,
        oldest first, including days with zero sessions (so a chart has no gaps)."""
        today = today or date.today()
        first = today - timedelta(days=days - 1)
        minutes = {first + timedelta(i): 0.0 for i in range(days)}
        distractions = dict.fromkeys(minutes, 0)
        for rec in self.load():
            if rec.day in minutes:
                minutes[rec.day] += rec.focused_seconds / 60
                distractions[rec.day] += len(rec.distractions) + rec.pauses
        return [(d, round(minutes[d], 1), distractions[d]) for d in sorted(minutes)]

    def streak(self, today: date = None) -> int:
        """Consecutive days (ending today, or yesterday if nothing yet today) with at
        least one completed session. Counting from yesterday means the streak does not
        look 'broken' first thing in the morning."""
        today = today or date.today()
        done_days = {r.day for r in self.load() if r.completed}
        day = today if today in done_days else today - timedelta(days=1)
        count = 0
        while day in done_days:
            count += 1
            day -= timedelta(days=1)
        return count

    def summary(self, today: date = None) -> dict:
        """Numbers shown in the app's footer and history window."""
        today = today or date.today()
        records = self.load()
        todays = [r for r in records if r.day == today]
        apps = Counter(d.get("app", "?") for r in records for d in r.distractions)
        finished = [r for r in records if r.completed]
        return {
            "today_minutes": round(sum(r.focused_seconds for r in todays) / 60),
            "today_sessions": sum(1 for r in todays if r.completed),
            "streak": self.streak(today),
            "top_distraction": apps.most_common(1)[0][0] if apps else None,
            "completion_rate": round(100 * len(finished) / len(records)) if records else None,
            "average_minutes_to_first_distraction": _avg_first_distraction(records),
        }


def _avg_first_distraction(records) -> float:
    """How many minutes into a session the first distraction usually happens.
    Tells the user whether shorter sessions might suit them better."""
    times = [min(d.get("after_sec", 0) for d in r.distractions) for r in records if r.distractions]
    return round(sum(times) / len(times) / 60, 1) if times else None
