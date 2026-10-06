import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { baselineRun, managedRun } from '../test/fixtures'
import { MetricsComparison } from './MetricsComparison'

describe('MetricsComparison', () => {
  it('shows the baseline, the risk profile and the change side by side', () => {
    render(
      <MetricsComparison
        run={{ label: 'Conservative', metrics: managedRun.metrics! }}
        baseline={{ label: 'No Risk Management', metrics: baselineRun.metrics! }}
      />,
    )
    const headers = screen.getAllByRole('columnheader').map((h) => h.textContent)
    expect(headers).toEqual(['Metric', 'No Risk Management', 'Conservative', 'Change'])

    const drawdown = screen.getByRole('row', { name: /Max drawdown/ })
    expect(within(drawdown).getAllByRole('cell').map((c) => c.textContent)).toEqual(['8.75%', '3.25%', '-5.50'])
    const trades = screen.getByRole('row', { name: /Trades/ })
    expect(within(trades).getAllByRole('cell').map((c) => c.textContent)).toEqual(['7', '9', '+2'])
    const equity = screen.getByRole('row', { name: /Final equity/ })
    expect(within(equity).getAllByRole('cell').map((c) => c.textContent)).toEqual(['$101,500', '$104,500', '+$3,000'])
  })

  it('shows one column without a baseline', () => {
    render(<MetricsComparison run={{ label: 'Conservative', metrics: managedRun.metrics! }} baseline={null} />)
    expect(screen.getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['Metric', 'Conservative'])
  })
})
