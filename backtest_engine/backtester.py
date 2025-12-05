"""
Main backtesting engine
Orchestrates the entire backtesting process
"""
import pandas as pd
from datetime import datetime
from typing import Dict, List, Optional
from .data_loader import DataLoader
from .portfolio import Portfolio
from .strategy_base import StrategyBase
from .risk import RiskManager, RiskConfig
from .metrics import PerformanceMetrics


class Backtester:
    """Main backtesting engine"""

    def __init__(
        self,
        strategy: StrategyBase,
        data_loader: DataLoader,
        initial_capital: float,
        risk_config: Optional[RiskConfig] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        symbols: Optional[List[str]] = None
    ):
        self.strategy = strategy
        self.data_loader = data_loader
        self.initial_capital = initial_capital
        self.risk_config = risk_config or RiskConfig(name='No Risk Management', enabled=False)
        self.start_date = start_date
        self.end_date = end_date
        self.symbols = symbols

        self.portfolio = None
        self.risk_manager = None
        self.data = None
        self.results = None

    def run(self) -> Dict:
        """
        Run the backtest

        Returns dictionary with results
        """
        # Initialize portfolio and risk manager
        self.portfolio = Portfolio(self.initial_capital)
        self.risk_manager = RiskManager(self.risk_config)

        # Load and filter data
        self.data = self.data_loader.load_csv(self.symbols)

        if self.start_date and self.end_date:
            self.data = self.data_loader.filter_by_date(self.start_date, self.end_date)

        if len(self.data) == 0:
            raise ValueError("No data available for backtesting")

        print(f"Running backtest on {len(self.data)} data points")
        print(f"Strategy: {self.strategy.name}")
        print(f"Risk Config: {self.risk_config.name}")
        print(f"Date Range: {self.data['timestamp'].min()} to {self.data['timestamp'].max()}")

        # Group data by timestamp for bar-by-bar processing
        grouped = self.data.groupby('timestamp')

        bar_count = 0
        for timestamp, bar_data in grouped:
            bar_count += 1

            # Update current prices
            current_prices = dict(zip(bar_data['symbol'], bar_data['close']))
            self.portfolio.update_prices(current_prices)

            # Check risk conditions (stop loss, take profit, drawdown)
            if self.risk_manager.config.enabled:
                # Check for stop loss / take profit triggers
                risk_orders = self.risk_manager.check_stop_loss_take_profit(
                    self.portfolio,
                    current_prices
                )

                # Execute risk orders first
                for order in risk_orders:
                    price = current_prices.get(order.symbol)
                    if price:
                        self.portfolio.execute_order(order, price, timestamp)

                # Check drawdown
                self.risk_manager.check_drawdown(self.portfolio)

            # Generate strategy signals
            # Get historical data up to current point
            historical_data = self.data[self.data['timestamp'] <= timestamp]
            strategy_orders = self.strategy.generate_signals(historical_data, self.portfolio)

            # Apply risk management to strategy orders
            if self.risk_manager.config.enabled:
                strategy_orders = self.risk_manager.apply_risk_adjustments(
                    strategy_orders,
                    self.portfolio,
                    current_prices
                )

            # Execute strategy orders
            for order in strategy_orders:
                price = current_prices.get(order.symbol)
                if price:
                    self.portfolio.execute_order(order, price, timestamp)

            # Record equity snapshot
            self.portfolio.record_equity(timestamp)

            # Progress indicator
            if bar_count % 100 == 0:
                print(f"Processed {bar_count} bars, Current equity: ${self.portfolio.equity:,.2f}")

        # Close all positions at end
        final_bar = self.data[self.data['timestamp'] == self.data['timestamp'].max()]
        final_prices = dict(zip(final_bar['symbol'], final_bar['close']))
        self.portfolio.close_all_positions(final_prices, self.data['timestamp'].max())

        # Calculate metrics
        metrics = self._calculate_metrics()

        # Compile results
        self.results = {
            'metrics': metrics,
            'equity_curve': self.portfolio.equity_history,
            'trades': self._format_trades(),
            'final_portfolio': {
                'equity': self.portfolio.equity,
                'cash': self.portfolio.cash,
                'positions': len(self.portfolio.positions),
                'total_return': self.portfolio.total_return
            },
            'risk_stats': self.risk_manager.get_stats() if self.risk_manager else {}
        }

        self._print_summary()

        return self.results

    def _calculate_metrics(self) -> Dict:
        """Calculate performance metrics"""
        trades_data = [
            {
                'symbol': t.symbol,
                'entry_date': t.entry_date,
                'exit_date': t.exit_date,
                'entry_price': t.entry_price,
                'exit_price': t.exit_price,
                'quantity': t.quantity,
                'side': t.side,
                'pnl': t.pnl,
                'pnl_pct': t.pnl_pct,
                'status': t.status
            }
            for t in self.portfolio.trades
        ]

        calculator = PerformanceMetrics(
            equity_curve=self.portfolio.equity_history,
            trades=trades_data,
            initial_capital=self.initial_capital
        )

        return calculator.calculate_all()

    def _format_trades(self) -> List[Dict]:
        """Format trades for output"""
        return [
            {
                'symbol': t.symbol,
                'entry_date': t.entry_date.isoformat() if t.entry_date else None,
                'exit_date': t.exit_date.isoformat() if t.exit_date else None,
                'entry_price': t.entry_price,
                'exit_price': t.exit_price,
                'quantity': t.quantity,
                'side': t.side,
                'pnl': t.pnl,
                'pnl_pct': t.pnl_pct,
                'status': t.status
            }
            for t in self.portfolio.trades
        ]

    def _print_summary(self):
        """Print backtest summary"""
        print("\n" + "=" * 60)
        print("BACKTEST RESULTS")
        print("=" * 60)

        metrics = self.results['metrics']
        print(f"\nInitial Capital: ${self.initial_capital:,.2f}")
        print(f"Final Equity: ${metrics['final_equity']:,.2f}")
        print(f"Total Return: {metrics['total_return']:.2f}%")
        print(f"CAGR: {metrics['cagr']:.2f}%")
        print(f"Max Drawdown: {metrics['max_drawdown']:.2f}%")
        print(f"Volatility: {metrics['volatility']:.2f}%")
        print(f"Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
        print(f"\nNumber of Trades: {metrics['num_trades']}")
        print(f"Win Rate: {metrics['win_rate']:.2f}%")
        print(f"Average Win: ${metrics['avg_win']:.2f}")
        print(f"Average Loss: ${metrics['avg_loss']:.2f}")
        print(f"Profit Factor: {metrics['profit_factor']:.2f}")

        print("\n" + "=" * 60)

    def get_results(self) -> Dict:
        """Get backtest results"""
        return self.results

    def compare_with_baseline(self, baseline_results: Dict) -> Dict:
        """
        Compare results with a baseline run

        Returns comparison metrics
        """
        if not self.results or not baseline_results:
            raise ValueError("Both current and baseline results must be available")

        current = self.results['metrics']
        baseline = baseline_results['metrics']

        comparison = {
            'total_return_diff': current['total_return'] - baseline['total_return'],
            'max_drawdown_diff': current['max_drawdown'] - baseline['max_drawdown'],
            'sharpe_ratio_diff': current['sharpe_ratio'] - baseline['sharpe_ratio'],
            'win_rate_diff': current['win_rate'] - baseline['win_rate'],
            'num_trades_diff': current['num_trades'] - baseline['num_trades'],
            'drawdown_improvement_pct': ((baseline['max_drawdown'] - current['max_drawdown']) /
                                         baseline['max_drawdown'] * 100) if baseline['max_drawdown'] > 0 else 0
        }

        return comparison
