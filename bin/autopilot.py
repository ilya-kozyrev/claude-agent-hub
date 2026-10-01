"""Autopilot: the hub hands its shift to a successor session by itself (`hub succeed`, hooks/context_budget.py).

At the context budget's warn threshold the hook tells a stage hub to hand over at its next quiet point: `hub handoff`,
fill the TODOs, `hub succeed`. `hub succeed` starts the successor as a background Remote Control session
(`claude --bg --remote-control`), reachable from the phone or claude.ai and from a terminal (`claude attach <id>`);
when that cannot start, as a headless hub (`agent spawn`) the owner talks to through `ask` and `agent send`.

Settings (the hub home's config.json or the environment only — a cloned repository must not start background
sessions or choose their permission mode):
  AGENT_HUB_AUTO_HANDOFF               off | on (default off)
  AGENT_HUB_AUTO_HANDOFF_CHAIN         automatic handoffs in a row without the owner (default 10; 0 = never)
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
             "HUB_TAG", "AGENT_ROLE", "AGENT_SESSION_ID")
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

def succeed_command(stage: str, model: Optional[str], mode: Optional[str], cwd: Optional[str]) -> str:
    parts = [tool("hub"), "succeed", "--stage", stage, "--handoff", "<the draft>"]
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
    def __init__(self, stage: str, n: int, handoff: Path, model: str, mode: str, cwd: Path, k: int, limit: int):
        self.stage, self.n, self.handoff, self.model, self.mode, self.cwd = stage, n, handoff, model, mode, cwd
        self.k, self.limit = k, limit
        self.succ = n + 1
        self.tag = f"hub-{n}"
        self.rc_name = f"{stage}-hub-{self.succ}"
        self.title = f"Hub {stage} #{self.succ}"
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
        argv = ["--bg", "--remote-control", self.rc_name, "-n", self.title] + hc.add_dir_args(cwd or self.cwd)
        argv += ["--model", self.cli_model]
        if flag:
            argv += ["--permission-mode", flag]
        if flag != "bypassPermissions":
            argv += ["--settings", json.dumps(successor_settings(), separators=(",", ":"))]
        return argv + [self.prompt()]

    def start_bg(self) -> dict:
        """Start the background session; retry once without bypass (its disclaimer was never accepted) and once in
        the repository's main checkout (the worktree is not trusted). Returns {id, cwd, mode}; the link is read
        afterwards (wait_link), once the id is recorded."""
        self.check_login()
        mode, cwd = self.mode, self.cwd
        tried_bypass = tried_main = False
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
                    self.mode, self.cwd = mode, cwd
                    return {"id": bg_id, "cwd": str(cwd), "mode": mode}
                stopped = self.stop_late()
                raise Start(f"`claude --bg` did not return in {BG_TIMEOUT_S} s and `claude agents` lists no session of "
                            f"it" + (f"; stopped the late ones {', '.join(stopped)}" if stopped else ""))
            if "disclaimer" in out.lower() and mode == "bypassPermissions" and not tried_bypass:
                tried_bypass, mode = True, fallback_mode(self.cli_model)
                self.notes.append(f"bypassPermissions needs its disclaimer accepted once (`claude "
                                  f"--dangerously-skip-permissions` in a terminal) — started in {mode} instead")
                continue
            if "not trusted" in out.lower() and not tried_main:
                tried_main = True
                main = main_checkout(cwd)
                if main and main != cwd:
                    self.notes.append(f"{cwd} is not trusted by the claude CLI — started in the main checkout {main}")
                    cwd = main
                    continue
            raise Start(f"`claude --bg` exited {res.returncode}: {tail(out, 300) or 'no output'}")
        m = BG_ID_RE.search(out)
        bg_id = m.group(1) if m else self.id_from_agents()
        if not bg_id:
            raise Start(f"`claude --bg` printed no session id: {tail(out, 300) or 'no output'}")
        self.mode, self.cwd = mode, cwd
        return {"id": bg_id, "cwd": str(cwd), "mode": mode}

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
        res = subprocess.run(argv, capture_output=True, text=True, env=dict(self.env, HUB_TAG=self.tag),
                             stdin=subprocess.DEVNULL)
        if res.returncode != 0:
            if f"agent {role} is already running" in res.stderr + res.stdout:
                # a previous run (killed before it could record it) started it: the successor is there
                self.notes.append(f"the headless {role} was already running (started by an earlier run)")
                return {"role": role, "brief": str(brief)}
            raise hc.Failure(f"the headless successor did not start either: {tail(res.stderr or res.stdout, 400)}")
        return {"role": role, "brief": str(brief)}


def successor_settings() -> dict:
    """Permissions of a successor not in bypass mode: the hub's commands, reading and writing in the hub home (its
    journal, the handoff, the next handoff). Both spellings of the home when a symlink is in its path (/tmp)."""
    homes = list(dict.fromkeys([str(hc.root()), str(hc.root().resolve())]))
    allow = ([f"Bash({c}:*)" for c in HUB_ALLOW] + [f"Bash({tool(c.split()[0])}{c[len(c.split()[0]):]}:*)" for c in HUB_ALLOW]
             + [f"Edit(/{h}/**)" for h in homes])
    return {"permissions": {"allow": allow, "additionalDirectories": homes}}


def main_checkout(cwd: Path) -> Optional[Path]:
    """The main checkout of the repository `cwd` is in (itself, when it is the main checkout)."""
    res = subprocess.run(["git", "-C", str(cwd), "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                         env=hc.git_env())
    top = Path(res.stdout.strip()) if res.returncode == 0 and res.stdout.strip() else None
    if top is None:
        return None
    return hc.main_checkout(top) or top


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
                f"session {pend['id']} — {where}; terminal: claude attach {pend['id']}; waiting for its takeover "
                f"(≤ {timeout_s} s)")
    else:
        line = (f"auto-handoff {s.k}/{s.limit}: started \"{s.title}\" ({s.model}) headless as agent {pend['role']} "
                f"because {pend['why']} — the owner reaches it through `ask` and `agent send {pend['role']} \"…\"`; "
                f"waiting for its takeover (≤ {timeout_s} s)")
    if s.notes:
        line += "; " + "; ".join(s.notes)
    hc.journal_append(stage, s.tag, line)
    print(line)
    print("\nNext: run in the background (Bash run_in_background: true):\n  "
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


def drop_dead(stage: str, n: int, cwd) -> None:
    """`hub succeed --again`: the recorded successor of this shift did not take over and does not run — drop its
    record and give back its count. A live one is refused, a run in progress too."""
    pend = load_state(stage).get("pending") or {}
    if pend.get("n") != n + 1 or pend.get("taken_over"):
        return
    if pend.get("kind") in IN_PROGRESS and blocking(pend, n + 1):
        raise hc.Failure(f"hub-{n + 1} is being started right now — {wait_hint(stage, pend)}")
    if pend.get("kind") not in IN_PROGRESS and successor_alive(stage, pend, cwd):
        stop = (f"claude stop {pend.get('id')}" if pend.get("kind") == "bg" else f"agent stop {pend.get('role')}")
        raise hc.Failure(f"--again: the successor hub-{n + 1} ({pend.get('kind')} {pend.get('id') or pend.get('role')}) "
                         f"is still running — wait for it, or stop it first (`{stop}`)")
    with state_lock(stage):
        data = load_state(stage)
        if data.get("pending") != pend:
            raise hc.Failure("--again: the pending record changed meanwhile — look again (`hub succeed` once more)")
        data["pending"] = None
        if pend.get("k") and data["chain"] == pend["k"]:
            data["chain"] -= 1
        save_state(stage, data)
    hc.journal_append(stage, f"hub-{n}", f"auto-handoff: dropped hub-{n + 1} ({pend.get('kind')} "
                                         f"{pend.get('id') or pend.get('role')}): it did not take over and is not running")


def _record(stage: str, succ: int, pend: dict) -> None:
    """Replace the pending record of this shift (a takeover by hand in between cleared it: then leave it)."""
    with state_lock(stage):
        data = load_state(stage)
        if (data.get("pending") or {}).get("n") == succ:
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
            headless: bool = False, dry_run: bool = False, again: bool = False) -> int:
    limit = chain_limit()
    tag, succ = f"hub-{n}", n + 1
    model = successor_model(model)
    if not model:
        raise hc.UsageError("no model for the successor: pass --model (the hub's transcript was not found and "
                            "AGENT_HUB_SUCCESSOR_MODEL is not set)")
    problem = hc.model_problem(model, cwd)
    if problem:
        raise hc.UsageError(f"--model {model!r}: {problem}")
    mode = successor_mode(mode)
    if mode not in MODES:
        raise hc.UsageError(f"permission mode {mode!r}: one of {', '.join(MODES)}")
    if again and not dry_run:
        drop_dead(stage, n, cwd)
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
                               "model": model, "k": k}
            save_state(stage, data)
    if at_limit:
        line = (f"auto-handoff chain limit {limit} reached — waiting for the owner; handoff {handoff}. "
                f"No successor started.")
        if not dry_run:
            hc.journal_append(stage, tag, line)
        print(line + "\nTell the owner one line (the handoff path) and stop; the owner starts the next hub.")
        return 3
    try:
        s = Successor(stage, n, handoff, model, mode, cwd, k, limit)
    except hc.Failure as e:
        if not dry_run:
            _release(stage, succ, k)
            hc.journal_append(stage, tag, f"BLOCKED auto-handoff: no successor started ({e}) — waiting for the owner; "
                                          f"handoff {handoff}")
        raise
    if dry_run:
        print(f"[plan] auto-handoff {s.k}/{limit}: start \"{s.title}\" in {cwd}:\n  "
              + " ".join(shlex.quote(x) for x in [s.claude] + s.bg_argv(mode)))
        return 0
    if headless:
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
                          "handoff": str(handoff), "model": model, "k": k})  # a new phase: a fresh start budget
    got = headless_or_owner(stage, s, why)
    pend = {"n": succ, "kind": "headless", "at": started, "handoff": str(handoff), "model": model, "k": k,
            "why": why, "cwd": str(s.cwd), **got}
    _record(stage, succ, pend)
    report(stage, s, pend, takeover_timeout())
    return 0


def headless_or_owner(stage: str, s: Successor, why: str) -> dict:
    try:
        return s.start_headless(why)
    except hc.Failure as e:
        _release(stage, s.succ, s.k)
        hc.journal_append(stage, s.tag, f"BLOCKED auto-handoff: no successor started ({e}) — waiting for the owner; "
                                        f"handoff {s.handoff}")
        raise


def fallback(stage: str, n: int, why: Optional[str]) -> int:
    """The background successor did not take over in time: journal its log tail, stop it, start a headless one from
    the same handoff (the chain is not counted again). Only for this hub's own successor (hub-<n+1>). Reserved under
    the lock like `hub succeed`, so a retry after a killed run is refused rather than doubled."""
    now = hc.now().isoformat(timespec="seconds")
    with state_lock(stage):
        data = load_state(stage)
        pend = data.get("pending") or {}
        if pend.get("n") != n + 1:
            print(f"auto-handoff: no successor of hub-{n} pending (pending: "
                  f"{'hub-' + str(pend['n']) if pend.get('n') else 'none'}) — nothing to fall back from")
            return 1
        if pend.get("taken_over"):
            print(f"hub-{pend.get('n')} already took over at {pend['taken_over'][:16]} — nothing to fall back from")
            return 0
        if pend.get("kind") in IN_PROGRESS and blocking(pend, n + 1):
            print(f"auto-handoff: hub-{n + 1} is being started right now — {wait_hint(stage, pend)}")
            return 1
        if pend.get("kind") == "headless":
            line = (f"auto-handoff: the headless successor {pend.get('role')} did not take over either — waiting for "
                    "the owner")
            hc.journal_append(stage, f"hub-{n}", line)
            print(line + "; if it is not running: "
                  + wait_hint(stage, dict(pend, at="1970-01-01T00:00:00+00:00")).split("on ALARM: ", 1)[-1])
            return 1
        if pend.get("kind") == "starting" or not pend.get("id"):
            print(f"auto-handoff: the run that was starting hub-{n + 1} died before it started anything — "
                  f"`{tool('hub')} succeed --stage {stage} --handoff {shlex.quote(str(pend.get('handoff', '<the handoff>')))}`")
            return 1
        bg = dict(pend, kind="bg") if pend.get("kind") == "falling-back" else pend  # a stale run of --fallback
        data["pending"] = dict(bg, kind="falling-back", at=now, bg_at=bg.get("bg_at") or bg.get("at"))
        save_state(stage, data)
    timeout_s = takeover_timeout()
    try:
        s = Successor(stage, n, Path(bg["handoff"]), bg["model"], bg.get("mode") or "default",
                      Path(bg.get("cwd") or os.getcwd()), bg.get("k") or data["chain"], chain_limit())
    except hc.Failure:
        _record(stage, n + 1, bg)
        raise
    logs = tail(s.run(["logs", bg["id"]], timeout=30).stdout)
    with state_lock(stage):
        # the successor may have registered while its logs were read: then it is taking over — do not stop it
        rec = hc.roles_load(stage)["roles"].get("hub") or {}
        if rec.get("tag") != f"hub-{n}":
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
