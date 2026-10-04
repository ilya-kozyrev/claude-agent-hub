// Tests of the agent-top mod (run: `claude plugin test hooks`, a Claude Code with mods). `process.run` is stubbed with
// fixture JSON of `agent-top --json`; nothing reads real agents. Each test loads the module afresh.
import { expect, mock, test } from 'claude-code/testing'

import {
  capToasts,
  isOwnCommand,
  notices,
  onceArgs,
  parseArgs,
  parseSnapshot,
  planRun,
  remember,
  statusText,
  taskText,
} from './agent-top-model'

// The plugin's name (plugin.json). The dev copy is checked by running this file there with this line set to 'agent-top-dev'.
const PLUGIN: string = 'agent-hub'
const BIN = /\/bin\/agent-top$/

type Row = Record<string, unknown>

const agent = (o: Row = {}): Row => ({
  kind: 'headless', parent: null, engine: 'claude', stage: 'stage-a', role: 'worker', dir_name: 'worker', tag: 'w-1',
  title: 'Build the thing (w-1)', model: 'sonnet', model_id: 'sonnet-5-5', effort: 'high', state: 'live', quiet: false,
  alive: true, pid: 123, age_s: 4, runs: 1, turns: 7, run_turns: 7, turns_approx: false, sub_turns: 0, ctx_tokens: 52000,
  cost_usd: null, cwd: null, archived: false, action: { tool: 'Bash', text: 'run the tests', elapsed_s: 2 }, last_text: '',
  unread: [], result: null, ...o,
})

const snapshot = (agents: Row[], extra: Row = {}): string => {
  const counts = { live: 0, done: 0, error: 0, dead: 0 } as Record<string, number>
  for (const a of agents) counts[a.state as string] += 1
  return JSON.stringify({
    generated_at: '2026-10-04T12:00:00+00:00', stages: ['stage-a'], counts, agents, roles: {}, locks: [], questions: {}, questions_ok: true,
    limits: null, codex_limits: {}, journal_tail: [], ...extra,
  })
}

const cardJson = (a: Row, items: Row[]): string =>
  snapshot([a], { feed: { agent: a.dir_name, stage: a.stage, items } })

const PANE = {
  plugin: PLUGIN,
  component: 'Pane',
  requestId: 'agent-top',
  viewport: { columns: 120, rows: 40 },
  props: { title: 'Agents', isFocused: true, bodyColumns: 70, placement: 'inline', scroll: { offset: 0, bodyRows: 20 }, view: {} },
} as const

const DONE = { subtype: 'success', is_error: false, text: 'all green' }

test('status line has the counts; the first snapshot never toasts, a transition toasts once', async ($, on) => {
  const clock = mock.clock(on)
  let json = snapshot([agent(), agent({ role: 'rev', dir_name: 'rev', state: 'done', alive: false, action: null, result: DONE })])
  const toasts: string[] = []
  const statuses: (string | undefined)[] = []
  on('command.register', () => ({ value: undefined }))
  on('session.surfaces', () => ({ value: ['terminal'] }))
  on('ui.panes', () => ({ value: [] }))
  on('process.run', () => ({ value: { exitCode: 0, stdout: json, stderr: '' } }))
  on('ui.toast', ($, e) => (toasts.push(e.text), { value: undefined }))
  on('ui.status', ($, e) => (statuses.push(e.text), { value: undefined }))
  on('session.start', () => ({ cwd: '/work' }))
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })

  await clock.advance(3000) // the first poll: a live and a done agent are already there
  expect(statuses).toEqual(['agents ● 1 ✓ 1 ✗ 0'])
  expect(toasts).toEqual([])

  json = snapshot([agent({ state: 'done', alive: false, action: null, result: DONE }), agent({ role: 'rev', dir_name: 'rev', state: 'done', alive: false, result: DONE })])
  await clock.advance(15000)
  expect(statuses.at(-1)).toBe('agents ● 0 ✓ 2 ✗ 0')
  expect(toasts).toEqual(['✓ worker · stage-a finished'])

  await clock.advance(30000) // the same snapshot again: no second toast
  expect(toasts).toHaveLength(1)
})

test('a failed and a died agent toast; a new open owner question toasts once', async ($, on) => {
  const clock = mock.clock(on)
  const q = (...ids: string[]) => withQuestions('stage-a', ids)
  let json = snapshot([agent(), agent({ role: 'b', dir_name: 'b' })], { questions: q('Q-A-001') })
  const toasts: string[] = []
  on('command.register', () => ({ value: undefined }))
  on('session.surfaces', () => ({ value: ['terminal'] }))
  on('ui.panes', () => ({ value: [] }))
  on('process.run', () => ({ value: { exitCode: 0, stdout: json, stderr: '' } }))
  on('ui.toast', ($, e) => (toasts.push(e.text), { value: undefined }))
  on('ui.status', () => ({ value: undefined }))
  on('session.start', () => ({ cwd: '/work' }))
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  await clock.advance(3000)
  expect(toasts).toEqual([]) // Q-A-001 was open before the session looked

  json = snapshot(
    [
      agent({ state: 'error', alive: false, action: null, result: { subtype: 'error_max_turns', is_error: true, text: 'ran out of turns' } }),
      agent({ role: 'b', dir_name: 'b', state: 'dead', alive: false, action: null }),
    ],
    { questions: q('Q-A-002', 'Q-A-001') },
  )
  await clock.advance(15000)
  expect(toasts).toEqual(['✗ worker · stage-a failed: ran out of turns', '✗ b · stage-a died', '? stage-a: new question Q-A-002 [stage-a] open — Question Q-A-002?'])
  await clock.advance(30000)
  expect(toasts).toHaveLength(3)
})

test('no agents in the default view: nothing in the status line', async ($, on) => {
  const clock = mock.clock(on)
  const statuses: (string | undefined)[] = []
  on('command.register', () => ({ value: undefined }))
  on('session.surfaces', () => ({ value: ['terminal'] }))
  on('ui.panes', () => ({ value: [] }))
  on('process.run', () => ({ value: { exitCode: 0, stdout: snapshot([]), stderr: '' } }))
  on('ui.toast', () => ({ value: undefined }))
  on('ui.status', ($, e) => (statuses.push(e.text), { value: undefined }))
  on('session.start', () => ({ cwd: '/work' }))
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  await clock.advance(3000)
  expect(statuses).toEqual([])
})

test('/agent-top opens the pane; rows open the card with the feed, Back returns (terminal and desktop)', async ($, on) => {
  mock.clock(on)
  const calls: string[][] = []
  const list = snapshot([agent(), agent({ role: 'rev', dir_name: 'rev', state: 'done', alive: false, action: null, last_text: 'looks fine', result: DONE })])
  const feed = [
    { at: '12:00:01', kind: 'tool', sub: false, tool: 'Bash', text: 'run the tests', detail: 'pytest' },
    { at: '12:00:02', kind: 'result', sub: false, tool: 'Bash', text: '12 passed', detail: null },
    { at: '12:00:03', kind: 'text', sub: false, tool: null, text: 'all green, writing the report', detail: null },
  ]
  on('command.register', () => ({ value: undefined }))
  on('session.surfaces', () => ({ value: ['terminal'] }))
  on('ui.panes', () => ({ value: [] }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.toast', () => ({ value: undefined }))
  on('ui.status', () => ({ value: undefined }))
  on('process.run', ($, e) => {
    calls.push([...e.argv])
    return { value: { exitCode: 0, stdout: e.argv.includes('--agent') ? cardJson(agent(), feed) : list, stderr: '' } }
  })
  const answer = await $.command.run({ command: 'agent-top', args: '' })
  expect(answer.text).toBe('agent-top pane opened: ● 1 ✓ 1 ✗ 0')
  expect(calls[0].slice(1)).toEqual(['--json']) // the plugin's own CLI, JSON only
  expect(calls[0][0]).toMatch(BIN)

  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...PANE, surface })
    expect(await ui.find({ type: 'Text', text: /^agent-top$/ })).toBeDefined()
    expect(await ui.find({ key: 'open:stage-a/worker' })).toBeDefined()
    expect(await ui.find({ key: 'open:stage-a/rev' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /▸ Bash: run the tests/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /looks fine/ })).toBeDefined()
    expect(await ui.find({ key: 'back' })).toBeUndefined()

    await ui.press({ key: 'open:stage-a/worker' })
    const lastCall = calls.at(-1) ?? []
    expect(lastCall.slice(1)).toEqual(['--json', '--agent', 'worker', '--stage', 'stage-a', '--feed', '30'])
    expect(await ui.find({ type: 'Text', text: /worker · live pid 123 · 4s ago/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /stage-a · sonnet-5-5\/hi · tag w-1/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /▸ Bash: run the tests/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /◂ 12 passed/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /✎ all green, writing the report/ })).toBeDefined()
    expect(await ui.find({ key: 'open:stage-a/worker' })).toBeUndefined()

    await ui.press({ key: 'back' })
    expect(await ui.find({ key: 'open:stage-a/worker' })).toBeDefined()
    await ui.unmount()
  }
})

test('an agent opened from the --all list is asked for with --all (old and archived agents are only there)', async ($, on) => {
  mock.clock(on)
  const calls: string[][] = []
  const old = agent({ role: 'old', dir_name: 'old', state: 'done', alive: false, action: null, age_s: 90000, archived: true, result: DONE })
  on('command.register', () => ({ value: undefined }))
  on('session.surfaces', () => ({ value: ['terminal'] }))
  on('ui.panes', () => ({ value: [] }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.toast', () => ({ value: undefined }))
  on('ui.status', () => ({ value: undefined }))
  on('process.run', ($, e) => {
    calls.push([...e.argv])
    const isAll = e.argv.includes('--all')
    if (e.argv.includes('--agent')) return { value: { exitCode: 0, stdout: isAll ? cardJson(old, []) : snapshot([], { feed: { agent: 'old', stage: 'stage-a', items: [] } }), stderr: '' } }
    return { value: { exitCode: 0, stdout: snapshot(isAll ? [agent(), old] : [agent()]), stderr: '' } }
  })
  await $.command.run({ command: 'agent-top', args: '--all' })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await ui.press({ key: 'open:stage-a/old' })
  expect(calls.at(-1)?.slice(1)).toEqual(['--json', '--all', '--agent', 'old', '--stage', 'stage-a', '--feed', '30'])
  expect(await ui.find({ type: 'Text', text: /old · done/ })).toBeDefined()
  await ui.unmount()

  // the role argument of the command itself takes the same path
  calls.length = 0
  await $.command.run({ command: 'agent-top', args: 'old --all' })
  expect(calls.some(c => c.join(' ').endsWith('--json --all --agent old --stage stage-a --feed 30'))).toBe(true)
})

test('Journal and Summary views draw the journal tail, locks, questions and plan limits incl. Codex', async ($, on) => {
  mock.clock(on)
  const json = snapshot([agent()], {
    journal_tail: [{ stage: 'stage-a', time: '12:01', tag: 'hub-1', text: 'plan: ship the mod' }],
    locks: [{ kind: 'main-merge', repo: 'santinel', owner_name: 'Hub core-c #28', until: '2026-10-31T23:59:00+03:00', active: true, why: 'held' }],
    questions: { 'stage-a': { open: 1, overdue: 1, line: 'stage-a — open 1, overdue 1', items: ['Q-9 [stage-a] open OVERDUE — decide?'] } },
    limits: { info: { unifiedWindows: { five_hour: { utilization: 0.42, resetsAt: 1791547735 }, seven_day: { utilization: 0.1 } } }, seen_at: 1790972433 },
    codex_limits: { codex: { info: { primary: { used_percent: 21, window_minutes: 10080, resets_at: 1791547735 }, secondary: null }, seen_at: 1790972433 } },
  })
  on('command.register', () => ({ value: undefined }))
  on('session.surfaces', () => ({ value: ['terminal'] }))
  on('ui.panes', () => ({ value: [] }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.toast', () => ({ value: undefined }))
  on('ui.status', () => ({ value: undefined }))
  on('process.run', () => ({ value: { exitCode: 0, stdout: json, stderr: '' } }))
  await $.command.run({ command: 'agent-top', args: '' })

  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...PANE, surface })
    await ui.press({ key: 'view-journal' })
    expect(await ui.find({ type: 'Text', text: /12:01 \[hub-1\] plan: ship the mod/ })).toBeDefined()
    await ui.press({ key: 'view-summary' })
    expect(await ui.find({ type: 'Text', text: /main-merge santinel until 2026-10-31 23:59/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /Q-9 \[stage-a\] open OVERDUE/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /5h: 42% used/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /7d: 21% used/ })).toBeDefined()
    await ui.press({ key: 'view-agents' })
    expect(await ui.find({ key: 'open:stage-a/worker' })).toBeDefined()
    await ui.unmount()
  }
})

test('/agent-top <role> --stage S opens that agent card; an unknown role says so', async ($, on) => {
  mock.clock(on)
  const calls: string[][] = []
  const rows = [agent(), agent({ stage: 'stage-b', dir_name: 'worker' })]
  on('command.register', () => ({ value: undefined }))
  on('session.surfaces', () => ({ value: ['terminal'] }))
  on('ui.panes', () => ({ value: [] }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.toast', () => ({ value: undefined }))
  on('ui.status', () => ({ value: undefined }))
  on('process.run', ($, e) => {
    calls.push([...e.argv])
    return { value: { exitCode: 0, stdout: e.argv.includes('--agent') ? cardJson(agent({ stage: e.argv[e.argv.indexOf('--stage') + 1] }), []) : snapshot(rows, { stages: ['stage-a', 'stage-b'] }), stderr: '' } }
  })
  const ok = await $.command.run({ command: 'agent-top', args: 'worker --stage stage-b' })
  expect(ok.text).toMatch(/^agent-top pane opened: /)
  expect(calls.some(c => c.join(' ').endsWith('--agent worker --stage stage-b --feed 30'))).toBe(true)

  const none = await $.command.run({ command: 'agent-top', args: 'ghost' })
  expect(none.text).toBe('agent-top pane opened: no agent "ghost"; ● 2 ✓ 0 ✗ 0')
})

test('where no pane can be placed, /agent-top answers with the text picture', async ($, on) => {
  const calls: string[][] = []
  on('command.register', () => ({ value: undefined }))
  on('session.surfaces', () => ({ value: ['terminal'] }))
  on('ui.open', () => ({ value: { isPlaced: false, reason: 'no pane here' } }))
  on('process.run', ($, e) => (calls.push([...e.argv]), { value: { exitCode: 0, stdout: 'agent-top picture\n', stderr: '' } }))
  const answer = await $.command.run({ command: 'agent-top', args: 'worker --stage s --all' })
  expect(answer.text).toBe('agent-top picture')
  expect(calls.at(-1)?.slice(1)).toEqual(['--once', '--width', '100', '--stage', 's', '--all', '--agent', 'worker'])
})

test("only agent-top and this plugin's own <name>:agent-top are answered; another plugin's command passes through", async ($, on) => {
  mock.clock(on)
  const own = `${PLUGIN}:agent-top`
  const isDev = PLUGIN === 'agent-top-dev'
  on('command.register', () => ({ value: undefined }))
  on('session.surfaces', () => ({ value: [] }))
  on('process.run', () => ({ value: { exitCode: 0, stdout: 'picture\n', stderr: '' } }))
  on('command.run', () => ({ text: 'the engine ran it' }))
  expect((await $.command.run({ command: 'agent-top', args: '' })).text).toBe('picture')
  expect((await $.command.run({ command: own, args: '' })).text).toBe('picture')
  expect((await $.command.run({ command: 'agent-hub:agent-top', args: '' })).text).toBe(isDev || PLUGIN === 'agent-hub' ? 'picture' : 'the engine ran it')
  for (const other of ['compact', 'other-plugin:agent-top', 'other-plugin:agent-topic', 'agent-top-dev-x:agent-top']) {
    expect((await $.command.run({ command: other, args: '' })).text).toBe('the engine ran it')
  }
  expect((await $.command.run({ command: 'agent-top-dev:agent-top', args: '' })).text).toBe(isDev ? 'picture' : 'the engine ran it')
})

test('isOwnCommand: the dev copy also answers agent-hub:agent-top, nobody else does', async () => {
  expect(isOwnCommand('agent-top', 'agent-hub')).toBe(true)
  expect(isOwnCommand('agent-hub:agent-top', 'agent-hub')).toBe(true)
  expect(isOwnCommand('agent-top-dev:agent-top', 'agent-hub')).toBe(false) // not an allow-list for the installed plugin
  expect(isOwnCommand('other:agent-top', 'agent-hub')).toBe(false)
  expect(isOwnCommand('agent-top', 'agent-top-dev')).toBe(true)
  expect(isOwnCommand('agent-top-dev:agent-top', 'agent-top-dev')).toBe(true)
  expect(isOwnCommand('agent-hub:agent-top', 'agent-top-dev')).toBe(true)
  expect(isOwnCommand('other:agent-top', 'agent-top-dev')).toBe(false)
  expect(isOwnCommand('agent-hub:agent-topic', 'agent-top-dev')).toBe(false)
})

test('with no surface at all (a -p run) /agent-top answers with the text picture and opens nothing', async ($, on) => {
  let opened = 0
  on('command.register', () => ({ value: undefined }))
  on('session.surfaces', () => ({ value: [] }))
  on('ui.open', () => (opened += 1, { value: { isPlaced: true } }))
  on('process.run', () => ({ value: { exitCode: 0, stdout: 'picture\n', stderr: '' } }))
  const answer = await $.command.run({ command: 'agent-top', args: '' })
  expect(answer.text).toBe('picture')
  expect(opened).toBe(0)
})

test('a failing CLI shows one dim line and keeps the last good snapshot', async ($, on) => {
  const clock = mock.clock(on)
  let isBroken = false
  on('command.register', () => ({ value: undefined }))
  on('session.surfaces', () => ({ value: ['terminal'] }))
  on('ui.panes', () => ({ value: [{ id: 'agent-top', title: 'Agents', isShown: true, isFocused: false, isPlaced: true }] }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.toast', () => ({ value: undefined }))
  on('ui.status', () => ({ value: undefined }))
  on('process.run', () =>
    isBroken
      ? { value: { exitCode: 2, stdout: '', stderr: 'FAILED: hub home is unreadable\nmore\n' } }
      : { value: { exitCode: 0, stdout: snapshot([agent()]), stderr: '' } },
  )
  await $.command.run({ command: 'agent-top', args: '' })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  isBroken = true
  await clock.advance(3000) // the pane is open: polls every 3 s
  expect(await ui.find({ type: 'Text', text: '! FAILED: hub home is unreadable' })).toBeDefined()
  expect(await ui.find({ key: 'open:stage-a/worker' })).toBeDefined() // the last good snapshot is still drawn
  isBroken = false
  await clock.advance(3000)
  expect(await ui.find({ type: 'Text', text: /^!/ })).toBeUndefined()
})

test('a missing agent-top stops the polling: status cleared, no toasts, no more calls', async ($, on) => {
  const clock = mock.clock(on)
  let runs = 0
  let isGone = false
  const statuses: (string | undefined)[] = []
  const toasts: string[] = []
  on('command.register', () => ({ value: undefined }))
  on('session.surfaces', () => ({ value: ['terminal'] }))
  on('ui.panes', () => ({ value: [] }))
  on('process.run', () => {
    runs += 1
    if (isGone) return { deny: 'spawn ENOENT: no such file or directory' }
    return { value: { exitCode: 0, stdout: snapshot([agent()]), stderr: '' } }
  })
  on('ui.toast', ($, e) => (toasts.push(e.text), { value: undefined }))
  on('ui.status', ($, e) => (statuses.push(e.text), { value: undefined }))
  on('session.start', () => ({ cwd: '/work' }))
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  await clock.advance(3000)
  expect(statuses).toEqual(['agents ● 1 ✓ 0 ✗ 0'])

  isGone = true
  await clock.advance(15000)
  expect(statuses).toEqual(['agents ● 1 ✓ 0 ✗ 0', undefined])
  const seen = runs
  await clock.advance(60000)
  expect(runs).toBe(seen)
  expect(toasts).toEqual([])
})

test('never two runs in flight', async ($, on) => {
  const clock = mock.clock(on)
  let active = 0
  let most = 0
  on('command.register', () => ({ value: undefined }))
  on('session.surfaces', () => ({ value: ['terminal'] }))
  on('ui.panes', () => ({ value: [{ id: 'agent-top', title: 'Agents', isShown: true, isFocused: false, isPlaced: true }] }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.toast', () => ({ value: undefined }))
  on('ui.status', () => ({ value: undefined }))
  on('process.run', async () => {
    active += 1
    most = Math.max(most, active)
    await clock.sleep(7000) // slower than two ticks
    active -= 1
    return { value: { exitCode: 0, stdout: snapshot([agent()]), stderr: '' } }
  })
  const opening = $.command.run({ command: 'agent-top', args: '' })
  await clock.advance(60000)
  await opening
  expect(most).toBe(1)
})

// ---------------------------------------------------------------- the pure helpers

test('parseArgs and onceArgs', async () => {
  expect(parseArgs('')).toEqual({ role: null, stages: [], isAll: false })
  expect(parseArgs('hub --stage a --stage=b --all')).toEqual({ role: 'hub', stages: ['a', 'b'], isAll: true })
  expect(onceArgs(parseArgs('hub --stage a'))).toEqual(['--once', '--width', '100', '--stage', 'a', '--agent', 'hub'])
})

test('planRun: every tick while the pane shows the list, every 15 s otherwise, the card is an extra call', async () => {
  const base = { now: 100000, lastWatchAt: 99000, isOpen: false, view: 'list', isAll: false, hasTarget: false, force: false } as const
  expect(planRun(base)).toEqual({ watch: false, extra: null })
  expect(planRun({ ...base, lastWatchAt: 85000 })).toEqual({ watch: true, extra: null })
  expect(planRun({ ...base, isOpen: true })).toEqual({ watch: true, extra: null })
  expect(planRun({ ...base, isOpen: true, isAll: true })).toEqual({ watch: false, extra: 'all' })
  expect(planRun({ ...base, isOpen: true, view: 'card', hasTarget: true })).toEqual({ watch: false, extra: 'card' })
  expect(planRun({ ...base, isOpen: true, view: 'card', hasTarget: true, lastWatchAt: 85000 })).toEqual({ watch: true, extra: 'card' })
  expect(planRun({ ...base, isOpen: true, view: 'journal' })).toEqual({ watch: true, extra: null })
})

test('notices, status text and toast cap on parsed snapshots', async () => {
  const before = parseSnapshot(snapshot([agent(), agent({ role: 'x', dir_name: 'x' })]), 0)
  const after = parseSnapshot(snapshot([agent({ state: 'done', alive: false, result: DONE }), agent({ role: 'x', dir_name: 'x' }), agent({ role: 'n', dir_name: 'n', state: 'done', alive: false, age_s: 5, result: DONE }), agent({ role: 'old', dir_name: 'old', state: 'done', alive: false, age_s: 90000 })]), 0)
  expect(notices(remember(before), after)).toEqual(['✓ worker · stage-a finished', '✓ n · stage-a finished'])
  expect(statusText(after)).toBe('agents ● 1 ✓ 3 ✗ 0')
  expect(statusText(parseSnapshot(snapshot([]), 0))).toBeUndefined()
  expect(capToasts(['a', 'b', 'c', 'd', 'e'])).toEqual(['a', 'b', '+3 more events (open /agent-top)'])
  expect(taskText(parseSnapshot(snapshot([agent()]), 0).agents[0])).toBe('Build the thing')
  expect(() => parseSnapshot('not json', 0)).toThrow('agent-top printed no JSON')
  expect(() => parseSnapshot('{"x":1}', 0)).toThrow('unexpected agent-top output')
})

// ---------------------------------------------------------------- owner questions and finishes: real `ask list --open` format

// Generated by `bin/ask add ... ; bin/ask list --stage stage-a --open`, one entry per three lines (header, blocks, asked);
// bin/agent-top keeps each non-empty line as an item (at most 12).
const askItems = (...ids: string[]): string[] =>
  ids.flatMap(id => [
    `${id} [stage-a] open — Question ${id}?`,
    '    blocks: stage B; default by 2026-10-10: keep Claude',
    '    asked 2026-10-03 (hub); source: brief',
  ])

// `items` are cut to 12 display lines like bin/agent-top does; `ids` carry every open id.
const withQuestions = (stage: string, ids: string[], open = ids.length): Row => ({
  [stage]: { open, overdue: 0, line: `${stage} — open ${open}, overdue 0`, items: askItems(...ids).slice(0, 12), ids },
})

const qids = (...nums: number[]): string[] => nums.map(n => `Q-A-${String(n).padStart(3, '0')}`)
const toast = (id: string): string => `? stage-a: new question ${id} [stage-a] open — Question ${id}?`
const bare = (id: string): string => `? stage-a: new question ${id}` // past the 12 display lines: only the id is known

const snapQ = (questions: Row, agents: Row[] = [agent()]): ReturnType<typeof parseSnapshot> => parseSnapshot(snapshot(agents, { questions }), 0)

test('one new question toasts once, not once per display line (id, blocks:, asked)', async () => {
  const empty = snapQ(withQuestions('stage-a', [])) // a register that exists but holds no open question yet
  const one = snapQ(withQuestions('stage-a', ['Q-A-001']))
  const two = snapQ(withQuestions('stage-a', ['Q-A-002', 'Q-A-001']))
  expect(notices(remember(empty), one)).toEqual(['? stage-a: new question Q-A-001 [stage-a] open — Question Q-A-001?'])
  expect(notices(remember(one), two)).toEqual(['? stage-a: new question Q-A-002 [stage-a] open — Question Q-A-002?'])
  expect(notices(remember(two), two)).toEqual([])
})

test('open ids past the 12 display lines are diffed too: 3 -> 8 shows 3 toasts and a count line', async () => {
  const out = notices(remember(snapQ(withQuestions('stage-a', qids(1, 2, 3)))), snapQ(withQuestions('stage-a', qids(1, 2, 3, 4, 5, 6, 7, 8))))
  expect(out).toEqual([toast('Q-A-004'), bare('Q-A-005'), bare('Q-A-006'), '? stage-a: 2 more new questions'])
})

test('5 open (4 visible): close 001/002 and add 006 toasts 006 only', async () => {
  const before = snapQ(withQuestions('stage-a', qids(1, 2, 3, 4, 5)))
  const after = snapQ(withQuestions('stage-a', qids(3, 4, 5, 6)))
  expect(notices(remember(before), after)).toEqual([toast('Q-A-006')])
})

test('5 open (4 visible): close 001 and add 006/007 toasts 006 and 007, never 005', async () => {
  const before = snapQ(withQuestions('stage-a', qids(1, 2, 3, 4, 5)))
  const after = snapQ(withQuestions('stage-a', qids(2, 3, 4, 5, 6, 7)))
  expect(notices(remember(before), after)).toEqual([bare('Q-A-006'), bare('Q-A-007')])
})

test('a failed first ask summary is not a baseline: the next good snapshot toasts nothing for existing questions', async () => {
  const failed = parseSnapshot(snapshot([agent()], { questions: {}, questions_ok: false }), 0)
  const good = snapQ(withQuestions('stage-a', qids(1)))
  const next = snapQ(withQuestions('stage-a', qids(1, 2)))
  expect(notices(remember(failed), good)).toEqual([])
  expect(notices(remember(good, remember(failed)), next)).toEqual([toast('Q-A-002')])
})

test('a failed ask in the middle keeps the memory; a stage with ids null keeps its set; older JSON never toasts', async () => {
  const good = snapQ(withQuestions('stage-a', qids(1, 2)))
  const failed = parseSnapshot(snapshot([agent()], { questions: {}, questions_ok: false }), 0)
  const mem = remember(failed, remember(good))
  expect(notices(mem, snapQ(withQuestions('stage-a', qids(1, 2))))).toEqual([]) // nothing looks new after the hiccup
  expect(notices(mem, snapQ(withQuestions('stage-a', qids(1, 2, 3))))).toEqual([toast('Q-A-003')])
  const listFailed = parseSnapshot(snapshot([agent()], { questions: { 'stage-a': { open: 2, overdue: 0, line: 'stage-a — open 2, overdue 0', items: [], ids: null } } }), 0)
  expect(notices(remember(good), listFailed)).toEqual([])
  const kept = remember(listFailed, remember(good))
  expect(notices(kept, snapQ(withQuestions('stage-a', qids(1, 2, 3))))).toEqual([toast('Q-A-003')])
  const older = parseSnapshot(JSON.stringify({ ...JSON.parse(snapshot([agent()])), questions_ok: undefined, questions: { 'stage-a': { open: 1, overdue: 0, line: 'x', items: askItems('Q-A-009') } } }), 0)
  expect(notices(remember(good), older)).toEqual([])
})

test('the first question of a stage that had no register at the first snapshot toasts', async () => {
  const before = snapQ({}) // `ask summary` lists only stages that already have a register
  const after = snapQ(withQuestions('stage-a', ['Q-A-001']))
  expect(notices(remember(before), after)).toEqual(['? stage-a: new question Q-A-001 [stage-a] open — Question Q-A-001?'])
})

test('a resumed agent that finishes again between two polls (done, runs 1 -> 2) toasts', async () => {
  const done = (runs: number) => parseSnapshot(snapshot([agent({ state: 'done', alive: false, action: null, age_s: 600, runs, result: DONE })]), 0)
  expect(notices(remember(done(1)), done(2))).toEqual(['✓ worker · stage-a finished'])
  expect(notices(remember(done(2)), done(2))).toEqual([])
})
