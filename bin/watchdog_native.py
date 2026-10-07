"""Local candidate/attempt protocol for a supported app-native watchdog consumer.

This module never asserts runtime idle, calls an app API, or uses a CLI transport.
The app consumer must establish idle and actionable work with native read_thread.
"""
from __future__ import annotations

import hashlib
import json
import os
from uuid import UUID, uuid4

import autopilot
import codex_rollouts
import engines
import hubcore as hc
import watchdog_codex as wc


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def consumer():
    sid = os.environ.get("CODEX_THREAD_ID", "").strip()
    try:
        valid = str(UUID(sid)) == sid.lower()
    except ValueError:
        valid = False
    if not valid or not engines.codex_desktop():
        raise hc.Failure("native attempts require the current confirmed Codex app consumer")
    return sid


def recipient_activity(path, sid, since, now):
    """Only a new own turn proves recipient progress; work/registration/file touches do not."""
    if path is None or since is None:
        return False
    try:
        with path.open("rb") as f:
            head = json.loads(f.readline(256_001))
            birth = codex_rollouts.epoch(head.get("timestamp"))
            if head.get("payload", {}).get("id") != sid or birth is None:
                return False
            f.seek(0, 2); offset = max(0, f.tell() - 512_000); f.seek(offset)
            if offset:
                f.readline()
            data = f.read()
        if not data.endswith(b"\n"):
            return False
        for line in data.splitlines():
            ev = json.loads(line); payload = ev.get("payload")
            if ev.get("type") != "event_msg" or not isinstance(payload, dict) or payload.get("type") != "task_started":
                continue
            at = codex_rollouts.epoch(ev.get("timestamp")); started = payload.get("started_at")
            if (type(started) is int and at is not None and isinstance(payload.get("turn_id"), str) and payload["turn_id"]
                    and started >= max(int(birth), int(since.timestamp()))
                    and since.timestamp() < at <= now.timestamp() and started <= at):
                return True
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return False


def candidate(wd, tick, stage):
    rec = hc.roles_load(stage)["roles"].get("hub") or {}
    sid = wc._session(rec)
    if (not sid or rec.get("engine") != "codex" or rec.get("host") != "codex-app"
            or rec.get("kind") == "desktop" or str(rec.get("session", "")).startswith("local_")
            or hc.detached(stage, rec, engine="codex")):
        return None, "no active confirmed native app hub"
    why = wc.wake_guard(stage, rec, tick.now)
    if why:
        return None, why
    if wd.live_waiter(tick, stage, rec):
        return None, "the hub has a live waiter"
    lines, night = wd.waiting_lines(tick, stage, rec), wd.night_work(tick, stage)
    rollout = codex_rollouts.INDEX.session(sid)
    last = wd.mtime_of(rollout[0]) if rollout else wd.parse_ts(rec.get("set_at"))
    error = wc.retryable_turn(rollout[0], sid, tick.now) if rollout and wd.flag("AGENT_HUB_WATCHDOG_API_ERROR") else None
    dead = (error["at"], error["error"]) if error and tick.now - error["at"] >= tick.wake_after else None
    if not (lines or night or dead):
        return None, "no aged unconsumed work or eligible final error"
    if last is None or tick.now - last < tick.wake_after:
        return None, "recent or unknown local activity; no silent-hub candidate"
    failure = {**error, "at": wd.iso(error["at"])} if dead else None
    work = {"lines": [key for _, key, _ in lines], "night": night[1] if night else None, "failed_turn": failure}
    work_id = fingerprint(work)
    # One app thread may be registered in more than one stage. Serialize all
    # native claims by UUID, not merely by stage, including lost API replies.
    for other_stage, saved_state in tick.state["stages"].items():
        other = saved_state.get("native_episode")
        if not isinstance(other, dict) or str(other.get("session", "")).lower() != sid.lower():
            continue
        acted = wd.parse_ts(other.get("acted_at"))
        progressed = recipient_activity(rollout[0] if rollout else None, sid, acted, tick.now)
        if other.get("result") == "unknown" and not progressed:
            return None, "the UUID has unknown delivery with no verified recipient turn progress"
        if other_stage == stage or progressed:
            continue
        nxt = wd.parse_ts(other.get("next_try_at"))
        if other.get("result") != "completed-skip" and nxt and tick.now < nxt:
            return None, "the same UUID has an unresolved/cooling native attempt in another stage"
    identity = fingerprint(rec)
    stage_state = tick.state["stages"].get(stage, {})
    core = stage_state.get("hub") or {}
    core_ep = core.get("episode") or {}
    if core.get("session") == rec.get("session") and core_ep.get("result") != "notified":
        core_next = wd.parse_ts(core_ep.get("next_try_at"))
        if core_next and tick.now < core_next:
            return None, "standalone delivery attempt cooldown; notification-only cooldown is ignored"
    saved = stage_state.get("native_episode")
    ep = saved if isinstance(saved, dict) and saved.get("registry_fingerprint") == identity else {}
    if ep.get("result") == "completed-skip" and ep.get("work_fingerprint") == work_id:
        return None, "same fingerprint was confirmed complete; no stale-work retry"
    if ep.get("result") == "completed-skip":
        ep = {}  # a new work fingerprint re-arms, without closing the whole stage
    acted = wd.parse_ts(ep.get("acted_at"))
    recovered = recipient_activity(rollout[0] if rollout else None, sid, acted, tick.now) and not (error and error["at"] > acted)
    nxt = wd.parse_ts(ep.get("next_try_at"))
    if nxt and tick.now < nxt and not recovered:
        return None, "native attempt cooldown (including unknown delivery)"
    out = {"stage": stage, "session": sid, "registry_fingerprint": identity,
           "work_fingerprint": work_id, "fingerprint": fingerprint([identity, work_id]), "reason": "R4" if dead else "R3",
           "count": len(lines), "waiting_since": wd.iso(lines[0][0]) if lines else None,
           "night_open": night[1].get("open", 0) if night else 0, "failed_turn": failure,
           "last_local_activity": wd.iso(last), "requires_native_idle_check": True,
           "requires_latest_turn_actionability_check": True,
           "message": wd.wake_text(stage, {}, lines, dead, night, False)}
    return (out, rec, {} if recovered else ep), ""


def plan(wd, only=None):
    tick = wd.Tick(True, True)  # read-only waiter check: never reaps armed files
    candidates, skipped = [], []
    if wd.enabled():
        for stage in wd.stage_names(only):
            try:
                result, why = candidate(wd, tick, stage)
            except (OSError, ValueError, TypeError, AttributeError, KeyError, hc.Failure) as exc:
                result, why = None, f"candidate unavailable: {type(exc).__name__}"
            if result:
                candidates.append(result[0])
            else:
                skipped.append({"stage": stage, "reason": why})
    unique, seen = [], set()
    for value in sorted(candidates, key=lambda c: (c["reason"] != "R4", c["waiting_since"] or c["last_local_activity"], c["stage"])):
        if value["session"].lower() in seen:
            skipped.append({"stage": value["stage"], "reason": "same UUID already has a candidate"})
        else:
            unique.append(value)
            seen.add(value["session"].lower())
    return {"version": 1, "at": wd.iso(tick.now), "enabled": wd.enabled(),
            "candidates": unique, "skipped": skipped}


def claim(wd, a):
    caller = consumer()
    with wd.TickLock() as lock:
        if not lock.held:
            raise hc.Failure("another watchdog tick/attempt is running")
        with autopilot.state_lock(a.stage), hc.roles_lock(a.stage):
            tick = wd.Tick(True, True)
            if not wd.enabled():
                raise hc.Failure("watchdog is off")
            codex_rollouts.INDEX.checked = None
            result, why = candidate(wd, tick, a.stage)
            if not result:
                raise hc.Failure(why)
            out, rec, ep = result
            if out["session"] != a.session or out["fingerprint"] != a.fingerprint:
                raise hc.Failure("registry or pending work changed since native-plan")
            attempts = int(ep.get("attempts", 0)) + 1
            delay = min(tick.wake_after * (2 ** min(attempts - 1, 16)), tick.backoff_max)
            token = uuid4().hex
            episode = {"registry_fingerprint": out["registry_fingerprint"], "work_fingerprint": out["work_fingerprint"],
                       "fingerprint": out["fingerprint"],
                       "session": out["session"], "attempts": attempts, "acted_at": wd.iso(tick.now),
                       "next_try_at": wd.iso(tick.now + delay), "result": "unknown",
                       "attempt": token, "consumer": caller}
            tick.state["stages"].setdefault(a.stage, {})["native_episode"] = episode
            wd.save_state(tick.state)  # before the native API: a lost reply cannot immediately send twice
            return {**public(out), "attempt": token, "outcome": "unknown", "next_try_at": episode["next_try_at"],
                    "failed_turn": out["failed_turn"]}


def ack(wd, a):
    caller = consumer()
    with wd.TickLock() as lock:
        if not lock.held:
            raise hc.Failure("another watchdog tick/attempt is running")
        with autopilot.state_lock(a.stage), hc.roles_lock(a.stage):
            state = wd.load_state()
            rec = hc.roles_load(a.stage)["roles"].get("hub")
            ep = state["stages"].get(a.stage, {}).get("native_episode")
            if (not rec or wc._session(rec) != a.session or not isinstance(ep, dict)
                    or fingerprint(rec) != ep.get("registry_fingerprint") or ep.get("fingerprint") != a.fingerprint
                    or ep.get("attempt") != a.attempt or ep.get("consumer") != caller):
                raise hc.Failure("native ack rejected: retired/replaced registry or stale/foreign attempt")
            why = wc.wake_guard(a.stage, rec, wd.clock())
            if why:
                raise hc.Failure(f"native ack rejected: {why}")
            if ep.get("acknowledged_at"):
                if ep.get("result") != a.outcome:
                    raise hc.Failure("native attempt already acknowledged with a different outcome")
                return {"stage": a.stage, "session": a.session, "outcome": a.outcome, "already_acknowledged": True}
            ep.update(result=a.outcome, acknowledged_at=wd.iso(wd.clock()))
            wd.save_state(state)
            return {"stage": a.stage, "session": a.session, "outcome": a.outcome,
                    "next_try_at": ep["next_try_at"]}


def public(value):
    return {k: value[k] for k in ("stage", "session", "fingerprint", "reason", "waiting_since", "count", "message")}


def command(wd, a):
    if a.cmd == "native-plan":
        result = [public(x) for x in plan(wd, a.stage)["candidates"]]
    else:
        a.stage = hc.check_stage(a.stage)
        result = claim(wd, a) if a.cmd == "native-claim" else ack(wd, a)
    print(json.dumps(result, ensure_ascii=False))
    return 0
