import { useState } from 'react'
import type { Trade } from '../api'
import { dateOf } from '../curves'
import { formatMoney, formatPct, formatQuantity } from '../format'

interface Props {
  tables: { label: string; trades: Trade[] }[]
}

/** Closed round trips; one tab per run when a baseline is shown too */
export function TradesTable({ tables }: Props) {
  const [active, setActive] = useState(0)
  const current = tables[Math.min(active, tables.length - 1)]
  if (!current) return null

  return (
    <div>
      {tables.length > 1 && (
        <div className="tabs" role="tablist" aria-label="Trades for">
          {tables.map((t, i) => (
            <button
              key={t.label}
              type="button"
              role="tab"
              aria-selected={i === active}
              className="tab"
              onClick={() => setActive(i)}
            >
              {t.label} <span className="count">{t.trades.length}</span>
            </button>
          ))}
        </div>
      )}
      {current.trades.length === 0 ? (
        <p className="hint">No closed trades in this run.</p>
      ) : (
        <div className="table-wrap scroll" role="tabpanel">
          <table className="trades">
            <caption className="sr-only">Closed trades, {current.label}</caption>
            <thead>
              <tr>
                <th scope="col">Symbol</th>
                <th scope="col">Entry</th>
                <th scope="col">Exit</th>
                <th scope="col" className="num">Shares</th>
                <th scope="col" className="num">Entry price</th>
                <th scope="col" className="num">Exit price</th>
                <th scope="col" className="num">P&amp;L</th>
                <th scope="col" className="num">P&amp;L %</th>
              </tr>
            </thead>
            <tbody>
              {current.trades.map((t, i) => (
                <tr key={`${t.symbol}-${t.entry_date}-${i}`}>
                  <td>{t.symbol}</td>
                  <td>{dateOf(t.entry_date)}</td>
                  <td>{t.exit_date ? dateOf(t.exit_date) : '–'}</td>
                  <td className="num">{formatQuantity(t.quantity)}</td>
                  <td className="num">{formatMoney(t.entry_price, true)}</td>
                  <td className="num">{formatMoney(t.exit_price, true)}</td>
                  <td className="num">{formatMoney(t.pnl, true)}</td>
                  <td className="num">{formatPct(t.pnl_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
