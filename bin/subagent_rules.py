"""Subagent rules: one rule format for the delegation hook (in-session Agent/Task/Workflow calls) and `agent spawn`
(headless agents). No model or agent name is built in; everything comes from configuration.

A rule list is JSON, evaluated top to bottom; the first rule whose `when` matches decides:

    [{"when": {"subagent_type": "fork"}, "decision": "deny", "reason": "A fork inherits the parent's effort."},
     {"when": {"model": "*haiku*"}, "decision": "allow"},
     {"when": {"effort": ["inherit", "max"]}, "decision": "deny", "reason": "Pin the effort ({subagent_type})."}]

No matching rule = allow. `when` keys (all must match; a value is a glob or a list of globs, case-insensitive):

    tool           Agent | Task | Workflow | agent-spawn
    level          the delegation level "0".."5", or "off" when the dial is off
    subagent_type  the Agent call's subagent_type ("" when not given; plugin agents as "plugin:name")
    defined        "true" when a definition file for subagent_type was found, else "false"
    model          the model the subagent runs on: the call's `model`, else the definition's `model:`, else
                   "inherit"; for agent spawn both the alias given and the id it maps to are tried
    model_from     param | definition | inherit
    effort         the definition's pinned `effort:`, else "inherit"; for agent spawn the effort used ("none" for
                   a model that takes no effort flag)

`reason` may name any of these fields in braces: "{model} at {effort} is not allowed".

AGENT_HUB_EFFORT_RULES may also be the shorthand object {"<model>": "<effort>|<effort>", …}: each model (a glob, or a
plain word matched anywhere in the model name) runs only at the listed efforts. {"sonnet": "high|xhigh"} is

    [{"when": {"model": "*sonnet*", "effort": ["high", "xhigh"]}, "decision": "allow"},
     {"when": {"model": "*sonnet*"}, "decision": "deny", "reason": "…"}]
"""
from __future__ import annotations

import fnmatch
import json
import os
import sys
from pathlib import Path
from typing import Optional

FIELDS = ("tool", "level", "subagent_type", "defined", "model", "model_from", "effort")
DECISIONS = ("allow", "deny")
PLUGIN_ROOT = Path(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))


def plugin_name() -> str:
    try:
        return json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["name"]
    except (OSError, ValueError, KeyError):
        return "agent-hub"


def _warn(msg: str) -> None:
    print(f"agent-hub: {msg}", file=sys.stderr)


# ------------------------------------------------------------------ agent definitions

def _frontmatter(path: Path) -> Optional[dict]:
    """Lower-cased `key: value` pairs of a definition's YAML front matter; {} for a file without one."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.startswith("---"):
        return {}
    fm: dict = {}
    for line in text.split("\n")[1:]:
        if line.strip() == "---":
            break
        k, sep, v = line.partition(":")
        if sep and not k.startswith((" ", "\t")):
            fm[k.strip().lower()] = v.strip().strip("\"'").lower()
    return fm


def _find_in(dirs, name: str) -> Optional[dict]:
    for d in dirs:
        f = d / f"{name}.md"
        fm = _frontmatter(f) if f.is_file() else None
        if fm is not None:
            return fm
    for d in dirs:  # a definition whose `name:` differs from its file name
        try:
            files = sorted(d.glob("*.md"))
        except OSError:
            continue
        for f in files:
            fm = _frontmatter(f)
            if fm and fm.get("name") == name.lower():
                return fm
    return None


def plugin_agent_dirs(plugin: str) -> list:
    """agents/ of an installed plugin: this plugin's own directory, else the newest cached version of another."""
    if plugin == plugin_name():
        return [PLUGIN_ROOT / "agents"]
    base = Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude")) / "plugins" / "cache"
    found = sorted(base.glob(f"*/{plugin}/*/agents"), key=lambda p: p.stat().st_mtime, reverse=True)
    return found[:1]


def agent_definition(name: str, cwd=None) -> Optional[dict]:
    """Front matter of the definition `name` resolves to, or None when none is found.

    "plugin:agent" (or "plugin:ns:agent") looks in that plugin's agents/; a bare name in <cwd>/.claude/agents,
    ~/.claude/agents, then this plugin's agents/ (an unambiguous plugin agent may be called without its prefix)."""
    if not name or "/" in name or name.startswith("."):
        return None
    if ":" in name:
        parts = name.split(":")
        return _find_in(plugin_agent_dirs(parts[0]), parts[-1])
    dirs = []
    if cwd:
        dirs.append(Path(cwd) / ".claude" / "agents")
    dirs.append(Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude")) / "agents")
    dirs.append(PLUGIN_ROOT / "agents")
    return _find_in(dirs, name)


# ------------------------------------------------------------------ calls and rules

def agent_call(tool: str, tool_input: dict, cwd=None, level=None) -> dict:
    """The rule fields of an in-session Agent/Task/Workflow call."""
    typ = str(tool_input.get("subagent_type") or "").strip()
    param = str(tool_input.get("model") or "").strip().lower()
    fm = agent_definition(typ, cwd) if typ else None
    def_model = (fm or {}).get("model", "")
    if param:
        model, source = param, "param"
    elif def_model and def_model != "inherit":
        model, source = def_model, "definition"
    else:
        model, source = "inherit", "inherit"
    return {"tool": tool, "level": "off" if level is None else str(level), "subagent_type": typ,
            "defined": "true" if fm is not None else "false", "model": model, "model_from": source,
            "effort": (fm or {}).get("effort") or "inherit"}


def spawn_call(model_given: str, model_id: str, effort: Optional[str]) -> dict:
    """The rule fields of `agent spawn`."""
    models = [m.lower() for m in dict.fromkeys([model_given, model_id]) if m]
    return {"tool": "agent-spawn", "level": "off", "subagent_type": "", "defined": "false", "model": models,
            "model_from": "param", "effort": (effort or "none").lower()}


def problems(rules) -> list:
    """Why a rule list is malformed (empty list = fine)."""
    if not isinstance(rules, list):
        return ["rules must be a JSON list"]
    out = []
    for i, r in enumerate(rules):
        if not isinstance(r, dict):
            out.append(f"rule {i}: not an object")
            continue
        when = r.get("when", {})
        if not isinstance(when, dict):
            out.append(f"rule {i}: `when` must be an object")
        else:
            for k, v in when.items():
                if k not in FIELDS:
                    out.append(f"rule {i}: unknown field {k!r} (one of {', '.join(FIELDS)})")
                elif not (isinstance(v, (str, int)) or (isinstance(v, list) and all(isinstance(x, (str, int)) for x in v))):
                    out.append(f"rule {i}: {k} must be a glob or a list of globs")
        if r.get("decision") not in DECISIONS:
            out.append(f"rule {i}: decision must be one of {DECISIONS}")
    return out


def _match(value, pattern) -> bool:
    values = value if isinstance(value, list) else [value]
    pats = pattern if isinstance(pattern, list) else [pattern]
    return any(fnmatch.fnmatchcase(str(v).lower(), str(p).lower()) for v in values for p in pats)


class _Fields(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def evaluate(rules, call: dict, label: str = "rules"):
    """(decision, reason, index) of the first matching rule, or None. A malformed list is reported and skipped
    as a whole (fail-open: a typo must not stop every subagent)."""
    if not rules:
        return None
    errs = problems(rules)
    if errs:
        _warn(f"{label} ignored: " + "; ".join(errs))
        return None
    for i, r in enumerate(rules):
        if all(_match(call.get(k, ""), v) for k, v in (r.get("when") or {}).items()):
            shown = {k: ("/".join(v) if isinstance(v, list) else v) or "-" for k, v in call.items()}
            reason = str(r.get("reason") or f"denied by {label} #{i}")
            try:
                reason = reason.format_map(_Fields(shown))
            except (ValueError, IndexError):
                pass
            return r["decision"], reason, i
    return None


def expand(rules):
    """A rule list as is; the shorthand {"<model>": "<effort>|…"} as the equivalent rule list."""
    if not isinstance(rules, dict):
        return rules
    out = []
    for model, efforts in rules.items():
        if str(model).startswith("_"):
            continue
        pat = model if any(ch in model for ch in "*?[") else f"*{model}*"
        allowed = [e.strip() for e in str(efforts).split("|") if e.strip()]
        out.append({"when": {"model": pat, "effort": allowed}, "decision": "allow"})
        out.append({"when": {"model": pat}, "decision": "deny",
                    "reason": f"{model} runs only at effort {' or '.join(allowed)} (got {{effort}}, type "
                              f"{{subagent_type}})."})
    return out


def effort_rules(cwd=None) -> list:
    """AGENT_HUB_EFFORT_RULES from the environment, the repository at `cwd`, or the hub home."""
    sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
    import hubcore  # noqa: E402

    return expand(hubcore.setting_json("AGENT_HUB_EFFORT_RULES", [], cwd=cwd)) or []


def deny_reason(res, label: str) -> Optional[str]:
    """The reason of a deny result of evaluate(), with the rule named; None for allow / no match."""
    if not res or res[0] != "deny":
        return None
    return f"{res[1]} [{label} rule {res[2]}]"


def check_spawn(model_given: str, model_id: str, effort: Optional[str], cwd=None) -> Optional[str]:
    """The deny reason AGENT_HUB_EFFORT_RULES gives an `agent spawn`, or None."""
    label = "AGENT_HUB_EFFORT_RULES"
    return deny_reason(evaluate(effort_rules(cwd), spawn_call(model_given, model_id, effort), label), label)
