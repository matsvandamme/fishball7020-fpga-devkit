import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, RenderChildren, Timer } from 'claude-code'

import type {
  BoardStats,
  BuildStats,
  Collected,
  Link,
  RadioStats,
  RepoStats,
  SectionName,
  Snapshot,
  Stats,
  TempSample,
  Workflow,
} from '../types'

const PANE = 'fishball'
const TITLE = 'Fishball7020'
// empty: collect.py reads the checkout it sits in (tools/claude-pane/bin/)
const DEFAULT_REPO = ''

// cadences: the board and radio are cheap local reads, GitHub is five `gh`
// calls, and the status line only needs the board now and then
const FAST_MS = 10_000
const SLOW_MS = 180_000
const CLOSED_MS = 60_000
const FIRST_CLOSED_MS = 5_000
const TICK_MS = 1_000
const HISTORY = 60

// the die limits tools/temps.py warns against: 80 % and 94 % of 85 C
const WARM_C = 68
const HOT_C = 80
const SCALE_C = 85

const BLUE = '#4069FF' // VMAT brand blue, docs/stylesheets/vmat.css
const LEVEL_RGB = [0x3fb950, 0xd29922, 0xf85149] as const
const LEVEL_NAME = ['green', 'yellow', 'red'] as const

const FAST: SectionName[] = ['board', 'radio']
const SLOW: SectionName[] = ['repo', 'build']
const ALL: SectionName[] = ['board', 'radio', 'repo', 'build']

const INITIAL: Stats = {
  snapshot: null,
  collectedAt: {},
  nextAt: { fast: null, slow: null },
  error: null,
  isRefreshing: false,
  history: [],
}
const stats = atom({ plugin: 'fishball-stats', key: 'stats' } as const, INITIAL)

// $.state outlives a reload, so a value an older version of this mod wrote
// (no collectedAt, nextAt or history) is read back as is: fill in what it lacks.
function normalize(s: Partial<Stats> | undefined): Stats {
  return {
    ...INITIAL,
    ...s,
    collectedAt: s?.collectedAt ?? {},
    nextAt: { ...INITIAL.nextAt, ...s?.nextAt },
    history: Array.isArray(s?.history) ? s.history : [],
  }
}
const now = atom({ plugin: 'fishball-stats', key: 'now' } as const, 0)

// Module variables start over on a hot reload, and so do the timers. The
// timers live here, and session.start (which fires again at every reload, and
// whose `$` is the one meant for work that outlives a dispatch) rebuilds them
// from what the engine still knows: whether the pane is open. `polling` holds
// that hook's closures, so a command, a close or a press starts timers on the
// session's `$`, never on their own dispatch's.
let polling: { open: () => void; closed: () => void; refresh: () => void } | undefined
let timers: { fast?: Timer; slow?: Timer; tick?: Timer; closed?: Timer } = {}
const busy: Record<'fast' | 'slow' | 'all', boolean> = { fast: false, slow: false, all: false }
let repo = DEFAULT_REPO
let pollWhileClosed = true

// -- collecting ------------------------------------------------------------------

const tempLevel = (c: number) => (c >= HOT_C ? 2 : c >= WARM_C ? 1 : 0)

function merge(s: Stats, got: Collected, at: number, started: number, kind: 'fast' | 'slow' | 'all'): Stats {
  const snapshot: Snapshot = { ...(s.snapshot ?? {}) }
  const collectedAt = { ...s.collectedAt }
  for (const name of got.sections ?? ALL) {
    const section = got[name]
    if (section === undefined) continue
    // the section tables differ, so each is assigned on its own
    if (name === 'board') snapshot.board = section as BoardStats
    else if (name === 'radio') snapshot.radio = section as RadioStats
    else if (name === 'repo') snapshot.repo = section as RepoStats
    else snapshot.build = section as BuildStats
    collectedAt[name] = at
  }
  let history = s.history
  const t = got.board?.temps_c
  if (t) history = [...history, { at, zynq: t.zynq, ad9361: t.ad9361 }].slice(-HISTORY)
  const nextAt = { ...s.nextAt }
  if (kind !== 'slow') nextAt.fast = timers.fast ? started + FAST_MS : timers.closed ? started + CLOSED_MS : null
  if (kind !== 'fast') nextAt.slow = timers.slow ? started + SLOW_MS : null
  // another collect may still be running (fast and slow overlap now and then)
  const isRefreshing = (Object.keys(busy) as (keyof typeof busy)[]).some(k => k !== kind && busy[k])
  return { snapshot, collectedAt, nextAt, error: null, isRefreshing, history }
}

/** The toasts a change since the previous snapshot earns: transitions only. */
function alerts(prev: Snapshot | null, got: Collected): string[] {
  const out: string[] = []
  if (!prev) return out
  const b = got.board
  if (b && prev.board && typeof b.online === 'boolean' && typeof prev.board.online === 'boolean' && b.online !== prev.board.online) {
    const via = (b.links ?? []).find(l => l.up)
    out.push(b.online ? `${TITLE} connected${via ? ` over ${LINK_NAME[via.name]}` : ''}` : `${TITLE} disconnected`)
  }
  if (b?.temps_c && prev.board?.temps_c) {
    for (const die of ['zynq', 'ad9361'] as const) {
      const was = tempLevel(prev.board.temps_c[die])
      const is = tempLevel(b.temps_c[die])
      if (was === is) continue
      const name = die === 'zynq' ? 'Zynq' : 'AD9361'
      const c = b.temps_c[die].toFixed(1)
      out.push(is === 2 ? `${name} is hot: ${c} °C` : is === 1 ? `${name} is ${is > was ? 'warm' : 'cooling'}: ${c} °C` : `${name} is back to normal: ${c} °C`)
    }
  }
  if (got.repo?.workflows && prev.repo?.workflows) {
    const before = new Map(prev.repo.workflows.map(w => [w.name, w]))
    for (const w of got.repo.workflows) {
      const p = before.get(w.name)
      if (!p || p.status !== 'completed' || w.status !== 'completed') continue
      if (p.conclusion === 'success' && w.conclusion === 'failure') out.push(`CI ✗ ${w.name} failed`)
      else if (p.conclusion === 'failure' && w.conclusion === 'success') out.push(`CI ✓ ${w.name} passes again`)
    }
  }
  return out
}

function ciSummary(workflows: Workflow[] | undefined): { mark: string; color: string } | null {
  if (!workflows || workflows.length === 0) return null
  if (workflows.some(w => w.status === 'completed' && w.conclusion === 'failure')) return { mark: '✗', color: 'red' }
  if (workflows.some(w => w.status !== 'completed')) return { mark: '…', color: 'yellow' }
  return { mark: '✓', color: 'green' }
}

/** The one-line status under the prompt: `fishball ● USB 74°C CI ✓`. */
function statusText(snap: Snapshot | null): string | undefined {
  if (!snap?.board) return undefined
  const b = snap.board
  if (typeof b.online !== 'boolean') return 'fishball ? unreadable'
  if (!b.online) return 'fishball ○ offline'
  const via = (b.links ?? []).find(l => l.up)
  const parts = ['fishball ●', via ? LINK_NAME[via.name] : 'online']
  if (b.temps_c) parts.push(`${Math.round(b.temps_c.zynq)}°C`)
  const ci = ciSummary(snap.repo?.workflows)
  if (ci) parts.push(`CI ${ci.mark}`)
  return parts.join(' ')
}

async function collect($: EngineInterface, sections: SectionName[], kind: 'fast' | 'slow' | 'all'): Promise<void> {
  if (busy[kind] || (kind !== 'all' && busy.all)) return
  busy[kind] = true
  try {
    await update($, stats, s => ({ ...normalize(s), isRefreshing: true }))
    const prev = normalize(await read($, stats))
    const started = await clockNow($)
    const argv = ['python3', `${$.plugin.root}/bin/collect.py`, ...(repo ? [repo] : []), '--sections', sections.join(',')]
    const ran = await $.process.run(argv, { timeoutMs: 30_000 })
    const got = JSON.parse(ran.stdout) as Collected
    const at = await clockNow($)
    const next = await update($, stats, s => merge(normalize(s), got, at, started, kind))
    for (const text of alerts(prev.snapshot, got)) safe(() => $.ui.toast(text, { timeoutMs: 8_000 }))
    safe(() => $.ui.status(statusText(next.snapshot)))
  } catch (err) {
    const error = err instanceof Error ? err.message : String(err)
    await update($, stats, s => ({ ...normalize(s), error, isRefreshing: false })).catch(() => undefined)
  } finally {
    busy[kind] = false
  }
}

/** A `$.ui` call that must never take the collect down with it. */
function safe(fn: () => unknown): void {
  try {
    const r = fn()
    if (r instanceof Promise) r.catch(() => undefined)
  } catch {
    // nothing: the status line and toasts are extras
  }
}

// -- timers --------------------------------------------------------------------------

function cancel(...names: (keyof typeof timers)[]): void {
  for (const n of names) {
    timers[n]?.cancel()
    delete timers[n]
  }
}

/** The pane is open: board and radio fast, GitHub and build slowly, a clock tick. */
function startOpen($: EngineInterface): void {
  cancel('closed')
  timers.fast ??= $.clock.every(FAST_MS, () => void collect($, FAST, 'fast'))
  timers.slow ??= $.clock.every(SLOW_MS, () => void collect($, SLOW, 'slow'))
  timers.tick ??= $.clock.every(TICK_MS, () => void tick($))
}

/** The pane is closed: a board-only read now and then keeps the status line honest. */
function startClosed($: EngineInterface): void {
  cancel('fast', 'slow', 'tick')
  if (!pollWhileClosed) return
  timers.closed ??= $.clock.every(CLOSED_MS, () => void collect($, ['board'], 'fast'))
}

/** The engine's clock (mockable in tests), the module's when the read fails. */
async function clockNow($: EngineInterface): Promise<number> {
  try {
    return await $.clock.now()
  } catch {
    return Date.now()
  }
}

async function tick($: EngineInterface): Promise<void> {
  try {
    const t = await clockNow($)
    await update($, now, () => t)
  } catch {
    // a tick lost is nothing
  }
}

// -- formatting ----------------------------------------------------------------------

const LINK_NAME = { usb: 'USB', eth: 'Ethernet', iio: 'libiio' } as const
const LINK_ICON = { usb: '🔌', eth: '🌐', iio: '🔗' } as const

const mhz = (hz?: number) => (hz === undefined ? '?' : `${(hz / 1e6).toFixed(3)} MHz`)
const msps = (hz?: number) => (hz === undefined ? '?' : `${(hz / 1e6).toFixed(3)} MSPS`)

function duration(s: number): string {
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  return d > 0 ? `${d}d ${h}h` : h > 0 ? `${h}h ${m}m` : `${m}m`
}

function ago(fromMs: number, nowMs: number): string {
  const s = Math.max(0, Math.round((nowMs - fromMs) / 1000))
  return s < 60 ? `${s}s ago` : s < 3600 ? `${Math.round(s / 60)}m ago` : s < 86400 ? `${Math.round(s / 3600)}h ago` : `${Math.round(s / 86400)}d ago`
}

function linkNote(l: Link): string {
  if (l.up) return l.name === 'iio' ? l.addr : `${l.addr}${l.iiod ? '' : ' (ssh only)'}`
  if (l.name !== 'usb') return 'not found'
  return `${l.addr} not answering`
}

function ciMark(status: string, conclusion: string | null): { mark: string; color: string } {
  if (status !== 'completed') return { mark: '…', color: 'yellow' }
  if (conclusion === 'success') return { mark: '✓', color: 'green' }
  if (conclusion === 'skipped' || conclusion === 'cancelled') return { mark: '-', color: 'gray' }
  return { mark: '✗', color: 'red' }
}

/** `▕████████░░░░▏`: `c` over 0..SCALE_C in `width` cells. */
function gauge(c: number, width: number): string {
  const filled = Math.max(0, Math.min(width, Math.round((c / SCALE_C) * width)))
  return `▕${'█'.repeat(filled)}${'░'.repeat(width - filled)}▏`
}

const BLOCKS = '▁▂▃▄▅▆▇█'

/** The sparkline's heights 0..7 for one die, scaled over its own range (4 °C at least). */
function heights(values: number[]): number[] {
  const lo = Math.min(...values)
  const hi = Math.max(...values)
  const mid = (lo + hi) / 2
  const span = Math.max(4, hi - lo)
  const bottom = mid - span / 2
  return values.map(v => Math.max(0, Math.min(7, Math.round(((v - bottom) / span) * 7))))
}

const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'

function base64(bytes: Uint8Array): string {
  let out = ''
  for (let i = 0; i < bytes.length; i += 3) {
    const a = bytes[i] ?? 0
    const b = bytes[i + 1] ?? 0
    const c = bytes[i + 2] ?? 0
    const n = (a << 16) | (b << 8) | c
    out += B64[(n >> 18) & 63]! + B64[(n >> 12) & 63]! + (i + 1 < bytes.length ? B64[(n >> 6) & 63]! : '=') + (i + 2 < bytes.length ? B64[n & 63]! : '=')
  }
  return out
}

/** The Raster cells of a sparkline: one row per die, the newest sample at the right. */
function sparkCells(history: TempSample[], columns: number): string {
  const rows: (readonly [number[], number[]])[] = (['zynq', 'ad9361'] as const).map(die => {
    const vals = history.map(h => h[die])
    return [heights(vals), vals.map(tempLevel)] as const
  })
  const bytes = new Uint8Array(columns * rows.length * 12)
  const view = new DataView(bytes.buffer)
  let off = 0
  for (const [hs, levels] of rows) {
    const pad = columns - hs.length
    for (let x = 0; x < columns; x++) {
      const i = x - pad
      const k = hs[i]
      const cp = k === undefined ? 0x20 : BLOCKS.codePointAt(k)!
      const fg = k === undefined ? 0x01000000 : (LEVEL_RGB[levels[i] ?? 0] ?? LEVEL_RGB[0])
      view.setUint32(off, cp, true)
      view.setUint32(off + 4, fg, true)
      view.setUint32(off + 8, 0x01000000, true)
      off += 12
    }
  }
  return base64(bytes)
}

// -- the hooks ---------------------------------------------------------------------------

export const register: Register = (on, options) => {
  repo = typeof options.repo === 'string' && options.repo !== '' ? options.repo : DEFAULT_REPO
  pollWhileClosed = options.pollWhileClosed !== false

  on('session.start', async ($, e, next) => {
    polling = {
      open: () => startOpen($),
      closed: () => startClosed($),
      refresh: () => void collect($, ALL, 'all'),
    }
    await $.command.register({
      name: 'fishball',
      description: 'Show Fishball7020 board, radio, CI and build stats in a pane',
    })
    // a reload dropped the previous environment's timers; the engine still knows the pane
    let isOpen = false
    try {
      isOpen = (await $.ui.panes()).some(p => p.id === PANE)
    } catch {
      isOpen = false
    }
    await update($, stats, s => ({ ...normalize(s), isRefreshing: false })).catch(() => undefined)
    if (isOpen) {
      startOpen($)
      void collect($, ALL, 'all')
    } else {
      startClosed($)
      if (pollWhileClosed) $.clock.after(FIRST_CLOSED_MS, () => void collect($, ['board'], 'fast'))
    }
    return next(e)
  })

  on('command.run', { command: 'fishball' }, async $ => {
    const opened = await $.ui.open({ id: PANE, title: TITLE })
    if (polling) {
      polling.open()
      polling.refresh()
    } else {
      startOpen($)
      void collect($, ALL, 'all')
    }
    return { text: opened.isPlaced === false ? `Fishball pane not placed: ${opened.reason}` : 'Fishball stats pane opened.' }
  })

  on('ui.close', ($, e, next) => {
    if (e.id === PANE) (polling ? polling.closed() : startClosed($))
    return next(e)
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    const s = normalize(await read($, stats))
    const t = (await read($, now)) || Date.now()
    const snap = s.snapshot
    const cols = e.props.bodyColumns
    const isNarrow = cols < 44

    const Heading = (p: { children: string; section?: SectionName }) => {
      const at = p.section ? s.collectedAt[p.section] : undefined
      return (
        <Box marginTop={1} gap={1}>
          <Text bold>{p.children}</Text>
          {at !== undefined && !isNarrow && <Text dimColor>{ago(at, t)}</Text>}
        </Box>
      )
    }
    const Line = (p: { children: RenderChildren; dim?: boolean; color?: string }) => (
      <Text wrap="truncate-end" dimColor={p.dim} color={p.color}>
        {p.children}
      </Text>
    )
    const Failed = (p: { error?: string }) => <Line color="red">{p.error ?? 'unavailable'}</Line>

    function textmark() {
      return (
        <Box flexDirection="column">
          <Box gap={1}>
            <Text color={BLUE}>◥◥</Text>
            <Text bold>VMAT</Text>
          </Box>
          <Box gap={1}>
            <Text color={BLUE}>◥◥</Text>
            <Text dimColor>{TITLE} · Zynq 7020 + AD9361</Text>
          </Box>
        </Box>
      )
    }

    function toolbar() {
      const fast = s.collectedAt.board ?? s.collectedAt.radio
      const due = s.nextAt.fast
      const words: string[] = []
      if (fast !== undefined) words.push(`updated ${ago(fast, t)}`)
      if (due !== null && !s.isRefreshing) words.push(`next in ${Math.max(0, Math.ceil((due - t) / 1000))}s`)
      return (
        <Box gap={1} marginTop={1}>
          <Button key="refresh" hotkey="r" onPress={() => (polling ? polling.refresh() : void collect($, ALL, 'all'))}>
            Refresh
          </Button>
          <Text dimColor color={s.isRefreshing ? 'cyan' : undefined}>{s.isRefreshing ? '⟳ refreshing…' : words.join(' · ')}</Text>
        </Box>
      )
    }

    function links(b: BoardStats) {
      return (b.links ?? []).map(l => (
        <Box gap={1}>
          <Text>{LINK_ICON[l.name]}</Text>
          <Text>{LINK_NAME[l.name].padEnd(8)}</Text>
          <Text color={l.up ? 'green' : 'gray'}>{l.up ? '●' : '○'}</Text>
          <Text dimColor wrap="truncate-end">{linkNote(l)}</Text>
        </Box>
      ))
    }

    function temps(b: BoardStats) {
      if (!b.temps_c) return null
      const width = Math.max(6, Math.min(30, cols - 19))
      const dies = [
        ['Zynq', b.temps_c.zynq],
        ['AD9361', b.temps_c.ad9361],
      ] as const
      return (
        <Box flexDirection="column">
          <Text dimColor>🌡 die temperatures (warm {WARM_C}, hot {HOT_C} °C)</Text>
          {dies.map(([name, c]) => (
            <Box gap={1}>
              <Text>{name.padEnd(6)}</Text>
              <Text color={LEVEL_NAME[tempLevel(c)]}>{gauge(c, width)}</Text>
              <Text color={LEVEL_NAME[tempLevel(c)]}>{c.toFixed(1)}°C</Text>
            </Box>
          ))}
        </Box>
      )
    }

    function sparkline() {
      // (`h` is the JSX factory here: no local may take that name)
      const hist = s.history
      if (hist.length < 2) return null
      const columns = Math.max(2, Math.min(hist.length, cols - 2))
      const shown = hist.slice(-columns)
      const range = (die: 'zynq' | 'ad9361') => {
        const v = shown.map(x => x[die])
        return `${Math.min(...v).toFixed(0)}–${Math.max(...v).toFixed(0)}`
      }
      const label = (
        <Text dimColor wrap="truncate-end">
          last {shown.length} readings · Zynq {range('zynq')} · AD9361 {range('ad9361')} °C
        </Text>
      )
      if (e.surface === 'terminal') {
        const { Raster } = $.ui.resolve(e)
        return (
          <Box flexDirection="column">
            <Raster key="temps" columns={columns} rows={2} cells={sparkCells(shown, columns)} />
            {label}
          </Box>
        )
      }
      // the other surfaces have no Raster: the same bars as block characters
      return (
        <Box flexDirection="column">
          {(['zynq', 'ad9361'] as const).map(die => {
            const last = shown[shown.length - 1]!
            return (
              <Text color={LEVEL_NAME[tempLevel(last[die])]} wrap="truncate-end">
                {heights(shown.map(x => x[die])).map(k => BLOCKS[k]).join('')}
              </Text>
            )
          })}
          {label}
        </Box>
      )
    }

    function firmware(b: BoardStats) {
      const running = b.fw_build ?? b.firmware
      if (!running) return null
      const local = b.local_describe
      let verdict: { text: string; color: string } | null = null
      if (b.behind !== undefined) {
        const behind = b.behind
        const ahead = b.ahead ?? 0
        if (behind === 0 && ahead === 0) verdict = { text: '✓ the board runs the local build', color: 'green' }
        else if (behind > 0) verdict = { text: `△ board is ${behind} commit${behind === 1 ? '' : 's'} behind local${ahead ? `, ${ahead} ahead` : ''}`, color: 'yellow' }
        else verdict = { text: `△ board is ${ahead} commit${ahead === 1 ? '' : 's'} ahead of local (fetch?)`, color: 'yellow' }
      } else if (b.behind_error) verdict = { text: `? ${b.behind_error}`, color: 'yellow' }
      return (
        <Box flexDirection="column">
          <Box gap={1}>
            <Text dimColor>board</Text>
            <Text wrap="truncate-end">{running}</Text>
          </Box>
          {local && (
            <Box gap={1}>
              <Text dimColor>local</Text>
              <Text wrap="truncate-end">{local}</Text>
            </Box>
          )}
          {verdict && <Line color={verdict.color}>{verdict.text}</Line>}
        </Box>
      )
    }

    function board(b: BoardStats) {
      if (b.online !== true)
        return (
          <Box flexDirection="column">
            {links(b)}
            <Line color={b.online === false ? 'red' : 'yellow'}>
              {b.online === false ? '○ offline' : '? not read this time'} · {b.error ?? 'not found'}
            </Line>
          </Box>
        )
      return (
        <Box flexDirection="column">
          {links(b)}
          {b.model && <Line>{b.model}</Line>}
          {b.uptime_s !== undefined && (
            <Line>
              ⏱ up {duration(b.uptime_s)} · ⚡ load {b.load?.map(n => n.toFixed(2)).join(' ')}
            </Line>
          )}
          {temps(b)}
          {sparkline()}
          {firmware(b)}
          {b.kernel && <Line dim>kernel {b.kernel}</Line>}
          {b.via && <Line dim>read via {b.via}</Line>}
          {b.error && <Line color="yellow">{b.error}</Line>}
        </Box>
      )
    }

    function radio(r: RadioStats) {
      if (!r.ok) return <Line dim>{r.error ?? 'unavailable'}</Line>
      return (
        <Box flexDirection="column">
          <Line>RX LO {mhz(r.rx_lo_hz)}</Line>
          <Line>TX LO {mhz(r.tx_lo_hz)}</Line>
          <Line>rate {msps(r.sample_rate_hz)}</Line>
          <Line>
            BW rx {mhz(r.rx_bw_hz)}
            {isNarrow ? '' : ` · tx ${mhz(r.tx_bw_hz)}`}
          </Line>
          {isNarrow && <Line>BW tx {mhz(r.tx_bw_hz)}</Line>}
          {(r.channels ?? []).map((c, i) => (
            <Line>
              ch{i} rx {c.rx_gain_db} dB ({c.gain_mode}) · tx −{Math.abs(c.tx_atten_db)} dB
            </Line>
          ))}
        </Box>
      )
    }

    function repoSection(r: RepoStats) {
      if (!r.ok) return <Failed error={r.error} />
      return (
        <Box flexDirection="column">
          <Line dim>
            ★ {r.stars} · ⑂ {r.forks} · PRs {r.open_prs} · issues {r.open_issues}
          </Line>
          {(r.workflows ?? []).map(w => {
            const { mark, color } = ciMark(w.status, w.conclusion)
            return (
              <Box gap={1}>
                <Text color={color}>{mark}</Text>
                <Text wrap="truncate-end">{w.name}</Text>
                {!isNarrow && <Text dimColor>{ago(Date.parse(w.at), t)}</Text>}
              </Box>
            )
          })}
          {(r.runners ?? []).map(x => (
            <Line color={x.status === 'online' ? 'green' : 'red'}>
              {x.status === 'online' ? '●' : '○'} runner {x.name} {x.status}
              {x.busy ? ' · busy' : ''}
            </Line>
          ))}
          {r.runners_error && <Line color="yellow">runners: {r.runners_error}</Line>}
        </Box>
      )
    }

    function build(b: BuildStats) {
      if (!b.ok) return <Failed error={b.error} />
      const files = b.sections?.['last modern build'] ?? []
      const built = files[0]?.match(/(\d{4}-\d\d-\d\d \d\d:\d\d)/)?.[1]
      return (
        <Box flexDirection="column">
          <Line>
            {b.describe}
            {b.dirty ? ' (uncommitted changes)' : ''}
          </Line>
          <Line dim>{b.head}</Line>
          <Line>{built ? `last modern build ${built}` : 'no modern build yet'}</Line>
          {(b.sections?.['modern source'] ?? []).map(l => (
            <Line dim>{l}</Line>
          ))}
        </Box>
      )
    }

    return (
      <Box flexDirection="column" width={cols}>
        {textmark()}
        {toolbar()}
        {s.error && <Line color="red">{s.error}</Line>}
        {!snap ? (
          <Line dim>{s.isRefreshing ? 'Collecting stats…' : 'No stats yet.'}</Line>
        ) : (
          <Box flexDirection="column">
            <Heading section="board">📡 Board</Heading>
            {snap.board ? board(snap.board) : <Line dim>not read yet</Line>}
            <Heading section="radio">📻 Radio</Heading>
            {snap.radio ? radio(snap.radio) : <Line dim>not read yet</Line>}
            <Heading section="repo">🐙 GitHub</Heading>
            {snap.repo ? repoSection(snap.repo) : <Line dim>not read yet</Line>}
            <Heading section="build">🔨 Build</Heading>
            {snap.build ? build(snap.build) : <Line dim>not read yet</Line>}
          </Box>
        )}
      </Box>
    )
  })
}
