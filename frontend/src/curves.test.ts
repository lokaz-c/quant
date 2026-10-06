import { describe, expect, it } from 'vitest'
import type { EquityPoint } from './api'
import { dateOf, drawdownSeries, mergeCurves } from './curves'

const point = (date: string, equity: number): EquityPoint => ({
  timestamp: `${date}T00:00:00+00:00`,
  equity,
  cash: null,
  positions_value: null,
})

describe('drawdownSeries', () => {
  it('measures from the running peak, like the Python and SQL versions', () => {
    // peak 110 -> 88 is 20%; the later peak of 120 resets it; 114 is 5% below 120
    const result = drawdownSeries([100, 110, 88, 120, 114])
    expect(result.map((v) => Number(v.toFixed(9)))).toEqual([0, 0, 20, 0, 5])
  })

  it('is zero for a flat or rising curve', () => {
    expect(drawdownSeries([100, 100, 101, 105])).toEqual([0, 0, 0, 0])
  })
})

describe('mergeCurves', () => {
  it('lines the run and its baseline up by date', () => {
    const run = [point('2023-01-02', 100), point('2023-01-03', 90)]
    const baseline = [point('2023-01-02', 100), point('2023-01-03', 95), point('2023-01-04', 99)]
    expect(mergeCurves(run, baseline, 'equity')).toEqual([
      { date: '2023-01-02', run: 100, baseline: 100 },
      { date: '2023-01-03', run: 90, baseline: 95 },
      { date: '2023-01-04', baseline: 99 },
    ])
    expect(mergeCurves(run, null, 'drawdown').map((r) => r.run)).toEqual([0, 10])
  })

  it('takes the date from UTC timestamps', () => {
    expect(dateOf('2023-01-03T00:00:00+00:00')).toBe('2023-01-03')
  })
})
