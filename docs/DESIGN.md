# Design notes

This document answers three questions raised in the A1 pitch feedback:
what each feature is *for*, when notifications are allowed, and what happens when a
distracting app is detected. It also lists the reference projects used as guides.

## 1. Each feature targets one stage of a distraction

A distraction is not one moment; it has stages. Each feature is placed at one of them.

| Stage | What goes wrong | Feature | Module |
|---|---|---|---|
| **Before** the session | Vague intention ("study") is easy to drift from | **Task commitment** – Start is disabled until you type one concrete task | `gui.py` |
| **Before** temptation | Distracting sites are one click away | **Website blocking** for the length of the session (hosts file) | `site_blocker.py` |
| **During** – keeping going | No end in sight, so stopping feels reasonable | **Deadline timer** with a visible countdown and cycle dots | `timer.py` |
| **During** – the slip | You open Discord "for a second" | **App guard**: detect → in-app warning + task reminder → (optional) close after a grace period | `guard.py` |
| **After** the session | No feedback, so nothing is learned | **One-click reflection** ("Got it done / Partly / Not really") | `gui.py` |
| **Over time** | Patterns stay invisible | **History**: streak, completion rate, top distraction, *when* in a session you usually get distracted, 7-day chart | `history.py`, `charts.py` |

## 2. Notification policy

The contradiction in the pitch: a focus app that sends pop-ups interrupts focus.

**Rule:** a system notification may only appear at a *phase boundary* — when a focus session
ends, or when a break ends. At those moments the user is supposed to switch attention, so the
notification helps the transition rather than breaking concentration.

- During focus, **nothing** goes to the system tray. Distraction warnings appear only *inside*
  the app window.
- The rule is enforced in code: `Notifier.notify()` raises `ValueError` for any event not in
  `ALLOWED_EVENTS` (tested in `tests/test_core.py::test_notifier_only_allows_phase_boundaries`).
- Notifications can be switched off entirely in Settings; the app then just plays a sound.

**Exception, and why it is consistent:** when the guard detects a *new* distracting app, the
app window is brought to the front for 1.5 seconds. This is not a contradiction — at that moment
the user is already distracted, so interrupting the *distraction* is the intended effect.

## 3. What happens when psutil detects a distracting app

```
scan every 3 s (focus only, not paused, never during breaks)
   │
   ├─ new blocklisted app found ──► log {app, minutes into session}
   │                                 show in-app banner + "You said you'd work on: …"
   │                                 bring window to front briefly
   │
   ├─ still open ──► warn mode : banner stays until it is closed
   │                 close mode: countdown; after grace period (default 20 s) → terminate()
   │
   └─ closed by user ──► banner disappears
```

Three strictness levels (`off` / `warn` / `close`) let the user choose; `close` uses a grace
period so unsaved work is never lost without warning. `terminate()` is a polite quit request,
not a forced kill.

## 4. Why breaks return to idle

After a break the timer does **not** start the next focus session automatically. The user types
the next task first. Auto-starting is convenient but means sessions run without a purpose,
which is how a timer turns into background noise.

## 5. Reference projects (guides, not copied code)

These are closer to Study Focus Buddy than Pomodoro tutorials. They were studied for *ideas and
behaviour*; no code was copied. Where a technique was adopted, the module comment says so.

| Project | What I took from it |
|---|---|
| **SelfControl** (macOS, open source) – https://github.com/SelfControlApp/selfcontrol | Blocking that cannot be casually undone mid-session; hosts-file blocking approach |
| **LeechBlock NG** (browser extension, open source) – https://github.com/proginosko/LeechBlockNG | Block lists + time-limited block periods; the idea of a short delay before access instead of only a hard block (→ grace period) |
| **StevenBlack/hosts** – https://github.com/StevenBlack/hosts | How hosts entries are formatted for both IPv4 (`127.0.0.1`) and IPv6 (`::1`) |
| **Pomatez** (open-source Pomodoro app) – https://github.com/zidoro/pomatez | Phase colours and cycle indicator so the state is readable at a glance |
| **Cold Turkey** (commercial, closed source) – https://getcoldturkey.com | Escalating strictness levels (warn → block) |

Documentation used directly: Python `tkinter`, `time`, `dataclasses` docs; psutil docs
(`process_iter`, `Process.terminate`); plyer API docs; matplotlib "Embed in Tk" example.
