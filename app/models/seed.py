from __future__ import annotations

from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash

from app import db
from .core import (
    Role,
    User,
    Destination,
    Pass,
    PassAssignment,
    PassState,
    Setting,
    LogEntry,
    ClassPeriod,
    StudentEnrollment,
    Kiosk,
)


def seed_data() -> None:
    # Roles
    role_names = ["Admin", "Teacher", "Student"]
    roles = {r.name: r for r in Role.query.filter(Role.name.in_(role_names)).all()}
    for name in role_names:
        if name not in roles:
            r = Role(name=name)
            db.session.add(r)
            roles[name] = r

    db.session.flush()

    # Users
    def get_or_create_user(email: str, full_name: str, role_name: str) -> User:
        user = User.query.filter_by(email=email).first()
        if not user:
            user = User(
                email=email,
                full_name=full_name,
                password_hash=generate_password_hash("password"),
                role_id=roles[role_name].id,
                is_active_flag=1,
            )
            db.session.add(user)
        return user

    admin = get_or_create_user("admin@example.com", "Alice Admin", "Admin")
    teacher = get_or_create_user("teacher@example.com", "Tom Teacher", "Teacher")
    student = get_or_create_user("student@example.com", "Sam Student", "Student")

    # Destinations
    def get_or_create_destination(name: str, default_minutes: int, max_concurrent: int) -> Destination:
        d = Destination.query.filter_by(name=name).first()
        if not d:
            d = Destination(name=name, default_minutes=default_minutes, max_concurrent=max_concurrent)
            db.session.add(d)
        return d

    restroom = get_or_create_destination("Restroom", default_minutes=5, max_concurrent=2)
    nurse = get_or_create_destination("Nurse", default_minutes=10, max_concurrent=1)
    counselor = get_or_create_destination("Counselor", default_minutes=15, max_concurrent=-1)

    db.session.flush()

    # Class Periods and Enrollment
    cp = ClassPeriod.query.filter_by(name="Algebra 1 - P1", teacher_id=teacher.id).first()
    if not cp:
        cp = ClassPeriod(name="Algebra 1 - P1", teacher_id=teacher.id, room="101", is_active=1)
        db.session.add(cp)
        db.session.flush()

    enrollment = StudentEnrollment.query.filter_by(student_id=student.id, class_period_id=cp.id).first()
    if not enrollment:
        enrollment = StudentEnrollment(student_id=student.id, class_period_id=cp.id, is_active=1)
        db.session.add(enrollment)

    # Settings
    def set_setting(key: str, value: str, scope: str = "global") -> None:
        existing = Setting.query.filter_by(key=key, scope=scope).first()
        if existing:
            existing.value = value
        else:
            db.session.add(Setting(key=key, value=value, scope=scope))

    set_setting("kiosk_auto_refresh_seconds", "10")
    set_setting("near_expiry_seconds", "120")
    # Prefer class-period-based kiosk auto-assign for demo (legacy global)
    set_setting("kiosk_class_period_id", str(cp.id))

    # Create a demo kiosk bound to the class period with a generated 32-char token
    import secrets
    token = secrets.token_urlsafe(24)[:32]  # ~192 bits, 32 chars
    existing_kiosk = Kiosk.query.filter_by(token=token).first()
    if not existing_kiosk:
        kiosk = Kiosk(
            token=token,
            name="Room 101 Kiosk",
            room="101",
            class_period_id=cp.id,
            teacher_id=teacher.id,
            is_active=1,
        )
        db.session.add(kiosk)

    db.session.commit()
    print(f"Demo kiosk token: {token}")

    # Example active pass (approved)
    existing_active = (
        Pass.query.filter_by(student_id=student.id, destination_id=restroom.id, state=PassState.ACTIVE).first()
    )
    if not existing_active:
        issued = datetime.utcnow()
        expires = issued + timedelta(minutes=restroom.default_minutes)
        p = Pass(
            student_id=student.id,
            destination_id=restroom.id,
            issued_at=issued,
            expires_at=expires,
            state=PassState.ACTIVE,
        )
        db.session.add(p)
        db.session.flush()
        db.session.add(PassAssignment(pass_id=p.id, teacher_id=teacher.id))
        db.session.add(
            LogEntry(
                actor_id=teacher.id,
                action="pass_issued",
                target_type="pass",
                target_id=p.id,
                message=f"Issued to {student.full_name} for {restroom.name}",
            )
        )
        db.session.commit()
