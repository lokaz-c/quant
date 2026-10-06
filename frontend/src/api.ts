// Typed client for the Flask API (docs/api.md). Same origin in production;
// proxied by Vite in development.

export type DataSource = 'synthetic' | 'market-data'
// What the market-data service said the bars are; always 'synthetic' for the local file
export type ReportedSource = 'synthetic' | 'alpaca' | 'mixed'

/** Where bars came from: returned with every run and by GET /api/data */
export interface DataLabel {
  source: DataSource
  reported_source: ReportedSource
  synthetic: boolean
  description: string
  file?: string
  symbol_sources?: Record<string, string> | null
  adjustment?: 'split' | 'raw' | null
}

/** This server's caps on one run (QUANT_MAX_SYMBOLS, QUANT_MAX_RANGE_DAYS, QUANT_BACKTEST_TIMEOUT_SECONDS) */
export interface Limits {
  max_symbols: number
  // calendar days from start_date to end_date, both included
  max_range_days: number
  timeout_seconds: number
}

export interface DataInfo extends DataLabel {
  symbols: string[]
  start_date: string
  end_date: string
  // business days in the synthetic file; null for market-data
  bars: number | null
  available_sources: DataSource[]
  default_source: DataSource
  limits: Limits
}

export interface ParameterLimit {
  type: 'int' | 'float'
  min: number
  max: number
}

export interface Strategy {
  id: number
  name: string
  description: string | null
  parameters: Record<string, number>
  // null for a stored strategy with no implementation (it can't be run)
  parameter_limits: Record<string, ParameterLimit> | null
}

export interface RiskProfile {
  id: number
  name: string
  max_position_size: number | null
  max_portfolio_exposure: number | null
  stop_loss_pct: number | null
  take_profit_pct: number | null
  max_drawdown_pct: number | null
  enabled: boolean
}

// Percentages are in percent (12.3 = 12.3%); money in dollars. A metric is
// null when it is undefined for the run (Sharpe with zero volatility, win rate
// with no trades, ...); the API never sends NaN or Infinity
// (docs/api.md#undefined-metrics).
export interface Metrics {
  total_return: number
  cagr: number | null
  max_drawdown: number
  volatility: number | null
  sharpe_ratio: number | null
  win_rate: number | null
  avg_win: number | null
  avg_loss: number | null
  num_trades: number
  final_equity: number
}

/** Sent next to metrics: the reason for each null metric, e.g. {"sharpe_ratio": "zero volatility"} */
export type UndefinedMetrics = Record<string, string>

export interface EquityPoint {
  timestamp: string
  equity: number
  cash: number | null
  positions_value: number | null
}

export interface Trade {
  symbol: string
  entry_date: string
  exit_date: string | null
  entry_price: number
  exit_price: number | null
  quantity: number
  side: string
  pnl: number | null
  pnl_pct: number | null
  status: string
}

export interface Run {
  id: number
  strategy: string
  risk_config: string
  start_date: string
  end_date: string
  initial_capital: number
  symbols: string[] | null
  strategy_parameters: Record<string, number> | null
  baseline_run_id: number | null
  status: string
  created_at: string
  metrics: Metrics | null
  // null when metrics is null (a run that failed)
  undefined_metrics: UndefinedMetrics | null
  equity_curve: EquityPoint[]
  trades: Trade[]
  data: DataLabel
}

export interface RunSummary {
  id: number
  strategy: string
  risk_config: string
  start_date: string
  end_date: string
  symbols: string[] | null
  initial_capital: number
  baseline_run_id: number | null
  status: string
  total_return: number | null
  max_drawdown: number | null
  sharpe_ratio: number | null
  // why any of the three metrics above is null; null for a run with no metrics
  undefined_metrics: UndefinedMetrics | null
  created_at: string
  data_source: DataSource
  reported_source: ReportedSource
  synthetic: boolean
}

export interface RunRequest {
  strategy_name: string
  risk_config_name: string
  start_date: string
  end_date: string
  initial_capital: number
  symbols: string[]
  parameters: Record<string, number>
  compare_to_baseline: boolean
  // the source the form's symbols and dates came from; the server default if omitted
  data_source?: DataSource
}

export interface RunResponse {
  backtest_id: number
  status: string
  metrics: Metrics
  undefined_metrics: UndefinedMetrics
  baseline: { backtest_id: number; risk_config: string; metrics: Metrics; undefined_metrics: UndefinedMetrics } | null
  data: DataLabel
}

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/** The message to show for an error response: RFC 9457 `detail`, or the older `error` field */
function errorMessage(response: Response, body: unknown): string {
  if (response.status === 429) {
    const wait = Number(response.headers.get('Retry-After'))
    return `Too many requests from this address. Try again in ${Number.isFinite(wait) && wait > 0 ? wait : 60} s.`
  }
  if (body && typeof body === 'object') {
    for (const field of ['detail', 'error'] as const) {
      const value = (body as Record<string, unknown>)[field]
      if (typeof value === 'string' && value) return value
    }
  }
  return `${response.status} ${response.statusText}`
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  const body: unknown = await response.json().catch(() => null)
  if (!response.ok) throw new ApiError(errorMessage(response, body), response.status)
  return body as T
}

export const api = {
  dataInfo: () => request<DataInfo>('/api/data'),
  strategies: () => request<Strategy[]>('/api/strategies/'),
  riskProfiles: () => request<RiskProfile[]>('/api/risk-configs/'),
  runs: (limit = 50) => request<RunSummary[]>(`/api/backtest/list?limit=${limit}`),
  run: (id: number) => request<Run>(`/api/backtest/${id}`),
  startRun: (body: RunRequest) =>
    request<RunResponse>('/api/backtest/', { method: 'POST', body: JSON.stringify(body) }),
}
