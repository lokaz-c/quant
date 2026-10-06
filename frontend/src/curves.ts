import type { EquityPoint } from './api'

/**
 * Drawdown from the running peak at each point, in percent. Same definition
 * as PerformanceMetrics.drawdown_series() and the drawdown_curve query in
 * sql/metrics.sql: the peak starts at the first point.
 */
export function drawdownSeries(equity: number[]): number[] {
  let peak = -Infinity
  return equity.map((value) => {
    peak = Math.max(peak, value)
    return peak > 0 ? ((peak - value) / peak) * 100 : 0
  })
}

export interface CurveRow {
  date: string // YYYY-MM-DD
  run?: number
  baseline?: number
}

/** The date part of an API timestamp (always UTC, e.g. 2023-01-03T00:00:00+00:00) */
export function dateOf(timestamp: string): string {
  return timestamp.slice(0, 10)
}

/**
 * One row per date with the run's and the baseline's value, for charts with
 * one line per run. `value` picks equity or drawdown.
 */
export function mergeCurves(
  run: EquityPoint[],
  baseline: EquityPoint[] | null,
  value: 'equity' | 'drawdown',
): CurveRow[] {
  const series = (points: EquityPoint[]) => {
    const equity = points.map((p) => p.equity)
    return value === 'equity' ? equity : drawdownSeries(equity)
  }
  const rows = new Map<string, CurveRow>()
  const add = (points: EquityPoint[], key: 'run' | 'baseline') => {
    series(points).forEach((v, i) => {
      const date = dateOf(points[i]!.timestamp)
      const row = rows.get(date) ?? { date }
      row[key] = v
      rows.set(date, row)
    })
  }
  add(run, 'run')
  if (baseline) add(baseline, 'baseline')
  return [...rows.values()].sort((a, b) => a.date.localeCompare(b.date))
}
