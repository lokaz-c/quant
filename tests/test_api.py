"""
Flask API tests against a temporary SQLite database seeded from config/*.json
"""
import json
from pathlib import Path

import pytest

from app.main import create_app
from app.services.backtest_service import BacktestService
from init_db import init_database

REPO_ROOT = Path(__file__).resolve().parent.parent

BACKTEST = {
    'strategy_name': 'Trend Following',
    'risk_config_name': 'Conservative',
    'start_date': '2023-01-01',
    'end_date': '2023-12-31',
    'initial_capital': 100000,
    'symbols': ['AAPL', 'MSFT'],
}


@pytest.fixture(scope='module')
def client():
    init_database()
    app = create_app()
    app.testing = True
    return app.test_client()


@pytest.fixture(scope='module')
def completed_run(client):
    response = client.post('/api/backtest/', json=BACKTEST)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def test_health(client):
    assert client.get('/health').get_json() == {'status': 'healthy'}


def test_dashboard_says_the_data_is_synthetic(client):
    page = client.get('/').get_data(as_text=True)
    assert 'Prices are synthetic' in page


def test_seeded_strategies_match_the_engine(client):
    names = {s['name'] for s in client.get('/api/strategies/').get_json()}
    assert names == set(BacktestService().strategy_map)


def test_seeded_risk_profiles_match_config(client):
    with open(REPO_ROOT / 'config' / 'risk_configs.json') as f:
        expected = {c['name']: c for c in json.load(f).values()}
    served = {c['name']: c for c in client.get('/api/risk-configs/').get_json()}
    assert served.keys() == expected.keys()
    for name, config in expected.items():
        for field in ('max_position_size', 'max_portfolio_exposure', 'stop_loss_pct',
                      'take_profit_pct', 'max_drawdown_pct', 'enabled'):
            assert served[name][field] == config[field], (name, field)


def test_run_backtest_labels_the_data_as_synthetic(completed_run):
    assert completed_run['status'] == 'completed'
    assert completed_run['data']['synthetic'] is True
    assert {'total_return', 'sharpe_ratio', 'max_drawdown', 'num_trades'} <= completed_run['metrics'].keys()


def test_stored_run_has_equity_curve_and_trades(client, completed_run):
    run = client.get(f"/api/backtest/{completed_run['backtest_id']}").get_json()
    assert run['symbols'] == BACKTEST['symbols']
    assert len(run['equity_curve']) == 260  # business days in 2023
    assert run['equity_curve'][-1]['equity'] == pytest.approx(completed_run['metrics']['final_equity'])
    assert all(t['status'] == 'closed' for t in run['trades'])
    assert run['data']['synthetic'] is True


def test_missing_field_is_a_400(client):
    body = {k: v for k, v in BACKTEST.items() if k != 'start_date'}
    response = client.post('/api/backtest/', json=body)
    assert response.status_code == 400
    assert 'start_date' in response.get_json()['error']


def test_unknown_backtest_is_a_404(client):
    assert client.get('/api/backtest/999999').status_code == 404


def test_regime_analysis_splits_returns_by_the_generators_labels(client):
    body = {k: BACKTEST[k] for k in ('strategy_name', 'risk_config_name', 'initial_capital',
                                     'symbols', 'start_date', 'end_date')}
    response = client.post('/api/backtest/regime-analysis', json=body)
    assert response.status_code == 200, response.get_json()
    result = response.get_json()
    by_regime = result['by_regime']
    assert by_regime and set(by_regime) <= {'bull', 'bear', 'sideways'}
    # Every daily return after the first bar is attributed to exactly one regime
    assert sum(r['days'] for r in by_regime.values()) == 260 - 1
