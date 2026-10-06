import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { dataInfo, riskProfiles, strategies } from '../test/fixtures'
import { RunForm } from './RunForm'

function renderForm() {
  const onSubmit = vi.fn()
  render(<RunForm data={dataInfo} strategies={strategies} riskProfiles={riskProfiles} running={false} onSubmit={onSubmit} />)
  return { onSubmit, user: userEvent.setup() }
}

describe('RunForm', () => {
  it('submits the defaults: the results setup over 2023, Conservative, with the baseline', async () => {
    const { onSubmit, user } = renderForm()
    await user.click(screen.getByRole('button', { name: 'Run backtest' }))
    expect(onSubmit).toHaveBeenCalledWith({
      strategy_name: 'Moving Average Crossover',
      risk_config_name: 'Conservative',
      start_date: '2023-01-01',
      end_date: '2023-12-31',
      initial_capital: 100000,
      symbols: ['AAPL', 'AMZN', 'GOOGL', 'JPM', 'MSFT'],
      parameters: { fast_period: 20, slow_period: 50 },
      compare_to_baseline: true,
      data_source: 'synthetic',
    })
  })

  it('only offers strategies that can run, and swaps in their parameters', async () => {
    const { onSubmit, user } = renderForm()
    const strategy = screen.getByRole('combobox', { name: 'Strategy' })
    expect(within(strategy).queryByText('Stored only')).toBeNull()

    await user.selectOptions(strategy, 'Trend Following')
    const multiplier = screen.getByRole('spinbutton', { name: /atr multiplier/i })
    await user.clear(multiplier)
    await user.type(multiplier, '2.5')
    await user.click(screen.getByRole('button', { name: 'TSLA' }))
    await user.click(screen.getByRole('button', { name: 'AAPL' }))
    await user.click(screen.getByRole('button', { name: 'Run backtest' }))

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        strategy_name: 'Trend Following',
        parameters: { lookback_period: 20, atr_period: 14, atr_multiplier: 2.5 },
        // data file order, not click order
        symbols: ['AMZN', 'GOOGL', 'JPM', 'MSFT', 'TSLA'],
      }),
    )
  })

  it('blocks out-of-range parameters and an empty symbol list, and says why', async () => {
    const { onSubmit, user } = renderForm()
    const fast = screen.getByRole('spinbutton', { name: /fast period/i })
    await user.clear(fast)
    await user.type(fast, '1.5')
    await user.click(screen.getByRole('button', { name: 'None' }))
    await user.click(screen.getByRole('button', { name: 'Run backtest' }))

    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent('fast_period must be a whole number')
    expect(alert).toHaveTextContent('Pick at least one symbol')
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('turns the baseline off when the profile already has no risk layer', async () => {
    const { onSubmit, user } = renderForm()
    await user.selectOptions(screen.getByRole('combobox', { name: 'Risk profile' }), 'No Risk Management')
    expect(screen.getByRole('checkbox')).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Run backtest' }))
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ compare_to_baseline: false }))
  })
})
