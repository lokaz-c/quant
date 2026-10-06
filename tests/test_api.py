"""
Flask API tests, run twice: on a temporary SQLite database and on a fresh
PostgreSQL database (skipped without one; see conftest.py). Both are created
with the Alembic migrations and seeded from config/*.json.
"""
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from app.main import create_app
from app.services.backtest_service import BacktestService
from init_db import init_database
from tests.postgres import app_bound_to, fresh_postgres_database

REPO_ROOT = Path(__file__).resolve().parent.parent

BACKTEST = {
    'strategy_name': 'Trend Following',
    'risk_config_name': 'Conservative',
    'start_date': '2023-01-01',
    'end_date': '2023-12-31',
    'initial_capital': 100000,
    'symbols': ['AAPL', 'MSFT'],
}


@pytest.fixture(scope='module', params=['sqlite', pytest.param('postgres', marks=pytest.mark.postgres)])
def client(request):
    app = create_app()
    app.testing = True
    if request.param == 'sqlite':
        init_database()  # the app's DATABASE_URL: a temporary SQLite file
        yield app.test_client()
        return
    with fresh_postgres_database() as url:
        engine = create_engine(url)
        init_database(engine)
        with app_bound_to(engine):
            yield app.test_client()
        engine.dispose()


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


def test_stored_values_are_json_numbers_and_utc_timestamps(client, completed_run):
    # NUMERIC columns come back as Decimal and TIMESTAMPTZ as aware datetimes;
    # the API returns numbers and ISO 8601 with the UTC offset on both backends
    run = client.get(f"/api/backtest/{completed_run['backtest_id']}").get_json()
    assert isinstance(run['initial_capital'], float)
    assert isinstance(run['metrics']['final_equity'], float)
    point = run['equity_curve'][0]
    assert isinstance(point['equity'], float) and isinstance(point['cash'], float)
    assert point['timestamp'] == '2023-01-02T00:00:00+00:00'
    assert run['created_at'].endswith('+00:00')
    trade = run['trades'][0]
    assert all(isinstance(trade[k], float) for k in ('entry_price', 'exit_price', 'quantity', 'pnl'))
    assert trade['exit_date'].endswith('T00:00:00+00:00')
    assert trade['side'] == 'sell' and trade['status'] == 'closed'


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
