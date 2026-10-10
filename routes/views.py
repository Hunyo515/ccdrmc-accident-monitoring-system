from flask import Blueprint, render_template, current_app

views_bp = Blueprint("views", __name__)


def _ctx(active: str, **extra):
    ctx = {
        "app_name": current_app.config["APP_NAME"],
        "app_short_name": current_app.config["APP_SHORT_NAME"],
        "agency_note": current_app.config["AGENCY_NOTE"],
        "dashboard_title": current_app.config["DASHBOARD_TITLE"],
        "active": active,
    }
    ctx.update(extra)
    return ctx


@views_bp.get("/")
def overview():
    return render_template("overview.html", **_ctx("overview"))


@views_bp.get("/explorer")
def explorer():
    return render_template("explorer.html", **_ctx("explorer"))


@views_bp.get('/data')
def data():
    return render_template('data.html', **_ctx('data'))


@views_bp.get("/map")
def accident_map():
    return render_template("map.html", **_ctx("map"))


@views_bp.get("/upload")
def upload():
    return render_template("upload.html", **_ctx("data"))

