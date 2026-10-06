import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from './api'

afterEach(() => vi.unstubAllGlobals())

describe('api', () => {
  it('posts a run as JSON', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ backtest_id: 7 }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    const body = {
      strategy_name: 'Trend Following',
      risk_config_name: 'Conservative',
      start_date: '2023-01-01',
      end_date: '2023-12-31',
      initial_capital: 100000,
      symbols: ['AAPL'],
      parameters: { lookback_period: 20 },
      compare_to_baseline: true,
    }
    await expect(api.startRun(body)).resolves.toEqual({ backtest_id: 7 })
    const [url, init] = fetchMock.mock.calls[0]!
    expect(url).toBe('/api/backtest/')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual(body)
  })

  it("raises the server's error message for a 400", async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: 'Unknown symbol(s): NOPE' }), { status: 400 })),
    )
    const error = await api.run(1).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 400, message: 'Unknown symbol(s): NOPE' })
  })

  it('falls back to the status line when the body is not JSON', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('gateway timeout', { status: 504, statusText: 'Gateway Timeout' })),
    )
    await expect(api.runs()).rejects.toThrow('504 Gateway Timeout')
  })
})
