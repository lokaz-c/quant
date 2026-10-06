"""
Settings for running the API in public: CORS, rate limits, the optional API
key, request caps and the per-run time limit. All come from the environment
(.env.example lists them) and are checked when the app starts, so a typo
fails the deploy instead of the first request.
"""
import math
import os
import re
from dataclasses import dataclass, field
from typing import Mapping, Optional, Tuple
from urllib.parse import urlsplit

from limits import parse_many

# The synthetic file spans 2020-01-01 to 2024-12-31: 1,827 days, one of them a leap day
DEFAULT_MAX_RANGE_DAYS = 1827
DEFAULT_MAX_SYMBOLS = 10
DEFAULT_RUN_LIMIT = '5 per minute;30 per hour'
DEFAULT_READ_LIMIT = '120 per minute'
# The limit covers the whole request, including a market-data fetch. In a container limited to
# Render's free 0.1 CPU (`make deploy-check`) the largest run the default caps allow took 8.6 to
# 10.1 s; 90 s also covers a free market-data service waking up (about a minute)
DEFAULT_TIMEOUT_SECONDS = 90.0
# Runs are CPU-bound on 0.1 CPU: a second one at the same time would share the CPU, not finish sooner
DEFAULT_MAX_CONCURRENT_RUNS = 1
MAX_BODY_BYTES = 64 * 1024

_HEX_DIGEST = re.compile(r'^[0-9a-fA-F]{64}$')


class ConfigError(ValueError):
    """A setting that doesn't make sense; raised at startup"""


def _origin(value: str) -> str:
    parts = urlsplit(value)
    if (value == '*' or parts.scheme not in ('http', 'https') or not parts.hostname
            or parts.path not in ('', '/') or parts.query or parts.fragment or parts.username):
        raise ConfigError(f'QUANT_CORS_ORIGINS: {value!r} is not an origin like https://example.com '
                          '("*" is not allowed: list the sites that may call the API)')
    return f'{parts.scheme}://{parts.netloc}'


def _digest(value: str) -> bytes:
    if not _HEX_DIGEST.match(value):
        raise ConfigError('QUANT_API_KEY_SHA256 must be SHA-256 digests in hex (64 characters), comma-separated')
    return bytes.fromhex(value)


def _number(env: Mapping[str, str], name: str, default, kind, low):
    raw = env.get(name, '').strip()
    if not raw:
        return default
    try:
        value = kind(raw)
    except ValueError:
        raise ConfigError(f'{name} must be a number, got {raw!r}')
    if not (math.isfinite(value) and value >= low):
        raise ConfigError(f'{name} must be at least {low}, got {raw!r}')
    return value


def _limit(env: Mapping[str, str], name: str, default: str) -> str:
    value = env.get(name, '').strip() or default
    try:
        parse_many(value)
    except ValueError:
        raise ConfigError(f'{name} must be a rate limit such as "5 per minute;30 per hour", got {value!r}')
    return value


def _list(env: Mapping[str, str], name: str) -> Tuple[str, ...]:
    return tuple(item.strip() for item in env.get(name, '').split(',') if item.strip())


@dataclass(frozen=True)
class ApiConfig:
    # Exact origins allowed to call /api from a browser. Empty: no CORS headers,
    # which is right when the frontend is served by this app (same origin).
    cors_origins: Tuple[str, ...] = ()
    # SHA-256 digests of the keys clients send as X-API-Key; a valid key lifts the rate limits
    api_key_digests: Tuple[bytes, ...] = field(default=(), repr=False)
    # Header the proxy sets to the client's address (Render: CF-Connecting-IP). Empty: the socket peer.
    client_ip_header: Optional[str] = None
    rate_limits_enabled: bool = True
    run_limit: str = DEFAULT_RUN_LIMIT
    read_limit: str = DEFAULT_READ_LIMIT
    rate_limit_storage: str = 'memory://'
    backtest_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_concurrent_runs: int = DEFAULT_MAX_CONCURRENT_RUNS
    max_symbols: int = DEFAULT_MAX_SYMBOLS
    max_range_days: int = DEFAULT_MAX_RANGE_DAYS

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> 'ApiConfig':
        env = os.environ if env is None else env
        switch = env.get('QUANT_RATE_LIMITS', '').strip().lower()
        if switch not in ('', 'on', 'off'):
            raise ConfigError(f'QUANT_RATE_LIMITS must be on or off, got {switch!r}')
        return cls(
            cors_origins=tuple(_origin(o) for o in _list(env, 'QUANT_CORS_ORIGINS')),
            api_key_digests=tuple(_digest(d) for d in _list(env, 'QUANT_API_KEY_SHA256')),
            client_ip_header=env.get('QUANT_CLIENT_IP_HEADER', '').strip() or None,
            rate_limits_enabled=switch != 'off',
            run_limit=_limit(env, 'QUANT_RATE_LIMIT_RUNS', DEFAULT_RUN_LIMIT),
            read_limit=_limit(env, 'QUANT_RATE_LIMIT_READS', DEFAULT_READ_LIMIT),
            rate_limit_storage=env.get('QUANT_RATE_LIMIT_STORAGE_URI', '').strip() or 'memory://',
            backtest_timeout_seconds=_number(env, 'QUANT_BACKTEST_TIMEOUT_SECONDS',
                                             DEFAULT_TIMEOUT_SECONDS, float, 1.0),
            max_concurrent_runs=_number(env, 'QUANT_MAX_CONCURRENT_RUNS', DEFAULT_MAX_CONCURRENT_RUNS, int, 1),
            max_symbols=_number(env, 'QUANT_MAX_SYMBOLS', DEFAULT_MAX_SYMBOLS, int, 1),
            max_range_days=_number(env, 'QUANT_MAX_RANGE_DAYS', DEFAULT_MAX_RANGE_DAYS, int, 1),
        )
