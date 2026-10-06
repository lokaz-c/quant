"""
The app's JSON provider refuses NaN and infinities in both directions
(app/strict_json.py): a response that would carry one is a 500, and a request
body with one is a 400. So a regression to bare NaN/Infinity output fails
the tests instead of reaching a client.
"""
import json

import pytest

from app.main import create_app
from app.services.backtest_service import BacktestService

BACKTEST = {
    'strategy_name': 'Trend Following',
    'risk_config_name': 'Conservative',
    'start_date': '2023-01-01',
    'end_date': '2023-03-31',
    'initial_capital': 100000,
    'symbols': ['AAPL'],
}


@pytest.fixture
def app():
    app = create_app()
    app.testing = True
    return app


@pytest.mark.parametrize('value', [float('nan'), float('inf'), float('-inf')])
def test_dumps_refuses_non_finite_floats(app, value):
    with pytest.raises(ValueError):
        app.json.dumps({'profit_factor': value})


def test_dumps_keeps_field_order_and_null(app):
    assert app.json.dumps({'b': None, 'a': 1.5}) == '{"b": null, "a": 1.5}'


@pytest.mark.parametrize('text', ['{"x": NaN}', '{"x": Infinity}', '{"x": -Infinity}', '{"x": 1e400}'])
def test_loads_refuses_non_finite_input(app, text):
    with pytest.raises(ValueError):
        app.json.loads(text)


def test_loads_accepts_ordinary_numbers(app):
    assert app.json.loads('{"x": 1e300, "y": -2.5, "z": 3}') == {'x': 1e300, 'y': -2.5, 'z': 3}


def body_with(token, parameter=None):
    """BACKTEST as JSON text with the capital, or a parameter override, set to a raw token"""
    data = ({**BACKTEST, 'initial_capital': '__TOKEN__'} if parameter is None
            else {**BACKTEST, 'parameters': {parameter: '__TOKEN__'}})
    return json.dumps(data).replace('"__TOKEN__"', token)


@pytest.mark.parametrize('token', ['NaN', 'Infinity', '-Infinity', '1e400'])
def test_request_with_a_non_finite_capital_is_a_400(app, token):
    response = app.test_client().post('/api/backtest/', data=body_with(token), content_type='application/json')
    # refused by the parser, before any validation
    assert response.status_code == 400 and response.get_json()['error'] == 'Expected a JSON object'


def test_non_finite_parameter_override_is_a_400(app):
    body = body_with('Infinity', parameter='atr_multiplier')
    response = app.test_client().post('/api/backtest/', data=body, content_type='application/json')
    assert response.status_code == 400 and response.get_json()['error'] == 'Expected a JSON object'


def test_a_response_with_infinity_is_a_500_not_invalid_json(app, monkeypatch, caplog):
    def leaky(self, **kwargs):
        return {'backtest_id': 1, 'metrics': {'profit_factor': float('inf')}}
    monkeypatch.setattr(BacktestService, 'run_backtest', leaky)
    response = app.test_client().post('/api/backtest/', json=BACKTEST)
    assert response.status_code == 500
    assert 'Infinity' not in response.get_data(as_text=True)
    assert 'Out of range float values are not JSON compliant' in caplog.text
