"""
Backtest service layer
Handles business logic for running and managing backtests
"""
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import List, Optional, Dict, Tuple, Union
from app.models.database import (
    get_db, utcnow, Strategy, RiskConfig, BacktestRun,
    BacktestMetrics, EquityCurve, Trade
)
from backtest_engine.data_loader import DataLoader
from backtest_engine.backtester import Backtester
from backtest_engine.strategies.moving_average import MovingAverageCrossover
from backtest_engine.strategies.rsi_strategy import RSIMeanReversion
from backtest_engine.strategies.trend_following import TrendFollowing
from backtest_engine.metrics import returns_by_regime
from backtest_engine.regimes import RegimeModel
from backtest_engine.risk import RiskConfig as EngineRiskConfig

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_PATH = REPO_ROOT / 'data' / 'sample_data.csv'

# Returned with every result so API clients cannot mistake the data for market prices
DATA_SOURCE = {
    'synthetic': True,
    'file': 'data/sample_data.csv',
    'description': ('Synthetic daily bars from a seeded Markov regime-switching GBM '
                    '(config/data_generator.json). Ticker names are labels only.'),
}


def _num(value: Union[Decimal, float, None]) -> Optional[float]:
    """
    NUMERIC columns come back as Decimal. The API returns JSON numbers, so
    convert at this boundary (Flask would otherwise serialise a Decimal as a
    string). The exact values stay in the database.
    """
    return None if value is None else float(value)


def _iso(value: Optional[datetime]) -> Optional[str]:
    """ISO 8601 with the UTC offset, e.g. 2023-01-03T00:00:00+00:00"""
    return value.isoformat() if value is not None else None


class BacktestService:
    """Service for managing backtests"""

    DATA_PATH = os.getenv('DATA_PATH', str(DEFAULT_DATA_PATH))

    def __init__(self):
        self.strategy_map = {
            'Moving Average Crossover': MovingAverageCrossover,
            'RSI Mean Reversion': RSIMeanReversion,
            'Trend Following': TrendFollowing
        }

    def run_backtest(
        self,
        strategy_name: str,
        risk_config_name: str,
        start_date: str,
        end_date: str,
        initial_capital: float,
        symbols: Optional[List[str]] = None,
        market_regime: Optional[str] = None
    ) -> Dict:
        """Run a backtest and store results"""
        response, _ = self.run_backtest_with_results(
            strategy_name, risk_config_name, start_date, end_date, initial_capital,
            symbols, market_regime)
        return response

    def run_backtest_with_results(
        self,
        strategy_name: str,
        risk_config_name: str,
        start_date: str,
        end_date: str,
        initial_capital: float,
        symbols: Optional[List[str]] = None,
        market_regime: Optional[str] = None
    ) -> Tuple[Dict, Dict]:
        """
        run_backtest(), plus the engine's in-memory results: the float64
        equity curve before it is stored as NUMERIC, and every trade. The SQL
        cross-check compares against these.
        """

        with get_db() as db:
            # Get strategy from database
            strategy_db = db.query(Strategy).filter(Strategy.name == strategy_name).first()
            if not strategy_db:
                raise ValueError(f"Strategy not found: {strategy_name}")

            # Get risk config from database
            risk_config_db = db.query(RiskConfig).filter(RiskConfig.name == risk_config_name).first()
            if not risk_config_db:
                raise ValueError(f"Risk configuration not found: {risk_config_name}")

            # Create strategy instance
            strategy_class = self.strategy_map.get(strategy_name)
            if not strategy_class:
                raise ValueError(f"Strategy implementation not found: {strategy_name}")

            strategy = strategy_class(strategy_db.parameters)

            # Create risk config
            risk_config = EngineRiskConfig(
                name=risk_config_db.name,
                max_position_size=risk_config_db.max_position_size,
                max_portfolio_exposure=risk_config_db.max_portfolio_exposure,
                stop_loss_pct=risk_config_db.stop_loss_pct,
                take_profit_pct=risk_config_db.take_profit_pct,
                max_drawdown_pct=risk_config_db.max_drawdown_pct,
                enabled=risk_config_db.enabled
            )

            # Create backtest run record
            backtest_run = BacktestRun(
                strategy_id=strategy_db.id,
                risk_config_id=risk_config_db.id,
                start_date=datetime.strptime(start_date, '%Y-%m-%d').date(),
                end_date=datetime.strptime(end_date, '%Y-%m-%d').date(),
                initial_capital=initial_capital,
                symbols=symbols,
                market_regime=market_regime,
                status='running'
            )
            db.add(backtest_run)
            db.flush()

            backtest_id = backtest_run.id

        # Run backtest
        try:
            data_loader = DataLoader(self.DATA_PATH)
            backtester = Backtester(
                strategy=strategy,
                data_loader=data_loader,
                initial_capital=initial_capital,
                risk_config=risk_config,
                start_date=start_date,
                end_date=end_date,
                symbols=symbols
            )

            results = backtester.run()

            # Store results in database
            with get_db() as db:
                # Update run status
                backtest_run = db.query(BacktestRun).filter(BacktestRun.id == backtest_id).first()
                backtest_run.status = 'completed'
                backtest_run.completed_at = utcnow()

                # Store metrics (only fields that exist in the database model)
                metrics_data = results['metrics']
                metrics = BacktestMetrics(
                    backtest_run_id=backtest_id,
                    total_return=metrics_data['total_return'],
                    cagr=metrics_data['cagr'],
                    max_drawdown=metrics_data['max_drawdown'],
                    volatility=metrics_data['volatility'],
                    sharpe_ratio=metrics_data['sharpe_ratio'],
                    win_rate=metrics_data['win_rate'],
                    avg_win=metrics_data['avg_win'],
                    avg_loss=metrics_data['avg_loss'],
                    num_trades=metrics_data['num_trades'],
                    final_equity=metrics_data['final_equity']
                )
                db.add(metrics)

                # Store equity curve
                for point in results['equity_curve']:
                    equity_point = EquityCurve(
                        backtest_run_id=backtest_id,
                        timestamp=point['timestamp'],
                        equity=point['equity'],
                        cash=point['cash'],
                        positions_value=point['positions_value']
                    )
                    db.add(equity_point)

                # Store trades
                for trade_data in results['trades']:
                    if trade_data['status'] == 'closed':
                        trade = Trade(
                            backtest_run_id=backtest_id,
                            symbol=trade_data['symbol'],
                            entry_date=datetime.fromisoformat(trade_data['entry_date']),
                            exit_date=datetime.fromisoformat(trade_data['exit_date']) if trade_data['exit_date'] else None,
                            entry_price=trade_data['entry_price'],
                            exit_price=trade_data['exit_price'],
                            quantity=trade_data['quantity'],
                            side=trade_data['side'],
                            pnl=trade_data['pnl'],
                            pnl_pct=trade_data['pnl_pct'],
                            status=trade_data['status']
                        )
                        db.add(trade)

            return {
                'backtest_id': backtest_id,
                'status': 'completed',
                'metrics': results['metrics'],
                'summary': results['final_portfolio'],
                'data': DATA_SOURCE
            }, results

        except Exception as e:
            # Update status to failed
            with get_db() as db:
                backtest_run = db.query(BacktestRun).filter(BacktestRun.id == backtest_id).first()
                if backtest_run:
                    backtest_run.status = 'failed'

            raise e

    def get_backtest_results(self, backtest_id: int) -> Optional[Dict]:
        """Get full backtest results"""
        with get_db() as db:
            backtest_run = db.query(BacktestRun).filter(BacktestRun.id == backtest_id).first()

            if not backtest_run:
                return None

            # Get metrics
            metrics = db.query(BacktestMetrics).filter(
                BacktestMetrics.backtest_run_id == backtest_id
            ).first()

            # Get equity curve
            equity_curve = db.query(EquityCurve).filter(
                EquityCurve.backtest_run_id == backtest_id
            ).order_by(EquityCurve.timestamp).all()

            # Get trades
            trades = db.query(Trade).filter(
                Trade.backtest_run_id == backtest_id
            ).order_by(Trade.entry_date).all()

            result = {
                'id': backtest_run.id,
                'strategy': backtest_run.strategy.name,
                'risk_config': backtest_run.risk_config.name,
                'start_date': backtest_run.start_date.isoformat(),
                'end_date': backtest_run.end_date.isoformat(),
                'initial_capital': _num(backtest_run.initial_capital),
                'symbols': backtest_run.symbols,
                'market_regime': backtest_run.market_regime,
                'status': backtest_run.status,
                'created_at': _iso(backtest_run.created_at),
                'metrics': {
                    'total_return': metrics.total_return,
                    'cagr': metrics.cagr,
                    'max_drawdown': metrics.max_drawdown,
                    'volatility': metrics.volatility,
                    'sharpe_ratio': metrics.sharpe_ratio,
                    'win_rate': metrics.win_rate,
                    'avg_win': _num(metrics.avg_win),
                    'avg_loss': _num(metrics.avg_loss),
                    'num_trades': metrics.num_trades,
                    'final_equity': _num(metrics.final_equity)
                } if metrics else None,
                'equity_curve': [
                    {
                        'timestamp': _iso(point.timestamp),
                        'equity': _num(point.equity),
                        'cash': _num(point.cash),
                        'positions_value': _num(point.positions_value)
                    }
                    for point in equity_curve
                ],
                'trades': [
                    {
                        'symbol': t.symbol,
                        'entry_date': _iso(t.entry_date),
                        'exit_date': _iso(t.exit_date),
                        'entry_price': _num(t.entry_price),
                        'exit_price': _num(t.exit_price),
                        'quantity': _num(t.quantity),
                        'side': t.side,
                        'pnl': _num(t.pnl),
                        'pnl_pct': t.pnl_pct,
                        'status': t.status
                    }
                    for t in trades
                ],
                'data': DATA_SOURCE
            }

        return result

    def list_backtests(self, strategy_id: Optional[int] = None, limit: int = 50) -> List[Dict]:
        """List backtests with optional filtering"""
        with get_db() as db:
            query = db.query(BacktestRun)

            if strategy_id:
                query = query.filter(BacktestRun.strategy_id == strategy_id)

            backtests = query.order_by(BacktestRun.created_at.desc()).limit(limit).all()

            result = []
            for bt in backtests:
                metrics = db.query(BacktestMetrics).filter(
                    BacktestMetrics.backtest_run_id == bt.id
                ).first()

                result.append({
                    'id': bt.id,
                    'strategy': bt.strategy.name,
                    'risk_config': bt.risk_config.name,
                    'start_date': bt.start_date.isoformat(),
                    'end_date': bt.end_date.isoformat(),
                    'status': bt.status,
                    'total_return': metrics.total_return if metrics else None,
                    'max_drawdown': metrics.max_drawdown if metrics else None,
                    'sharpe_ratio': metrics.sharpe_ratio if metrics else None,
                    'created_at': _iso(bt.created_at)
                })

        return result

    def compare_backtests(self, baseline_id: int, comparison_id: int) -> Dict:
        """Compare two backtests"""
        baseline = self.get_backtest_results(baseline_id)
        comparison = self.get_backtest_results(comparison_id)

        if not baseline or not comparison:
            raise ValueError("One or both backtests not found")

        baseline_metrics = baseline['metrics']
        comparison_metrics = comparison['metrics']

        return {
            'baseline': {
                'id': baseline_id,
                'strategy': baseline['strategy'],
                'risk_config': baseline['risk_config'],
                'metrics': baseline_metrics
            },
            'comparison': {
                'id': comparison_id,
                'strategy': comparison['strategy'],
                'risk_config': comparison['risk_config'],
                'metrics': comparison_metrics
            },
            'differences': {
                'total_return_diff': comparison_metrics['total_return'] - baseline_metrics['total_return'],
                'max_drawdown_diff': comparison_metrics['max_drawdown'] - baseline_metrics['max_drawdown'],
                'sharpe_ratio_diff': comparison_metrics['sharpe_ratio'] - baseline_metrics['sharpe_ratio'],
                'drawdown_improvement_pct': (
                    (baseline_metrics['max_drawdown'] - comparison_metrics['max_drawdown']) /
                    baseline_metrics['max_drawdown'] * 100
                ) if baseline_metrics['max_drawdown'] > 0 else 0
            }
        }

    def run_regime_analysis(
        self,
        strategy_name: str,
        risk_config_name: str,
        initial_capital: float,
        symbols: Optional[List[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> Dict:
        """
        Run one backtest and split its daily returns by market regime.

        The regime of each day comes from the data's `regime` column, which the
        synthetic generator writes. Data without that column is rejected.
        """
        data = DataLoader(self.DATA_PATH).load_csv(symbols)
        if 'regime' not in data.columns:
            raise ValueError('The data file has no regime column, so returns cannot be split by regime')
        if data.empty:
            raise ValueError('No data for the requested symbols')

        start_date = start_date or data['timestamp'].min().strftime('%Y-%m-%d')
        end_date = end_date or data['timestamp'].max().strftime('%Y-%m-%d')

        run = self.run_backtest(
            strategy_name=strategy_name,
            risk_config_name=risk_config_name,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            symbols=symbols
        )
        equity_curve = self.get_backtest_results(run['backtest_id'])['equity_curve']

        regime_by_date = data.drop_duplicates('timestamp').set_index('timestamp')['regime'].to_dict()
        try:
            regime_order = RegimeModel.from_json().names
        except (OSError, ValueError, KeyError):
            regime_order = None

        return {
            'strategy': strategy_name,
            'risk_config': risk_config_name,
            'backtest_id': run['backtest_id'],
            'start_date': start_date,
            'end_date': end_date,
            'metrics': run['metrics'],
            'by_regime': returns_by_regime(equity_curve, regime_by_date, regime_order),
            'data': DATA_SOURCE
        }
