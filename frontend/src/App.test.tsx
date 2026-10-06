import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import type { Run } from './api'
import {
  alpaca,
  baselineRun,
  dataInfo,
  history,
  managedRun,
  marketDataInfo,
  mixed,
  riskProfiles,
  strategies,
} from './test/fixtures'

type Handler = (init?: RequestInit) => [number, unknown]

function serve(routes: Record<string, Handler>) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? 'GET'} ${url}`
    const handler = routes[key]
    if (!handler) return new Response(JSON.stringify({ error: `no route for ${key}` }), { status: 404 })
    const [status, body] = handler(init)
    return new Response(JSON.stringify(body), { status })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const READ_ROUTES: Record<string, Handler> = {
  'GET /api/data': () => [200, dataInfo],
  'GET /api/strategies/': () => [200, strategies],
  'GET /api/risk-configs/': () => [200, riskProfiles],
  'GET /api/backtest/list?limit=50': () => [200, history],
  'GET /api/backtest/12': () => [200, managedRun],
  'GET /api/backtest/11': () => [200, baselineRun],
}

afterEach(() => vi.unstubAllGlobals())

describe('App', () => {
  it('labels the data as synthetic and opens the newest run with its baseline', async () => {
    serve(READ_ROUTES)
    render(<App />)

    expect(screen.getByRole('note')).toHaveTextContent('Checking the data source')
    expect(await screen.findByText('Run #12 vs baseline #11')).toBeInTheDocument()
    expect(screen.getByRole('note')).toHaveTextContent('Synthetic data.')
    expect(screen.getByRole('note')).toHaveTextContent('seeded Markov regime-switching GBM')

    const metrics = screen.getByRole('table', { name: 'Conservative compared with No Risk Management' })
    expect(within(metrics).getByRole('row', { name: /Total return/ })).toHaveTextContent('1.50%4.50%+3.00')
    expect(screen.getByRole('figure', { name: /Equity/ })).toBeInTheDocument()
    expect(screen.getByRole('figure', { name: /Drawdown/ })).toBeInTheDocument()
    // the trades table has one tab per run
    expect(screen.getByRole('tab', { name: /Conservative/ })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('table', { name: 'Closed trades, Conservative' })).toHaveTextContent('AAPL')

    const runs = screen.getByRole('table', { name: 'Stored runs, newest first' })
    expect(within(runs).getByText('vs baseline #11')).toBeInTheDocument()
    expect(within(runs).getByText('baseline for #12')).toBeInTheDocument()
  })

  it('runs a backtest with its baseline and shows the new pair', async () => {
    const fetchMock = serve({
      ...READ_ROUTES,
      'GET /api/backtest/list?limit=50': () => [200, []],
      'POST /api/backtest/': () => [200, { backtest_id: 12, status: 'completed', metrics: managedRun.metrics, undefined_metrics: {}, baseline: { backtest_id: 11, risk_config: 'No Risk Management', metrics: baselineRun.metrics, undefined_metrics: {} } }],
    })
    const user = userEvent.setup()
    render(<App />)

    expect(await screen.findByText(/Run a backtest to see/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Run backtest' }))

    expect(await screen.findByText('Run #12 vs baseline #11')).toBeInTheDocument()
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST')!
    expect(JSON.parse(post[1]!.body as string)).toMatchObject({ compare_to_baseline: true, risk_config_name: 'Conservative' })
  })

  it("shows the API's reason when a run is rejected", async () => {
    serve({
      ...READ_ROUTES,
      'GET /api/backtest/list?limit=50': () => [200, []],
      'POST /api/backtest/': () => [400, { error: 'No bars between 2023-01-07 and 2023-01-08' }],
    })
    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByRole('button', { name: 'Run backtest' }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('No bars between'))
  })

  it('says so when the API is unreachable', async () => {
    serve({})
    render(<App />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not reach the API')
  })
})

describe('data source banner', () => {
  const withData = (run: Run, data: Run['data']): Run => ({ ...run, data })
  const routesFor = (run: Run, baseline: Run) => ({
    ...READ_ROUTES,
    'GET /api/backtest/list?limit=50': (): [number, unknown] => [
      200,
      history.map((h) => ({ ...h, data_source: run.data.source, reported_source: run.data.reported_source, synthetic: run.data.synthetic })),
    ],
    'GET /api/backtest/12': (): [number, unknown] => [200, run],
    'GET /api/backtest/11': (): [number, unknown] => [200, baseline],
  })

  it('says market data only for a run the service labelled alpaca', async () => {
    serve(routesFor(withData(managedRun, alpaca), withData(baselineRun, alpaca)))
    render(<App />)
    await screen.findByText('Run #12 vs baseline #11')
    const note = screen.getByRole('note')
    expect(note).toHaveTextContent('Market data.')
    expect(note).toHaveTextContent("Alpaca's IEX feed")
    expect(note).not.toHaveTextContent('Synthetic')
    expect(note).toHaveClass('notice-real')
    expect(screen.getByRole('contentinfo')).toHaveTextContent('Daily bars from Alpaca via the market-data service.')
    const runs = screen.getByRole('table', { name: 'Stored runs, newest first' })
    expect(within(runs).getAllByText('Alpaca')).toHaveLength(2)
  })

  it('labels a run with any synthetic symbol as partly synthetic', async () => {
    serve(routesFor(withData(managedRun, mixed), withData(baselineRun, mixed)))
    render(<App />)
    await screen.findByText('Run #12 vs baseline #11')
    expect(screen.getByRole('note')).toHaveTextContent('Partly synthetic data.')
    expect(screen.getByRole('note')).not.toHaveTextContent('Market data')
  })

  it('does not trust a synthetic=false flag that contradicts the reported source', async () => {
    const contradictory = { ...alpaca, reported_source: 'synthetic' as const }
    serve(routesFor(withData(managedRun, contradictory), withData(baselineRun, contradictory)))
    render(<App />)
    await screen.findByText('Run #12 vs baseline #11')
    expect(screen.getByRole('note')).toHaveTextContent('Synthetic data.')
  })

  it('before any run, describes the source a new run would use and sends it', async () => {
    const fetchMock = serve({
      ...READ_ROUTES,
      'GET /api/data': () => [200, marketDataInfo],
      'GET /api/backtest/list?limit=50': () => [200, []],
      'POST /api/backtest/': () => [400, { error: 'stop here' }],
    })
    const user = userEvent.setup()
    render(<App />)
    expect(await screen.findByText(/Run a backtest to see/)).toBeInTheDocument()
    expect(screen.getByRole('note')).toHaveTextContent('Synthetic data.')
    expect(screen.getByRole('note')).toHaveTextContent('generated by the market-data service')
    expect(screen.getByText('market-data has these symbols from 2020-10-05 to 2026-10-02.')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Run backtest' }))
    await screen.findByText('stop here')
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST')!
    expect(JSON.parse(post[1]!.body as string)).toMatchObject({ data_source: 'market-data', symbols: ['S001', 'S002'] })
  })
})

describe('charts', () => {
  it('report the final equity and the worst drawdown of each run in the legend', async () => {
    serve(READ_ROUTES)
    render(<App />)
    const equity = await screen.findByRole('figure', { name: 'Equity chart' })
    // fixtures: run ends at 104,500 and baseline at 101,500
    expect(within(equity).getByRole('list')).toHaveTextContent('Conservativefinal $104,500No Risk Managementfinal $101,500')
    const drawdown = screen.getByRole('figure', { name: 'Drawdown chart' })
    // run: 101,000 -> 99,000 is 1.98%; baseline: 102,000 -> 93,000 is 8.82%
    expect(within(drawdown).getByRole('list')).toHaveTextContent('Conservativeworst -1.98%No Risk Managementworst -8.82%')
  })
})
