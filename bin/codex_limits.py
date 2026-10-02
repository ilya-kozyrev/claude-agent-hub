"""Bounded, read-only account-limit snapshots from recent local Codex rollouts.

These are logged observations, not live API queries. Account limits do not
depend on the monitor's stage filter. Missing windows remain unknown.
"""
import json
import math
import time

import codex_rollouts

TAIL_BYTES = 256_000
RECENT_FILES = 32


def number(value):
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def windows(info):
    """Known usage percentages with actual window labels; never assume 5h/7d."""
    out = []
    for key in ("primary", "secondary"):
        w = info.get(key) if isinstance(info, dict) else None
        if not isinstance(w, dict) or not number(w.get("used_percent")) or w["used_percent"] < 0:
            continue
        minutes = w.get("window_minutes")
        label = key
        if number(minutes) and minutes > 0:
            if minutes % 1440 == 0:
                label = f"{minutes / 1440:g}d"
            elif minutes % 60 == 0:
                label = f"{minutes / 60:g}h"
            else:
                label = f"{minutes:g}m"
        out.append({"label": label, "used_percent": w["used_percent"],
                    "resets_at": w.get("resets_at") if number(w.get("resets_at")) else None})
    return out


class Reader:
    def __init__(self):
        self.checked, self.limits = None, {}

    def snapshot(self):
        now = time.monotonic()
        if self.checked is not None and now - self.checked < codex_rollouts.TTL:
            return self.limits
        limits = {}
        records = sorted(codex_rollouts.INDEX.update().records.values(), key=lambda r: r[2], reverse=True)
        for path, _, _ in records[:RECENT_FILES]:
            try:
                with path.open("rb") as f:
                    size = f.seek(0, 2)
                    f.seek(max(0, size - TAIL_BYTES))
                    if size > TAIL_BYTES:
                        f.readline()
                    lines = f.read(TAIL_BYTES).splitlines(keepends=True)
                for line in reversed(lines):
                    if not line.endswith(b"\n") or b'"rate_limits"' not in line:
                        continue
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(ev, dict):
                        continue
                    payload = ev.get("payload")
                    if ev.get("type") != "event_msg" or not isinstance(payload, dict) or payload.get("type") != "token_count":
                        continue
                    info, seen = payload.get("rate_limits"), codex_rollouts.epoch(ev.get("timestamp"))
                    if seen is None or not windows(info):
                        continue
                    lid = info.get("limit_id") or "codex"
                    if not isinstance(lid, str):
                        continue
                    if lid not in limits or seen > limits[lid]["seen_at"]:
                        limits[lid] = {"info": info, "seen_at": seen, "source": str(path)}
            except (OSError, ValueError, AttributeError, TypeError):
                continue
        self.checked, self.limits = now, limits
        return limits
