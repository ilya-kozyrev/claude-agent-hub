---
name: status
description: Answer questions about running agents, tasks or stages, who is waiting for the owner, and held locks. Use for “what is running”, “which agents are alive”, “task status”, “who needs an answer”, “что сейчас работает”, “какие агенты живы”, “что с задачами”, “кто ждёт ответа” and “какие блокировки”.
---

# Running work

1. Resolve the plugin root from `PLUGIN_ROOT` (Codex), `CLAUDE_PLUGIN_ROOT` (Claude), or this skill's location
   (two directories above `skills/status`). Run that root's `bin/agent-top --json` through the host's shell tool;
   an unrelated command may shadow it on PATH. This reads the shared hub home and session logs without changing them.
   Use `--stage <stage>` for a named or clearly implied stage (repeatable), otherwise cover every stage.
   Add `--all` when older finished runs matter; `--agent <role> --feed 10` gives one agent's recent activity.
2. Read the fresh snapshot before answering. Group by stage: live agents with role, task/current action and duration,
   relevant finished/failed work since the previous snapshot in this conversation, owner questions and held locks.
   Use `action.elapsed_s` for action duration and `started_at` for run duration; `age_s` is time since the last log
   event, not runtime. Describe native sessions' activity-based liveness as approximate. An unread inbox is a message
   awaiting the agent, not an owner question. `questions_ok: false` means the question register is unavailable.
   Report missing data or command failure as unavailable; an empty successful snapshot means no observed work.
   Infer tasks only from titles, activity, last words or the journal; compare snapshots only when a previous one exists.
3. Answer in a few plain-text lines in the user's language, prioritizing running work and anything needing attention.
   Summarize large stages and offer detail on request. Include question ids when they help the owner answer.
   Keep raw JSON and command names out of the answer unless requested. In Claude Code with mods available, add:
   “`/agent-top` opens the live pane” (in the user's language). Finish after the text answer; status is read-only.
