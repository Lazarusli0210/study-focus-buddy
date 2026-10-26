"""
Unit tests for the non-GUI modules. Run with:  python -m pytest

A FakeClock replaces real time so a 25-minute session can be tested instantly, and fake
process lists replace psutil so no real app is ever opened or closed.
"""

import json
from datetime import date, datetime, timedelta

import pytest

from focusbuddy.config import Settings, load_settings, save_settings, _clean_domain
from focusbuddy.guard import DistractionGuard, normalise
from focusbuddy.history import SessionLog, SessionRecord
from focusbuddy.notifier import Notifier
from focusbuddy.site_blocker import HostsBlocker, START_MARK
from focusbuddy.timer import FocusTimer, Phase, FOCUS_COMPLETE, BREAK_COMPLETE, format_seconds


class FakeClock:
    """A clock we can move forward by hand."""
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


# --------------------------------------------------------------------------- timer

def make_timer(clock):
    return FocusTimer(25 * 60, 5 * 60, 15 * 60, sessions_before_long_break=2, clock=clock)


def test_focus_then_short_break_then_idle():
    clock = FakeClock()
    t = make_timer(clock)
    t.start_focus()
    clock.advance(25 * 60 - 1)
    assert t.tick() is None and t.phase is Phase.FOCUS
    clock.advance(1)
    assert t.tick() == FOCUS_COMPLETE
    assert t.phase is Phase.SHORT_BREAK
    clock.advance(5 * 60)
    assert t.tick() == BREAK_COMPLETE
    assert t.phase is Phase.IDLE          # waits for the user to re-commit


def test_long_break_every_nth_session():
    clock = FakeClock()
    t = make_timer(clock)
    for expected in (Phase.SHORT_BREAK, Phase.LONG_BREAK):
        t.start_focus()
        clock.advance(25 * 60)
        t.tick()
        assert t.phase is expected
        t.skip_break()


def test_pause_freezes_remaining_time():
    clock = FakeClock()
    t = make_timer(clock)
    t.start_focus()
    clock.advance(60)
    t.pause()
    clock.advance(600)                     # ten minutes away from the desk
    assert t.remaining() == pytest.approx(24 * 60)
    t.resume()
    clock.advance(60)
    assert t.elapsed() == pytest.approx(120)


def test_stop_returns_focused_seconds():
    clock = FakeClock()
    t = make_timer(clock)
    t.start_focus()
    clock.advance(300)
    assert t.stop() == pytest.approx(300)
    assert t.phase is Phase.IDLE


def test_cannot_start_twice():
    t = make_timer(FakeClock())
    t.start_focus()
    with pytest.raises(RuntimeError):
        t.start_focus()


def test_format_seconds():
    assert format_seconds(1500) == "25:00"
    assert format_seconds(0.2) == "00:01"  # rounds up, never shows 00:00 early
    assert format_seconds(0) == "00:00"


# --------------------------------------------------------------------------- guard

def test_normalise_names():
    assert normalise("Discord.exe") == "discord"
    assert normalise("Spotify.app") == "spotify"


def test_guard_warn_mode_detects_and_clears():
    procs = [(10, "python"), (11, "Discord.exe"), (12, "DiscordPTB")]
    g = DistractionGuard(["discord"], mode="warn", process_source=lambda: procs)
    first = g.scan()
    assert [a.kind for a in first] == ["new"]
    assert g.active["discord"].pids == [11, 12]
    assert [a.kind for a in g.scan()] == ["ongoing"]
    procs.clear()
    assert [a.kind for a in g.scan()] == ["cleared"]


def test_guard_close_mode_waits_for_grace_period():
    clock = FakeClock()
    killed = []
    g = DistractionGuard(["steam"], mode="close", grace_seconds=20, clock=clock,
                         process_source=lambda: [(5, "steam")], terminator=killed.extend)
    assert g.scan()[0].seconds_left == 20
    clock.advance(10)
    assert g.scan()[0].seconds_left == pytest.approx(10)
    assert killed == []
    clock.advance(10)
    assert g.scan()[0].kind == "closed"
    assert killed == [5]


def test_guard_off_does_nothing():
    g = DistractionGuard(["steam"], mode="off", process_source=lambda: [(5, "steam")])
    assert g.scan() == []


def test_guard_real_psutil_scan_runs():
    """Smoke test against the real process list: must not crash, must not match itself."""
    if not DistractionGuard.available():
        pytest.skip("psutil not installed")
    g = DistractionGuard(["python"], mode="warn")
    g.scan()                                # our own python process is excluded by pid


# --------------------------------------------------------------------------- site blocker

def test_hosts_block_and_unblock_leave_file_unchanged(tmp_path):
    hosts = tmp_path / "hosts"
    original = "127.0.0.1 localhost\n# a user comment\n"
    hosts.write_text(original)
    b = HostsBlocker(hosts)
    ok, _ = b.block(["youtube.com"])
    assert ok and b.is_blocking()
    text = hosts.read_text()
    assert "127.0.0.1 www.youtube.com" in text and "::1 youtube.com" in text
    b.block(["reddit.com"])                 # blocking twice replaces, never duplicates
    assert hosts.read_text().count(START_MARK) == 1
    b.unblock()
    assert hosts.read_text() == original


def test_hosts_without_permission_reports_problem(tmp_path):
    b = HostsBlocker(tmp_path / "missing_hosts")
    ok, message = b.block(["youtube.com"])
    assert not ok and "administrator" in message


# --------------------------------------------------------------------------- notifier

class FakeBackend:
    def __init__(self):
        self.calls = []

    def notify(self, **kwargs):
        self.calls.append(kwargs)


def test_notifier_only_allows_phase_boundaries():
    n = Notifier(backend=FakeBackend())
    with pytest.raises(ValueError):
        n.notify("distraction_detected")    # mid-session pop-ups are forbidden by design


def test_notifier_formats_message_and_respects_setting():
    backend = FakeBackend()
    n = Notifier(backend=backend)
    assert n.notify("focus_complete", task="Essay intro", minutes=5)
    assert "Essay intro" in backend.calls[0]["message"]
    n.enabled = False
    assert not n.notify("break_complete")
    assert len(backend.calls) == 1


def test_notifier_falls_back_when_backend_fails():
    class Broken:
        def notify(self, **_):
            raise NotImplementedError
    beeps = []
    n = Notifier(backend=Broken(), fallback=lambda: beeps.append(1))
    assert not n.notify("break_complete")
    assert beeps == [1]


# --------------------------------------------------------------------------- history

def record(day, minutes=25, completed=True, apps=(), first_after=600):
    start = datetime.combine(day, datetime.min.time()).replace(hour=9)
    return SessionRecord(start.isoformat(), start.isoformat(), "task", 1500, minutes * 60,
                         completed, [{"app": a, "after_sec": first_after, "closed": False} for a in apps])


def test_history_round_trip_and_bad_lines(tmp_path):
    log = SessionLog(tmp_path / "h.jsonl")
    log.append(record(date(2026, 10, 26)))
    with log.path.open("a") as fh:
        fh.write("not json\n")
    assert len(log.load()) == 1


def test_streak_and_summary(tmp_path):
    today = date(2026, 10, 26)
    log = SessionLog(tmp_path / "h.jsonl")
    for back in (1, 2, 3):                  # three days in a row, ending yesterday
        log.append(record(today - timedelta(days=back), apps=["discord"]))
    log.append(record(today - timedelta(days=5)))   # older, after a gap
    log.append(record(today, minutes=10, completed=False, apps=["steam", "discord"], first_after=300))
    assert log.streak(today) == 3           # unfinished session today doesn't count
    s = log.summary(today)
    assert s["today_minutes"] == 10 and s["today_sessions"] == 0
    assert s["top_distraction"] == "discord"
    assert s["completion_rate"] == 80
    assert s["average_minutes_to_first_distraction"] == pytest.approx(8.8)   # (600*3 + 300) / 4 s = 8.75 min


def test_daily_totals_fill_empty_days(tmp_path):
    today = date(2026, 10, 26)
    log = SessionLog(tmp_path / "h.jsonl")
    log.append(record(today, apps=["qq"]))
    totals = log.daily_totals(7, today)
    assert len(totals) == 7 and totals[-1] == (today, 25.0, 1) and totals[0][1] == 0


# --------------------------------------------------------------------------- config

def test_settings_validation_and_round_trip(tmp_path):
    s = Settings(focus_minutes=0, guard_mode="nuclear",
                 blocked_sites=["https://www.YouTube.com/watch?v=1", "bad site", "x.com"])
    s.validate()
    assert s.focus_minutes == 1 and s.guard_mode == "warn"
    assert s.blocked_sites == ["youtube.com", "x.com"]
    path = tmp_path / "settings.json"
    save_settings(s, path)
    raw = json.loads(path.read_text())
    raw["unknown_future_option"] = True     # old app versions must ignore new keys
    path.write_text(json.dumps(raw))
    assert load_settings(path).blocked_sites == ["youtube.com", "x.com"]


def test_domain_cleaning_rejects_injection():
    assert _clean_domain("evil.com\n0.0.0.0 bank.com") == ""
    assert _clean_domain("Bilibili.com:443/video") == "bilibili.com"
