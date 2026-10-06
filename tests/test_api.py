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


def test_data_endpoint_labels_the_data_and_lists_symbols(client):
    info = client.get('/api/data').get_json()
    assert info['synthetic'] is True
    assert len(info['symbols']) == 25 and {'AAPL', 'MSFT'} <= set(info['symbols'])
    assert (info['start_date'], info['end_date'], info['bars']) == ('2020-01-01', '2024-12-31', 1305)


def test_strategies_include_parameter_limits(client):
    by_name = {s['name']: s for s in client.get('/api/strategies/').get_json()}
    limits = by_name['Moving Average Crossover']['parameter_limits']
    assert limits['fast_period'] == {'type': 'int', 'min': 2, 'max': 200}
    for strategy in by_name.values():
        assert set(strategy['parameter_limits']) == set(strategy['parameters'])


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


def test_parameter_overrides_are_used_and_stored(client):
    body = {**BACKTEST, 'strategy_name': 'Moving Average Crossover', 'risk_config_name': 'No Risk Management'}
    default = client.post('/api/backtest/', json=body).get_json()
    faster = client.post('/api/backtest/', json={**body, 'parameters': {'fast_period': 5, 'slow_period': 15}}).get_json()
    assert faster['metrics'] != default['metrics']
    stored = client.get(f"/api/backtest/{faster['backtest_id']}").get_json()
    assert stored['strategy_parameters'] == {'fast_period': 5, 'slow_period': 15}
    stored_default = client.get(f"/api/backtest/{default['backtest_id']}").get_json()
    assert stored_default['strategy_parameters'] == {'fast_period': 20, 'slow_period': 50}


@pytest.mark.parametrize('change, message', [
    ({'parameters': {'lookback': 10}}, 'Unknown parameter'),
    ({'parameters': {'lookback_period': 1}}, 'between 2 and 250'),
    ({'parameters': {'lookback_period': 10.5}}, 'whole number'),
    ({'parameters': {'atr_multiplier': 'two'}}, 'must be a number'),
    ({'parameters': [20]}, 'must be an object'),
    ({'strategy_name': 'Moving Average Crossover', 'parameters': {'fast_period': 60}},
     'fast_period must be less than slow_period'),
    ({'strategy_name': 'Buy the Dip'}, 'Strategy not found'),
    ({'risk_config_name': 'Reckless'}, 'Risk configuration not found'),
    ({'start_date': '2023-13-01'}, 'YYYY-MM-DD'),
    ({'start_date': '2023-06-01', 'end_date': '2023-05-01'}, 'must not be after'),
    ({'start_date': '2030-01-01', 'end_date': '2030-12-31'}, 'No bars between'),
    ({'start_date': '2023-01-07', 'end_date': '2023-01-08'}, 'No bars between'),  # a weekend
    ({'symbols': ['AAPL', 'NOPE']}, 'Unknown symbol(s): NOPE'),
    ({'symbols': []}, 'non-empty list'),
    ({'initial_capital': 0}, 'initial_capital must be above 0'),
    ({'initial_capital': 'lots'}, 'initial_capital must be a number'),
], ids=lambda value: value if isinstance(value, str) else None)
def test_invalid_requests_are_400s_with_the_reason(client, change, message):
    before = len(client.get('/api/backtest/list?limit=500').get_json())
    response = client.post('/api/backtest/', json={**BACKTEST, **change})
    assert response.status_code == 400
    assert message in response.get_json()['error']
    # rejected before a run row is created
    assert len(client.get('/api/backtest/list?limit=500').get_json()) == before


def test_non_json_body_is_a_400(client):
    response = client.post('/api/backtest/', data='strategy=x', content_type='text/plain')
    assert response.status_code == 400


def test_compare_to_baseline_runs_and_links_the_unmanaged_run(client):
    response = client.post('/api/backtest/', json={**BACKTEST, 'compare_to_baseline': True})
    assert response.status_code == 200, response.get_json()
    run = response.get_json()
    baseline = run['baseline']
    assert baseline['risk_config'] == 'No Risk Management'

    stored = client.get(f"/api/backtest/{run['backtest_id']}").get_json()
    stored_baseline = client.get(f"/api/backtest/{baseline['backtest_id']}").get_json()
    assert stored['baseline_run_id'] == baseline['backtest_id']
    assert stored_baseline['baseline_run_id'] is None
    assert stored_baseline['risk_config'] == 'No Risk Management'
    for field in ('strategy', 'start_date', 'end_date', 'symbols', 'initial_capital', 'strategy_parameters'):
        assert stored_baseline[field] == stored[field], field
    assert baseline['metrics']['final_equity'] == pytest.approx(stored_baseline['metrics']['final_equity'])

    listed = {r['id']: r for r in client.get('/api/backtest/list').get_json()}
    assert listed[run['backtest_id']]['baseline_run_id'] == baseline['backtest_id']
    assert listed[run['backtest_id']]['symbols'] == BACKTEST['symbols']


def test_compare_to_baseline_is_ignored_when_the_risk_layer_is_already_off(client):
    body = {**BACKTEST, 'risk_config_name': 'No Risk Management', 'compare_to_baseline': True}
    run = client.post('/api/backtest/', json=body).get_json()
    assert run['baseline'] is None


def test_frontend_is_served_from_the_build_directory(tmp_path):
    (tmp_path / 'assets').mkdir()
    (tmp_path / 'index.html').write_text('<!doctype html><div id="root"></div>')
    (tmp_path / 'assets' / 'index-abc123.js').write_text('console.log(1)')
    (tmp_path / 'favicon.svg').write_text('<svg/>')
    client = create_app(frontend_dist=tmp_path).test_client()

    index = client.get('/')
    assert index.status_code == 200 and 'id="root"' in index.get_data(as_text=True)
    assert index.headers['Cache-Control'] == 'no-cache'
    asset = client.get('/assets/index-abc123.js')
    assert asset.status_code == 200 and 'immutable' in asset.headers['Cache-Control']
    assert client.get('/favicon.svg').status_code == 200
    assert client.get('/nope.txt').status_code == 404
    assert client.get('/health').get_json() == {'status': 'healthy'}


def test_missing_frontend_build_is_a_503_that_says_how_to_build(tmp_path):
    response = create_app(frontend_dist=tmp_path / 'missing').test_client().get('/')
    assert response.status_code == 503
    assert 'make frontend' in response.get_data(as_text=True)


def test_unexpected_errors_are_500s_without_internals(client, monkeypatch):
    def broken(self, **kwargs):
        raise RuntimeError('(sqlite3.OperationalError) INSERT INTO backtest_runs ...')
    monkeypatch.setattr(BacktestService, 'list_backtests', broken)
    response = client.get('/api/backtest/list')
    assert response.status_code == 500
    assert 'INSERT' not in response.get_json()['error']


def test_comparing_an_unknown_run_is_a_404(client, completed_run):
    response = client.post('/api/backtest/compare',
                           json={'baseline_id': completed_run['backtest_id'], 'comparison_id': 999999})
    assert response.status_code == 404


def test_regime_analysis_with_unknown_symbols_is_a_400(client):
    body = {'strategy_name': 'Trend Following', 'initial_capital': 100000, 'symbols': ['NOPE']}
    assert client.post('/api/backtest/regime-analysis', json=body).status_code == 400
