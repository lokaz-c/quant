"""
Main Flask application
"""
import os
from flask import Flask, render_template, send_from_directory
from flask_cors import CORS
from app.routes import backtest_routes, strategy_routes, risk_routes


def create_app():
    """Application factory"""
    app = Flask(__name__, template_folder='../templates', static_folder='../static')

    # Configuration
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    app.config['JSON_SORT_KEYS'] = False

    # Enable CORS
    CORS(app)

    # Register blueprints
    app.register_blueprint(backtest_routes.bp)
    app.register_blueprint(strategy_routes.bp)
    app.register_blueprint(risk_routes.bp)

    # Web UI routes
    @app.route('/')
    def index():
        """Serve the main UI"""
        return render_template('index.html')

    @app.route('/health')
    def health():
        """Health check endpoint"""
        return {'status': 'healthy'}, 200

    return app


# Create app instance
app = create_app()


if __name__ == '__main__':
    # Development server only (Docker and Render use gunicorn). Port 8000 because
    # macOS binds 5000 for AirPlay; the debugger stays off unless FLASK_DEBUG=1.
    app.run(host='127.0.0.1', port=int(os.getenv('PORT', '8000')),
            debug=os.getenv('FLASK_DEBUG') == '1')
