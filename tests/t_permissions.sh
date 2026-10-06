#!/bin/bash
# Standing permissions (ask allow / revoke / allow --list) and the "covered" check of ask add: a permission is bound to
# the repository the action touches and read from every stage's register (docs/standing-permissions.md). Scope
# resolution, expiry, revocation, the refusal and its override, the hub start digest. Positive and negative controls.
. "$(dirname "$0")/lib.sh"
new_home; R=$AGENT_HUB_HOME; P=$(mktemp -d)/t
cd "$(mktemp -d)"   # outside any repository: the working directory names no repository of its own
mkdir -p $R/repos/shop/.git $R/repos/site/.git $R/stage-x $R/stage-y $R/stage-z $R/stage-n
printf '{"repo": "%s"}\n' $R/repos/shop > $R/stage-x/stage.json   # stages x and y work on shop, z on site
printf '{"repo": "%s"}\n' $R/repos/shop > $R/stage-y/stage.json
printf '{"repo": "%s"}\n' $R/repos/site > $R/stage-z/stage.json
add(){ $B/ask add "$@" > $P.add.out 2> $P.add.err; }

# ---- recording
out=$($B/ask allow --stage stage-y --class "merge, release" --words "«можно накатывать»" --source "chat 06.10, Q-Y-001" \
      "merge after green CI and one review, release")
check "$(echo "$out" | head -1)" "A-Y-001" "allow prints the new id"
echo "$out" | sed -n 2p | grep -q '^A-Y-001 recorded [0-9][0-9]\.[0-9][0-9] [0-9:]*: merge after green CI'; check $? 0 "…and a ready journal line"
F=$R/stage-y/questions.md
grep -q '^## A-Y-001 — merge after green CI' $F && grep -q '^- scope: repo$' $F && grep -q '^- repo: shop$' $F \
  && grep -q '^- class: merge, release$' $F && grep -q '^- words: «можно накатывать»$' $F && grep -q '^- until: not set$' $F
check $? 0 "the entry: scope repo, the stage's repository by name, class keywords, the owner's words, no expiry"
$B/ask allow --stage stage-y --class merge "no words" > /dev/null 2> $P.err; check $? 1 "negative: a permission without the owner's words is refused"
$B/ask allow --stage stage-n --words "ok" --class merge "unknown repo" > /dev/null 2> $P.err; check $? 1 "negative: scope repo and no repository known → refused"
grep -q 'pass --repo' $P.err; check $? 0 "…and says to pass --repo"
$B/ask allow --stage stage-y --words "ok" --scope all --repo shop "x" > /dev/null 2>&1; check $? 1 "negative: --scope all with --repo"
$B/ask allow --stage stage-y --words "ok" --until tomorrow "x" > /dev/null 2>&1; check $? 1 "negative: unparsable --until"
$B/ask list --stage stage-y 2>/dev/null | grep -q '^A-'; check $? 1 "a permission is not an unresolved entry of ask list"
$B/ask search накатывать | grep -q '^A-Y-001'; check $? 0 "ask search finds it by the owner's words"

# ---- scope resolution: the same stage, another stage on the same repository, another repository (DAY-03)
add --stage stage-y --class merge "Merge PR #5?"; check $? 3 "same stage, same class → refused (exit 3)"
grep -q '^ask: covered by A-Y-001 (chat 06.10, Q-Y-001): merge after green CI' $P.add.err; check $? 0 "…\"covered by A-… (<source>)\""
grep -q '^## Q-Y-' $F; check $? 1 "…and nothing is written"
add --stage stage-x --class release "Release shop?"; check $? 3 "another stage, same repository (its stage.json) → refused"
add --stage stage-z --repo shop --class release "Release shop to prod?"; check $? 3 "another repository's stage asking about shop (--repo shop) → refused"
add --stage stage-z --repo $R/repos/shop --class Release "Release shop?"; check $? 3 "…--repo as a path, class in another case → refused"
add --stage stage-z --class release "Release site?"; check $? 0 "negative control: stage z about its own repository site → passes"
grep -q '^- class: release$' $R/stage-z/questions.md; check $? 0 "…the question records its class"

# ---- a question no permission covers; a weak match warns and passes
add --stage stage-x --class migration "Run the migration on shop?"; check $? 0 "another class → passes"
[ -s $P.add.err ]; check $? 1 "…without a warning"
add --stage stage-x "Can I merge the hotfix?"; check $? 0 "no --class, a permission keyword in the text → passes"
grep -q '^ask: may be covered by A-Y-001' $P.add.err; check $? 0 "…with a may-be-covered warning"

# ---- the override
add --stage stage-x --class release --override "the release touches billing" "Release shop with billing?"; check $? 0 "--override adds a covered question"
grep -q '^- override: A-Y-001 — the release touches billing$' $R/stage-x/questions.md; check $? 0 "…and records which permission and why"

# ---- scopes stage and all
$B/ask allow --stage stage-z --scope stage --class deploy --words "деплой сам" "deploy" > /dev/null
add --stage stage-z --class deploy "Deploy?"; check $? 3 "scope stage: its own stage → refused"
add --stage stage-x --repo site --class deploy "Deploy site?"; check $? 0 "scope stage: another stage, even on that repository → passes"
$B/ask allow --stage stage-z --scope all --class docs --words "доки без вопросов" "docs" > /dev/null
add --stage stage-x --class docs "Publish docs?"; check $? 3 "scope all: any stage and repository → refused"

# ---- listing
$B/ask allow --list --stage stage-x > $P.l1
grep -q '^A-Y-001 \[stage-y\] allowed — merge' $P.l1 && grep -q '^A-Z-002 \[stage-z\] allowed — docs' $P.l1; check $? 0 "list --stage x: shop's permission from stage y and the all-repositories one"
grep -q '^A-Z-001' $P.l1; check $? 1 "…not stage z's stage-only permission"
$B/ask allow --list --repo site | grep -q '^A-Y-001'; check $? 1 "list --repo site: not shop's"
$B/ask allow --list --stage stage-n 2>&1 >/dev/null | grep -q 'no standing permission'; check $? 1 "stage n (no repository) still sees the all-repositories one"

# ---- expiry and revocation
$B/ask allow --stage stage-x --class hotfix --until 2000-01-01 --words "до 1 января" "hotfix" > /dev/null
add --stage stage-x --class hotfix "Hotfix?"; check $? 0 "an expired permission no longer covers"
$B/ask allow --list --stage stage-x | grep -q '^A-X-001'; check $? 1 "…and is not listed"
$B/ask allow --list --all | grep -q '^A-X-001 \[stage-x\] expired'; check $? 0 "…list --all shows it as expired"
$B/ask allow --stage stage-x --class hotfix --until 2099-01-01 --words "до 2099" "hotfix" > /dev/null
add --stage stage-x --class hotfix "Hotfix again?"; check $? 3 "a permission with a future --until covers"
$B/ask revoke A-Y-001 --reason "owner took it back" > $P.rv; check $? 0 "revoke"
grep -q '^- status: revoked: owner took it back (20' $F; check $? 0 "…writes revoked with a stamp"
grep -q '^A-Y-001 revoked ' $P.rv; check $? 0 "…prints a journal line"
add --stage stage-x --class merge "Merge PR #6?"; check $? 0 "a revoked permission no longer covers"
$B/ask revoke A-Y-001 > /dev/null 2>&1; check $? 1 "negative: revoking twice"
$B/ask revoke Q-X-001 > /dev/null 2>&1; check $? 1 "negative: revoke of a question"
$B/ask close A-X-002 --answer x > /dev/null 2>&1; check $? 1 "negative: a permission is not a question to close"

# ---- the hub start digest: permissions of the stage's repository, recorded in other stages too; one line when none
$B/hub start --stage stage-x --session 11111111-1111-4111-8111-111111111111 --dry-run > $P.d1 2>&1; check $? 0 "hub start --dry-run (stage x)"
grep -q '^Standing permissions (repo shop; from every stage' $P.d1 && grep -q '^A-X-002 \[stage-x\] hotfix — до 2099 (until 2099-01-01)' $P.d1 \
  && grep -q '^A-Z-002 \[stage-z\] docs — доки без вопросов' $P.d1; check $? 0 "…lists the permissions in force for shop and all repositories"
grep -q '^A-Y-001' $P.d1; check $? 1 "…not the revoked one"
$B/ask allow --stage stage-y --class merge --words "мержи" "merge" > /dev/null
$B/hub start --stage stage-x --session 11111111-1111-4111-8111-111111111111 --dry-run > $P.d2 2>&1
grep -q '^A-Y-002 \[stage-y\] merge — мержи' $P.d2; check $? 0 "…a permission recorded in another stage on the same repository shows"
$B/ask revoke A-Z-002 > /dev/null
$B/hub start --stage stage-z --session 11111111-1111-4111-8111-111111111111 --dry-run > $P.d3 2>&1
grep -q '^A-Z-001 \[stage-z\] deploy' $P.d3; check $? 0 "stage z: its stage-only permission"
mkdir -p $R/stage-w; printf '{"repo": "%s"}\n' $R/repos/site > $R/stage-w/stage.json
$B/hub start --stage stage-w --session 11111111-1111-4111-8111-111111111111 --dry-run > $P.d4 2>&1
check "$(grep -c '^Standing permissions' $P.d4)" 1 "stage w (site, nothing applies)"
grep -q '^Standing permissions (repo site): none — ' $P.d4; check $? 0 "…says so in one line"
exit $fail
