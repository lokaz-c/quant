"""
Shared test setup. The app reads DATABASE_URL when app.models.database is
first imported, so point it at a throwaway SQLite file before any test
module imports the app.

PostgreSQL tests (marked `postgres`) need a server they can create databases
on, given as QUANT_TEST_POSTGRES_URL, e.g.

    QUANT_TEST_POSTGRES_URL=postgresql://quant:quant@127.0.0.1:55432/postgres

`make test-pg` starts a throwaway container and sets it. Without the variable
these tests are skipped, unless QUANT_REQUIRE_POSTGRES=1 (set in CI), in
which case they fail, so CI can't pass by skipping them.
"""
import os
import tempfile

import pytest

_db_dir = tempfile.mkdtemp(prefix='quant-tests-')
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(_db_dir, 'test.db')

# The suite runs on the synthetic data unless a test configures market-data
# itself (against a fake server), whatever the developer's shell has set
for _name in ('QUANT_DATA_SOURCE', 'MARKET_DATA_URL', 'MARKET_DATA_API_KEY', 'MARKET_DATA_ADJUSTMENT',
              'MARKET_DATA_CACHE_DIR', 'MARKET_DATA_TIMEOUT', 'DATA_PATH'):
    os.environ.pop(_name, None)

# The public-deploy settings (app/config.py) take their defaults, except that
# rate limiting is off: the suite sends far more runs from one address than
# the limit allows. tests/test_protection.py builds apps with it on.
for _name in [n for n in os.environ if n.startswith('QUANT_') and n not in ('QUANT_TEST_POSTGRES_URL',
                                                                           'QUANT_REQUIRE_POSTGRES')]:
    os.environ.pop(_name, None)
os.environ['QUANT_RATE_LIMITS'] = 'off'

from tests.postgres import fresh_postgres_database  # noqa: E402


@pytest.fixture
def sqlite_url(tmp_path):
    return 'sqlite:///' + str(tmp_path / 'migrations.db')


@pytest.fixture
def postgres_url():
    with fresh_postgres_database() as url:
        yield url
