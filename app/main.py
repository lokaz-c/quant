"""
Main Flask application: the REST API under /api, and the React frontend
(frontend/, built by Vite into frontend/dist) at /.
"""
import os
from pathlib import Path

from flask import Flask, abort, send_from_directory
from flask_cors import CORS

from app.routes import backtest_routes, data_routes, risk_routes, strategy_routes
from app.strict_json import StrictJSONProvider
from data_sources.sources import DataConfig

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FRONTEND_DIST = REPO_ROOT / 'frontend' / 'dist'

NOT_BUILT = ('The frontend is not built. Run `make frontend` (needs Node 24), or use '
             '`make run` for the Docker build. The API is at /api.\n')


def create_app(frontend_dist=None):
    """Application factory"""
    app = Flask(__name__, static_folder=None)
    dist = Path(frontend_dist or os.getenv('FRONTEND_DIST', DEFAULT_FRONTEND_DIST))

    # Configuration
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    # Valid JSON only: NaN and infinities are refused both ways (app/strict_json.py)
    app.json = StrictJSONProvider(app)

    # Fail at startup, not on the first request, if QUANT_DATA_SOURCE,
    # MARKET_DATA_URL or MARKET_DATA_ADJUSTMENT don't make sense together
    DataConfig.from_env()

    # Enable CORS
    CORS(app)

    # Register blueprints
    app.register_blueprint(backtest_routes.bp)
    app.register_blueprint(strategy_routes.bp)
    app.register_blueprint(risk_routes.bp)
    app.register_blueprint(data_routes.bp)

    @app.route('/health')
    def health():
        """Health check endpoint"""
        return {'status': 'healthy'}, 200

    # Frontend. Vite writes index.html plus content-hashed files under
    # assets/, so those can be cached for good; index.html must not be.
    @app.route('/')
    def index():
        if not (dist / 'index.html').is_file():
            return NOT_BUILT, 503, {'Content-Type': 'text/plain; charset=utf-8'}
        response = send_from_directory(dist, 'index.html')
        response.headers['Cache-Control'] = 'no-cache'
        return response

    @app.route('/assets/<path:filename>')
    def assets(filename):
        response = send_from_directory(dist / 'assets', filename)
        response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        return response

    @app.route('/<path:filename>')
    def public_file(filename):
        # Files Vite copies from frontend/public (e.g. favicon.svg). Paths
        # under /api/ never fall through to a file.
        if filename.startswith('api/') or not (dist / filename).is_file():
            abort(404)
        return send_from_directory(dist, filename)

    return app


# Create app instance
app = create_app()


if __name__ == '__main__':
    # Development server only (Docker and Render use gunicorn). Port 8000 because
    # macOS binds 5000 for AirPlay; the debugger stays off unless FLASK_DEBUG=1.
    app.run(host='127.0.0.1', port=int(os.getenv('PORT', '8000')),
            debug=os.getenv('FLASK_DEBUG') == '1')
