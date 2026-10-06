"""
Strategy API routes
"""
from flask import Blueprint, request, jsonify
from sqlalchemy.exc import IntegrityError

from app.routes.errors import api_errors, problem
from app.models.database import get_db, Strategy
from app.services.backtest_service import BacktestService

# Column widths and a bound on the free-form parameters object
MAX_NAME_LENGTH = 255
MAX_DESCRIPTION_LENGTH = 2000
MAX_PARAMETERS = 50


def _parameter_limits(name):
    """Allowed range of each parameter, or None for a strategy with no implementation"""
    strategy_class = BacktestService().strategy_map.get(name)
    return strategy_class.parameter_limits() if strategy_class else None

bp = Blueprint('strategy', __name__, url_prefix='/api/strategies')


@bp.route('/', methods=['GET'])
@api_errors
def list_strategies():
    """List all available strategies"""
    with get_db() as db:
        result = [
            {
                'id': s.id,
                'name': s.name,
                'description': s.description,
                'parameters': s.parameters,
                'parameter_limits': _parameter_limits(s.name)
            }
            for s in db.query(Strategy).all()
        ]
    return jsonify(result), 200


@bp.route('/<int:strategy_id>', methods=['GET'])
@api_errors
def get_strategy(strategy_id):
    """Get strategy details"""
    with get_db() as db:
        strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()

        if not strategy:
            return problem(404, 'Strategy not found')

        result = {
            'id': strategy.id,
            'name': strategy.name,
            'description': strategy.description,
            'parameters': strategy.parameters,
            'created_at': strategy.created_at.isoformat()
        }

    return jsonify(result), 200


@bp.route('/', methods=['POST'])
@api_errors
def create_strategy():
    """
    Store a strategy record. It can only be run if BacktestService has a
    class for its name; this endpoint shares the tight rate limit of the run
    endpoints (app/protection.py).

    Expected JSON:
    {
        "name": "My Custom Strategy",
        "description": "Description here",
        "parameters": {"param1": value1}
    }
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return problem(400, 'Expected a JSON object')
    if 'name' not in data:
        return problem(400, 'Missing required field: name')
    name, description, parameters = data['name'], data.get('description'), data.get('parameters', {})
    if not isinstance(name, str) or not 0 < len(name.strip()) <= MAX_NAME_LENGTH:
        return problem(400, f'name must be text of 1 to {MAX_NAME_LENGTH} characters')
    if description is not None and (not isinstance(description, str) or len(description) > MAX_DESCRIPTION_LENGTH):
        return problem(400, f'description must be text of at most {MAX_DESCRIPTION_LENGTH} characters')
    if not isinstance(parameters, dict) or len(parameters) > MAX_PARAMETERS:
        return problem(400, f'parameters must be an object with at most {MAX_PARAMETERS} entries')

    try:
        with get_db() as db:
            strategy = Strategy(name=name, description=description, parameters=parameters)
            db.add(strategy)
            db.flush()

            result = {
                'id': strategy.id,
                'name': strategy.name,
                'description': strategy.description,
                'parameters': strategy.parameters
            }
    except IntegrityError:
        return problem(409, f'A strategy named {name!r} already exists')

    return jsonify(result), 201
