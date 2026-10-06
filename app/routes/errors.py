"""
Error responses shared by the routes: RFC 9457 problem details.

Every error from /api is `application/problem+json`:

    {"title": "Bad Request", "status": 400, "detail": "Unknown symbol(s): NOPE",
     "instance": "/api/backtest/", "error": "Unknown symbol(s): NOPE"}

`type` is left out, which RFC 9457 reads as "about:blank": the status code
says what kind of problem it is. `error` repeats `detail` for clients written
against the earlier `{"error": ...}` bodies (the frontend, TradeDesk).
"""
from functools import wraps
from typing import Mapping, Optional

from flask import current_app, request
from werkzeug.exceptions import HTTPException
from werkzeug.http import HTTP_STATUS_CODES

from app.services.backtest_service import DataSourceUnavailable, InvalidRequest, RunNotFound
from backtest_engine.backtester import BacktestTimeout


class RunsBusy(RuntimeError):
    """Every slot for a running backtest is taken (app/protection.py). 503."""

    retry_after = 10


def problem(status: int, detail: str, headers: Optional[Mapping[str, str]] = None):
    body = {
        'title': HTTP_STATUS_CODES.get(status, 'Error'),
        'status': status,
        'detail': detail,
        'instance': request.path,
        'error': detail,
    }
    response = current_app.json.response(body)
    response.status_code = status
    response.mimetype = 'application/problem+json'
    for name, value in (headers or {}).items():
        response.headers[name] = value
    return response


def server_error():
    """
    Log the exception being handled and return a 500 without its message:
    exception text can include SQL statements and their parameters, which
    the frontend would otherwise show to the user.
    """
    current_app.logger.exception('Unhandled error')
    return problem(500, 'Internal server error; the details are in the server log')


def bad_gateway(error: Exception):
    """
    502 for a failure of the market-data service (down, timing out, rate
    limiting past the retries, or answering outside its contract). The
    message is the client's, which names the service and its status but
    never the API key (that only travels in a header).
    """
    current_app.logger.warning('market-data failed: %s', error)
    return problem(502, f'The market-data service failed: {error}')


def api_errors(view):
    """
    Map the service's exceptions to responses, so each route only has the
    success path. HTTP errors raised by Flask itself (413, 415, ...) pass
    through to http_error below.
    """
    @wraps(view)
    def wrapper(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except HTTPException:
            raise
        except InvalidRequest as e:
            return problem(400, str(e))
        except RunNotFound as e:
            return problem(404, str(e))
        except DataSourceUnavailable as e:
            return bad_gateway(e)
        except RunsBusy:
            return problem(503, 'The server is already running as many backtests as it allows at once; '
                                f'retry in {RunsBusy.retry_after} s',
                           {'Retry-After': str(RunsBusy.retry_after)})
        except BacktestTimeout as e:
            seconds = current_app.config['QUANT'].backtest_timeout_seconds
            current_app.logger.warning('backtest timed out: %s', e)
            return problem(504, f"The backtest ran past this server's {seconds:g} s limit and was {e}. "
                                'It is stored with status failed. Fewer symbols or a shorter period run faster.')
        except Exception:
            return server_error()
    return wrapper


def http_error(error: HTTPException):
    """Flask's own HTTP errors (404, 405, 413, ...) as problem details under /api"""
    if not request.path.startswith('/api/'):
        return error
    headers = {k: v for k, v in error.get_headers() if k.lower() == 'allow'}
    return problem(error.code or 500, error.description or '', headers)
