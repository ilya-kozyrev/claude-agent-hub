"""Shared helpers for the hub tools: jlog, jwait, roles, hub, agent, agent-top.

Layout under the hub home (where it is: home(); default ~/agent-hub):
  <stage>/coordinator/work/journal-YYYY-MM-DD.md   stage journal, one line per event:
                                                   "- HH:MM [tag] text" (hub time zone, see below)
  <stage>/roles.json                               role registry (tool `roles`)
  <stage>/agents/<role>/                           headless agents (tool `agent`)
  <stage>/questions.md                             owner-question register (tool `ask`)
  board.md                                         lock board (tool `lock`)
  .jwait-state/<caller>.json                       what jwait has already shown each caller

Time zone: $AGENT_HUB_TZ (an IANA name such as Europe/Berlin), else the system's local zone.
Python 3.10+ stdlib only.
"""
from __future__ import annotations

import datetime as dt
import fcntl
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple, Optional

BIN = Path(os.path.dirname(os.path.realpath(__file__)))
DEFAULT_STAGE = "default"
STAGE_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")
# "- 14:35 [hub-16] text"; the tag may hold spaces ("[qa-2 r5b]").
JOURNAL_LINE_RE = re.compile(r"^- (\d{1,2}:\d{2}) \[([^\]]+)\]\s?(.*)$")
CONFIG_DIRNAME = ".agent-hub"
EFFORTS = ("low", "medium", "high", "xhigh", "max")  # what `claude --effort` takes
MODEL_ALIASES = ("opus", "sonnet", "haiku", "fable")
# The first Claude Code CLI whose aliases resolve to the latest models (sonnet-5-5, opus-5-5, haiku-4-5, fable-5-1);
# an older CLI resolves the same aliases to older models. The plugin pins no ids: the alias follows the CLI.
MIN_CLI_VERSION = (2, 1, 285)
# A full model id, `claude-` plus letters, digits and . _ : @ [ ] - ("claude-opus-4-7[1m]", the Vertex id
# "claude-sonnet-4-5@20250929"): nothing a shell treats as syntax, so an id from a repository's config cannot carry a
# command into a line the hub runs; and a length cap, so a value cannot flood what the hub reads.
MODEL_ID_RE = re.compile(r"claude-[A-Za-z0-9._:@\[\]-]{1,100}")
MODEL_ALIAS_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
# What an alias of AGENT_HUB_MODEL_MAP may stand for: any provider's model id (a Bedrock "us.anthropic.claude-…:0" or
# an inference-profile ARN, a Vertex "…@2025…", a `claude-…` id) — the same characters plus "/", no `claude-` prefix.
MODEL_VALUE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@\[\]/-]{0,199}")
# Settings that only the hub home's config.json may set: every tool sharing a hub home must agree on them.
HUB_WIDE_KEYS = ("AGENT_HUB_TZ", "AGENT_HUB_SEND_CAP", "AGENT_HUB_NIGHT", "AGENT_HUB_HANDOFF_MAX_BYTES",
                 "AGENT_HUB_JWAIT_MATCH", "AGENT_HUB_SCOPE_DIRS")
# Settings a repository's .agent-hub/config.json may set as well (the repository's value wins over the home's).
PROJECT_KEYS = ("AGENT_HUB_MODEL_MAP", "AGENT_HUB_DEFAULT_EFFORT", "AGENT_HUB_PERMISSION_MODE",
                "AGENT_HUB_DEFAULT_REPO", "AGENT_HUB_TAKE_MAIN_MERGE", "CLAUDE_BIN", "AGENT_INIT_TIMEOUT",
                "AGENT_HUB_BG_WAIT_CEILING_MS")
PROJECT_KEYS += ("AGENT_HUB_ENGINE", "CODEX_BIN", "AGENT_HUB_CODEX_MODEL_MAP", "AGENT_HUB_CODEX_DEFAULT_MODEL",
                 "AGENT_HUB_CODEX_PERMISSION_MODE", "AGENT_HUB_CODEX_HOOK_TRUST")
# Yes/no settings: a JSON boolean is accepted for them (read with truthy()).
BOOL_KEYS = ("AGENT_HUB_TAKE_MAIN_MERGE",)
# Status words: what the hub's digest jwait wakes on and what counts as an agent's clean ending.
# $AGENT_HUB_JWAIT_MATCH adds alternatives (a regex) for a team whose scripts or briefs use other words.
STATUS_WORDS = r"\b(MERGED|STOP|DONE|BLOCKED|EXIT|QUESTION)\b|AWAITING ANSWER"
# Agent-discipline hooks (hooks/context_budget.py, polling_guard.py, delegation.py). The user's own limits —
# context budget and the delegation dial — come from the hub home only, so a cloned repository cannot loosen them;
# the polling guard is a team convention a repository may set; a repository's effort rules apply in addition to the
# user's, never instead (bin/subagent_rules.py evaluates both).
HUB_WIDE_KEYS += ("AGENT_HUB_CONTEXT_BUDGET", "AGENT_HUB_CONTEXT_WARN", "AGENT_HUB_CONTEXT_WARN_STEP",
                  "AGENT_HUB_CONTEXT_BLOCK", "AGENT_HUB_CONTEXT_BLOCK_TOOLS", "AGENT_HUB_CONTEXT_ESCAPE",
                  "AGENT_HUB_CONTEXT_TODO",
                  "AGENT_HUB_DELEGATION", "AGENT_HUB_DELEGATION_DEFAULT", "AGENT_HUB_DELEGATION_LEVELS",
                  "AGENT_HUB_DELEGATION_COMMON", "AGENT_HUB_DELEGATION_RULES",
                  "AGENT_HUB_STATE_DIR")
PROJECT_KEYS += ("AGENT_HUB_POLL_GUARD", "AGENT_HUB_POLL_MAX_SLEEP", "AGENT_HUB_POLL_MAX_BOUNDED_WAIT",
                 "AGENT_HUB_POLL_ESCAPE", "AGENT_HUB_CI_STATUS_DENY", "AGENT_HUB_CI_STATUS_ALLOW",
                 "AGENT_HUB_WAIT_HINT", "AGENT_HUB_EFFORT_RULES")
# Reviewers (bin/reviewers.py): the list, and the model and effort of a built-in `agent` reviewer. A repository may
# set them all; a `check` command in a repository's list is never run (see reviewers.py).
PROJECT_KEYS += ("AGENT_HUB_REVIEWERS", "AGENT_HUB_REVIEW_MODEL", "AGENT_HUB_REVIEW_EFFORT")
BOOL_KEYS += ("AGENT_HUB_CONTEXT_BUDGET", "AGENT_HUB_POLL_GUARD", "AGENT_HUB_DELEGATION")
# Autopilot (bin/autopilot.py): hub home only — a cloned repository must not start background sessions or choose their
# permission mode.
HUB_WIDE_KEYS += ("AGENT_HUB_AUTO_HANDOFF", "AGENT_HUB_AUTO_HANDOFF_CHAIN", "AGENT_HUB_SUCCESSOR_MODEL",
                  "AGENT_HUB_SUCCESSOR_PERMISSION_MODE", "AGENT_HUB_SUCCESSOR_TIMEOUT")
HUB_WIDE_KEYS += ("AGENT_HUB_SUCCESSOR_ENGINE",)
BOOL_KEYS += ("AGENT_HUB_AUTO_HANDOFF",)
# Settings whose config.json value may be a JSON list or object; setting() returns it as a JSON string and
# setting_json() parses it (the environment variable holds the same JSON text).
JSON_KEYS = ("AGENT_HUB_CONTEXT_BLOCK_TOOLS", "AGENT_HUB_DELEGATION_LEVELS", "AGENT_HUB_DELEGATION_RULES",
             "AGENT_HUB_EFFORT_RULES", "AGENT_HUB_CI_STATUS_DENY", "AGENT_HUB_CI_STATUS_ALLOW", "AGENT_HUB_REVIEWERS")
JSON_KEYS += ("AGENT_HUB_CODEX_MODEL_MAP",)


# ---------------------------------------------------------------- the hub home
#
# Where the hub keeps its files (journals, inboxes, the question register, the lock board, handoffs), most specific
# first:
#   1. $AGENT_HUB_HOME — any path (the user's shell, or `env` of their Claude Code settings); every child the tools
#      start gets it set to the parent's resolved home, so parent and children never resolve differently;
#   2. the project layer: AGENT_HUB_HOME in <repo>/.agent-hub/config.json, "project" (<main checkout>/.agent-hub/local/,
#      shared by every worktree of the repository) or "user" (3-4) — nothing else: a cloned repository must not choose
#      arbitrary paths the tools write to;
#   3. the user default ~/agent-hub;
#   4. legacy: ~/.claude/agent-hub while ~/agent-hub does not exist (the default before 0.7). Claude Code protects
#      .claude directories: an edit there is prompted (or classified, or denied) whatever the allow rules say, and the
#      Bash sandbox refuses writes there — `hub home migrate` moves it.
# Hooks resolve for the session's directory (use_cwd with the hook input's cwd), the tools for their working directory.

HOME_KEY = "AGENT_HUB_HOME"
HOME_CHOICES = ("project", "user")
LOCAL_HOME = "local"  # <main checkout>/.agent-hub/local/


class Home(NamedTuple):
    path: Path
    layer: str  # "env", "project", "user" (the project layer chose the user default), "default", "legacy"
    source: str  # what chose it, for `hub home`


def user_home() -> Path:
    return Path.home() / "agent-hub"


def legacy_home() -> Path:
    return Path.home() / ".claude" / "agent-hub"


_SESSION_CWD: Optional[str] = None
_HOME_CACHE: dict = {}
_HOME_WARNED: set = set()
_STAGE_GUARD = True
_STAGE_SEEN: set = set()


def use_cwd(cwd, stage_guard: bool = False) -> None:
    """For a hook: resolve the hub home (and the settings of the home layer) for the session's directory — the hook
    input's `cwd` — instead of the process's. A hook never raises over a stage found in another home (stage_guard)."""
    global _SESSION_CWD, _STAGE_GUARD, TZ, TZ_LABEL
    _SESSION_CWD = str(cwd) if isinstance(cwd, str) and cwd else None
    _STAGE_GUARD = stage_guard
    _HOME_CACHE.clear()
    _STAGE_SEEN.clear()
    TZ = _zone()
    TZ_LABEL = dt.datetime.now(TZ).strftime("%Z") or "local"


def _git_top(d: Path) -> Optional[Path]:
    for p in [d] + list(d.parents):
        if (p / ".git").exists():
            return p
    return None


def project_home(proj: Path) -> Path:
    """The "project" hub home of the repository whose .agent-hub/ is in `proj`: under the main checkout (a linked
    worktree with its own committed .agent-hub/ still shares the main checkout's), <…>/.agent-hub/local/."""
    top = _git_top(proj)
    if top is None:
        return proj / CONFIG_DIRNAME / LOCAL_HOME
    main = (main_checkout(top) if (top / ".git").is_file() else None) or top
    return main / proj.relative_to(top) / CONFIG_DIRNAME / LOCAL_HOME


def _exclude_project_home(home: Path) -> None:
    """Add the project home to the main checkout's .git/info/exclude once (like .worktrees/), so it never shows as
    untracked. Best effort: a read-only .git costs a note, never a tool."""
    top = _git_top(home.parent.parent)
    if top is None or not (top / ".git").is_dir():
        return
    line = "/" + home.relative_to(top).as_posix() + "/"
    exclude = top / ".git" / "info" / "exclude"
    try:
        lines = exclude.read_text(encoding="utf-8").splitlines() if exclude.exists() else []
        if line in lines:
            return
        exclude.parent.mkdir(parents=True, exist_ok=True)
        with open(exclude, "a", encoding="utf-8") as fh:
            fh.write(("" if not lines or lines[-1] == "" else "\n") + line + "\n")
    except OSError as e:
        _warn(f"could not add {line} to {exclude}: {e}")


def home(cwd=None) -> Home:
    """The hub home and the layer that chose it (see the order above). `cwd`: the directory whose repository's
    .agent-hub/config.json counts (default: the hook's session directory, else the working directory)."""
    raw = os.environ.get(HOME_KEY)
    if raw:
        # absolute: a relative value pinned into a child in another directory would name another home
        return Home(Path(raw).expanduser().absolute(), "env", "the environment ($AGENT_HUB_HOME)")
    start = cwd or _SESSION_CWD
    if start is None:
        try:
            start = os.getcwd()
        except OSError:
            start = None
    key = str(start)
    if key in _HOME_CACHE:
        return _HOME_CACHE[key]
    proj = project_dir(start) if start else None
    choice, cfg = None, None
    if proj:
        cfg = proj / CONFIG_DIRNAME / "config.json"
        val = read_config(cfg, project=True).get(HOME_KEY)
        if val in HOME_CHOICES:
            choice = val
        elif val and (str(cfg), val) not in _HOME_WARNED:
            _HOME_WARNED.add((str(cfg), val))
            _warn(f"{cfg}: AGENT_HUB_HOME={val[:80]!r} ignored — a repository chooses only \"project\" or \"user\" "
                  "(another path: set AGENT_HUB_HOME in the environment)")
    if choice == "project":
        path = project_home(proj)
        _exclude_project_home(path)
        out = Home(path, "project", f'{cfg}: AGENT_HUB_HOME "project"')
    else:
        user, legacy = user_home(), legacy_home()
        if not user.exists() and legacy.is_dir():
            out = Home(legacy, "legacy", "the legacy default: ~/agent-hub does not exist, ~/.claude/agent-hub does")
        elif choice == "user":
            out = Home(user, "user", f'{cfg}: AGENT_HUB_HOME "user" (the user default)')
        else:
            out = Home(user, "default", "the user default (~/agent-hub)")
    _HOME_CACHE[key] = out
    return out


def root(cwd=None) -> Path:
    """The hub home's path (home())."""
    return home(cwd).path


def is_protected(path) -> bool:
    """Whether `path` lies under a directory named .claude, which Claude Code protects from edits."""
    return ".claude" in Path(path).expanduser().parts


def under(path, parent) -> bool:
    """Whether `path` is `parent` or inside it (both resolved)."""
    try:
        p, d = Path(path).expanduser().resolve(), Path(parent).expanduser().resolve()
    except (OSError, ValueError, RuntimeError):
        return False
    return p == d or d in p.parents


def stage_elsewhere(stage: str) -> Optional[Path]:
    """Another home (the user default, the legacy one) that has this stage while the resolved home does not."""
    here = root()
    if (here / stage).is_dir():
        return None
    for other in dict.fromkeys((user_home(), legacy_home())):
        if not under(other, here) and not under(here, other) and (other / stage).is_dir():
            return other
    return None


# ---------------------------------------------------------------- configuration
#
# One mechanism, three layers of the same directory shape (most specific first):
#   <hub home>/<stage>/          stage layer   (files only)
#   <repo>/.agent-hub/           project layer (found from the working directory, see project_dir)
#   <hub home>/                  home layer
# Files: config.json (settings, see setting()), lock-rules.json (the lock hook; project + home rules
# together), brief-footer.md, handoff-facts.sh, takeover.sh (first layer that has the file wins).

def project_dir(start=None) -> Optional[Path]:
    """The directory holding `.agent-hub/`, searched upwards from `start` (default: the working directory)
    up to the enclosing git root; None outside such a repository."""
    try:
        p = Path(start or os.getcwd()).expanduser().resolve()
    except (OSError, ValueError):
        return None
    for d in [p] + list(p.parents):
        if (d / CONFIG_DIRNAME).is_dir():
            return d
        if (d / ".git").is_file():
            # a linked worktree without its own .agent-hub/ (not committed, or not yet) uses the main checkout's:
            # a guard configured there must not vanish in an agent's worktree
            main = main_checkout(d)
            return main if main is not None and (main / CONFIG_DIRNAME).is_dir() else None
        if (d / ".git").exists():
            return None
    return None


def main_checkout(worktree: Path) -> Optional[Path]:
    """The main working tree of a linked worktree (its `.git` file names a gitdir with a `commondir`); None for
    anything else, a submodule included."""
    try:
        m = re.match(r"gitdir:\s*(.+)", (worktree / ".git").read_text(encoding="utf-8").strip())
        if not m:
            return None
        gitdir = Path(m.group(1).strip())
        gitdir = gitdir if gitdir.is_absolute() else (worktree / gitdir)
        common = (gitdir / (gitdir / "commondir").read_text(encoding="utf-8").strip()).resolve()
    except (OSError, ValueError):
        return None
    return common.parent if common.name == ".git" else None


def git_repo_name(path) -> Optional[str]:
    """Name of the git repository enclosing `path` (a `.git` directory or file found upwards from it); a worktree
    resolves to its main repository. None outside any repository. The board hook names the repository of a command
    this way, so a lock taken with this name is matched there."""
    try:
        p = Path(os.path.abspath(os.path.expanduser(str(path))))
    except (OSError, ValueError):
        return None
    for d in [p] + list(p.parents):
        g = d / ".git"
        if g.is_dir():
            return d.name
        if g.is_file():  # a worktree or submodule: "gitdir: <main>/.git/worktrees/<name>"
            try:
                m = re.match(r"gitdir:\s*(.+)", g.read_text(encoding="utf-8").strip())
            except OSError:
                return d.name
            if m:
                gitdir = Path(m.group(1).strip())
                if not gitdir.is_absolute():
                    gitdir = (d / gitdir).resolve()
                parts = gitdir.parts
                if ".git" in parts:
                    return parts[parts.index(".git") - 1]
            return d.name
    return None


def default_repo(cwd=None) -> Optional[str]:
    """The repository a lock taken from `cwd` guards: AGENT_HUB_DEFAULT_REPO (env, the project's config.json, the hub
    home's), else the name of the git repository enclosing `cwd` (a worktree resolves to its main repository), else
    None: the caller falls back to "*" (every repository) only outside any checkout."""
    return setting("AGENT_HUB_DEFAULT_REPO", cwd=cwd) or git_repo_name(cwd or os.getcwd())


def in_scope(path) -> bool:
    """Whether the plugin's session-wide hooks (handoff size, the owner-questions line) apply at `path`: inside the
    hub home, inside a repository with `.agent-hub/`, or under a directory of AGENT_HUB_SCOPE_DIRS (paths separated
    by ':', `~` expanded). Elsewhere a session on the same machine is left alone."""
    try:
        p = Path(path).expanduser().resolve()
    except (OSError, ValueError, TypeError):
        return False
    dirs = [root()]
    for d in (setting("AGENT_HUB_SCOPE_DIRS") or "").split(":"):
        if d.strip():
            try:
                full = Path(d.strip()).expanduser()  # ~unknownuser raises RuntimeError
            except RuntimeError as e:
                _warn(f"AGENT_HUB_SCOPE_DIRS: {d.strip()!r}: {e}; ignored")
                continue
            if not full.is_absolute():
                _warn(f"AGENT_HUB_SCOPE_DIRS: {d.strip()!r} is not an absolute path (or ~/…); ignored")
                continue
            dirs.append(full)
    for d in dirs:
        try:
            if p == d.resolve() or d.resolve() in p.parents:
                return True
        except OSError:
            continue
    return project_dir(p if p.is_dir() else p.parent) is not None


def git_env() -> dict:
    """The environment for the tools' own git calls: without GIT_DIR / GIT_WORK_TREE (a dotfiles setup exports them),
    so git answers about the directory it is pointed at — the way project_dir and the hook walk the filesystem."""
    return {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE")}


def config_dirs(stage: Optional[str] = None, cwd=None) -> list:
    """Existing config layers, most specific first: <home>/<stage>/, <project>/.agent-hub/, <home>/."""
    out = []
    if stage:
        out.append(root() / stage)
    proj = project_dir(cwd)
    if proj:
        out.append(proj / CONFIG_DIRNAME)
    out.append(root())
    return [d for d in out if d.is_dir()]


def config_file(name: str, stage: Optional[str] = None, cwd=None) -> Optional[Path]:
    """The first layer's copy of a config file (brief-footer.md, handoff-facts.sh, takeover.sh), or None."""
    for d in config_dirs(stage, cwd):
        if (d / name).is_file():
            return d / name
    return None


_CONFIG_CACHE: dict = {}


def _warn(msg: str) -> None:
    print(f"agent-hub: {msg}", file=sys.stderr)


warn = _warn  # for the tools that report a bad setting themselves (bin/reviewers.py, `hub reviewer`)


def read_config(path: Path, project: bool) -> dict:
    """Settings of one config.json as {NAME: str}. A broken file or a key the layer may not set is reported on
    stderr and ignored, so a typo never stops a tool (but never passes silently either)."""
    key = (str(path), project)
    if key in _CONFIG_CACHE:
        return _CONFIG_CACHE[key]
    out: dict = {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("not a JSON object")
    except FileNotFoundError:
        data = {}
    except (OSError, ValueError) as e:
        _warn(f"{path} ignored: {e}")
        data = {}
    allowed = PROJECT_KEYS + (HOME_KEY,) if project else PROJECT_KEYS + HUB_WIDE_KEYS
    for name, value in data.items():
        if name.startswith("_"):  # "_comment" and the like
            continue
        if name not in allowed:
            hint = (" (hub-wide: set it in the hub home's config.json)" if name in HUB_WIDE_KEYS else
                    " (the environment or a repository's .agent-hub/config.json chooses the hub home)"
                    if name == HOME_KEY else "")
            _warn(f"{path}: {name} is not a setting this file may set{hint}; ignored")
            continue
        if name in JSON_KEYS and isinstance(value, (list, dict)):
            out[name] = json.dumps(value, ensure_ascii=False)
            continue
        if isinstance(value, dict):  # {"sonnet": "claude-…"} for AGENT_HUB_MODEL_MAP
            value = ",".join(f"{k}={v}" for k, v in value.items())
        if isinstance(value, bool):  # a JSON boolean: "true" / "false", what truthy() reads
            if name not in BOOL_KEYS:
                _warn(f"{path}: {name} is not a yes/no setting (true/false); ignored")
                continue
            value = "true" if value else "false"
        if not isinstance(value, (str, int, float)):
            _warn(f"{path}: {name} must be a string or a number; ignored")
            continue
        out[name] = str(value)
    _CONFIG_CACHE[key] = out
    return out


def setting_origin(name: str, default: Optional[str] = None, cwd=None) -> tuple:
    """(value, origin) of a setting, origin one of "env", "project", "home", "default": which layer supplied it.
    A setting whose meaning depends on who wrote it (a command a repository must not run) asks for it."""
    raw = os.environ.get(name)
    if raw:
        return raw, "env"
    if name in PROJECT_KEYS:
        proj = project_dir(cwd)
        if proj:
            val = read_config(proj / CONFIG_DIRNAME / "config.json", project=True).get(name)
            if val:
                return val, "project"
    val = read_config(root() / "config.json", project=False).get(name)
    return (val, "home") if val else (default, "default")


def setting(name: str, default: Optional[str] = None, cwd=None) -> Optional[str]:
    """$NAME if set and non-empty, else the project's .agent-hub/config.json (for PROJECT_KEYS; the project is
    found from `cwd`, default the working directory), else <hub home>/config.json, else `default`."""
    return setting_origin(name, default, cwd)[0]


def setting_json(name: str, default=None, cwd=None):
    """A JSON_KEYS setting parsed (list or object). A value that does not start like JSON ([ { ") is returned as the
    plain string (e.g. "Agent,SendMessage" from the environment); broken JSON is reported on stderr and gives
    `default`."""
    raw = setting(name, cwd=cwd)
    if not raw:
        return default
    if not raw.lstrip().startswith(("[", "{", '"')):
        return raw
    try:
        return json.loads(raw)
    except ValueError as e:
        _warn(f"{name}: not valid JSON ({e}); using the default")
        return default


def _zone() -> dt.tzinfo:
    name = (setting("AGENT_HUB_TZ") or "").strip()
    if name:
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(name)
        except Exception:  # noqa: BLE001 — an unknown zone name falls back to local time
            print(f"agent-hub: unknown AGENT_HUB_TZ {name!r}, using local time", file=sys.stderr)
    return dt.datetime.now().astimezone().tzinfo


TZ = _zone()
TZ_LABEL = dt.datetime.now(TZ).strftime("%Z") or "local"
DEFAULT_MESSAGE_CAP = 10


_MAP_WARNED: set = set()


def model_map(cwd=None) -> dict:
    """Alias -> full id from AGENT_HUB_MODEL_MAP ("sonnet=claude-…,opus=claude-…"; env, else the agent's repo
    .agent-hub/config.json, else the hub home's config.json); empty = pass aliases through. A pair whose alias or
    id has characters outside MODEL_ALIAS_RE / MODEL_VALUE_RE is reported once and left out: what a repository's
    config maps an alias to goes into the agent's command line and its journal."""
    out = {}
    for part in (setting("AGENT_HUB_MODEL_MAP", cwd=cwd) or "").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            k, v = k.strip(), v.strip()
            if not (k and v):
                continue
            if not (MODEL_ALIAS_RE.fullmatch(k) and MODEL_VALUE_RE.fullmatch(v)):
                if (k, v) not in _MAP_WARNED:
                    _MAP_WARNED.add((k, v))
                    _warn(f"AGENT_HUB_MODEL_MAP: {k[:30]!r}={v[:30]!r}{'…' if len(v) > 30 else ''} is not an alias "
                          "and a model id (letters, digits and . _ : @ [ ] / - only); left out")
                continue
            out[k] = v
    return out


def model_problem(model, cwd=None) -> Optional[str]:
    """None when `agent spawn --model` takes `model`: an alias (opus, sonnet, haiku, fable), an alias of
    AGENT_HUB_MODEL_MAP, or a full id claude-… — and in each case only the characters above; else the reason."""
    if not isinstance(model, str) or not model:
        return "not a model name"
    if model in MODEL_ALIASES:
        return None
    if MODEL_ALIAS_RE.fullmatch(model) and model in model_map(cwd):
        return None
    if MODEL_ID_RE.fullmatch(model):
        return None
    return (f"one of {', '.join(MODEL_ALIASES)}, an alias from AGENT_HUB_MODEL_MAP, or a full id claude-… "
            "(letters, digits and . _ : @ [ ] - only)")


def int_setting(name: str, default: int, minimum: int = 1) -> int:
    """An integer setting; a value that is not a whole number >= minimum is reported on stderr and replaced by the
    default (a typo in config.json must not break every tool at import)."""
    raw = setting(name)
    if raw is None or raw == "":
        return default
    try:
        val = int(str(raw).strip())
        if val < minimum:
            raise ValueError
        return val
    except ValueError:
        _warn(f"{name}={raw!r} is not a whole number >= {minimum}; using {default}")
        return default


def message_cap() -> int:
    """Claude Desktop pauses a session's outgoing cross-session sends after this many messages without the user
    typing in it; `roles` counts sends against it. $AGENT_HUB_SEND_CAP (hub-wide), default 10."""
    return int_setting("AGENT_HUB_SEND_CAP", DEFAULT_MESSAGE_CAP)


def __getattr__(name: str):
    # MESSAGE_CAP is read when used, not at import: a bad value then costs a warning, not every tool.
    if name == "MESSAGE_CAP":
        return message_cap()
    raise AttributeError(name)


def status_pattern(exit_word: bool = True) -> str:
    """STATUS_WORDS plus $AGENT_HUB_JWAIT_MATCH (hub-wide), if set and a valid regex. exit_word=False leaves out
    EXIT (the line `agent` itself writes when a run ends without a status word)."""
    extra = (setting("AGENT_HUB_JWAIT_MATCH") or "").strip()
    if extra:
        try:
            re.compile(extra)
        except re.error as e:
            _warn(f"AGENT_HUB_JWAIT_MATCH is not a valid regex ({e}); ignored")
            extra = ""
    base = STATUS_WORDS if exit_word else STATUS_WORDS.replace("|EXIT", "")
    return f"{base}|{extra}" if extra else base


def truthy(raw: Optional[str]) -> bool:
    return (raw or "").strip().lower() in ("1", "true", "yes", "on")


def child_env(extra: Optional[dict] = None) -> dict:
    """Environment for calling the sibling tools and the agents: the resolved home pinned in $AGENT_HUB_HOME (a child
    in another directory must not resolve another one), this bin/ first on PATH and in $HUB_BIN."""
    env = dict(os.environ)
    env["AGENT_HUB_HOME"] = str(root())
    env["PATH"] = str(BIN) + os.pathsep + env.get("PATH", "")
    env["HUB_BIN"] = str(BIN)  # for a brief written by an older run: rebuilt at every spawn and resume, so it follows updates
    if extra:
        env.update(extra)
    return env


def add_dir_args(cwd) -> list:
    """`--add-dir <hub home>` for a CLI started in `cwd`, unless the home is under it: the session may then read and
    write the hub's files without a prompt, and the Bash sandbox lets its tools write there."""
    h = root()
    return [] if under(h, cwd) else ["--add-dir", str(h)]


# ---------------------------------------------------------------- the CLI and the PATH

# `claude --version` prints "<version> (Claude Code)". A wrapper (a version manager's shim) may print other lines with
# other version numbers first: take the line in that format, else a last line that starts with a version.
_CLI_VERSION_RE = re.compile(r"^\s*(\d+)\.(\d+)\.(\d+)\s+\(Claude Code\)\s*$", re.M)
_LEADING_VERSION_RE = re.compile(r"^\s*v?(\d+)\.(\d+)\.(\d+)(?![\w.])")
_VERSION_CACHE: dict = {}
VERSION_TIMEOUT = 5  # seconds `<cli> --version` may take; a hanging shim must not stall every spawn


def parse_version(text) -> Optional[tuple]:
    text = str(text or "")
    m = _CLI_VERSION_RE.search(text)
    if not m:
        lines = [ln for ln in text.splitlines() if ln.strip()]
        m = _LEADING_VERSION_RE.match(lines[-1]) if lines else None
    return tuple(int(x) for x in m.groups()) if m else None


def fmt_version(v) -> str:
    return ".".join(str(x) for x in v)


def state_dir() -> Path:
    """<hub home>/.state, or $AGENT_HUB_STATE_DIR (hub-wide)."""
    raw = setting("AGENT_HUB_STATE_DIR")
    return Path(raw).expanduser() if raw else root() / ".state"


def _version_cache_file() -> Path:
    return state_dir() / "cli-version" / "cache.json"


def cli_version(path: str, cwd=None, persist: bool = True) -> Optional[tuple]:
    """`<path> --version` parsed as (major, minor, patch); None when the CLI does not run, takes longer than
    VERSION_TIMEOUT or prints no version. Cached per process, and on disk by path, size and modification time (a CLI
    update changes them): a spawn costs no extra process. A failure is cached for the process only. The disk cache is
    read always and written only when `persist` and the hub home exists (a dry run writes nothing)."""
    if path in _VERSION_CACHE:
        return _VERSION_CACHE[path]
    try:
        st = os.stat(shutil.which(path) or path)
        stamp = {"mtime_ns": st.st_mtime_ns, "size": st.st_size}
    except OSError:
        stamp = None
    cache_file, disk = _version_cache_file(), {}
    if stamp:
        try:
            disk = json.loads(cache_file.read_text(encoding="utf-8"))
            hit = disk.get(path) if isinstance(disk, dict) else None
            if isinstance(hit, dict) and hit.get("mtime_ns") == stamp["mtime_ns"] and hit.get("size") == stamp["size"]:
                v = parse_version(hit.get("version"))
                if v:
                    _VERSION_CACHE[path] = v
                    return v
        except (OSError, ValueError):
            disk = {}
    try:
        res = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=VERSION_TIMEOUT,
                             stdin=subprocess.DEVNULL, cwd=str(cwd) if cwd else None)
        version = parse_version(res.stdout) if res.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        version = None
    _VERSION_CACHE[path] = version
    if version and stamp and persist and root().is_dir():
        disk = disk if isinstance(disk, dict) else {}
        disk.pop(path, None)
        disk[path] = dict(stamp, version=fmt_version(version))
        try:
            atomic_write(cache_file, json.dumps(dict(list(disk.items())[-20:]), indent=1) + "\n")
        except OSError:
            pass
    return version


def desktop_cli() -> Optional[tuple]:
    """(version, path) of the newest CLI bundled with Claude Desktop on macOS (the directory name is the version);
    None when there is none."""
    base = Path.home() / "Library/Application Support/Claude/claude-code"
    found = []
    for d in base.glob("*/claude.app/Contents/MacOS/claude"):
        v = parse_version(d.parents[3].name)
        if v:
            found.append((v, str(d)))
    return max(found) if found else None


class Cli(NamedTuple):
    path: str
    version: Optional[tuple]
    how: str  # why this one

    def describe(self) -> str:
        return f"{self.path} ({fmt_version(self.version) if self.version else 'version unknown'}; {self.how})"


def find_claude(cwd=None, persist: bool = True) -> Optional[Cli]:
    """The CLI the tools start. $CLAUDE_BIN (a path or a name on PATH; `desktop` = the newest CLI bundled with Claude
    Desktop, which survives Desktop updates) wins. Otherwise the newer of `claude` on PATH and the newest bundled with
    Claude Desktop: an old `claude` on PATH must not hold the agents back on old models (PATH keeps a tie and a
    version it cannot read). None when there is no CLI at all. persist=False: do not write the version cache."""
    b = setting("CLAUDE_BIN", cwd=cwd)
    if b and b.strip().lower() == "desktop":
        app = desktop_cli()
        if not app:
            raise Failure("CLAUDE_BIN=desktop, but no CLI bundled with Claude Desktop was found under "
                          f"{Path.home() / 'Library/Application Support/Claude/claude-code'}")
        return Cli(app[1], app[0], "CLAUDE_BIN=desktop")
    if b:
        return Cli(b, cli_version(b, cwd, persist), "CLAUDE_BIN")
    on_path, app = shutil.which("claude"), desktop_cli()
    if on_path:
        pv = cli_version(on_path, cwd, persist)
        if app and pv is not None and app[0] > pv:
            return Cli(app[1], app[0], f"the newest bundled with Claude Desktop; `claude` on PATH is older: "
                                       f"{on_path} {fmt_version(pv)}")
        return Cli(on_path, pv, "claude on PATH" + (f"; the Claude Desktop bundle is {fmt_version(app[0])}"
                                                    if app and app[0] != pv else ""))
    return Cli(app[1], app[0], "bundled with Claude Desktop; no claude on PATH") if app else None


def cli_warning(cli: Optional[Cli]) -> Optional[str]:
    """One line when the chosen CLI is older than MIN_CLI_VERSION, else None."""
    if cli is None or cli.version is None or cli.version >= MIN_CLI_VERSION:
        return None
    return (f"Claude Code {fmt_version(cli.version)} ({cli.path}) is older than {fmt_version(MIN_CLI_VERSION)}: update "
            "Claude Code; with an older CLI the aliases (opus, sonnet, haiku, fable) resolve to older models "
            "(pin ids with AGENT_HUB_MODEL_MAP if you must stay on it)")


def plugin_tools() -> list:
    """The plugin's commands: every executable file of this bin/ without an extension (the .py files are modules)."""
    try:
        return sorted(p.name for p in BIN.iterdir() if "." not in p.name and p.is_file() and os.access(p, os.X_OK))
    except OSError:
        return []


# A personal wrapper that dispatches into the plugin (a shim in ~/.local/bin that picks the newest installed `bin/`)
# says so with this comment line near the top of its file; the shadow check then treats it as the plugin's own.
DISPATCHER_MARKER = "# agent-hub: dispatcher"


def installed_plugin_bins() -> list:
    """Real paths of the installed agent-hub plugin `bin/` directories: the Claude and Codex plugin caches
    (`<config>/plugins/cache/*/agent-hub/*/bin`) and a marketplace folder that is the plugin itself
    (`<config>/plugins/marketplaces/*/bin` holding hubcore.py), of $CLAUDE_CONFIG_DIR / ~/.claude and
    $CODEX_HOME / ~/.codex."""
    home = Path.home()
    out = []
    for config in (Path(os.environ.get("CLAUDE_CONFIG_DIR") or home / ".claude"),
                   Path(os.environ.get("CODEX_HOME") or home / ".codex")):
        plugins = config / "plugins"
        found = list(plugins.glob("cache/*/agent-hub/*/bin")) + [
            d for d in plugins.glob("marketplaces/*/bin") if (d / "hubcore.py").is_file()]
        out += [os.path.realpath(d) for d in found]
    return out


def is_dispatcher(path) -> bool:
    """Whether the file `path` (symlinks resolved) carries the DISPATCHER_MARKER line among its first lines."""
    try:
        with open(os.path.realpath(path), "rb") as fh:
            head = fh.read(2048).decode("utf-8", "replace")
    except OSError:
        return False
    return any(line.strip() == DISPATCHER_MARKER for line in head.splitlines()[:10])


def shadowed_tools(path=None) -> list:
    """[(tool, path found)] for each of the plugin's commands (plugin_tools) that PATH resolves to a file that is not
    the plugin's own (`command -v`: the first match on PATH). Ours: a file whose real path is in this bin/ (a symlink
    into it counts) or in an installed agent-hub plugin's bin/ (installed_plugin_bins), or a personal dispatcher that
    carries the DISPATCHER_MARKER line (is_dispatcher)."""
    path = os.environ.get("PATH", "") if path is None else path
    out = []
    installed = None
    for name in plugin_tools():
        found = shutil.which(name, path=path)
        if not found:
            continue
        folder = os.path.dirname(os.path.realpath(found))
        if folder == str(BIN):
            continue
        if installed is None:
            installed = installed_plugin_bins()
        if folder in installed or is_dispatcher(found):
            continue
        out.append((name, found))
    return out


def shadow_warning(shadowed: list) -> Optional[str]:
    """One line naming every shadowing path and the fix, or None."""
    if not shadowed:
        return None
    names = ", ".join(f"`{n}` is {p}" for n, p in shadowed)
    return (f"{names} — not the plugin's own tool in {BIN}. A same-named command earlier on PATH answers instead "
            "(GitHub CLI `hub` from Homebrew is the usual one): put the plugin's bin/ first on PATH, or remove the old "
            f"tool; until then call the plugin's tools by absolute path ({BIN}/<tool>)")


def sessions_dir() -> Path:
    """Claude Desktop session metadata (macOS); override with $CLAUDE_SESSIONS_DIR."""
    raw = os.environ.get("CLAUDE_SESSIONS_DIR")
    return Path(raw) if raw else Path.home() / "Library" / "Application Support" / "Claude" / "claude-code-sessions"


def now() -> dt.datetime:
    return dt.datetime.now(TZ)


def default_stage() -> str:
    return os.environ.get("HUB_STAGE") or DEFAULT_STAGE


def check_stage(stage: str) -> str:
    """The stage name, checked; and the stage must not live in another hub home than the resolved one (a stage split
    across two homes loses half its journal): Failure naming where it is."""
    if not STAGE_RE.fullmatch(stage or ""):
        raise UsageError(f"bad stage name {stage!r} (lowercase letters, digits, '-' and '_')")
    if _STAGE_GUARD and stage not in _STAGE_SEEN:
        other = stage_elsewhere(stage)
        if other is not None:
            h = home()
            # the whole-home move fits only legacy -> the user default; into another home (a project's) it would carry
            # every other project's stages along
            move = ("move the old home with `hub home migrate`" if under(other, legacy_home())
                    and under(h.path, user_home()) else
                    f"move the stage (`mv {other / stage} {h.path}/`; its records keep the old paths)")
            raise Failure(f"stage {stage} is not in the hub home {h.path} ({h.source}) but in {other}: {move}, or work "
                          f"there with AGENT_HUB_HOME={other}; to start the stage afresh here, `mkdir -p {h.path / stage}`")
        _STAGE_SEEN.add(stage)
    return stage


class UsageError(Exception):
    """Bad arguments: exit 2."""


class Failure(Exception):
    """A step failed: exit 1."""


# ---------------------------------------------------------------- time

def parse_deadline(raw: str, base: Optional[dt.datetime] = None) -> dt.datetime:
    """'HH:MM' (hub time zone; a time already past today means tomorrow), ISO datetime (naive = hub zone)."""
    base = base or now()
    raw = raw.strip()
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", raw)
    if m:
        t = base.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
        if t <= base:
            t += dt.timedelta(days=1)
        return t
    try:
        t = dt.datetime.fromisoformat(raw)
    except ValueError:
        raise UsageError(f"cannot parse time {raw!r}: use HH:MM or 2026-09-29T20:23") from None
    return (t.replace(tzinfo=TZ) if t.tzinfo is None else t).astimezone(TZ)


def parse_duration(raw: str) -> dt.timedelta:
    """'90s', '30m', '6h', '1h30m', '2d'."""
    parts = re.findall(r"(\d+)([smhd])", raw.strip())
    if not parts or "".join(n + u for n, u in parts) != raw.strip():
        raise UsageError(f"cannot parse duration {raw!r}: use 90s, 30m, 6h, 1h30m")
    secs = sum(int(n) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[u] for n, u in parts)
    return dt.timedelta(seconds=secs)


def age(t: Optional[dt.datetime], at: Optional[dt.datetime] = None) -> str:
    if t is None:
        return "—"
    s = int(((at or now()) - t).total_seconds())
    if s < 0:
        s = 0
    if s < 90:
        return f"{s} s"
    if s < 90 * 60:
        return f"{s // 60} min"
    if s < 48 * 3600:
        return f"{s // 3600} h {s % 3600 // 60:02d} min"
    return f"{s // 86400} d"


# ---------------------------------------------------------------- files

def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        if path.exists():
            os.chmod(tmp, path.stat().st_mode & 0o777)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class Flock:
    def __init__(self, path: Path):
        self.path = path

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(self.path, "a")
        fcntl.flock(self.fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        fcntl.flock(self.fh, fcntl.LOCK_UN)
        self.fh.close()


# ---------------------------------------------------------------- journal

def work_dir(stage: str) -> Path:
    return root() / check_stage(stage) / "coordinator" / "work"


def journal_path(stage: str, day: Optional[dt.date] = None) -> Path:
    day = day or now().date()
    return work_dir(stage) / f"journal-{day.isoformat()}.md"


def one_line(text: str) -> str:
    return " ".join(text.split())


def journal_append(stage: str, tag: str, text: str) -> str:
    """Append '- HH:MM [tag] text' to today's journal; return the line."""
    text, tag = one_line(text), one_line(tag)
    if not text:
        raise UsageError("empty text")
    if not tag or "]" in tag or "[" in tag:
        raise UsageError(f"bad tag {tag!r}")
    t = now()
    line = f"- {t:%H:%M} [{tag}] {text}"
    path = journal_path(stage, t.date())
    path.parent.mkdir(parents=True, exist_ok=True)
    with Flock(path.parent / ".journal.lock"):
        prefix = ""
        try:
            with open(path, "rb") as fh:
                fh.seek(0, os.SEEK_END)
                if fh.tell() > 0:
                    fh.seek(-1, os.SEEK_END)
                    if fh.read(1) != b"\n":
                        prefix = "\n"
        except FileNotFoundError:
            pass
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, (prefix + line + "\n").encode("utf-8"))
        finally:
            os.close(fd)
    return line


def parse_journal_line(line: str):
    """(time, tag, text) or None."""
    m = JOURNAL_LINE_RE.match(line)
    return (m.group(1), m.group(2).strip(), m.group(3)) if m else None


def tag_is(tag: str, base: str) -> bool:
    """tag equals base or is its sub-tag base/…; the first word counts too ('qa-2 r5b' is 'qa-2')."""
    if not tag or not base:
        return False
    cands = {tag, tag.split()[0]}
    return any(c == base or c.startswith(base + "/") for c in cands)


def mentions(text: str, tag: str) -> bool:
    return re.search(r"(?<![\w@])@" + re.escape(tag) + r"(?![\w-])", text) is not None


def last_line_by_tag(stage: str, tag: str, days: int = 2) -> Optional[dt.datetime]:
    """Time of the latest journal line with this tag (or a sub-tag) in the last `days` journals."""
    today = now().date()
    for back in range(days):
        day = today - dt.timedelta(days=back)
        try:
            lines = journal_path(stage, day).read_text(encoding="utf-8", errors="replace").splitlines()
        except FileNotFoundError:
            continue
        for line in reversed(lines):
            p = parse_journal_line(line)
            if p and tag_is(p[1], tag):
                hh, mm = map(int, p[0].split(":"))
                return dt.datetime.combine(day, dt.time(hh, mm), tzinfo=TZ)
    return None


# ---------------------------------------------------------------- desktop sessions

def normalize_local_id(raw: str) -> str:
    raw = raw.strip()
    return raw if raw.startswith("local_") else f"local_{raw}"


def desktop_session(local_id: str) -> Optional[dict]:
    """Metadata of a Claude Desktop session (read-only), or None when not found."""
    local_id = normalize_local_id(local_id)
    hits = glob.glob(str(sessions_dir() / "*" / "*" / f"{glob.escape(local_id)}.json"))
    if not hits:
        return None
    try:
        with open(hits[0], encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- roles registry

def roles_path(stage: str) -> Path:
    return root() / check_stage(stage) / "roles.json"


def roles_load(stage: str) -> dict:
    try:
        data = json.loads(roles_path(stage).read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    except ValueError as e:
        raise Failure(f"{roles_path(stage)} is not valid JSON ({e}); fix it by hand") from None
    data.setdefault("version", 1)
    data.setdefault("roles", {})
    data.setdefault("retired", [])
    data.setdefault("sends", [])
    return data


# The hub's number in its roles tag: "hub-26", a legacy "хаб-25" (hubs registered by hand before the plugin), any tag
# that ends in "-<n>".
HUB_NUMBER_RE = re.compile(r".+-(\d+)")


def hub_number(tag) -> Optional[int]:
    m = HUB_NUMBER_RE.fullmatch(tag.strip()) if isinstance(tag, str) else None
    return int(m.group(1)) if m else None


def roles_save(stage: str, data: dict) -> None:
    atomic_write(roles_path(stage), json.dumps(data, ensure_ascii=False, indent=1) + "\n")


def roles_lock(stage: str) -> Flock:
    return Flock(root() / check_stage(stage) / ".roles.lock")


def role_for_session(stage: str, sid: str) -> Optional[tuple]:
    """(role, record) whose session or cli session id is sid."""
    if not sid:
        return None
    for name, rec in roles_load(stage).get("roles", {}).items():
        if sid in (rec.get("session"), rec.get("cli_session_id")):
            return name, rec
    return None


def session_id() -> str:
    """Identity of the current host session, also usable from detached workers."""
    if os.environ.get("AGENT_HUB_ENGINE") == "codex" or os.environ.get("CODEX_THREAD_ID"):
        return os.environ.get("CODEX_THREAD_ID", "").strip() or os.environ.get("AGENT_SESSION_ID", "").strip()
    return os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip() or os.environ.get("AGENT_SESSION_ID", "").strip()


def caller_tag(stage: str) -> Optional[str]:
    """HUB_TAG, else the registry tag of this session ($CLAUDE_CODE_SESSION_ID)."""
    if os.environ.get("HUB_TAG"):
        return os.environ["HUB_TAG"].strip()
    try:
        hit = role_for_session(stage, session_id())
    except Failure:
        return None
    if hit:
        return hit[1].get("tag") or hit[0]
    return None


def run_main(fn, argv) -> int:
    try:
        return fn(argv)
    except UsageError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except Failure as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
