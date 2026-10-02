"""Autopilot: the hub hands its shift to a successor session by itself (`hub succeed`, hooks/context_budget.py).

At the context budget's warn threshold the hook tells a stage hub to hand over at its next quiet point: `hub handoff`,
fill the TODOs, `hub succeed`. Codex successors are detached `agent spawn --engine codex` sessions.
Claude starts the successor as a background Remote Control session
(`claude --bg --remote-control`), reachable from the phone or claude.ai and from a terminal (`claude attach <id>`);
when that cannot start, as a headless hub (`agent spawn`) the owner talks to through `ask` and `agent send`. Either
starts from the main checkout of the hub's directory in a new worktree of its own (outside git: in the directory).

Settings (the hub home's config.json or the environment only — a cloned repository must not start background
sessions or choose their permission mode):
  AGENT_HUB_AUTO_HANDOFF               off | on (default off)
  AGENT_HUB_AUTO_HANDOFF_CHAIN         automatic handoffs in a row without the owner (default 10; 0 = never)
  AGENT_HUB_SUCCESSOR_ENGINE           inherit the selected engine, or claude | codex
  AGENT_HUB_SUCCESSOR_MODEL            the successor's model (default: the hub's own, from its transcript)
  AGENT_HUB_SUCCESSOR_PERMISSION_MODE  inherit (default: the hub's own mode) or a `claude --permission-mode` value
  AGENT_HUB_SUCCESSOR_TIMEOUT          seconds to wait for the successor's takeover line (default 600)
Chain state: <hub home>/<stage>/auto-handoff.json — `chain` (automatic handoffs since the owner last spoke) and
`pending` (the successor started last). `hub succeed` adds one; a takeover that is not the pending successor's, and a
prompt in the hub's session without the marker "[agent-hub auto-handoff k/N]" (the owner spoke), reset it.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import hubcore as hc  # noqa: E402
import engines  # noqa: E402
import codex_rollouts  # noqa: E402

MARKER_RE = re.compile(r"\[agent-hub auto-handoff (\d+)/(\d+)\]")
LINK_RE = re.compile(r"https?://claude\.ai/code/session_[A-Za-z0-9_-]+|claude\.ai/code/session_[A-Za-z0-9_-]+")
BG_ID_RE = re.compile(r"backgrounded\s*·\s*(\S+)")
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")
# `claude --permission-mode` values; "default" (what a hook's input says for the normal mode) means no flag.
MODES = ("default", "manual", "acceptEdits", "auto", "bypassPermissions", "dontAsk", "plan")
# Environment a child CLI must not inherit: the parent session's identity, and the old hub's journal tag.
# AGENT_SESSION_ID: a headless hub's own id (`agent spawn` sets it); inherited, the successor's `--session self` would
# name the old hub.
STRIP_ENV = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_SSE_PORT",
             "HUB_TAG", "AGENT_ROLE", "AGENT_SESSION_ID", "CODEX_THREAD_ID", "AGENT_HUB_CODEX_MODEL",
             "AGENT_HUB_CODEX_EFFORT")
# The hub's own commands and the hub home, allowed in the successor (`--settings`) unless it runs in bypass mode: a
# background session in the default mode otherwise stops at the permission prompt of its takeover, then at reading the
# handoff outside the project, with nobody there to answer (smoke test, CLI 2.1.285). Everything else still asks — the
# owner answers over Remote Control.
HUB_ALLOW = ("hub takeover", "hub handoff", "hub succeed", "jlog", "jwait", "ask", "roles", "lock list", "agent status")
LINK_WAIT_S = 90
BG_TIMEOUT_S = 60  # one `claude --bg` call
# How long a reservation of `hub succeed` / `--fallback` blocks the shift: login (30 s), up to three `claude --bg` tries
# and `claude agents` (30 s). A phase that starts later (the headless start) refreshes it; a reservation older than
# this belongs to a run that died.
START_BUDGET_S = 240
IN_PROGRESS = ("starting", "falling-back")


def tool(name: str) -> str:
    """A plugin tool as the commands this module writes call it: by the absolute path of this bin/, so a same-named
    command earlier on PATH (GitHub CLI `hub`) cannot answer instead, and with no shell expansion ($HUB_BIN), which an
    allow rule would not match."""
    return shlex.quote(str(hc.BIN / name))
TAIL_CHARS = 600


# ---------------------------------------------------------------- settings

def enabled() -> bool:
    return hc.truthy(hc.setting("AGENT_HUB_AUTO_HANDOFF"))


def chain_limit() -> int:
    return hc.int_setting("AGENT_HUB_AUTO_HANDOFF_CHAIN", 10, minimum=0)


def takeover_timeout() -> int:
    return hc.int_setting("AGENT_HUB_SUCCESSOR_TIMEOUT", 600)


def configured_model() -> Optional[str]:
    return (hc.setting("AGENT_HUB_SUCCESSOR_MODEL") or "").strip() or None


def configured_mode() -> Optional[str]:
    """The successor's permission mode from the setting; None = inherit the hub's own."""
    raw = (hc.setting("AGENT_HUB_SUCCESSOR_PERMISSION_MODE") or "inherit").strip()
    return None if raw == "inherit" else raw


# ---------------------------------------------------------------- chain state

def state_path(stage: str) -> Path:
    return hc.root() / hc.check_stage(stage) / "auto-handoff.json"


def load_state(stage: str) -> dict:
    try:
        data = json.loads(state_path(stage).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError
    except (OSError, ValueError):
        data = {}
    data.setdefault("chain", 0)
    data.setdefault("pending", None)
    return data


def save_state(stage: str, data: dict) -> None:
    hc.atomic_write(state_path(stage), json.dumps(data, ensure_ascii=False, indent=1) + "\n")


def state_lock(stage: str) -> hc.Flock:
    return hc.Flock(hc.root() / hc.check_stage(stage) / ".auto-handoff.lock")


def reset_chain(stage: str, why: str) -> bool:
    """Chain back to 0 (the owner is here), and a pending successor that has not taken over within the takeover
    timeout is dropped, so the shift is not blocked by a dead one (its session is not stopped: the owner decides).
    A successor still in its window, or a `hub succeed` still running, is kept. True when anything changed; then it is
    journaled."""
    with state_lock(stage):
        data = load_state(stage)
        pend = data.get("pending") or {}
        stale = (pend and not pend.get("taken_over") and pend.get("kind") not in IN_PROGRESS
                 and _age(pend) >= takeover_timeout())
        if not data["chain"] and not stale:
            return False
        was = data["chain"]
        data["chain"] = 0
        if stale:
            data["pending"] = None
        save_state(stage, data)
    dropped = (f"; dropped the pending hub-{pend.get('n')} ({pend.get('kind')} {pend.get('id') or pend.get('role')}), "
               "which did not take over in time — its session is not stopped" if stale else "")
    hc.journal_append(stage, "hub", f"auto-handoff chain reset ({was} → 0): {why}{dropped}")
    return True


def on_takeover(stage: str, n: int, auto: bool = False) -> None:
    """Called by `hub takeover` once it is done: the pending automatic successor (its takeover carries
    --auto-handoff, which only `hub succeed` writes) keeps the chain; any other takeover resets it — a takeover by
    hand means the owner is involved, even when it gets the same number."""
    with state_lock(stage):
        data = load_state(stage)
        pend = data.get("pending") or {}
        if auto and pend.get("n") == n:
            if not pend.get("taken_over"):
                pend["taken_over"] = hc.now().isoformat(timespec="seconds")
                save_state(stage, data)
            return
        if not data["chain"] and not pend:
            return
        was = data["chain"]
        data["chain"], data["pending"] = 0, None
        save_state(stage, data)
    if was:
        hc.journal_append(stage, f"hub-{n}", f"auto-handoff chain reset ({was} → 0): a takeover by hand")


def pending_number(stage: str, handoff) -> Optional[int]:
    """The number `hub succeed` gave the successor it started from `handoff` (the pending record), for that
    successor's `hub takeover --auto-handoff`: the name it was started under, its journal tag and the chain agree
    whatever the registry says by then. None when no pending record names that handoff."""
    pend = load_state(stage).get("pending") or {}
    if handoff is None or not isinstance(pend.get("n"), int) or not pend.get("handoff"):
        return None
    try:
        return pend["n"] if Path(pend["handoff"]).resolve() == Path(handoff).expanduser().resolve() else None
    except (OSError, ValueError):
        return None


def hub_stage_of(sid: str) -> Optional[str]:
    """The stage whose registered hub is the session `sid` (a CLI uuid or a local_… id), or None."""
    if not sid:
        return None
    for path in sorted(hc.root().glob("*/roles.json")):
        try:
            rec = (json.loads(path.read_text(encoding="utf-8")).get("roles") or {}).get("hub") or {}
        except (OSError, ValueError, AttributeError):
            continue
        if sid in (rec.get("session"), rec.get("cli_session_id")) and hc.STAGE_RE.fullmatch(path.parent.name):
            return path.parent.name
    return None


def owner_spoke(prompt) -> bool:
    """A prompt typed by a person: no autopilot marker and not a harness notice (they start with an XML-like tag)."""
    text = prompt if isinstance(prompt, str) else ""
    return bool(text.strip()) and not MARKER_RE.search(text) and not text.lstrip().startswith("<")


# ---------------------------------------------------------------- the hub's own model and mode

def find_transcript(sid: str) -> Optional[Path]:
    if not sid:
        return None
    base = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "projects"
    hits = sorted(base.glob(f"*/{sid}.jsonl"), key=lambda p: p.stat().st_mtime)
    return hits[-1] if hits else None


def transcript_model(path) -> Optional[str]:
    """message.model of the last real assistant record of the main thread."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - (4 << 20)))
            lines = f.read().split(b"\n")
    except (OSError, TypeError):
        return None
    for line in reversed(lines):
        if b'"assistant"' not in line:
            continue
        try:
            o = json.loads(line)
        except ValueError:
            continue
        if not isinstance(o, dict) or o.get("type") != "assistant" or o.get("isSidechain") is True:
            continue
        model = (o.get("message") or {}).get("model")
        if isinstance(model, str) and model and model != "<synthetic>":
            return model
    return None


def successor_model(given: Optional[str], transcript=None) -> Optional[str]:
    return given or configured_model() or transcript_model(
        transcript or find_transcript(os.environ.get("CLAUDE_CODE_SESSION_ID", "")))


def codex_context() -> dict:
    """The latest persisted turn settings of this exact Codex session, if present."""
    hit = codex_rollouts.INDEX.session(hc.session_id())
    if hit:
        try:
            with hit[0].open("rb") as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - (4 << 20)))
                lines = f.read().splitlines()
            for line in reversed(lines):
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if isinstance(ev, dict) and ev.get("type") == "turn_context" and isinstance(ev.get("payload"), dict):
                    return dict(ev["payload"], _rollout_found=True)
        except OSError:
            pass
    # A detached coordinator knows its launch policy even before a rollout is discoverable.
    role = os.environ.get("AGENT_ROLE")
    stage = os.environ.get("HUB_STAGE")
    if role and stage and hc.STAGE_RE.fullmatch(role):
        try:
            meta = json.loads((hc.root() / hc.check_stage(stage) / "agents" / role / "meta.json").read_text())
            if meta.get("engine") == "codex" and meta.get("session_id") == hc.session_id():
                return {"model": meta.get("model"), "effort": meta.get("effort"), "sandbox_policy": meta.get("sandbox_policy") or {"type": meta.get("sandbox")},
                        "approval_policy": meta.get("approval_policy", "never")}
        except (OSError, ValueError, hc.Failure):
            pass
    return {}


def codex_model(given: Optional[str], context: dict, cwd: Path) -> Optional[str]:
    return (given or configured_model() or context.get("model") or os.environ.get("AGENT_HUB_CODEX_MODEL")
            or hc.setting("AGENT_HUB_CODEX_DEFAULT_MODEL", cwd=cwd) or None)


def codex_policy(given: Optional[str], context: dict, cwd: Path) -> tuple:
    override = given or configured_mode()
    if override:
        return engines.permission_policy(override, cwd=cwd), "never"
    sandbox = context.get("sandbox_policy")
    sandbox = sandbox.get("type") if isinstance(sandbox, dict) else sandbox
    if context and sandbox not in engines.SANDBOXES:
        raise hc.UsageError(f"unsupported or missing inherited Codex sandbox {sandbox!r}; "
                            "choose an explicit supported --permission-mode")
    if not sandbox:
        sandbox = engines.permission_policy(cwd=cwd)
    # Detached successors cannot surface approvals. Keep the sandbox and fail denied tools without a prompt.
    return sandbox, "never"


def successor_mode(given: Optional[str], hub_mode: Optional[str] = None) -> str:
    return given or configured_mode() or hub_mode or "default"


def mode_flag(mode: str) -> tuple:
    """(value for --permission-mode or None, note): default and plan start the successor in the normal mode."""
    if mode in ("default", ""):
        return None, ""
    if mode == "plan":
        return None, "the hub was in plan mode; the successor starts in the default mode"
    return mode, ""


def fallback_mode(model: str) -> str:
    """Instead of bypassPermissions when its disclaimer was never accepted."""
    return "acceptEdits" if "haiku" in model.lower() else "auto"


# ---------------------------------------------------------------- instructions for the hub (the hook)

def succeed_command(stage: str, model: Optional[str], mode: Optional[str], cwd: Optional[str], engine=None) -> str:
    parts = [tool("hub"), "succeed", "--stage", stage, "--handoff", "<the draft>"]
    if engine:
        parts += ["--engine", engine]
    if model:
        parts += ["--model", shlex.quote(model)]
    if mode:
        parts += ["--permission-mode", shlex.quote(mode)]
    if cwd:
        parts += ["--cwd", shlex.quote(cwd)]
    return " ".join(parts)


def instruction(stage: str, model: Optional[str], mode: Optional[str], cwd: Optional[str], now_block: bool,
                block_k: str) -> str:
    """The autopilot paragraph of the context budget's warning and deny reason."""
    when = ("Hand over now" if now_block else
            "Hand your shift to a successor yourself at the next quiet point (no agent waiting for your reply, no "
            "merge or lock operation in flight)")
    if engines.selected(hc.setting("AGENT_HUB_SUCCESSOR_ENGINE"), cwd) == "codex":
        context = codex_context()
        model = codex_model(None, context, Path(cwd or os.getcwd()))
        # Hook inputs may carry Claude-shaped permission names; inherit the exact Codex rollout at execution.
        command = succeed_command(stage, model, configured_mode(), cwd, "codex")
        return (f"Autopilot is on (AGENT_HUB_AUTO_HANDOFF). {when}: (1) `{tool('hub')} handoff --stage {stage}` "
                f"and fill its TODOs; (2) `{command}` starts a detached Codex successor and prints one `jwait`; "
                "(3) run/continue that waiter through the Codex shell harness, with individual waits bounded. "
                "On the successor's start line, tell the owner its name and `agent send` command, then stop: "
                "release no locks and make no more tool calls. On ALARM, check `agent status`; retry with --again "
                "only when the successor is dead. A chain limit stops automatic launches until the owner responds. "
                f"At {block_k} only handoff/succeed, jlog/jwait and the HANDOFF file pass.")
    return (f"Autopilot is on (AGENT_HUB_AUTO_HANDOFF). {when}: (1) `{tool('hub')} handoff --stage {stage}` and fill "
            "its TODOs; "
            f"(2) `{succeed_command(stage, model, mode, cwd)}` (Bash timeout 300000: it may take minutes) — it starts the successor (a background Remote Control "
            "session, else a headless hub) and prints a `jwait` command; (3) run that `jwait` with Bash "
            "run_in_background: true. When it delivers the successor's start line, tell the owner one line — the "
            "successor's name and link from `hub succeed` — and stop: no more tool calls, release no locks (the "
            f"successor's takeover moves them). If it ends with ALARM: `{tool('hub')} succeed --stage {stage} --fallback` "
            "(Bash timeout 300000). If "
            "`hub succeed` reports the chain limit, stop after the handoff and wait for the owner. "
            f"At {block_k} only `hub handoff`, `hub succeed`, `jlog`, `jwait` and the HANDOFF file pass.")


# ---------------------------------------------------------------- starting the successor

def child_env() -> dict:
    return {k: v for k, v in hc.child_env().items() if k not in STRIP_ENV}


def clean(text: str) -> str:
    return ANSI_RE.sub("", text or "").replace("\r", "")


def tail(text: str, limit: int = TAIL_CHARS) -> str:
    lines = [ln.strip() for ln in clean(text).splitlines() if ln.strip()]
    return hc.one_line(" / ".join(lines[-15:]))[-limit:]


class Start(Exception):
    """The background successor could not start; the message says why (it goes to the journal)."""


class Successor:
    def __init__(self, stage: str, n: int, handoff: Path, model: str, mode: str, cwd: Path, k: int, limit: int,
                 succ: Optional[int] = None):
        # The successor starts where a Desktop session does: in the repository's main checkout (the root), in a new
        # worktree of its own — never in the hub's directory, which may be a Desktop session's worktree that goes
        # when that session is archived. Outside git: in `cwd` itself, no worktree.
        self.root = main_checkout(cwd)
        self.stage, self.n, self.handoff, self.model, self.mode = stage, n, handoff, model, mode
        self.cwd = self.root or cwd
        self.k, self.limit = k, limit
        self.succ = succ or n + 1
        self.worktree: Optional[Path] = None  # the successor's worktree once started
        self.tag = f"hub-{n}"
        self.rc_name = f"{stage}-hub-{self.succ}"
        self.title = f"Hub {stage} #{self.succ}"
        self.wt_name = ""  # the name `claude --worktree` gets, picked once per background start
        self.notes: list = []
        self.env = child_env()
        cli = hc.find_claude(cwd)  # $CLAUDE_BIN, else the newer of `claude` on PATH and Claude Desktop's
        if cli is None:
            raise hc.Failure("claude not found on PATH, and no CLI is bundled with Claude Desktop (set $CLAUDE_BIN)")
        self.claude = cli.path
        old = hc.cli_warning(cli)
        if old:
            self.notes.append(old)
        self.cli_model = hc.model_map(cwd).get(model, model)  # `claude --bg` gets the id an AGENT_HUB_MODEL_MAP alias names
        self.since_ms = 0  # `claude agents` rows started before this are not ours (an earlier chain's)

    @property
    def marker(self) -> str:
        return f"[agent-hub auto-handoff {self.k}/{self.limit}]"

    def takeover_cmd(self) -> str:
        # no shell expansion (`--session self`, no AGENT_HUB_HOME= prefix: the session inherits the environment, E14,
        # E20): a command with `$VAR` in it asks for permission even under the allow rule of HUB_ALLOW (CLI 2.1.285)
        return (f"{tool('hub')} takeover --stage {self.stage} --session self --auto-handoff "
                f"--handoff {shlex.quote(str(self.handoff))}")

    def prompt(self) -> str:
        return (f"/agent-hub:hub take over stage {self.stage} from {self.handoff}: run `{self.takeover_cmd()}`, then "
                f"follow its digest and the handoff. \"Hub {self.stage} #{self.n}\" handed over automatically and "
                f"stopped; the owner may be away and reaches you here through Remote Control. {self.marker}")

    def run(self, argv: list, cwd=None, timeout: int = 60) -> subprocess.CompletedProcess:
        try:
            return subprocess.run([self.claude] + argv, capture_output=True, text=True, timeout=timeout,
                                  cwd=str(cwd or self.cwd), env=self.env, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(argv, 124, "", f"claude {argv[0]} did not finish in {timeout} s")
        except OSError as e:
            return subprocess.CompletedProcess(argv, 127, "", str(e))

    def check_login(self) -> None:
        res = self.run(["auth", "status", "--json"], timeout=30)
        try:
            data = json.loads(res.stdout)
        except ValueError:
            self.notes.append(f"`claude auth status` unreadable (exit {res.returncode}) — trying anyway")
            return
        if isinstance(data, dict) and data.get("loggedIn") is False:
            raise Start("the claude CLI is not logged in (`claude auth status`: loggedIn false) — run `claude auth "
                        "login` once in a terminal")

    def bg_argv(self, mode: str, cwd=None) -> list:
        flag, note = mode_flag(mode)
        if note and note not in self.notes:
            self.notes.append(note)
        # the hub home, writable also under the sandbox; before another option: --add-dir takes several values and
        # would swallow the prompt
        argv = ["--bg", "--remote-control", self.rc_name, "-n", self.title]
        if self.root:
            self.wt_name = self.wt_name or free_worktree_name(self.root, self.rc_name)
            argv += ["--worktree", self.wt_name]
        argv += hc.add_dir_args(cwd or self.cwd)
        argv += ["--model", self.cli_model]
        if flag:
            argv += ["--permission-mode", flag]
        if flag != "bypassPermissions":
            argv += ["--settings", json.dumps(successor_settings(), separators=(",", ":"))]
        return argv + [self.prompt()]

    def started(self, bg_id: str, mode: str) -> dict:
        self.mode = mode
        if self.root:  # where `claude --bg --worktree` puts it (E26)
            self.worktree = self.root / ".claude" / "worktrees" / self.wt_name
        return {"id": bg_id, "cwd": str(self.cwd), "mode": mode, "worktree": str(self.worktree or "")}

    def start_bg(self) -> dict:
        """Start the background session from the root, in a new worktree; retry once without bypass (its disclaimer
        was never accepted). Returns {id, cwd, mode, worktree}; the link is read afterwards (wait_link), once the id
        is recorded."""
        self.check_login()
        mode, cwd = self.mode, self.cwd
        tried_bypass = False
        self.since_ms = int(time.time() * 1000) - 2000  # a little slack for the daemon's clock
        while True:
            res = self.run(self.bg_argv(mode, cwd), cwd=cwd, timeout=BG_TIMEOUT_S)
            out = clean(res.stdout + "\n" + res.stderr)
            if res.returncode == 0:
                break
            if res.returncode == 124:
                # `claude --bg` hung: the session may exist all the same — never start a second one beside it
                bg_id = self.id_from_agents()
                if bg_id:
                    self.notes.append(f"`claude --bg` did not return in {BG_TIMEOUT_S} s; its session {bg_id} is "
                                      "listed by `claude agents`")
                    return self.started(bg_id, mode)
                stopped = self.stop_late()
                raise Start(f"`claude --bg` did not return in {BG_TIMEOUT_S} s and `claude agents` lists no session of "
                            f"it" + (f"; stopped the late ones {', '.join(stopped)}" if stopped else ""))
            if "disclaimer" in out.lower() and mode == "bypassPermissions" and not tried_bypass:
                tried_bypass, mode = True, fallback_mode(self.cli_model)
                self.notes.append(f"bypassPermissions needs its disclaimer accepted once (`claude "
                                  f"--dangerously-skip-permissions` in a terminal) — started in {mode} instead")
                continue
            if "not trusted" in out.lower():
                raise Start(f"{cwd} is not trusted by the claude CLI — run `claude` there once and accept the trust "
                            f"prompt (`claude --bg` exited {res.returncode})")
            raise Start(f"`claude --bg` exited {res.returncode}: {tail(out, 300) or 'no output'}")
        m = BG_ID_RE.search(out)
        bg_id = m.group(1) if m else self.id_from_agents()
        if not bg_id:
            raise Start(f"`claude --bg` printed no session id: {tail(out, 300) or 'no output'}")
        return self.started(bg_id, mode)

    def our_rows(self) -> list:
        """Active background sessions (`claude agents --json`) with the successor's name started since this start —
        a same-named one from an earlier chain is not ours. Oldest first."""
        res = self.run(["agents", "--json"], timeout=30)
        try:
            rows = json.loads(res.stdout)
        except ValueError:
            return []
        hits = [r for r in (rows if isinstance(rows, list) else []) if isinstance(r, dict)
                and r.get("kind") == "background" and r.get("name") in (self.rc_name, self.title)
                and isinstance(r.get("startedAt"), (int, float)) and r["startedAt"] >= self.since_ms]
        return sorted(hits, key=lambda r: r["startedAt"])

    def id_from_agents(self) -> Optional[str]:
        hits = self.our_rows()
        return (hits[-1].get("id") or hits[-1].get("sessionId")) if hits else None

    def stop_late(self) -> list:
        """After a `claude --bg` that hung and is not listed: stop whatever of that name shows up after all, so no
        background successor runs beside the headless one. Returns the ids stopped."""
        ids = [r.get("id") or r.get("sessionId") for r in self.our_rows()]
        for bg_id in ids:
            self.remove(bg_id, rm=False)
        return ids

    def wait_link(self, bg_id: str) -> str:
        """The Remote Control link from `claude logs`, polled up to min(90 s, the takeover timeout); "" when it never
        shows. A session that says it is not logged in is stopped and reported."""
        deadline = time.monotonic() + min(LINK_WAIT_S, takeover_timeout())
        while True:
            text = clean(self.run(["logs", bg_id], timeout=30).stdout)
            m = LINK_RE.search(text) or LINK_RE.search(text.replace("\n", ""))
            if m:
                link = m.group(0)
                return link if link.startswith("http") else "https://" + link
            if "not logged in" in text.lower():
                self.remove(bg_id, rm=True)
                raise Start("the background session is not logged in (`claude logs`: \"Not logged in\") — run "
                            "`claude auth login` once in a terminal")
            if time.monotonic() >= deadline:
                return ""
            time.sleep(1)

    def remove(self, bg_id: str, rm: bool) -> None:
        self.run(["stop", bg_id], timeout=30)
        if rm:
            self.run(["rm", bg_id], timeout=30)

    def brief(self, why: str) -> Path:
        path = hc.work_dir(self.stage) / f"hub-{self.succ}-takeover-brief.md"
        hc.atomic_write(path, f"""# Takeover brief: "{self.title}" — stage {self.stage}

You are the next hub of stage `{self.stage}`. "Hub {self.stage} #{self.n}" handed over automatically and stopped; a
background Remote Control session could not start ({why}), so you run headless. The owner may be away: they reach you
through `ask` (the question register) and `agent send hub-{self.succ} "…"`.

1. Load the hub skill (`/agent-hub:hub`) and take over: `{self.takeover_cmd()}`
   (`self` is this session: $CLAUDE_CODE_SESSION_ID, else the $AGENT_SESSION_ID `agent spawn` exports).
   Then follow the digest and the handoff `{self.handoff}`.
2. You are a `claude -p` run: the end of your turn ends the process, and a background `jwait` dies with it. Wait with
   `"$HUB_BIN/jwait"` in the foreground (Bash `timeout` 600000, `--for 9m`). When nothing is left to wait for, write a
   status line with `"$HUB_BIN/jlog"` and end your turn; `agent send` resumes this session.
3. The footer below is written for executors: for you "the hub" is the owner — questions go to `ask add` and a
   `"$HUB_BIN/jlog" "@owner …"` line, never to chat.
4. Your own context budget applies as it did to your predecessor: hand over the same way when it says so.

{self.marker}
""")
        return path

    def start_headless(self, why: str) -> dict:
        role = f"hub-{self.succ}"
        brief = self.brief(why)
        argv = [sys.executable, str(hc.BIN / "agent"), "spawn", "--stage", self.stage, "--role", role, "--tag", role,
                "--cwd", str(self.cwd), "--model", self.model, "--brief", str(brief), "--title", self.title]
        if self.root:
            # agent spawn's own worktree: <root>/.worktrees/<branch>, a new branch from the root's HEAD
            branch = free_worktree_name(self.root, self.rc_name)
            argv += ["--worktree", branch]
            self.worktree = self.root / ".worktrees" / branch
        res = subprocess.run(argv, capture_output=True, text=True, env=dict(self.env, HUB_TAG=self.tag),
                             stdin=subprocess.DEVNULL)
        if res.returncode != 0:
            if f"agent {role} is already running" in res.stderr + res.stdout:
                # a previous run (killed before it could record it) started it: the successor is there
                self.notes.append(f"the headless {role} was already running (started by an earlier run)")
                self.worktree = None  # its worktree is wherever that run put it (`agent status {role}`)
                return {"role": role, "brief": str(brief), "worktree": ""}
            raise hc.Failure(f"the headless successor did not start either: {tail(res.stderr or res.stdout, 400)}")
        return {"role": role, "brief": str(brief), "worktree": str(self.worktree or "")}

    def where(self) -> str:
        """Where the successor works, for the journal line."""
        if self.worktree:
            return f"in the new worktree {self.worktree} of {self.root}"
        return f"in {self.root} (a worktree of it)" if self.root else f"in {self.cwd}"


class CodexSuccessor(Successor):
    """Detached successor without a Claude login check or Remote Control fallback."""
    def __init__(self, stage, n, handoff, model, mode, cwd, k, limit, approval="never", sandbox_policy=None, effort=None, succ=None):
        self.root = main_checkout(cwd)
        self.stage, self.n, self.handoff, self.model, self.mode = stage, n, handoff, model, mode
        self.cwd = self.root or cwd
        self.k, self.limit, self.succ = k, limit, succ or n + 1
        self.tag, self.title = f"hub-{n}", f"Hub {stage} #{self.succ}"
        self.rc_name = f"{stage}-hub-{self.succ}"
        self.worktree = None
        self.wt_name = ""
        self.notes, self.env, self.approval = [], child_env(), approval
        self.sandbox_policy = sandbox_policy or {"type": mode}
        self.effort = effort
        self.codex = engines.codex_bin(cwd)
        self.cli_model = engines.model_map(cwd).get(model, model) if model else None

    def brief_text(self):
        skill = hc.BIN.parent / "skills" / "hub" / "SKILL.md"
        return f"""# Takeover brief: "{self.title}" — stage {self.stage}

You are the next hub of stage `{self.stage}`. Your predecessor handed over automatically and stopped.
The owner may be away; they reach you through `ask` and `agent send hub-{self.succ} "…"`.

1. Read the bundled hub skill at `{skill}` (or invoke the installed `agent-hub:hub` skill), then run
   `{self.takeover_cmd()}`. `self` resolves this worker's own session id. Follow its digest and `{self.handoff}`.
2. Wait through the shell harness with `"$HUB_BIN/jwait" --for 9m`; preserve its execution id and exit status.
   Keep individual tool waits bounded so you can read the inbox and respond. When nothing remains to wait for,
   write a status line with `"$HUB_BIN/jlog"` and finish; `agent send` resumes this same Codex thread.
3. The executor footer's "hub" means the owner here: record questions with `ask add` and journal `@owner …`.
4. Hand over at your context budget as your predecessor did. Preserve your engine, model and permission policy.

{self.marker}
"""

    def brief(self, why):
        path = hc.work_dir(self.stage) / f"hub-{self.succ}-takeover-brief.md"
        hc.atomic_write(path, self.brief_text())
        return path

    def argv(self, brief):
        role = f"hub-{self.succ}"
        argv = [sys.executable, str(hc.BIN / "agent"), "spawn", "--engine", "codex", "--stage", self.stage,
                "--role", role, "--tag", role, "--cwd", str(self.cwd), "--brief", str(brief), "--title", self.title,
                "--sandbox-policy", json.dumps(self.sandbox_policy, separators=(",", ":"))]
        if self.model:
            argv += ["--model", self.model]
        if self.effort:
            argv += ["--effort", self.effort]
        if self.root and self.wt_name:
            argv += ["--worktree", self.wt_name]
        return argv

    def start_headless(self, why):
        role, brief = f"hub-{self.succ}", self.brief(why)
        if self.root:
            self.wt_name = free_worktree_name(self.root, self.rc_name)
            self.worktree = self.root / ".worktrees" / self.wt_name
        res = subprocess.run(self.argv(brief), capture_output=True, text=True, env=dict(self.env, HUB_TAG=self.tag),
                             stdin=subprocess.DEVNULL)
        if res.returncode:
            if f"agent {role} is already running" in res.stdout + res.stderr:
                self.notes.append(f"the headless {role} was already running (started by an earlier run)")
                self.worktree = None
            else:
                raise hc.Failure(f"the Codex successor did not start: {tail(res.stderr or res.stdout, 400)}")
        return {"role": role, "brief": str(brief), "worktree": str(self.worktree or "")}

    def dry_argv(self):
        meta = {"cwd": str(self.cwd), "model": self.cli_model, "sandbox": self.mode,
                "approval_policy": self.approval, "sandbox_policy": self.sandbox_policy, "effort": self.effort}
        return engines.codex_argv(meta, self.brief_text())


def successor_settings() -> dict:
    """Permissions of a successor not in bypass mode: the hub's commands, reading and writing in the hub home (its
    journal, the handoff, the next handoff). Both spellings of the home when a symlink is in its path (/tmp)."""
    homes = list(dict.fromkeys([str(hc.root()), str(hc.root().resolve())]))
    allow = ([f"Bash({c}:*)" for c in HUB_ALLOW] + [f"Bash({tool(c.split()[0])}{c[len(c.split()[0]):]}:*)" for c in HUB_ALLOW]
             + [f"Edit(/{h}/**)" for h in homes])
    return {"permissions": {"allow": allow, "additionalDirectories": homes}}


def main_checkout(cwd: Path) -> Optional[Path]:
    """The main checkout of the repository `cwd` is in (itself, when it is the main checkout); None outside git."""
    res = subprocess.run(["git", "-C", str(cwd), "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                         env=hc.git_env())
    top = Path(res.stdout.strip()) if res.returncode == 0 and res.stdout.strip() else None
    if top is None:
        return None
    return hc.main_checkout(top) or top


def free_worktree_name(root: Path, base: str) -> str:
    """`base`, else `base-2`, `base-3`…: the first name no worktree directory of `root` (`.claude/worktrees/` of
    `claude --worktree`, `.worktrees/` of `agent spawn`) and no branch (`worktree-<name>`, `<name>`) holds yet.
    `claude --bg --worktree` with a taken name does not fail: it joins the existing worktree (E26)."""
    def taken(name: str) -> bool:
        if (root / ".claude" / "worktrees" / name).exists() or (root / ".worktrees" / name).exists():
            return True
        return any(subprocess.run(["git", "-C", str(root), "show-ref", "--verify", "--quiet", f"refs/heads/{b}"],
                                  capture_output=True, env=hc.git_env()).returncode == 0
                   for b in (f"worktree-{name}", name))
    for name in [base] + [f"{base}-{i}" for i in range(2, 100)]:
        if not taken(name):
            return name
    raise Start(f"no free worktree name {base}-2 … {base}-99 under {root}")


def jwait_command(stage: str, succ: int, since: str, timeout_s: int) -> str:
    match = shlex.quote(r"\[hub-" + str(succ) + r"\] start:")
    return (f"{tool('jwait')} --journal --stage {stage} --match {match} --since {since} "
            f"--settle 1 --for {timeout_s}s --note \"no takeover by hub-{succ}\"")


def report(stage: str, s: Successor, pend: dict, timeout_s: int) -> None:
    """The journal line and what the hub does next."""
    since = pend["at"][11:16]
    if pend["kind"] == "bg":
        where = (f"Remote Control {pend['link']}" if pend.get("link")
                 else f"Remote Control link not shown yet (`claude logs {pend['id']}`)")
        line = (f"auto-handoff {s.k}/{s.limit}: started \"{s.title}\" ({s.model}, {pend['mode']}) as background "
                f"session {pend['id']} — {where}; terminal: claude attach {pend['id']}; {s.where()}; waiting for its "
                f"takeover (≤ {timeout_s} s)")
    else:
        line = (f"auto-handoff {s.k}/{s.limit}: started \"{s.title}\" ({s.model or 'CLI configured model'}) headless as agent {pend['role']} "
                f"because {pend['why']} — the owner reaches it through `ask` and `agent send {pend['role']} \"…\"`; "
                f"{s.where()}; waiting for its takeover (≤ {timeout_s} s)")
    if s.notes:
        line += "; " + "; ".join(s.notes)
    hc.journal_append(stage, s.tag, line)
    print(line)
    waiting = ("continue through the Codex shell execution harness" if pend.get("engine") == "codex"
               else "run in the background (Bash run_in_background: true)")
    print(f"\nNext: {waiting}:\n  "
          + jwait_command(stage, s.succ, since, timeout_s))
    if pend["kind"] == "bg":
        print(f"Exit 0 (its start line) → tell the owner one line: \"{s.title}\" took over — "
              f"{pend.get('link') or 'claude attach ' + pend['id']}; then stop: no more tool calls.\n"
              f"ALARM (exit 3) → {tool('hub')} succeed --stage {stage} --fallback")
    else:
        print(f"Exit 0 → tell the owner one line: \"{s.title}\" took over headless — `agent send {pend['role']} \"…\"`; "
              "then stop: no more tool calls.\nALARM (exit 3) → if `agent status " + pend['role'] + "` says it is not "
              f"running: `{tool('hub')} succeed --stage {stage} --again --handoff <the handoff>`; else tell the owner the "
              "handoff did not complete and wait for them.")


def _age(pend: dict) -> float:
    """Seconds since the record's `at`; infinite when it cannot be read."""
    try:
        return (hc.now() - hc.dt.datetime.fromisoformat(pend["at"])).total_seconds()
    except (KeyError, ValueError, TypeError):
        return float("inf")


def blocking(pend: dict, succ: int) -> bool:
    """A successor for this shift is being started (a reservation younger than START_BUDGET_S: an older one is a run
    that died) or was started and has not taken over (until `--fallback`, `--again` or the owner drops it)."""
    if pend.get("n") != succ or pend.get("taken_over"):
        return False
    if pend.get("kind") in IN_PROGRESS:
        return _age(pend) < START_BUDGET_S
    return True


def wait_hint(stage: str, pend: dict) -> str:
    """What to do about a blocking record: when to retry, and the ready `jwait` that wakes then."""
    succ = pend.get("n")
    match = shlex.quote(r"\[hub-" + str(succ) + r"\] start:|auto-handoff")
    if pend.get("kind") in IN_PROGRESS:
        left = max(30, int(START_BUDGET_S - _age(pend)) + 5)
        at = (hc.now() + hc.dt.timedelta(seconds=left)).strftime("%H:%M")
        return (f"a run of `hub succeed` holds the shift until about {at}; wait (Bash run_in_background: true): "
                f"{tool('jwait')} --journal --stage {stage} --match {match} --settle 1 --for {left}s "
                f"--note \"retry hub succeed\" — then retry")
    left = max(30, int(takeover_timeout() - _age(pend)))
    alive = (f"`claude agents` lists {pend.get('id')}" if pend.get("kind") == "bg"
             else f"`agent status {pend.get('role')}` says it runs")
    return (f"wait for its takeover (Bash run_in_background: true): {tool('jwait')} --journal --stage {stage} "
            f"--match {match} --settle 1 --for {left}s --note \"no takeover by hub-{succ}\"; on ALARM: "
            + (f"`{tool('hub')} succeed --stage {stage} --fallback`" if pend.get("kind") == "bg" else
               f"`{tool('hub')} succeed --stage {stage} --again --handoff <the handoff>` unless {alive}"))


def _agent_module():
    loader = importlib.machinery.SourceFileLoader("agent_cli", str(hc.BIN / "agent"))
    spec = importlib.util.spec_from_loader("agent_cli", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def successor_alive(stage: str, pend: dict, cwd) -> bool:
    """Whether the recorded successor still runs: a background session listed by `claude agents`, a headless agent
    whose process is alive. When it cannot be told, alive (never drop a record of a live successor)."""
    if pend.get("kind") == "headless":
        try:
            ag = _agent_module()
            return ag.alive(ag.load_meta(stage, pend["role"]))
        except (hc.Failure, KeyError, OSError, ValueError):
            return False  # no agent directory or meta: nothing runs
    cli = hc.find_claude(cwd)
    if cli is None:
        return True
    try:
        res = subprocess.run([cli.path, "agents", "--json"], capture_output=True, text=True, timeout=30,
                             env=child_env(), stdin=subprocess.DEVNULL)
        rows = json.loads(res.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return True
    return any(isinstance(r, dict) and pend.get("id") in (r.get("id"), r.get("sessionId")) for r in rows or [])


def drop_dead(stage: str, n: int, cwd, succ: int) -> None:
    """`hub succeed --again`: the recorded successor of this shift did not take over and does not run — drop its
    record and give back its count. A live one is refused, a run in progress too."""
    pend = load_state(stage).get("pending") or {}
    if pend.get("n") != succ or pend.get("taken_over"):
        return
    if pend.get("kind") in IN_PROGRESS and blocking(pend, succ):
        raise hc.Failure(f"hub-{succ} is being started right now — {wait_hint(stage, pend)}")
    if pend.get("kind") not in IN_PROGRESS and successor_alive(stage, pend, cwd):
        stop = (f"claude stop {pend.get('id')}" if pend.get("kind") == "bg" else f"agent stop {pend.get('role')}")
        raise hc.Failure(f"--again: the successor hub-{succ} ({pend.get('kind')} {pend.get('id') or pend.get('role')}) "
                         f"is still running — wait for it, or stop it first (`{stop}`)")
    with state_lock(stage):
        data = load_state(stage)
        if data.get("pending") != pend:
            raise hc.Failure("--again: the pending record changed meanwhile — look again (`hub succeed` once more)")
        data["pending"] = None
        if pend.get("k") and data["chain"] == pend["k"]:
            data["chain"] -= 1
        save_state(stage, data)
    hc.journal_append(stage, f"hub-{n}", f"auto-handoff: dropped hub-{succ} ({pend.get('kind')} "
                                         f"{pend.get('id') or pend.get('role')}): it did not take over and is not running")


def _record(stage: str, succ: int, pend: dict) -> None:
    """Replace the pending record of this shift (a takeover by hand in between cleared it: then leave it)."""
    with state_lock(stage):
        data = load_state(stage)
        previous = data.get("pending") or {}
        if previous.get("n") == succ:
            if previous.get("taken_over"):
                pend = dict(pend, taken_over=previous["taken_over"])
            data["pending"] = pend
            save_state(stage, data)


def _release(stage: str, succ: int, k: int) -> None:
    """No successor started after all: drop the reservation and give back its count."""
    with state_lock(stage):
        data = load_state(stage)
        if (data.get("pending") or {}).get("n") == succ:
            data["pending"] = None
        if data["chain"] == k:
            data["chain"] = k - 1
        save_state(stage, data)


def succeed(stage: str, n: int, handoff: Path, model: Optional[str], mode: Optional[str], cwd: Path,
            headless: bool = False, dry_run: bool = False, again: bool = False, engine=None,
            succ: Optional[int] = None, notes: tuple = ()) -> int:
    limit = chain_limit()
    tag, succ = f"hub-{n}", succ or n + 1
    retry = (load_state(stage).get("pending") or {}) if again else {}
    if retry.get("n") != succ or retry.get("taken_over"):
        retry = {}
    engine = engines.selected(engine or hc.setting("AGENT_HUB_SUCCESSOR_ENGINE") or retry.get("engine"), cwd)
    approval, sandbox_policy, effort = "never", None, None
    if engine == "codex":
        context = codex_context()
        if retry.get("engine") == "codex":
            context = dict(context, model=retry.get("model"), effort=retry.get("effort"),
                           sandbox_policy=retry.get("sandbox_policy") or {"type": retry.get("mode")},
                           approval_policy=retry.get("approval_policy", "never"))
        effort = context.get("effort")
        if effort is None and retry.get("engine") != "codex":
            effort = os.environ.get("AGENT_HUB_CODEX_EFFORT") or None
        if effort is not None and effort not in engines.CODEX_EFFORTS:
            raise hc.UsageError(f"unsupported inherited Codex effort {effort!r}")
        model = codex_model(model, context, cwd)
        problem = engines.model_problem(model, cwd) if model else None
        explicit_mode = mode or configured_mode()
        mode, approval = codex_policy(mode, context, cwd)
        sandbox_policy = (context.get("sandbox_policy") if not explicit_mode else None)
        if not isinstance(sandbox_policy, dict):
            sandbox_policy = {"type": mode}
        sandbox_policy = engines.sandbox_policy(sandbox_policy)
    else:
        model = successor_model(model)
        if not model:
            raise hc.UsageError("no model for the successor: pass --model (the hub's transcript was not found and "
                                "AGENT_HUB_SUCCESSOR_MODEL is not set)")
        problem = hc.model_problem(model, cwd)
        mode = successor_mode(mode)
        if mode not in MODES:
            raise hc.UsageError(f"permission mode {mode!r}: one of {', '.join(MODES)}")
    if problem:
        raise hc.UsageError(f"--model {model!r}: {problem}")
    if again and not dry_run:
        drop_dead(stage, n, cwd, succ)
    started = hc.now().isoformat(timespec="seconds")
    # One successor per shift and the chain counted under the lock, before anything starts: a second `hub succeed`
    # (a retry after a Bash timeout, a parallel call) sees the reservation, and an owner's reset is never overwritten.
    with state_lock(stage):
        data = load_state(stage)
        pend = data.get("pending") or {}
        if blocking(pend, succ) and not dry_run:
            raise hc.Failure(f"a successor hub-{succ} is already {'being started' if pend.get('kind') in IN_PROGRESS else 'started'} "
                             f"({pend.get('kind')} {pend.get('id') or pend.get('role') or ''}, at {pend.get('at', '?')[11:16]}): "
                             + wait_hint(stage, pend))
        at_limit = data["chain"] >= limit
        k = data["chain"] + 1
        if not at_limit and not dry_run:
            data["chain"] = k
            data["pending"] = {"n": succ, "kind": "starting", "at": started, "handoff": str(handoff),
                               "model": model, "k": k, "engine": engine, "mode": mode, "approval_policy": approval, "sandbox_policy": sandbox_policy, "effort": effort}
            save_state(stage, data)
    if at_limit:
        line = (f"auto-handoff chain limit {limit} reached — waiting for the owner; handoff {handoff}. "
                f"No successor started.")
        if not dry_run:
            hc.journal_append(stage, tag, line)
        print(line + "\nTell the owner one line (the handoff path) and stop; the owner starts the next hub.")
        return 3
    try:
        s = (CodexSuccessor(stage, n, handoff, model, mode, cwd, k, limit, approval, sandbox_policy, effort, succ) if engine == "codex"
             else Successor(stage, n, handoff, model, mode, cwd, k, limit, succ))
        s.notes.extend(notes)
        if engine == "codex" and context.get("approval_policy") not in (None, "never"):
            s.notes.append(f"inherited sandbox {mode}; approval policy {context['approval_policy']} becomes never "
                           "for the unattended successor (denied tools fail without broadening permissions)")
    except hc.Failure as e:
        if not dry_run:
            _release(stage, succ, k)
            hc.journal_append(stage, tag, f"BLOCKED auto-handoff: no successor started ({e}) — waiting for the owner; "
                                          f"handoff {handoff}")
        raise
    if dry_run:
        print(f"[plan] auto-handoff {s.k}/{limit}: start \"{s.title}\" from {s.cwd}"
              + (" in a new worktree" if s.root else "") + ":\n  "
              + " ".join(shlex.quote(x) for x in (s.dry_argv() if engine == "codex"
                                                 else [s.claude] + s.bg_argv(mode))))
        return 0
    if engine == "codex":
        why = "the Codex engine uses a detached successor"
    elif headless:
        why = "--headless was given"
    else:
        try:
            got = s.start_bg()
            pend = {"n": succ, "kind": "bg", "at": started, "handoff": str(handoff), "model": model, "k": k,
                    "link": "", **got}
            _record(stage, succ, pend)  # the id first: a crash while the link is read leaves it findable
            pend["link"] = s.wait_link(got["id"])
            _record(stage, succ, pend)
            report(stage, s, pend, takeover_timeout())
            return 0
        except Start as e:
            why = str(e)
    hc.journal_append(stage, tag, f"auto-handoff: background successor not started — {why}; falling back to a "
                                  "headless hub (agent spawn)")
    _record(stage, succ, {"n": succ, "kind": "starting", "at": hc.now().isoformat(timespec="seconds"),
                          "handoff": str(handoff), "model": model, "k": k, "engine": engine, "mode": mode,
                          "approval_policy": approval, "sandbox_policy": sandbox_policy, "effort": effort})  # a new phase: a fresh start budget
    got = headless_or_owner(stage, s, why)
    pend = {"n": succ, "kind": "headless", "at": started, "handoff": str(handoff), "model": model, "k": k,
            "why": why, "cwd": str(s.cwd), "engine": engine, "mode": mode, "approval_policy": approval, "sandbox_policy": sandbox_policy, "effort": effort, **got}
    _record(stage, succ, pend)
    report(stage, s, pend, takeover_timeout())
    return 0


def headless_or_owner(stage: str, s: Successor, why: str) -> dict:
    try:
        if isinstance(s, CodexSuccessor):
            # A manual takeover while this command prepared its successor ends our reservation.
            # Keep the lock until spawn has returned its init handshake; takeover then proceeds normally.
            with state_lock(stage):
                current = hc.roles_load(stage)["roles"].get("hub") or {}
                pending = load_state(stage).get("pending") or {}
                number = hc.hub_number(current.get("tag"))
                if not current or (number is not None and number != s.n) or pending.get("n") != s.succ or pending.get("taken_over"):
                    raise hc.Failure("the hub changed while the successor was prepared; no Codex process started")
                return s.start_headless(why)
        return s.start_headless(why)
    except hc.Failure as e:
        _release(stage, s.succ, s.k)
        hc.journal_append(stage, s.tag, f"BLOCKED auto-handoff: no successor started ({e}) — waiting for the owner; "
                                        f"handoff {s.handoff}")
        raise


def fallback(stage: str, n: int, why: Optional[str], succ: Optional[int] = None) -> int:
    """The background successor did not take over in time: journal its log tail, stop it, start a headless one from
    the same handoff (the chain is not counted again). Only for this hub's own successor (hub-<succ>, default n + 1).
    Reserved under the lock like `hub succeed`, so a retry after a killed run is refused rather than doubled."""
    now = hc.now().isoformat(timespec="seconds")
    succ = succ or n + 1
    with state_lock(stage):
        data = load_state(stage)
        pend = data.get("pending") or {}
        if pend.get("n") != succ:
            print(f"auto-handoff: no successor of hub-{n} pending (pending: "
                  f"{'hub-' + str(pend['n']) if pend.get('n') else 'none'}) — nothing to fall back from")
            return 1
        if pend.get("taken_over"):
            print(f"hub-{pend.get('n')} already took over at {pend['taken_over'][:16]} — nothing to fall back from")
            return 0
        if pend.get("kind") in IN_PROGRESS and blocking(pend, succ):
            print(f"auto-handoff: hub-{succ} is being started right now — {wait_hint(stage, pend)}")
            return 1
        if pend.get("kind") == "headless":
            line = (f"auto-handoff: the headless successor {pend.get('role')} did not take over either — waiting for "
                    "the owner")
            hc.journal_append(stage, f"hub-{n}", line)
            print(line + "; if it is not running: "
                  + wait_hint(stage, dict(pend, at="1970-01-01T00:00:00+00:00")).split("on ALARM: ", 1)[-1])
            return 1
        if pend.get("kind") == "starting" or not pend.get("id"):
            print(f"auto-handoff: the run that was starting hub-{succ} died before it started anything — "
                  f"`{tool('hub')} succeed --stage {stage} --handoff {shlex.quote(str(pend.get('handoff', '<the handoff>')))}`")
            return 1
        bg = dict(pend, kind="bg") if pend.get("kind") == "falling-back" else pend  # a stale run of --fallback
        data["pending"] = dict(bg, kind="falling-back", at=now, bg_at=bg.get("bg_at") or bg.get("at"))
        save_state(stage, data)
    timeout_s = takeover_timeout()
    try:
        s = Successor(stage, n, Path(bg["handoff"]), bg["model"], bg.get("mode") or "default",
                      Path(bg.get("cwd") or os.getcwd()), bg.get("k") or data["chain"], chain_limit(), succ)
    except hc.Failure:
        _record(stage, succ, bg)
        raise
    logs = tail(s.run(["logs", bg["id"]], timeout=30).stdout)
    with state_lock(stage):
        # the successor may have registered while its logs were read: then it is taking over — do not stop it
        rec = hc.roles_load(stage)["roles"].get("hub") or {}
        num = hc.hub_number(rec.get("tag"))  # a tag with no number (`hub`) is the old hub's: a takeover tags `hub-N`
        if num is not None and num != n:
            data = load_state(stage)
            if (data.get("pending") or {}).get("kind") == "falling-back":
                data["pending"] = bg
                save_state(stage, data)
            print(f"auto-handoff: the hub is now {rec.get('tag')} ({rec.get('title') or rec.get('session')}) — "
                  f"{bg['id']} is taking over; not stopped")
            return 0
        s.remove(bg["id"], rm=False)
    why = why or f"background session {bg['id']} wrote no takeover line in {timeout_s} s"
    hc.journal_append(stage, s.tag, f"auto-handoff: {why}; stopped it (`claude attach {bg['id']}` shows it); "
                                    f"claude logs tail: {logs or '—'}; falling back to a headless hub")
    got = headless_or_owner(stage, s, why)
    new = {"n": s.succ, "kind": "headless", "at": hc.now().isoformat(timespec="seconds"), "handoff": bg["handoff"],
           "model": bg["model"], "k": s.k, "why": why, "cwd": str(s.cwd), "bg_id": bg["id"], **got}
    _record(stage, s.succ, new)
    report(stage, s, new, timeout_s)
    return 0
