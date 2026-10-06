"""Spawn policy of `agent spawn` / `agent send`: default effort per model, a reason for anything above the default,
and the context size above which a stopped agent is not resumed with a new task. Nothing is built in beyond the
generic fallbacks; every value is a setting read through the config layers (see docs/reference.md):

  AGENT_HUB_EFFORT_DEFAULTS   {"<model>": "<effort>", …}: the effort a spawn gets when --effort is not given. A key is a
                              glob, or a plain word matched anywhere in the model name (the alias given and the id it
                              maps to are both tried; the first matching key wins). Else AGENT_HUB_DEFAULT_EFFORT, else high.
  AGENT_HUB_REASON_MODELS     ["<model>", …]: models that count as above the default; spawning one needs --reason.
  AGENT_HUB_REASON_POLICY     warn (default) | refuse | off: what a spawn above the default without --reason gets.
  AGENT_HUB_RESUME_MAX_CTX    tokens of context (250000, 250k, 1m; 0 = no limit; default 250k) above which `agent send`
                              does not resume a stopped agent with a new task.
"""
from __future__ import annotations

import fnmatch
import re
from typing import Optional

import hubcore as hc

DEFAULT_EFFORT = "high"
DEFAULT_RESUME_MAX_CTX = 250_000
REASON_POLICIES = ("warn", "refuse", "off")
REASON_MAX = 300


def pattern_matches(key: str, names: list) -> bool:
    """A setting key against model names: a glob as is, a plain word anywhere in the name; case-insensitive."""
    pat = key if any(ch in key for ch in "*?[") else f"*{key}*"
    return any(fnmatch.fnmatchcase(n.lower(), pat.lower()) for n in names if n)


def _object(name: str, cwd) -> dict:
    val = hc.setting_json(name, {}, cwd=cwd)
    if not isinstance(val, dict):
        hc.warn(f"{name}: a JSON object {{\"<model>\": \"<effort>\"}} is expected; ignored")
        return {}
    return {str(k): str(v).strip() for k, v in val.items() if not str(k).startswith("_")}


def default_effort(names: list, allowed: tuple, cwd=None) -> str:
    """The effort a spawn of a model (its names: alias given, resolved id) gets without --effort."""
    for key, effort in _object("AGENT_HUB_EFFORT_DEFAULTS", cwd).items():
        if pattern_matches(key, names):
            if effort not in allowed:
                raise hc.UsageError(f"AGENT_HUB_EFFORT_DEFAULTS[{key!r}] = {effort!r}: one of {allowed}")
            return effort
    return hc.setting("AGENT_HUB_DEFAULT_EFFORT", cwd=cwd) or DEFAULT_EFFORT


def clean_reason(reason: Optional[str]) -> str:
    return hc.one_line(reason or "").strip()[:REASON_MAX]


def check_reason(names: list, effort: Optional[str], default: str, allowed: tuple, reason: str, cwd=None) -> Optional[str]:
    """A warning line for a spawn above the default without a reason (None: fine); a UsageError when the policy is
    `refuse`. Above the default: an effort ranked higher than the model's default, or a model of AGENT_HUB_REASON_MODELS."""
    policy = (hc.setting("AGENT_HUB_REASON_POLICY", cwd=cwd) or "warn").strip().lower()
    if policy not in REASON_POLICIES:
        raise hc.UsageError(f"AGENT_HUB_REASON_POLICY {policy!r}: one of {', '.join(REASON_POLICIES)}")
    if policy == "off" or reason:
        return None
    above = []
    if effort and default in allowed and effort in allowed and allowed.index(effort) > allowed.index(default):
        above.append(f"effort {effort} is above the default {default}")
    models = hc.setting_json("AGENT_HUB_REASON_MODELS", [], cwd=cwd)
    models = [models] if isinstance(models, str) else models
    if isinstance(models, list):
        hit = [m for m in models if isinstance(m, str) and pattern_matches(m, names)]
        if hit:
            above.append(f"model {names[0]} is above the default (AGENT_HUB_REASON_MODELS: {hit[0]})")
    if not above:
        return None
    text = (f"{' and '.join(above)}: say why the work needs it with --reason \"…\" (a short sentence; it goes into the "
            "journal and meta.json)")
    if policy == "refuse":
        raise hc.UsageError(text)
    return text + "; spawning anyway"


def resume_max_ctx(cwd=None) -> int:
    """Tokens of context above which a stopped agent is not resumed (0 = no limit)."""
    raw = (hc.setting("AGENT_HUB_RESUME_MAX_CTX", cwd=cwd) or "").strip().lower()
    if not raw:
        return DEFAULT_RESUME_MAX_CTX
    m = re.fullmatch(r"([0-9]+)\s*([km]?)", raw)
    if not m:
        raise hc.UsageError("AGENT_HUB_RESUME_MAX_CTX must be a number of tokens (250000, 250k, 1m; 0 = no limit)")
    return int(m.group(1)) * {"": 1, "k": 1000, "m": 1_000_000}[m.group(2)]


def fmt_tokens(n: int) -> str:
    return f"{n / 1000:.0f}k" if n >= 1000 else str(n)


def resume_refusal(role: str, ctx: int, limit: int) -> str:
    return (f"agent {role} holds {fmt_tokens(ctx)} tokens of context, above AGENT_HUB_RESUME_MAX_CTX "
            f"({fmt_tokens(limit)}): every turn of a resume re-reads all of it. Spawn a fresh agent from a handoff "
            f"file (`agent spawn --brief <handoff>`); to resume this one anyway: `agent send {role} --resume-anyway …`")


def brief_title(role: str, stage: str, brief_text: str, width: int = 90) -> str:
    """`<role> — <the brief's first heading, without a leading "Brief:"> (<stage>)`, trimmed to `width`; without a
    heading, `agent <role> (<stage>)`."""
    heading, fenced = "", False
    for line in brief_text.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        elif not fenced:
            m = re.match(r"#{1,6}\s+(.*?)\s*#*\s*$", line)
            if m and m.group(1).strip():
                heading = m.group(1).strip()
                break
    heading = re.sub(r"^brief\s*:\s*", "", heading, flags=re.IGNORECASE).strip()
    heading = re.sub(r"\s+", " ", re.sub(r"[`*]", "", heading)).strip()
    if not heading:
        return f"agent {role} ({stage})"
    head, tail = f"{role} — ", f" ({stage})"
    room = max(width - len(head) - len(tail), 12)
    if len(heading) > room:
        heading = heading[:room - 1].rstrip() + "…"
    return head + heading + tail
