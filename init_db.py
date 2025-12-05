"""
Initialize database and seed with strategies and risk configs
"""
from app.models.database import Base, engine, SessionLocal, Strategy, RiskConfig
import json

def init_database():
    """Create all tables and seed initial data"""
    # Create tables
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()

    try:
        # Check if data already exists
        if db.query(Strategy).count() > 0:
            print("Database already contains data. Skipping seed.")
            return

        # Load strategies from config
        print("Loading strategies...")
        with open('config/strategies.json', 'r') as f:
            strategies_config = json.load(f)

        for key, config in strategies_config.items():
            strategy = Strategy(
                name=config['name'],
                description=config.get('description', f"{config['name']} trading strategy"),
                parameters=config['parameters']
            )
            db.add(strategy)
            print(f"  - Added strategy: {config['name']}")

        # Load risk configs
        print("Loading risk configurations...")
        with open('config/risk_configs.json', 'r') as f:
            risk_configs = json.load(f)

        for key, config in risk_configs.items():
            risk_config = RiskConfig(
                name=config['name'],
                max_position_size=config['max_position_size'],
                max_portfolio_exposure=config['max_portfolio_exposure'],
                stop_loss_pct=config['stop_loss_pct'],
                take_profit_pct=config['take_profit_pct'],
                max_drawdown_pct=config['max_drawdown_pct'],
                enabled=config['enabled']
            )
            db.add(risk_config)
            print(f"  - Added risk config: {config['name']}")

        db.commit()
        print("\nDatabase initialized successfully!")

    except Exception as e:
        print(f"Error initializing database: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == '__main__':
    init_database()
