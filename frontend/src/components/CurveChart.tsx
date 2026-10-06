import { useState } from 'react'
import { CartesianGrid, Line, LineChart, Tooltip, XAxis, YAxis, type TooltipContentProps } from 'recharts'
import type { CurveRow } from '../curves'
import { formatMonth } from '../format'

export interface Series {
  key: 'run' | 'baseline'
  label: string
}

// Black and grey to match lorenzokamanzi.com. The baseline is also dashed,
// and both lines are named in the legend, so colour is never the only cue.
const STYLE = {
  run: { stroke: '#000000', dash: undefined },
  baseline: { stroke: '#8A8A8A', dash: '6 4' },
} as const

interface Props {
  title: string
  description: string
  rows: CurveRow[]
  series: Series[]
  formatValue: (value: number) => string
  formatTick: (value: number) => string
  // What the legend reports for each line: its final value, or its lowest
  legendValue: { label: string; pick: 'last' | 'min' }
}

function summarize(rows: CurveRow[], key: Series['key'], pick: 'last' | 'min'): number | null {
  const values = rows.map((r) => r[key]).filter((v): v is number => v != null)
  if (values.length === 0) return null
  return pick === 'last' ? values[values.length - 1]! : Math.min(...values)
}

export function CurveChart({ title, description, rows, series, formatValue, formatTick, legendValue }: Props) {
  const [showTable, setShowTable] = useState(false)

  return (
    <figure className="chart" aria-label={`${title} chart`}>
      <figcaption>
        <span className="chart-title">{title}</span>
        <span className="hint">{description}</span>
      </figcaption>

      <ul className="legend">
        {series.map((s) => {
          const value = summarize(rows, s.key, legendValue.pick)
          return (
            <li key={s.key}>
              <LineKey series={s.key} />
              <span>{s.label}</span>
              {value != null && (
                <span className="muted">
                  {legendValue.label} <strong>{formatValue(value)}</strong>
                </span>
              )}
            </li>
          )
        })}
      </ul>

      <LineChart
        responsive
        style={{ width: '100%', height: 280 }}
        data={rows}
        margin={{ top: 8, right: 8, bottom: 0, left: 8 }}
        accessibilityLayer
      >
        <CartesianGrid vertical={false} stroke="#EDEDED" />
        <XAxis
          dataKey="date"
          tickFormatter={formatMonth}
          minTickGap={48}
          tick={{ fill: 'rgba(17,17,17,0.6)', fontSize: 12 }}
          tickLine={false}
          axisLine={{ stroke: '#D9D9D9' }}
        />
        <YAxis
          tickFormatter={formatTick}
          width={64}
          tick={{ fill: 'rgba(17,17,17,0.6)', fontSize: 12 }}
          tickLine={false}
          axisLine={false}
          domain={['auto', 'auto']}
        />
        <Tooltip
          cursor={{ stroke: '#111111', strokeWidth: 1 }}
          content={(props: TooltipContentProps) => <ChartTooltip {...props} series={series} formatValue={formatValue} />}
        />
        {[...series].reverse().map((s) => (
          <Line
            key={s.key}
            dataKey={s.key}
            name={s.label}
            stroke={STYLE[s.key].stroke}
            strokeDasharray={STYLE[s.key].dash}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, strokeWidth: 2, stroke: '#FFFFFF' }}
            isAnimationActive={false}
            connectNulls
          />
        ))}
      </LineChart>

      <button type="button" className="text-button" aria-expanded={showTable} onClick={() => setShowTable(!showTable)}>
        {showTable ? 'Hide' : 'Show'} data table
      </button>
      {showTable && (
        <div className="table-wrap scroll">
          <table>
            <caption className="sr-only">{title}</caption>
            <thead>
              <tr>
                <th scope="col">Date</th>
                {series.map((s) => (
                  <th key={s.key} scope="col" className="num">
                    {s.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.date}>
                  <td>{row.date}</td>
                  {series.map((s) => (
                    <td key={s.key} className="num">
                      {row[s.key] == null ? '–' : formatValue(row[s.key] as number)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </figure>
  )
}

function LineKey({ series }: { series: Series['key'] }) {
  return (
    <svg className="line-key" width="20" height="8" aria-hidden="true">
      <line x1="0" y1="4" x2="20" y2="4" stroke={STYLE[series].stroke} strokeWidth="2" strokeDasharray={STYLE[series].dash} />
    </svg>
  )
}

function ChartTooltip({
  active,
  payload,
  label,
  series,
  formatValue,
}: TooltipContentProps & { series: Series[]; formatValue: (value: number) => string }) {
  if (!active || !payload?.length) return null
  const row = payload[0]?.payload as CurveRow | undefined
  return (
    <div className="tooltip">
      <div className="tooltip-date">{String(label)}</div>
      {series.map((s) =>
        row?.[s.key] == null ? null : (
          <div key={s.key} className="tooltip-row">
            <strong>{formatValue(row[s.key] as number)}</strong>
            <LineKey series={s.key} />
            <span>{s.label}</span>
          </div>
        ),
      )}
    </div>
  )
}
