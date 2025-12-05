"""
Data loader for historical market data
Supports loading OHLCV data from CSV files
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Optional


class DataLoader:
    """Loads and manages historical market data"""

    def __init__(self, data_path: str):
        self.data_path = data_path
        self.data = None

    def load_csv(self, symbols: Optional[List[str]] = None) -> pd.DataFrame:
        """
        Load historical data from CSV file

        Expected CSV columns: timestamp, symbol, open, high, low, close, volume
        """
        df = pd.read_csv(self.data_path)

        # Convert timestamp to datetime
        df['timestamp'] = pd.to_datetime(df['timestamp'])

        # Filter by symbols if provided
        if symbols:
            df = df[df['symbol'].isin(symbols)]

        # Sort by timestamp
        df = df.sort_values(['symbol', 'timestamp']).reset_index(drop=True)

        self.data = df
        return df

    def filter_by_date(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Filter data by date range"""
        if self.data is None:
            raise ValueError("No data loaded. Call load_csv() first.")

        start = pd.to_datetime(start_date)
        end = pd.to_datetime(end_date)

        filtered = self.data[(self.data['timestamp'] >= start) & (self.data['timestamp'] <= end)]
        return filtered.reset_index(drop=True)

    def get_symbols(self) -> List[str]:
        """Get list of unique symbols in the dataset"""
        if self.data is None:
            raise ValueError("No data loaded. Call load_csv() first.")

        return self.data['symbol'].unique().tolist()

    def validate_data(self) -> bool:
        """Validate that data has required columns and proper format"""
        if self.data is None:
            return False

        required_cols = ['timestamp', 'symbol', 'open', 'high', 'low', 'close', 'volume']
        if not all(col in self.data.columns for col in required_cols):
            return False

        # Check for missing values
        if self.data[required_cols].isnull().any().any():
            return False

        return True


def generate_sample_data(
    symbols: List[str],
    start_date: str,
    end_date: str,
    output_path: str,
    regime: str = 'mixed'
) -> pd.DataFrame:
    """
    Generate sample OHLCV data for testing

    Args:
        symbols: List of ticker symbols
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        output_path: Path to save CSV
        regime: Market regime - 'bullish', 'bearish', 'sideways', or 'mixed'
    """
    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)

    # Generate date range (trading days only)
    dates = pd.date_range(start, end, freq='B')  # B = business days

    all_data = []

    for symbol in symbols:
        np.random.seed(hash(symbol) % 2**32)  # Deterministic but different per symbol

        # Initial price
        price = np.random.uniform(50, 200)
        prices = [price]

        # Generate price series based on regime
        for i in range(1, len(dates)):
            if regime == 'bullish':
                drift = 0.0008  # Upward drift
                volatility = 0.015
            elif regime == 'bearish':
                drift = -0.0006  # Downward drift
                volatility = 0.020
            elif regime == 'sideways':
                drift = 0.0001  # Minimal drift
                volatility = 0.012
            else:  # mixed
                # Change regime periodically
                period = i // 60
                if period % 3 == 0:
                    drift = 0.0008
                    volatility = 0.015
                elif period % 3 == 1:
                    drift = -0.0004
                    volatility = 0.018
                else:
                    drift = 0.0001
                    volatility = 0.012

            # Geometric Brownian Motion
            change = drift + volatility * np.random.randn()
            price = price * (1 + change)
            prices.append(price)

        # Generate OHLCV data
        for i, date in enumerate(dates):
            close = prices[i]
            daily_range = close * np.random.uniform(0.01, 0.03)

            high = close + np.random.uniform(0, daily_range)
            low = close - np.random.uniform(0, daily_range)
            open_price = np.random.uniform(low, high)

            # Ensure OHLC relationships
            high = max(high, open_price, close)
            low = min(low, open_price, close)

            volume = np.random.randint(100000, 10000000)

            all_data.append({
                'timestamp': date,
                'symbol': symbol,
                'open': round(open_price, 2),
                'high': round(high, 2),
                'low': round(low, 2),
                'close': round(close, 2),
                'volume': volume
            })

    df = pd.DataFrame(all_data)
    df = df.sort_values(['timestamp', 'symbol']).reset_index(drop=True)

    # Save to CSV
    df.to_csv(output_path, index=False)
    print(f"Generated {len(df)} data points for {len(symbols)} symbols")
    print(f"Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")

    return df


if __name__ == '__main__':
    # Generate sample data
    symbols = ['AAPL', 'GOOGL', 'MSFT', 'AMZN', 'TSLA']
    output_path = 'data/sample_data.csv'

    generate_sample_data(
        symbols=symbols,
        start_date='2022-01-01',
        end_date='2024-12-31',
        output_path=output_path,
        regime='mixed'
    )
