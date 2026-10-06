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


def bad_gateway(error: Exception):
    """
    502 for a failure of the market-data service (down, timing out, rate
    limiting past the retries, or answering outside its contract). The
    message is the client's, which names the service and its status but
    never the API key (that only travels in a header).
    """
    current_app.logger.warning('market-data failed: %s', error)
    return jsonify({'error': f'The market-data service failed: {error}'}), 502
