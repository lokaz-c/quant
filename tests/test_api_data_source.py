"""
The data source through the API, against the fake market-data service:
what each run records (data_source, reported_source, per-symbol sources),
what the API returns for it, and that a run is only labelled real when the
service reported Alpaca data for every symbol. Runs on SQLite and, like
tests/test_api.py, on PostgreSQL when one is configured.
"""
import pytest
from sqlalchemy import create_engine

from app.main import create_app
from app.models.database import BacktestRun, get_db
from app.services.backtest_service import BacktestService
from data_sources import sources
from data_sources.sources import DataSourceError
from init_db import init_database
from tests.fake_market_data import FakeMarketData, generated_bars, problem
from tests.postgres import app_bound_to, fresh_postgres_database

URL = 'http://market-data.test'
# Seeded generator output, served under whichever labels a test chooses
BARS = generated_bars(['AAPL', 'MSFT'], '2023-01-01', '2023-12-31')
RUN = {
    'strategy_name': 'Moving Average Crossover',
    'risk_config_name': 'Conservative',
    'start_date': '2023-01-01',
    'end_date': '2023-12-31',
    'initial_capital': 100000,
}


@pytest.fixture(scope='module', params=['sqlite', pytest.param('postgres', marks=pytest.mark.postgres)])
def client(request):
    app = create_app()
    app.testing = True
    if request.param == 'sqlite':
        init_database()
        yield app.test_client()
        return
    with fresh_postgres_database() as url:
        engine = create_engine(url)
        init_database(engine)
        with app_bound_to(engine):
            yield app.test_client()
        engine.dispose()


@pytest.fixture
def market_data(monkeypatch, tmp_path):
    """market-data configured as the default source, served by a fake"""
    fake = FakeMarketData()
    monkeypatch.setenv('MARKET_DATA_URL', URL)
    monkeypatch.setenv('MARKET_DATA_CACHE_DIR', str(tmp_path / 'cache'))
    monkeypatch.setattr(BacktestService, 'client_kwargs',
                        {'transport': fake.transport(), 'sleep': lambda s: None, 'max_retries': 1})
    sources._symbols_memo.clear()
    yield fake
    sources._symbols_memo.clear()


def run(client, symbols, **extra):
    response = client.post('/api/backtest/', json={**RUN, 'symbols': symbols, **extra})
    return response.status_code, response.get_json()


def stored_row(run_id):
    with get_db() as db:
        row = db.query(BacktestRun).filter(BacktestRun.id == run_id).one()
        return row.data_source, row.reported_source, row.symbol_sources, row.price_adjustment


def history_entry(client, run_id):
    return next(r for r in client.get('/api/backtest/list').get_json() if r['id'] == run_id)


def test_data_info_reports_what_the_service_serves(client, market_data):
    market_data.add('S001', 'synthetic', BARS['AAPL'])
    market_data.add('S002', 'synthetic', BARS['MSFT'])
    info = client.get('/api/data').get_json()
    assert (info['source'], info['reported_source'], info['synthetic']) == ('market-data', 'synthetic', True)
    assert info['symbols'] == ['S001', 'S002'] and info['bars'] is None
    assert (info['start_date'], info['end_date']) == ('2023-01-02', '2023-12-29')
    assert info['default_source'] == 'market-data'
    assert info['available_sources'] == ['synthetic', 'market-data']

    local = client.get('/api/data?source=synthetic').get_json()
    assert (local['source'], local['synthetic'], local['bars']) == ('synthetic', True, 1305)
    assert client.get('/api/data?source=yahoo').status_code == 400


def test_service_synthetic_data_is_recorded_and_labelled_synthetic(client, market_data):
    market_data.add('S001', 'synthetic', BARS['AAPL'])
    market_data.add('S002', 'synthetic', BARS['MSFT'])
    status, body = run(client, ['S001', 'S002'])
    assert status == 200, body
    data = body['data']
    assert (data['source'], data['reported_source'], data['synthetic']) == ('market-data', 'synthetic', True)
    assert data['symbol_sources'] == {'S001': 'synthetic', 'S002': 'synthetic'}
    assert data['adjustment'] == 'split'

    run_id = body['backtest_id']
    assert stored_row(run_id) == ('market-data', 'synthetic', {'S001': 'synthetic', 'S002': 'synthetic'}, 'split')
    assert client.get(f'/api/backtest/{run_id}').get_json()['data'] == data
    entry = history_entry(client, run_id)
    assert (entry['data_source'], entry['reported_source'], entry['synthetic']) == (
        'market-data', 'synthetic', True)


def test_alpaca_data_is_the_only_thing_labelled_real(client, market_data):
    market_data.add('AAPL', 'alpaca', BARS['AAPL'])
    market_data.add('MSFT', 'alpaca', BARS['MSFT'])
    status, body = run(client, ['AAPL', 'MSFT'])
    assert status == 200, body
    data = body['data']
    assert (data['reported_source'], data['synthetic']) == ('alpaca', False)
    assert "Alpaca's IEX feed" in data['description']
    assert client.get(f"/api/backtest/{body['backtest_id']}").get_json()['data']['synthetic'] is False
    assert history_entry(client, body['backtest_id'])['synthetic'] is False


def test_one_synthetic_symbol_makes_the_run_mixed_and_not_real(client, market_data):
    market_data.add('AAPL', 'alpaca', BARS['AAPL'])
    market_data.add('S001', 'synthetic', BARS['MSFT'])
    status, body = run(client, ['AAPL', 'S001'])
    assert status == 200, body
    assert (body['data']['reported_source'], body['data']['synthetic']) == ('mixed', True)
    assert stored_row(body['backtest_id'])[1] == 'mixed'


def test_a_baseline_pair_shares_one_fetch_and_one_provenance(client, market_data):
    market_data.add('AAPL', 'alpaca', BARS['AAPL'])
    market_data.add('MSFT', 'alpaca', BARS['MSFT'])
    status, body = run(client, ['AAPL', 'MSFT'], compare_to_baseline=True)
    assert status == 200, body
    assert len(market_data.bar_requests()) == 2   # one per symbol, not one per run
    baseline = client.get(f"/api/backtest/{body['baseline']['backtest_id']}").get_json()
    assert baseline['data'] == body['data']


def test_the_synthetic_file_can_be_requested_when_market_data_is_the_default(client, market_data):
    status, body = run(client, ['AAPL', 'MSFT'], data_source='synthetic')
    assert status == 200, body
    assert body['data']['source'] == 'synthetic' and body['data']['synthetic'] is True
    assert market_data.requests == []


def test_an_unknown_symbol_is_a_400_before_any_bars_are_fetched(client, market_data):
    market_data.add('S001', 'synthetic', BARS['AAPL'])
    status, body = run(client, ['S001', 'AAPL'])
    assert status == 400
    assert 'Unknown symbol(s): AAPL' in body['error'] and 'MARKET_DATA_API_KEY' in body['error']
    assert market_data.bar_requests() == []


def test_market_data_needs_explicit_symbols_and_a_covered_period(client, market_data):
    market_data.add('S001', 'synthetic', BARS['AAPL'])
    response = client.post('/api/backtest/', json=RUN)
    assert response.status_code == 400 and 'symbols is required' in response.get_json()['error']
    status, body = run(client, ['S001'], start_date='2019-01-01', end_date='2019-12-31')
    assert status == 400 and 'No bars between 2019-01-01 and 2019-12-31' in body['error']


def test_a_failing_service_is_a_502_and_nothing_is_stored(client, market_data):
    before = len(client.get('/api/backtest/list?limit=1000').get_json())
    market_data.fail_next = [problem(503, 'Service Unavailable', 'database down', '/v1/symbols')] * 10
    status, body = run(client, ['S001'])
    assert status == 502 and 'database down' in body['error']
    assert len(client.get('/api/backtest/list?limit=1000').get_json()) == before

    market_data.fail_next = [problem(503, 'Service Unavailable', 'database down', '/v1/symbols')] * 10
    assert client.get('/api/data').status_code == 502


def test_regime_analysis_needs_the_synthetic_data(client, market_data):
    body = {k: RUN[k] for k in ('strategy_name', 'risk_config_name', 'initial_capital', 'start_date', 'end_date')}
    body['symbols'] = ['AAPL']
    response = client.post('/api/backtest/regime-analysis', json=body)
    assert response.status_code == 400 and '"data_source": "synthetic"' in response.get_json()['error']
    response = client.post('/api/backtest/regime-analysis', json={**body, 'data_source': 'synthetic'})
    assert response.status_code == 200 and response.get_json()['data']['source'] == 'synthetic'


def test_market_data_cannot_be_requested_when_it_is_not_configured(client):
    status, body = run(client, ['AAPL'], data_source='market-data')
    assert status == 400 and 'not configured' in body['error']


def test_runs_made_before_this_change_read_as_synthetic(client):
    status, body = run(client, ['AAPL'])   # the default without MARKET_DATA_URL
    assert status == 200
    assert stored_row(body['backtest_id']) == ('synthetic', 'synthetic', None, None)
    assert body['data']['synthetic'] is True and body['data']['file'] == 'data/sample_data.csv'


def test_the_app_refuses_to_start_with_a_contradictory_config(monkeypatch):
    monkeypatch.setenv('QUANT_DATA_SOURCE', 'market-data')
    monkeypatch.delenv('MARKET_DATA_URL', raising=False)
    with pytest.raises(DataSourceError, match='needs MARKET_DATA_URL'):
        create_app()
