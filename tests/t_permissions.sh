#!/bin/bash
# Standing permissions (ask allow / revoke / allow --list) and the "covered" check of ask add: a permission is bound to
# the repository the action touches (its origin URL, else its main clone's path) and read from every stage's register
# (docs/standing-permissions.md). Scope resolution, repository identity, every class and every repository covered,
# sensitive classes, invalid entries, expiry, revocation, the refusal and its override, the hub digest.
. "$(dirname "$0")/lib.sh"
new_home; R=$AGENT_HUB_HOME; P=${PERM_OUT:-$(mktemp -d)}/t
cd "$(mktemp -d)"   # outside any repository: the working directory names no repository of its own
G=$R/repos; mkdir -p $G/client-a $G/client-b
for d in client-a/shop client-b/shop site; do git init -q $G/$d && git -C $G/$d commit -q --allow-empty -m init; done
git -C $G/client-a/shop remote add origin git@github.com:client-a/shop.git   # two repositories named shop
git -C $G/client-b/shop remote add origin https://github.com/client-b/shop    # site has no remote: its path is its id
git -C $G/client-a/shop worktree add -q $G/shop-wt 2>/dev/null
A=$G/client-a/shop; SITE=$(cd $G/site && pwd -P)
stage(){ mkdir -p $R/$1; printf '{"repo": "%s"}\n' "$2" > $R/$1/stage.json; }
stage stage-x $A; stage stage-y $A; stage stage-z $G/site; stage stage-q $G/client-b/shop; mkdir -p $R/stage-n
add(){ $B/ask add "$@" > $P.add.out 2> $P.add.err; }
allow(){ $B/ask allow "$@" > /dev/null; }

# ---- recording
out=$($B/ask allow --stage stage-y --class "merge, release" --words "«можно накатывать»" --source "chat 06.10, Q-Y-001" \
      "merge after green CI and one review, release")
check "$(echo "$out" | head -1)" "A-Y-001" "allow prints the new id"
echo "$out" | sed -n 2p | grep -q '^A-Y-001 recorded [0-9][0-9]\.[0-9][0-9] [0-9:]*: merge after green CI'; check $? 0 "…and a ready journal line"
F=$R/stage-y/questions.md
grep -q '^## A-Y-001 — merge after green CI' $F && grep -q '^- scope: repo$' $F && grep -q '^- repo: shop$' $F \
  && grep -q '^- repo-id: github.com/client-a/shop$' $F && grep -q '^- class: merge, release$' $F \
  && grep -q '^- words: «можно накатывать»$' $F && grep -q '^- until: not set$' $F
check $? 0 "the entry: scope repo, the origin URL as the repository id, the short name, class, the owner's words"
$B/ask allow --stage stage-y --class merge "no words" > /dev/null 2> $P.err; check $? 1 "negative: a permission without the owner's words is refused"
$B/ask allow --stage stage-n --words "ok" --class merge "unknown repo" > /dev/null 2> $P.err; check $? 1 "negative: scope repo and no repository known → refused"
grep -q 'pass --repo' $P.err; check $? 0 "…and says to pass --repo"
$B/ask allow --stage stage-y --words "ok" --scope all --repo $A "x" > /dev/null 2>&1; check $? 1 "negative: --scope all with --repo"
$B/ask allow --stage stage-y --words "ok" --until tomorrow "x" > /dev/null 2>&1; check $? 1 "negative: unparsable --until"
$B/ask list --stage stage-y 2>/dev/null | grep -q '^A-'; check $? 1 "a permission is not an unresolved entry of ask list"
$B/ask search накатывать | grep -q '^A-Y-001'; check $? 0 "ask search finds it by the owner's words"
$B/ask digest --stage stage-y | grep -q '^A-Y-001 allowed (repo shop): merge after green CI.* — «можно накатывать»'; check $? 0 "ask digest has a line per permission in force"

# ---- scope resolution: the same stage, another stage on the same repository, another repository (DAY-03)
add --stage stage-y --class merge "Merge PR #5?"; check $? 3 "same stage, same class → refused (exit 3)"
grep -q '^ask: covered by A-Y-001 (chat 06.10, Q-Y-001): merge after green CI' $P.add.err; check $? 0 "…\"covered by A-… (<source>)\""
grep -q "^ask:   the owner's words: «можно накатывать»" $P.add.err && grep -q 'only if these words cover this case' $P.add.err
check $? 0 "…prints the owner's words and to act only where they cover the case"
grep -q '^## Q-Y-' $F; check $? 1 "…and nothing is written"
add --stage stage-x --class release "Release shop?"; check $? 3 "another stage, same repository (its stage.json) → refused"
add --stage stage-z --repo $A --class release "Release shop to prod?"; check $? 3 "another repository's stage naming --repo <path> → refused"
add --stage stage-z --repo $G/shop-wt --class Release "Release shop?"; check $? 3 "…a linked worktree's path resolves to its main clone"
add --stage stage-z --repo https://github.com/client-a/shop.git --class release "Release shop?"; check $? 3 "…the remote URL in another form → refused"
add --stage stage-z --class release "Release site?"; check $? 0 "negative control: stage z about its own repository site → passes"
grep -q '^- class: release$' $R/stage-z/questions.md; check $? 0 "…the question records its class"

# ---- repository identity: two repositories named shop do not share permissions
add --stage stage-q --class merge "Merge the client-b PR?"; check $? 0 "client-b/shop is not client-a/shop: not covered"
add --stage stage-z --repo shop --class merge "Merge shop?"; check $? 1 "an ambiguous short --repo is refused"
grep -q 'ambiguous: .*github.com/client-a/shop.*github.com/client-b/shop\|ambiguous: .*github.com/client-b/shop.*github.com/client-a/shop' $P.add.err; check $? 0 "…naming both candidates"
add --stage stage-z --repo nosuchrepo --class merge "x"; check $? 1 "an unknown short --repo is refused"
allow --stage stage-z --class merge --words "сайт мержи" "merge site"
grep -q "^- repo-id: $SITE\$" $R/stage-z/questions.md; check $? 0 "a repository without a remote: the main clone's path is its id"
add --stage stage-x --repo site --class merge "Merge site?"; check $? 3 "a short name only one known repository has → resolved"

# ---- an explicit port is part of the id (the scp-like git@host:path form has none)
allow --stage stage-p --repo ssh://git@git.example.com:2222/team/tool.git --class merge --words "«мержи tool»" "merge tool"
grep -q '^- repo-id: git.example.com:2222/team/tool$' $R/stage-p/questions.md; check $? 0 "the id keeps the port"
add --stage stage-p --repo ssh://git@git.example.com:3333/team/tool.git --class merge "Merge tool on 3333?"; check $? 0 "another port is another repository: not covered"
add --stage stage-p --repo ssh://git@Git.Example.com:2222/team/tool --class merge "Merge tool on 2222?"; check $? 3 "the same port (host case, .git aside) → refused"
allow --stage stage-p --repo 'ssh://git@[2001:db8::1]:2222/team/tool.git' --class deploy --words "«выкатывай tool»" "deploy tool"
grep -q '^- repo-id: \[2001:db8::1\]:2222/team/tool$' $R/stage-p/questions.md; check $? 0 "an IPv6 host keeps its brackets in the id"
add --stage stage-p --repo 'ssh://git@[2001:db8::1:2222]/team/tool.git' --class deploy "Deploy tool on the other host?"; check $? 0 "…so [2001:db8::1]:2222 and [2001:db8::1:2222] are two repositories"
add --stage stage-p --repo 'ssh://git@[2001:db8::1]:2222/team/tool' --class deploy "Deploy tool?"; check $? 3 "…the same host and port → refused"
allow --stage stage-p --repo git@git.example.com:/srv/tool.git --class release --words "«релизь tool»" "release tool"
grep -q '^- repo-id: git.example.com//srv/tool$' $R/stage-p/questions.md; check $? 0 "an absolute scp-like path keeps its leading /"
add --stage stage-p --repo git@git.example.com:srv/tool.git --class release "Release the home-relative tool?"; check $? 0 "…so host:srv/tool (under the user's home) is another repository"
add --stage stage-p --repo git@git.example.com:/srv/tool --class release "Release tool?"; check $? 3 "…the same absolute path → refused"
for id in $($B/ask allow --list --stage stage-p --repo ssh://git@git.example.com:2222/team/tool.git | grep -E '^A-P-[0-9]+ .* — merge tool' | cut -d' ' -f1); do $B/ask revoke $id > /dev/null; done

# ---- every class and every repository must be covered; sensitive classes need a permission that names them
allow --stage stage-y --class deploy --words "«на стейдж выкатывай»" "deploy to staging"
add --stage stage-x --class "deploy, migration" "Deploy and migrate?"; check $? 0 "a deploy permission does not cover a deploy + migration question"
grep -q '^ask: not covered: migration on shop' $P.add.err; check $? 0 "…and says which class is not covered"
add --stage stage-x --class deploy "Deploy and run the new migration?"; check $? 0 "a migration named only in the text is still a class to cover"
add --stage stage-x --class release "Release with the new billing flow?"; check $? 0 "money in the text: a release permission does not cover it"
add --stage stage-x --repo $A --repo $G/site --class release "Release shop and site?"; check $? 0 "two repositories, one without the permission → not covered"
grep -q '^ask: not covered: release on site' $P.add.err; check $? 0 "…the gap is named (site has merge, not release)"
add --stage stage-x --repo $A --repo $G/site --class merge "Merge shop and site?"; check $? 3 "two repositories, both with a merge permission → refused"
allow --stage stage-y --class "deploy, migration" --words "«миграции на стейдже сами»" "deploy with migrations"
add --stage stage-x --class "deploy, migration" "Deploy and migrate?"; check $? 3 "a permission that names the migration class covers it"
allow --stage stage-y --class rbac-read --words "«читать роли можно»" "read RBAC settings"
add --stage stage-x --class rbac-write "Change the RBAC roles?"; check $? 0 "rbac-read does not cover rbac-write (a sensitive keyword is not reduced to its class)"
grep -q '^ask: not covered: rbac-write on shop' $P.add.err; check $? 0 "…the missing keyword is named"
allow --stage stage-y --class migration-schema --words "«схему мигрируй сам»" "schema migrations"
add --stage stage-x --class migration-data "Run the data migration?"; check $? 0 "migration-schema does not cover migration-data"
add --stage stage-x --class migration-schema "Run the schema migration?"; check $? 3 "…the same keyword covers"
allow --stage stage-y --class release-notes --words "«заметки пиши сам»" "release notes"
add --stage stage-x --class release-notes "Publish the release notes, and the billing change?"; check $? 0 "a covered keyword plus money in the text: still not covered"
LONG="«выкатывай на стейдж сам, $(printf 'и так далее %.0s' $(seq 1 30))но прод по-прежнему только с моего согласия»"
allow --stage stage-y --class deploy-preview --words "$LONG" "deploy previews"
add --stage stage-x --class deploy-preview "Deploy the preview?"; check $? 3 "a long permission covers"
grep -q 'но прод по-прежнему только с моего согласия»$' $P.add.err; check $? 0 "…and the refusal prints the owner's words in full, the restriction at their end included"
for id in $($B/ask allow --list --stage stage-y | grep -E '^A-Y-[0-9]+ .* — (read RBAC|schema migr|release notes|deploy previews)' | cut -d' ' -f1); do $B/ask revoke $id > /dev/null; done

# ---- a question no permission covers; a weak match warns and passes
add --stage stage-x --class hotfix "Ship a hotfix?"; check $? 0 "another class → passes"
add --stage stage-x "Can I merge the hotfix?"; check $? 0 "no --class, a permission keyword in the text → passes"
grep -q '^ask: may be covered by A-Y-001' $P.add.err; check $? 0 "…with a may-be-covered warning"

# ---- the override
add --stage stage-x --class release --override "the owner's words were about the last release" "Release shop?"; check $? 0 "--override adds a covered question"
grep -q "^- override: A-Y-001 — the owner's words were about the last release\$" $R/stage-x/questions.md; check $? 0 "…and records which permission and why"

# ---- scopes stage and all
allow --stage stage-z --scope stage --class publish --words "публикуй сам" "publish"
add --stage stage-z --class publish "Publish?"; check $? 3 "scope stage: its own stage → refused"
add --stage stage-x --repo $G/site --class publish "Publish site?"; check $? 0 "scope stage: another stage, even on that repository → passes"
allow --stage stage-z --scope all --class docs --words "доки без вопросов" "docs"
add --stage stage-x --class docs "Publish docs?"; check $? 3 "scope all: any stage and repository → refused"

# ---- invalid entries cover nothing and are reported
cat >> $R/stage-x/questions.md <<'MD'

## A-X-050 — tag releases by hand
- kind: allow
- status: allowed
- scope: repo
- repo: shop
- repo-id: github.com/client-a/shop
- class: tag
- words: «тегай»
- until: someday

## A-X-051 — bump versions by hand
- kind: allow
- status: allowed
- scope: repo
- repo: shop
- repo-id: github.com/client-a/shop
- class: bump

## A-X-060 — rotate logs by hand
- kind: allow
- status: allowed
- scope: repo
- repo: shop
- repo-id: github.com/client-a/shop
- class: rotate
- words: «логи крути сам»
- until: 2026-10-06Tgarbage

## A-X-070 — prune branches by hand
- kind: allow
- status: allowed
- scope: repo
- repo: shop
- class: prune
- words: «ветки чисти сам»
MD
add --stage stage-x --class tag "Tag the release?"; check $? 0 "an entry with an unparsable until covers nothing"
grep -q "^ask: A-X-050 is invalid (until 'someday' unparsable) and covers nothing" $P.add.err; check $? 0 "…and ask add reports it"
add --stage stage-x --class bump "Bump the version?"; check $? 0 "an entry without the owner's words covers nothing"
add --stage stage-x --class rotate "Rotate the logs?"; check $? 0 "an until with a valid date and garbage after it covers nothing"
grep -q "^ask: A-X-060 is invalid (until '2026-10-06Tgarbage' unparsable)" $P.add.err; check $? 0 "…and is reported"
$B/ask allow --stage stage-x --class rotate --words "ok" --until 2099-01-01Tgarbage "x" > /dev/null 2>&1; check $? 1 "negative: ask allow refuses such an --until"
add --stage stage-x --class prune "Prune the branches?"; check $? 0 "a repo-scope entry without a repo-id covers nothing"
grep -q "^ask: A-X-070 is invalid (scope repo without a repo-id)" $P.add.err; check $? 0 "…and ask add reports it"
$B/ask allow --list --stage stage-x > $P.l0
grep -q "^A-X-050 \[stage-x\] INVALID (until 'someday' unparsable): covers nothing" $P.l0 && grep -q "^A-X-051 \[stage-x\] INVALID (no owner's words)" $P.l0
check $? 0 "ask allow --list marks both invalid"
grep -q "^A-X-070 \[stage-x\] INVALID (scope repo without a repo-id)" $P.l0; check $? 0 "…and the entry without a repo-id, listed for the stage"

# ---- listing
$B/ask allow --list --stage stage-x > $P.l1
grep -q '^A-Y-001 \[stage-y\] allowed — merge' $P.l1 && grep -q '^A-Z-003 \[stage-z\] allowed — docs' $P.l1; check $? 0 "list --stage x: shop's permission from stage y and the all-repositories one"
grep -q '(github.com/client-a/shop)' $P.l1; check $? 0 "…with the repository id"
grep -q '^A-Z-002' $P.l1; check $? 1 "…not stage z's stage-only permission"
$B/ask allow --list --repo $G/site | grep -q '^A-Y-001'; check $? 1 "list --repo site: not shop's"

# ---- expiry and revocation
HX1=$($B/ask allow --stage stage-x --class hotfix --until 2000-01-01 --words "до 1 января" --print-id "hotfix")
add --stage stage-x --class hotfix "Hotfix?"; check $? 0 "an expired permission no longer covers"
$B/ask allow --list --all | grep -q "^$HX1 \[stage-x\] expired"; check $? 0 "…list --all shows it as expired"
HX2=$($B/ask allow --stage stage-x --class hotfix --until 2099-01-01 --words "до 2099" --print-id "hotfix")
add --stage stage-x --class hotfix "Hotfix again?"; check $? 3 "a permission with a future --until covers"
$B/ask revoke A-Y-001 --reason "owner took it back" > $P.rv; check $? 0 "revoke"
grep -q '^- status: revoked: owner took it back (20' $F; check $? 0 "…writes revoked with a stamp"
grep -q '^A-Y-001 revoked ' $P.rv; check $? 0 "…prints a journal line"
add --stage stage-x --class release "Release shop again?"; check $? 0 "a revoked permission no longer covers"
$B/ask revoke A-Y-001 > /dev/null 2>&1; check $? 1 "negative: revoking twice"
$B/ask revoke Q-X-001 > /dev/null 2>&1; check $? 1 "negative: revoke of a question"
$B/ask close A-X-002 --answer x > /dev/null 2>&1; check $? 1 "negative: a permission is not a question to close"

# ---- the hub start digest: permissions of the stage's repository from every stage; one line when none
S1=11111111-1111-4111-8111-111111111111
$B/hub start --stage stage-x --session $S1 --dry-run > $P.d1 2>&1; check $? 0 "hub start --dry-run (stage x)"
grep -q '^Standing permissions (repo shop; act only where' $P.d1 && grep -q "^$HX2 \[stage-x\] hotfix — до 2099 (until 2099-01-01)" $P.d1 \
  && grep -q '^A-Z-003 \[stage-z\] docs — доки без вопросов' $P.d1; check $? 0 "…lists the permissions in force for shop and all repositories"
grep -q '^A-Y-001' $P.d1; check $? 1 "…not the revoked one"
grep '^invalid, cover nothing:' $P.d1 | grep 'A-X-050' | grep 'A-X-051' | grep -q 'A-X-060'; check $? 0 "…names the invalid ones"
grep '^invalid, cover nothing:' $P.d1 | grep -q 'A-X-070'; check $? 0 "…the one without a repo-id too"
mkdir -p $R/stage-w; printf '{"repo": "%s"}\n' $G/client-b/shop > $R/stage-w/stage.json
$B/hub start --stage stage-w --session $S1 --dry-run > $P.d4 2>&1
grep -q '^A-Z-003' $P.d4 && ! grep -q '^A-Y-' $P.d4; check $? 0 "client-b's shop: only the all-repositories one, none of client-a's"
$B/ask revoke A-Z-003 > /dev/null; $B/hub start --stage stage-w --session $S1 --dry-run > $P.d4 2>&1
grep -q '^Standing permissions (repo shop): none — ' $P.d4; check $? 0 "…with that one revoked: none, in one line"
# a long § 0 and many permissions: § 0 and the handoff pointer keep their room, the block is capped
for i in 1 2 3 4 5 6 7; do allow --stage stage-y --class "c$i" --words "«слово $i, достаточно длинное, чтобы строка была полной»" "class number $i of things allowed"; done
C=$R/stage-x/coordinator; mkdir -p $C
{ echo "# Handoff — stage-x"; echo; echo "## 0. First steps for the successor"
  for i in $(seq 1 9); do echo "$i. A step of the handoff that takes most of a line, so that section zero is long enough. END$i"; done
  echo; echo "## 1. Where things stand"; } > $C/HANDOFF-hub-stage-x-2026-10-06-1200.md
printf '{"roles": {"hub": {"session": "%s", "kind": "cli", "tag": "hub-1"}}}\n' 22222222-2222-4222-8222-222222222222 > $R/stage-x/roles.json
$B/hub takeover --stage stage-x --session $S1 --dry-run > $P.d5 2>&1; check $? 0 "hub takeover --dry-run with a long § 0"
sed -n '/^DIGEST/,$p' $P.d5 > $P.d5d
grep -q '^§ 0 of the handoff HANDOFF-hub-stage-x-2026-10-06-1200.md' $P.d5d && grep -q 'END9$' $P.d5d; check $? 0 "…§ 0 is whole, with its pointer"
z=$(grep -n '^§ 0 of the handoff' $P.d5d | cut -d: -f1); p=$(grep -n '^Standing permissions' $P.d5d | cut -d: -f1)
[ -n "$z" ] && [ -n "$p" ] && [ "$z" -lt "$p" ]; check $? 0 "…§ 0 comes before the permissions block (the 3 KB cut drops the tail)"
grep -q '^[0-9][0-9]* more: ask allow --list --stage stage-x$' $P.d5d; check $? 0 "…the permissions block is capped with \"K more\""
blk=$(sed -n '/^Standing permissions/,/^$/p' $P.d5d); n=$(echo "$blk" | grep -c '^A-'); k=$(echo "$blk" | sed -n 's/^\([0-9]*\) more: .*/\1/p')
check "$((n + k)) $([ $n -ge 1 ] && echo some)" "10 some" "…shown + more = the 10 in force, at least one shown"
echo "$blk" | grep -q '…cut'; check $? 1 "…the block fits its budget (no cut)"
check "$(wc -c < $P.d5d | tr -d ' ' | awk '{print ($1<=3072)}')" 1 "…the digest stays ≤ 3 KB"
exit $fail
