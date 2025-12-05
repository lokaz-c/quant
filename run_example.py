"""
Example script demonstrating how to run backtests programmatically
"""
from backtest_engine.data_loader import DataLoader
from backtest_engine.backtester import Backtester
from backtest_engine.strategies.moving_average import MovingAverageCrossover
from backtest_engine.strategies.rsi_strategy import RSIMeanReversion
from backtest_engine.risk import RiskConfig


def run_baseline_backtest():
    """Run backtest without risk management"""
    print("\n" + "="*60)
    print("BASELINE BACKTEST (No Risk Management)")
    print("="*60)

    # Load data
    data_loader = DataLoader('data/sample_data.csv')

    # Create strategy
    strategy = MovingAverageCrossover(parameters={'fast_period': 20, 'slow_period': 50})

    # No risk management
    risk_config = RiskConfig(name='No Risk Management', enabled=False)

    # Run backtest
    backtester = Backtester(
        strategy=strategy,
        data_loader=data_loader,
        initial_capital=100000,
        risk_config=risk_config,
        start_date='2022-01-01',
        end_date='2023-12-31',
        symbols=['AAPL', 'GOOGL', 'MSFT']
    )

    results = backtester.run()
    return results


def run_risk_managed_backtest():
    """Run backtest with risk management"""
    print("\n" + "="*60)
    print("RISK-MANAGED BACKTEST (Conservative Risk)")
    print("="*60)

    # Load data
    data_loader = DataLoader('data/sample_data.csv')

    # Create strategy
    strategy = MovingAverageCrossover(parameters={'fast_period': 20, 'slow_period': 50})

    # Conservative risk management
    risk_config = RiskConfig(
        name='Conservative',
        max_position_size=0.15,
        max_portfolio_exposure=0.70,
        stop_loss_pct=0.05,
        take_profit_pct=0.15,
        max_drawdown_pct=0.15,
        enabled=True
    )

    # Run backtest
    backtester = Backtester(
        strategy=strategy,
        data_loader=data_loader,
        initial_capital=100000,
        risk_config=risk_config,
        start_date='2022-01-01',
        end_date='2023-12-31',
        symbols=['AAPL', 'GOOGL', 'MSFT']
    )

    results = backtester.run()
    return results


def compare_results(baseline, risk_managed):
    """Compare baseline vs risk-managed results"""
    print("\n" + "="*60)
    print("COMPARISON: Risk Management Impact")
    print("="*60)

    baseline_metrics = baseline['metrics']
    risk_metrics = risk_managed['metrics']

    print(f"\nTotal Return:")
    print(f"  Baseline:      {baseline_metrics['total_return']:>8.2f}%")
    print(f"  Risk-Managed:  {risk_metrics['total_return']:>8.2f}%")
    print(f"  Difference:    {risk_metrics['total_return'] - baseline_metrics['total_return']:>8.2f}%")

    print(f"\nMax Drawdown:")
    print(f"  Baseline:      {baseline_metrics['max_drawdown']:>8.2f}%")
    print(f"  Risk-Managed:  {risk_metrics['max_drawdown']:>8.2f}%")
    improvement = baseline_metrics['max_drawdown'] - risk_metrics['max_drawdown']
    improvement_pct = (improvement / baseline_metrics['max_drawdown'] * 100) if baseline_metrics['max_drawdown'] > 0 else 0
    print(f"  Improvement:   {improvement:>8.2f}% ({improvement_pct:.1f}% reduction)")

    print(f"\nSharpe Ratio:")
    print(f"  Baseline:      {baseline_metrics['sharpe_ratio']:>8.2f}")
    print(f"  Risk-Managed:  {risk_metrics['sharpe_ratio']:>8.2f}")
    print(f"  Difference:    {risk_metrics['sharpe_ratio'] - baseline_metrics['sharpe_ratio']:>8.2f}")

    print(f"\nNumber of Trades:")
    print(f"  Baseline:      {baseline_metrics['num_trades']:>8}")
    print(f"  Risk-Managed:  {risk_metrics['num_trades']:>8}")

    print("\n" + "="*60)


if __name__ == '__main__':
    print("\nQuant Portfolio Simulator - Example Backtest")
    print("=" * 60)

    # Run baseline
    baseline_results = run_baseline_backtest()

    # Run with risk management
    risk_managed_results = run_risk_managed_backtest()

    # Compare
    compare_results(baseline_results, risk_managed_results)

    print("\nBacktests completed successfully!")
    print("\nTo run this example:")
    print("  python run_example.py")
