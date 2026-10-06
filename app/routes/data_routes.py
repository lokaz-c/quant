"""
Data API route: what the backtests run on
"""
from flask import Blueprint, jsonify
from app.routes.errors import server_error
from app.services.backtest_service import BacktestService

bp = Blueprint('data', __name__, url_prefix='/api/data')


@bp.route('', methods=['GET'])
def data_info():
    """The data file's synthetic label, symbols, date range and bar count"""
    try:
        return jsonify(BacktestService().data_info()), 200
    except Exception:
        return server_error()
