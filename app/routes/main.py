from __future__ import annotations

from datetime import datetime, timedelta

from flask import Blueprint, render_template, redirect, url_for
from flask_login import login_required, current_user

from app import db
from app.models.core import Role, User, Destination, Pass, PassState, PassAssignment, LogEntry

bp = Blueprint("main", __name__)


@bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    return redirect(url_for("auth.login"))


@bp.route("/dashboard")
@login_required
def dashboard():
    # Role-aware landing
    if current_user.role.name == "Admin":
        users_count = User.query.count()
        destinations_count = Destination.query.count()
        active_passes = Pass.query.filter_by(state=PassState.ACTIVE).count()
        return render_template(
            "admin/dashboard.html",
            users_count=users_count,
            destinations_count=destinations_count,
            active_passes=active_passes,
        )
    elif current_user.role.name == "Teacher":
        my_passes = (
            db.session.query(Pass)
            .join(PassAssignment, PassAssignment.pass_id == Pass.id)
            .filter(PassAssignment.teacher_id == current_user.id)
            .order_by(Pass.issued_at.desc())
            .limit(20)
            .all()
        )
        return render_template("teacher/dashboard.html", my_passes=my_passes)
    else:
        student_passes = (
            Pass.query.filter_by(student_id=current_user.id)
            .order_by(Pass.issued_at.desc())
            .limit(20)
            .all()
        )
        return render_template("student/dashboard.html", passes=student_passes)
