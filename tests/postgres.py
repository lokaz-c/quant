"""
Helpers for tests that need PostgreSQL. The server comes from
QUANT_TEST_POSTGRES_URL; see tests/conftest.py.
"""
import os
import uuid
from contextlib import contextmanager

import pytest

POSTGRES_URL_ENV = 'QUANT_TEST_POSTGRES_URL'


def postgres_server_url() -> str:
    url = os.getenv(POSTGRES_URL_ENV)
    if url:
        return url
    message = f'{POSTGRES_URL_ENV} is not set'
    if os.getenv('QUANT_REQUIRE_POSTGRES') == '1':
        pytest.fail(message + ' but QUANT_REQUIRE_POSTGRES=1')
    pytest.skip(message + ' (run `make test-pg`)')


@contextmanager
def fresh_postgres_database():
    """Create an empty database on the test server; yield its URL; drop it."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    server_url = make_url(postgres_server_url())
    name = f'quant_test_{uuid.uuid4().hex[:12]}'
    admin = create_engine(server_url, isolation_level='AUTOCOMMIT')
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE {name}'))
    try:
        yield server_url.set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS {name} WITH (FORCE)'))
        admin.dispose()


@contextmanager
def app_bound_to(engine):
    """Point the app's sessions (get_db) at `engine` for the duration."""
    from app.models.database import SessionLocal

    previous = SessionLocal.kw['bind']
    SessionLocal.configure(bind=engine)
    try:
        yield
    finally:
        SessionLocal.configure(bind=previous)
