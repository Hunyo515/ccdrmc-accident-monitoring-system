"""Session authentication and CSRF protection for dashboard routes."""
import secrets
import threading
import time
from collections import defaultdict
from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

auth_bp = Blueprint('auth', __name__)
_attempts = defaultdict(list)
_lock = threading.Lock()


def csrf_token():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_urlsafe(32)
    return session['csrf_token']


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('authenticated'):
        return redirect(url_for('views.overview'))
    error = None
    status = 200
    if request.method == 'POST':
        now = time.monotonic()
        address = request.remote_addr or 'unknown'
        with _lock:
            for key in list(_attempts):
                _attempts[key] = [t for t in _attempts[key] if now - t < 900]
                if not _attempts[key]:
                    del _attempts[key]
            blocked = len(_attempts[address]) >= 5
            if not blocked:
                _attempts[address].append(now)
        if blocked:
            error, status = 'Too many sign-in attempts. Please try again in 15 minutes.', 429
        else:
            valid_password = check_password_hash(current_app.config['LOGIN_PASSWORD_HASH'], request.form.get('password', ''))
            valid_user = secrets.compare_digest(request.form.get('username', '').strip().encode(), current_app.config['LOGIN_USERNAME'].encode())
            if valid_password and valid_user:
                with _lock:
                    _attempts.pop(address, None)
                session.clear()
                session['authenticated'] = True
                session.permanent = True
                csrf_token()
                return redirect(url_for('views.overview'))
            error, status = 'The username or password is incorrect.', 401
    response = current_app.make_response((render_template('login.html', error=error), status))
    if status == 429:
        response.headers['Retry-After'] = '900'
    return response


@auth_bp.post('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))


def init_auth(app):
    app.register_blueprint(auth_bp)
    app.jinja_env.globals['csrf_token'] = csrf_token

    @app.before_request
    def protect_routes():
        if request.endpoint == 'static' or request.endpoint is None:
            return
        if request.endpoint != 'auth.login' and not session.get('authenticated'):
            if request.path.startswith('/api/'):
                return jsonify(error='Sign in to continue.'), 401
            return redirect(url_for('auth.login'))
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            supplied = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token', '')
            expected = session.get('csrf_token', '')
            if not expected or not secrets.compare_digest(supplied.encode(), expected.encode()):
                if request.path.startswith('/api/'):
                    return jsonify(error='Your session has changed. Refresh the page and try again.'), 403
                return render_template('login.html', error='Your session has changed. Please sign in again.'), 403

    @app.after_request
    def security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        if request.endpoint != 'static':
            response.headers['Cache-Control'] = 'no-store'
        return response
