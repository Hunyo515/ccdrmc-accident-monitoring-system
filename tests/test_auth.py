import pytest
from app import app
from routes.auth import _attempts

@pytest.fixture
def client():
    _attempts.clear()
    return app.test_client()


def sign_in(client, password='AbanteEchague1234'):
    client.get('/login')
    with client.session_transaction() as session:
        token = session['csrf_token']
    return client.post('/login', data={'username':'RescueEchague', 'password':password, 'csrf_token':token})


def test_pages_and_apis_require_authentication(client):
    for path in ['/', '/explorer', '/data', '/map', '/upload']:
        response = client.get(path)
        assert response.status_code == 302 and response.location.endswith('/login')
    for path in ['/api/meta', '/api/rules', '/api/overview', '/api/export/data.csv', '/api/review/batches', '/api/records/example', '/api/export/data.xlsx', '/api/export/analysis.pdf']:
        assert client.get(path).status_code == 401
    assert client.post('/api/upload/confirm', json={}).status_code == 401
    assert client.post('/api/review/manual', json={}).status_code == 401


def test_login_video_and_no_exposed_credentials(client):
    html = client.get('/login').get_data(as_text=True)
    assert 'video/login-background.mp4' in html
    assert 'AbanteEchague1234' not in html
    assert client.get('/static/video/login-background.mp4', headers={'Range':'bytes=0-99'}).status_code == 206


def test_login_logout_and_csrf(client):
    assert client.post('/login', data={'username':'RescueEchague','password':'AbanteEchague1234'}).status_code == 403
    assert sign_in(client).status_code == 302
    assert client.get('/').status_code == 200
    assert client.get('/api/meta').status_code == 200
    assert client.post('/api/upload/confirm', json={}).status_code == 403
    assert client.post('/logout').status_code == 403
    with client.session_transaction() as session:
        token = session['csrf_token']
    assert client.post('/logout', data={'csrf_token':token}).status_code == 302
    assert client.get('/api/meta').status_code == 401


def test_wrong_password_and_throttling(client):
    for _ in range(5):
        assert sign_in(client, 'incorrect').status_code == 401
    assert sign_in(client).status_code == 429
    assert client.get('/api/meta').status_code == 401


def test_cookie_and_cache_headers(client):
    response = sign_in(client)
    cookie = response.headers['Set-Cookie']
    assert 'HttpOnly' in cookie and 'SameSite=Lax' in cookie
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.headers['X-Frame-Options'] == 'DENY'
