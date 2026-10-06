"""
The deploy files agree with the app: gunicorn binds where Render expects and
runs one process (the rate-limit counters are in-process), and the Render
blueprint builds the Dockerfile and checks a route that exists. The image
itself is checked by `make deploy-check`.
"""
import runpy
from pathlib import Path

from app.main import create_app

REPO_ROOT = Path(__file__).resolve().parent.parent


def gunicorn_settings(monkeypatch, **env):
    for name in ('PORT', 'WEB_CONCURRENCY', 'GUNICORN_THREADS'):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return runpy.run_path(str(REPO_ROOT / 'gunicorn.conf.py'))


def test_gunicorn_binds_to_renders_port_on_all_interfaces(monkeypatch):
    assert gunicorn_settings(monkeypatch, PORT='10000')['bind'] == '0.0.0.0:10000'
    assert gunicorn_settings(monkeypatch)['bind'] == '0.0.0.0:5000'  # docker compose maps 5000


def test_gunicorn_runs_one_threaded_process_by_default(monkeypatch):
    settings = gunicorn_settings(monkeypatch)
    assert (settings['workers'], settings['worker_class'], settings['threads']) == (1, 'gthread', 4)


def test_render_blueprint_builds_the_dockerfile_on_the_free_plan():
    blueprint = (REPO_ROOT / 'render.yaml').read_text()
    for line in ('runtime: docker', 'plan: free', 'dockerfilePath: ./Dockerfile', 'healthCheckPath: /health',
                 'key: DATABASE_URL', 'key: QUANT_CLIENT_IP_HEADER', 'value: CF-Connecting-IP',
                 'key: QUANT_API_KEY_SHA256', 'key: QUANT_CORS_ORIGINS'):
        assert line in blueprint, line
    assert 'env: python' not in blueprint and 'buildCommand' not in blueprint
    assert not (REPO_ROOT / 'Procfile').exists() and not (REPO_ROOT / 'runtime.txt').exists()


def test_image_builds_the_frontend_and_migrates_before_serving():
    dockerfile = (REPO_ROOT / 'Dockerfile').read_text()
    assert 'FROM node:24-alpine AS frontend' in dockerfile and 'COPY --from=frontend' in dockerfile
    assert 'python init_db.py && exec gunicorn app.main:app' in dockerfile


def test_health_answers_without_the_database(monkeypatch):
    # Render checks every few seconds; touching the database would keep Neon awake
    from app.models import database

    def no_database(*args, **kwargs):
        raise AssertionError('/health opened a database session')
    monkeypatch.setattr(database, 'SessionLocal', no_database)
    client = create_app().test_client()
    assert client.get('/health').get_json() == {'status': 'healthy'}
