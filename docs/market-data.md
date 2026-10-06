# Data sources and the market-data client

Backtests run on one of two data sources:

| Source | What it is | When it is used |
| --- | --- | --- |
| `synthetic` | `data/sample_data.csv`, written by the seeded generator ([data.md](data.md)) | The default without `MARKET_DATA_URL`. Always behind `make results` and CI. |
| `market-data` | Daily bars from [lokaz-c/market-data](https://github.com/lokaz-c/market-data) (Java, Spring Boot), read through a local cache | The default when `MARKET_DATA_URL` is set. |

The market-data service labels every symbol `alpaca` or `synthetic`. Each run stores both where its bars came from and what the service said they are, and the API and the UI label the run from that record.

## Alpaca's terms

The market-data service ingests bars from Alpaca's market data API (the IEX feed by default). Alpaca's terms do not allow public display of its data without written consent. So the service's public (keyless) endpoints serve only its synthetic data by default (`PUBLIC_DATA_SOURCES=synthetic`), and an Alpaca symbol answers 404 without an API key. For this app that means:

- without `MARKET_DATA_API_KEY`, the market-data source gives synthetic data only, and runs say so;
- with a key, runs can use Alpaca bars, but a deployment that shows those runs publicly needs the same consent. Until then, keep a public deployment on the synthetic data, or on the service without a key.

The service ingests Alpaca's IEX feed by default (`ALPACA_FEED=iex`, the only feed a paper-only account gets), but its API does not say which feed a bar came from. IEX is a single exchange, so its prices and volumes are not the consolidated tape. Both points are in the description every Alpaca-labelled run carries.

## Configuration

Environment variables (see `.env.example`):

| Variable | Default | Meaning |
| --- | --- | --- |
| `QUANT_DATA_SOURCE` | `market-data` if `MARKET_DATA_URL` is set, else `synthetic` | The default source for runs |
| `MARKET_DATA_URL` | unset | The service's base URL, e.g. `http://localhost:8080` |
| `MARKET_DATA_API_KEY` | unset | Sent as `X-API-Key`. Unlocks non-public sources (Alpaca) |
| `MARKET_DATA_ADJUSTMENT` | `split` | `split` or `raw` bars |
| `MARKET_DATA_CACHE_DIR` | `data/cache` | Where the cache lives; `off` disables it |
| `MARKET_DATA_TIMEOUT` | `30` | Read timeout in seconds (connect: 5 s) |
| `DATA_PATH` | `data/sample_data.csv` | The synthetic file |

The app checks these at startup and refuses to start if they contradict each other (for example `QUANT_DATA_SOURCE=market-data` without a URL). A request can pick a source with `"data_source": "synthetic" | "market-data"` (see [api.md](api.md)); the UI sends the source its form was built from. Regime analysis needs the synthetic data, because only the generator writes regime labels.

## The client

`data_sources/market_data.py`, `MarketDataClient`. It uses two endpoints of the service's API, as implemented on its `feat/perf-docker-deploy` branch:

- `GET /v1/bars/{ticker}?from=&to=&after=&limit=&adjustment=split|raw` returns `{ticker, source, adjustment, from, to, bars: [{date, open, high, low, close, volume}], nextAfter}`;
- `GET /v1/symbols?q=&limit=` returns `{symbols: [{ticker, name, source, firstBar, lastBar, lastClose}]}`.

Behaviour:

- **Pagination.** The service pages by key, not offset: while `nextAfter` is not null, the client asks again with `after=nextAfter`, at the maximum page size of 1,000. It checks that each page starts after the cursor and that `nextAfter` is the last bar's date, and it stops with an error if there are more pages than the date range could hold. Five years of daily bars take two requests.
- **Split-adjusted by default.** The request always sends `adjustment`, `split` unless configured otherwise, and the client checks that the response echoes it. Raw bars show a split as a price jump, which the strategies would read as a crash.
- **API key.** Optional, from `MARKET_DATA_API_KEY`, sent only as the `X-API-Key` header. It never appears in a URL, a log line or an error message.
- **Timeouts.** 5 s to connect, 30 s to read (`MARKET_DATA_TIMEOUT`).
- **Retries.** 429, 500, 502, 503, 504, timeouts and connection errors are retried up to 4 times. On a 429 the service sends `Retry-After` in seconds; the client waits exactly that long (an HTTP-date is also accepted). A `Retry-After` above 120 s is not waited out: the call fails at once with `MarketDataRateLimited`, which says how long to wait. Without `Retry-After` the wait is "full jitter" exponential backoff, uniform in [0, min(30 s, 0.5 s x 2^attempt)]. Other 4xx responses are not retried. The client records the last `X-RateLimit-Remaining` it saw.
- **Errors.** The service's errors are RFC 9457 problem details; the client turns them into exceptions with the service's `detail` (and the failing parameter, for validation errors):

  | Status | Exception | In the API |
  | --- | --- | --- |
  | 400 | `MarketDataBadRequest` | 400 |
  | 401, 403 | `MarketDataUnauthorized` | 502 |
  | 404 | `MarketDataNotFound`, with a hint that an Alpaca ticker needs a key | 400 |
  | 429 after the retries | `MarketDataRateLimited` | 502 |
  | 5xx, timeout, connection error after the retries | `MarketDataUnavailable` | 502 |
  | A 200 that breaks the contract | `MarketDataContractError` | 502 |

- **Contract checks.** The parser is strict: a missing field, a price that is not a number, bars out of order or outside the requested range, OHLC values out of range, or a `source` other than `alpaca` or `synthetic` is an error. An unknown source is never guessed at, because the label decides whether a run is shown as real.

**Why httpx.** The project had no HTTP client in `requirements.txt` (alpaca-py pulls in `requests`, but only in `requirements-live.txt`, which the Docker image does not install), so either choice adds one dependency. httpx has per-phase timeouts (`httpx.Timeout(connect=..., read=...)`), where `requests` has none by default, a pooled `Client`, and `httpx.MockTransport` built in, so the tests need no extra mocking library. Its own transport retries only cover connection setup, so the retry loop is written out in the client, where it can honour `Retry-After`.

## The cache

`data_sources/cache.py`, `BarCache`: one SQLite file, `data/cache/market_data.sqlite3`, git-ignored and kept out of the Docker image. SQLite is in the standard library, handles concurrent gunicorn workers (WAL mode, short transactions, writes take the lock up front), and can answer "which dates do I have" with a query. Parquet would have needed pyarrow and a locking scheme.

**Keys.** A series is (service URL, ticker, adjustment). Split-adjusted and raw bars are separate series, and two services never share entries. For each series the cache stores the bars by date, the source the service reported, and the date ranges known to be complete.

**Fetching only what is missing.** A range is complete once the service has answered for it, including weekends and holidays, which have no bars. A request for `[start, end]` subtracts the complete ranges, fetches only the gaps, and reads the whole range from the cache. A fetch replaces the cached bars in its range, so the cache never keeps a bar the service no longer has there. A run on 2020-2024 after a run on 2020-2023 fetches 2024 only. A repeated run makes no requests.

**Invalidation rule.**

1. **Settling.** The service re-ingests the last 7 days every session (its `lookback-days`). Bars newer than 7 days before the fetch date are stored but not marked complete, so the next request for them fetches them again.
2. **Re-basing.** A new split changes every earlier split-adjusted price, and the service can correct old bars. Every fetch next to cached data also fetches the nearest cached bar: by extending the request when the bar is adjacent to the gap (so exactly one extra bar comes back), or with a one-day request when it is not. If that bar differs from the cached copy, the whole series is dropped and fetched again. So the bars of a series always share one adjustment basis. A fully cached range is not re-checked: multiplying every price by the same factor does not change a backtest's returns.
3. **Source.** If the service reports a different source for a ticker than the cache holds, the series is dropped.
4. **By hand.** `python -m data_sources cache clear`, or delete the file. Do this if the service backfills bars older than 7 days into a range the cache already holds as complete: the cache can't see that (see the gaps below). A change to the cache's schema version rebuilds the file.

## What a run records, and the labelling guarantee

Migration `0004` adds four columns to `backtest_runs` (see [database.md](database.md)):

| Column | Values |
| --- | --- |
| `data_source` | `synthetic` (the local file) or `market-data` |
| `reported_source` | `alpaca`, `synthetic`, or `mixed` when the run's symbols disagree; always `synthetic` for the local file |
| `symbol_sources` | market-data runs: the source the service reported for each symbol |
| `price_adjustment` | market-data runs: `split` or `raw` |

The API returns them as the run's `data` object, with `synthetic` (true unless the run is real) and a description. `GET /api/backtest/list` has `data_source`, `reported_source` and `synthetic` per run. `GET /api/data` gives the same label for the source a new run would use, computed from the service's symbol list.

A run is labelled real only if every one of these holds, and each is enforced in a different place:

1. the client accepted the service's `source` field, which must be `alpaca` or `synthetic` (an unknown value is an error, not a label);
2. `Provenance.real` (`data_sources/sources.py`): the bars came from market-data and the service reported `alpaca` for every symbol. One synthetic symbol makes the run `mixed`, which is labelled synthetic;
3. the database rejects unknown labels, and a run from the local file labelled anything but `synthetic` (`ck_backtest_runs_local_is_synthetic`). The column defaults are `synthetic`;
4. the UI derives the banner from `source` and `reported_source` (`frontend/src/dataLabel.ts`) and shows "Market data" only when they say market-data and alpaca and the server's `synthetic` flag is false. Any disagreement falls back to "Synthetic data". The banner describes the run on screen, or before one is open, the source a new run would use; each row of the run history has its own label;
5. both runs of a baseline pair use the same loaded bars, so they always share a label.

## make results and make results-real

- `make results` runs the benchmark (3 strategies x 4 risk profiles, 5 symbols, 2020-2024, $100,000) on the synthetic file and writes `docs/results.md`. It ignores `QUANT_DATA_SOURCE` and `MARKET_DATA_URL`, so it stays reproducible byte for byte, and CI still regenerates it and fails on any difference.
- `make results-real` runs the same benchmark on market-data bars and writes `docs/results-real.md`. It needs `MARKET_DATA_URL`, and a key for Alpaca symbols. It refuses to write the file unless the service reports `alpaca` for every symbol. With `--allow-synthetic` it writes the report anyway, headed "The data is synthetic". The report gives each symbol's reported source, the bar counts, and a sha256 of the bars used, because the output changes when the service's data does. Returns are not split by regime: market bars have no regime labels. CI does not run it.

`docs/results-real.md` is not committed. TODO(lorenzo): run it once market-data has ingested Alpaca bars and you have its API key, then commit the file.

## Local end to end

```bash
make run-market-data   # quant + PostgreSQL + market-data + its PostgreSQL
```

This is `make run` plus the `market-data` profile in `docker-compose.yml`, which builds the service from a checkout of lokaz-c/market-data next to this one (`MARKET_DATA_DIR`, default `../market-data`) and points quant at it. The service gets no Alpaca keys and serves only its own synthetic demo data (symbols S001-S050, every one labelled `synthetic`), so every run is labelled synthetic. Without the profile, `make run` does not need the market-data checkout.

## Command line

```bash
python -m data_sources symbols
python -m data_sources bars S001 --from 2024-01-01 --to 2024-12-31   # through the cache
python -m data_sources cache info
python -m data_sources cache clear
```

## Tests

- `tests/test_market_data_client.py`: the client against an in-process fake of the service (`tests/fake_market_data.py`, through `httpx.MockTransport`) and real sockets: pagination, split-adjusted by default, the API key, retries and backoff bounds, `Retry-After` (seconds and HTTP-date, and the cap), read timeouts on a real slow server, refused connections, error mapping, and responses that break the contract.
- `tests/test_market_data_contract.py`: the parser against responses recorded from the real service (`tests/fixtures/market_data/`; the module docstring says how they were recorded).
- `tests/test_bar_cache.py`: hits, partial fetches, holes, the anchor check, re-based series, the settle window, source changes and the keys.
- `tests/test_data_sources.py`: the configuration switch and the provenance rules.
- `tests/test_api_data_source.py`: runs on the fake service through the API, on SQLite and PostgreSQL: what is stored and returned for synthetic, Alpaca and mixed data, baseline pairs, 400s and 502s.
- `tests/test_results_real.py`: `make results-real` labels and refusals, and `make results` ignoring the market-data settings.
- `frontend/src/dataLabel.test.ts` and `frontend/src/App.test.tsx`: the banner and the run history labels.

## Gaps in the market-data API

Things this client works around, which the service could add:

- **No splits endpoint or adjustment version.** A client can't tell that split-adjusted history was re-based, so the cache re-reads one bar per fetch. A `/v1/splits/{ticker}` endpoint, or the date of the latest split on each bars page, would make invalidation exact.
- **No way to tell a backfill from a range with no bars.** There is no trading calendar, `ETag` or per-symbol "last ingested" time, so a range the service answered once with no bars stays complete in the cache even if the service backfills it later (beyond the 7-day settle window).
- **The bulk CSV export has no source.** `/v1/export/bars.csv` has columns `ticker,date,open,high,low,close,volume` and no `source` column or header, so a client can't label what it exports. This client uses the paginated JSON endpoint, which carries `source` on every page.
- **No multi-ticker JSON endpoint.** One request or more per symbol; with the anonymous limit (burst of 30, then 60 a minute) a run over many symbols waits on 429s.
- **Rate-limit headers.** Only `X-RateLimit-Remaining` on success and `Retry-After` on 429. Without the limit or the reset time a client can't pace itself before the first 429.
- **`/v1/symbols` stops at 200 rows** and has no pagination.
- **No feed field.** Bars don't say whether they came from Alpaca's IEX or SIP feed, so the label says "IEX by default" rather than stating it.
