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

  it('reads the problem detail, and says when to retry after a 429', async () => {
    const problem = { title: 'Bad Request', status: 400, detail: 'The period is 2,000 days', error: 'old field' }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(problem), { status: 400 })))
    await expect(api.runs()).rejects.toThrow('The period is 2,000 days')

    const limited = new Response(JSON.stringify({ status: 429, detail: 'Rate limit of 5 per 1 minute exceeded' }), {
      status: 429,
      headers: { 'Retry-After': '37' },
    })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(limited))
    const error = await api.startRun({} as never).catch((e: unknown) => e)
    expect(error).toMatchObject({ status: 429, message: 'Too many requests from this address. Try again in 37 s.' })
  })

  it('falls back to the status line when the body is not JSON', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('gateway timeout', { status: 504, statusText: 'Gateway Timeout' })),
    )
    await expect(api.runs()).rejects.toThrow('504 Gateway Timeout')
  })
})
