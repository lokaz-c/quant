import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { baselineRun, managedRun } from '../test/fixtures'
import { MetricsComparison } from './MetricsComparison'

describe('MetricsComparison', () => {
  it('shows the baseline, the risk profile and the change side by side', () => {
    render(
      <MetricsComparison
        run={{ label: 'Conservative', metrics: managedRun.metrics!, undefinedMetrics: {} }}
        baseline={{ label: 'No Risk Management', metrics: baselineRun.metrics!, undefinedMetrics: {} }}
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
    render(
      <MetricsComparison run={{ label: 'Conservative', metrics: managedRun.metrics!, undefinedMetrics: {} }} baseline={null} />,
    )
    expect(screen.getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['Metric', 'Conservative'])
    expect(screen.queryByText(/the metric is undefined/)).not.toBeInTheDocument()
  })

  it('shows an undefined metric as n/a with the reason, and no change against it', () => {
    render(
      <MetricsComparison
        run={{
          label: 'Conservative',
          metrics: { ...managedRun.metrics!, sharpe_ratio: null, volatility: null },
          undefinedMetrics: { sharpe_ratio: 'zero volatility', volatility: 'fewer than two daily returns' },
        }}
        baseline={{ label: 'No Risk Management', metrics: baselineRun.metrics!, undefinedMetrics: {} }}
      />,
    )
    const sharpe = screen.getByRole('row', { name: /Sharpe ratio/ })
    const cells = within(sharpe).getAllByRole('cell')
    expect(cells.map((c) => c.textContent)).toEqual(['-0.20', 'n/a', 'n/a'])
    expect(within(cells[1]!).getByTitle('Not available: zero volatility')).toBeInTheDocument()

    const notes = screen.getAllByRole('listitem').map((li) => li.textContent)
    expect(notes).toEqual([
      'Volatility (annualised), Conservative: fewer than two daily returns',
      'Sharpe ratio, Conservative: zero volatility',
    ])
  })
})
