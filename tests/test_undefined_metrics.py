"""
Undefined metrics through the API, on SQLite and PostgreSQL: null with the
reason in `undefined_metrics`, never NaN or Infinity, in every response that
carries metrics, and NULL in the database.

Two runs on the synthetic file produce them:
- two bars (one daily return): no volatility or Sharpe, and no closed trades;
- Trend Following on AAPL over the first half of 2023: one closed trade, a
  winner, so no losing trade for the profit factor or the average loss.
"""
import contextlib
import io
import json

import pytest
from sqlalchemy import create_engine

from app.main import create_app
from app.models.database import BacktestMetrics, get_db
from app.services.backtest_service import REASON_NOT_RECORDED
from init_db import init_database
from tests.postgres import app_bound_to, fresh_postgres_database

TWO_BARS = {
    'strategy_name': 'Moving Average Crossover',
    'risk_config_name': 'No Risk Management',
    'start_date': '2023-01-02',
    'end_date': '2023-01-03',
    'initial_capital': 100000,
    'symbols': ['AAPL'],
}
NO_LOSERS = {**TWO_BARS, 'strategy_name': 'Trend Following', 'start_date': '2023-01-01', 'end_date': '2023-06-30'}


def strict_json(text):
    """JSON.parse's view: NaN and Infinity are syntax errors"""
    def reject(token):
        raise AssertionError(f'{token} in the response')
    return json.loads(text, parse_constant=reject)


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


def post(client, body):
    with contextlib.redirect_stdout(io.StringIO()):
        response = client.post('/api/backtest/', json=body)
    assert response.status_code == 200, response.get_data(as_text=True)
    return strict_json(response.get_data(as_text=True))


def get(client, path):
    response = client.get(path)
    assert response.status_code == 200, response.get_data(as_text=True)
    return strict_json(response.get_data(as_text=True))


@pytest.fixture(scope='module')
def two_bars(client):
    return post(client, TWO_BARS)


@pytest.fixture(scope='module')
def no_losers(client):
    return post(client, NO_LOSERS)


def nulls(metrics):
    return {k for k, v in metrics.items() if v is None}


def test_one_daily_return_leaves_volatility_and_sharpe_null_with_the_reason(two_bars):
    metrics, reasons = two_bars['metrics'], two_bars['undefined_metrics']
    assert metrics['volatility'] is None and metrics['sharpe_ratio'] is None
    assert reasons['volatility'] == reasons['sharpe_ratio'] == 'fewer than two daily returns'
    for key in ('win_rate', 'avg_win', 'avg_loss', 'profit_factor'):
        assert metrics[key] is None and reasons[key] == 'no closed trades'
    # defined metrics stay numbers
    assert metrics['max_drawdown'] == 0.0 and metrics['num_trades'] == 0
    assert set(reasons) == nulls(metrics)


def test_no_losing_trade_makes_profit_factor_null_not_infinity(no_losers):
    metrics, reasons = no_losers['metrics'], no_losers['undefined_metrics']
    assert metrics['num_trades'] > 0 and metrics['win_rate'] == 100.0
    assert metrics['profit_factor'] is None and reasons['profit_factor'] == 'no losing trades'
    assert metrics['avg_loss'] is None and reasons['avg_loss'] == 'no losing trades'
    assert metrics['avg_win'] > 0 and isinstance(metrics['sharpe_ratio'], float)
    assert set(reasons) == nulls(metrics)


def test_database_stores_null_and_the_reasons(two_bars):
    with get_db() as db:
        row = db.query(BacktestMetrics).filter(BacktestMetrics.backtest_run_id == two_bars['backtest_id']).one()
        assert row.volatility is None and row.sharpe_ratio is None and row.win_rate is None
        assert row.undefined_metrics['sharpe_ratio'] == 'fewer than two daily returns'
        assert row.undefined_metrics['profit_factor'] == 'no closed trades'  # not a column, still recorded


def test_stored_run_returns_null_with_the_reason(client, two_bars):
    run = get(client, f"/api/backtest/{two_bars['backtest_id']}")
    assert run['metrics']['sharpe_ratio'] is None
    assert run['undefined_metrics'] == {
        'volatility': 'fewer than two daily returns',
        'sharpe_ratio': 'fewer than two daily returns',
        'win_rate': 'no closed trades',
        'avg_win': 'no closed trades',
        'avg_loss': 'no closed trades',
    }  # only the stored metrics: there is no profit factor column


def test_run_list_gives_the_reason_for_a_null_sharpe(client, two_bars, no_losers):
    listed = {r['id']: r for r in get(client, '/api/backtest/list?limit=500')}
    row = listed[two_bars['backtest_id']]
    assert row['sharpe_ratio'] is None
    assert row['undefined_metrics'] == {'sharpe_ratio': 'fewer than two daily returns'}
    assert listed[no_losers['backtest_id']]['undefined_metrics'] == {}


def test_compare_gives_null_differences_with_the_reason(client, two_bars, no_losers):
    response = client.post('/api/backtest/compare', json={'baseline_id': no_losers['backtest_id'],
                                                          'comparison_id': two_bars['backtest_id']})
    assert response.status_code == 200
    result = strict_json(response.get_data(as_text=True))
    assert result['differences']['sharpe_ratio_diff'] is None
    assert result['undefined_differences']['sharpe_ratio_diff'] == 'sharpe_ratio is undefined for the comparison run'
    assert isinstance(result['differences']['total_return_diff'], float)
    assert result['comparison']['undefined_metrics']['sharpe_ratio'] == 'fewer than two daily returns'


def test_compare_against_a_baseline_with_no_drawdown_is_null_not_zero(client, two_bars, no_losers):
    # the two-bar run never trades, so it has no drawdown to improve on
    result = client.post('/api/backtest/compare', json={'baseline_id': two_bars['backtest_id'],
                                                        'comparison_id': no_losers['backtest_id']}).get_json()
    assert result['differences']['drawdown_improvement_pct'] is None
    assert result['undefined_differences']['drawdown_improvement_pct'] == 'the baseline run had no drawdown'


def test_baseline_pair_carries_reasons_for_both_runs(client):
    body = {**NO_LOSERS, 'risk_config_name': 'Conservative', 'compare_to_baseline': True}
    run = post(client, body)
    assert set(run['undefined_metrics']) == nulls(run['metrics'])
    assert set(run['baseline']['undefined_metrics']) == nulls(run['baseline']['metrics'])


def test_regime_entries_carry_undefined_metrics(client):
    response = client.post('/api/backtest/regime-analysis', json={**TWO_BARS, 'data_source': 'synthetic'})
    assert response.status_code == 200
    result = strict_json(response.get_data(as_text=True))
    assert result['undefined_metrics']['sharpe_ratio'] == 'fewer than two daily returns'
    (regime,) = result['by_regime'].values()  # one return, so one regime
    assert regime['days'] == 1 and regime['annualized_volatility_pct'] is None
    assert regime['undefined_metrics'] == {'annualized_volatility_pct': 'fewer than two daily returns'}


def test_null_stored_before_reasons_were_recorded_says_so(client, two_bars):
    run = post(client, TWO_BARS)
    with get_db() as db:
        row = db.query(BacktestMetrics).filter(BacktestMetrics.backtest_run_id == run['backtest_id']).one()
        row.undefined_metrics = None   # as migration 0005 leaves older rows
    stored = get(client, f"/api/backtest/{run['backtest_id']}")
    assert stored['undefined_metrics']['sharpe_ratio'] == REASON_NOT_RECORDED
    assert set(stored['undefined_metrics']) == nulls(stored['metrics'])
