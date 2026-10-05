"""
Shared test setup. The app reads DATABASE_URL when app.models.database is
first imported, so point it at a throwaway SQLite file before any test
module imports the app.
"""
import os
import tempfile

_db_dir = tempfile.mkdtemp(prefix='quant-tests-')
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(_db_dir, 'test.db')
