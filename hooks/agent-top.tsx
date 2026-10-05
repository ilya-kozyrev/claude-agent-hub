// agent-top as a Claude Code mod: the headless agents of the agent-hub plugin, live in a pane.
//
//   /agent-top [role] [--stage S] [--all]   opens the pane (a role opens that agent's card)
//   pane views: Agents (a) · agent card (header + live feed) · Journal (j) · Summary (s: plan limits, owner questions, locks)
//   the drawing: hooks/agent-top-view.tsx; the list's cursor follows the pane's focus ring (ui.focus)
//   status line: `agents ● 2 ✓ 5 ✗ 1`; toasts when an agent finishes, fails or dies and when a new owner question opens
//
// Read-only. Data comes only from the plugin's own CLI, `bin/agent-top --json`; nothing is written anywhere. The module is
// plugin-name-agnostic (no $.state, no hard-coded plugin name): state lives in this closure, and a hot reload starts it over.
// Needs Claude Code with mods (2.1.287+). Older CLIs ignore the module; the skill `agent-top` keeps working there.
import type { EngineInterface, Register, Timer } from 'claude-code'

import {
  TICK_MS,
  agentKey,
  capToasts,
  clip,
  countsOf,
  findByRole,
  inStages,
  isOwnCommand,
  notices,
  oneLine,
  onceArgs,
  parseArgs,
  parseCard,
  parseSnapshot,
  planRun,
  remember,
  statusText,
} from './agent-top-model'
import type { Agent, Card, CommandArgs, Memory, Snapshot, Target, View } from './agent-top-model'
import { drawPane } from './agent-top-view'
import type { PaneModel } from './agent-top-view'

type Api = EngineInterface

const PANE = 'agent-top'
const INLINE_ROWS = 24 // body rows asked for above the prompt (a request: the person's own size wins)
const DOCK_COLUMNS = 76 // body columns asked for beside a fullscreen transcript
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
let cursorKey: string | null = null // agentKey of the list row the cursor is on, kept while the ring is elsewhere
let isAutoFocus = true // until the ring first lands on a row, the cursor row is drawn autoFocus
let ringKey: string | null = null // the element the ring was last moved onto (ui.focus)
let lastControls = '' // the drawn Buttons' keys, in order, at the last drawing
let edges: { prev: string | null; next: string | null } = { prev: null, next: null } // the agents past the list's window

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

/** Moves the ring from a handler (never from a drawing): the element is awaited until the next drawing brings it. */
function focusOn($: Api, key: string): void {
  if (!isOpen) return
  try {
    void $.ui.focus({ requestId: PANE, key }).catch(() => undefined)
  } catch {
    // a host without a focus ring: the cursor stays where it was
  }
}

function openCard($: Api, a: Pick<Agent, 'stage' | 'dir_name' | 'role'>): Promise<void> {
  target = { stage: a.stage, dirName: a.dir_name, role: a.role }
  cursorKey = agentKey(a)
  card = null
  view = 'card'
  $.ui.invalidate('ui.render')
  focusOn($, 'back')
  return refresh($, true)
}

/** From the card back to the list, the cursor on the agent the card showed. */
function back($: Api): void {
  go($, 'list')
}

function go($: Api, next: View): void {
  view = next
  $.ui.invalidate('ui.render')
  // the ring onto the new view's own element: the cursor row, or the active tab (its old element may be gone)
  if (next === 'list') {
    if (cursorKey !== null) focusOn($, `open:${cursorKey}`)
  } else if (next === 'journal' || next === 'summary') focusOn($, `view-${next}`)
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

    isAutoFocus = true
    ringKey = null
    lastControls = ''
    const opened = await $.ui.open({ id: PANE, title: 'Agents', focus: true, closeOnEscape: true, rows: INLINE_ROWS, columns: DOCK_COLUMNS })
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

  // The focus ring: the list row it lands on is the cursor (drawn with ❯, and the window follows it). The ring itself
  // is the engine's: this only listens, and never moves it from inside a drawing.
  on('ui.focus', { requestId: PANE }, async ($, e, next) => {
    const done = await next(e)
    if (done.deny) return done
    // the ring on `↑ more` / `↓ more` means the agent just past the window: the cursor goes there, the window follows
    // and the drawing that brings its row puts the ring on it
    const past = e.element === 'more-up' ? edges.prev : e.element === 'more-down' ? edges.next : null
    ringKey = past !== null ? `open:${past}` : (e.element ?? null)
    const row = ringKey?.startsWith('open:') ? ringKey.slice(5) : null
    if (row !== null && (row !== cursorKey || isAutoFocus)) {
      cursorKey = row
      isAutoFocus = false
      $.ui.invalidate('ui.render')
    }

    return done
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    isOpen = true
    const shown = isAll && allSnap ? allSnap : snap
    const agents = shown ? inStages(shown.agents, stages) : []
    const model: PaneModel = {
      view,
      cols: Math.max(20, e.props.bodyColumns), // the drawing's own floor: below 20 columns rows are cut by the surface
      rows: Math.max(8, e.props.scroll.bodyRows),
      placement: e.props.placement,
      shown,
      agents,
      counts: shown ? (stages.length ? countsOf(agents) : shown.counts) : null,
      stages,
      isAll,
      error,
      card,
      target,
      cursorKey: cursorKey !== null && agents.some(a => agentKey(a) === cursorKey) ? cursorKey : agents[0] ? agentKey(agents[0]) : null,
      isAutoFocus,
      nowMs: shown?.fetchedAt ?? 0,
    }
    const drawn = drawPane($.ui.resolve(e), model, {
      go: next => go($, next),
      refresh: () => void refresh($, true),
      toggleAll: () => {
        isAll = !isAll
        allSnap = null
        go($, 'list')
      },
      open: a => void openCard($, a),
      back: () => back($),
      step: dir => {
        const to = dir < 0 ? edges.prev : edges.next
        if (to === null) return
        cursorKey = to
        isAutoFocus = false
        ringKey = `open:${to}`
        $.ui.invalidate('ui.render')
        focusOn($, `open:${to}`)
      },
    })
    edges = drawn.edges
    // The ring keeps its place among the Buttons, not its element: when the drawn Buttons change (the window moved, a
    // poll reordered the rows), put it back on the element it means, once this drawing is in (a timer: never from here).
    const sig = drawn.controls.join('\n')
    if (sig !== lastControls) {
      lastControls = sig
      const meant = ringKey?.startsWith('open:') && model.cursorKey !== null ? `open:${model.cursorKey}` : ringKey
      if (meant !== null && drawn.controls.includes(meant)) $.clock.after(0, () => focusOn($, meant))
    }

    return drawn.tree
  })
}
