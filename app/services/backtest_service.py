"""
Backtest service layer
Handles business logic for running and managing backtests
"""
import logging
from bisect import bisect_left
from contextlib import contextmanager
from dataclasses import dataclass
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


# For a null metric stored before reasons were recorded (migration 0005)
REASON_NOT_RECORDED = 'undefined; the reason was not recorded for this run'


def undefined_for(values: Dict, reasons: Optional[Dict[str, str]]) -> Dict[str, str]:
    """
    The `undefined_metrics` object that goes next to `values`: the reason for
    each value that is None, and nothing else. A metric is null in the API
    only when it is undefined for the run (docs/api.md#undefined-metrics).
    """
    reasons = reasons or {}
    return {name: reasons.get(name, REASON_NOT_RECORDED) for name, value in values.items() if value is None}


def _stored_metrics(metrics: BacktestMetrics) -> Dict:
    return {
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
    }


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


class RunNotFound(LookupError):
    """A backtest id that isn't stored. The API answers 404."""


# NUMERIC(18, 4) holds values below 1e14; this leaves room for gains
MAX_INITIAL_CAPITAL = 1e12
# Column widths: trades.symbol and backtest_runs.market_regime
MAX_SYMBOL_LENGTH = 20
MAX_REGIME_LABEL_LENGTH = 50


@dataclass(frozen=True)
class RequestLimits:
    """
    Caps on what one request may ask for. The API applies the configured ones
    (app/config.py); scripts that call the service directly have none.
    """
    max_symbols: int
    max_range_days: int


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

    def __init__(self, config: Optional[DataConfig] = None, limits: Optional[RequestLimits] = None,
                 deadline: Optional[float] = None):
        """
        limits: request caps (None: no caps). deadline: a time.monotonic()
        value after which a running backtest stops with BacktestTimeout; it
        covers the whole request, both runs of a baseline pair included.
        """
        self.strategy_map = {
            'Moving Average Crossover': MovingAverageCrossover,
            'RSI Mean Reversion': RSIMeanReversion,
            'Trend Following': TrendFollowing
        }
        self.config = config or DataConfig.from_env()
        self.limits = limits
        self.deadline = deadline

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
        if market_regime is not None and (not isinstance(market_regime, str)
                                          or len(market_regime) > MAX_REGIME_LABEL_LENGTH):
            raise InvalidRequest(f'market_regime must be text of at most {MAX_REGIME_LABEL_LENGTH} characters')
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
             'metrics': baseline['metrics'], 'undefined_metrics': baseline['undefined_metrics']}
            if baseline else None)
        return response, results

    def _validate_inputs(self, source, start_date, end_date, initial_capital, symbols) -> None:
        start, end = _parse_date(start_date, 'start_date'), _parse_date(end_date, 'end_date')
        if start > end:
            raise InvalidRequest('start_date must not be after end_date')
        days = (end - start).days + 1
        if self.limits and days > self.limits.max_range_days:
            raise InvalidRequest(f'The period is {days:,} days; this server allows at most '
                                 f'{self.limits.max_range_days:,} per run')
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
            if any(not 0 < len(s) <= MAX_SYMBOL_LENGTH for s in symbols):
                raise InvalidRequest(f'Each symbol must be 1 to {MAX_SYMBOL_LENGTH} characters')
        if self.limits:
            count = len(symbols) if symbols is not None else (
                len(known_symbols) if isinstance(source, SyntheticSource) else 0)
            if count > self.limits.max_symbols:
                omitted = '' if symbols is not None else '; without symbols the run would use every one in the file'
                raise InvalidRequest(f'This server allows at most {self.limits.max_symbols} symbols per run, '
                                     f'got {count}{omitted}')
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
                symbols=symbols,
                deadline=self.deadline
            )

            results = backtester.run()

            # Store results in database
            with get_db() as db:
                # Update run status
                backtest_run = db.query(BacktestRun).filter(BacktestRun.id == backtest_id).first()
                backtest_run.status = 'completed'
                backtest_run.completed_at = utcnow()

                # Store metrics (only fields that exist in the database model).
                # Undefined ones are None -> NULL, with the reasons alongside.
                metrics_data = results['metrics']
                metrics = BacktestMetrics(
                    undefined_metrics=results['undefined_metrics'] or None,
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
                'undefined_metrics': undefined_for(results['metrics'], results['undefined_metrics']),
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

            stored = _stored_metrics(metrics) if metrics else None

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
                'metrics': stored,
                'undefined_metrics': (undefined_for(stored, metrics.undefined_metrics)
                                      if metrics else None),
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

                summary = {
                    'total_return': metrics.total_return if metrics else None,
                    'max_drawdown': metrics.max_drawdown if metrics else None,
                    'sharpe_ratio': metrics.sharpe_ratio if metrics else None,
                }
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
                    **summary,
                    # null for a run with no metrics (failed); otherwise why any of the three is null
                    'undefined_metrics': undefined_for(summary, metrics.undefined_metrics) if metrics else None,
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
            raise RunNotFound("One or both backtests not found")

        for run_id, run in ((baseline_id, baseline), (comparison_id, comparison)):
            if run['metrics'] is None:
                raise InvalidRequest(f"Backtest {run_id} has no metrics (status: {run['status']})")
        baseline_metrics = baseline['metrics']
        comparison_metrics = comparison['metrics']

        differences: Dict[str, Optional[float]] = {}
        reasons: Dict[str, str] = {}
        for key in ('total_return', 'max_drawdown', 'sharpe_ratio'):
            undefined_in = [label for label, m in (('baseline', baseline_metrics),
                                                   ('comparison', comparison_metrics)) if m[key] is None]
            differences[f'{key}_diff'] = (None if undefined_in
                                          else comparison_metrics[key] - baseline_metrics[key])
            if undefined_in:
                reasons[f'{key}_diff'] = f"{key} is undefined for the {' and '.join(undefined_in)} run"
        base_drawdown = baseline_metrics['max_drawdown']
        if base_drawdown is None or comparison_metrics['max_drawdown'] is None:
            differences['drawdown_improvement_pct'] = None
            reasons['drawdown_improvement_pct'] = 'max_drawdown is undefined for a run'
        elif base_drawdown > 0:
            differences['drawdown_improvement_pct'] = (
                (base_drawdown - comparison_metrics['max_drawdown']) / base_drawdown * 100)
        else:
            differences['drawdown_improvement_pct'] = None
            reasons['drawdown_improvement_pct'] = 'the baseline run had no drawdown'

        return {
            'baseline': {
                'id': baseline_id,
                'strategy': baseline['strategy'],
                'risk_config': baseline['risk_config'],
                'metrics': baseline_metrics,
                'undefined_metrics': baseline['undefined_metrics']
            },
            'comparison': {
                'id': comparison_id,
                'strategy': comparison['strategy'],
                'risk_config': comparison['risk_config'],
                'metrics': comparison_metrics,
                'undefined_metrics': comparison['undefined_metrics']
            },
            'differences': differences,
            'undefined_differences': reasons
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
            'undefined_metrics': run['undefined_metrics'],
            'by_regime': returns_by_regime(equity_curve, regime_by_date, regime_order),
            'data': run['data']
        }
