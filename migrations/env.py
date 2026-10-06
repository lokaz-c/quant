"""
Alembic environment.

The target database is, in order of precedence:
1. a connection passed in by the caller (config.attributes['connection']),
   which is how init_db.py and the tests run migrations;
2. config.attributes['url'];
3. the app's DATABASE_URL (default sqlite:///quant.db).
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.models.database import DATABASE_URL, Base

config = context.config

# disable_existing_loggers=False: when migrations run inside the app or pytest,
# don't silence loggers they have already set up
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    return config.attributes.get('url') or DATABASE_URL


def _configure(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # SQLite can't ALTER column types or add constraints in place; batch mode
        # rebuilds the table instead. Only matters for autogenerate output.
        render_as_batch=connection.dialect.name == 'sqlite',
        compare_type=True,
    )


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it (`alembic upgrade head --sql`)."""
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={'paramstyle': 'named'},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get('connection')
    if connection is not None:
        _configure(connection)
        with context.begin_transaction():
            context.run_migrations()
        return

    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        _configure(connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
