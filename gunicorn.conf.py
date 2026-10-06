"""
gunicorn settings, read automatically from the working directory (/app in
the Docker image). One process with threads:

- the rate-limit counters and the run slots are in-process
  (app/protection.py), so one process keeps them exact for the instance;
- each process imports pandas, numpy and scipy, and Render's free instance
  has 512 MB;
- threads keep /health and reads answering while a CPU-bound backtest runs,
  so Render's health check doesn't fail during a long run.

Every value can be overridden with gunicorn's own GUNICORN_CMD_ARGS.
"""
import os

# Render sets PORT (10000 by default) and needs 0.0.0.0; docker compose maps 5000
bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"
workers = int(os.environ.get('WEB_CONCURRENCY', '1'))
worker_class = 'gthread'
threads = int(os.environ.get('GUNICORN_THREADS', '4'))
# For gthread workers this is the worker heartbeat, not a request limit; a
# backtest is stopped by QUANT_BACKTEST_TIMEOUT_SECONDS (90 s by default)
timeout = 120
graceful_timeout = 30
accesslog = '-'
