"""Existing workflow tests run as an authenticated operator."""
import os
# Legacy unit tests use fixture CSV files; never write to the configured Oracle database.
os.environ["DATA_BACKEND"]="csv"
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest
from flask.testing import FlaskClient

@pytest.fixture(autouse=True)
def authenticated_workflow_client(request, monkeypatch):
    if request.module.__name__.endswith('test_auth'):
        return
    from app import app
    class OperatorClient(FlaskClient):
        def open(self, *args, **kwargs):
            with self.session_transaction() as sess:
                sess['authenticated'] = True
                sess['csrf_token'] = 'workflow-test-token'
            headers = dict(kwargs.pop('headers', {}) or {})
            headers['X-CSRF-Token'] = 'workflow-test-token'
            return super().open(*args, headers=headers, **kwargs)
    monkeypatch.setattr(app, 'test_client_class', OperatorClient)
