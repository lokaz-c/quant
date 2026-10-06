// Typed client for the Flask API (docs/api.md). Same origin in production;
// proxied by Vite in development.

export interface DataInfo {
  synthetic: boolean
  file: string
  description: string
  symbols: string[]
  start_date: string
  end_date: string
  bars: number
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

// Percentages are in percent (12.3 = 12.3%); money in dollars
export interface Metrics {
  total_return: number
  cagr: number
  max_drawdown: number
  volatility: number
  sharpe_ratio: number
  win_rate: number
  avg_win: number
  avg_loss: number
  num_trades: number
  final_equity: number
}

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
  equity_curve: EquityPoint[]
  trades: Trade[]
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
  created_at: string
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
}

export interface RunResponse {
  backtest_id: number
  status: string
  metrics: Metrics
  baseline: { backtest_id: number; risk_config: string; metrics: Metrics } | null
}

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  const body: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    const message =
      body && typeof body === 'object' && 'error' in body && typeof body.error === 'string'
        ? body.error
        : `${response.status} ${response.statusText}`
    throw new ApiError(message, response.status)
  }
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
