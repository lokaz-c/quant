"""
Public-deploy protection (app/config.py, app/protection.py): the CORS
allow-list, per-IP rate limits with 429 + Retry-After, the optional API key,
request caps, the per-run time limit and the run slots. Errors are RFC 9457
problem details.

Each test builds its own app with the settings it needs; the rest of the
suite runs with rate limiting off (tests/conftest.py). Most requests here are
cheap 400s or two-day runs: the limiter counts a request whatever its outcome.
"""
import contextlib
import hashlib
import io
import time

import pytest

from app.config import DEFAULT_MAX_RANGE_DAYS, ApiConfig, ConfigError
from app.main import create_app
from app.models.database import BacktestRun, get_db
from backtest_engine.backtester import Backtester, BacktestTimeout
from backtest_engine.data_loader import DataLoader
from backtest_engine.strategies.moving_average import MovingAverageCrossover
from init_db import init_database

KEY = 'test-key-for-tradedesk'
KEY_DIGEST = hashlib.sha256(KEY.encode()).hexdigest()

TWO_BARS = {
    'strategy_name': 'Moving Average Crossover',
    'risk_config_name': 'No Risk Management',
    'start_date': '2023-01-02',
    'end_date': '2023-01-03',
    'initial_capital': 100000,
    'symbols': ['AAPL'],
}
INCOMPLETE = {'strategy_name': 'Moving Average Crossover'}  # a cheap 400


@pytest.fixture(scope='module', autouse=True)
def database():
    with contextlib.redirect_stdout(io.StringIO()):
        init_database()


def make_client(**settings):
    app = create_app(config=ApiConfig(**settings))
    app.testing = True
    return app.test_client()


def post(client, path='/api/backtest/', body=None, ip='203.0.113.1', **headers):
    with contextlib.redirect_stdout(io.StringIO()):
        return client.post(path, json=INCOMPLETE if body is None else body,
                           environ_base={'REMOTE_ADDR': ip}, headers=headers)


def get(client, path='/api/strategies/', ip='203.0.113.1', **headers):
    return client.get(path, environ_base={'REMOTE_ADDR': ip}, headers=headers)


def assert_problem(response, status):
    assert response.status_code == status
    assert response.mimetype == 'application/problem+json'
    body = response.get_json()
    assert body['status'] == status and body['detail'] == body['error'] and body['title']
    return body


# --- configuration ---------------------------------------------------------

def test_defaults_from_an_empty_environment():
    config = ApiConfig.from_env({})
    assert config.cors_origins == () and config.api_key_digests == ()
    assert config.rate_limits_enabled and config.run_limit == '5 per minute;30 per hour'
    assert config.read_limit == '120 per minute' and config.rate_limit_storage == 'memory://'
    assert (config.max_symbols, config.max_range_days) == (10, DEFAULT_MAX_RANGE_DAYS)
    assert config.backtest_timeout_seconds == 90 and config.max_concurrent_runs == 1


def test_settings_are_read_and_normalised():
    config = ApiConfig.from_env({
        'QUANT_CORS_ORIGINS': 'https://lorenzokamanzi.com, https://cf-ai-tradedesk.pages.dev/',
        'QUANT_API_KEY_SHA256': f'{KEY_DIGEST.upper()},{"0" * 64}',
        'QUANT_CLIENT_IP_HEADER': 'CF-Connecting-IP',
        'QUANT_RATE_LIMIT_RUNS': '2 per minute',
        'QUANT_BACKTEST_TIMEOUT_SECONDS': '30',
        'QUANT_MAX_SYMBOLS': '3',
        'QUANT_RATE_LIMITS': 'off',
    })
    assert config.cors_origins == ('https://lorenzokamanzi.com', 'https://cf-ai-tradedesk.pages.dev')
    assert config.api_key_digests[0] == bytes.fromhex(KEY_DIGEST)
    assert config.client_ip_header == 'CF-Connecting-IP' and not config.rate_limits_enabled
    assert (config.run_limit, config.backtest_timeout_seconds, config.max_symbols) == ('2 per minute', 30.0, 3)


@pytest.mark.parametrize('env', [
    {'QUANT_CORS_ORIGINS': '*'},
    {'QUANT_CORS_ORIGINS': 'lorenzokamanzi.com'},
    {'QUANT_CORS_ORIGINS': 'https://lorenzokamanzi.com/app'},
    {'QUANT_API_KEY_SHA256': 'not-a-digest'},
    {'QUANT_API_KEY_SHA256': KEY},  # the key itself instead of its digest
    {'QUANT_RATE_LIMIT_RUNS': 'lots'},
    {'QUANT_BACKTEST_TIMEOUT_SECONDS': '0'},
    {'QUANT_BACKTEST_TIMEOUT_SECONDS': 'nan'},
    {'QUANT_MAX_SYMBOLS': 'ten'},
    {'QUANT_RATE_LIMITS': 'maybe'},
], ids=lambda env: '-'.join(f'{k}={v}' for k, v in env.items()))
def test_bad_settings_fail_at_startup(env):
    with pytest.raises(ConfigError):
        ApiConfig.from_env(env)


# --- CORS --------------------------------------------------------------------

def test_no_cors_headers_by_default():
    response = get(make_client(), Origin='https://example.com')
    assert response.status_code == 200
    assert 'Access-Control-Allow-Origin' not in response.headers


def test_cors_allows_only_listed_origins():
    client = make_client(cors_origins=('https://lorenzokamanzi.com',))
    allowed = get(client, Origin='https://lorenzokamanzi.com')
    assert allowed.headers['Access-Control-Allow-Origin'] == 'https://lorenzokamanzi.com'
    for origin in ('https://example.com', 'https://lorenzokamanzi.com.evil.example', 'http://lorenzokamanzi.com'):
        assert 'Access-Control-Allow-Origin' not in get(client, Origin=origin).headers, origin


def test_cors_preflight_for_a_listed_origin():
    client = make_client(cors_origins=('https://lorenzokamanzi.com',))
    response = client.options('/api/backtest/', headers={
        'Origin': 'https://lorenzokamanzi.com', 'Access-Control-Request-Method': 'POST',
        'Access-Control-Request-Headers': 'Content-Type'})
    assert response.status_code == 200
    assert response.headers['Access-Control-Allow-Origin'] == 'https://lorenzokamanzi.com'
    assert 'POST' in response.headers['Access-Control-Allow-Methods']
    assert 'content-type' in response.headers['Access-Control-Allow-Headers'].lower()


# --- rate limits ---------------------------------------------------------------

def test_run_limit_gives_429_with_retry_after_and_a_problem_body():
    client = make_client(run_limit='2 per minute')
    assert [post(client).status_code for _ in range(2)] == [400, 400]  # counted whatever the outcome
    response = post(client)
    body = assert_problem(response, 429)
    assert body['title'] == 'Too Many Requests' and body['instance'] == '/api/backtest/'
    retry_after = int(response.headers['Retry-After'])
    assert 1 <= retry_after <= 60
    assert f'Retry in {retry_after} s' in body['detail'] and '2 per 1 minute' in body['detail']


def test_run_limit_is_per_client_address():
    client = make_client(run_limit='1 per minute')
    assert post(client, ip='203.0.113.1').status_code == 400
    assert post(client, ip='203.0.113.1').status_code == 429
    assert post(client, ip='203.0.113.2').status_code == 400


def test_run_endpoints_share_one_limit_and_reads_have_their_own():
    client = make_client(run_limit='2 per minute', read_limit='100 per minute')
    assert post(client, '/api/backtest/').status_code == 400
    assert post(client, '/api/backtest/regime-analysis').status_code == 400
    assert post(client, '/api/strategies/', body={}).status_code == 429  # third write
    # reads are still allowed, and /health and the frontend are never limited
    assert get(client).status_code == 200
    assert get(client, '/health').status_code == 200


def test_read_limit_is_looser_but_enforced():
    client = make_client(run_limit='1 per minute', read_limit='3 per minute')
    assert [get(client).status_code for _ in range(4)] == [200, 200, 200, 429]
    assert [get(client, '/health').status_code for _ in range(5)] == [200] * 5


def test_client_ip_header_is_used_only_when_configured():
    spoofing = make_client(run_limit='1 per minute')
    assert post(spoofing, **{'CF-Connecting-IP': '198.51.100.1'}).status_code == 400
    # without the setting the header is ignored: a new value doesn't give a new bucket
    assert post(spoofing, **{'CF-Connecting-IP': '198.51.100.2'}).status_code == 429

    behind_proxy = make_client(run_limit='1 per minute', client_ip_header='CF-Connecting-IP')
    assert post(behind_proxy, **{'CF-Connecting-IP': '198.51.100.1'}).status_code == 400
    assert post(behind_proxy, **{'CF-Connecting-IP': '198.51.100.1'}).status_code == 429
    assert post(behind_proxy, **{'CF-Connecting-IP': '198.51.100.2'}).status_code == 400


def test_rate_limits_can_be_switched_off():
    client = make_client(run_limit='1 per minute', rate_limits_enabled=False)
    assert [post(client).status_code for _ in range(3)] == [400, 400, 400]


# --- API key -----------------------------------------------------------------------

def test_valid_api_key_lifts_the_rate_limits():
    client = make_client(run_limit='1 per minute', read_limit='1 per minute',
                         api_key_digests=(bytes.fromhex(KEY_DIGEST),))
    assert [post(client, **{'X-API-Key': KEY}).status_code for _ in range(4)] == [400] * 4
    assert [get(client, **{'X-API-Key': KEY}).status_code for _ in range(3)] == [200] * 3
    # the same address without the key is limited as usual
    assert post(client).status_code == 400 and post(client).status_code == 429


def test_valid_api_key_still_gets_the_request_caps():
    client = make_client(api_key_digests=(bytes.fromhex(KEY_DIGEST),), max_symbols=1)
    response = post(client, body={**TWO_BARS, 'symbols': ['AAPL', 'MSFT']}, **{'X-API-Key': KEY})
    assert 'at most 1 symbols' in assert_problem(response, 400)['detail']


@pytest.mark.parametrize('digests', [(bytes.fromhex(KEY_DIGEST),), ()], ids=['wrong-key', 'no-keys-configured'])
def test_wrong_api_key_is_a_401(digests):
    client = make_client(api_key_digests=digests)
    key = 'not-the-key' if digests else KEY
    body = assert_problem(get(client, **{'X-API-Key': key}), 401)
    assert 'X-API-Key' in body['detail']
    assert get(client).status_code == 200  # no key: an ordinary anonymous request


# --- request caps -----------------------------------------------------------------

def test_data_endpoint_reports_the_caps():
    info = get(make_client(max_symbols=4, max_range_days=400, backtest_timeout_seconds=30.0), '/api/data').get_json()
    assert info['limits'] == {'max_symbols': 4, 'max_range_days': 400, 'timeout_seconds': 30.0}


@pytest.mark.parametrize('change, message', [
    ({'symbols': ['AAPL', 'AMZN', 'GOOGL', 'JPM']}, 'at most 3 symbols per run, got 4'),
    ({'symbols': None}, 'without symbols the run would use every one in the file'),
    ({'start_date': '2023-01-01', 'end_date': '2023-01-31'}, 'The period is 31 days; this server allows at most 30'),
    ({'symbols': ['A' * 21]}, 'Each symbol must be 1 to 20 characters'),
    ({'market_regime': 'x' * 51}, 'market_regime must be text of at most 50 characters'),
    ({'parameters': {'fast_period': 1}}, 'fast_period must be between 2 and 200'),
    ({'parameters': {'slow_period': 401}}, 'slow_period must be between 3 and 400'),
    ({'initial_capital': 2e12}, 'at most 1,000,000,000,000'),
], ids=['symbols', 'all-symbols', 'range', 'symbol-length', 'regime-label', 'parameter-low', 'parameter-high',
        'capital'])
def test_requests_over_the_caps_are_400s(change, message):
    client = make_client(max_symbols=3, max_range_days=30)
    body = {k: v for k, v in {**TWO_BARS, **change}.items() if v is not None}
    assert message in assert_problem(post(client, body=body), 400)['detail']


def test_a_request_at_the_caps_runs():
    client = make_client(max_symbols=2, max_range_days=30)
    body = {**TWO_BARS, 'symbols': ['AAPL', 'MSFT'], 'start_date': '2023-01-02', 'end_date': '2023-01-31'}
    assert post(client, body=body).status_code == 200


def test_body_over_64_kib_is_a_413():
    response = post(make_client(), body={**TWO_BARS, 'padding': 'x' * 70_000})
    assert_problem(response, 413)


@pytest.mark.parametrize('limit', [0, 501])
def test_list_limit_is_bounded(limit):
    assert_problem(get(make_client(), f'/api/backtest/list?limit={limit}'), 400)


def test_strategy_records_are_validated_and_names_unique():
    client = make_client()
    assert_problem(post(client, '/api/strategies/', body={'name': 'x' * 256}), 400)
    assert_problem(post(client, '/api/strategies/', body={'name': 'Big', 'parameters': {str(i): i for i in range(51)}}), 400)
    name = f'Stored record {time.time_ns()}'
    assert post(client, '/api/strategies/', body={'name': name}).status_code == 201
    assert 'already exists' in assert_problem(post(client, '/api/strategies/', body={'name': name}), 409)['detail']


# --- time limit and run slots ----------------------------------------------------

def test_engine_stops_at_its_deadline():
    def run(deadline):
        with contextlib.redirect_stdout(io.StringIO()):
            return Backtester(MovingAverageCrossover(), DataLoader('data/sample_data.csv'), 100000.0,
                              start_date='2023-01-01', end_date='2023-03-31', symbols=['AAPL'],
                              deadline=deadline).run()
    with pytest.raises(BacktestTimeout, match='stopped after 0 of 65 bars'):
        run(time.monotonic() - 1)
    assert len(run(time.monotonic() + 600)['equity_curve']) == 65  # business days in 2023 Q1


def test_run_past_the_time_limit_is_a_504_and_stored_as_failed():
    client = make_client(backtest_timeout_seconds=0.0)
    response = post(client, body=TWO_BARS)
    body = assert_problem(response, 504)
    assert "this server's 0 s limit" in body['detail'] and 'stopped after 0 of 2 bars' in body['detail']
    with get_db() as db:
        newest = db.query(BacktestRun).order_by(BacktestRun.id.desc()).first()
        assert newest.status == 'failed'


def test_every_run_slot_taken_is_a_503_with_retry_after():
    client = make_client(max_concurrent_runs=1)
    slots = client.application.extensions['quant_run_slots']
    assert slots.acquire(blocking=False)  # a run in progress
    try:
        response = post(client, body=TWO_BARS)
        assert_problem(response, 503)
        assert response.headers['Retry-After'] == '10'
    finally:
        slots.release()
    assert post(client, body=TWO_BARS).status_code == 200


# --- problem details for Flask's own errors ---------------------------------------

def test_unknown_api_route_and_wrong_method_are_problems():
    client = make_client()
    assert assert_problem(get(client, '/api/nope'), 404)['instance'] == '/api/nope'
    response = client.delete('/api/backtest/list')
    assert_problem(response, 405)
    assert 'GET' in response.headers['Allow']


def test_non_json_body_is_a_problem():
    client = make_client()
    response = client.post('/api/backtest/', data='strategy=x', content_type='text/plain')
    assert assert_problem(response, 400)['detail'] == 'Expected a JSON object'
