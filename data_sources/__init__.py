"""
Where the backtester's bars come from.

- market_data: a client for the market-data service's REST API (/v1).
- cache: a local SQLite cache of the bars that client fetches.
- sources: the switch between the seeded synthetic generator and market-data,
  and the provenance every run records.

See docs/market-data.md.
"""
