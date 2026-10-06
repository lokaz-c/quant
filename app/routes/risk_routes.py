"""
Risk configuration API routes
"""
from flask import Blueprint, jsonify
from app.routes.errors import api_errors, problem
from app.models.database import get_db, RiskConfig

bp = Blueprint('risk', __name__, url_prefix='/api/risk-configs')


def _profile(config: RiskConfig) -> dict:
    return {
        'id': config.id,
        'name': config.name,
        'max_position_size': config.max_position_size,
        'max_portfolio_exposure': config.max_portfolio_exposure,
        'stop_loss_pct': config.stop_loss_pct,
        'take_profit_pct': config.take_profit_pct,
        'max_drawdown_pct': config.max_drawdown_pct,
        'enabled': config.enabled
    }


@bp.route('/', methods=['GET'])
@api_errors
def list_risk_configs():
    """List all risk configurations"""
    with get_db() as db:
        result = [_profile(c) for c in db.query(RiskConfig).all()]
    return jsonify(result), 200


@bp.route('/<int:config_id>', methods=['GET'])
@api_errors
def get_risk_config(config_id):
    """Get risk configuration details"""
    with get_db() as db:
        config = db.query(RiskConfig).filter(RiskConfig.id == config_id).first()
        if not config:
            return problem(404, 'Risk configuration not found')
        result = _profile(config)
    return jsonify(result), 200
