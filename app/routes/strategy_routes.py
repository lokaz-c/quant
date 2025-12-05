"""
Strategy API routes
"""
from flask import Blueprint, request, jsonify
from app.models.database import get_db, Strategy

bp = Blueprint('strategy', __name__, url_prefix='/api/strategies')


@bp.route('/', methods=['GET'])
def list_strategies():
    """List all available strategies"""
    try:
        with get_db() as db:
            strategies = db.query(Strategy).all()

            result = [
                {
                    'id': s.id,
                    'name': s.name,
                    'description': s.description,
                    'parameters': s.parameters
                }
                for s in strategies
            ]

        return jsonify(result), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/<int:strategy_id>', methods=['GET'])
def get_strategy(strategy_id):
    """Get strategy details"""
    try:
        with get_db() as db:
            strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()

            if not strategy:
                return jsonify({'error': 'Strategy not found'}), 404

            result = {
                'id': strategy.id,
                'name': strategy.name,
                'description': strategy.description,
                'parameters': strategy.parameters,
                'created_at': strategy.created_at.isoformat()
            }

        return jsonify(result), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/', methods=['POST'])
def create_strategy():
    """
    Create a new strategy

    Expected JSON:
    {
        "name": "My Custom Strategy",
        "description": "Description here",
        "parameters": {"param1": value1}
    }
    """
    try:
        data = request.get_json()

        if 'name' not in data:
            return jsonify({'error': 'Missing required field: name'}), 400

        with get_db() as db:
            strategy = Strategy(
                name=data['name'],
                description=data.get('description'),
                parameters=data.get('parameters', {})
            )
            db.add(strategy)
            db.flush()

            result = {
                'id': strategy.id,
                'name': strategy.name,
                'description': strategy.description,
                'parameters': strategy.parameters
            }

        return jsonify(result), 201

    except Exception as e:
        return jsonify({'error': str(e)}), 500
