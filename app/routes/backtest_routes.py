"""
Backtest API routes
"""
from flask import Blueprint, request, jsonify
from datetime import datetime
from app.services.backtest_service import BacktestService

bp = Blueprint('backtest', __name__, url_prefix='/api/backtest')


@bp.route('/', methods=['POST'])
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
        "market_regime": "mixed"
    }
    """
    try:
        data = request.get_json()

        # Validate required fields
        required = ['strategy_name', 'start_date', 'end_date', 'initial_capital']
        for field in required:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400

        service = BacktestService()
        result = service.run_backtest(
            strategy_name=data['strategy_name'],
            risk_config_name=data.get('risk_config_name', 'No Risk Management'),
            start_date=data['start_date'],
            end_date=data['end_date'],
            initial_capital=data['initial_capital'],
            symbols=data.get('symbols'),
            market_regime=data.get('market_regime', 'mixed')
        )

        return jsonify(result), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/<int:backtest_id>', methods=['GET'])
def get_backtest(backtest_id):
    """Get backtest results by ID"""
    try:
        service = BacktestService()
        result = service.get_backtest_results(backtest_id)

        if not result:
            return jsonify({'error': 'Backtest not found'}), 404

        return jsonify(result), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/list', methods=['GET'])
def list_backtests():
    """List all backtests with optional filters"""
    try:
        strategy_id = request.args.get('strategy_id', type=int)
        limit = request.args.get('limit', 50, type=int)

        service = BacktestService()
        results = service.list_backtests(strategy_id=strategy_id, limit=limit)

        return jsonify(results), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/compare', methods=['POST'])
def compare_backtests():
    """
    Compare two backtests

    Expected JSON:
    {
        "baseline_id": 1,
        "comparison_id": 2
    }
    """
    try:
        data = request.get_json()

        baseline_id = data.get('baseline_id')
        comparison_id = data.get('comparison_id')

        if not baseline_id or not comparison_id:
            return jsonify({'error': 'Missing baseline_id or comparison_id'}), 400

        service = BacktestService()
        result = service.compare_backtests(baseline_id, comparison_id)

        return jsonify(result), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/regime-analysis', methods=['POST'])
def regime_analysis():
    """
    Run backtests across different market regimes

    Expected JSON:
    {
        "strategy_name": "Moving Average Crossover",
        "risk_config_name": "Conservative",
        "initial_capital": 100000,
        "symbols": ["AAPL", "GOOGL"]
    }
    """
    try:
        data = request.get_json()

        service = BacktestService()
        result = service.run_regime_analysis(
            strategy_name=data['strategy_name'],
            risk_config_name=data.get('risk_config_name', 'Conservative'),
            initial_capital=data['initial_capital'],
            symbols=data.get('symbols')
        )

        return jsonify(result), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500
