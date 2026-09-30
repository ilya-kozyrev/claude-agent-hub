#!/usr/bin/env python3
"""PreToolUse(Bash) hook: refuse an action on a shared resource under another session's lock.

Text rules ("ask the merge owner first") do not stop a busy agent; the lock board (<hub home>/board.md,
CLI `lock`) makes the holder explicit and this hook enforces it.

Built-in actions (per shell segment; text inside quotes, heredocs and echo/printf/cat is not a command):
  merge into main   gh pr merge …; glab mr merge|accept …;
                    gh api / glab api with -X PUT …/pulls/<n>/merge or …/merge_requests/<n>/merge;
                    git push <remote> … <ref> where the target branch is protected (main, master) -> main-merge
Custom actions: <hub home>/lock-rules.json (or $AGENT_HUB_LOCK_RULES), for deploys and shared environments:
  {"protected_branches": ["main", "master"],
   "rules": [{"match": "\\bmake deploy-prod\\b", "kinds": ["deploy-window"], "action": "production deploy"},
             {"match": "\\bhelm upgrade .* -n staging\\b", "kinds": ["stage"], "action": "staging rollout"}]}
  `match` is a Python regex searched in the segment's words joined by single spaces.
  (migration-head is informational; nothing is refused for it.)

Decision: an active lock of a relevant kind held by another session_id -> deny with holder, until,
reason. Own lock, expired lock, no lock -> no decision. `# lock-ok: <reason>` anywhere in the
command -> no decision. Fail-open: any own error (broken board, bad JSON, bad rules file, import
failure) exits 0 without a decision.

Repo scoping: a lock guards one repo (default "*": every repo). The action's repo is taken from
`-R/--repo`, a `repos/<owner>/<name>` or `projects/<group%2Fname>` API path, `git -C`/`cd` in the
command, or the event cwd: the name of the enclosing git repository (a worktree resolves to its main
repository). Unknown repo matches every lock (conservative).
"""
from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path
from urllib.parse import unquote

ESCAPE_HATCH = re.compile(r"#\s*lock-ok\b")
_HEREDOC = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?.*?^\s*\1\s*$", re.DOTALL | re.MULTILINE)
_PRINTING = ("echo", "printf", "cat")
_PREFIX_WORDS = ("command", "env", "sudo", "time", "nohup", "exec")
_PUNCT = set(";&|()<>")
DEFAULT_PROTECTED = ("main", "master")


def plugin_bin() -> str:
    root = os.environ.get("CLAUDE_PLUGIN_ROOT") or os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    return os.path.join(root, "bin")


def segments(command: str) -> list[list[str]]:
    """Simple commands of a shell line as token lists; quoted text stays inside its token."""
    command = _HEREDOC.sub(" ", command)
    try:
        lex = shlex.shlex(command, posix=True, punctuation_chars=";&|()<>")
        lex.whitespace_split = True
        lex.commenters = "#"
        tokens = list(lex)
    except ValueError:  # unbalanced quotes: fall back to a crude split
        tokens = []
        for part in re.split(r"(\|\||&&|[;|()\n])", command):
            tokens += part.split() if part.strip() and not re.fullmatch(r"\|\||&&|[;|()\n]", part) else [";"]
    segs, cur = [], []
    for t in tokens:
        if t and set(t) <= _PUNCT:
            if cur:
                segs.append(cur)
            cur = []
        else:
            cur.append(t)
    if cur:
        segs.append(cur)
    out = []
    for seg in segs:
        seg = _strip_prefix(seg)
        if not seg:
            continue
        # bash -c '...' / zsh -c: recurse into the script
        if os.path.basename(seg[0]) in ("bash", "sh", "zsh") and "-c" in seg:
            i = seg.index("-c")
            if i + 1 < len(seg):
                out += segments(seg[i + 1])
            continue
        out.append(seg)
    return out


def _strip_prefix(seg: list[str]) -> list[str]:
    i = 0
    while i < len(seg):
        t = seg[i]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t):
            i += 1
        elif t in _PREFIX_WORDS:
            i += 1
        elif t in ("timeout", "gtimeout"):
            i += 1
            while i < len(seg) and (seg[i].startswith("-") or re.fullmatch(r"[\d.]+[smhd]?", seg[i])):
                i += 1
        else:
            break
    return seg[i:]


def _api_method(seg: list[str]) -> str:
    """HTTP method of a `gh api` / `glab api` call: explicit -X/--method, else POST if fields given, else GET."""
    for i, t in enumerate(seg):
        if t in ("-X", "--method") and i + 1 < len(seg):
            return seg[i + 1].upper()
        m = re.match(r"^(?:-X|--method=)(\w+)$", t)
        if m:
            return m.group(1).upper()
    if any(t in ("-f", "-F", "--field", "--raw-field", "--input") or t.startswith(("--field=", "--raw-field="))
           for t in seg):
        return "POST"
    return "GET"


def _git_repo_name(path: str) -> str | None:
    """Name of the git repository enclosing `path`; a worktree resolves to its main repository."""
    try:
        p = Path(os.path.abspath(os.path.expanduser(path)))
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


def _repo_of(seg: list[str], cwd: str | None) -> str | None:
    for i, t in enumerate(seg):
        if t in ("-R", "--repo") and i + 1 < len(seg):
            return seg[i + 1].rstrip("/").split("/")[-1]
        if t.startswith("--repo="):
            return t.split("=", 1)[1].rstrip("/").split("/")[-1]
        m = re.search(r"(?:^|/)repos/[^/\s]+/([^/\s]+)", t)
        if m and not m.group(1).startswith((":", "{")):
            return m.group(1)
        m = re.search(r"projects/([^/\s]+)", t)
        if m and not m.group(1).startswith(":"):
            proj = unquote(m.group(1))
            if not proj.isdigit():
                return proj.rstrip("/").split("/")[-1]
        if t == "-C" and seg[0] == "git" and i + 1 < len(seg):
            return _git_repo_name(seg[i + 1])
    return _git_repo_name(cwd) if cwd else None


def load_rules() -> dict:
    """Custom rules; a missing file means built-ins only. A broken file raises (the hook fails open)."""
    path = os.environ.get("AGENT_HUB_LOCK_RULES")
    if not path:
        home = os.environ.get("AGENT_HUB_HOME") or os.path.join(os.path.expanduser("~"), ".claude", "agent-hub")
        path = os.path.join(home, "lock-rules.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {"protected_branches": list(DEFAULT_PROTECTED), "rules": []}
    rules = []
    for r in data.get("rules") or []:
        rules.append({"re": re.compile(r["match"]), "kinds": tuple(r["kinds"]),
                      "action": r.get("action") or r["match"]})
    return {"protected_branches": list(data.get("protected_branches") or DEFAULT_PROTECTED), "rules": rules}


def classify(seg: list[str], rules: dict) -> tuple[str, tuple[str, ...]] | None:
    """(action description, lock kinds it needs) or None for anything else."""
    if not seg:
        return None
    prog = os.path.basename(seg[0])
    args = seg[1:]
    if any(a in ("-h", "--help") for a in args):
        return None
    joined = " ".join(seg)
    for r in rules["rules"]:
        if r["re"].search(joined):
            return (r["action"], r["kinds"])
    if prog == "gh" and len(args) >= 2 and args[0] == "pr" and args[1] == "merge":
        return ("merge a PR (gh pr merge)", ("main-merge",))
    if prog == "glab" and len(args) >= 2 and args[0] == "mr" and args[1] in ("merge", "accept"):
        return ("merge an MR (glab mr merge)", ("main-merge",))
    if prog in ("gh", "glab") and args and args[0] == "api":
        method = _api_method(args)
        tail = " ".join(args) + " "
        if method == "PUT" and re.search(r"(?:pulls|merge_requests)/\d+/merge(?:$|[?\s\"'])", tail):
            return ("merge a PR/MR through the API", ("main-merge",))
        return None
    if prog == "git" and "push" in args:
        after = args[args.index("push") + 1:]
        if any(a in ("-n", "--dry-run") for a in after):
            return None
        positional = [a for a in after if not a.startswith("-")]
        protected = set(rules["protected_branches"])
        for ref in positional[1:]:
            target = ref.split(":", 1)[1] if ":" in ref else ref
            target = target.lstrip("+")
            if target.startswith("refs/heads/"):
                target = target[len("refs/heads/"):]
            if target in protected:
                return (f"push to {target}", ("main-merge",))
    return None


def blocking_lock(kinds, repo, session_id, locks, board):
    at = board.now()
    for kind in kinds:
        for rec in locks:
            if rec.get("kind") != kind or not board.repo_matches(rec, repo):
                continue
            if not board.is_active(rec, at):
                continue
            if session_id and rec.get("session_id") == session_id:
                continue
            return rec
    return None


def decide(event: dict, board, rules: dict | None = None) -> str | None:
    """Deny reason, or None for no decision."""
    if event.get("tool_name") != "Bash":
        return None
    ti = event.get("tool_input") or {}
    command = ti.get("command")
    if not isinstance(command, str) or ESCAPE_HATCH.search(command):
        return None
    rules = rules if rules is not None else load_rules()
    cwd = event.get("cwd")
    hits = []
    for seg in segments(command):
        if os.path.basename(seg[0]) in _PRINTING:
            continue
        if seg[0] == "cd" and len(seg) > 1:
            cwd = os.path.join(cwd or "", os.path.expanduser(seg[1]))
            continue
        c = classify(seg, rules)
        if c:
            hits.append((c, _repo_of(seg, cwd)))
    if not hits:
        return None
    locks = board.load()  # BoardError -> caller fails open
    sid = event.get("session_id") or ""
    for (action, kinds), repo in hits:
        rec = blocking_lock(kinds, repo, sid, locks, board)
        if rec:
            holder = rec.get("owner_name") or "?"
            hid = rec.get("session_id") or "no session_id recorded"
            return (
                f"Command refused by the board_locks hook: {action}.\n"
                f"The resource is under another session's `{rec['kind']}` lock ({rec.get('repo') or '*'}): held by "
                f"\"{holder}\" ({hid}) until {rec['until']}. Reason: {rec.get('why') or '—'}.\n"
                f"Message the holder (SendMessage to \"{holder}\") and wait for the answer; the board is "
                f"`lock list` ({board.BOARD}).\n"
                f"If you are the holder's successor — `lock take {rec['kind']} --force --until … --why …`. If the "
                "action certainly does not touch the resource, add `# lock-ok: <reason>` to the command; the reason "
                "stays in the transcript."
            )
    return None


def main() -> int:
    try:
        event = json.load(sys.stdin)
        sys.path.insert(0, plugin_bin())
        import board  # noqa: E402

        reason = decide(event, board)
    except Exception as e:  # fail-open: never break the user's sessions
        print(f"board_locks: fail-open ({type(e).__name__}: {e})", file=sys.stderr)
        return 0
    if reason:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
