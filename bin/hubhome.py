"""`hub home` and `hub home migrate`: where the hub keeps its files, and moving them (hubcore's "the hub home").

  hub home [--cwd DIR] [--json]
  hub home migrate [--from DIR] [--to DIR] [--apply]

show: the resolved home, the layer that chose it, whether it is under a .claude directory (protected by Claude Code:
then the migrate command), and how to grant a session access to it when the session starts elsewhere.
migrate: from the legacy ~/.claude/agent-hub (--from) to the resolved home (--to; the user default ~/agent-hub when the
resolved home is the source itself). A dry run unless --apply: it lists what would be copied and which JSON files name
the old path. --apply refuses while an agent of any stage of the source is alive and when a file of the source already
exists in the target; it copies (modes and times kept, symlinks as symlinks), verifies the file count and bytes, rewrites
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
    conflicts = [f for f in conflicts if not (f.name.endswith(EMPTY_LOCK) and _size(src_p / f) == 0)]
    live = _live_agents(src_p)
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
        print("live agents (migrate refuses while they run; `agent stop` them or wait): " + ", ".join(live))
    if conflicts:
        print("already in the target (migrate refuses to overwrite): "
              + ", ".join(str(c) for c in conflicts[:10]) + (" …" if len(conflicts) > 10 else ""))
    if not apply:
        print("dry run: nothing written; run again with --apply")
        return 1 if (live or conflicts) else 0
    if live:
        raise hc.Failure(f"{len(live)} agent(s) of the source still run: {', '.join(live)}")
    if conflicts:
        raise hc.Failure(f"{len(conflicts)} file(s) of the source already exist in {dst_p}")
    # the rewritten JSON, worked out before anything is written: a path with a quote in it must stop the run here
    new, planned = str(dst_p), []
    for rel in rewrites:
        text = (src_p / rel).read_text(encoding="utf-8")
        out = pat.sub(lambda m: new, text)
        if _valid_json(text) and not _valid_json(out):
            raise hc.Failure(f"rewriting {src_p / rel} would break its JSON; nothing written")
        planned.append((rel, out))
    dst_p.mkdir(parents=True, exist_ok=True)
    for d in dirs:
        (dst_p / d).mkdir(parents=True, exist_ok=True)
    copied = []
    for f in files:
        s, t = src_p / f, dst_p / f
        if t.exists() and f.name.endswith(EMPTY_LOCK):
            continue
        if s.is_symlink():
            os.symlink(os.readlink(s), t)
        else:
            shutil.copy2(s, t)
        copied.append(f)
    # verify before anything is rewritten or renamed: every file there, every size equal
    bad = [f for f in copied if not ((dst_p / f).exists() or (dst_p / f).is_symlink())
           or _size(dst_p / f) != _size(src_p / f)]
    got = sum(_size(dst_p / f) for f in copied if f not in bad)
    want = sum(_size(src_p / f) for f in copied)
    if bad or got != want:
        raise hc.Failure(f"verification failed: {len(bad)} file(s) missing or of another size ({', '.join(map(str, bad[:5]))}),"
                         f" {got} of {want} bytes; the source {src_p} is untouched, the partial copy is in {dst_p}")
    print(f"copied and verified: {len(copied)} files, {got} bytes")
    for rel, out in planned:
        hc.atomic_write(dst_p / rel, out)
    print(f"rewrote the old path in {len(planned)} JSON file(s)")
    src_p.rename(renamed)
    print(f"renamed {src_p} -> {renamed}")
    if os.environ.get("AGENT_HUB_HOME") and hc.under(os.environ["AGENT_HUB_HOME"], src_p):
        print(f"ATTENTION: $AGENT_HUB_HOME still names {os.environ['AGENT_HUB_HOME']}: change it (your shell, or the "
              f"`env` of your Claude Code settings) to {dst_p}")
    print("grant the new home to sessions that start elsewhere:")
    print("\n".join(grant_lines(dst_p)))
    return 0
