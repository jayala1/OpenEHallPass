from __future__ import annotations

from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user

from app import db
from app.models.core import User, Destination, Pass, PassAssignment, PassState, Override, LogEntry, Setting, ClassPeriod, StudentEnrollment, Role, Kiosk

bp = Blueprint("passes", __name__)


def is_admin() -> bool:
    return current_user.role.name == "Admin"


def is_teacher() -> bool:
    return current_user.role.name == "Teacher"


def is_student() -> bool:
    return current_user.role.name == "Student"


def get_setting(key: str, default: str) -> str:
    s = Setting.query.filter_by(key=key, scope="global").first()
    return s.value if s else default


@bp.route("/")
@login_required
def index():
    if is_teacher() or is_admin():
        # Auto-expire any passes whose time has elapsed
        now = datetime.utcnow()
        stale = (
            db.session.query(Pass)
            .filter(Pass.state == PassState.ACTIVE, Pass.expires_at != None, Pass.expires_at <= now)  # noqa: E711
            .all()
        )
        for p in stale:
            p.state = PassState.EXPIRED
            db.session.add(
                LogEntry(
                    actor_id=current_user.id if current_user.is_authenticated else None,
                    action="pass_auto_expired",
                    target_type="pass",
                    target_id=p.id,
                    message="expired by system",
                )
            )
        if stale:
            db.session.commit()

        query_pending = db.session.query(Pass).filter(Pass.state == PassState.PENDING)
        query_active = db.session.query(Pass).filter(Pass.state == PassState.ACTIVE)

        # Teachers only see passes assigned to them; Admin sees all
        if is_teacher():
            query_pending = (
                query_pending.join(PassAssignment, PassAssignment.pass_id == Pass.id)
                .filter(PassAssignment.teacher_id == current_user.id)
            )
            query_active = (
                query_active.join(PassAssignment, PassAssignment.pass_id == Pass.id)
                .filter(PassAssignment.teacher_id == current_user.id)
            )

        pending = query_pending.order_by(Pass.id.desc()).limit(100).all()
        active = query_active.order_by(Pass.issued_at.desc()).limit(100).all()
        return render_template("passes/index.html", passes=pending + active)
    else:
        mine = Pass.query.filter_by(student_id=current_user.id).order_by(Pass.issued_at.desc()).limit(50).all()
        return render_template("passes/mine.html", passes=mine)


@bp.route("/request", methods=["GET", "POST"])
@login_required
def request_pass():
    if not is_student():
        flash("Only students can request passes.", "warning")
        return redirect(url_for("passes.index"))

    destinations = Destination.query.order_by(Destination.name).all()

    # Settings
    kiosk_strict = (get_setting("kiosk_strict_binding", "true") == "true")
    enforce_window = (get_setting("enforce_period_time_window", "false") == "true")
    # Safety: if there is no kiosk token, treat as non-kiosk so old defaults can't leak through
    is_kiosk = False

    # Resolve kiosk auto-assign: prefer kiosk token binding over legacy global settings
    kiosk_cp_id = None
    kiosk_teacher_id = None
    kiosk_token = request.args.get("token") or request.cookies.get("kiosk_token")
    if kiosk_token:
        kiosk = Kiosk.query.filter_by(token=kiosk_token, is_active=1).first()
        if kiosk:
            is_kiosk = True
            if kiosk.class_period_id:
                kiosk_cp_id = kiosk.class_period_id
            elif kiosk.teacher_id:
                kiosk_teacher_id = kiosk.teacher_id
    # IMPORTANT: Do NOT fall back to legacy global kiosk settings unless an actual kiosk token is present
    # This prevents unintended auto-assignment to the seeded teacher.
    # If you still want legacy fallback behavior, re-enable the block below.
    # if not kiosk_cp_id and not kiosk_teacher_id and is_kiosk:
    #     s_cp = Setting.query.filter_by(key="kiosk_class_period_id", scope="global").first()
    #     s_t = Setting.query.filter_by(key="kiosk_teacher_id", scope="global").first()
    #     if s_cp and s_cp.value and s_cp.value.isdigit():
    #         kiosk_cp_id = int(s_cp.value)
    #     if s_t and s_t.value and s_t.value.isdigit():
    #         kiosk_teacher_id = int(s_t.value)

    # Student enrollments (for class period selection)
    enrollments = (
        db.session.query(StudentEnrollment)
        .filter(StudentEnrollment.student_id == current_user.id, StudentEnrollment.is_active == 1)
        .join(ClassPeriod, ClassPeriod.id == StudentEnrollment.class_period_id)
        .order_by(ClassPeriod.name.asc())
        .all()
    )

    auto_assigned_note = None
    target_teacher_id = None
    selected_cp = None

    # Determine target teacher:
    # 1) Prefer kiosk class-period binding if present.
    if kiosk_cp_id:
        selected_cp = db.session.get(ClassPeriod, kiosk_cp_id)
        if selected_cp:
            target_teacher_id = selected_cp.teacher_id
            auto_assigned_note = f"Auto-assigned to {selected_cp.teacher.full_name} ({selected_cp.name})"
    # 2) Else if kiosk is bound to a teacher, use that.
    elif kiosk_teacher_id:
        t = db.session.get(User, kiosk_teacher_id)
        if t:
            target_teacher_id = t.id
            auto_assigned_note = f"Auto-assigned to {t.full_name}"
    # 3) Else infer teacher from the student's active enrollments if exactly one teacher is associated.
    if not target_teacher_id:
        # Only consider ACTIVE enrollments for ACTIVE teachers (Teacher role and is_active_flag=1)
        enrolled_periods = (
            db.session.query(ClassPeriod)
            .join(StudentEnrollment, StudentEnrollment.class_period_id == ClassPeriod.id)
            .join(User, User.id == ClassPeriod.teacher_id)
            .join(Role, Role.id == User.role_id)
            .filter(
                StudentEnrollment.student_id == current_user.id,
                StudentEnrollment.is_active == 1,
                ClassPeriod.is_active == 1,
                Role.name == "Teacher",
                User.is_active_flag == 1,
            )
            .all()
        )
        unique_teachers = {p.teacher_id for p in enrolled_periods}
        if len(unique_teachers) == 1:
            target_teacher_id = next(iter(unique_teachers))
            # Also pick a representative period for time window check/note
            if enrolled_periods:
                selected_cp = enrolled_periods[0]
                auto_assigned_note = f"Auto-assigned from enrollment: {selected_cp.teacher.full_name} ({selected_cp.name})"

    if request.method == "POST":
        dest_id = int(request.form.get("destination_id", "0"))
        dest = db.session.get(Destination, dest_id)
        if not dest:
            flash("Invalid destination.", "warning")
            return render_template("passes/request.html", destinations=destinations, enrollments=enrollments, auto_assigned_note=auto_assigned_note)

        # If strict kiosk binding: do not allow user override; use kiosk-bound values
        if kiosk_strict and is_kiosk and (kiosk_cp_id or kiosk_teacher_id):
            pass  # target_teacher_id already determined above
        else:
            # Derive from selected class period (only from student's enrollments)
            sel_cp_id = request.form.get("class_period_id")
            if sel_cp_id:
                try:
                    cp_id = int(sel_cp_id)
                except ValueError:
                    cp_id = 0
                if cp_id:
                    cp = db.session.get(ClassPeriod, cp_id)
                    # validate student is enrolled in this class
                    if cp and StudentEnrollment.query.filter_by(student_id=current_user.id, class_period_id=cp.id, is_active=1).first():
                        selected_cp = cp
                        target_teacher_id = cp.teacher_id
            # If still not resolved and there is exactly one enrolled teacher, auto-assign that teacher
            if not target_teacher_id:
                enrolled_periods = (
                    db.session.query(ClassPeriod)
                    .join(StudentEnrollment, StudentEnrollment.class_period_id == ClassPeriod.id)
                    .join(User, User.id == ClassPeriod.teacher_id)
                    .join(Role, Role.id == User.role_id)
                    .filter(
                        StudentEnrollment.student_id == current_user.id,
                        StudentEnrollment.is_active == 1,
                        ClassPeriod.is_active == 1,
                        Role.name == "Teacher",
                        User.is_active_flag == 1,
                    )
                    .all()
                )
                unique_teachers = {p.teacher_id for p in enrolled_periods}
                if len(unique_teachers) == 1:
                    target_teacher_id = next(iter(unique_teachers))
                    if enrolled_periods:
                        selected_cp = enrolled_periods[0]

        if not target_teacher_id:
            # If there are multiple active enrolled periods, force selection and display options.
            flash("Please select a class period (or use a kiosk).", "warning")
            return render_template("passes/request.html", destinations=destinations, enrollments=enrollments, auto_assigned_note=auto_assigned_note)

        # Enforce time window if enabled
        if enforce_window and selected_cp:
            if not selected_cp.is_now_in_window(datetime.utcnow()):
                flash("Requests are restricted outside the class period time window.", "danger")
                return render_template("passes/request.html", destinations=destinations, enrollments=enrollments, auto_assigned_note=auto_assigned_note)

        # Create pending pass and assign to target teacher
        p = Pass(student_id=current_user.id, destination_id=dest.id, state=PassState.PENDING, issued_at=None, expires_at=None)
        db.session.add(p)
        db.session.flush()
        db.session.add(PassAssignment(pass_id=p.id, teacher_id=target_teacher_id))
        msg = f"to_teacher:{target_teacher_id}"
        if kiosk_token:
            msg += f" via_kiosk:{kiosk_token[:6]}"
        if selected_cp:
            msg += f" period:{selected_cp.id}"
        db.session.add(LogEntry(actor_id=current_user.id, action="pass_requested", target_type="pass", target_id=p.id, message=msg))
        db.session.commit()
        flash("Pass requested. Awaiting teacher approval.", "success")
        return redirect(url_for("passes.mine"))

    return render_template("passes/request.html", destinations=destinations, enrollments=enrollments, auto_assigned_note=auto_assigned_note)


@bp.route("/mine")
@login_required
def mine():
    passes = Pass.query.filter_by(student_id=current_user.id).order_by(Pass.issued_at.desc()).limit(50).all()
    return render_template("passes/mine.html", passes=passes)


@bp.route("/my-period", methods=["GET"])
@login_required
def my_period():
    if not is_teacher() and not is_admin():
        flash("Teacher/Admin access required.", "danger")
        return redirect(url_for("passes.index"))

    # Determine filter by selected period (optional)
    period_id = request.args.get("period_id")
    period = None
    if period_id and period_id.isdigit():
        period = db.session.get(ClassPeriod, int(period_id))

    # Build base query for passes assigned to current teacher (or all if admin)
    base_pending = db.session.query(Pass).filter(Pass.state == PassState.PENDING)
    base_active = db.session.query(Pass).filter(Pass.state == PassState.ACTIVE)

    # Restrict by teacher unless admin
    if is_teacher():
        base_pending = base_pending.join(PassAssignment, PassAssignment.pass_id == Pass.id).filter(
            PassAssignment.teacher_id == current_user.id
        )
        base_active = base_active.join(PassAssignment, PassAssignment.pass_id == Pass.id).filter(
            PassAssignment.teacher_id == current_user.id
        )

    # Further filter by period (if provided) to passes requested by students enrolled in that class
    if period:
        student_ids = [e.student_id for e in StudentEnrollment.query.filter_by(class_period_id=period.id, is_active=1).all()]
        if student_ids:
            base_pending = base_pending.filter(Pass.student_id.in_(student_ids))
            base_active = base_active.filter(Pass.student_id.in_(student_ids))

    pending = base_pending.order_by(Pass.id.desc()).all()
    active = base_active.order_by(Pass.issued_at.desc().nullslast()).all()

    # Teacher's available periods for filter
    teacher_periods = []
    if is_teacher():
        teacher_periods = ClassPeriod.query.filter_by(teacher_id=current_user.id, is_active=1).order_by(ClassPeriod.name).all()

    return render_template("passes/my_period.html", pending=pending, active=active, teacher_periods=teacher_periods, selected_period=period)


@bp.route("/my-period/approve_all", methods=["POST"])
@login_required
def my_period_approve_all():
    if not is_teacher() and not is_admin():
        flash("Teacher/Admin access required.", "danger")
        return redirect(url_for("passes.my_period"))

    # Optional period filter
    period_id = request.form.get("period_id")
    period = None
    if period_id and period_id.isdigit():
        period = db.session.get(ClassPeriod, int(period_id))
    q = db.session.query(Pass).filter(Pass.state == PassState.PENDING)
    if is_teacher():
        q = q.join(PassAssignment, PassAssignment.pass_id == Pass.id).filter(PassAssignment.teacher_id == current_user.id)
    if period:
        student_ids = [e.student_id for e in StudentEnrollment.query.filter_by(class_period_id=period.id, is_active=1).all()]
        if student_ids:
            q = q.filter(Pass.student_id.in_(student_ids))
    now = datetime.utcnow()
    updated = 0
    for p in q.all():
        dest = db.session.get(Destination, p.destination_id)
        minutes = dest.default_minutes if dest else 5
        p.issued_at = now
        p.expires_at = now + timedelta(minutes=minutes)
        p.state = PassState.ACTIVE
        db.session.add(LogEntry(actor_id=current_user.id, action="pass_approved", target_type="pass", target_id=p.id, message="batch"))
        updated += 1
    if updated:
        db.session.commit()
        flash(f"Approved {updated} pending pass(es).", "success")
    else:
        flash("No pending passes to approve.", "info")
    return redirect(url_for("passes.my_period", period_id=period_id) if period_id else url_for("passes.my_period"))


@bp.route("/my-period/deny_selected", methods=["POST"])
@login_required
def my_period_deny_selected():
    if not is_teacher() and not is_admin():
        flash("Teacher/Admin access required.", "danger")
        return redirect(url_for("passes.my_period"))
    ids = request.form.getlist("pass_ids")
    if not ids:
        flash("No passes selected.", "info")
        return redirect(url_for("passes.my_period"))
    q = db.session.query(Pass).filter(Pass.id.in_(ids), Pass.state == PassState.PENDING)
    if is_teacher():
        q = q.join(PassAssignment, PassAssignment.pass_id == Pass.id).filter(PassAssignment.teacher_id == current_user.id)
    count = 0
    for p in q.all():
        p.state = PassState.DENIED
        db.session.add(LogEntry(actor_id=current_user.id, action="pass_denied", target_type="pass", target_id=p.id, message="batch"))
        count += 1
    if count:
        db.session.commit()
        flash(f"Denied {count} pass(es).", "success")
    else:
        flash("No pending passes in selection.", "info")
    return redirect(url_for("passes.my_period"))


@bp.route("/my-period/cancel_selected", methods=["POST"])
@login_required
def my_period_cancel_selected():
    if not is_teacher() and not is_admin():
        flash("Teacher/Admin access required.", "danger")
        return redirect(url_for("passes.my_period"))
    ids = request.form.getlist("pass_ids")
    if not ids:
        flash("No passes selected.", "info")
        return redirect(url_for("passes.my_period"))
    q = db.session.query(Pass).filter(Pass.id.in_(ids), Pass.state == PassState.ACTIVE)
    if is_teacher():
        q = q.join(PassAssignment, PassAssignment.pass_id == Pass.id).filter(PassAssignment.teacher_id == current_user.id)
    count = 0
    for p in q.all():
        p.state = PassState.CANCELLED
        db.session.add(LogEntry(actor_id=current_user.id, action="pass_cancelled", target_type="pass", target_id=p.id, message="batch"))
        count += 1
    if count:
        db.session.commit()
        flash(f"Cancelled {count} pass(es).", "success")
    else:
        flash("No active passes in selection.", "info")
    return redirect(url_for("passes.my_period"))


@bp.route("/my-period/override_selected", methods=["POST"])
@login_required
def my_period_override_selected():
    if not is_teacher() and not is_admin():
        flash("Teacher/Admin access required.", "danger")
        return redirect(url_for("passes.my_period"))
    ids = request.form.getlist("pass_ids")
    add_minutes = int(request.form.get("add_minutes", "0"))
    reason = request.form.get("reason", "").strip() or None
    if not ids or add_minutes <= 0:
        flash("Select passes and specify minutes > 0.", "warning")
        return redirect(url_for("passes.my_period"))
    q = db.session.query(Pass).filter(Pass.id.in_(ids), Pass.state == PassState.ACTIVE)
    if is_teacher():
        q = q.join(PassAssignment, PassAssignment.pass_id == Pass.id).filter(PassAssignment.teacher_id == current_user.id)
    count = 0
    for p in q.all():
        if not p.expires_at:
            continue
        prev = p.expires_at
        p.expires_at = p.expires_at + timedelta(minutes=add_minutes)
        db.session.add(Override(pass_id=p.id, performed_by_id=current_user.id, previous_expires_at=prev, new_expires_at=p.expires_at, reason=reason))
        action = "override_admin" if is_admin() else "override_teacher"
        db.session.add(LogEntry(actor_id=current_user.id, action=action, target_type="pass", target_id=p.id, message=reason))
        count += 1
    if count:
        db.session.commit()
        flash(f"Overridden {count} pass(es) by +{add_minutes} minutes.", "success")
    else:
        flash("No active passes in selection.", "info")
    return redirect(url_for("passes.my_period"))


@bp.route("/my-period/stats", methods=["GET"])
@login_required
def my_period_stats():
    if not is_teacher() and not is_admin():
        return jsonify({"pending_count": 0})
    q = db.session.query(Pass).filter(Pass.state == PassState.PENDING)
    if is_teacher():
        q = q.join(PassAssignment, PassAssignment.pass_id == Pass.id).filter(PassAssignment.teacher_id == current_user.id)
    return jsonify({"pending_count": q.count(), "ts": datetime.utcnow().isoformat() + "Z"})


@bp.route("/approve/<int:pass_id>", methods=["POST"])
@login_required
def approve(pass_id: int):
    if not (is_teacher() or is_admin()):
        flash("Teacher/Admin required to approve.", "danger")
        return redirect(url_for("passes.index"))

    p = db.session.get(Pass, pass_id)
    if not p or p.state not in (PassState.PENDING, PassState.ACTIVE):
        flash("Pass not found or not in approvable state.", "warning")
        return redirect(url_for("passes.index"))

    # Enforcement settings
    enforce_window = (get_setting("enforce_period_time_window", "false") == "true")
    allow_outside = (get_setting("allow_teacher_approval_outside_period", "true") == "true")

    # If pending, evaluate optional time window using any linked class period (via teacher).
    selected_cp = None
    if enforce_window:
        # Heuristic: pick a class period for the approving teacher where the student is enrolled.
        if is_teacher():
            # teacher's periods
            t_periods = ClassPeriod.query.filter_by(teacher_id=current_user.id, is_active=1).all()
            if t_periods:
                student_period = (
                    db.session.query(ClassPeriod)
                    .join(StudentEnrollment, StudentEnrollment.class_period_id == ClassPeriod.id)
                    .filter(StudentEnrollment.student_id == p.student_id, ClassPeriod.teacher_id == current_user.id, StudentEnrollment.is_active == 1)
                    .first()
                )
                selected_cp = student_period
        elif is_admin():
            # For admin, we attempt to pick any period where the student is enrolled whose teacher is assigned
            assigned_teacher = (
                db.session.query(User)
                .join(PassAssignment, PassAssignment.teacher_id == User.id)
                .filter(PassAssignment.pass_id == p.id)
                .first()
            )
            if assigned_teacher:
                selected_cp = (
                    db.session.query(ClassPeriod)
                    .join(StudentEnrollment, StudentEnrollment.class_period_id == ClassPeriod.id)
                    .filter(StudentEnrollment.student_id == p.student_id, ClassPeriod.teacher_id == assigned_teacher.id, StudentEnrollment.is_active == 1)
                    .first()
                )

        if selected_cp and not selected_cp.is_now_in_window(datetime.utcnow()):
            if not allow_outside:
                flash("Approval blocked: outside class period time window.", "danger")
                return redirect(url_for("passes.index"))
            else:
                flash("Warning: approving outside class period time window.", "warning")

    # On approval: if pending, start the timer from now and set active
    now = datetime.utcnow()
    if p.state == PassState.PENDING:
        dest = db.session.get(Destination, p.destination_id)
        minutes = dest.default_minutes if dest else 5
        p.issued_at = now
        p.expires_at = now + timedelta(minutes=minutes)
        p.state = PassState.ACTIVE

    # Assign teacher (track staff)
    assigned = PassAssignment.query.filter_by(pass_id=p.id, teacher_id=current_user.id).first()
    if not assigned:
        db.session.add(PassAssignment(pass_id=p.id, teacher_id=current_user.id))

    db.session.add(LogEntry(actor_id=current_user.id, action="pass_approved", target_type="pass", target_id=p.id, message="approved"))
    db.session.commit()
    flash("Approved", "success")
    return redirect(url_for("passes.index"))


@bp.route("/deny/<int:pass_id>", methods=["POST"])
@login_required
def deny(pass_id: int):
    if not (is_teacher() or is_admin()):
        flash("Teacher/Admin required to deny.", "danger")
        return redirect(url_for("passes.index"))
    p = db.session.get(Pass, pass_id)
    if not p:
        flash("Pass not found.", "warning")
        return redirect(url_for("passes.index"))
    if p.state != PassState.PENDING:
        flash("Only pending passes can be denied.", "warning")
        return redirect(url_for("passes.index"))
    p.state = PassState.DENIED
    db.session.add(LogEntry(actor_id=current_user.id, action="pass_denied", target_type="pass", target_id=p.id))
    db.session.commit()
    flash("Denied", "danger")
    return redirect(url_for("passes.index"))


@bp.route("/cancel/<int:pass_id>", methods=["POST"])
@login_required
def cancel(pass_id: int):
    p = db.session.get(Pass, pass_id)
    if not p:
        flash("Pass not found.", "warning")
        return redirect(url_for("passes.index"))
    # Students can cancel their own; teachers/admin can cancel any
    if not (is_admin() or is_teacher() or p.student_id == current_user.id):
        flash("Not authorized.", "danger")
        return redirect(url_for("passes.index"))
    if p.state in (PassState.CANCELLED, PassState.EXPIRED, PassState.ARCHIVED, PassState.DENIED):
        flash("Pass is not active.", "warning")
        return redirect(url_for("passes.index"))
    p.state = PassState.CANCELLED
    db.session.add(LogEntry(actor_id=current_user.id, action="pass_cancelled", target_type="pass", target_id=p.id))
    db.session.commit()
    flash("Pass cancelled.", "success")
    return redirect(url_for("passes.index"))


@bp.route("/override/<int:pass_id>", methods=["POST"])
@login_required
def override(pass_id: int):
    if not (is_teacher() or is_admin()):
        flash("Teacher/Admin required to override.", "danger")
        return redirect(url_for("passes.index"))

    p = db.session.get(Pass, pass_id)
    if not p:
        flash("Pass not found.", "warning")
        return redirect(url_for("passes.index"))

    minutes = int(request.form.get("add_minutes", "0"))
    reason = request.form.get("reason", "").strip() or None
    prev = p.expires_at
    p.expires_at = p.expires_at + timedelta(minutes=minutes)
    db.session.add(
        Override(
            pass_id=p.id,
            performed_by_id=current_user.id,
            previous_expires_at=prev,
            new_expires_at=p.expires_at,
            reason=reason,
        )
    )

    action = "override_admin" if is_admin() else "override_teacher"
    db.session.add(LogEntry(actor_id=current_user.id, action=action, target_type="pass", target_id=p.id, message=reason))
    db.session.commit()

    if not is_admin():
        # Warning for teacher override
        flash("Timer overridden. Warning logged.", "warning")
    else:
        flash("Timer overridden.", "success")

    return redirect(url_for("passes.index"))
