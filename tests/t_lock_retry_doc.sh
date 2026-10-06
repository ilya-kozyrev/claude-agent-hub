#!/bin/bash
# The lock-rules.json example of docs/reference.md ("A CI retry is not a deploy", DAY-10) does what the text says: it is
# taken from the document itself, so the two cannot drift apart. A deploy job's retry and `make deploy-prod` are guarded
# by deploy-window; a retry of a test job, a retry by job id and an ordinary command are not; a rule on the id form
# guards it and `# lock-ok: <reason>` passes it deliberately.
. "$(dirname "$0")/lib.sh"
new_home
P=$(mktemp -d); APP=$P/app; git init -q -b main $APP; mkdir $APP/.agent-hub
python3 - "$T/../docs/reference.md" > $APP/.agent-hub/lock-rules.json <<'PY'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
m = re.search(r"\*\*A CI retry is not a deploy\.\*\*.*?```json\n(.*?)```", text, re.S)
sys.stdout.write(m.group(1))
PY
check $? 0 "the example is extracted from docs/reference.md"
python3 -c 'import json,sys; json.load(open(sys.argv[1]))' $APP/.agent-hub/lock-rules.json; check $? 0 "…and is valid JSON"
chk(){ (cd $APP && $B/lock rules check "$@") > $P/out 2>&1; }
chk "make deploy-prod" --expect deploy-window; check $? 0 "positive: make deploy-prod is guarded by deploy-window"
chk "glab ci retry deploy:prod" --expect deploy-window; check $? 0 "positive: a retry of a deploy job is guarded"
chk "glab ci run -b main deploy-prod" --expect deploy-window; check $? 0 "positive: so is a run that names it"
chk "glab ci retry test-shard-3" --expect-none; check $? 0 "negative: a retry of a test job is not"
chk "glab api -X POST projects/g%2Fr/jobs/434654/retry" --expect-none; check $? 0 "negative: a retry by job id names nothing and is not guarded"
chk "make test" --expect-none; check $? 0 "negative: an ordinary command is not"
chk "glab ci retry test-shard-3" --expect deploy-window; check $? 1 "control: a wrong expectation fails the check"
# the variation of the text: a rule for the id form, passed with lock-ok after looking the job up
python3 - $APP/.agent-hub/lock-rules.json <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
d["rules"].append({"match": "\\bjobs/\\d+/retry\\b", "kinds": ["deploy-window"], "action": "retry a CI job by id"})
json.dump(d, open(sys.argv[1], "w"))
PY
chk "glab api -X POST projects/g%2Fr/jobs/434654/retry" --expect deploy-window; check $? 0 "variation: the id form is guarded once a rule names it"
chk "glab api -X POST projects/g%2Fr/jobs/434654/retry # lock-ok: job 434654 is test-shard-3, not a deploy" --expect-none; check $? 0 "…and the lock-ok comment passes it deliberately"
exit $fail
