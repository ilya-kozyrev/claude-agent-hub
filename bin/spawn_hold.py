"""The machine-load spawn hold (R5): `bin/watchdog run` writes <state_dir>/spawn-hold.json while the machine is busy,
`agent spawn` reads it. Off unless AGENT_HUB_SPAWN_HOLD_LOAD is set; every value is a setting (docs/reference.md):

  AGENT_HUB_SPAWN_HOLD_LOAD   1-minute load average per core above which the tick holds spawns (1.5, 0.75); empty = off.
                              The hold ends when the load falls below 80 % of it. An invalid value counts as unset.
  AGENT_HUB_SPAWN_HOLD        warn (default) | refuse: what `agent spawn` does while the hold is on; `--ignore-hold`
                              passes. An invalid value counts as warn. Resumes (`agent send`) are never held.

The file is {since, load, cores, threshold, until}; a reader ignores it once `until` has passed (the tick refreshes it,
so a stopped job cannot hold spawns for more than two intervals) or when it cannot be read.
Test-only: AGENT_HUB_WATCHDOG_LOAD=<load>[:<cores>] replaces the measured load (and the core count) of one tick.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
from pathlib import Path
from typing import Optional

import hubcore as hc

ACTIONS = ("warn", "refuse")
HYSTERESIS = 0.8  # the hold ends below this share of the threshold


def hold_file() -> Path:
    return hc.state_dir() / "spawn-hold.json"


def threshold() -> Optional[float]:
    """AGENT_HUB_SPAWN_HOLD_LOAD as load per core; None when unset or invalid (with a warning)."""
    raw = (hc.setting("AGENT_HUB_SPAWN_HOLD_LOAD") or "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
        if math.isfinite(value) and value > 0:
            return value
    except ValueError:
        pass
    hc.warn(f"AGENT_HUB_SPAWN_HOLD_LOAD={raw!r} is not a positive number (load per core); the load hold is off")
    return None


def action() -> str:
    raw = (hc.setting("AGENT_HUB_SPAWN_HOLD") or "").strip().lower()
    if raw in ACTIONS:
        return raw
    if raw:
        hc.warn(f"AGENT_HUB_SPAWN_HOLD={raw!r} is not one of {'|'.join(ACTIONS)}; using warn")
    return "warn"


def measure() -> tuple:
    """(1-minute load average, cores) of this machine, or of AGENT_HUB_WATCHDOG_LOAD when that is set."""
    fake = os.environ.get("AGENT_HUB_WATCHDOG_LOAD", "").strip()
    if fake:
        load, _, cores = fake.partition(":")
        return float(load), int(cores) if cores else (os.cpu_count() or 1)
    return os.getloadavg()[0], os.cpu_count() or 1


def read(now: dt.datetime) -> Optional[dict]:
    """The hold record when it is in force at `now`; None when absent, unreadable, malformed or expired."""
    try:
        rec = json.loads(hold_file().read_text(encoding="utf-8"))
        until = dt.datetime.fromisoformat(str(rec["until"]))
        if until.tzinfo is None:
            until = until.replace(tzinfo=hc.TZ)
        float(rec["load"])
        int(rec["cores"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return rec if now < until else None


def describe(rec: dict) -> str:
    cores = int(rec["cores"])
    text = f"machine load {float(rec['load']):.2f} on {cores} cores ({float(rec['load']) / max(cores, 1):.2f} per core)"
    if rec.get("threshold") is not None:
        text += f", above AGENT_HUB_SPAWN_HOLD_LOAD={rec['threshold']}"
    return text


def gate(ignore: bool) -> Optional[str]:
    """What `agent spawn` does about the hold: None (no hold, or --ignore-hold), the warning text, or hc.Failure."""
    if ignore:
        return None
    rec = read(hc.now())
    if rec is None:
        return None
    since = f" since {rec['since']}" if rec.get("since") else ""
    text = f"spawn held: {describe(rec)}{since}"
    if action() == "refuse":
        raise hc.Failure(f"{text}; start it later, or pass --ignore-hold")
    return f"{text}; spawning anyway (AGENT_HUB_SPAWN_HOLD=refuse refuses; --ignore-hold silences this)"
