"""`hub home` and `hub home migrate`: where the hub keeps its files, and moving them (hubcore's "the hub home").

  hub home [--cwd DIR] [--json]
  hub home migrate [--from DIR] [--to DIR] [--apply]

show: the resolved home, the layer that chose it, whether it is under a .claude directory (protected by Claude Code:
then the migrate command), and how to grant a session access to it when the session starts elsewhere.
migrate: from the legacy ~/.claude/agent-hub (--from) to the resolved home (--to; the user default ~/agent-hub when the
resolved home is the source itself). A dry run unless --apply: it lists what would be copied and which JSON files name
the old path. --apply refuses while an agent of any stage of the source is alive or a background hub of one of its stages
runs (`claude agents`, asked when a stage used the autopilot), and when a path of the source already exists in the
target; it copies into a staging directory beside the target (modes and times kept, symlinks as symlinks, a link into
the old home retargeted), verifies the file count and bytes, moves the copy into place only then, rewrites
the old absolute path in every *.json under the new home (roles, agents' meta, .jwait-state, .state, the autopilot
state) — the Markdown history stays as written — and renames the source to <source>.migrated-YYYYMMDD. Nothing is
deleted. A second run finds no source and says there is nothing to migrate.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import hubcore as hc  # noqa: E402

DOCS_PROTECTED = "https://code.claude.com/docs/en/permission-modes.md"
DOCS_SANDBOX = "https://code.claude.com/docs/en/sandboxing.md"
EMPTY_LOCK = ".lock"  # an empty flock file: already in the target is no conflict


def grant_lines(home: Path) -> list:
    snippet = json.dumps({"permissions": {"additionalDirectories": [str(home)]}})
    return [f"  this session:   /add-dir {home}",
            f"  every session:  ~/.claude/settings.json {snippet}",
            f"  one CLI run:    claude --add-dir {home}"]


def info(cwd=None) -> dict:
    h = hc.home(cwd)
    here = Path(cwd or os.getcwd())
    return {"home": str(h.path), "layer": h.layer, "chosen_by": h.source, "exists": h.path.is_dir(),
            "protected": hc.is_protected(h.path), "under_cwd": hc.under(h.path, here),
            "user_default": str(hc.user_home()), "legacy": str(hc.legacy_home())}


def show(cwd=None, as_json: bool = False) -> int:
    d = info(cwd)
    if as_json:
        print(json.dumps(d, ensure_ascii=False, indent=1))
        return 0
    home = Path(d["home"])
    print(f"hub home: {home}{'' if d['exists'] else ' (not created yet)'}")
    print(f"chosen by: {d['chosen_by']}")
    if d["protected"]:
        print("protected: yes — it is under a .claude directory. Claude Code prompts for (or, in auto mode, classifies; "
              "in dontAsk, refuses) every edit there whatever the allow rules say, and the Bash sandbox refuses writes "
              f"there ({DOCS_PROTECTED} § Protected paths, {DOCS_SANDBOX} § Protected paths). Move it: "
              f"`hub home migrate` (a dry run; then --apply) — to {hc.user_home()} unless AGENT_HUB_HOME says otherwise.")
    else:
        print("protected: no")
    if d["under_cwd"]:
        print("access: the home is under this directory — a session started here needs no grant")
    else:
        print("access: a session started outside the home needs it granted (agent spawn and the autopilot successor "
              "pass --add-dir themselves):")
        print("\n".join(grant_lines(home)))
    print("another home: AGENT_HUB_HOME in the shell, or {\"env\": {\"AGENT_HUB_HOME\": \"…\"}} in your Claude Code "
          "settings; per repository, .agent-hub/config.json {\"AGENT_HUB_HOME\": \"project\"} (inside the repository) "
          "or \"user\"")
    return 0


# ---------------------------------------------------------------- migrate

def _walk(src: Path) -> tuple:
    """(dirs, files) under src, relative; symlinks are files (copied as links), never followed."""
    dirs, files = [], []
    for d, dnames, fnames in os.walk(src, followlinks=False):
        base = Path(d)
        for n in list(dnames):
            p = base / n
            if p.is_symlink():
                files.append(p.relative_to(src))
                dnames.remove(n)
            else:
                dirs.append(p.relative_to(src))
        for n in fnames:
            files.append((base / n).relative_to(src))
    return sorted(dirs), sorted(files)


def _size(p: Path) -> int:
    return os.lstat(p).st_size


def _live_agents(src: Path) -> list:
    """`stage/role (pid N)` of every agent under src whose process is alive."""
    out, ag = [], None
    for meta_path in sorted(src.glob("*/agents/*/meta.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(meta, dict) or not meta.get("pid") or not meta.get("session_id"):
            continue
        if ag is None:
            import autopilot  # noqa: E402  (loads bin/agent for its alive())
            ag = autopilot._agent_module()
        if ag.alive(meta):
            out.append(f"{meta_path.parent.parent.parent.name}/{meta_path.parent.name} (pid {meta['pid']})")
    return out


def _live_successors(src: Path) -> tuple:
    """(names, note): background hub sessions of the source's stages that still run — an autopilot successor carries
    the old home in its environment and would recreate it — from `claude agents --json`; asked only when a stage of the
    source has used the autopilot (an auto-handoff.json). note: why it could not be told, else ""."""
    states = sorted(src.glob("*/auto-handoff.json"))
    if not states:
        return [], ""
    stages = sorted({p.parent.name for p in states})
    ids = set()
    for p in states:
        try:
            pend = (json.loads(p.read_text(encoding="utf-8")) or {}).get("pending") or {}
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(pend, dict) and pend.get("id"):
            ids.add(str(pend["id"]))
    alt = "|".join(map(re.escape, stages))
    names = re.compile(rf"^(?:(?:{alt})-hub-\d+|Hub (?:{alt}) #\d+(?: — .*)?)$")  # a title may carry the stage's goal
    try:
        cli = hc.find_claude(persist=False)
    except hc.Failure as e:
        return [], str(e)
    if cli is None:
        return [], "no claude CLI found"
    import autopilot  # noqa: E402
    try:
        res = subprocess.run([cli.path, "agents", "--json"], capture_output=True, text=True, timeout=30,
                             env=autopilot.child_env(), stdin=subprocess.DEVNULL)
        rows = json.loads(res.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        return [], f"`claude agents --json` did not answer ({e})"
    out = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict) or r.get("kind") != "background":
            continue
        rid = str(r.get("id") or r.get("sessionId") or "")
        if names.match(str(r.get("name") or "")) or rid in ids or str(r.get("sessionId") or "") in ids:
            out.append(f"{r.get('name') or '?'} ({rid}; `claude stop {rid}`)")
    return out, ""


def _old_paths(src: Path) -> list:
    """The spellings of the source's absolute path a JSON file may hold (as given, resolved), longest first."""
    out = {str(src)}
    try:
        out.add(str(src.resolve()))
    except OSError:
        pass
    return sorted(out, key=len, reverse=True)


def _path_re(olds: list) -> re.Pattern:
    # the old path as a whole path or a prefix of one, never a longer name ("…/agent-hub2")
    return re.compile("(?:" + "|".join(re.escape(o) for o in olds) + r')(?=[/"\\]|$)')


def _json_hits(root: Path, files: list, pat: re.Pattern) -> list:
    hits = []
    for rel in files:
        p = root / rel
        if p.suffix != ".json" or p.is_symlink():
            continue
        try:
            if pat.search(p.read_text(encoding="utf-8")):
                hits.append(rel)
        except (OSError, UnicodeDecodeError):
            continue
    return hits


def _stage(src: Path, staging: Path, dirs: list, files: list, dst: Path, pat: re.Pattern, new: str) -> list:
    """Copy the source into `staging` (modes and times kept; a symlink as a symlink, its target moved to the new home
    when it pointed into the old one) and verify every file's presence and size. Returns the files copied: all but
    an empty lock file the target already has."""
    staging.mkdir(parents=True)
    for d in dirs:
        (staging / d).mkdir(parents=True, exist_ok=True)
    copied = []
    for f in files:
        s, t = src / f, staging / f
        if f.name.endswith(EMPTY_LOCK) and (dst / f).is_file() and _size(s) == 0:
            continue
        if s.is_symlink():
            os.symlink(pat.sub(lambda m: new, os.readlink(s)), t)
        else:
            shutil.copy2(s, t)
        copied.append(f)
    bad = [f for f in copied if not ((staging / f).exists() or (staging / f).is_symlink())
           or (not (src / f).is_symlink() and _size(staging / f) != _size(src / f))]
    if bad:
        raise hc.Failure(f"verification failed: {len(bad)} file(s) missing or of another size "
                         f"({', '.join(map(str, bad[:5]))})")
    want = sum(_size(src / f) for f in copied if not (src / f).is_symlink())
    got = sum(_size(staging / f) for f in copied if not (staging / f).is_symlink())
    if got != want:
        raise hc.Failure(f"verification failed: {got} of {want} bytes copied")
    return copied


def _valid_json(text: str) -> bool:
    try:
        json.loads(text)
    except ValueError:
        return False
    return True


def _target_default(src: Path) -> Path:
    h = hc.home()
    return hc.user_home() if hc.under(h.path, src) else h.path


def migrate(src: Optional[str], dst: Optional[str], apply: bool) -> int:
    src_p = Path(src).expanduser() if src else hc.legacy_home()
    if not src_p.is_absolute():
        src_p = Path.cwd() / src_p
    if not src_p.is_dir() or not any(src_p.iterdir()):
        print(f"nothing to migrate: {src_p} {'is empty' if src_p.is_dir() else 'does not exist'}")
        return 0
    dst_p = Path(dst).expanduser() if dst else _target_default(src_p)
    if not dst_p.is_absolute():
        dst_p = Path.cwd() / dst_p
    if hc.under(dst_p, src_p) or hc.under(src_p, dst_p):
        raise hc.UsageError(f"--to {dst_p} and --from {src_p} overlap: pick a target outside the source")
    dirs, files = _walk(src_p)
    total = sum(_size(src_p / f) for f in files)
    pat = _path_re(_old_paths(src_p))
    rewrites = _json_hits(src_p, files, pat)
    conflicts = [f for f in files if (dst_p / f).exists() or (dst_p / f).is_symlink()]
    conflicts = [f for f in conflicts if not (f.name.endswith(EMPTY_LOCK) and _size(src_p / f) == 0
                                              and (dst_p / f).is_file())]
    conflicts += [d for d in dirs if ((dst_p / d).exists() or (dst_p / d).is_symlink()) and not (dst_p / d).is_dir()]
    live = _live_agents(src_p)
    successors, unknown = _live_successors(src_p)
    live += successors
    stamp = dt.date.today().strftime("%Y%m%d")
    renamed = src_p.with_name(f"{src_p.name}.migrated-{stamp}")
    if renamed.exists():
        renamed = src_p.with_name(f"{src_p.name}.migrated-{stamp}-{dt.datetime.now():%H%M%S}")
    print(f"{'migrate' if apply else 'dry run'}: {src_p} -> {dst_p}")
    print(f"files: {len(files)} ({total} bytes) in {len(dirs)} directories")
    print(f"JSON files naming the old path (rewritten to the new one): {len(rewrites)}"
          + "".join(f"\n  {r}" for r in rewrites[:20]) + ("\n  …" if len(rewrites) > 20 else ""))
    print("Markdown and other files: copied as they are (the history keeps the old paths)")
    print(f"then: {src_p} renamed to {renamed} (nothing is deleted)")
    if hc.is_protected(dst_p):
        print(f"note: the target {dst_p} is under a .claude directory too — protected the same way")
    if live:
        print("still running with the old home (migrate refuses while they run; `agent stop` an agent, `claude stop` a "
              "background hub, or wait): " + ", ".join(live))
    if unknown:
        print(f"note: could not check for a running background hub ({unknown}); make sure no autopilot successor of "
              "these stages runs")
    if conflicts:
        print("already in the target (migrate refuses to overwrite): "
              + ", ".join(str(c) for c in conflicts[:10]) + (" …" if len(conflicts) > 10 else ""))
    if not apply:
        print("dry run: nothing written; run again with --apply")
        return 1 if (live or conflicts) else 0
    if live:
        raise hc.Failure(f"{len(live)} session(s) of the source still run: {', '.join(live)}")
    if conflicts:
        raise hc.Failure(f"{len(conflicts)} path(s) of the source already exist in {dst_p}")
    # the rewritten JSON, worked out before anything is written: a path with a quote in it must stop the run here
    new, planned = str(dst_p), []
    for rel in rewrites:
        text = (src_p / rel).read_text(encoding="utf-8")
        out = pat.sub(lambda m: new, text)
        if _valid_json(text) and not _valid_json(out):
            raise hc.Failure(f"rewriting {src_p / rel} would break its JSON; nothing written")
        planned.append((rel, out))
    # Copy into a staging directory beside the target and move it into place only once verified: a half-done copy at
    # ~/agent-hub would become the live home (an existing ~/agent-hub wins over the legacy one).
    staging = dst_p.with_name(f".{dst_p.name}.migrating-{os.getpid()}")
    try:
        copied = _stage(src_p, staging, dirs, files, dst_p, pat, new)
        for rel, out in planned:
            hc.atomic_write(staging / rel, out)
    except (OSError, hc.Failure) as e:
        shutil.rmtree(staging, ignore_errors=True)
        raise hc.Failure(f"{e}; nothing was written to {dst_p}, the source {src_p} is untouched") from None
    print(f"copied and verified: {len(copied)} files, {sum(_size(src_p / f) for f in copied)} bytes")
    print(f"rewrote the old path in {len(planned)} JSON file(s)")
    if not dst_p.exists():
        os.rename(staging, dst_p)
    else:  # a target that already holds other files: move ours in beside them
        moved = 0
        try:
            for d in dirs:
                (dst_p / d).mkdir(parents=True, exist_ok=True)
            for f in copied:
                os.rename(staging / f, dst_p / f)
                moved += 1
        except OSError as e:
            raise hc.Failure(f"moving the verified copy into {dst_p} failed after {moved} of {len(copied)} files ({e}); "
                             f"the rest is in {staging}, the source {src_p} is untouched") from None
        shutil.rmtree(staging, ignore_errors=True)
    src_p.rename(renamed)
    print(f"renamed {src_p} -> {renamed}")
    if os.environ.get("AGENT_HUB_HOME") and hc.under(os.environ["AGENT_HUB_HOME"], src_p):
        print(f"ATTENTION: $AGENT_HUB_HOME still names {os.environ['AGENT_HUB_HOME']}: change it (your shell, or the "
              f"`env` of your Claude Code settings) to {dst_p}")
    print("grant the new home to sessions that start elsewhere:")
    print("\n".join(grant_lines(dst_p)))
    return 0
