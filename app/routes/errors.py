"""
Error responses shared by the routes
"""
from flask import current_app, jsonify


def server_error():
    """
    Log the exception being handled and return a 500 without its message:
    exception text can include SQL statements and their parameters, which
    the frontend would otherwise show to the user.
    """
    current_app.logger.exception('Unhandled error')
    return jsonify({'error': 'Internal server error; the details are in the server log'}), 500
