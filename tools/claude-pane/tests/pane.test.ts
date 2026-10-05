import type { On } from 'claude-code'
import { expect, mock, test } from 'claude-code/testing'

/** `/fishball` as the person types it at a fullscreen terminal. */
const FISHBALL = {
  command: 'fishball',
  args: '',
  origin: { kind: 'composer' },
  presentation: { isFullscreen: true, columns: 160 },
} as const

const PANE = {
  component: 'Pane',
  requestId: 'fishball',
  props: {
    title: 'Fishball7020',
    isFocused: false,
    bodyColumns: 48,
    view: {},
    placement: 'dock',
    scroll: { offset: 0, bodyRows: 40 },
  },
} as const

const LINKS_DOWN = [
  { name: 'usb', addr: '192.168.2.1', iface: 'usb0', up: false, iiod: false },
  { name: 'eth', addr: 'no answer', up: false, iiod: false },
  { name: 'iio', addr: 'usb:', up: false, iiod: false },
]
const LINKS_USB = [
  { name: 'usb', addr: '192.168.2.1', iface: 'usb0', up: true, iiod: true },
  { name: 'eth', addr: 'no answer', up: false, iiod: false },
  { name: 'iio', addr: 'usb:3.35.4', up: true, iiod: true },
]

const REPO_OK = {
  ok: true,
  stars: 13,
  forks: 4,
  open_prs: 0,
  open_issues: 0,
  branch: 'main',
  workflows: [
    { name: 'Hardware', status: 'completed', conclusion: 'success', branch: 'main', at: '2026-10-05T17:47:24Z' },
    { name: 'Docs', status: 'completed', conclusion: 'failure', branch: 'main', at: '2026-10-05T17:47:24Z' },
  ],
  runners: [{ name: 'hardware-runner', status: 'online', busy: false }],
}
const BUILD_OK = { ok: true, head: '608cb36 SDR++', describe: 'v2.3-66-g608cb36', dirty: true, sections: {} }

const OFFLINE = {
  board: { ok: false, online: false, error: 'board not found on USB or the network', links: LINKS_DOWN },
  radio: { ok: false, error: 'board offline' },
  repo: REPO_OK,
  build: BUILD_OK,
  sections: ['board', 'radio', 'repo', 'build'],
  took_s: 2.3,
}

const online = (zynq: number, ad9361 = 53.5) => ({
  ok: true,
  online: true,
  host: '192.168.2.1',
  links: LINKS_USB,
  model: 'FISH Ball PlutoSDR Rev.A (Z7020/AD9361)',
  firmware: 'modern (Debian), v2.0-9-g5ae29d94-dirty',
  kernel: '6.12.0-g61ef303acadc-dirty',
  fw_build: 'v2.0-9-g5ae29d94-dirty',
  local_describe: 'v2.3-66-g608cb36',
  behind: 255,
  ahead: 0,
  via: 'iiod 192.168.2.1',
  uptime_s: 481.85,
  load: [0.24, 0.05, 0.02],
  temps_c: { zynq, ad9361 },
})

const RADIO_OK = {
  ok: true,
  via: 'iiod 192.168.2.1',
  rx_lo_hz: 2.4e9,
  tx_lo_hz: 2.4e9,
  sample_rate_hz: 30.72e6,
  rx_bw_hz: 18e6,
  tx_bw_hz: 18e6,
  channels: [{ rx_gain_db: 71, gain_mode: 'slow_attack', tx_atten_db: -89.75 }],
}

const ONLINE = {
  board: online(73.8),
  radio: RADIO_OK,
  repo: REPO_OK,
  build: BUILD_OK,
  sections: ['board', 'radio', 'repo', 'build'],
  took_s: 2.6,
}

type Ran = { exitCode: number; stdout: string; stderr: string; isStdoutTruncated: boolean; isStderrTruncated: boolean }
const printed = (snapshot: unknown): { value: Ran } => ({
  value: { exitCode: 0, stdout: JSON.stringify(snapshot), stderr: '', isStdoutTruncated: false, isStderrTruncated: false },
})

/** The sections a collect.py argv asks for. */
const sectionsOf = (argv: readonly string[]): string[] => {
  const i = argv.indexOf('--sections')
  return i === -1 ? ['board', 'radio', 'repo', 'build'] : (argv[i + 1] ?? '').split(',')
}

/** Answers collect.py with the sections asked for, out of a full snapshot the test may swap. */
type Held = { snapshot: Record<string, unknown> }

function collector(on: On, state: Held) {
  const runs: string[][] = []
  on('process.run', (_$, e) => {
    const sections = sectionsOf(e.argv)
    runs.push(sections)
    const out: Record<string, unknown> = { sections, took_s: 1 }
    for (const s of sections) out[s] = state.snapshot[s]
    return printed(out)
  })
  return runs
}

/** What a session's start needs beneath the plugin: the command registry and the start itself. */
const sessionBottom = (on: On) => {
  on('command.register', () => ({ value: { command: 'fishball' } }))
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
}

const quietUi = (on: On) => {
  const toasts: string[] = []
  const statuses: (string | undefined)[] = []
  on('ui.toast', (_$, e) => {
    toasts.push(e.text)
    return { value: undefined }
  })
  on('ui.status', (_$, e) => {
    statuses.push(e.text)
    return { value: undefined }
  })
  return { toasts, statuses }
}

test('the pane says there are no stats before the first collect, under the VMAT textmark', async ($, on) => {
  mock.clock(on, { now: 1_700_000_000_000 })
  on('ui.panes', () => ({ value: [] }))
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'fishball-stats', surface, ...PANE })
    expect(await ui.find({ type: 'Text', text: /No stats yet/ })).toBeDefined()
    expect(await ui.find({ key: 'refresh' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^VMAT$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^◥◥$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /Fishball7020/ })).toBeDefined()
    await ui.unmount()
  }
})

test('the pane shows an offline board beside CI and build', async ($, on) => {
  mock.clock(on, { now: 1_700_000_000_000 })
  on('ui.panes', () => ({ value: [] }))
  quietUi(on)
  collector(on, { snapshot: OFFLINE })
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'fishball-stats', surface, ...PANE })
    await ui.press({ key: 'refresh' })
    expect(await ui.find({ type: 'Text', text: /offline · board not found on USB or the network/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /192\.168\.2\.1 not answering/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^not found$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^Hardware$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /CI on main/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /runner hardware-runner online/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /v2\.3-66-g608cb36 \(uncommitted changes\)/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /📡 Board/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /🐙 GitHub/ })).toBeDefined()
    await ui.unmount()
  }
})

test('an online board draws temperature gauges and the board-vs-local build verdict', async ($, on) => {
  mock.clock(on, { now: 1_700_000_000_000 })
  on('ui.panes', () => ({ value: [] }))
  quietUi(on)
  collector(on, { snapshot: ONLINE })
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'fishball-stats', surface, ...PANE })
    await ui.press({ key: 'refresh' })
    // 73.8 of 85 over a 29-cell bar (48 columns - 19) is 25 filled cells
    expect(await ui.find({ type: 'Text', text: /^▕█{25}░{4}▏$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /🌡 die temperatures/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^73\.8°C$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^53\.5°C$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /board is 255 commits behind local/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^v2\.0-9-g5ae29d94-dirty$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^v2\.3-66-g608cb36$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /⏱ up 8m · ⚡ load 0\.24 0\.05 0\.02/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /RX LO 2400\.000 MHz/ })).toBeDefined()
    // one reading is no history: the sparkline waits for a second (the desktop mount is that second)
    if (surface === 'terminal') expect(await ui.find({ type: 'Text', text: /last \d+ readings/ })).toBeUndefined()
    await ui.unmount()
  }
})

test('two readings make a temperature sparkline: a Raster on the terminal, block text elsewhere', async ($, on) => {
  mock.clock(on, { now: 1_700_000_000_000 })
  on('ui.panes', () => ({ value: [] }))
  quietUi(on)
  const state: Held = { snapshot: ONLINE }
  collector(on, state)
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'fishball-stats', surface, ...PANE })
    await ui.press({ key: 'refresh' })
    state.snapshot = { ...ONLINE, board: online(76.3, 55.3) }
    await ui.press({ key: 'refresh' })
    expect(await ui.find({ type: 'Text', text: /last \d+ readings · Zynq \d+–\d+ · AD9361 \d+–\d+ °C/ })).toBeDefined()
    if (surface === 'terminal') {
      expect(await ui.find({ type: 'Raster', key: 'temps' })).toBeDefined()
    } else {
      expect(await ui.find({ type: 'Raster' })).toBeUndefined()
      expect(await ui.find({ type: 'Text', text: /^[▁▂▃▄▅▆▇█]+$/ })).toBeDefined()
    }
    await ui.unmount()
  }
})

test('the status line summarises the board, and only transitions toast', async ($, on) => {
  mock.clock(on, { now: 1_700_000_000_000 })
  on('ui.panes', () => ({ value: [] }))
  const { toasts, statuses } = quietUi(on)
  const state: Held = { snapshot: ONLINE }
  collector(on, state)
  const ui = await $.ui.mount({ plugin: 'fishball-stats', surface: 'terminal', ...PANE })

  await ui.press({ key: 'refresh' })
  expect(statuses.at(-1)).toBe('fishball ● USB 74°C CI ✗')
  expect(toasts).toEqual([]) // the first reading has nothing to compare with

  await ui.press({ key: 'refresh' }) // the same again: no change, no toast
  expect(toasts).toEqual([])

  // Zynq crosses the warning level, Docs passes again
  state.snapshot = {
    ...ONLINE,
    board: online(62.0),
    repo: { ...REPO_OK, workflows: REPO_OK.workflows.map(w => ({ ...w, conclusion: 'success' })) },
  }
  await ui.press({ key: 'refresh' })
  expect(toasts).toEqual(['Zynq is back to normal: 62.0 °C', 'CI ✓ Docs passes again'])
  expect(statuses.at(-1)).toBe('fishball ● USB 62°C CI ✓')

  // the board goes away, Hardware fails
  state.snapshot = {
    ...OFFLINE,
    repo: { ...REPO_OK, workflows: [{ ...REPO_OK.workflows[0]!, conclusion: 'failure' }] },
  }
  await ui.press({ key: 'refresh' })
  expect(toasts.slice(2)).toEqual(['Fishball7020 disconnected', 'CI ✗ Hardware failed'])
  expect(statuses.at(-1)).toBe('fishball ○ offline')

  // and comes back over USB, hot; Hardware is green again
  state.snapshot = { ...ONLINE, board: online(81.5) }
  await ui.press({ key: 'refresh' })
  expect(toasts.slice(4)).toEqual(['Fishball7020 connected over USB', 'CI ✓ Hardware passes again'])
  expect(statuses.at(-1)).toBe('fishball ● USB 82°C CI ✗')

  // one read that fails outright is a glitch, not a disconnect: no toast either way
  state.snapshot = { ...ONLINE, board: { ok: false, error: 'timed out (TimeoutError)' } }
  await ui.press({ key: 'refresh' })
  expect(statuses.at(-1)).toBe('fishball ? unreadable')
  expect(await ui.find({ type: 'Text', text: /\? not read this time · timed out/ })).toBeDefined()
  state.snapshot = { ...ONLINE, board: online(81.5) }
  await ui.press({ key: 'refresh' })
  expect(toasts.length).toBe(6)
  await ui.unmount()
})

test('/fishball opens the pane and polls on its own: board and radio fast, GitHub and build slowly', async ($, on) => {
  const clock = mock.clock(on, { now: 1_000_000 })
  on('ui.panes', () => ({ value: [] }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  quietUi(on)
  const runs = collector(on, { snapshot: ONLINE })

  const ran = await $.command.run(FISHBALL)
  expect(ran.text).toBe('Fishball stats pane opened.')
  await clock.settle()
  expect(runs).toEqual([['board', 'radio', 'repo', 'build']])

  await clock.advance(10_000)
  expect(runs).toEqual([['board', 'radio', 'repo', 'build'], ['board', 'radio']])
  await clock.advance(10_000)
  expect(runs.length).toBe(3)
  expect(runs.filter(r => r.includes('repo')).length).toBe(1)

  // at three minutes GitHub and the build go again, the board 18 times
  await clock.advance(160_000)
  expect(runs.filter(r => r.includes('repo')).length).toBe(2)
  expect(runs.filter(r => r.includes('board'))).toHaveLength(19)

  // a second /fishball starts no second timer
  await $.command.run(FISHBALL)
  await clock.settle()
  const before = runs.length
  await clock.advance(10_000)
  expect(runs.length).toBe(before + 1)

  // the pane shows when it was updated and when the next read is due
  const ui = await $.ui.mount({ plugin: 'fishball-stats', surface: 'terminal', ...PANE })
  expect(await ui.find({ type: 'Text', text: /^updated \d+s ago · next in \d+s$/ })).toBeDefined()
  await ui.unmount()

})

test('after a hot reload with the pane still open, session.start resumes polling', async ($, on) => {
  const clock = mock.clock(on, { now: 5_000_000 })
  on('ui.panes', () => ({
    value: [{ id: 'fishball', title: 'Fishball7020', isShown: true, isFocused: false, isPlaced: true }],
  }))
  quietUi(on)
  const runs = collector(on, { snapshot: ONLINE })
  sessionBottom(on)
  await $.session.start({ cwd: '/tmp/devkit-test', surface: 'terminal', isInteractive: true })
  await clock.settle()
  expect(runs).toEqual([['board', 'radio', 'repo', 'build']])
  await clock.advance(10_000)
  expect(runs).toEqual([['board', 'radio', 'repo', 'build'], ['board', 'radio']])
})

test('with the pane closed the status line is kept by a board-only read, unless opted out', async ($, on) => {
  const clock = mock.clock(on, { now: 7_000_000 })
  on('ui.panes', () => ({ value: [] }))
  const { statuses } = quietUi(on)
  const runs = collector(on, { snapshot: ONLINE })
  sessionBottom(on)
  await $.session.start({ cwd: '/tmp/devkit-test', surface: 'terminal', isInteractive: true })
  await clock.advance(5_000)
  expect(runs).toEqual([['board']])
  expect(statuses.at(-1)).toBe('fishball ● USB 74°C')
  await clock.advance(60_000)
  expect(runs).toEqual([['board'], ['board']])
})

test('pollWhileClosed: false reads nothing while the pane is closed', { options: { pollWhileClosed: false } }, async ($, on) => {
  const clock = mock.clock(on, { now: 9_000_000 })
  on('ui.panes', () => ({ value: [] }))
  quietUi(on)
  const runs = collector(on, { snapshot: ONLINE })
  sessionBottom(on)
  await $.session.start({ cwd: '/tmp/devkit-test', surface: 'terminal', isInteractive: true })
  await clock.advance(120_000)
  expect(runs).toEqual([])
})

test('the repo option names the checkout collect.py reads', { options: { repo: '/tmp/devkit' } }, async ($, on) => {
  mock.clock(on, { now: 1_700_000_000_000 })
  on('ui.panes', () => ({ value: [] }))
  quietUi(on)
  const argvs: (readonly string[])[] = []
  on('process.run', (_$, e) => {
    argvs.push(e.argv)
    return printed(ONLINE)
  })
  const ui = await $.ui.mount({ plugin: 'fishball-stats', surface: 'terminal', ...PANE })
  await ui.press({ key: 'refresh' })
  expect(argvs[0]?.[2]).toBe('/tmp/devkit')
  expect(argvs[0]?.slice(-2)).toEqual(['--sections', 'board,radio,repo,build'])
  await ui.unmount()
})

test('stats an older version of the mod left in the session still draw', async ($, on) => {
  // the first version's shape: no collectedAt, nextAt or history
  const OLD = { snapshot: null, error: null, updatedAt: 1, isRefreshing: false }
  on('state.get', { plugin: 'fishball-stats', key: 'stats' }, () => ({ value: { value: OLD, version: 1 } }))
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'fishball-stats', surface, ...PANE })
    expect(await ui.find({ key: 'refresh' })).toBeDefined()
    await ui.unmount()
  }
})

test('with no repo option, collect.py is left to find the checkout it sits in', async ($, on) => {
  mock.clock(on, { now: 1_700_000_000_000 })
  on('ui.panes', () => ({ value: [] }))
  quietUi(on)
  const argvs: (readonly string[])[] = []
  on('process.run', (_$, e) => {
    argvs.push(e.argv)
    return printed(ONLINE)
  })
  const ui = await $.ui.mount({ plugin: 'fishball-stats', surface: 'terminal', ...PANE })
  await ui.press({ key: 'refresh' })
  expect(argvs[0]?.[1]).toMatch(/bin\/collect\.py$/)
  expect(argvs[0]?.[2]).toBe('--sections')
  await ui.unmount()
})
