import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { RunSummary } from '../api'
import { history } from '../test/fixtures'
import { RunHistory } from './RunHistory'

describe('RunHistory', () => {
  it('shows n/a with the reason for an undefined metric, and a dash for a run with no metrics', () => {
    const flat: RunSummary = {
      ...history[0]!,
      id: 30,
      sharpe_ratio: null,
      undefined_metrics: { sharpe_ratio: 'zero volatility' },
    }
    const failed: RunSummary = {
      ...history[0]!,
      id: 31,
      status: 'failed',
      total_return: null,
      max_drawdown: null,
      sharpe_ratio: null,
      undefined_metrics: null,
    }
    render(<RunHistory runs={[flat, failed]} selectedId={null} onSelect={() => {}} />)

    const flatCells = within(screen.getByRole('row', { name: /#30/ })).getAllByRole('cell')
    const sharpe = flatCells.at(-1)!
    expect(sharpe).toHaveTextContent('n/a')
    expect(within(sharpe).getByTitle('Not available: zero volatility')).toBeInTheDocument()
    expect(flatCells.at(-3)).toHaveTextContent('4.50%')

    const failedCells = within(screen.getByRole('row', { name: /#31/ })).getAllByRole('cell')
    expect(failedCells.slice(-3).map((c) => c.textContent)).toEqual(['–', '–', '–'])
  })
})
