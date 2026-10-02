#!/bin/bash
. "$(dirname "$0")/lib.sh"
new_home
AGENT_HUB_ENGINE=codex "$B/hub" reviewer --json > "$AGENT_HUB_HOME/default.json"; check $? 0 'Codex default reviewer resolves'
python3 - "$AGENT_HUB_HOME/default.json" <<'PY'
import json,sys
r=json.load(open(sys.argv[1]));s=r['start']
assert '--engine codex' in s and '--sandbox read-only' in s,s
assert '--model opus' not in s and '--model None' not in s,s
assert '--model gpt-6-astra' in s,s
PY
check $? 0 'Codex reviewer defaults to Astra high read-only'
AGENT_HUB_ENGINE=codex AGENT_HUB_CODEX_DEFAULT_MODEL=gpt-6.1-sol "$B/hub" reviewer --json > "$AGENT_HUB_HOME/sol-author.json"
python3 - "$AGENT_HUB_HOME/sol-author.json" <<'PY'
import json,sys
assert '--model gpt-6-astra' in json.load(open(sys.argv[1]))['start']
PY
check $? 0 'Sol implementation default does not downgrade reviewer'
AGENT_HUB_REVIEWERS='[{"name":"codex","kind":"agent","engine":"codex","model":"gpt-fixture","effort":"high"}]' "$B/hub" reviewer --json > "$AGENT_HUB_HOME/explicit.json"; check $? 0 'mixed engine reviewer config'
python3 - "$AGENT_HUB_HOME/explicit.json" <<'PY'
import json,sys
r=json.load(open(sys.argv[1]));assert r['chosen']=='codex';assert '--engine codex --sandbox read-only --model gpt-fixture' in r['start']
PY
check $? 0 'Codex reviewer selection and start line'
AGENT_HUB_ENGINE=codex AGENT_HUB_REVIEWERS='[{"name":"claude","kind":"agent","engine":"claude","model":"opus","effort":"high"}]' "$B/hub" reviewer --json > "$AGENT_HUB_HOME/mixed.json"; check $? 0 'Claude reviewer from Codex coordinator'
python3 - "$AGENT_HUB_HOME/mixed.json" <<'PY'
import json,sys
r=json.load(open(sys.argv[1]));assert '--engine claude' in r['start'];assert '--sandbox' not in r['start']
PY
check $? 0 'explicit Claude engine preserved'
exit $fail
