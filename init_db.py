"""
Bring the schema to the latest Alembic revision, then seed strategies and risk
profiles from config/*.json. This is the only place seed data comes from
(SQLite locally, PostgreSQL in Docker).

    python init_db.py        # = `alembic upgrade head`, plus the seed

A database created before Alembic (by the old db/init.sql or create_all()) has
the tables but no alembic_version table. Its schema is the baseline revision,
so it is stamped 0001 and then upgraded.
"""
import json
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.models.database import RiskConfig, Strategy, engine as default_engine

REPO_ROOT = Path(__file__).resolve().parent
CONFIG_DIR = REPO_ROOT / 'config'
ALEMBIC_INI = REPO_ROOT / 'alembic.ini'
BASELINE_REVISION = '0001'


def alembic_config(connection=None) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    if connection is not None:
        cfg.attributes['connection'] = connection
    return cfg


def upgrade_to_head(engine=None) -> None:
    """`alembic upgrade head` on `engine` (default: the app's DATABASE_URL)."""
    engine = engine or default_engine
    with engine.begin() as connection:
        cfg = alembic_config(connection)
        tables = set(inspect(connection).get_table_names())
        if 'strategies' in tables and 'alembic_version' not in tables:
            print(f"Existing schema without Alembic history: stamping {BASELINE_REVISION}")
            command.stamp(cfg, BASELINE_REVISION)
        command.upgrade(cfg, 'head')


def seed(engine=None) -> None:
    """Insert the strategies and risk profiles from config/ into an empty database."""
    with Session(engine or default_engine) as db:
        if db.query(Strategy).count() > 0 or db.query(RiskConfig).count() > 0:
            print("Database already contains data. Skipping seed.")
            return

        print("Loading strategies...")
        with open(CONFIG_DIR / 'strategies.json', 'r') as f:
            strategies_config = json.load(f)
        for config in strategies_config.values():
            db.add(Strategy(
                name=config['name'],
                description=config.get('description', f"{config['name']} trading strategy"),
                parameters=config['parameters']
            ))
            print(f"  - Added strategy: {config['name']}")

        print("Loading risk configurations...")
        with open(CONFIG_DIR / 'risk_configs.json', 'r') as f:
            risk_configs = json.load(f)
        for config in risk_configs.values():
            db.add(RiskConfig(
                name=config['name'],
                max_position_size=config['max_position_size'],
                max_portfolio_exposure=config['max_portfolio_exposure'],
                stop_loss_pct=config['stop_loss_pct'],
                take_profit_pct=config['take_profit_pct'],
                max_drawdown_pct=config['max_drawdown_pct'],
                enabled=config['enabled']
            ))
            print(f"  - Added risk config: {config['name']}")

        db.commit()


def init_database(engine=None) -> None:
    """Upgrade the schema to head and seed it"""
    print("Upgrading the schema (alembic upgrade head)...")
    upgrade_to_head(engine)
    seed(engine)
    print("Database ready.")


if __name__ == '__main__':
    init_database()
