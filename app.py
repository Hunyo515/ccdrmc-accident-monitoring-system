import os
from pathlib import Path

from flask import Flask
from markupsafe import Markup

from config import Config
from arm.pipeline import pipeline
from services import prescription_service

ICONS_DIR = Path(__file__).resolve().parent / "static" / "icons"
_icon_cache: dict[str, str] = {}


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    from routes.auth import init_auth
    init_auth(app)

    # Mine (or load cached) association rules once at startup so every
    # request is served from memory instead of re-mining on demand.
    try:
        pipeline.load_data()
        pipeline.run()
    except Exception:
        app.logger.exception("Database unavailable at startup; sign-in remains available")
        pipeline.data = None

    from flask import request, jsonify, render_template
    from services import storage_service
    @app.before_request
    def database_availability():
        from flask import session
        if not session.get('authenticated') or request.endpoint in ('static', 'auth.login', 'auth.logout') or request.endpoint is None:
            return
        if storage_service.backend() != 'oracle':
            return
        try:
            with storage_service.connect() as connection, connection.cursor() as cursor:
                cursor.execute('SELECT REVISION FROM MDRRMC_STATE WHERE STATE_ID=1')
                cursor.fetchone()
            if pipeline.data is None:
                pipeline.load_data()
                pipeline.run(force=True)
        except Exception:
            if request.path.startswith('/api/'):
                return jsonify(error='Database unavailable. Please reconnect; no records were saved.'), 503
            return render_template('database_unavailable.html'), 503

    @app.errorhandler(503)
    def database_error(error):
        return jsonify(error='Database unavailable. Please reconnect; no records were saved.'),503


    # Load the supplied prescription catalog. A malformed file stops
    # startup with a specific message rather than failing on the first request.
    prescription_service.init(Path(app.config["PRESCRIPTIONS_PATH"]))

    from routes.views import views_bp
    from routes.api import api_bp
    app.register_blueprint(views_bp)
    app.register_blueprint(api_bp)
    from routes.review import review_bp
    app.register_blueprint(review_bp)
    from routes.dataset import dataset_bp
    app.register_blueprint(dataset_bp)
    import oracledb
    @app.errorhandler(oracledb.Error)
    def oracle_error(error):
        app.logger.exception("Oracle operation failed")
        return jsonify(error="Database unavailable. Please reconnect; no records were saved."),503

    @app.context_processor
    def inject_meta():
        cat = prescription_service.get()
        return {
            "rule_meta": pipeline.meta,
            "catalog_stats": {"total": len(cat.entries), "active": len(cat.active)},
        }

    @app.context_processor
    def inject_brand_lines():
        # Wraps the app name onto two roughly-balanced lines at the space
        # closest to the middle, so the sidebar never shows a cramped
        # single line or an awkward organic 3-line wrap.
        name = app.config["APP_NAME"]
        spaces = [i for i, ch in enumerate(name) if ch == " "]
        if not spaces:
            return {"app_name_line1": name, "app_name_line2": ""}
        mid = len(name) / 2
        split_at = min(spaces, key=lambda i: abs(i - mid))
        return {"app_name_line1": name[:split_at], "app_name_line2": name[split_at + 1:]}

    def icon(name: str, cls: str = "") -> Markup:
        """Inline an SVG icon (Lucide, vendored under static/icons/) with an optional CSS class."""
        if name not in _icon_cache:
            path = ICONS_DIR / f"{name}.svg"
            _icon_cache[name] = path.read_text() if path.exists() else ""
        svg = _icon_cache[name]
        if cls and svg:
            svg = svg.replace('class="lucide', f'class="lucide {cls}', 1)
        return Markup(svg)

    app.jinja_env.globals["icon"] = icon

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
