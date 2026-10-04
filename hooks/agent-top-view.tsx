// The drawing of the agent-top pane (hooks/agent-top.tsx owns the data, the polling and the focus): pure tree builders,
// no `$`. One tree for every surface: only Box, Text and Button, which both the terminal and the desktop table hold.
//
//   dock (beside a fullscreen transcript): a rounded cyan frame; the card in its state's colour; Summary sections framed
//   inline (above the prompt, the engine draws the frame) and narrow bodies: no frames, sections under `──` rules
//
// The agent list is a window around the cursor that always fits the pane's body: then the arrows walk the rows (the
// engine scrolls only a drawing taller than the body), and `ui.focus` tells the module where the ring went.
import type { Elements, RenderChildren, RenderElement } from 'claude-code'

import {
  actionText,
  agentKey,
  badgeOf,
  barCells,
  claudeWindows,
  clip,
  codexWindows,
  colorOf,
  ctxPercent,
  feedLine,
  fmtAge,
  fmtCost,
  fmtK,
  fmtResetShort,
  journalColor,
  levelColor,
  modelLabel,
  nowText,
  padEnd,
  tagColor,
  taskText,
  turnsLabel,
  windowAround,
  wrapLines,
} from './agent-top-model'
import type { Agent, Card, Counts, LimitWindow, Snapshot, Target, View } from './agent-top-model'

export type Els = Pick<Elements['terminal'], 'Box' | 'Text' | 'Button'>

/** Below this many body columns the pane drops its frames and the list's meta column. */
export const COMPACT_COLS = 44

export type PaneModel = {
  view: View
  /** The pane body's columns and rows (`e.props.bodyColumns`, `e.props.scroll.bodyRows`). */
  cols: number
  rows: number
  placement: 'dock' | 'inline'
  shown: Snapshot | null
  /** `shown.agents` after the stage filter, in the CLI's order. */
  agents: Agent[]
  counts: Counts | null
  stages: string[]
  isAll: boolean
  error: string | null
  card: Card | null
  target: Target | null
  /** agentKey of the list row the cursor is on (the focus ring's, or the last one it was on). */
  cursorKey: string | null
  /** The list row drawn `autoFocus`: the ring starts there when the pane takes the keyboard. */
  isAutoFocus: boolean
  nowMs: number
}

export type PaneActions = {
  go: (view: View) => void
  refresh: () => void
  toggleAll: () => void
  open: (a: Agent) => void
  back: () => void
}

type Style = { color?: string; bg?: string; dim?: boolean; bold?: boolean; italic?: boolean; strike?: boolean }

const len = (s: string): number => Array.from(s).length
const padStart = (s: string, w: number): string => ' '.repeat(Math.max(0, w - len(s))) + s

/** The tree, and the keys of its Buttons in document order: the pane's focus ring walks them by position. */
export type Drawn = { tree: RenderElement; controls: string[] }

export function drawPane(els: Els, m: PaneModel, act: PaneActions): Drawn {
  const { Box, Text } = els
  const controls: string[] = []
  const Button = (p: Parameters<Els['Button']>[0]): RenderElement => {
    if (p.key) controls.push(p.key)
    return els.Button(p)
  }
  const isCompact = m.cols < COMPACT_COLS
  const isFramed = m.placement === 'dock' && !isCompact
  const w = Math.max(20, m.cols - (isFramed ? 4 : 0)) // the frame's two borders and paddingX 1
  const failed = m.counts ? m.counts.error + m.counts.dead : 0

  const t = (s: string, o: Style = {}): RenderChildren => (
    <Text
      wrap="truncate-end"
      color={o.color}
      backgroundColor={o.bg}
      dimColor={o.dim}
      bold={o.bold}
      italic={o.italic}
      strikethrough={o.strike}
    >
      {s}
    </Text>
  )
  const row = (key: string | undefined, kids: RenderChildren[], between = false): RenderChildren => (
    <Box key={key} flexDirection="row" justifyContent={between ? 'space-between' : 'flex-start'}>
      {kids}
    </Box>
  )
  const rule = (label: string, width: number, right = ''): RenderChildren => {
    const head = label ? `── ${label} ` : ''
    const tail = right ? ` ${right} ──` : ''
    return t(head + '─'.repeat(Math.max(2, width - len(head) - len(tail))) + tail, { dim: true })
  }
  const pill = (s: string, bg: string, fg = 'black', dim = false): RenderChildren => t(` ${s} `, { bg, color: fg, bold: true, dim })

  // ---------------------------------------------------------------- header: title, counters, stage and time
  const counters: { text: string; node: RenderChildren }[] = []
  const live = m.counts?.live ?? 0
  counters.push({ text: ` ● ${live} `, node: live ? pill(`● ${live}`, 'green') : t(` ● 0 `, { dim: true }) })
  counters.push({ text: ` ✓ ${m.counts?.done ?? 0} `, node: t(` ✓ ${m.counts?.done ?? 0} `, { dim: true }) })
  counters.push({ text: ` ✗ ${failed} `, node: failed ? pill(`✗ ${failed}`, 'red', 'white') : t(` ✗ 0 `, { dim: true }) })
  const title = '◆ agent-top'
  const leftLen = len(title) + 1 + counters.reduce((n, c) => n + len(c.text), 0)
  const where = `${m.stages.length ? m.stages.join('/') : 'all stages'}${m.shown ? ` · ${m.shown.generated_at.slice(11, 16)}` : ''}`
  const room = w - leftLen - 1
  const header = row(
    'header',
    [
      <Box flexDirection="row">
        {t(title, { color: 'cyan', bold: true })}
        {t(' ')}
        {counters.map(c => c.node)}
      </Box>,
      room >= 6 ? t(clip(where, room), { dim: true }) : null,
    ],
    true,
  )

  // ---------------------------------------------------------------- tabs: the active one filled, the rest buttons
  // the active tab stays a Button (on a filled Box): a focused element that vanished would leave the ring nowhere
  const tab = (key: string, label: string, hotkey: string, view: View, isActive: boolean): RenderChildren =>
    isActive ? (
      <Box key={`tab:${view}`} backgroundColor="cyan">
        <Button key={key} label={` ${label} `} plain onPress={() => act.go(view)} />
      </Box>
    ) : (
      <Button key={key} label={label} hotkey={hotkey} plain dimColor onPress={() => act.go(view)} />
    )
  const isNarrow = w < 52
  const tabs = row(
    'tabs',
    [
      <Box flexDirection="row" columnGap={1}>
        {tab('view-agents', 'Agents', 'a', 'list', m.view === 'list' || m.view === 'card')}
        {tab('view-journal', 'Journal', 'j', 'journal', m.view === 'journal')}
        {tab('view-summary', 'Summary', 's', 'summary', m.view === 'summary')}
      </Box>,
      <Box flexDirection="row" columnGap={1}>
        <Button key="refresh" label={isNarrow ? '↻' : 'refresh'} hotkey="r" plain dimColor onPress={act.refresh} />
        {m.view === 'list' ? (
          <Button key="toggle-all" label={m.isAll ? 'recent' : 'old'} hotkey="l" plain dimColor onPress={act.toggleAll} />
        ) : null}
      </Box>,
    ],
    true,
  )
  const errorLine = m.error ? row('error', [pill('!', 'yellow'), t(' '), t(clip(m.error, w - 4), { color: 'yellow' })]) : null
  const topRule = isFramed ? null : rule('', w)

  // rows the view may fill: the body less the frame, the header, the tabs, the error and the rule under the tabs
  const chrome = (isFramed ? 2 : 0) + 2 + (errorLine ? 1 : 0) + (topRule ? 1 : 0)
  const budget = Math.max(3, m.rows - chrome)

  let body: RenderChildren[]
  if (m.view === 'list') body = listView()
  else if (m.view === 'card') body = cardView()
  else if (m.view === 'journal') body = journalView()
  else body = summaryView()

  const content = (
    <Box flexDirection="column">
      {header}
      {tabs}
      {topRule}
      {errorLine}
      {body}
    </Box>
  )
  const tree = isFramed ? (
    <Box key="frame" flexDirection="column" borderStyle="round" borderColor="cyan" paddingX={1}>
      {content}
    </Box>
  ) : (
    content
  )
  return { tree, controls }

  // ---------------------------------------------------------------- Agents: a window of two-line rows around the cursor
  function listView(): RenderChildren[] {
    if (!m.shown) return [t(m.error ? '' : 'loading agents…', { dim: true })]
    if (m.agents.length === 0) {
      return [t(`no agents${m.stages.length ? ` in ${m.stages.join(', ')}` : ''}${m.isAll ? '' : ' (l: include finished agents older than 24 h)'}`, { dim: true })]
    }
    const isMulti = new Set(m.agents.map(a => a.stage)).size > 1
    // items: a stage rule before the first agent of each stage (when several), then the agent
    type Item = { kind: 'rule'; stage: string } | { kind: 'agent'; agent: Agent; index: number }
    const items: Item[] = []
    let lastStage = ''
    m.agents.forEach((a, index) => {
      if (isMulti && a.stage !== lastStage) items.push({ kind: 'rule', stage: a.stage })
      lastStage = a.stage
      items.push({ kind: 'agent', agent: a, index })
    })
    const cursorIndex = Math.max(0, m.agents.findIndex(a => agentKey(a) === m.cursorKey))
    const cursorItem = items.findIndex(it => it.kind === 'agent' && it.index === cursorIndex)
    const { start, end } = windowAround(
      items.map(it => (it.kind === 'agent' ? 2 : 1)),
      cursorItem,
      budget - 1, // the footer
    )
    const shownItems = items.slice(start, end)
    const firstAgent = shownItems.find(it => it.kind === 'agent')
    const lastAgent = [...shownItems].reverse().find(it => it.kind === 'agent')
    const above = firstAgent && firstAgent.kind === 'agent' ? firstAgent.index : 0
    const below = lastAgent && lastAgent.kind === 'agent' ? m.agents.length - 1 - lastAgent.index : 0

    const roleW = Math.min(isCompact ? 10 : 16, Math.max(6, ...m.agents.map(a => len(a.role))))
    const ageW = 4
    const lead = 2 + 7 + 1 // cursor, badge, gap
    const out: RenderChildren[] = []
    let n = 0
    for (const it of shownItems) {
      if (it.kind === 'rule') {
        out.push(rule(it.stage, w))
        continue
      }
      const a = it.agent
      const key = agentKey(a)
      const isCursor = key === m.cursorKey || (m.cursorKey === null && it.index === 0)
      const b = badgeOf(a)
      const isDone = a.state === 'done'
      const hotkey = n < 9 ? String(n + 1) : undefined
      n += 1
      const taskW = Math.max(4, w - lead - (roleW + 3) - 1 - 1 - ageW)
      out.push(
        row(`row:${key}`, [
          t(isCursor ? '❯ ' : '  ', { color: 'cyan', bold: true }),
          pill(padEnd(b.label, 5), b.bg, b.fg, b.isDim),
          t(' '),
          <Button
            key={`open:${key}`}
            label={padEnd(clip(a.role, roleW), roleW)}
            plain
            {...(hotkey ? { hotkey } : {})}
            {...(isCursor && m.isAutoFocus ? { autoFocus: true as const } : {})}
            onPress={() => act.open(a)}
          />,
          t(hotkey ? ' ' : '    '),
          t(padEnd(clip(taskText(a), taskW), taskW), { dim: isDone, bold: isCursor && !isDone }),
          t(' '),
          t(padStart(fmtAge(a.age_s), ageW), { dim: true }),
        ]),
      )
      // line 2: what it does now, and on the right model · turns · context
      const pct = ctxPercent(a)
      const meta = `${modelLabel(a)} · ${turnsLabel(a)}t · ${fmtK(a.ctx_tokens)}`
      const metaLen = len(meta) + (pct !== null ? len(` ${pct}%`) : 0)
      const hasMeta = !isCompact && w - lead - metaLen - 1 >= 16
      const nowW = Math.max(4, w - lead - (hasMeta ? metaLen + 1 : 0))
      const now = nowText(a)
      const nowStyle: Style = a.alive && a.action ? { color: 'green' } : a.state === 'error' ? { color: 'red' } : { dim: true }
      out.push(
        row(
          `now:${key}`,
          [
            <Box flexDirection="row">
              {t(' '.repeat(lead))}
              {t(clip(now, nowW), nowStyle)}
            </Box>,
            hasMeta ? (
              <Box flexDirection="row">
                {t(meta, { dim: true })}
                {pct !== null ? t(` ${pct}%`, { color: levelColor(pct), dim: pct < 60 }) : null}
              </Box>
            ) : null,
          ],
          true,
        ),
      )
    }
    const more = [above ? `↑ ${above} more` : '', below ? `↓ ${below} more` : ''].filter(Boolean).join('  ')
    const keys = '↑↓ select · ⏎ open'
    out.push(row('footer', [t(more, { dim: true }), w - len(more) - 2 >= len(keys) ? t(keys, { dim: true }) : null], true))
    return out
  }

  // ---------------------------------------------------------------- the agent card and its feed
  function cardView(): RenderChildren[] {
    const tg = m.target
    const a = tg ? (m.card?.agent ?? m.agents.find(x => x.stage === tg.stage && x.dir_name === tg.dirName) ?? null) : null
    const backButton = (
      <Box key="card-actions" flexDirection="row" columnGap={2}>
        <Button key="back" label="‹ Back" hotkey="b" autoFocus onPress={act.back} />
      </Box>
    )
    if (!tg || !a) {
      return [t(m.error ? '' : tg ? `loading ${tg.role}…` : 'no agent selected (Back, then pick one)', { dim: true }), backButton]
    }
    const b = badgeOf(a)
    const stateColor = colorOf(a) ?? 'gray'
    const cw = isFramed ? w - 4 : w // inside the card's own frame
    const lines: RenderChildren[] = []

    // the title line: badge, role, pid and age; the stage on the right
    const who = `${a.alive && a.pid ? ` · pid ${a.pid}` : ''} · ${fmtAge(a.age_s)} ago`
    lines.push(
      row(
        'card-title',
        [
          <Box flexDirection="row">
            {pill(b.label, b.bg, b.fg, b.isDim)}
            {t(' ')}
            {t(clip(a.role, Math.max(6, cw - 30)), { bold: true, color: stateColor === 'gray' ? undefined : stateColor })}
            {t(clip(who, Math.max(0, cw - 8 - len(a.role) - len(a.stage) - 2)), { dim: true })}
          </Box>,
          t(a.stage, { dim: true }),
        ],
        true,
      ),
    )

    // label / value pairs, two columns when there is room
    const L = 9
    const pair = (label: string, value: RenderChildren, valueLen: number): { node: RenderChildren; len: number } => ({
      node: (
        <Box flexDirection="row">
          {t(padEnd(label, L), { dim: true })}
          {value}
        </Box>
      ),
      len: L + valueLen,
    })
    const val = (s: string, o: Style = { bold: true }) => ({ node: t(s, o), len: len(s) })
    const pct = ctxPercent(a)
    const ctxRow = (): RenderChildren => {
      const tokens = `${fmtK(a.ctx_tokens)}${a.ctx_window ? ` / ${fmtK(a.ctx_window)}` : ''}`
      if (pct === null) return pair('Context', t(tokens, { bold: true }), len(tokens)).node
      const bw = Math.max(6, Math.min(30, cw - L - len(tokens) - 7))
      const bar = barCells(pct, bw)
      return pair(
        'Context',
        <Box flexDirection="row">
          {t(bar.full, { color: levelColor(pct) })}
          {t(bar.empty, { dim: true })}
          {t(` ${pct}%`, { color: levelColor(pct), bold: true })}
          {t(` ${tokens}`, { dim: true })}
        </Box>,
        0,
      ).node
    }
    const turns = `${turnsLabel(a)}${a.sub_turns ? `  (+${a.sub_turns} sub)` : ''}`
    type Cell = { label: string; v: { node: RenderChildren; len: number }; key: string }
    const cells: Cell[] = [
      { label: 'Model', v: val(modelLabel(a)), key: 'card-model' },
      { label: 'Turns', v: val(turns), key: 'card-turns' },
      { label: 'Cost', v: val(fmtCost(a.cost_usd)), key: 'card-cost' },
      { label: 'Runs', v: val(String(a.runs), {}), key: 'card-runs' },
      { label: 'Tag', v: val(a.tag || '—', {}), key: 'card-tag' },
    ]
    const colW = Math.floor(cw / 2)
    const isTwo = cw >= 56 && cells.every(c => L + c.v.len < colW)
    const grid: Cell[][] = isTwo ? [cells.slice(0, 2), cells.slice(2, 4), cells.slice(4)] : cells.map(c => [c])
    grid.forEach((cs, i) => {
      const [l, r] = cs
      if (!l) return
      const left = pair(l.label, l.v.node, l.v.len)
      lines.push(
        <Box key={l.key} flexDirection="row">
          {left.node}
          {r ? t(' '.repeat(Math.max(1, colW - left.len))) : null}
          {r ? pair(r.label, r.v.node, r.v.len).node : null}
        </Box>,
      )
      if (i === 0) lines.push(<Box key="card-context" flexDirection="row">{ctxRow()}</Box>)
    })
    const task = taskText(a)
    wrapLines(task, cw - L, 2).forEach((l, i) => lines.push(row(i === 0 ? 'card-task' : undefined, [t(padEnd(i === 0 ? 'Task' : '', L), { dim: true }), t(l)])))
    if (a.action) lines.push(row('card-now', [t(padEnd('Now', L), { dim: true }), t(clip(actionText(a), cw - L), { color: 'green' })]))
    else if (a.alive) lines.push(row('card-now', [t(padEnd('Now', L), { dim: true }), t('⋯ waiting for the model', { dim: true })]))
    if (a.result && (a.state === 'done' || a.state === 'error')) {
      const isErr = a.result.is_error || a.state === 'error'
      const head = `${a.result.subtype}${a.result.is_error ? ', error' : ''}`
      const textW = cw - L - len(head) - 4
      lines.push(
        row('card-result', [
          t(padEnd('Result', L), { dim: true }),
          pill(isErr ? `✗ ${head}` : `✓ ${head}`, isErr ? 'red' : 'green', isErr ? 'white' : 'black'),
          t(' '),
          t(clip(a.result.text, Math.max(0, textW)), { color: isErr ? 'red' : undefined, dim: !isErr }),
        ]),
      )
    }
    if (a.kind === 'subagent' || a.kind === 'session') {
      lines.push(row('card-kind', [pill('READ-ONLY', 'gray'), t(' '), t(a.kind === 'subagent' ? `sub-agent of ${a.parent ?? '?'}` : 'native Codex session', { dim: true })]))
    }
    if (a.unread.length) lines.push(row('card-unread', [t(`✉ ${a.unread.length} unread in the inbox`, { color: 'yellow', bold: true })]))
    if (a.state === 'dead') lines.push(row('card-dead', [t('no process, no result: died or was killed', { color: 'red' })]))

    const cardNode = isFramed ? (
      <Box key="card" flexDirection="column" borderStyle="round" borderColor={stateColor} borderDimColor={a.state === 'done'} paddingX={1}>
        {lines}
      </Box>
    ) : (
      <Box key="card" flexDirection="column">
        {lines}
      </Box>
    )
    const cardRows = lines.length + (isFramed ? 2 : 0)

    // the feed: fixed time and tool columns, the newest at the bottom, as many as fit
    const feedRoom = Math.max(2, budget - cardRows - 2) // its rule and the Back row
    const feedRows: RenderChildren[] = []
    const items = m.card?.feed ?? []
    const timeW = 8
    const toolW = isCompact ? 6 : 10
    const textW = Math.max(8, w - timeW - 1 - toolW - 1)
    items.forEach((it, i) => {
      const f = feedLine(it)
      const isTool = it.kind === 'tool'
      const isResult = it.kind === 'result' || it.kind === 'result_err'
      const mark = it.sub ? '⤷' : f.mark.trim()
      const col = isTool ? `${mark} ${it.tool ?? 'tool'}` : it.sub ? '⤷ sub' : mark
      const text = isTool ? it.text : f.text
      const style: Style = it.sub
        ? { italic: true, dim: true }
        : { color: f.color, dim: f.dim, bold: f.bold }
      wrapLines(text, textW, isResult ? 1 : 2).forEach((l, j) => {
        feedRows.push(
          <Box key={j === 0 ? `feed:${i}` : undefined} flexDirection="row">
            {t(padEnd(j === 0 ? (it.at ?? '').slice(0, timeW) : '', timeW), { dim: true })}
            {t(' ')}
            {t(padEnd(j === 0 ? clip(col, toolW) : '', toolW), isTool ? { color: 'cyan' } : { dim: true })}
            {t(' ')}
            {t(l, style)}
          </Box>,
        )
      })
    })
    const feedTail = feedRows.slice(-feedRoom)
    return [
      cardNode,
      rule('Feed', w, items.length ? `last ${items.length}` : ''),
      ...(feedTail.length ? feedTail : [t(m.card ? '(the log is empty)' : 'loading the feed…', { dim: true })]),
      backButton,
    ]
  }

  // ---------------------------------------------------------------- Journal: time, tag pill, the line coloured by its first word
  function journalView(): RenderChildren[] {
    const lines = m.shown ? (m.stages.length ? m.shown.journal_tail.filter(l => m.stages.includes(l.stage)) : m.shown.journal_tail) : []
    if (lines.length === 0) return [t(m.shown ? 'the journal is empty' : 'loading…', { dim: true })]
    const isMulti = new Set(lines.map(l => l.stage)).size > 1
    const tagW = Math.min(isCompact ? 8 : 12, Math.max(4, ...lines.map(l => len(l.tag))))
    const lead = 5 + 1 + tagW + 2 + 1
    const out: RenderChildren[] = []
    let lastStage = ''
    lines.forEach((l, i) => {
      if (isMulti && l.stage !== lastStage) out.push(rule(l.stage, w))
      lastStage = l.stage
      const color = journalColor(l.text)
      wrapLines(l.text, w - lead, 2).forEach((txt, j) => {
        out.push(
          j === 0 ? (
            <Box key={`journal:${i}`} flexDirection="row">
              {t(padEnd(l.time.slice(0, 5), 5), { dim: true })}
              {t(' ')}
              {pill(padEnd(clip(l.tag, tagW), tagW), tagColor(l.tag))}
              {t(' ')}
              {t(txt, { color })}
            </Box>
          ) : (
            <Box flexDirection="row">
              {t(' '.repeat(lead))}
              {t(txt, { color })}
            </Box>
          ),
        )
      })
    })
    return out.slice(-budget)
  }

  // ---------------------------------------------------------------- Summary: plan limits, owner questions, locks
  function summaryView(): RenderChildren[] {
    const s = m.shown
    if (!s) return [t('loading…', { dim: true })]
    const sw = isFramed ? w - 4 : w // inside a section's frame
    const section = (key: string, label: string, kids: RenderChildren[]): RenderChildren[] =>
      isFramed
        ? [
            <Box key={key} flexDirection="column" borderStyle="round" borderDimColor paddingX={1}>
              {t(label, { bold: true })}
              {kids}
            </Box>,
          ]
        : [rule(label, w), ...kids]

    // ---- plan limits: one bar per window
    const limitRows: RenderChildren[] = []
    const provW = 8
    const barW = Math.max(6, Math.min(20, sw - provW - 4 - 6 - 14))
    const limitRow = (key: string, provider: string, lw: LimitWindow, note = ''): RenderChildren => {
      const pct = Math.round(lw.percent)
      const cells = barCells(pct, barW)
      const reset = lw.resetsAt !== null ? `  ↻ ${fmtResetShort(lw.resetsAt, m.nowMs)}` : ''
      const used = provW + 4 + barW + 6 + len(reset)
      return row(
        key,
        [
          <Box flexDirection="row">
            {t(padEnd(provider, provW), { bold: true })}
            {t(padEnd(lw.label, 4), { dim: true })}
            {t(cells.full, { color: levelColor(pct) })}
            {t(cells.empty, { dim: true })}
            {t(padStart(`${pct}%`, 6), { color: levelColor(pct), bold: true })}
            {t(reset, { dim: true })}
          </Box>,
          note && sw - used - 2 >= len(note) ? t(note, { dim: true }) : null,
        ],
        true,
      )
    }
    claudeWindows(s).forEach((lw, i) => limitRows.push(limitRow(`limit:claude:${lw.label}`, i === 0 ? 'Claude' : '', lw)))
    for (const [id, rec] of Object.entries(s.codex_limits).sort(([x], [y]) => (x < y ? -1 : 1))) {
      const name = id === 'codex' ? 'Codex' : clip(`Codex ${id}`, provW - 1)
      const age = `·${fmtAge(Math.max(0, s.fetchedAt / 1000 - rec.seen_at))} ago`
      codexWindows(rec.info).forEach((lw, i) => limitRows.push(limitRow(`limit:${id}:${lw.label}`, i === 0 ? name : '', lw, i === 0 ? age : '')))
    }
    if (limitRows.length === 0) limitRows.push(t('no limit data yet', { dim: true }))

    // ---- owner questions: per stage, open count and an OVERDUE pill; the first items
    const qRows: RenderChildren[] = []
    const qs = Object.entries(s.questions).filter(([st]) => m.stages.length === 0 || m.stages.includes(st))
    const stW = Math.min(16, Math.max(6, ...qs.map(([st]) => len(st))))
    for (const [st, q] of qs) {
      qRows.push(
        row(`q:${st}`, [
          t(padEnd(clip(st, stW), stW), { bold: true }),
          t(`  ${q.open} open  `, { dim: q.open === 0 }),
          q.overdue ? pill(`OVERDUE ${q.overdue}`, 'red', 'white') : null,
        ]),
      )
      for (const item of q.items.slice(0, 8)) qRows.push(t(clip(`  ${item}`, sw), { dim: true }))
    }
    if (qRows.length === 0) qRows.push(t(s.questionsOk ? 'no open questions' : 'no data (ask is unavailable or there is no register)', { dim: true }))

    // ---- locks: kind pill, repo, until, owner: why; an expired one struck through
    const lockRows: RenderChildren[] = []
    s.locks.forEach((lk, i) => {
      const until = lk.until.slice(5, 16).replace('T', ' ')
      const rest = ` ${lk.repo}  until ${until}  ${lk.owner_name}: ${lk.why}`
      lockRows.push(
        row(`lock:${i}`, [
          pill(lk.kind, lk.active ? 'magenta' : 'gray', lk.active ? 'white' : 'black', !lk.active),
          t(clip(rest, Math.max(4, sw - len(lk.kind) - 2)), { dim: !lk.active, strike: !lk.active }),
        ]),
      )
    })
    if (lockRows.length === 0) lockRows.push(t('no locks', { dim: true }))

    return [...section('sum-limits', 'Plan limits', limitRows), ...section('sum-questions', 'Owner questions', qRows), ...section('sum-locks', 'Locks', lockRows)]
  }
}
