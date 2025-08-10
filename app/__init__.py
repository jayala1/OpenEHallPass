from __future__ import annotations

from pathlib import Path
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect

db = SQLAlchemy()
login_manager = LoginManager()
# CSRF disabled globally for demo per user request
csrf = None


def create_app() -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    # Basic config
    # Ensure SECRET_KEY is set for session and CSRF protection
    app.config["SECRET_KEY"] = app.config.get("SECRET_KEY") or "dev-secret-change-me"
    instance_path = Path(app.instance_path)
    instance_path.mkdir(parents=True, exist_ok=True)
    db_path = instance_path / "ehallpass.sqlite"
    app.config.setdefault("SQLALCHEMY_DATABASE_URI", f"sqlite:///{db_path}")
    app.config.setdefault("SQLALCHEMY_TRACK_MODIFICATIONS", False)

    # Init extensions
    db.init_app(app)
    login_manager.init_app(app)
    # CSRF disabled globally for demo; do not initialize
    login_manager.login_view = "auth.login"

    # Register blueprints
    from .routes.auth import bp as auth_bp
    from .routes.main import bp as main_bp
    from .routes.admin import bp as admin_bp
    from .routes.passes import bp as passes_bp
    from .routes.kiosk import bp as kiosk_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(passes_bp, url_prefix="/passes")
    app.register_blueprint(kiosk_bp, url_prefix="/kiosk")

    # Create DB tables if not exist (dev convenience)
    with app.app_context():
        from . import models  # noqa: F401
        db.create_all()

    return app
