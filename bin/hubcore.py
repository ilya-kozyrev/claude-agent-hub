"""Shared helpers for the hub tools: jlog, jwait, roles, hub, agent, agent-top.

Layout under the hub home ($AGENT_HUB_HOME, default ~/.claude/agent-hub):
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
import sys
import tempfile
from pathlib import Path
from typing import Optional

BIN = Path(os.path.dirname(os.path.realpath(__file__)))
DEFAULT_STAGE = "default"
STAGE_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")
# "- 14:35 [hub-16] text"; the tag may hold spaces ("[qa-2 r5b]").
JOURNAL_LINE_RE = re.compile(r"^- (\d{1,2}:\d{2}) \[([^\]]+)\]\s?(.*)$")
CONFIG_DIRNAME = ".agent-hub"
# Settings that only the hub home's config.json may set: every tool sharing a hub home must agree on them.
HUB_WIDE_KEYS = ("AGENT_HUB_TZ", "AGENT_HUB_SEND_CAP", "AGENT_HUB_NIGHT", "AGENT_HUB_HANDOFF_MAX_BYTES")
# Settings a repository's .agent-hub/config.json may set as well (the repository's value wins over the home's).
PROJECT_KEYS = ("AGENT_HUB_MODEL_MAP", "AGENT_HUB_DEFAULT_EFFORT", "AGENT_HUB_PERMISSION_MODE",
                "AGENT_HUB_DEFAULT_REPO", "CLAUDE_BIN", "AGENT_INIT_TIMEOUT")


def root() -> Path:
    """The hub home: $AGENT_HUB_HOME, else ~/.claude/agent-hub."""
    raw = os.environ.get("AGENT_HUB_HOME")
    return Path(raw).expanduser() if raw else Path.home() / ".claude" / "agent-hub"


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
        if (d / ".git").exists():
            return None
    return None


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
    allowed = PROJECT_KEYS if project else PROJECT_KEYS + HUB_WIDE_KEYS
    for name, value in data.items():
        if name.startswith("_"):  # "_comment" and the like
            continue
        if name not in allowed:
            hint = " (hub-wide: set it in the hub home's config.json)" if name in HUB_WIDE_KEYS else ""
            _warn(f"{path}: {name} is not a setting this file may set{hint}; ignored")
            continue
        if isinstance(value, dict):  # {"sonnet": "claude-…"} for AGENT_HUB_MODEL_MAP
            value = ",".join(f"{k}={v}" for k, v in value.items())
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            _warn(f"{path}: {name} must be a string or a number; ignored")
            continue
        out[name] = str(value)
    _CONFIG_CACHE[key] = out
    return out


def setting(name: str, default: Optional[str] = None, cwd=None) -> Optional[str]:
    """$NAME if set and non-empty, else the project's .agent-hub/config.json (for PROJECT_KEYS; the project is
    found from `cwd`, default the working directory), else <hub home>/config.json, else `default`."""
    raw = os.environ.get(name)
    if raw:
        return raw
    if name in PROJECT_KEYS:
        proj = project_dir(cwd)
        if proj:
            val = read_config(proj / CONFIG_DIRNAME / "config.json", project=True).get(name)
            if val:
                return val
    return read_config(root() / "config.json", project=False).get(name) or default


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
# Claude Desktop pauses a session's outgoing cross-session sends after this many messages without the
# user typing in it; `roles` counts sends against it. Override with $AGENT_HUB_SEND_CAP.
MESSAGE_CAP = int(setting("AGENT_HUB_SEND_CAP") or 10)


def child_env(extra: Optional[dict] = None) -> dict:
    """Environment for calling the sibling tools: same home, and this bin/ first on PATH."""
    env = dict(os.environ)
    env["AGENT_HUB_HOME"] = str(root())
    env["PATH"] = str(BIN) + os.pathsep + env.get("PATH", "")
    if extra:
        env.update(extra)
    return env


def sessions_dir() -> Path:
    """Claude Desktop session metadata (macOS); override with $CLAUDE_SESSIONS_DIR."""
    raw = os.environ.get("CLAUDE_SESSIONS_DIR")
    return Path(raw) if raw else Path.home() / "Library" / "Application Support" / "Claude" / "claude-code-sessions"


def now() -> dt.datetime:
    return dt.datetime.now(TZ)


def default_stage() -> str:
    return os.environ.get("HUB_STAGE") or DEFAULT_STAGE


def check_stage(stage: str) -> str:
    if not STAGE_RE.fullmatch(stage or ""):
        raise UsageError(f"bad stage name {stage!r} (lowercase letters, digits, '-' and '_')")
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


def caller_tag(stage: str) -> Optional[str]:
    """HUB_TAG, else the registry tag of this session ($CLAUDE_CODE_SESSION_ID)."""
    if os.environ.get("HUB_TAG"):
        return os.environ["HUB_TAG"].strip()
    try:
        hit = role_for_session(stage, os.environ.get("CLAUDE_CODE_SESSION_ID", ""))
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
