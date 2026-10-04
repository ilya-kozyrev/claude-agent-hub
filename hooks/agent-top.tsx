// agent-top as a Claude Code mod: the headless agents of the agent-hub plugin, live in a pane.
//
//   /agent-top [role] [--stage S] [--all]   opens the pane (a role opens that agent's card)
//   pane views: Agents (a) · agent card (header + live feed) · Journal (j) · Summary (s: locks, owner questions, plan limits)
//   status line: `agents ● 2 ✓ 5 ✗ 1`; toasts when an agent finishes, fails or dies and when a new owner question opens
//
// Read-only. Data comes only from the plugin's own CLI, `bin/agent-top --json`; nothing is written anywhere. The module is
// plugin-name-agnostic (no $.state, no hard-coded plugin name): state lives in this closure, and a hot reload starts it over.
// Needs Claude Code with mods (2.1.287+). Older CLIs ignore the module; the skill `agent-top` keeps working there.
import type { EngineInterface, Register, Timer } from 'claude-code'

import {
  TICK_MS,
  agentKey,
  actionText,
  capToasts,
  claudeWindows,
  clip,
  codexWindows,
  colorOf,
  countsOf,
  feedLine,
  feedPrefix,
  findByRole,
  fmtAge,
  fmtCost,
  fmtK,
  glyphOf,
  inStages,
  isOwnCommand,
  limitLine,
  modelLabel,
  notices,
  nowText,
  oneLine,
  onceArgs,
  parseArgs,
  parseCard,
  parseSnapshot,
  planRun,
  remember,
  stateWord,
  statusText,
  taskText,
  turnsLabel,
  wrapLines,
} from './agent-top-model'
import type { Agent, Card, CommandArgs, Memory, Snapshot, Target, View } from './agent-top-model'

type Api = EngineInterface

const PANE = 'agent-top'
const INLINE_ROWS = 22 // rows we fill when the pane sits above the prompt (it grows with the tree up to a limit)
const MAX_AGENT_ROWS = 60
const CALL_TIMEOUT_MS = 25000
const SKILL_HINT = 'agent-top: the mod needs bin/agent-top of the agent-hub plugin'

type Called = { ok: true; stdout: string } | { ok: false; error: string; isMissing: boolean }

const firstLine = (s: string): string => clip(oneLine(s.split('\n').find(l => l.trim() !== '') ?? ''), 140)

let snap: Snapshot | null = null // the default view, every stage: feeds the status line and the toasts
let allSnap: Snapshot | null = null // the same with --all, only while the pane shows it
let card: Card | null = null
let view: View = 'list'
let target: Target | null = null
let stages: string[] = []
let isAll = false
let isOpen = false
let isMissing = false
let running: Promise<void> | null = null // the refresh in flight
let isForced = false
let error: string | null = null
let lastWatchAt = -Infinity
let lastStatus: string | undefined
let memory: Memory | null = null // null until the first snapshot of the session: that one never toasts
let timer: Timer | null = null

// ---------------------------------------------------------------- data

async function callCli($: Api, args: string[]): Promise<Called> {
  const bin = `${$.plugin.root}/bin/agent-top`
  try {
    const r = await $.process.run([bin, ...args], { timeoutMs: CALL_TIMEOUT_MS, env: { PYTHONDONTWRITEBYTECODE: '1' } })
    if (r.exitCode === 127) return { ok: false, error: `${SKILL_HINT} (${bin} cannot run)`, isMissing: true }
    if (r.exitCode !== 0) return { ok: false, error: firstLine(r.stderr) || `agent-top exited with ${r.exitCode}`, isMissing: false }
    return { ok: true, stdout: r.stdout }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    const isGone = /ENOENT|no such file|not found|cannot start|spawn/i.test(msg)
    return { ok: false, error: isGone ? `${SKILL_HINT} (${bin} is missing)` : `agent-top: ${clip(oneLine(msg), 100)}`, isMissing: isGone }
  }
}

const stopPolling = (): void => {
  timer?.cancel()
  timer = null
}

function giveUp($: Api, message: string): void {
  isMissing = true
  error = message
  stopPolling()
  if (lastStatus !== undefined) {
    lastStatus = undefined
    $.ui.status(undefined)
  }
}

function applyWatch($: Api, s: Snapshot): void {
  snap = s
  lastWatchAt = s.fetchedAt
  const text = statusText(s)
  if (text !== lastStatus) {
    lastStatus = text
    $.ui.status(text)
  }
  if (memory !== null) for (const t of capToasts(notices(memory, s))) $.ui.toast(t)
  memory = remember(s, memory ?? undefined)
}

async function runOnce($: Api, isForce: boolean): Promise<void> {
  const now = await $.clock.now()
  const plan = planRun({ now, lastWatchAt, isOpen, view, isAll, hasTarget: target !== null, force: isForce })
  if (!plan.watch && plan.extra === null) return
  const errors: string[] = []
  let isGone = false
  const note = (c: Called & { ok: false }): void => {
    errors.push(c.error)
    if (c.isMissing) isGone = true
  }
  if (plan.extra === 'card' && target) {
    const t = target
    const c = await callCli($, ['--json', ...(isAll ? ['--all'] : []), '--agent', t.dirName, '--stage', t.stage, '--feed', '30'])
    if (c.ok) {
      try {
        card = parseCard(c.stdout, t.dirName, now)
      } catch (err) {
        errors.push(err instanceof Error ? err.message : String(err))
      }
    } else note(c)
  } else if (plan.extra === 'all' && !isGone) {
    const c = await callCli($, ['--json', '--all'])
    if (c.ok) {
      try {
        allSnap = parseSnapshot(c.stdout, now)
      } catch (err) {
        errors.push(err instanceof Error ? err.message : String(err))
      }
    } else note(c)
  }
  if (plan.watch && !isGone) {
    const c = await callCli($, ['--json'])
    if (c.ok) {
      try {
        applyWatch($, parseSnapshot(c.stdout, now))
      } catch (err) {
        errors.push(err instanceof Error ? err.message : String(err))
      }
    } else note(c)
  }
  if (isGone) giveUp($, errors[0] ?? SKILL_HINT)
  else error = errors[0] ?? null
  $.ui.invalidate('ui.render')
}

async function refreshLoop($: Api, isForce: boolean): Promise<void> {
  try {
    let again = isForce
    do {
      again = again || isForced
      isForced = false
      await runOnce($, again)
      again = false
    } while (isForced)
  } catch (err) {
    error = `agent-top: ${clip(oneLine(err instanceof Error ? err.message : String(err)), 100)}`
    $.ui.invalidate('ui.render')
  }
}

/**
 * One refresh; never two in flight. A forced one asked while another runs makes that one run once more, and the
 * promise returned settles when it is done: the caller then sees the data its press asked for.
 */
function refresh($: Api, isForce: boolean): Promise<void> {
  if (running !== null) {
    if (isForce) isForced = true
    return running
  }
  if (isMissing && !isForce) return Promise.resolve()
  running = refreshLoop($, isForce).finally(() => {
    running = null
  })
  return running
}

async function hasSurface($: Api): Promise<boolean> {
  try {
    return (await $.session.surfaces()).length > 0
  } catch {
    return true // cannot tell: assume somebody looks
  }
}

/** The engine's own record of the pane survives a reload of this module; the flag also follows ui.render / ui.close. */
async function syncPane($: Api): Promise<void> {
  try {
    isOpen = (await $.ui.panes()).some(p => p.id === PANE && p.isPlaced)
  } catch {
    // keep the flag as it is
  }
}

async function tick($: Api): Promise<void> {
  if (running !== null || isMissing) return
  if (!(await hasSurface($))) return
  await syncPane($)
  await refresh($, false)
}

function startPolling($: Api): void {
  if (timer === null) timer = $.clock.every(TICK_MS, () => void tick($))
}

function openCard($: Api, a: Pick<Agent, 'stage' | 'dir_name' | 'role'>): Promise<void> {
  target = { stage: a.stage, dirName: a.dir_name, role: a.role }
  card = null
  view = 'card'
  $.ui.invalidate('ui.render')
  return refresh($, true)
}

function go($: Api, next: View): void {
  view = next
  $.ui.invalidate('ui.render')
  void refresh($, true)
}

// ---------------------------------------------------------------- the command and its lifecycle

const countsLine = (s: Snapshot | null): string =>
  s ? `● ${s.counts.live} ✓ ${s.counts.done} ✗ ${s.counts.error + s.counts.dead}` : 'no data yet'

async function onceText($: Api, a: CommandArgs): Promise<string> {
  const c = await callCli($, onceArgs(a))
  return c.ok ? c.stdout.trimEnd() : c.error
}


export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    try {
      await $.command.register({
        name: 'agent-top',
        description: 'Show the headless agents live in a pane (read-only)',
        argumentHint: '[role] [--stage S] [--all]',
        immediate: true,
      })
    } catch (err) {
      $.ui.log(`agent-top: could not register /agent-top: ${err instanceof Error ? err.message : String(err)}`, { to: 'debug' })
    }
    await syncPane($)
    startPolling($)

    return next(e)
  })

  // Bare `agent-top` is the command this module registers. A plugin that ships a skill of that name (agent-hub does) gets
  // the registration refused, and `/agent-top` then runs as the skill's `<plugin>:agent-top`: that run is answered here,
  // before the skill's prompt is expanded, so the skill stays what it is for hosts without mods. Only this plugin's own
  // `<name>:agent-top` counts, and the dev copy (plugin `agent-top-dev`) also answers `agent-hub:agent-top`, the installed skill
  // it is tested beside; another plugin's command of that name goes on to the engine.
  on('command.run', async ($, e, next) => {
    if (!isOwnCommand(e.command, $.plugin.name)) return next(e)
    const args = parseArgs(e.args)
    if (!(await hasSurface($))) return { text: await onceText($, args) }

    stages = args.stages
    isAll = args.isAll
    isMissing = false
    error = null
    view = 'list'
    target = null
    card = null
    allSnap = null
    startPolling($)

    const opened = await $.ui.open({ id: PANE, title: 'Agents', focus: true })
    if (!opened.isPlaced) return { text: await onceText($, args) }
    isOpen = true
    $.ui.invalidate('ui.render')
    await refresh($, true)

    let notFound = ''
    if (args.role !== null) {
      const found = findByRole((isAll && allSnap ? allSnap : snap)?.agents ?? [], args.role, stages)
      if (found) {
        await openCard($, found)
      } else if (snap || allSnap) notFound = `no agent "${args.role}"${stages.length ? ` in ${stages.join(', ')}` : ''}; `
    }
    const tail = error ? `${notFound}${error}` : `${notFound}${countsLine(snap)}`

    return { text: `agent-top pane opened: ${tail}` }
  })

  on('ui.close', async ($, e, next) => {
    const done = await next(e)
    if (e.id === PANE) isOpen = false

    return done
  })

  // ---------------------------------------------------------------- the pane

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    isOpen = true
    const { Box, Text, Button } = $.ui.resolve(e)
    const cols = Math.max(24, e.props.bodyColumns)
    const rows = e.props.placement === 'dock' ? Math.max(8, e.props.scroll.bodyRows) : INLINE_ROWS
    const shown = isAll && allSnap ? allSnap : snap
    const agents = shown ? inStages(shown.agents, stages) : []
    const isMulti = new Set(agents.map(a => a.stage)).size > 1
    const counts = shown ? (stages.length ? countsOf(agents) : shown.counts) : null
    const failed = counts ? counts.error + counts.dead : 0

    const text = (s: string, o: { color?: string; dim?: boolean; bold?: boolean } = {}) => (
      <Text color={o.color} dimColor={o.dim} bold={o.bold}>
        {clip(s, cols)}
      </Text>
    )
    const navButton = (key: string, label: string, hotkey: string, isActive: boolean, onPress: () => void) => (
      <Button key={key} label={label} hotkey={hotkey} plain dimColor={!isActive} onPress={onPress} />
    )

    // ---- header and navigation
    const header = (
      <Box flexDirection="row" columnGap={1}>
        <Text bold>agent-top</Text>
        <Text color="green">{`● ${counts?.live ?? 0}`}</Text>
        <Text dimColor>{`✓ ${counts?.done ?? 0}`}</Text>
        <Text color={failed ? 'red' : undefined} dimColor={!failed}>
          {`✗ ${failed}`}
        </Text>
        <Text dimColor>{clip(`${stages.length ? stages.join('/') : 'all stages'}${shown ? ` · ${shown.generated_at.slice(11, 19)}` : ''}`, Math.max(4, cols - 22))}</Text>
      </Box>
    )
    const nav = (
      <Box flexDirection="row" columnGap={2}>
        {navButton('view-agents', 'Agents', 'a', view === 'list' || view === 'card', () => go($, 'list'))}
        {navButton('view-journal', 'Journal', 'j', view === 'journal', () => go($, 'journal'))}
        {navButton('view-summary', 'Summary', 's', view === 'summary', () => go($, 'summary'))}
        <Button key="refresh" label="Refresh" hotkey="r" plain dimColor onPress={() => void refresh($, true)} />
        {view === 'card' ? (
          <Button key="back" label="Back" hotkey="b" plain onPress={() => go($, 'list')} />
        ) : view === 'list' ? (
          <Button
            key="toggle-all"
            label={isAll ? 'Recent only' : 'Include old'}
            hotkey="l"
            plain
            dimColor
            onPress={() => {
              isAll = !isAll
              allSnap = null
              go($, 'list')
            }}
          />
        ) : null}
      </Box>
    )
    const errorLine = error ? text(`! ${error}`, { dim: true }) : null
    const chrome = 2 + (errorLine ? 1 : 0)

    // ---- views
    let body: unknown[] = []

    if (view === 'list') {
      if (!shown) body = [text(error ? '' : 'loading agents…', { dim: true })]
      else if (agents.length === 0) {
        body = [text(`no agents${stages.length ? ` in ${stages.join(', ')}` : ''}${isAll ? '' : ' (l: include finished agents older than 24 h)'}`, { dim: true })]
      } else {
        const lines: unknown[] = []
        agents.slice(0, MAX_AGENT_ROWS).forEach((a, i) => {
          lines.push(
            <Box flexDirection="row">
              <Text color={colorOf(a)} dimColor={a.state === 'done'}>{`${glyphOf(a)} `}</Text>
              <Button
                key={`open:${agentKey(a)}`}
                label={clip(`${a.role}  ${taskText(a)}`, Math.max(8, cols - 8))}
                plain
                {...(i < 9 ? { hotkey: String(i + 1) } : {})}
                onPress={() => void openCard($, a)}
              />
            </Box>,
            <Box flexDirection="row">
              <Text color={colorOf(a)} dimColor={a.state === 'done'}>{`  ${stateWord(a)}`}</Text>
              <Text dimColor>
                {clip(` ${fmtAge(a.age_s)} · ${turnsLabel(a)}t · ctx ${fmtK(a.ctx_tokens)} · ${modelLabel(a)}${isMulti ? ` · ${a.stage}` : ''}`, Math.max(4, cols - 8))}
              </Text>
            </Box>,
            text(`  ${nowText(a)}`, { dim: !a.alive || !a.action }),
          )
        })
        if (agents.length > MAX_AGENT_ROWS) lines.push(text(`… and ${agents.length - MAX_AGENT_ROWS} more (the console shows all: agent-top)`, { dim: true }))
        body = lines
      }
    } else if (view === 'card') {
      const t = target
      const a = t ? (card?.agent ?? agents.find(x => x.stage === t.stage && x.dir_name === t.dirName) ?? null) : null
      if (!t || !a) {
        body = [text(error ? '' : t ? `loading ${t.role}…` : 'no agent selected (Back, then pick one)', { dim: true })]
      } else {
        const color = colorOf(a)
        const head: unknown[] = [
          text(`${glyphOf(a)} ${a.role} · ${stateWord(a)}${a.alive && a.pid ? ` pid ${a.pid}` : ''} · ${fmtAge(a.age_s)} ago`, { color, dim: a.state === 'done', bold: true }),
          ...wrapLines(
            `${a.stage} · ${modelLabel(a)} · tag ${a.tag || '—'} · turns ${turnsLabel(a)}${a.sub_turns ? ` (+${a.sub_turns} sub)` : ''} · ctx ${fmtK(a.ctx_tokens)} · ${fmtCost(a.cost_usd)} · runs ${a.runs}`,
            cols,
            2,
          ).map(l => text(l, { dim: true })),
        ]
        if (a.title) for (const l of wrapLines(a.title, cols, 2)) head.push(text(l, { dim: true }))
        if (a.action) head.push(text(actionText(a), { color: 'green' }))
        else if (a.alive) head.push(text('⋯ waiting for the model', { dim: true }))
        if (a.result && (a.state === 'done' || a.state === 'error')) {
          for (const l of wrapLines(`result: ${a.result.subtype}${a.result.is_error ? ', error' : ''} — ${a.result.text}`, cols, 3)) {
            head.push(text(l, { color: a.result.is_error ? 'red' : undefined, dim: !a.result.is_error }))
          }
        }
        if (a.kind === 'subagent') head.push(text(`sub-agent of ${a.parent ?? '?'}; read-only here`, { dim: true }))
        else if (a.kind === 'session') head.push(text('native Codex session; read-only here', { dim: true }))
        if (a.unread.length) head.push(text(`✉ ${a.unread.length} unread in the inbox`, { color: 'yellow' }))
        if (a.state === 'dead') head.push(text('no process, no result: died or was killed', { color: 'red' }))

        const feed: { text: string; color?: string; dim?: boolean; bold?: boolean }[] = []
        for (const it of card?.feed ?? []) {
          const f = feedLine(it)
          const prefix = feedPrefix(it)
          const room = Math.max(10, cols - prefix.length - f.mark.length - 1)
          wrapLines(f.text, room, f.mark === '  ◂' ? 1 : 2).forEach((l, i) => {
            feed.push({ text: i === 0 ? `${prefix}${f.mark} ${l}` : `${' '.repeat(prefix.length + f.mark.length + 1)}${l}`, color: f.color, dim: f.dim, bold: f.bold })
          })
        }
        const room = Math.max(5, rows - chrome - head.length - 1)
        body = [
          ...head,
          text('─'.repeat(cols), { dim: true }),
          ...(feed.length ? feed.slice(-room).map(f => text(f.text, f)) : [text(card ? '(the log is empty)' : 'loading the feed…', { dim: true })]),
        ]
      }
    } else if (view === 'journal') {
      const lines = shown ? inStages(shown.journal_tail, stages) : []
      const multi = new Set(lines.map(l => l.stage)).size > 1
      const out: { text: string; dim?: boolean }[] = []
      for (const l of lines) {
        const lead = `${l.time} ${multi ? `${l.stage.slice(0, 7)} ` : ''}[${l.tag}] `
        wrapLines(l.text, cols - lead.length, 2).forEach((t, i) => out.push({ text: i === 0 ? `${lead}${t}` : `${' '.repeat(lead.length)}${t}` }))
      }
      body = out.length ? out.slice(-Math.max(5, rows - chrome)).map(l => text(l.text)) : [text(shown ? 'the journal is empty' : 'loading…', { dim: true })]
    } else {
      const out: unknown[] = []
      const heading = (s: string) => out.push(text(s, { bold: true }))
      if (!shown) out.push(text('loading…', { dim: true }))
      else {
        heading('Locks')
        if (shown.locks.length === 0) out.push(text('  no locks', { dim: true }))
        for (const lk of shown.locks) {
          for (const l of wrapLines(`${lk.kind} ${lk.repo} until ${lk.until.slice(0, 16).replace('T', ' ')}${lk.active ? '' : ' (expired)'} — ${lk.owner_name}: ${lk.why}`, cols - 2, 3)) {
            out.push(text(`  ${l}`, { dim: !lk.active }))
          }
        }
        out.push(text(''))
        heading('Owner questions')
        const qs = Object.entries(shown.questions).filter(([s]) => stages.length === 0 || stages.includes(s))
        if (qs.length === 0) out.push(text('  no data (ask is unavailable or there is no register)', { dim: true }))
        for (const [, q] of qs) {
          for (const l of wrapLines(q.line, cols - 2, 2)) out.push(text(`  ${l}`, { color: q.overdue ? 'red' : undefined }))
          for (const item of q.items.slice(0, 8)) for (const l of wrapLines(item, cols - 4, 2)) out.push(text(`    ${l}`, { dim: true }))
        }
        out.push(text(''))
        heading('Plan limits')
        const claude = claudeWindows(shown)
        const codex = Object.entries(shown.codex_limits)
        if (claude.length === 0 && codex.length === 0) out.push(text('  no limit data yet', { dim: true }))
        if (claude.length) {
          out.push(text('  Claude (latest rate-limit event in the logs)', { dim: true }))
          for (const w of claude) out.push(text(`    ${limitLine(w)}`))
        }
        for (const [id, rec] of codex.sort(([x], [y]) => (x < y ? -1 : 1))) {
          const ws = codexWindows(rec.info)
          if (ws.length === 0) continue
          out.push(text(`  ${id === 'codex' ? 'Codex' : `Codex ${id}`} (latest logged snapshot, observed ${fmtAge(Math.max(0, shown.fetchedAt / 1000 - rec.seen_at))} ago)`, { dim: true }))
          for (const w of ws) out.push(text(`    ${limitLine(w)}`))
        }
      }
      body = out
    }

    return (
      <Box flexDirection="column">
        {header}
        {nav}
        {errorLine}
        {body}
      </Box>
    )
  })
}
