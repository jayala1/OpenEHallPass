from __future__ import annotations

from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file
from flask_login import login_required, current_user
from io import StringIO, BytesIO
import csv
import base64
import json

from app import db
from app.models.core import Role, User, Destination, Pass, PassState, LogEntry, Setting, Kiosk, ClassPeriod, StudentEnrollment

bp = Blueprint("admin", __name__)


def require_admin():
    if current_user.role.name != "Admin":
        flash("Admin access required.", "danger")
        return redirect(url_for("main.dashboard"))
    return None


@bp.route("/")
@login_required
def index():
    redir = require_admin()
    if redir:
        return redir
    users = User.query.order_by(User.full_name).limit(50).all()
    destinations = Destination.query.order_by(Destination.name).all()
    active_passes = Pass.query.filter_by(state=PassState.ACTIVE).count()
    return render_template("admin/index.html", users=users, destinations=destinations, active_passes=active_passes)


# Users
@bp.route("/users")
@login_required
def users():
    redir = require_admin()
    if redir:
        return redir
    q = request.args.get("q", "").strip()
    query = User.query
    if q:
        query = query.filter(User.full_name.ilike(f"%{q}%") | User.email.ilike(f"%{q}%"))
    users = query.order_by(User.full_name).limit(200).all()
    roles = Role.query.order_by(Role.name).all()
    return render_template("admin/users.html", users=users, roles=roles, q=q)


@bp.route("/users/create", methods=["POST"])
@login_required
def users_create():
    redir = require_admin()
    if redir:
        return redir
    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip().lower()
    role_id = int(request.form.get("role_id", "0"))
    password = request.form.get("password", "").strip()
    if not full_name or not email or not role_id:
        flash("Full name, email and role are required.", "warning")
        return redirect(url_for("admin.users"))
    if User.query.filter_by(email=email).first():
        flash("Email already exists.", "warning")
        return redirect(url_for("admin.users"))
    if not password:
        flash("Password is required.", "warning")
        return redirect(url_for("admin.users"))
    from werkzeug.security import generate_password_hash
    u = User(full_name=full_name, email=email, role_id=role_id, is_active_flag=1, password_hash=generate_password_hash(password))
    db.session.add(u)
    db.session.flush()
    db.session.add(LogEntry(actor_id=current_user.id, action="user_created", target_type="user", target_id=u.id, message=email))
    db.session.commit()
    flash("User created with password.", "success")
    return redirect(url_for("admin.users"))


@bp.route("/users/<int:user_id>/toggle", methods=["POST"])
@login_required
def users_toggle(user_id: int):
    redir = require_admin()
    if redir:
        return redir
    u = db.session.get(User, user_id)
    if not u:
        flash("User not found.", "warning")
    return redirect(url_for("admin.users"))


@bp.route("/users/<int:user_id>/reset_password", methods=["POST"])
@login_required
def users_reset_password(user_id: int):
    redir = require_admin()
    if redir:
        return redir
    u = db.session.get(User, user_id)
    if not u:
        flash("User not found.", "warning")
        return redirect(url_for("admin.users"))
    new_password = request.form.get("new_password", "").strip()
    if not new_password:
        flash("New password is required.", "warning")
        return redirect(url_for("admin.users"))
    from werkzeug.security import generate_password_hash
    u.password_hash = generate_password_hash(new_password)
    db.session.add(LogEntry(actor_id=current_user.id, action="user_password_reset", target_type="user", target_id=u.id, message=u.email))
    db.session.commit()
    flash("Password reset.", "success")
    return redirect(url_for("admin.users"))
    u.is_active_flag = 0 if u.is_active_flag else 1
    db.session.add(LogEntry(actor_id=current_user.id, action="user_toggle", target_type="user", target_id=u.id))
    db.session.commit()
    flash("User status updated.", "success")
    return redirect(url_for("admin.users"))


# Destinations
@bp.route("/destinations")
@login_required
def destinations():
    redir = require_admin()
    if redir:
        return redir
    dests = Destination.query.order_by(Destination.name).all()
    return render_template("admin/destinations.html", destinations=dests)


@bp.route("/destinations/create", methods=["POST"])
@login_required
def destinations_create():
    redir = require_admin()
    if redir:
        return redir
    name = request.form.get("name", "").strip()
    default_minutes = int(request.form.get("default_minutes", "5"))
    max_concurrent = int(request.form.get("max_concurrent", "-1"))
    if not name:
        flash("Name required.", "warning")
        return redirect(url_for("admin.destinations"))
    if Destination.query.filter_by(name=name).first():
        flash("Destination name already exists.", "warning")
        return redirect(url_for("admin.destinations"))
    d = Destination(name=name, default_minutes=default_minutes, max_concurrent=max_concurrent)
    db.session.add(d)
    db.session.add(LogEntry(actor_id=current_user.id, action="dest_created", target_type="destination", target_id=d.id))
    db.session.commit()
    flash("Destination created.", "success")
    return redirect(url_for("admin.destinations"))


@bp.route("/destinations/<int:dest_id>/update", methods=["POST"])
@login_required
def destinations_update(dest_id: int):
    redir = require_admin()
    if redir:
        return redir
    d = db.session.get(Destination, dest_id)
    if not d:
        flash("Destination not found.", "warning")
        return redirect(url_for("admin.destinations"))
    d.default_minutes = int(request.form.get("default_minutes", d.default_minutes))
    d.max_concurrent = int(request.form.get("max_concurrent", d.max_concurrent))
    db.session.add(LogEntry(actor_id=current_user.id, action="dest_updated", target_type="destination", target_id=d.id))
    db.session.commit()
    flash("Destination updated.", "success")
    return redirect(url_for("admin.destinations"))


# Kiosks
@bp.route("/kiosks")
@login_required
def kiosks():
    redir = require_admin()
    if redir:
        return redir
    kiosks = Kiosk.query.order_by(Kiosk.name).all()
    periods = ClassPeriod.query.order_by(ClassPeriod.name).all()
    teachers = User.query.join(Role, Role.id == User.role_id).filter(Role.name == "Teacher", User.is_active_flag == 1).order_by(User.full_name).all()
    return render_template("admin/kiosks.html", kiosks=kiosks, periods=periods, teachers=teachers)


@bp.route("/kiosks/create", methods=["POST"])
@login_required
def kiosks_create():
    redir = require_admin()
    if redir:
        return redir
    name = request.form.get("name", "").strip()
    room = request.form.get("room", "").strip() or None
    class_period_id = request.form.get("class_period_id") or None
    teacher_id = request.form.get("teacher_id") or None
    import secrets
    token = secrets.token_urlsafe(24)[:32]
    if not name:
        flash("Name is required.", "warning")
        return redirect(url_for("admin.kiosks"))
    k = Kiosk(
        token=token,
        name=name,
        room=room,
        class_period_id=int(class_period_id) if class_period_id else None,
        teacher_id=int(teacher_id) if teacher_id else None,
        is_active=1,
    )
    db.session.add(k)
    db.session.add(LogEntry(actor_id=current_user.id, action="kiosk_created", target_type="kiosk", target_id=k.id, message=f"name={name}"))
    db.session.commit()
    flash(f"Kiosk created. Token: {token}", "success")
    return redirect(url_for("admin.kiosks"))


@bp.route("/kiosks/<int:kiosk_id>/toggle", methods=["POST"])
@login_required
def kiosks_toggle(kiosk_id: int):
    redir = require_admin()
    if redir:
        return redir
    k = db.session.get(Kiosk, kiosk_id)
    if not k:
        flash("Kiosk not found.", "warning")
        return redirect(url_for("admin.kiosks"))
    k.is_active = 0 if k.is_active else 1
    db.session.add(LogEntry(actor_id=current_user.id, action="kiosk_toggle", target_type="kiosk", target_id=k.id))
    db.session.commit()
    flash("Kiosk status updated.", "success")
    return redirect(url_for("admin.kiosks"))


@bp.route("/kiosks/<int:kiosk_id>/rotate", methods=["POST"])
@login_required
def kiosks_rotate(kiosk_id: int):
    redir = require_admin()
    if redir:
        return redir
    k = db.session.get(Kiosk, kiosk_id)
    if not k:
        flash("Kiosk not found.", "warning")
        return redirect(url_for("admin.kiosks"))
    import secrets
    k.token = secrets.token_urlsafe(24)[:32]
    db.session.add(LogEntry(actor_id=current_user.id, action="kiosk_rotated", target_type="kiosk", target_id=k.id))
    db.session.commit()
    flash(f"Kiosk token rotated. New token: {k.token}", "success")
    return redirect(url_for("admin.kiosks"))


@bp.route("/kiosks/<int:kiosk_id>/bind", methods=["POST"])
@login_required
def kiosks_bind(kiosk_id: int):
    redir = require_admin()
    if redir:
        return redir
    k = db.session.get(Kiosk, kiosk_id)
    if not k:
        flash("Kiosk not found.", "warning")
        return redirect(url_for("admin.kiosks"))
    class_period_id = request.form.get("class_period_id") or None
    teacher_id = request.form.get("teacher_id") or None
    # prefer class period bind
    k.class_period_id = int(class_period_id) if class_period_id else None
    k.teacher_id = None if class_period_id else (int(teacher_id) if teacher_id else None)
    db.session.add(LogEntry(actor_id=current_user.id, action="kiosk_bound", target_type="kiosk", target_id=k.id, message=f"cp={k.class_period_id} teacher={k.teacher_id}"))
    db.session.commit()
    flash("Kiosk binding updated.", "success")
    return redirect(url_for("admin.kiosks"))

# Settings
@bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    redir = require_admin()
    if redir:
        return redir
    if request.method == "POST":
        for key in ["kiosk_auto_refresh_seconds", "near_expiry_seconds"]:
            if key in request.form:
                value = request.form.get(key, "").strip()
                s = Setting.query.filter_by(key=key, scope="global").first()
                if s:
                    s.value = value
                else:
                    db.session.add(Setting(key=key, scope="global", value=value))
        db.session.add(LogEntry(actor_id=current_user.id, action="settings_updated", target_type="setting"))
        db.session.commit()
        flash("Settings saved.", "success")
        return redirect(url_for("admin.settings"))
    settings_map = {s.key: s.value for s in Setting.query.filter_by(scope="global").all()}
    return render_template("admin/settings.html", settings=settings_map)


# Logs and export
@bp.route("/logs")
@login_required
def logs():
    redir = require_admin()
    if redir:
        return redir
    items = LogEntry.query.order_by(LogEntry.created_at.desc()).limit(200).all()
    return render_template("admin/logs.html", items=items)


@bp.route("/logs/export")
@login_required
def logs_export():
    redir = require_admin()
    if redir:
        return redir
    si = StringIO()
    writer = csv.writer(si)
    writer.writerow(["created_at", "actor_id", "action", "target_type", "target_id", "message"])
    for l in LogEntry.query.order_by(LogEntry.created_at.desc()).all():
        writer.writerow([l.created_at, l.actor_id, l.action, l.target_type, l.target_id, l.message or ""])
    si.seek(0)
    return send_file(
        si,
        mimetype="text/csv",
        as_attachment=True,
        download_name="logs.csv",
    )


# Simple metrics
@bp.route("/metrics")
@login_required
def metrics():
    redir = require_admin()
    if redir:
        return redir
    # Top destinations by pass count
    dest_counts = (
        db.session.query(Destination.name, db.func.count(Pass.id))
        .join(Pass, Pass.destination_id == Destination.id, isouter=True)
        .group_by(Destination.id)
        .order_by(db.func.count(Pass.id).desc())
        .limit(10)
        .all()
    )
    # Frequent students
    student_counts = (
        db.session.query(User.full_name, db.func.count(Pass.id))
        .join(Pass, Pass.student_id == User.id)
        .group_by(User.id)
        .order_by(db.func.count(Pass.id).desc())
        .limit(10)
        .all()
    )
    # Peak times (hour)
    hourly = (
        db.session.query(db.func.strftime("%H", Pass.issued_at), db.func.count(Pass.id))
        .group_by(db.func.strftime("%H", Pass.issued_at))
        .order_by(db.func.count(Pass.id).desc())
        .all()
    )
    return render_template("admin/metrics.html", dest_counts=dest_counts, student_counts=student_counts, hourly=hourly)


# -----------------------------
# Bulk Import (Periods & Enrollments)
# -----------------------------
@bp.route("/import")
@login_required
def import_view():
    redir = require_admin()
    if redir:
        return redir
    return render_template("admin/import.html", report=None)


def _b64encode_dict(d: dict) -> str:
    raw = json.dumps(d).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def _b64decode_dict(s: str) -> dict:
    raw = base64.b64decode(s.encode("ascii"))
    return json.loads(raw.decode("utf-8"))


def _read_csv_upload(file_storage):
    if not file_storage:
        return []
    text = file_storage.read().decode("utf-8", errors="ignore")
    reader = csv.DictReader(text.splitlines())
    return list(reader)


@bp.route("/import/dry-run", methods=["POST"])
@login_required
def import_dry_run():
    redir = require_admin()
    if redir:
        return redir
    periods_rows = _read_csv_upload(request.files.get("periods_csv"))
    enroll_rows = _read_csv_upload(request.files.get("enrollments_csv"))

    report = {
        "periods": {"create": [], "update": [], "errors": []},
        "enrollments": {"create": [], "update": [], "errors": []},
    }

    # Periods
    for i, r in enumerate(periods_rows, start=2):  # start=2 for header offset
        name = (r.get("name") or "").strip()
        teacher_email = (r.get("teacher_email") or "").strip().lower()
        start_time = (r.get("start_time") or "").strip() or None
        end_time = (r.get("end_time") or "").strip() or None
        days_mask = (r.get("days_mask") or "").strip() or None
        is_active = 1 if (r.get("is_active") or "1").strip() == "1" else 0
        if not name or not teacher_email:
            report["periods"]["errors"].append(f"Row {i}: name and teacher_email required")
            continue
        teacher = User.query.filter_by(email=teacher_email).first()
        if not teacher:
            report["periods"]["errors"].append(f"Row {i}: teacher not found: {teacher_email}")
            continue
        existing = ClassPeriod.query.filter_by(name=name, teacher_id=teacher.id).first()
        if existing:
            report["periods"]["update"].append(
                {"id": existing.id, "name": name, "teacher_id": teacher.id, "start_time": start_time, "end_time": end_time, "days_mask": days_mask, "is_active": is_active}
            )
        else:
            report["periods"]["create"].append(
                {"name": name, "teacher_id": teacher.id, "start_time": start_time, "end_time": end_time, "days_mask": days_mask, "is_active": is_active}
            )

    # Enrollments
    for i, r in enumerate(enroll_rows, start=2):
        period_name = (r.get("class_period_name") or "").strip()
        student_email = (r.get("student_email") or "").strip().lower()
        is_active = 1 if (r.get("is_active") or "1").strip() == "1" else 0
        if not period_name or not student_email:
            report["enrollments"]["errors"].append(f"Row {i}: class_period_name and student_email required")
            continue
        period = ClassPeriod.query.filter_by(name=period_name).first()
        if not period:
            report["enrollments"]["errors"].append(f"Row {i}: class period not found: {period_name}")
            continue
        student = User.query.filter_by(email=student_email).first()
        if not student:
            report["enrollments"]["errors"].append(f"Row {i}: student not found: {student_email}")
            continue
        existing = StudentEnrollment.query.filter_by(student_id=student.id, class_period_id=period.id).first()
        if existing:
            report["enrollments"]["update"].append({"id": existing.id, "student_id": student.id, "class_period_id": period.id, "is_active": is_active})
        else:
            report["enrollments"]["create"].append({"student_id": student.id, "class_period_id": period.id, "is_active": is_active})

    payload = {
        "periods_payload": _b64encode_dict({"create": report["periods"]["create"], "update": report["periods"]["update"]}),
        "enrollments_payload": _b64encode_dict({"create": report["enrollments"]["create"], "update": report["enrollments"]["update"]}),
    }
    return render_template("admin/import.html", report={**report, **payload})


@bp.route("/import/execute", methods=["POST"])
@login_required
def import_execute():
    redir = require_admin()
    if redir:
        return redir
    try:
        periods_payload = _b64decode_dict(request.form.get("periods_payload", ""))
        enrollments_payload = _b64decode_dict(request.form.get("enrollments_payload", ""))
    except Exception:
        flash("Invalid import payload.", "danger")
        return redirect(url_for("admin.import_view"))

    created_p, updated_p = 0, 0
    for d in periods_payload.get("create", []):
        p = ClassPeriod(**d)  # type: ignore[arg-type]
        db.session.add(p)
        created_p += 1
    for d in periods_payload.get("update", []):
        p = db.session.get(ClassPeriod, d.get("id"))
        if not p:
            continue
        for k in ["name", "teacher_id", "start_time", "end_time", "days_mask", "is_active"]:
            if k in d:
                setattr(p, k, d[k])
        updated_p += 1
    db.session.flush()

    created_e, updated_e = 0, 0
    for d in enrollments_payload.get("create", []):
        e = StudentEnrollment(**d)  # type: ignore[arg-type]
        db.session.add(e)
        created_e += 1
    for d in enrollments_payload.get("update", []):
        e = db.session.get(StudentEnrollment, d.get("id"))
        if not e:
            continue
        for k in ["student_id", "class_period_id", "is_active"]:
            if k in d:
                setattr(e, k, d[k])
        updated_e += 1

    db.session.commit()
    db.session.add(
        LogEntry(
            actor_id=current_user.id,
            action="bulk_periods_import",
            target_type="class_period",
            message=f"created={created_p} updated={updated_p}",
        )
    )
    db.session.add(
        LogEntry(
            actor_id=current_user.id,
            action="bulk_enrollments_import",
            target_type="student_enrollment",
            message=f"created={created_e} updated={updated_e}",
        )
    )
    db.session.commit()
    flash(f"Import complete: Periods c/u {created_p}/{updated_p}, Enrollments c/u {created_e}/{updated_e}", "success")
    return redirect(url_for("admin.import_view"))


# -----------------------------
# Class Periods (CRUD)
# -----------------------------
@bp.route("/periods")
@login_required
def periods():
    redir = require_admin()
    if redir:
        return redir
    periods = ClassPeriod.query.order_by(ClassPeriod.name.asc()).all()
    teachers = (
        User.query.join(Role, Role.id == User.role_id)
        .filter(Role.name == "Teacher", User.is_active_flag == 1)
        .order_by(User.full_name.asc())
        .all()
    )
    return render_template("admin/periods.html", periods=periods, teachers=teachers)


@bp.route("/periods/create", methods=["POST"])
@login_required
def periods_create():
    redir = require_admin()
    if redir:
        return redir
    name = request.form.get("name", "").strip()
    teacher_id = request.form.get("teacher_id")
    start_time = request.form.get("start_time", "").strip() or None
    end_time = request.form.get("end_time", "").strip() or None
    days_mask = request.form.get("days_mask", "").strip() or None
    room = request.form.get("room", "").strip() or None
    is_active = 1 if request.form.get("is_active", "1") == "1" else 0
    if not name or not teacher_id:
        flash("Name and teacher are required.", "warning")
        return redirect(url_for("admin.periods"))
    try:
        t_id = int(teacher_id)
    except ValueError:
        flash("Invalid teacher.", "warning")
        return redirect(url_for("admin.periods"))
    p = ClassPeriod(
        name=name,
        teacher_id=t_id,
        start_time=start_time,
        end_time=end_time,
        days_mask=days_mask,
        room=room,
        is_active=is_active,
    )
    db.session.add(p)
    db.session.add(LogEntry(actor_id=current_user.id, action="period_created", target_type="class_period", target_id=p.id, message=name))
    db.session.commit()
    flash("Class period created.", "success")
    return redirect(url_for("admin.periods"))


@bp.route("/periods/<int:period_id>/update", methods=["POST"])
@login_required
def periods_update(period_id: int):
    redir = require_admin()
    if redir:
        return redir
    p = db.session.get(ClassPeriod, period_id)
    if not p:
        flash("Period not found.", "warning")
        return redirect(url_for("admin.periods"))
    name = request.form.get("name", "").strip() or p.name
    teacher_id = request.form.get("teacher_id") or str(p.teacher_id)
    start_time = request.form.get("start_time", "").strip() or None
    end_time = request.form.get("end_time", "").strip() or None
    days_mask = request.form.get("days_mask", "").strip() or None
    room = request.form.get("room", "").strip() or None
    is_active = 1 if request.form.get("is_active", "1") == "1" else 0
    try:
        p.teacher_id = int(teacher_id)
    except ValueError:
        flash("Invalid teacher.", "warning")
        return redirect(url_for("admin.periods"))
    p.name = name
    p.start_time = start_time
    p.end_time = end_time
    p.days_mask = days_mask
    p.room = room
    p.is_active = is_active
    db.session.add(LogEntry(actor_id=current_user.id, action="period_updated", target_type="class_period", target_id=p.id))
    db.session.commit()
    flash("Class period updated.", "success")
    return redirect(url_for("admin.periods"))


# -----------------------------
# Enrollments
# -----------------------------
@bp.route("/periods/<int:period_id>/enrollments")
@login_required
def period_enrollments(period_id: int):
    redir = require_admin()
    if redir:
        return redir
    p = db.session.get(ClassPeriod, period_id)
    if not p:
        flash("Period not found.", "warning")
        return redirect(url_for("admin.periods"))
    enrollments = (
        StudentEnrollment.query.filter_by(class_period_id=period_id)
        .join(User, User.id == StudentEnrollment.student_id)
        .order_by(User.full_name.asc())
        .all()
    )
    return render_template("admin/enrollments.html", period=p, enrollments=enrollments)


@bp.route("/periods/<int:period_id>/enrollments/add", methods=["POST"])
@login_required
def period_enrollments_add(period_id: int):
    redir = require_admin()
    if redir:
        return redir
    p = db.session.get(ClassPeriod, period_id)
    if not p:
        flash("Period not found.", "warning")
        return redirect(url_for("admin.periods"))
    student_email = request.form.get("student_email", "").strip().lower()
    if not student_email:
        flash("Student email is required.", "warning")
        return redirect(url_for("admin.period_enrollments", period_id=period_id))
    student = User.query.filter_by(email=student_email).first()
    if not student:
        flash("Student not found.", "warning")
        return redirect(url_for("admin.period_enrollments", period_id=period_id))
    existing = StudentEnrollment.query.filter_by(student_id=student.id, class_period_id=period_id).first()
    if existing:
        existing.is_active = 1
    else:
        db.session.add(StudentEnrollment(student_id=student.id, class_period_id=period_id, is_active=1))
    db.session.add(LogEntry(actor_id=current_user.id, action="enrollment_added", target_type="class_period", target_id=period_id, message=student_email))
    db.session.commit()
    flash("Enrollment added.", "success")
    return redirect(url_for("admin.period_enrollments", period_id=period_id))


@bp.route("/periods/<int:period_id>/enrollments/<int:enr_id>/remove", methods=["POST"])
@login_required
def period_enrollments_remove(period_id: int, enr_id: int):
    redir = require_admin()
    if redir:
        return redir
    e = db.session.get(StudentEnrollment, enr_id)
    if not e or e.class_period_id != period_id:
        flash("Enrollment not found.", "warning")
        return redirect(url_for("admin.period_enrollments", period_id=period_id))
    db.session.delete(e)
    db.session.add(LogEntry(actor_id=current_user.id, action="enrollment_removed", target_type="class_period", target_id=period_id, message=str(enr_id)))
    db.session.commit()
    flash("Enrollment removed.", "success")
    return redirect(url_for("admin.period_enrollments", period_id=period_id))
