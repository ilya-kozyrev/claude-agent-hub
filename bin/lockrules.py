"""Lock rules: which shared resources a project has and which commands touch each.

A lock is on a named resource. The plugin knows one resource by itself, `main-merge` (who may merge into, or push
to, the protected branches); every other resource is named by the project in a lock-rules.json:

  {"protected_branches": ["main"],
   "resources": {"deploy-window": "a production rollout is in progress",
                 "staging": "the shared staging environment"},
   "rules": [{"match": "\\bmake deploy-prod\\b", "kinds": ["deploy-window"], "action": "production deploy"},
             {"match": "\\bhelm upgrade .* -n staging\\b", "kinds": ["staging"], "action": "staging rollout"}]}

`resources` (optional) declares the names and says what each guards; a resource with no rule (say, the expected
head of a migration chain) is still a valid lock and is informational. When `resources` is present, every rule's
`kinds` must be declared there or be `main-merge` (a typo is an error, not a lock nobody ever takes); without it,
the names used by the rules are the resources. A name is lowercase letters, digits and hyphens.

Files, the repository's first: <repo>/.agent-hub/lock-rules.json of the repository the command runs in, then
<hub home>/lock-rules.json ($AGENT_HUB_LOCK_RULES replaces that one and must exist). A file that cannot be used is
skipped with a warning; the others and the built-in main-merge rules still apply.

Python 3.10+ stdlib only: the PreToolUse hook imports this module and must stay fast.
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import hubcore as hc  # noqa: E402

BUILTIN = {"main-merge": "merges into, and pushes to, the protected branches (main, master unless configured)"}
DEFAULT_PROTECTED = ("main", "master")
NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")


class RulesError(ValueError):
    """A lock-rules.json that cannot be used."""


def valid_name(name) -> bool:
    return isinstance(name, str) and NAME_RE.fullmatch(name) is not None


def read(path: str, required: bool = False) -> Optional[dict]:
    """One lock-rules.json as {"protected_branches", "resources", "rules"}; None when the file does not exist (a
    dangling symlink, or a missing file that was named explicitly with `required`, raises RulesError: a guard that
    was configured must not vanish without a word)."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        if os.path.islink(path):
            raise RulesError(f"{path} is a symlink to a missing file ({os.readlink(path)})") from None
        if required:
            raise RulesError(f"{path} (AGENT_HUB_LOCK_RULES) does not exist") from None
        return None
    except (OSError, ValueError) as e:
        raise RulesError(f"{path}: {e}") from None
    if not isinstance(data, dict):
        raise RulesError(f"{path}: not a JSON object")

    declared = data.get("resources")
    if declared is not None:
        if not isinstance(declared, dict) or not all(isinstance(v, str) for v in declared.values()):
            raise RulesError(f"{path}: \"resources\" must be an object {{name: description}}")
        bad = [k for k in declared if not valid_name(k)]
        if bad:
            raise RulesError(f"{path}: bad resource name {', '.join(map(repr, bad))} "
                             "(lowercase letters, digits and hyphens)")
    resources = dict(declared or {})

    rules = []
    raw_rules = data.get("rules") or []
    if not isinstance(raw_rules, list):
        raise RulesError(f"{path}: \"rules\" must be a list")
    for i, r in enumerate(raw_rules):
        where = f"{path}: rule {i + 1}"
        if not isinstance(r, dict) or not isinstance(r.get("match"), str) or not r["match"]:
            raise RulesError(f"{where}: \"match\" must be a non-empty string")
        kinds = r.get("kinds")
        if not isinstance(kinds, list) or not kinds or not all(isinstance(k, str) for k in kinds):
            raise RulesError(f"{where}: \"kinds\" must be a non-empty list of resource names")
        bad = [k for k in kinds if not valid_name(k)]
        if bad:
            raise RulesError(f"{where}: \"kinds\" has a bad resource name {', '.join(map(repr, bad))} "
                             "(lowercase letters, digits and hyphens)")
        if declared is not None:
            unknown = [k for k in kinds if k not in declared and k not in BUILTIN]
            if unknown:
                known = ", ".join(sorted(set(declared) | set(BUILTIN)))
                raise RulesError(f"{where}: \"kinds\" names {', '.join(map(repr, unknown))}, not declared in "
                                 f"\"resources\" (declared: {known})")
        try:
            rx = re.compile(r["match"])
        except re.error as e:
            raise RulesError(f"{where}: bad regex: {e}") from None
        for k in kinds:
            resources.setdefault(k, "")
        rules.append({"re": rx, "kinds": tuple(kinds), "action": r.get("action") or r["match"]})

    protected = data.get("protected_branches")
    if protected is not None and (not isinstance(protected, list) or not all(isinstance(b, str) for b in protected)):
        raise RulesError(f"{path}: \"protected_branches\" must be a list of branch names")
    resources.pop("main-merge", None)
    return {"protected_branches": protected, "resources": resources, "rules": rules}


def files(cwd: Optional[str]) -> list:
    """The lock-rules.json files that apply to a command run in `cwd`, as (path, required): the repository's
    <repo>/.agent-hub/lock-rules.json (if any), then the hub home's ($AGENT_HUB_LOCK_RULES overrides that one and
    must exist)."""
    out = []
    proj = hc.project_dir(cwd) if cwd else None
    if proj:
        out.append((str(proj / hc.CONFIG_DIRNAME / "lock-rules.json"), False))
    env = os.environ.get("AGENT_HUB_LOCK_RULES")
    out.append((env, True) if env else (str(hc.root() / "lock-rules.json"), False))
    return out


_CACHE: dict = {}


def load(cwd: Optional[str] = None) -> dict:
    """Every applicable file together: {"protected_branches", "resources" (name -> description, built-ins first),
    "rules", "warnings", "files"}. Protected branches: the union of the files that name them, else main and
    master. No file = built-ins only."""
    fs = tuple(files(cwd))
    if fs in _CACHE:
        return _CACHE[fs]
    rules, protected, warnings, used = [], [], [], []
    resources = dict(BUILTIN)
    for path, required in fs:
        try:
            data = read(path, required)
        except RulesError as e:
            warnings.append(f"lock rules skipped — {e}. Its commands are NOT guarded until the file is fixed.")
            continue
        if data is None:
            continue
        used.append(path)
        rules += data["rules"]
        protected += [b for b in data["protected_branches"] or [] if b not in protected]
        for k, v in data["resources"].items():
            if not resources.get(k):
                resources[k] = v
    out = {"protected_branches": protected or list(DEFAULT_PROTECTED), "resources": resources, "rules": rules,
           "warnings": warnings, "files": used}
    _CACHE[fs] = out
    return out
