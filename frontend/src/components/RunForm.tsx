import { useMemo, useState, type FormEvent } from 'react'
import type { DataInfo, Limits, RiskProfile, RunRequest, Strategy } from '../api'
import { formatFraction } from '../format'

// Same setup as `make results` (docs/results.md), over one year
const DEFAULT_SYMBOLS = ['AAPL', 'AMZN', 'GOOGL', 'JPM', 'MSFT']
const DEFAULT_START = '2023-01-01'
const DEFAULT_END = '2023-12-31'
const DEFAULT_CAPITAL = 100_000

interface Props {
  data: DataInfo
  strategies: Strategy[]
  riskProfiles: RiskProfile[]
  running: boolean
  onSubmit: (request: RunRequest) => void
}

/** Inline problems with the form, or [] if it can be submitted */
export function validate(
  request: Omit<RunRequest, 'parameters'>,
  parameters: Record<string, string>,
  strategy: Strategy | undefined,
  limits?: Limits,
): string[] {
  const problems: string[] = []
  for (const [name, limit] of Object.entries(strategy?.parameter_limits ?? {})) {
    const raw = parameters[name]?.trim() ?? ''
    const value = Number(raw)
    if (raw === '' || !Number.isFinite(value)) problems.push(`${name} must be a number`)
    else if (limit.type === 'int' && !Number.isInteger(value)) problems.push(`${name} must be a whole number`)
    else if (value < limit.min || value > limit.max) problems.push(`${name} must be between ${limit.min} and ${limit.max}`)
  }
  if (request.symbols.length === 0) problems.push('Pick at least one symbol')
  else if (limits && request.symbols.length > limits.max_symbols)
    problems.push(`Pick at most ${limits.max_symbols} symbols (this server's limit per run)`)
  if (!request.start_date || !request.end_date) problems.push('Pick a start and an end date')
  else if (request.start_date > request.end_date) problems.push('The start date is after the end date')
  else if (limits && periodDays(request.start_date, request.end_date) > limits.max_range_days)
    problems.push(
      `The period is ${periodDays(request.start_date, request.end_date).toLocaleString('en-US')} days; ` +
        `this server allows at most ${limits.max_range_days.toLocaleString('en-US')} per run`,
    )
  if (!(request.initial_capital > 0)) problems.push('Initial capital must be above 0')
  return problems
}

export function RunForm({ data, strategies, riskProfiles, running, onSubmit }: Props) {
  const runnable = strategies.filter((s) => s.parameter_limits)
  const [strategyName, setStrategyName] = useState(runnable[0]?.name ?? '')
  const strategy = runnable.find((s) => s.name === strategyName)
  const [parameters, setParameters] = useState<Record<string, string>>(() => asStrings(runnable[0]?.parameters))
  const [symbols, setSymbols] = useState<string[]>(() => {
    const defaults = DEFAULT_SYMBOLS.filter((s) => data.symbols.includes(s))
    return defaults.length ? defaults : data.symbols.slice(0, 5)
  })
  const [startDate, setStartDate] = useState(clampDate(DEFAULT_START, data))
  const [endDate, setEndDate] = useState(clampDate(DEFAULT_END, data))
  const [capital, setCapital] = useState(String(DEFAULT_CAPITAL))
  const managed = riskProfiles.filter((p) => p.enabled)
  const [riskName, setRiskName] = useState(
    managed.find((p) => p.name === 'Conservative')?.name ?? riskProfiles[0]?.name ?? '',
  )
  const risk = riskProfiles.find((p) => p.name === riskName)
  const [compare, setCompare] = useState(true)
  const [problems, setProblems] = useState<string[]>([])

  const selected = useMemo(() => new Set(symbols), [symbols])

  function chooseStrategy(name: string) {
    setStrategyName(name)
    setParameters(asStrings(runnable.find((s) => s.name === name)?.parameters))
    setProblems([])
  }

  function toggleSymbol(symbol: string) {
    setSymbols((current) =>
      current.includes(symbol)
        ? current.filter((s) => s !== symbol)
        : data.symbols.filter((s) => s === symbol || current.includes(s)),
    )
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    const request = {
      strategy_name: strategyName,
      risk_config_name: riskName,
      start_date: startDate,
      end_date: endDate,
      initial_capital: Number(capital),
      symbols,
      compare_to_baseline: compare && Boolean(risk?.enabled),
      data_source: data.source,
    }
    const found = validate(request, parameters, strategy, data.limits)
    setProblems(found)
    if (found.length) return
    onSubmit({
      ...request,
      parameters: Object.fromEntries(Object.entries(parameters).map(([k, v]) => [k, Number(v)])),
    })
  }

  return (
    <form className="run-form" onSubmit={submit} noValidate aria-label="Backtest settings">
      <fieldset>
        <legend className="label">Strategy</legend>
        <select
          aria-label="Strategy"
          value={strategyName}
          onChange={(e) => chooseStrategy(e.target.value)}
        >
          {runnable.map((s) => (
            <option key={s.id} value={s.name}>
              {s.name}
            </option>
          ))}
        </select>
        {strategy?.description && <p className="hint">{strategy.description}</p>}
      </fieldset>

      <fieldset>
        <legend className="label">Parameters</legend>
        <div className="field-grid">
          {Object.entries(strategy?.parameter_limits ?? {}).map(([name, limit]) => (
            <label key={name} className="field">
              <span>{sentenceCase(name)}</span>
              <input
                type="number"
                inputMode="decimal"
                min={limit.min}
                max={limit.max}
                step={limit.type === 'int' ? 1 : 'any'}
                value={parameters[name] ?? ''}
                onChange={(e) => setParameters({ ...parameters, [name]: e.target.value })}
              />
              <small>
                {limit.min} to {limit.max}
              </small>
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset>
        <legend className="label">
          Symbols{' '}
          <span className="count">
            {symbols.length} of {data.symbols.length}, at most {data.limits.max_symbols}
          </span>
        </legend>
        <div className="chips" role="group" aria-label="Symbols">
          {data.symbols.map((symbol) => (
            <button
              key={symbol}
              type="button"
              className="chip"
              aria-pressed={selected.has(symbol)}
              onClick={() => toggleSymbol(symbol)}
            >
              {symbol}
            </button>
          ))}
        </div>
        <div className="chip-actions">
          {data.symbols.length <= data.limits.max_symbols && (
            <button type="button" className="text-button" onClick={() => setSymbols(data.symbols)}>
              All
            </button>
          )}
          <button type="button" className="text-button" onClick={() => setSymbols([])}>
            None
          </button>
        </div>
      </fieldset>

      <fieldset>
        <legend className="label">Period and capital</legend>
        <div className="field-grid">
          <label className="field">
            <span>Start</span>
            <input
              type="date"
              min={data.start_date}
              max={data.end_date}
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
            />
          </label>
          <label className="field">
            <span>End</span>
            <input
              type="date"
              min={data.start_date}
              max={data.end_date}
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
            />
          </label>
          <label className="field field-wide">
            <span>Initial capital ($)</span>
            <input
              type="number"
              min={1}
              step="any"
              inputMode="decimal"
              value={capital}
              onChange={(e) => setCapital(e.target.value)}
            />
          </label>
        </div>
        <p className="hint">
          {data.bars != null
            ? `Data covers ${data.start_date} to ${data.end_date} (${data.bars.toLocaleString('en-US')} business days).`
            : `market-data has these symbols from ${data.start_date} to ${data.end_date}.`}{' '}
          At most {data.limits.max_range_days.toLocaleString('en-US')} days per run; the server stops a run after{' '}
          {data.limits.timeout_seconds} s.
        </p>
      </fieldset>

      <fieldset>
        <legend className="label">Risk profile</legend>
        <select aria-label="Risk profile" value={riskName} onChange={(e) => setRiskName(e.target.value)}>
          {riskProfiles.map((p) => (
            <option key={p.id} value={p.name}>
              {p.name}
            </option>
          ))}
        </select>
        {risk && <RiskLimits profile={risk} />}
        <label className="check">
          <input
            type="checkbox"
            checked={compare && Boolean(risk?.enabled)}
            disabled={!risk?.enabled}
            onChange={(e) => setCompare(e.target.checked)}
          />
          <span>Also run the unmanaged baseline (risk layer off) on the same inputs</span>
        </label>
      </fieldset>

      {problems.length > 0 && (
        <ul className="problems" role="alert">
          {problems.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      )}

      <button type="submit" className="button" disabled={running || !strategy}>
        {running ? 'Running…' : 'Run backtest'}
      </button>
    </form>
  )
}

function RiskLimits({ profile }: { profile: RiskProfile }) {
  if (!profile.enabled) return <p className="hint">Risk layer off: no caps, stops or drawdown halt.</p>
  const rows: [string, number | null][] = [
    ['Max position', profile.max_position_size],
    ['Max exposure', profile.max_portfolio_exposure],
    ['Stop-loss', profile.stop_loss_pct],
    ['Take-profit', profile.take_profit_pct],
    ['Halt at drawdown', profile.max_drawdown_pct],
  ]
  return (
    <dl className="limits">
      {rows.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{formatFraction(value)}</dd>
        </div>
      ))}
    </dl>
  )
}

/** fast_period -> "Fast period" */
function sentenceCase(name: string): string {
  const words = name.replaceAll('_', ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}

function asStrings(values: Record<string, number> | undefined): Record<string, string> {
  return Object.fromEntries(Object.entries(values ?? {}).map(([k, v]) => [k, String(v)]))
}

/** Calendar days from start to end, both included (as the server counts them) */
export function periodDays(start: string, end: string): number {
  return Math.round((Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / 86_400_000) + 1
}

function clampDate(value: string, data: DataInfo): string {
  if (value < data.start_date) return data.start_date
  if (value > data.end_date) return data.end_date
  return value
}
