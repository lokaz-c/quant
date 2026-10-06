"""
Backtest API routes
"""
import time

from flask import Blueprint, current_app, jsonify, request

from app.protection import run_slot
from app.routes.errors import api_errors, problem
from app.services.backtest_service import BacktestService, RequestLimits

bp = Blueprint('backtest', __name__, url_prefix='/api/backtest')

# GET /api/backtest/list?limit= at most this many rows
MAX_LIST_LIMIT = 500


def _service(timed: bool = False) -> BacktestService:
    """The service with this server's request caps and, for a run, its deadline"""
    config = current_app.config['QUANT']
    return BacktestService(
        limits=RequestLimits(max_symbols=config.max_symbols, max_range_days=config.max_range_days),
        deadline=time.monotonic() + config.backtest_timeout_seconds if timed else None)


def _json_object():
    """The request body as a dict, or None. Bodies that aren't JSON objects,
    or that hold NaN or Infinity (app/strict_json.py), give None."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


NOT_AN_OBJECT = 'Expected a JSON object'


@bp.route('/', methods=['POST'])
@api_errors
def run_backtest():
    """
    Run a new backtest

    Expected JSON:
    {
        "strategy_name": "Moving Average Crossover",
        "risk_config_name": "Conservative",
        "start_date": "2022-01-01",
        "end_date": "2023-12-31",
        "initial_capital": 100000,
        "symbols": ["AAPL", "GOOGL"],
        "parameters": {"fast_period": 10},      # optional overrides
        "compare_to_baseline": true,            # optional
        "data_source": "market-data"            # optional: synthetic | market-data
    }

    The response's `data` object says where the bars came from: the local
    synthetic generator, or the market-data service and the source it
    reported for each symbol. Invalid input or a request over the server's
    caps is a 400 with the reason; a market-data failure is a 502; a run past
    the time limit is a 504; every run slot taken is a 503.
    """
    data = _json_object()
    if data is None:
        return problem(400, NOT_AN_OBJECT)

    # Validate required fields
    required = ['strategy_name', 'start_date', 'end_date', 'initial_capital']
    for field in required:
        if field not in data:
            return problem(400, f'Missing required field: {field}')

    with run_slot():
        result = _service(timed=True).run_backtest(
            strategy_name=data['strategy_name'],
            risk_config_name=data.get('risk_config_name', 'No Risk Management'),
            start_date=data['start_date'],
            end_date=data['end_date'],
            initial_capital=data['initial_capital'],
            symbols=data.get('symbols'),
            market_regime=data.get('market_regime'),
            parameters=data.get('parameters'),
            compare_to_baseline=bool(data.get('compare_to_baseline', False)),
            data_source=data.get('data_source')
        )

    return jsonify(result), 200


@bp.route('/<int:backtest_id>', methods=['GET'])
@api_errors
def get_backtest(backtest_id):
    """Get backtest results by ID"""
    result = _service().get_backtest_results(backtest_id)

    if not result:
        return problem(404, 'Backtest not found')

    return jsonify(result), 200


@bp.route('/list', methods=['GET'])
@api_errors
def list_backtests():
    """List backtests, newest first, with optional filters"""
    strategy_id = request.args.get('strategy_id', type=int)
    limit = request.args.get('limit', 50, type=int)
    if not 1 <= limit <= MAX_LIST_LIMIT:
        return problem(400, f'limit must be between 1 and {MAX_LIST_LIMIT}')

    results = _service().list_backtests(strategy_id=strategy_id, limit=limit)

    return jsonify(results), 200


@bp.route('/compare', methods=['POST'])
@api_errors
def compare_backtests():
    """
    Compare two backtests

    Expected JSON:
    {
        "baseline_id": 1,
        "comparison_id": 2
    }
    """
    data = _json_object()
    if data is None:
        return problem(400, NOT_AN_OBJECT)

    baseline_id = data.get('baseline_id')
    comparison_id = data.get('comparison_id')

    if not baseline_id or not comparison_id:
        return problem(400, 'Missing baseline_id or comparison_id')
    if not all(isinstance(i, int) and not isinstance(i, bool) for i in (baseline_id, comparison_id)):
        return problem(400, 'baseline_id and comparison_id must be integers')

    result = _service().compare_backtests(baseline_id, comparison_id)

    return jsonify(result), 200


@bp.route('/regime-analysis', methods=['POST'])
@api_errors
def regime_analysis():
    """
    Run one backtest and split its daily returns by the generator's regime labels.
    Only the synthetic data has regime labels; with market-data as the default
    source, send "data_source": "synthetic".

    Expected JSON (dates default to the full dataset):
    {
        "strategy_name": "Moving Average Crossover",
        "risk_config_name": "Conservative",
        "initial_capital": 100000,
        "symbols": ["AAPL", "GOOGL"],
        "start_date": "2020-01-01",
        "end_date": "2024-12-31"
    }
    """
    data = _json_object()
    if data is None:
        return problem(400, NOT_AN_OBJECT)

    for field in ('strategy_name', 'initial_capital'):
        if field not in data:
            return problem(400, f'Missing required field: {field}')

    with run_slot():
        result = _service(timed=True).run_regime_analysis(
            strategy_name=data['strategy_name'],
            risk_config_name=data.get('risk_config_name', 'Conservative'),
            initial_capital=data['initial_capital'],
            symbols=data.get('symbols'),
            start_date=data.get('start_date'),
            end_date=data.get('end_date'),
            data_source=data.get('data_source')
        )

    return jsonify(result), 200
