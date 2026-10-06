import type { Metrics, UndefinedMetrics } from '../api'
import { formatMoney, formatNumber, formatPct, formatSigned } from '../format'
import { NOT_AVAILABLE, NotAvailable, reasonFor } from './NotAvailable'

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

interface Column {
  label: string
  metrics: Metrics
  // the reason for each null metric, from the API
  undefinedMetrics: UndefinedMetrics | null
}

interface Props {
  run: Column
  baseline: Column | null
}

function Value({ row, column }: { row: Row; column: Column }) {
  const value = column.metrics[row.key]
  return value == null ? <NotAvailable reason={reasonFor(column.undefinedMetrics, row.key)} /> : <>{row.format(value)}</>
}

export function MetricsComparison({ run, baseline }: Props) {
  // One line per undefined value on screen, so the reason can be read without hovering
  const notes = ROWS.flatMap((row) =>
    [baseline, run]
      .filter((column): column is Column => column != null && column.metrics[row.key] == null)
      .map((column) => `${row.label}, ${column.label}: ${reasonFor(column.undefinedMetrics, row.key)}`),
  )

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
                {baseline && (
                  <td className="num">
                    <Value row={row} column={baseline} />
                  </td>
                )}
                <td className="num strong">
                  <Value row={row} column={run} />
                </td>
                {baseline && (
                  <td className="num">
                    {value == null || base == null ? NOT_AVAILABLE : (row.formatChange ?? formatSigned)(value - base)}
                  </td>
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
      {notes.length > 0 && (
        <div className="hint">
          <p>n/a: the metric is undefined for that run.</p>
          <ul className="notes">
            {notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
