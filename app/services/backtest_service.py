"""
Backtest service layer
Handles business logic for running and managing backtests
"""
import logging
from bisect import bisect_left
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Iterator, List, Optional, Dict, Tuple, Union
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
from data_sources.market_data import MarketDataBadRequest, MarketDataError, MarketDataNotFound
from data_sources.sources import (
    SYNTHETIC, DataConfig, DataSourceError, LoadedBars, MarketDataSource, NoBars, Provenance,
    SyntheticSource, open_source,
)

log = logging.getLogger(__name__)


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


class InvalidRequest(ValueError):
    """
    A client error: an unknown strategy or risk profile, or bad parameters,
    dates, symbols, capital or data source. The API answers 400 with the message.
    """


class DataSourceUnavailable(RuntimeError):
    """
    The market-data service failed (down, timing out, rate-limiting past the
    retries, or answering outside its contract). The API answers 502.
    """


# NUMERIC(18, 4) holds values below 1e14; this leaves room for gains
MAX_INITIAL_CAPITAL = 1e12


def _parse_date(value, field: str) -> date:
    try:
        return datetime.strptime(str(value), '%Y-%m-%d').date()
    except ValueError:
        raise InvalidRequest(f'{field} must be a date in YYYY-MM-DD form')


def run_provenance(run: BacktestRun) -> Provenance:
    """A stored run's data provenance (migration 0004 columns)"""
    return Provenance(data_source=run.data_source, reported_source=run.reported_source,
                      symbol_sources=run.symbol_sources, adjustment=run.price_adjustment)


class BacktestService:
    """Service for managing backtests"""

    # Extra MarketDataClient arguments; the tests pass a fake transport here
    client_kwargs: Dict = {}

    def __init__(self, config: Optional[DataConfig] = None):
        self.strategy_map = {
            'Moving Average Crossover': MovingAverageCrossover,
            'RSI Mean Reversion': RSIMeanReversion,
            'Trend Following': TrendFollowing
        }
        self.config = config or DataConfig.from_env()

    @contextmanager
    def _source(self, requested: Optional[str]) -> Iterator[Union[SyntheticSource, MarketDataSource]]:
        """
        The data source for one request, as a context. Maps market-data
        failures to InvalidRequest (the request can't be served as asked) or
        DataSourceUnavailable (the service failed).
        """
        try:
            name = self.config.resolve(requested)
        except DataSourceError as e:
            raise InvalidRequest(str(e))
        source = open_source(self.config, name, **self.client_kwargs)
        try:
            yield source
        except NoBars as e:
            raise InvalidRequest(str(e))
        except (MarketDataNotFound, MarketDataBadRequest) as e:
            raise InvalidRequest(str(e))
        except MarketDataError as e:
            log.warning('market-data failed: %s', e)
            raise DataSourceUnavailable(str(e))
        finally:
            if isinstance(source, MarketDataSource):
                source.client.close()

    def data_info(self, data_source: Optional[str] = None) -> Dict:
        """The data source's label, symbols and date range (and bar count for the file)"""
        with self._source(data_source) as source:
            info = source.info()
        return {**info, 'available_sources': self.config.available,
                'default_source': self.config.default_source}

    def run_backtest(
        self,
        strategy_name: str,
        risk_config_name: str,
        start_date: str,
        end_date: str,
        initial_capital: float,
        symbols: Optional[List[str]] = None,
        market_regime: Optional[str] = None,
        parameters: Optional[Dict] = None,
        compare_to_baseline: bool = False,
        data_source: Optional[str] = None
    ) -> Dict:
        """
        Run a backtest and store results.

        parameters: overrides for the strategy's stored parameters.
        compare_to_baseline: also run the same inputs with the risk layer off
        first, store it, and link this run to it (`baseline` in the response).
        Ignored when the chosen profile already has the risk layer off.
        data_source: 'synthetic' or 'market-data'; default from the config.
        """
        response, _ = self.run_backtest_with_results(
            strategy_name, risk_config_name, start_date, end_date, initial_capital,
            symbols, market_regime, parameters, compare_to_baseline, data_source)
        return response

    def run_backtest_with_results(
        self,
        strategy_name: str,
        risk_config_name: str,
        start_date: str,
        end_date: str,
        initial_capital: float,
        symbols: Optional[List[str]] = None,
        market_regime: Optional[str] = None,
        parameters: Optional[Dict] = None,
        compare_to_baseline: bool = False,
        data_source: Optional[str] = None
    ) -> Tuple[Dict, Dict]:
        """
        run_backtest(), plus the engine's in-memory results: the float64
        equity curve before it is stored as NUMERIC, and every trade. The SQL
        cross-check compares against these.

        The bars are loaded once, after validation and before anything is
        stored, and both runs of a baseline pair use them, so the pair always
        shares its data and its provenance.
        """
        with self._source(data_source) as source:
            self._validate_inputs(source, start_date, end_date, initial_capital, symbols)
            with get_db() as db:   # unknown strategy, profile or bad parameters: fail before fetching
                self._build(db, strategy_name, risk_config_name, parameters)
            bars = source.load(symbols, _parse_date(start_date, 'start_date'),
                               _parse_date(end_date, 'end_date'))

        baseline = None
        if compare_to_baseline:
            with get_db() as db:
                chosen = db.query(RiskConfig).filter(RiskConfig.name == risk_config_name).first()
                risk_layer_on = chosen is not None and bool(chosen.enabled)
                baseline_profile = (db.query(RiskConfig).filter(RiskConfig.enabled.is_(False))
                                    .order_by(RiskConfig.id).first())
                baseline_name = baseline_profile.name if baseline_profile else None
            if risk_layer_on:
                if baseline_name is None:
                    raise InvalidRequest('No risk profile with the risk layer off to compare against')
                baseline, _ = self._run(strategy_name, baseline_name, start_date, end_date,
                                        initial_capital, symbols, market_regime, parameters, bars)

        response, results = self._run(
            strategy_name, risk_config_name, start_date, end_date, initial_capital, symbols,
            market_regime, parameters, bars,
            baseline_run_id=baseline['backtest_id'] if baseline else None)
        response['baseline'] = (
            {'backtest_id': baseline['backtest_id'], 'risk_config': baseline_name,
             'metrics': baseline['metrics']}
            if baseline else None)
        return response, results

    def _validate_inputs(self, source, start_date, end_date, initial_capital, symbols) -> None:
        start, end = _parse_date(start_date, 'start_date'), _parse_date(end_date, 'end_date')
        if start > end:
            raise InvalidRequest('start_date must not be after end_date')
        if isinstance(source, SyntheticSource):
            known_symbols, dates = source.index()
            first_bar = bisect_left(dates, start)
            if first_bar == len(dates) or dates[first_bar] > end:
                raise InvalidRequest(f'No bars between {start} and {end}; the data covers '
                                     f'{dates[0]} to {dates[-1]} (business days)')

        if isinstance(initial_capital, bool) or not isinstance(initial_capital, (int, float)):
            raise InvalidRequest('initial_capital must be a number')
        if not 0 < initial_capital <= MAX_INITIAL_CAPITAL:
            raise InvalidRequest(f'initial_capital must be above 0 and at most {MAX_INITIAL_CAPITAL:,.0f}')

        if symbols is not None:
            if not isinstance(symbols, list) or not symbols or not all(isinstance(s, str) for s in symbols):
                raise InvalidRequest('symbols must be a non-empty list of strings')
        if isinstance(source, SyntheticSource):
            unknown = sorted(set(symbols or ()) - set(known_symbols))
            if unknown:
                raise InvalidRequest(f"Unknown symbol(s): {', '.join(unknown)}")
            return

        # market-data: one listing call; every symbol must be visible to this server
        if symbols is None:
            raise InvalidRequest('symbols is required with the market-data source')
        listing = {s.ticker: s for s in source.symbols()}
        unknown = sorted(set(symbols) - set(listing))
        if unknown:
            hint = '' if source.client.has_api_key else (
                ' (without MARKET_DATA_API_KEY the service shows only its public symbols, which are '
                'synthetic unless its operator has made Alpaca data public)')
            raise InvalidRequest(f"Unknown symbol(s): {', '.join(unknown)}{hint}")
        first = min(listing[s].first_bar for s in symbols)
        last = max(listing[s].last_bar for s in symbols)
        if end < first or start > last:
            raise InvalidRequest(f'No bars between {start} and {end}; market-data has these symbols '
                                 f'from {first} to {last}')

    def _build(self, db, strategy_name: str, risk_config_name: str, parameters: Optional[Dict]):
        """Look up and check the strategy, the risk profile and the parameters"""
        strategy_db = db.query(Strategy).filter(Strategy.name == strategy_name).first()
        if not strategy_db:
            raise InvalidRequest(f"Strategy not found: {strategy_name}")

        risk_config_db = db.query(RiskConfig).filter(RiskConfig.name == risk_config_name).first()
        if not risk_config_db:
            raise InvalidRequest(f"Risk configuration not found: {risk_config_name}")

        strategy_class = self.strategy_map.get(strategy_name)
        if not strategy_class:
            raise InvalidRequest(f"Strategy implementation not found: {strategy_name}")

        if parameters is not None and not isinstance(parameters, dict):
            raise InvalidRequest('parameters must be an object')
        try:
            strategy_parameters = strategy_class.validate_parameters(
                {**(strategy_db.parameters or {}), **(parameters or {})})
        except ValueError as e:
            raise InvalidRequest(str(e))

        risk_config = EngineRiskConfig(
            name=risk_config_db.name,
            max_position_size=risk_config_db.max_position_size,
            max_portfolio_exposure=risk_config_db.max_portfolio_exposure,
            stop_loss_pct=risk_config_db.stop_loss_pct,
            take_profit_pct=risk_config_db.take_profit_pct,
            max_drawdown_pct=risk_config_db.max_drawdown_pct,
            enabled=risk_config_db.enabled
        )
        return strategy_db, risk_config_db, strategy_class(strategy_parameters), risk_config, strategy_parameters

    def _run(
        self,
        strategy_name: str,
        risk_config_name: str,
        start_date: str,
        end_date: str,
        initial_capital: float,
        symbols: Optional[List[str]],
        market_regime: Optional[str],
        parameters: Optional[Dict],
        bars: LoadedBars,
        baseline_run_id: Optional[int] = None
    ) -> Tuple[Dict, Dict]:
        """Run one backtest on already-loaded bars and store it"""
        provenance = bars.provenance
        with get_db() as db:
            strategy_db, risk_config_db, strategy, risk_config, strategy_parameters = self._build(
                db, strategy_name, risk_config_name, parameters)

            # Create backtest run record, with where its bars came from
            backtest_run = BacktestRun(
                strategy_id=strategy_db.id,
                risk_config_id=risk_config_db.id,
                start_date=_parse_date(start_date, 'start_date'),
                end_date=_parse_date(end_date, 'end_date'),
                initial_capital=initial_capital,
                symbols=symbols,
                market_regime=market_regime,
                status='running',
                strategy_parameters=strategy_parameters,
                baseline_run_id=baseline_run_id,
                data_source=provenance.data_source,
                reported_source=provenance.reported_source,
                symbol_sources=provenance.symbol_sources,
                price_adjustment=provenance.adjustment
            )
            db.add(backtest_run)
            db.flush()

            backtest_id = backtest_run.id

        # Run backtest
        try:
            backtester = Backtester(
                strategy=strategy,
                data_loader=bars.loader,
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
                'data': provenance.to_api()
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
                'strategy_parameters': backtest_run.strategy_parameters,
                'baseline_run_id': backtest_run.baseline_run_id,
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
                'data': run_provenance(backtest_run).to_api()
            }

        return result

    def list_backtests(self, strategy_id: Optional[int] = None, limit: int = 50) -> List[Dict]:
        """List backtests with optional filtering"""
        with get_db() as db:
            query = db.query(BacktestRun)

            if strategy_id:
                query = query.filter(BacktestRun.strategy_id == strategy_id)

            backtests = query.order_by(BacktestRun.created_at.desc(), BacktestRun.id.desc()).limit(limit).all()

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
                    'symbols': bt.symbols,
                    'initial_capital': _num(bt.initial_capital),
                    'baseline_run_id': bt.baseline_run_id,
                    'status': bt.status,
                    'total_return': metrics.total_return if metrics else None,
                    'max_drawdown': metrics.max_drawdown if metrics else None,
                    'sharpe_ratio': metrics.sharpe_ratio if metrics else None,
                    'created_at': _iso(bt.created_at),
                    'data_source': bt.data_source,
                    'reported_source': bt.reported_source,
                    'synthetic': not run_provenance(bt).real
                })

        return result

    def compare_backtests(self, baseline_id: int, comparison_id: int) -> Dict:
        """Compare two backtests"""
        baseline = self.get_backtest_results(baseline_id)
        comparison = self.get_backtest_results(comparison_id)

        if not baseline or not comparison:
            raise LookupError("One or both backtests not found")

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
        end_date: Optional[str] = None,
        data_source: Optional[str] = None
    ) -> Dict:
        """
        Run one backtest and split its daily returns by market regime.

        The regime of each day comes from the data's `regime` column, which the
        synthetic generator writes. Market-data bars have no regime labels, so
        this needs the synthetic source, whatever the configured default.
        """
        try:
            name = self.config.resolve(data_source)
        except DataSourceError as e:
            raise InvalidRequest(str(e))
        if name != SYNTHETIC:
            raise InvalidRequest('Regime analysis needs the regime labels that only the synthetic data has; '
                                 'send "data_source": "synthetic"')
        data = DataLoader(str(self.config.synthetic_path)).load_csv(symbols)
        if 'regime' not in data.columns:
            raise ValueError('The data file has no regime column, so returns cannot be split by regime')
        if data.empty:
            raise InvalidRequest('No data for the requested symbols')

        start_date = start_date or data['timestamp'].min().strftime('%Y-%m-%d')
        end_date = end_date or data['timestamp'].max().strftime('%Y-%m-%d')

        run = self.run_backtest(
            strategy_name=strategy_name,
            risk_config_name=risk_config_name,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            symbols=symbols,
            data_source=SYNTHETIC
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
            'data': run['data']
        }
