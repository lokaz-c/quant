"""
Protection for a public deployment (docs/api.md#limits-rate-limits-and-api-keys):

- per-client-IP rate limits, a tight one shared by the requests that run a
  backtest or write a record, a looser one for every other /api request;
- an optional API key (X-API-Key, checked against SHA-256 digests) that lifts
  the rate limits for server-side clients such as TradeDesk;
- a cap on backtests running at once in this process.

Rate limiting is Flask-Limiter with in-memory storage and the moving-window
strategy. In-memory counters live in one process: the Docker image runs one
gunicorn process (threads for concurrency) on one instance, so the limits are
exact. With more processes or instances each keeps its own counters and the
effective limit multiplies; QUANT_RATE_LIMIT_STORAGE_URI=redis://... shares
them, with no code change. The run-slot semaphore is per process as well.
"""
import hashlib
import hmac
import math
import threading
import time
from contextlib import contextmanager

from flask import Flask, current_app, g, request
from flask_limiter import Limiter, RateLimitExceeded

from app.config import ApiConfig
from app.routes.errors import RunsBusy, problem

API_KEY_HEADER = 'X-API-Key'

# Endpoints under the tight limit: they run a backtest or store a record
RUN_ENDPOINTS = ('backtest.run_backtest', 'backtest.regime_analysis', 'strategy.create_strategy')


def client_ip() -> str:
    """
    The client's address: the configured proxy header if set and present,
    else the socket peer. Only set QUANT_CLIENT_IP_HEADER to a header the
    proxy overwrites on every request (on Render, Cloudflare's
    CF-Connecting-IP); a header the client controls lets it pick its own
    rate-limit bucket. For a list (X-Forwarded-For) the last entry is used:
    the one the nearest proxy added.
    """
    header = current_app.config['QUANT'].client_ip_header
    if header:
        value = request.headers.get(header, '').split(',')[-1].strip()
        if value:
            return value
    return request.remote_addr or 'unknown'


def _key_matches(presented: str, digests) -> bool:
    actual = hashlib.sha256(presented.strip().encode('utf-8')).digest()
    match = False
    for digest in digests:
        match |= hmac.compare_digest(digest, actual)  # no early exit
    return match


def check_api_key():
    """
    before_request for /api: no header is an anonymous request; a valid key
    marks the request as a keyed client; a key that is present but wrong is a
    401, so a misconfigured client finds out rather than being silently rate
    limited (the same rule as the market-data service).
    """
    if not request.path.startswith('/api/'):
        return None
    key = request.headers.get(API_KEY_HEADER)
    if key is None:
        return None
    if not _key_matches(key, current_app.config['QUANT'].api_key_digests):
        return problem(401, f'The {API_KEY_HEADER} header is not a valid key.')
    g.keyed_client = True
    return None


def keyed_client() -> bool:
    return bool(g.get('keyed_client'))


def too_many_requests(error: RateLimitExceeded):
    limiter: Limiter = current_app.extensions['quant_limiter']
    current = limiter.current_limit
    reset_at = current.window[0] if current else time.time() + 60
    retry_after = max(1, math.ceil(reset_at - time.time()))
    return problem(429, f'Rate limit of {error.description} per client address exceeded. Retry in {retry_after} s; '
                        f'server-side clients can send an {API_KEY_HEADER} instead.',
                   {'Retry-After': str(retry_after)})


@contextmanager
def run_slot():
    """Hold one of the QUANT_MAX_CONCURRENT_RUNS slots for a backtest, or raise RunsBusy"""
    slots: threading.BoundedSemaphore = current_app.extensions['quant_run_slots']
    if not slots.acquire(blocking=False):
        raise RunsBusy()
    try:
        yield
    finally:
        slots.release()


def install(app: Flask, config: ApiConfig) -> Limiter:
    """Call after the blueprints are registered: it wraps their run endpoints"""
    # Registered before the limiter's own hook, so a bad key is a 401 before it counts
    app.before_request(check_api_key)
    limiter = Limiter(
        key_func=client_ip,
        app=app,
        storage_uri=config.rate_limit_storage,
        strategy='moving-window',
        default_limits=[config.read_limit],
        # /health (Render's health check) and the frontend's static files are not limited
        default_limits_exempt_when=lambda: not request.path.startswith('/api/'),
        headers_enabled=False,  # Retry-After is set on the 429 only (too_many_requests)
        enabled=config.rate_limits_enabled,
        key_prefix='quant',
    )
    limiter.request_filter(keyed_client)
    runs = limiter.shared_limit(config.run_limit, scope='runs')
    for endpoint in RUN_ENDPOINTS:
        app.view_functions[endpoint] = runs(app.view_functions[endpoint])
    app.register_error_handler(RateLimitExceeded, too_many_requests)
    app.extensions['quant_limiter'] = limiter
    app.extensions['quant_run_slots'] = threading.BoundedSemaphore(config.max_concurrent_runs)
    return limiter
