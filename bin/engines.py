"""Engine boundaries: validated launch policy and raw-event normalization.

Keep provider events in log.jsonl. Consumers use normalize_event without relying
on one provider's output format. Missing engine metadata always means Claude.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

import hubcore as hc

ENGINES = ("claude", "codex")
CODEX_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")
SANDBOXES = ("read-only", "workspace-write", "danger-full-access")


def selected(given=None, cwd=None):
    name = given or hc.setting("AGENT_HUB_ENGINE", cwd=cwd) or ("codex" if os.environ.get("CODEX_THREAD_ID") else "claude")
    if name not in ENGINES:
        raise hc.UsageError(f"engine {name!r}: one of {', '.join(ENGINES)}")
    return name


def codex_bin(cwd=None):
    value = hc.setting("CODEX_BIN", cwd=cwd) or "codex"
    found = shutil.which(value)
    if not found:
        raise hc.Failure("codex not found on PATH (set CODEX_BIN)")
    return found


def model_map(cwd=None):
    raw = hc.setting("AGENT_HUB_CODEX_MODEL_MAP", cwd=cwd)
    if not raw:
        return {}
    try:
        data = json.loads(raw) if raw.strip().startswith("{") else dict(s.strip().split("=", 1) for s in raw.split(","))
        if not isinstance(data, dict) or any(not isinstance(k, str) or not hc.MODEL_ALIAS_RE.fullmatch(k)
                                           or not isinstance(v, str) or not hc.MODEL_VALUE_RE.fullmatch(v)
                                           for k, v in data.items()):
            raise ValueError
    except (ValueError, TypeError):
        raise hc.UsageError("AGENT_HUB_CODEX_MODEL_MAP must map safe aliases to model IDs") from None
    return data


def model_problem(model, cwd=None):
    if not isinstance(model, str) or not hc.MODEL_VALUE_RE.fullmatch(model):
        return "a model ID or configured alias (letters, digits and . _ : @ [ ] / - only)"
    if model in hc.MODEL_ALIASES and model not in model_map(cwd):
        return f"{model!r} is a Claude alias; configure AGENT_HUB_CODEX_MODEL_MAP or pass a Codex model ID"
    return None


def permission_policy(mode=None, sandbox=None, cwd=None):
    """No interactive approval in a detached worker; preserve sandbox on resume."""
    if sandbox is not None:
        if sandbox not in SANDBOXES:
            raise hc.UsageError(f"sandbox {sandbox!r}: one of {', '.join(SANDBOXES)}")
        if mode is not None:
            raise hc.UsageError("choose --sandbox or --permission-mode for Codex, not both")
        return sandbox
    mode = mode or hc.setting("AGENT_HUB_CODEX_PERMISSION_MODE", cwd=cwd) or hc.setting("AGENT_HUB_PERMISSION_MODE", cwd=cwd) or "bypassPermissions"
    mapping = {"bypassPermissions": "danger-full-access", "full-access": "danger-full-access",
               "dontAsk": "workspace-write", "acceptEdits": "workspace-write", "plan": "read-only",
               **{s: s for s in SANDBOXES}}
    if mode not in mapping:
        raise hc.UsageError(f"Codex permission mode {mode!r}: use bypassPermissions or an explicit sandbox; "
                            "interactive Claude modes are not supported for detached Codex runs")
    return mapping[mode]


def toml_value(value):
    """A CLI config override is TOML, not JSON; quote keys as well as values."""
    if isinstance(value, dict):
        return "{ " + ", ".join(json.dumps(str(k)) + " = " + toml_value(v) for k, v in value.items()) + " }"
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(v) for v in value) + "]"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    raise hc.Failure(f"unsupported bundled hook configuration value: {type(value).__name__}")


def hook_args(cwd=None):
    path = hc.BIN.parent / "hooks" / "codex-hooks.json"
    try:
        hooks = json.loads(path.read_text(encoding="utf-8"))["hooks"]
        if not isinstance(hooks, dict):
            raise ValueError
    except (OSError, ValueError, KeyError) as e:
        raise hc.Failure(f"cannot load bundled Codex guards: {e}") from None
    trust = hc.setting("AGENT_HUB_CODEX_HOOK_TRUST", cwd=cwd) or "bypass"
    if trust not in ("bypass", "reviewed"):
        raise hc.UsageError("AGENT_HUB_CODEX_HOOK_TRUST must be bypass or reviewed")
    args = ["--enable", "hooks"]
    for event, groups in hooks.items():
        args += ["-c", f"hooks.{event}={toml_value(groups)}"]
    if trust == "bypass":
        args.append("--dangerously-bypass-hook-trust")
    return args


def codex_argv(meta, prompt, resume=False):
    args = [codex_bin(meta["cwd"]), "exec"]
    if resume:
        args += ["resume", meta["session_id"]]
    args += ["--json", "--skip-git-repo-check"]
    if meta.get("model"):
        args += ["-m", meta["model"]]
    if meta.get("effort"):
        args += ["-c", "model_reasoning_effort=" + json.dumps(meta["effort"])]
    sandbox = meta["sandbox"]
    if sandbox == "danger-full-access":
        args += ["--dangerously-bypass-approvals-and-sandbox"]
    else:
        # exec resume has no --sandbox/--add-dir flags; overrides work on both paths.
        args += ["-c", "sandbox_mode=" + json.dumps(sandbox), "-c", 'approval_policy="never"']
        if sandbox == "workspace-write":
            args += ["-c", "sandbox_workspace_write.writable_roots=" + toml_value([str(hc.root())])]
    args += hook_args(meta["cwd"])
    return args + [prompt]


def normalize_event(ev):
    """Return zero or more common events; Codex usage is explicitly cumulative."""
    if not isinstance(ev, dict):
        return []
    kind = ev.get("type", "")
    if kind == "thread.started":
        return [{"type": "system", "subtype": "init", "session_id": ev.get("thread_id"), "_engine": "codex"}]
    if kind == "turn.started":
        return [{"type": "system", "subtype": "turn_start", "_engine": "codex"}]
    if kind in ("turn.completed", "turn.failed"):
        failed = kind != "turn.completed"
        return [{"type": "result", "subtype": "error" if failed else "success", "is_error": failed,
                 "errors": [ev.get("error") or ev.get("message")] if failed else [],
                 "codex_usage": ev.get("usage"), "_engine": "codex"}]
    if kind in ("item.started", "item.updated", "item.completed"):
        item = ev.get("item") or {}
        itype = item.get("type")
        blocks = []
        if itype in ("agent_message", "reasoning") and kind == "item.completed":
            blocks = [{"type": "text" if itype == "agent_message" else "thinking",
                       "text" if itype == "agent_message" else "thinking": item.get("text", "")}]
        elif itype == "command_execution":
            if kind == "item.started":
                blocks = [{"type": "tool_use", "id": item.get("id"), "name": "Bash",
                           "input": {"command": item.get("command", "")}}]
            elif kind == "item.completed":
                return [{"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": item.get("id"),
                         "content": item.get("aggregated_output", ""), "is_error": item.get("exit_code", 0) != 0}]},
                         "_engine": "codex"}]
        elif itype in ("file_change", "mcp_tool_call", "web_search"):
            if kind == "item.started":
                blocks = [{"type": "tool_use", "id": item.get("id"), "name": itype, "input": item}]
            elif kind == "item.completed":
                return [{"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": item.get("id"),
                         "content": json.dumps(item, ensure_ascii=False), "is_error": item.get("status") == "failed"}]},
                         "_engine": "codex"}]
        if blocks:
            return [{"type": "assistant", "message": {"id": item.get("id"), "content": blocks}, "_engine": "codex"}]
        return []
    return [ev]
