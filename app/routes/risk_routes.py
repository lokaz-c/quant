"""
Risk configuration API routes
"""
from flask import Blueprint, request, jsonify
from app.models.database import get_db, RiskConfig

bp = Blueprint('risk', __name__, url_prefix='/api/risk-configs')


@bp.route('/', methods=['GET'])
def list_risk_configs():
    """List all risk configurations"""
    try:
        with get_db() as db:
            configs = db.query(RiskConfig).all()

            result = [
                {
                    'id': c.id,
                    'name': c.name,
                    'max_position_size': c.max_position_size,
                    'max_portfolio_exposure': c.max_portfolio_exposure,
                    'stop_loss_pct': c.stop_loss_pct,
                    'take_profit_pct': c.take_profit_pct,
                    'max_drawdown_pct': c.max_drawdown_pct,
                    'enabled': c.enabled
                }
                for c in configs
            ]

        return jsonify(result), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/<int:config_id>', methods=['GET'])
def get_risk_config(config_id):
    """Get risk configuration details"""
    try:
        with get_db() as db:
            config = db.query(RiskConfig).filter(RiskConfig.id == config_id).first()

            if not config:
                return jsonify({'error': 'Risk configuration not found'}), 404

            result = {
                'id': config.id,
                'name': config.name,
                'max_position_size': config.max_position_size,
                'max_portfolio_exposure': config.max_portfolio_exposure,
                'stop_loss_pct': config.stop_loss_pct,
                'take_profit_pct': config.take_profit_pct,
                'max_drawdown_pct': config.max_drawdown_pct,
                'enabled': config.enabled
            }

        return jsonify(result), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500
