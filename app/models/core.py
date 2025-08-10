from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from flask_login import UserMixin
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import time

from app import db, login_manager


# 5NF-oriented schema notes:
# - Roles factored into separate table; User-Role is 1..1 via FK to roles.id on users.role_id.
# - Destinations independent with defaults and concurrency caps.
# - Pass is the core fact (who, where, when, state). Teacher link via PassAssignment association.
# - Overrides are separate atomic facts tied to a Pass and performed_by (user).
# - Logs are event facts (actor, action, target_type, target_id, message).
# - Settings are atomic key/value scoped entries.
# - ClassPeriod and StudentEnrollment add routing context without duplication, maintaining 5NF.


class Role(db.Model):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)  # Admin, Teacher, Student

    users: Mapped[list["User"]] = relationship("User", back_populates="role")


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=True)  # nullable for SSO-only accounts
    is_active_flag: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), nullable=False)

    role: Mapped["Role"] = relationship("Role", back_populates="users")

    def get_id(self) -> str:
        return str(self.id)

    # Flask-Login's UserMixin.is_active is typed as always True; keep compatibility by returning True for active users.
    @property
    def is_active(self):  # type: ignore[override]
        return bool(self.is_active_flag)


@login_manager.user_loader
def load_user(user_id: str) -> Optional["User"]:
    return db.session.get(User, int(user_id))


class Destination(db.Model):
    __tablename__ = "destinations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    default_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    max_concurrent: Mapped[int] = mapped_column(Integer, nullable=False, default=-1)  # -1 = unlimited


class ClassPeriod(db.Model):
    __tablename__ = "class_periods"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    # store times as "HH:MM" strings (24h) for simplicity with SQLite, keep 5NF in separate attributes
    start_time: Mapped[str] = mapped_column(String(5), nullable=True)  # e.g., "08:30"
    end_time: Mapped[str] = mapped_column(String(5), nullable=True)    # e.g., "09:20"
    # days_mask like "1111100" for Mon..Sun; optional for schools that don't need it
    days_mask: Mapped[str] = mapped_column(String(7), nullable=True)
    # optional info
    room: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    is_active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    teacher: Mapped["User"] = relationship("User")
    enrollments: Mapped[list["StudentEnrollment"]] = relationship(
        "StudentEnrollment", back_populates="class_period", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("name", "teacher_id", name="uq_classperiod_name_teacher"),)

    def is_now_in_window(self, now: datetime) -> bool:
        if not self.start_time or not self.end_time:
            return True
        try:
            sh, sm = [int(x) for x in self.start_time.split(":")]
            eh, em = [int(x) for x in self.end_time.split(":")]
            start_minutes = sh * 60 + sm
            end_minutes = eh * 60 + em
            now_minutes = now.hour * 60 + now.minute
            in_time = start_minutes <= now_minutes <= end_minutes
            if self.days_mask and len(self.days_mask) == 7:
                # Python Monday=0 .. Sunday=6
                idx = now.weekday()
                return in_time and self.days_mask[idx] == "1"
            return in_time
        except Exception:
            return True


class StudentEnrollment(db.Model):
    __tablename__ = "student_enrollments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    class_period_id: Mapped[int] = mapped_column(ForeignKey("class_periods.id"), nullable=False)
    is_active: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    student: Mapped["User"] = relationship("User")
    class_period: Mapped["ClassPeriod"] = relationship("ClassPeriod", back_populates="enrollments")

    __table_args__ = (UniqueConstraint("student_id", "class_period_id", name="uq_enrollment_student_class"),)


class PassState(str, Enum):
    PENDING = "Pending"
    ACTIVE = "Active"
    EXPIRED = "Expired"
    CANCELLED = "Cancelled"
    DENIED = "Denied"
    ARCHIVED = "Archived"






class Pass(db.Model):
    __tablename__ = "passes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    destination_id: Mapped[int] = mapped_column(ForeignKey("destinations.id"), nullable=False)
    # Allow NULL for pending passes
    issued_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    state: Mapped[PassState] = mapped_column(SAEnum(PassState), nullable=False, default=PassState.PENDING)

    student: Mapped["User"] = relationship("User")
    destination: Mapped["Destination"] = relationship("Destination")
    assignments: Mapped[list["PassAssignment"]] = relationship(
        "PassAssignment", back_populates="pass_", cascade="all, delete-orphan"
    )
    overrides: Mapped[list["Override"]] = relationship(
        "Override", back_populates="pass_", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("(issued_at IS NULL AND expires_at IS NULL) OR (expires_at > issued_at)", name="ck_pass_time_order"),
    )

    def remaining_seconds(self) -> int:
        if self.state != PassState.ACTIVE or not self.expires_at:
            return 0
        return max(0, int((self.expires_at - datetime.utcnow()).total_seconds()))

    def mark_expired_if_needed(self) -> None:
        if self.state == PassState.ACTIVE and self.expires_at and datetime.utcnow() >= self.expires_at:
            self.state = PassState.EXPIRED


class PassAssignment(db.Model):
    __tablename__ = "pass_assignments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pass_id: Mapped[int] = mapped_column(ForeignKey("passes.id"), nullable=False)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    pass_: Mapped["Pass"] = relationship("Pass", back_populates="assignments")
    teacher: Mapped["User"] = relationship("User")

    __table_args__ = (UniqueConstraint("pass_id", "teacher_id", name="uq_pass_teacher"),)


class Override(db.Model):
    __tablename__ = "overrides"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pass_id: Mapped[int] = mapped_column(ForeignKey("passes.id"), nullable=False)
    performed_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    previous_expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    new_expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())

    pass_: Mapped["Pass"] = relationship("Pass", back_populates="overrides")
    performed_by: Mapped["User"] = relationship("User")


class LogEntry(db.Model):
    __tablename__ = "logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    target_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())

    actor: Mapped[Optional["User"]] = relationship("User")


class Setting(db.Model):
    __tablename__ = "settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    scope: Mapped[str] = mapped_column(String(120), nullable=False, default="global")
    value: Mapped[str] = mapped_column(String(500), nullable=False)

    __table_args__ = (UniqueConstraint("key", "scope", name="uq_settings_key_scope"),)


class Kiosk(db.Model):
    __tablename__ = "kiosks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)  # stores 32-char token
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    room: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    class_period_id: Mapped[Optional[int]] = mapped_column(ForeignKey("class_periods.id"), nullable=True)
    teacher_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    is_active: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    class_period: Mapped[Optional["ClassPeriod"]] = relationship("ClassPeriod")
    teacher: Mapped[Optional["User"]] = relationship("User")
