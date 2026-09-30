# Shared helpers for the agent-hub test scripts (bash). Source it: . "$(dirname "$0")/lib.sh"
# Every test runs against a throw-away hub home; nothing here may touch the real one.
set -u
T="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
B="${BIN:-$(cd "$T/../bin" && pwd)}"
HOOKS="$(cd "$T/../hooks" && pwd)"
export AGENT_HUB_TZ=UTC
unset HUB_TAG HUB_STAGE CLAUDE_CODE_SESSION_ID AGENT_BOARD_FILE AGENT_HUB_LOCK_RULES CLAUDE_SESSIONS_DIR \
      AGENT_HUB_MODEL_MAP AGENT_HUB_DEFAULT_EFFORT AGENT_HUB_PERMISSION_MODE CLAUDE_BIN
fail=0
check(){ if [ "$1" = "$2" ]; then echo "PASS $3"; else echo "FAIL $3 (got $1 want $2)"; fail=1; fi; }
new_home(){ export AGENT_HUB_HOME="$(mktemp -d)"; }
today(){ date -u +%F; }
# UTC clock arithmetic, portable (no GNU/BSD date flags): utc_iso -2 -> ISO minute two minutes ago
utc_iso(){ python3 -c 'import datetime as d,sys; print((d.datetime.now(d.timezone.utc)+d.timedelta(minutes=int(sys.argv[1]))).strftime("%Y-%m-%dT%H:%M"))' "$1"; }
utc_hhmm(){ python3 -c 'import datetime as d,sys; print((d.datetime.now(d.timezone.utc)+d.timedelta(minutes=int(sys.argv[1]))).strftime("%H:%M"))' "$1"; }
journal(){ echo "$AGENT_HUB_HOME/${1:-stage-a}/coordinator/work/journal-$(today).md"; }
# in-place regex substitution on a file, portable (no sed -i flavours)
subst(){ python3 - "$1" "$2" "$3" <<'PY'
import re, sys
p, pat, rep = sys.argv[1:]
s = open(p, encoding="utf-8").read()
open(p, "w", encoding="utf-8").write(re.sub(pat, rep, s, flags=re.M))
PY
}
# hash of every file under a dir (lock files and test outputs excluded)
snap(){ python3 - "$1" <<'PY'
import hashlib, os, sys
h = hashlib.sha1()
for d, _, files in sorted(os.walk(sys.argv[1])):
    if "/.jwait-state" in d:
        continue
    for f in sorted(files):
        if f.endswith((".lock", ".out")):
            continue
        h.update(f.encode()); h.update(open(os.path.join(d, f), "rb").read())
print(h.hexdigest())
PY
}
