"""
Data API route: what the backtests run on, and the request caps
"""
from flask import Blueprint, current_app, jsonify, request

from app.routes.errors import api_errors
from app.services.backtest_service import BacktestService

bp = Blueprint('data', __name__, url_prefix='/api/data')


@bp.route('', methods=['GET'])
@api_errors
def data_info():
    """
    The data source a run would use (?source= to pick one): its label, the
    source the market-data service reports, symbols and date range; and
    `limits`, this server's caps on a run, so clients can stay inside them
    """
    config = current_app.config['QUANT']
    info = BacktestService().data_info(request.args.get('source'))
    info['limits'] = {
        'max_symbols': config.max_symbols,
        'max_range_days': config.max_range_days,
        'timeout_seconds': config.backtest_timeout_seconds,
    }
    return jsonify(info), 200
