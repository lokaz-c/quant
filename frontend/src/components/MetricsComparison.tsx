import type { Metrics } from '../api'
import { formatMoney, formatNumber, formatPct, formatSigned } from '../format'

interface Row {
  key: keyof Metrics
  label: string
  format: (value: number) => string
  // How to read the change: for drawdown and volatility, lower is the improvement
  lowerIsBetter?: boolean
  formatChange?: (change: number) => string
}

export const ROWS: Row[] = [
  { key: 'total_return', label: 'Total return', format: (v) => formatPct(v) },
  { key: 'cagr', label: 'CAGR', format: (v) => formatPct(v) },
  { key: 'max_drawdown', label: 'Max drawdown', format: (v) => formatPct(v), lowerIsBetter: true },
  { key: 'volatility', label: 'Volatility (annualised)', format: (v) => formatPct(v), lowerIsBetter: true },
  { key: 'sharpe_ratio', label: 'Sharpe ratio', format: (v) => formatNumber(v) },
  { key: 'num_trades', label: 'Trades', format: (v) => String(v), formatChange: (c) => formatSigned(c, 0) },
  { key: 'win_rate', label: 'Win rate', format: (v) => formatPct(v) },
  {
    key: 'final_equity',
    label: 'Final equity',
    format: (v) => formatMoney(v),
    formatChange: (c) => (Math.round(c) === 0 ? '$0' : `${c > 0 ? '+' : '-'}${formatMoney(Math.abs(c))}`),
  },
]

interface Props {
  run: { label: string; metrics: Metrics }
  baseline: { label: string; metrics: Metrics } | null
}

export function MetricsComparison({ run, baseline }: Props) {
  return (
    <div className="table-wrap">
      <table className="metrics">
        <caption className="sr-only">
          {baseline ? `${run.label} compared with ${baseline.label}` : `Metrics for ${run.label}`}
        </caption>
        <thead>
          <tr>
            <th scope="col">Metric</th>
            {baseline && <th scope="col" className="num">{baseline.label}</th>}
            <th scope="col" className="num">{run.label}</th>
            {baseline && <th scope="col" className="num">Change</th>}
          </tr>
        </thead>
        <tbody>
          {ROWS.map((row) => {
            const value = run.metrics[row.key]
            const base = baseline?.metrics[row.key]
            return (
              <tr key={row.key}>
                <th scope="row">
                  {row.label}
                  {row.lowerIsBetter && <span className="muted block">lower is better</span>}
                </th>
                {baseline && <td className="num">{row.format(base as number)}</td>}
                <td className="num strong">{row.format(value)}</td>
                {baseline && (
                  <td className="num">{(row.formatChange ?? formatSigned)(value - (base as number))}</td>
                )}
              </tr>
            )
          })}
        </tbody>
      </table>
      {baseline && (
        <p className="hint">
          Change = {run.label} minus {baseline.label}, in percentage points for the percentages.
        </p>
      )}
    </div>
  )
}
