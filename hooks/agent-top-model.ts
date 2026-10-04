// Pure helpers of the agent-top mod (hooks/agent-top.tsx): parse the `agent-top --json` snapshot, decide what to poll
// and when, find the events worth a toast, and format the text the pane draws. No `$`, no I/O: unit-testable on its own.

export type AgentState = 'live' | 'done' | 'error' | 'dead'

export type Agent = {
  stage: string
  role: string
  dir_name: string
  title: string
  tag: string
  state: AgentState
  quiet: boolean
  alive: boolean
  kind: string
  parent: string | null
  engine: string
  model: string
  model_id: string | null
  effort: string | null
  age_s: number | null
  runs: number
  turns: number
  run_turns: number
  turns_approx: boolean
  sub_turns: number
  ctx_tokens: number | null
  cost_usd: number | null
  pid: number | null
  cwd: string | null
  archived: boolean
  action: { tool: string; text: string; elapsed_s: number } | null
  last_text: string
  unread: unknown[]
  result: { subtype: string; is_error: boolean; text: string } | null
}

export type Counts = { live: number; done: number; error: number; dead: number }

export type Lock = { kind: string; repo: string; owner_name: string; until: string; active: boolean; why: string }

/**
 * `items` are display lines (the CLI cuts them to 12); `ids` are every open question id of the stage, from the untruncated
 * `ask list`. `ids` is null when the list failed (unknown) or when an older CLI does not send it.
 */
export type StageQuestions = { open: number; overdue: number; line: string; items: string[]; ids: string[] | null }

export type JournalLine = { stage: string; time: string; tag: string; text: string }

export type Snapshot = {
  generated_at: string
  stages: string[]
  counts: Counts
  agents: Agent[]
  locks: Lock[]
  questions: Record<string, StageQuestions>
  /** `ask summary` succeeded on this fetch: an empty `questions` then means no registers, not a failed `ask`. */
  questionsOk: boolean
  limits: { info: { unifiedWindows?: Record<string, { utilization?: number; resetsAt?: number }> }; seen_at: number } | null
  codex_limits: Record<string, { info: unknown; seen_at: number }>
  journal_tail: JournalLine[]
  fetchedAt: number
}

export type FeedItem = { at: string | null; kind: string; sub: boolean; tool: string | null; text: string; detail: string | null }

export type Card = { agent: Agent | null; feed: FeedItem[]; fetchedAt: number }

export type View = 'list' | 'card' | 'journal' | 'summary'

export type Target = { stage: string; dirName: string; role: string }

// ---------------------------------------------------------------- parsing

const isObject = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)
const str = (v: unknown, d = ''): string => (typeof v === 'string' ? v : d)
const numOr = (v: unknown, d: number): number => (typeof v === 'number' && Number.isFinite(v) ? v : d)
const numOrNull = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)

export function toAgent(raw: unknown): Agent | null {
  if (!isObject(raw) || typeof raw.role !== 'string' || typeof raw.stage !== 'string') return null
  const state = raw.state === 'live' || raw.state === 'done' || raw.state === 'error' || raw.state === 'dead' ? raw.state : 'dead'
  const action = isObject(raw.action) ? { tool: str(raw.action.tool), text: str(raw.action.text), elapsed_s: numOr(raw.action.elapsed_s, 0) } : null
  const result = isObject(raw.result)
    ? { subtype: str(raw.result.subtype), is_error: raw.result.is_error === true, text: str(raw.result.text) }
    : null
  return {
    stage: raw.stage,
    role: raw.role,
    dir_name: str(raw.dir_name, raw.role),
    title: str(raw.title),
    tag: str(raw.tag),
    state,
    quiet: raw.quiet === true,
    alive: raw.alive === true,
    kind: str(raw.kind, 'headless'),
    parent: typeof raw.parent === 'string' ? raw.parent : null,
    engine: str(raw.engine, 'claude'),
    model: str(raw.model),
    model_id: typeof raw.model_id === 'string' ? raw.model_id : null,
    effort: typeof raw.effort === 'string' ? raw.effort : null,
    age_s: numOrNull(raw.age_s),
    runs: numOr(raw.runs, 0),
    turns: numOr(raw.turns, 0),
    run_turns: numOr(raw.run_turns, numOr(raw.turns, 0)),
    turns_approx: raw.turns_approx === true,
    sub_turns: numOr(raw.sub_turns, 0),
    ctx_tokens: numOrNull(raw.ctx_tokens),
    cost_usd: numOrNull(raw.cost_usd),
    pid: numOrNull(raw.pid),
    cwd: typeof raw.cwd === 'string' ? raw.cwd : null,
    archived: raw.archived === true,
    action,
    last_text: str(raw.last_text),
    unread: Array.isArray(raw.unread) ? raw.unread : [],
    result,
  }
}

/** Parses `agent-top --json` stdout. Throws an Error whose message is fit for the pane's one dim line. */
export function parseSnapshot(stdout: string, fetchedAt: number): Snapshot {
  let data: unknown
  try {
    data = JSON.parse(stdout)
  } catch {
    throw new Error('agent-top printed no JSON')
  }
  if (!isObject(data) || !Array.isArray(data.agents) || !isObject(data.counts)) {
    throw new Error('unexpected agent-top output (no agents/counts)')
  }
  const agents = data.agents.map(toAgent).filter((a): a is Agent => a !== null)
  const c = data.counts
  const questions: Record<string, StageQuestions> = {}
  if (isObject(data.questions)) {
    for (const [stage, q] of Object.entries(data.questions)) {
      if (!isObject(q)) continue
      questions[stage] = {
        open: numOr(q.open, 0),
        overdue: numOr(q.overdue, 0),
        line: str(q.line, stage),
        items: Array.isArray(q.items) ? q.items.filter((x): x is string => typeof x === 'string') : [],
        ids: Array.isArray(q.ids) ? q.ids.filter((x): x is string => typeof x === 'string') : null,
      }
    }
  }
  const locks: Lock[] = Array.isArray(data.locks)
    ? data.locks.filter(isObject).map(l => ({
        kind: str(l.kind),
        repo: str(l.repo),
        owner_name: str(l.owner_name),
        until: str(l.until),
        active: l.active === true,
        why: str(l.why),
      }))
    : []
  const journal: JournalLine[] = Array.isArray(data.journal_tail)
    ? data.journal_tail.filter(isObject).map(j => ({ stage: str(j.stage), time: str(j.time), tag: str(j.tag), text: str(j.text) }))
    : []
  const limits = isObject(data.limits) && isObject(data.limits.info) ? (data.limits as Snapshot['limits']) : null
  const codex: Snapshot['codex_limits'] = {}
  if (isObject(data.codex_limits)) {
    for (const [id, rec] of Object.entries(data.codex_limits)) {
      if (isObject(rec)) codex[id] = { info: rec.info, seen_at: numOr(rec.seen_at, 0) }
    }
  }
  return {
    generated_at: str(data.generated_at),
    stages: Array.isArray(data.stages) ? data.stages.filter((s): s is string => typeof s === 'string') : [],
    counts: { live: numOr(c.live, 0), done: numOr(c.done, 0), error: numOr(c.error, 0), dead: numOr(c.dead, 0) },
    agents,
    locks,
    questions,
    questionsOk: data.questions_ok === true,
    limits,
    codex_limits: codex,
    journal_tail: journal,
    fetchedAt,
  }
}

/** Parses the card call: the agent's row (if the CLI listed it) and its feed. Throws like parseSnapshot. */
export function parseCard(stdout: string, dirName: string, fetchedAt: number): Card {
  let data: unknown
  try {
    data = JSON.parse(stdout)
  } catch {
    throw new Error('agent-top printed no JSON')
  }
  if (!isObject(data) || !isObject(data.feed) || !Array.isArray(data.feed.items)) throw new Error('unexpected agent-top output (no feed)')
  const rows = Array.isArray(data.agents) ? data.agents.map(toAgent).filter((a): a is Agent => a !== null) : []
  const feed = data.feed.items.filter(isObject).map(it => ({
    at: typeof it.at === 'string' ? it.at : null,
    kind: str(it.kind),
    sub: it.sub === true,
    tool: typeof it.tool === 'string' ? it.tool : null,
    text: str(it.text),
    detail: typeof it.detail === 'string' ? it.detail : null,
  }))
  const wanted = str(data.feed.agent, dirName)
  return { agent: rows.find(a => a.dir_name === wanted) ?? rows.find(a => a.dir_name === dirName) ?? null, feed, fetchedAt }
}

// ---------------------------------------------------------------- the command's arguments

export type CommandArgs = { role: string | null; stages: string[]; isAll: boolean }

/** `/agent-top [role] [--stage S]... [--all]` (also `--stage=S`). Unknown flags are ignored. */
export function parseArgs(text: string): CommandArgs {
  const words = text.split(/\s+/).filter(Boolean)
  const out: CommandArgs = { role: null, stages: [], isAll: false }
  for (let i = 0; i < words.length; i += 1) {
    const w = words[i]
    if (w === '--all') out.isAll = true
    else if (w === '--stage') {
      if (i + 1 < words.length) out.stages.push(words[(i += 1)])
    } else if (w.startsWith('--stage=')) {
      if (w.length > 8) out.stages.push(w.slice(8))
    } else if (!w.startsWith('-') && out.role === null) out.role = w
  }
  return out
}

/** argv tail of `agent-top --once` for the same arguments (the text fallback where nothing draws). */
export function onceArgs(a: CommandArgs): string[] {
  const out = ['--once', '--width', '100']
  for (const s of a.stages) out.push('--stage', s)
  if (a.isAll) out.push('--all')
  if (a.role) out.push('--agent', a.role)
  return out
}

/** The dev copy of the mod is tested beside the installed agent-hub, whose skill `agent-top` then owns the plain name. */
const DEV_PLUGIN = 'agent-top-dev'
const DEV_ALSO_ANSWERS = 'agent-hub:agent-top'

/**
 * Whether `/command` is this module's: bare `agent-top`, `<this plugin>:agent-top`, and, in the dev copy only,
 * `agent-hub:agent-top`. Every other `<x>:agent-top` belongs to another plugin.
 */
export function isOwnCommand(command: string, pluginName: string): boolean {
  return command === 'agent-top' || command === `${pluginName}:agent-top` || (pluginName === DEV_PLUGIN && command === DEV_ALSO_ANSWERS)
}

// ---------------------------------------------------------------- polling plan

export const TICK_MS = 3000
export const IDLE_MS = 15000

export type Plan = { watch: boolean; extra: 'card' | 'all' | null }

/**
 * What one refresh runs. The "watch" call (default view, every stage) feeds the status line and the toasts, so it
 * runs every tick while the pane shows it and every IDLE_MS otherwise. The "extra" call feeds only the pane: the
 * card (one agent, its feed) or the all-agents list.
 */
export function planRun(i: { now: number; lastWatchAt: number; isOpen: boolean; view: View; isAll: boolean; hasTarget: boolean; force: boolean }): Plan {
  const extra: Plan['extra'] = !i.isOpen ? null : i.view === 'card' ? (i.hasTarget ? 'card' : null) : i.isAll ? 'all' : null
  const isIdleDue = i.now - i.lastWatchAt >= IDLE_MS - TICK_MS / 2
  const watch = (i.isOpen && extra === null) || isIdleDue || (i.force && extra === null)
  return { watch, extra }
}

// ---------------------------------------------------------------- status line and toasts

export function statusText(s: Snapshot | null): string | undefined {
  if (!s || s.agents.length === 0) return undefined
  return `agents ● ${s.counts.live} ✓ ${s.counts.done} ✗ ${s.counts.error + s.counts.dead}`
}

export const agentKey = (a: Pick<Agent, 'stage' | 'dir_name'>): string => `${a.stage}/${a.dir_name}`
/**
 * What the toasts diff against next time. `questions` maps a stage to the set of open question ids last seen there
 * (null: that stage's set is unknown); the whole field is null until the first snapshot whose `ask` data was good, which
 * sets the baseline silently. A snapshot with `questionsOk` false leaves the memory of questions as it was, and a stage
 * whose ids are unknown keeps its previous set. After the baseline, a stage missing from the snapshot counts as empty.
 */
export type Memory = {
  states: Record<string, { state: AgentState; runs: number }>
  questions: Record<string, string[] | null> | null
}

export function remember(s: Snapshot, prev?: Memory): Memory {
  const states: Memory['states'] = {}
  for (const a of s.agents) states[agentKey(a)] = { state: a.state, runs: a.runs }
  if (!s.questionsOk) return { states, questions: prev?.questions ?? null }
  const questions: Record<string, string[] | null> = {}
  for (const [stage, q] of Object.entries(s.questions)) questions[stage] = q.ids ?? prev?.questions?.[stage] ?? null
  return { states, questions }
}

/** Question toasts per stage before the rest fold into one "N more new questions" line. */
const MAX_NEW_QUESTIONS = 3

/** An agent first seen already finished this recently counts as just finished (it ran between two polls). */
const FRESH_S = 30

export function endNotice(a: Agent): string {
  const who = `${a.role} · ${a.stage}`
  if (a.state === 'done') return `✓ ${who} finished`
  if (a.state === 'error') return `✗ ${who} failed` + (a.result?.text ? `: ${clip(oneLine(a.result.text), 60)}` : '')
  return `✗ ${who} died`
}

/**
 * Toast texts for what changed since `prev`: an agent that finished, failed or died (also one that was resumed and ended
 * again between two polls: its `runs` grew), and each open owner question id that the stage's remembered set lacks.
 */
export function notices(prev: Memory, s: Snapshot): string[] {
  const out: string[] = []
  for (const a of s.agents) {
    if (a.state === 'live') continue
    const was = prev.states[agentKey(a)]
    const isJustEnded =
      was === undefined ? a.age_s !== null && a.age_s <= FRESH_S && !a.archived : was.state === 'live' || a.runs > was.runs
    if (isJustEnded) out.push(endNotice(a))
  }
  if (prev.questions === null || !s.questionsOk) return out
  for (const [stage, q] of Object.entries(s.questions)) {
    const before = prev.questions[stage]
    if (q.ids === null || before === null) continue // unknown now or before: no baseline to diff against
    const known = new Set(before ?? [])
    const fresh = q.ids.filter(id => !known.has(id))
    for (const id of fresh.slice(0, MAX_NEW_QUESTIONS)) {
      const line = q.items.find(l => l === id || l.startsWith(`${id} `)) ?? id
      out.push(`? ${stage}: new question ${clip(oneLine(line), 80)}`)
    }
    if (fresh.length > MAX_NEW_QUESTIONS) out.push(`? ${stage}: ${fresh.length - MAX_NEW_QUESTIONS} more new questions`)
  }
  return out
}

/** At most `max` toasts per snapshot; the rest fold into one line. */
export function capToasts(texts: string[], max = 3): string[] {
  return texts.length <= max ? texts : [...texts.slice(0, max - 1), `+${texts.length - (max - 1)} more events (open /agent-top)`]
}

// ---------------------------------------------------------------- stage filter (client side)

export function inStages<T extends { stage: string }>(rows: readonly T[], stages: readonly string[]): T[] {
  return stages.length === 0 ? [...rows] : rows.filter(r => stages.includes(r.stage))
}

export function countsOf(agents: readonly Agent[]): Counts {
  const c: Counts = { live: 0, done: 0, error: 0, dead: 0 }
  for (const a of agents) c[a.state] += 1
  return c
}

// ---------------------------------------------------------------- formatting

export const oneLine = (s: string): string => s.replace(/\s+/g, ' ').trim()

export function clip(s: string, w: number): string {
  const chars = Array.from(s)
  if (w <= 0) return ''
  if (chars.length <= w) return s
  return w === 1 ? '…' : chars.slice(0, w - 1).join('') + '…'
}

export const padEnd = (s: string, w: number): string => {
  const n = Array.from(s).length
  return n >= w ? s : s + ' '.repeat(w - n)
}

/** Word wrap to `width`, at most `maxLines` lines (the last one clipped with an ellipsis). */
export function wrapLines(text: string, width: number, maxLines = 2): string[] {
  const w = Math.max(8, width)
  const words = oneLine(text).split(' ').filter(Boolean)
  const lines: string[] = []
  let cur = ''
  for (const word of words) {
    const next = cur ? `${cur} ${word}` : word
    if (Array.from(next).length <= w) cur = next
    else {
      if (cur) lines.push(cur)
      cur = Array.from(word).length > w ? clip(word, w) : word
    }
  }
  if (cur) lines.push(cur)
  if (lines.length > maxLines) {
    const kept = lines.slice(0, maxLines)
    kept[maxLines - 1] = clip(kept[maxLines - 1] + ' …', w)
    return kept
  }
  return lines.length ? lines : ['']
}

export function fmtAge(s: number | null): string {
  if (s === null) return '—'
  const n = Math.max(0, Math.floor(s))
  if (n < 60) return `${n}s`
  if (n < 3600) return `${Math.floor(n / 60)}m`
  if (n < 86400) return `${Math.floor(n / 3600)}h${String(Math.floor((n % 3600) / 60)).padStart(2, '0')}`
  return `${Math.floor(n / 86400)}d`
}

export function fmtK(n: number | null): string {
  if (!n) return '—'
  if (n < 1000) return String(n)
  if (n < 1_000_000) return `${Math.round(n / 1000)}k`
  return `${(n / 1_000_000).toFixed(1)}M`
}

export const fmtCost = (c: number | null): string => (c === null ? '—' : `$${c.toFixed(2)}`)

export function modelLabel(a: Agent): string {
  const m = (a.model_id ?? a.model ?? '?').replace(/^claude-/, '').replace(/-\d{8}$/, '') || '?'
  const eff = ({ low: 'lo', medium: 'md', high: 'hi', xhigh: 'xh', max: 'mx' } as Record<string, string>)[a.effort ?? ''] ?? ''
  return eff ? `${m}/${eff}` : m
}

export function turnsLabel(a: Agent): string {
  const total = `${a.turns}${a.turns_approx ? '+' : ''}`
  return a.run_turns === a.turns ? total : `${a.run_turns}/${total}`
}

/** The agent's title without the trailing "(tag)" that `agent spawn` appends. */
export function taskText(a: Agent): string {
  let t = oneLine(a.title)
  if (a.tag && t.endsWith(`(${a.tag})`)) t = t.slice(0, t.length - a.tag.length - 2).trimEnd()
  return t || '—'
}

export const stateWord = (a: Agent): string => (a.quiet && a.state === 'live' ? 'quiet' : a.state === 'dead' ? 'died' : a.state)

export const glyphOf = (a: Agent): string => (a.state === 'live' ? '●' : a.state === 'done' ? '✓' : '✗')

/** The colour the console uses: live green, error/died red, quiet yellow, done dim (undefined = dim, no colour). */
export function colorOf(a: Agent): string | undefined {
  if (a.state === 'live') return a.quiet ? 'yellow' : 'green'
  return a.state === 'done' ? undefined : 'red'
}

export function actionText(a: Agent): string {
  if (!a.action) return ''
  const el = a.action.elapsed_s
  return `▸ ${a.action.tool}: ${oneLine(a.action.text)}` + (el >= 10 ? `  (${fmtAge(el)})` : '')
}

/** What the agent is doing now (live) or said last (finished), one line. */
export function nowText(a: Agent): string {
  if (a.alive) return a.action ? actionText(a) : a.last_text ? `⋯ ${oneLine(a.last_text)}` : '⋯ thinking'
  if (a.result && (a.state === 'done' || a.state === 'error')) return oneLine(a.last_text || a.result.text || a.result.subtype)
  if (a.last_text) return oneLine(a.last_text)
  if (a.kind === 'subagent') return 'no completion notice: its parent session ended or it was stopped'
  return 'no process, no result: died or was killed'
}

export function feedPrefix(it: FeedItem): string {
  const t = it.at ? `${it.at} ` : ''
  return it.sub ? `${t}↳ ` : t
}

export function feedLine(it: FeedItem): { mark: string; text: string; color?: string; dim?: boolean; bold?: boolean } {
  switch (it.kind) {
    case 'thinking':
      return { mark: '✎', text: it.text, dim: true }
    case 'text':
      return { mark: '✎', text: it.text }
    case 'tool':
      return { mark: '▸', text: `${it.tool ?? 'tool'}: ${it.text}` }
    case 'result':
      return { mark: '  ◂', text: it.text, dim: true }
    case 'result_err':
      return { mark: '  ◂', text: it.text, color: 'red' }
    case 'input':
      return { mark: '→', text: it.text, color: 'yellow' }
    case 'end':
      return { mark: '■', text: `end of run: ${it.text}`, bold: true }
    default:
      return { mark: '⚙', text: it.text, dim: true }
  }
}

// ---------------------------------------------------------------- plan limits

export type LimitWindow = { label: string; percent: number; resetsAt: number | null }

const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)

export function claudeWindows(s: Snapshot): LimitWindow[] {
  const w = s.limits?.info?.unifiedWindows
  if (!w) return []
  const out: LimitWindow[] = []
  for (const [key, label] of [['five_hour', '5h'], ['seven_day', '7d']] as const) {
    const one = w[key]
    if (one && finite(one.utilization)) out.push({ label, percent: Math.round(100 * one.utilization), resetsAt: finite(one.resetsAt) ? one.resetsAt : null })
  }
  return out
}

export function codexWindows(info: unknown): LimitWindow[] {
  if (!isObject(info)) return []
  const out: LimitWindow[] = []
  for (const key of ['primary', 'secondary']) {
    const w = info[key]
    if (!isObject(w) || !finite(w.used_percent) || w.used_percent < 0) continue
    const m = w.window_minutes
    let label = key
    if (finite(m) && m > 0) label = m % 1440 === 0 ? `${m / 1440}d` : m % 60 === 0 ? `${m / 60}h` : `${m}m`
    out.push({ label, percent: Math.round(w.used_percent * 10) / 10, resetsAt: finite(w.resets_at) ? w.resets_at : null })
  }
  return out
}

/** "10-09 14:30" in the local time zone. */
export function fmtReset(epochSeconds: number): string {
  const d = new Date(epochSeconds * 1000)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

export function limitLine(w: LimitWindow): string {
  return `${w.label}: ${w.percent}% used` + (w.resetsAt !== null ? `, resets ${fmtReset(w.resetsAt)}` : '')
}

/** The role's agent for `/agent-top <role>`: the live one first, else the freshest that is not archived. */
export function findByRole(agents: readonly Agent[], name: string, stages: readonly string[]): Agent | null {
  const rank = (a: Agent) => (a.archived ? 2 : 0) + (a.state === 'live' ? 0 : 1)
  const cands = agents.filter(a => (a.role === name || a.dir_name === name) && (stages.length === 0 || stages.includes(a.stage)))
  cands.sort((x, y) => rank(x) - rank(y) || (x.age_s ?? Infinity) - (y.age_s ?? Infinity))
  return cands[0] ?? null
}
