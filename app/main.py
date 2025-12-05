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
    app.run(host='0.0.0.0', port=5000, debug=True)
