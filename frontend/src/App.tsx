import { useCallback, useEffect, useState } from 'react'
import { api, type DataInfo, type RiskProfile, type Run, type RunRequest, type RunSummary, type Strategy } from './api'
import { CurveChart, type Series } from './components/CurveChart'
import { MetricsComparison } from './components/MetricsComparison'
import { RunForm } from './components/RunForm'
import { RunHistory } from './components/RunHistory'
import { TradesTable } from './components/TradesTable'
import { mergeCurves } from './curves'
import { formatMoney, formatPct } from './format'

const REPO = 'https://github.com/lokaz-c/quant'

interface Selection {
  runId: number
  baselineId: number | null
}

interface Loaded {
  run: Run
  baseline: Run | null
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

export default function App() {
  const [data, setData] = useState<DataInfo | null>(null)
  const [strategies, setStrategies] = useState<Strategy[]>([])
  const [riskProfiles, setRiskProfiles] = useState<RiskProfile[]>([])
  const [history, setHistory] = useState<RunSummary[]>([])
  const [selection, setSelection] = useState<Selection | null>(null)
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [runError, setRunError] = useState<string | null>(null)
  const [running, setRunning] = useState(false)

  useEffect(() => {
    Promise.all([api.dataInfo(), api.strategies(), api.riskProfiles(), api.runs()])
      .then(([info, strategyList, profiles, runs]) => {
        setData(info)
        setStrategies(strategyList)
        setRiskProfiles(profiles)
        setHistory(runs)
        // Open the newest run that has a baseline, so there is something to look at
        const first = runs.find((r) => r.baseline_run_id) ?? runs[0]
        if (first) setSelection({ runId: first.id, baselineId: first.baseline_run_id })
      })
      .catch((e: unknown) => setLoadError(message(e)))
  }, [])

  useEffect(() => {
    if (!selection) return
    let cancelled = false
    Promise.all([
      api.run(selection.runId),
      selection.baselineId ? api.run(selection.baselineId) : Promise.resolve(null),
    ])
      .then(([run, baseline]) => {
        if (!cancelled) setLoaded({ run, baseline })
      })
      .catch((e: unknown) => {
        if (!cancelled) setRunError(message(e))
      })
    return () => {
      cancelled = true
    }
  }, [selection])

  const submit = useCallback(async (request: RunRequest) => {
    setRunning(true)
    setRunError(null)
    try {
      const result = await api.startRun(request)
      setSelection({ runId: result.backtest_id, baselineId: result.baseline?.backtest_id ?? null })
      setHistory(await api.runs())
    } catch (e) {
      setRunError(message(e))
    } finally {
      setRunning(false)
    }
  }, [])

  return (
    <>
      <header className="topbar">
        <div className="container topbar-inner">
          <div>
            <span className="brand">Quant Portfolio Simulator</span>
            <a className="byline" href="https://lorenzokamanzi.com">
              Lorenzo Kamanzi
            </a>
          </div>
          <nav aria-label="Project links">
            <a href={`${REPO}/blob/main/docs/results.md`}>Results</a>
            <a href={`${REPO}/blob/main/docs/api.md`}>API</a>
            <a href={REPO}>GitHub</a>
          </nav>
        </div>
      </header>

      <div className="notice" role="note">
        <div className="container">
          <strong>Synthetic data.</strong>{' '}
          {data?.description ??
            'Prices come from a seeded Markov regime-switching GBM, not from any market. Ticker names are labels only.'}{' '}
          Results describe one simulated path, not real markets.
        </div>
      </div>

      <main className="container">
        <section className="intro">
          <span className="label">Backtest</span>
          <h1>Risk layer against an unmanaged baseline</h1>
          <p>
            Pick a strategy, its parameters, symbols, a period and a risk profile. The server can also run the same
            inputs with the risk layer off, store both runs and show them side by side.
          </p>
        </section>

        {loadError ? (
          <p className="error" role="alert">
            Could not reach the API: {loadError}
          </p>
        ) : !data ? (
          <p className="hint">Loading…</p>
        ) : (
          <div className="workspace">
            <aside className="panel">
              <RunForm
                data={data}
                strategies={strategies}
                riskProfiles={riskProfiles}
                running={running}
                onSubmit={submit}
              />
            </aside>
            <section className="results" aria-live="polite" aria-busy={running}>
              {runError && (
                <p className="error" role="alert">
                  {runError}
                </p>
              )}
              {loaded ? <Results loaded={loaded} /> : <EmptyState />}
            </section>
          </div>
        )}

        <section className="history-section">
          <span className="label">Run history</span>
          <RunHistory
            runs={history}
            selectedId={selection?.runId ?? null}
            onSelect={(r) => setSelection({ runId: r.id, baselineId: r.baseline_run_id })}
          />
        </section>
      </main>

      <footer className="footer">
        <div className="container">
          Synthetic prices only. Backtests fill at the signal bar's close with no costs or slippage; see the{' '}
          <a href={`${REPO}#limitations`}>limitations</a>.
        </div>
      </footer>
    </>
  )
}

function EmptyState() {
  return (
    <div className="empty">
      <p>Run a backtest to see the equity and drawdown curves, the metrics side by side and the trades.</p>
    </div>
  )
}

function Results({ loaded }: { loaded: Loaded }) {
  const { run, baseline } = loaded
  if (!run.metrics) return <p className="hint">Run #{run.id} has no metrics (status: {run.status}).</p>

  const series: Series[] = [{ key: 'run', label: run.risk_config }]
  if (baseline) series.push({ key: 'baseline', label: baseline.risk_config })
  const equity = mergeCurves(run.equity_curve, baseline?.equity_curve ?? null, 'equity')
  // Plotted below zero: a 5% drawdown is -5%
  const drawdown = mergeCurves(run.equity_curve, baseline?.equity_curve ?? null, 'drawdown').map((row) => ({
    date: row.date,
    run: row.run == null ? undefined : -row.run,
    baseline: row.baseline == null ? undefined : -row.baseline,
  }))
  const parameters = Object.entries(run.strategy_parameters ?? {})
    .map(([k, v]) => `${k.replaceAll('_', ' ')} ${v}`)
    .join(', ')

  return (
    <>
      <div className="results-head">
        <span className="label">
          Run #{run.id}
          {baseline && ` vs baseline #${baseline.id}`}
        </span>
        <h2>
          {run.strategy} · {run.risk_config}
        </h2>
        <p className="hint">
          {parameters && `${parameters} · `}
          {run.symbols ? run.symbols.join(', ') : 'all symbols'} · {run.start_date} to {run.end_date} ·{' '}
          {formatMoney(run.initial_capital)}
        </p>
      </div>

      <MetricsComparison
        run={{ label: run.risk_config, metrics: run.metrics }}
        baseline={baseline?.metrics ? { label: baseline.risk_config, metrics: baseline.metrics } : null}
      />

      <CurveChart
        title="Equity"
        description="Portfolio value at each close."
        rows={equity}
        series={series}
        formatValue={(v) => formatMoney(v)}
        formatTick={(v) => `$${Math.round(v / 1000)}k`}
        legendValue={{ label: 'final', pick: 'last' }}
      />
      <CurveChart
        title="Drawdown"
        description="Fall from the running peak of equity."
        rows={drawdown}
        series={series}
        formatValue={(v) => formatPct(v)}
        formatTick={(v) => `${v.toFixed(0)}%`}
        legendValue={{ label: 'worst', pick: 'min' }}
      />

      <div className="trades-section">
        <span className="label">Closed trades</span>
        <TradesTable
          key={`${run.id}-${baseline?.id ?? ''}`}
          tables={[
            { label: run.risk_config, trades: run.trades },
            ...(baseline ? [{ label: baseline.risk_config, trades: baseline.trades }] : []),
          ]}
        />
      </div>
    </>
  )
}
