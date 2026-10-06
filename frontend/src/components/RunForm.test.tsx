import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { dataInfo, riskProfiles, strategies } from '../test/fixtures'
import { periodDays, RunForm, validate } from './RunForm'

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

  it("keeps a run within the server's caps on symbols and period", async () => {
    const onSubmit = vi.fn()
    const capped = { ...dataInfo, limits: { max_symbols: 3, max_range_days: 365, timeout_seconds: 60 } }
    render(<RunForm data={capped} strategies={strategies} riskProfiles={riskProfiles} running={false} onSubmit={onSubmit} />)
    const user = userEvent.setup()
    // more symbols than the cap: no "All" button
    expect(screen.queryByRole('button', { name: 'All' })).toBeNull()
    expect(screen.getByText(/5 of 6, at most 3/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Run backtest' }))
    expect(screen.getByRole('alert')).toHaveTextContent("Pick at most 3 symbols (this server's limit per run)")
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('counts the period in calendar days, both ends included', () => {
    expect(periodDays('2023-01-01', '2023-12-31')).toBe(365)
    expect(periodDays('2020-01-01', '2024-12-31')).toBe(1827)
    expect(periodDays('2023-03-11', '2023-03-13')).toBe(3)
    const request = {
      strategy_name: 'x', risk_config_name: 'y', start_date: '2020-01-01', end_date: '2024-12-31',
      initial_capital: 1, symbols: ['AAPL'], compare_to_baseline: false,
    }
    const limits = { max_symbols: 10, max_range_days: 1826, timeout_seconds: 60 }
    expect(validate(request, {}, undefined, limits)).toEqual([
      'The period is 1,827 days; this server allows at most 1,826 per run',
    ])
    expect(validate(request, {}, undefined, { ...limits, max_range_days: 1827 })).toEqual([])
  })

  it('turns the baseline off when the profile already has no risk layer', async () => {
    const { onSubmit, user } = renderForm()
    await user.selectOptions(screen.getByRole('combobox', { name: 'Risk profile' }), 'No Risk Management')
    expect(screen.getByRole('checkbox')).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Run backtest' }))
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ compare_to_baseline: false }))
  })
})
