# Hub rules — <project>

<!-- Copy to <repo>/.agent-hub/hub-rules.md (or the hub home, or <hub home>/<stage>/) and edit. The hub skill reads
every layer before planning — hub home, then the repository, then the stage; a later file wins on the same subject.
A rule here replaces the skill's recommended rule of the same number or subject; anything else adds to them.
Say why for each rule: the next hub keeps a rule it understands. -->

## Replaces
- **6. Handoff size.** Write the handoff at ~60k tokens. *Why:* our hubs run on a 200k-token window.
- **5. Review rounds.** Two rounds, then the hub decides. *Why:* our reviews are cheap and fast; a third round has
  never found a blocker.

## Adds
- **Customer data never leaves the staging database.** Agents query it read-only; an export goes to the owner as
  `ask add`. *Why:* a contract clause.
- **Deploys only from the `deploy-window` lock holder**, and only between 10:00 and 16:00 on weekdays. *Why:* support
  is staffed then.
