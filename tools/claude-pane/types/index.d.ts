export type Section = { ok: boolean; error?: string }

export type Link = {
  name: 'usb' | 'eth' | 'iio'
  addr: string
  iface?: string
  up: boolean
  iiod: boolean
  /** an address the board holds that does not answer from this machine */
  reported?: boolean
}

export type BoardStats = Section & {
  links?: Link[]
  via?: string
  online?: boolean
  host?: string
  iiod?: boolean
  model?: string
  firmware?: string
  kernel?: string
  fw_build?: string | null
  uptime_s?: number
  load?: number[]
  temps_c?: { zynq: number; ad9361: number }
  /** `git describe` of the local checkout, read beside the board's fw_build */
  local_describe?: string | null
  /** local commits the board's build has not got (its g<sha> .. HEAD) */
  behind?: number
  /** commits of the board's build the local checkout has not got */
  ahead?: number
  behind_error?: string
}

export type RadioChannel = { rx_gain_db: number; gain_mode: string; tx_atten_db: number }

export type RadioStats = Section & {
  via?: string
  rx_lo_hz?: number
  tx_lo_hz?: number
  sample_rate_hz?: number
  rx_bw_hz?: number
  tx_bw_hz?: number
  channels?: RadioChannel[]
}

export type Workflow = {
  name: string
  status: string
  conclusion: string | null
  branch: string
  at: string
}

export type RepoStats = Section & {
  slug?: string
  /** the default branch, whose runs `workflows` lists */
  branch?: string
  stars?: number
  forks?: number
  open_prs?: number
  open_issues?: number
  workflows?: Workflow[]
  runners?: { name: string; status: string; busy: boolean }[]
  runners_error?: string
}

export type BuildStats = Section & {
  head?: string
  describe?: string
  dirty?: boolean
  sections?: Record<string, string[]>
}

export type SectionName = 'board' | 'radio' | 'repo' | 'build'

/** What one run of bin/collect.py prints: only the sections it was asked for. */
export type Collected = {
  board?: BoardStats
  radio?: RadioStats
  repo?: RepoStats
  build?: BuildStats
  sections?: SectionName[]
  took_s: number
}

/** The merged picture: every section as last collected, each with its own time. */
export type Snapshot = {
  board?: BoardStats
  radio?: RadioStats
  repo?: RepoStats
  build?: BuildStats
}

/** One temperature reading, for the sparkline. */
export type TempSample = { at: number; zynq: number; ad9361: number }

export type Stats = {
  snapshot: Snapshot | null
  /** when each section was last collected, ms since the epoch */
  collectedAt: Partial<Record<SectionName, number>>
  /** when each timer is next due, ms since the epoch */
  nextAt: { fast: number | null; slow: number | null }
  error: string | null
  isRefreshing: boolean
  history: TempSample[]
}

declare module 'claude-code' {
  interface PluginState {
    'fishball-stats': {
      stats: Stats
      /** the clock, written once a second while the pane is open, for countdowns */
      now: number
    }
  }
}
