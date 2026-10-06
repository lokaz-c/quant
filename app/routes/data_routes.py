"""
Data API route: what the backtests run on
"""
from flask import Blueprint, jsonify, request
from app.routes.errors import bad_gateway, server_error
from app.services.backtest_service import BacktestService, DataSourceUnavailable, InvalidRequest

bp = Blueprint('data', __name__, url_prefix='/api/data')


@bp.route('', methods=['GET'])
def data_info():
    """
    The data source a run would use (?source= to pick one): its label, the
    source the market-data service reports, symbols and date range
    """
    try:
        return jsonify(BacktestService().data_info(request.args.get('source'))), 200
    except InvalidRequest as e:
        return jsonify({'error': str(e)}), 400
    except DataSourceUnavailable as e:
        return bad_gateway(e)
    except Exception:
        return server_error()
