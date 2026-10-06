#!/bin/bash
# `agent-top --json` on a large home (tests/agent_top_perf_fixture.py: 90 MB of agent logs in 10 stages, 160 sub-agents
# with their parents' transcripts, 300 more project folders, 600 Codex rollouts with large headers). The mod runs it
# every few seconds, each time a new process: a run after the first must resume from the disk cache, not read every
# log again. Measured in CPU time, which the parallel test runner disturbs far less than the wall clock, less the fixed
# cost of a run (the same command on empty homes): a repeated run costs under 35 % of the first (0.8.2 read everything
# every time: ~100 %), and it agrees with a run that reads everything afresh (AGENT_TOP_CACHE=0). Appended lines are
# counted once; a log replaced by a new file or rewritten in place is read anew.
. "$(dirname "$0")/lib.sh"
export PYTHONDONTWRITEBYTECODE=1
new_home
export CLAUDE_CONFIG_DIR="$(mktemp -d)" CODEX_HOME="$(mktemp -d)"
TURNS=$(python3 "$T/agent_top_perf_fixture.py" "$AGENT_HUB_HOME" "$CLAUDE_CONFIG_DIR" "$CODEX_HOME"); check $? 0 "large fixture built"

python3 - "$B/agent-top" "$TURNS" <<'PY'
import json, os, resource, subprocess, sys, time
top, turns = sys.argv[1], int(sys.argv[2])
fails = 0


def chk(name, cond):
    global fails
    print(("PASS " if cond else "FAIL ") + name, flush=True)
    fails += 0 if cond else 1


def run(env=None, args=("--json",)):
    r0, t = resource.getrusage(resource.RUSAGE_CHILDREN), time.time()
    p = subprocess.run([top, *args], capture_output=True, text=True, env=dict(os.environ, **(env or {})))
    wall, r1 = time.time() - t, resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu = r1.ru_utime - r0.ru_utime + r1.ru_stime - r0.ru_stime
    if p.returncode != 0:
        print(p.stderr[-2000:])
    return json.loads(p.stdout or "{}"), wall, cpu


def grow1(d):
    return next((a for a in d.get("agents", []) if a["stage"] == "perf-00" and a["role"] == "grow1"), None)


STABLE = ("state", "turns", "run_turns", "sub_turns", "turns_approx", "ctx_tokens", "cost_usd", "last_text", "model_id", "result")


def picture(d):
    return {(a["stage"], a["dir_name"]): tuple(json.dumps(a.get(k), sort_keys=True) for k in STABLE) for a in d.get("agents", [])}


# the fixed cost of a run (interpreter, imports, `ps`): the same command on an empty hub home, best of 3
empty = os.path.join(os.environ["TMPDIR"] if os.environ.get("TMPDIR") else "/tmp", f"empty-home-{os.getpid()}")
os.makedirs(empty, exist_ok=True)
base = min(run({"AGENT_HUB_HOME": empty, "CLAUDE_CONFIG_DIR": empty, "CODEX_HOME": empty, "AGENT_TOP_CACHE": "0"})[2] for _ in range(3))
cold, cold_wall, cold_cpu = run()
n_head = sum(1 for a in cold.get("agents", []) if a["kind"] == "headless")
n_sub = sum(1 for a in cold.get("agents", []) if a["kind"] == "subagent")
chk(f"first run lists 60 agents and 160 sub-agents ({n_head}, {n_sub}); grow1 has {turns} turns", n_head == 60 and n_sub == 160
    and (grow1(cold) or {}).get("turns") == turns)
# the stage's hub: its 5 MB transcript (four lines of 1 MB) is read in pieces and priced from the agents' results (5e-6 $
# per weighted token): 2000 messages x 110 tokens
hub_usd = (cold.get("spend", {}).get("perf-00") or {}).get("hub_usd")
chk(f"the hub's transcript with 1 MB lines is read to its end and priced ({hub_usd} = 1.1)",
    hub_usd == 1.1 and not cold["spend"]["perf-00"]["hub_partial"])
runs = [run() for _ in range(3)]
warm, warm_wall, warm_cpu = min(runs, key=lambda r: r[2])
# what the logs cost: a run's CPU less the fixed cost
ratio = max(0.0, warm_cpu - base) / max(0.01, cold_cpu - base)
print(f"timing: first run {cold_wall:.2f} s wall / {cold_cpu:.2f} s CPU; repeated {warm_wall:.2f} s wall / {warm_cpu:.2f} s CPU "
      f"(best of 3); fixed cost of a run {base:.2f} s CPU; ratio of the rest {ratio:.2f}", flush=True)
chk(f"a repeated run costs under 35 % of the first's CPU beyond the fixed cost ({ratio:.0%})", ratio < 0.35 and cold_cpu - base > 0.3)
chk(f"a repeated run takes under 5 s wall ({warm_wall:.2f} s)", warm_wall < 5)
fresh, _, _ = run({"AGENT_TOP_CACHE": "0"})
diff = [k for k in picture(fresh) if picture(fresh)[k] != picture(warm).get(k)] + [k for k in picture(warm) if k not in picture(fresh)]
chk(f"the cached run agrees with one that reads everything afresh ({len(diff)} agents differ{': ' + str(diff[:3]) if diff else ''})",
    not diff and len(picture(fresh)) == 220)
chk("the cached run's spend agrees with the fresh one's", warm.get("spend") == fresh.get("spend") and fresh["spend"]["perf-00"]["hub_usd"] == 1.1)

# appended: a resumed run of grow1 (init, 5 turns, a result) is counted once, from where the cache left off
log = os.path.join(os.environ["AGENT_HUB_HOME"], "perf-00", "agents", "grow1", "log.jsonl")
with open(log, "a") as fh:
    fh.write(json.dumps({"type": "system", "subtype": "init", "session_id": "s2"}) + "\n")
    for i in range(5):
        fh.write(json.dumps({"type": "assistant", "message": {"id": f"again{i}", "content": [{"type": "text", "text": f"again {i}"}]},
                             "parent_tool_use_id": None}) + "\n")
    fh.write(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "again done", "total_cost_usd": 0.5}) + "\n")
g = grow1(run()[0]) or {}
chk(f"appended run counted once: turns {g.get('turns')} = {turns}+5, run turns {g.get('run_turns')} = 5, cost {g.get('cost_usd')} = 2.0",
    g.get("turns") == turns + 5 and g.get("run_turns") == 5 and g.get("cost_usd") == 2.0 and g.get("last_text") == "again 4")
# replaced (a new file under the same name, shorter): read anew, not resumed at the old offset
tmp = log + ".new"
with open(tmp, "w") as fh:
    fh.write(json.dumps({"type": "system", "subtype": "init", "session_id": "s3"}) + "\n")
    fh.write(json.dumps({"type": "assistant", "message": {"id": "only", "content": [{"type": "text", "text": "fresh file"}]},
                         "parent_tool_use_id": None}) + "\n")
os.replace(tmp, log)
g = grow1(run()[0]) or {}
chk(f"a replaced log is read anew: turns {g.get('turns')} = 1, last text {g.get('last_text')!r}", g.get("turns") == 1 and g.get("last_text") == "fresh file")
# rewritten in place (same inode, now longer than the cached offset): the bytes before the offset changed, read anew
ino = os.stat(log).st_ino
with open(log, "w") as fh:   # a result first, inside the bytes a resumed reader would skip
    fh.write(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "r", "total_cost_usd": 7.0}) + "\n")
    fh.write(json.dumps({"type": "system", "subtype": "init", "session_id": "s4"}) + "\n")
    for i in range(10):
        fh.write(json.dumps({"type": "assistant", "message": {"id": f"rw{i}", "content": [{"type": "text", "text": f"rewritten {i} " + "y" * 40}]},
                             "parent_tool_use_id": None}) + "\n")
g = grow1(run()[0]) or {}
chk(f"a log rewritten in place (same inode: {os.stat(log).st_ino == ino}) is read anew: turns {g.get('turns')} = 10, its first line's cost {g.get('cost_usd')} = 7.0",
    os.stat(log).st_ino == ino and g.get("turns") == 10 and g.get("cost_usd") == 7.0 and str(g.get("last_text")).startswith("rewritten 9"))
sys.exit(1 if fails else 0)
PY
[ $? -eq 0 ] || fail=1
[ -s "$AGENT_HUB_HOME/.state/agent-top/cache.sqlite" ]; check $? 0 "the cache is the hub home's .state/agent-top/cache.sqlite"

# the review's races, with the real readers and store: a log rewritten (same inode, same size) after it was read but
# before the flush, and a Codex header rewritten in place to the same length, are not resumed from the cache
python3 - "$B" <<'PY'
import importlib.machinery, importlib.util, json, os, sys, tempfile
sys.path.insert(0, sys.argv[1])
import codex_rollouts, topcache
loader = importlib.machinery.SourceFileLoader("agent_top", os.path.join(sys.argv[1], "agent-top"))
top = importlib.util.module_from_spec(importlib.util.spec_from_loader("agent_top", loader)); loader.exec_module(top)
d = tempfile.mkdtemp()
fails = 0
def chk(name, cond):
    global fails
    print(("PASS " if cond else "FAIL ") + name); fails += 0 if cond else 1
log = os.path.join(d, "log.jsonl")
res = lambda cost: json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "r", "total_cost_usd": cost}) + "\n"
open(log, "w").write(res(1.0))
store = topcache.Store(os.path.join(d, "c.sqlite"), "g1")
ls = top.LogState(top.Path(log)); ls.update(); store.put("log", log, ls)
with open(log, "r+") as fh:                      # rewritten in place, same size, before the flush
    fh.write(res(7.0))
store.flush()
again = top.LogState(top.Path(log))
ok = topcache.load_into(again, topcache.Store(os.path.join(d, "c.sqlite"), "g1").get("log", log), {"rollout": codex_rollouts.Normalizer})
again.update()
chk(f"a log rewritten between its read and the flush is read anew (restored: {ok}, cost {again.cost_sum} = 7.0)", not ok and again.cost_sum == 7.0)
os.environ["CODEX_HOME"] = os.path.join(d, "codex")
roll = os.path.join(d, "codex", "sessions", "2026", "10", "06", "rollout-x.jsonl"); os.makedirs(os.path.dirname(roll))
head = lambda sid: json.dumps({"type": "session_meta", "payload": {"id": sid, "cwd": "/w"}}) + "\n"
open(roll, "w").write(head("AAA") + "{}\n")
s2 = topcache.Store(os.path.join(d, "c.sqlite"), "g2"); idx = codex_rollouts.Index(); idx.store = s2; idx.update(); s2.flush()
with open(roll, "r+") as fh:
    fh.write(head("BBB"))
idx2 = codex_rollouts.Index(); idx2.store = topcache.Store(os.path.join(d, "c.sqlite"), "g2"); idx2.update()
chk(f"a Codex header rewritten in place to the same length is read anew ({sorted(idx2.records)} = ['BBB'])", sorted(idx2.records) == ["BBB"])
sys.exit(fails)
PY
check $? 0 "cache races from the review: rewritten before the flush, Codex header rewritten in place"
exit $fail
