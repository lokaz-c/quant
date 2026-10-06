import type { ReactNode } from 'react'
import type { RunSummary } from '../api'
import { banner } from '../dataLabel'
import { dash, formatNumber, formatPct } from '../format'
import { NotAvailable, reasonFor } from './NotAvailable'

type SummaryMetric = 'total_return' | 'max_drawdown' | 'sharpe_ratio'

/** A metric cell: the number; n/a with the reason if it is undefined; a dash for a run with no metrics */
function metric(run: RunSummary, key: SummaryMetric, format: (value: number) => string): ReactNode {
  const value = run[key]
  if (value != null) return format(value)
  return run.undefined_metrics ? <NotAvailable reason={reasonFor(run.undefined_metrics, key)} /> : dash
}

interface Props {
  runs: RunSummary[]
  selectedId: number | null
  onSelect: (run: RunSummary) => void
}

export function RunHistory({ runs, selectedId, onSelect }: Props) {
  if (runs.length === 0) return <p className="hint">No runs yet. Stored runs appear here, newest first.</p>

  // run id -> the run that used it as its baseline
  const baselineOf = new Map(runs.filter((r) => r.baseline_run_id).map((r) => [r.baseline_run_id, r.id]))

  return (
    <div className="table-wrap scroll">
      <table className="history">
        <caption className="sr-only">Stored runs, newest first</caption>
        <thead>
          <tr>
            <th scope="col">Run</th>
            <th scope="col">Strategy</th>
            <th scope="col">Risk profile</th>
            <th scope="col">Period</th>
            <th scope="col">Symbols</th>
            <th scope="col">Data</th>
            <th scope="col" className="num">Return</th>
            <th scope="col" className="num">Max drawdown</th>
            <th scope="col" className="num">Sharpe</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.id} aria-selected={r.id === selectedId} className={r.id === selectedId ? 'selected' : undefined}>
              <td>
                <button type="button" className="row-button" onClick={() => onSelect(r)}>
                  #{r.id}
                </button>
                {r.baseline_run_id && <span className="muted block">vs baseline #{r.baseline_run_id}</span>}
                {baselineOf.has(r.id) && <span className="muted block">baseline for #{baselineOf.get(r.id)}</span>}
              </td>
              <td>{r.strategy}</td>
              <td>{r.risk_config}</td>
              <td className="nowrap">
                {r.start_date} to {r.end_date}
              </td>
              <td title={r.symbols?.join(', ') ?? 'all'}>{r.symbols ? r.symbols.length : 'all'}</td>
              <td title={`${r.data_source}, reported ${r.reported_source}`}>
                {banner({ source: r.data_source, reported_source: r.reported_source, synthetic: r.synthetic, description: '' }).short}
              </td>
              <td className="num">{metric(r, 'total_return', formatPct)}</td>
              <td className="num">{metric(r, 'max_drawdown', formatPct)}</td>
              <td className="num">{metric(r, 'sharpe_ratio', formatNumber)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
