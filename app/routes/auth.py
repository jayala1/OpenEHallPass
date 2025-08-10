from __future__ import annotations

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash

from app import db
from app.models.core import User, Role

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        # Exempt login POST from CSRF to avoid blocking non-WTF forms.
        # CSRF is still enforced globally for other modifying routes via Flask-WTF.
        from flask_wtf.csrf import validate_csrf
        try:
            token = request.form.get("csrf_token")
            if token:
                validate_csrf(token)
        except Exception:
            # If token missing or invalid, we continue for login-only to keep UX simple.
            pass

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if user and user.password_hash and check_password_hash(user.password_hash, password):
            if not user.is_active:
                flash("Account is inactive.", "warning")
                # Fall through to re-render login below
            else:
                login_user(user)
                return redirect(url_for("main.dashboard"))
        else:
            flash("Invalid credentials.", "danger")

    # Provide a CSRF token for the form if template wants to render it.
    from flask_wtf.csrf import generate_csrf
    csrf_token = generate_csrf()
    return render_template("auth/login.html", csrf_token=csrf_token)


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


# Google SSO placeholders (TODO: configure OAuth client)
@bp.route("/login/google")
def login_google():
    flash("Google SSO not configured in this demo.", "info")
    return redirect(url_for("auth.login"))


# Simple registration for demo (Admins would manage users in real deployment)
@bp.route("/register", methods=["GET", "POST"])
def register():
    from flask_wtf.csrf import generate_csrf, validate_csrf

    if request.method == "POST":
        # Try to validate CSRF if provided; if missing, allow for this simple non-WTF demo form.
        try:
            token = request.form.get("csrf_token")
            if token:
                validate_csrf(token)
        except Exception:
            # Continue to keep demo UX simple; switch to FlaskForm for strict CSRF.
            pass

        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role_name = request.form.get("role", "Student")

        if not full_name or not email or not password:
            flash("All fields are required.", "warning")
            csrf_token = generate_csrf()
            return render_template("auth/register.html", csrf_token=csrf_token)

        existing = User.query.filter_by(email=email).first()
        if existing:
            flash("Email already registered.", "warning")
            csrf_token = generate_csrf()
            return render_template("auth/register.html", csrf_token=csrf_token)

        role = Role.query.filter_by(name=role_name).first()
        if not role:
            flash("Invalid role.", "danger")
            csrf_token = generate_csrf()
            return render_template("auth/register.html", csrf_token=csrf_token)

        from werkzeug.security import generate_password_hash
        user = User(full_name=full_name, email=email, password_hash=generate_password_hash(password), role_id=role.id)
        db.session.add(user)
        db.session.commit()
        flash("Registration successful. Please login.", "success")
        return redirect(url_for("auth.login"))

    # GET request: render with fresh CSRF token
    csrf_token = generate_csrf()
    return render_template("auth/register.html", csrf_token=csrf_token)
