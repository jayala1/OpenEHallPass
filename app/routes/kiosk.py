from __future__ import annotations

from datetime import datetime

from flask import Blueprint, render_template, jsonify, request, make_response
from app import db
from app.models.core import Pass, PassState, PassAssignment, Destination, Kiosk

bp = Blueprint("kiosk", __name__)


@bp.route("/")
def view():
    # Optional token binds kiosk to a class/teacher for routing context
    token = request.args.get("token") or request.cookies.get("kiosk_token")
    kiosk = None
    banner = None
    if token:
        kiosk = Kiosk.query.filter_by(token=token, is_active=1).first()
        if kiosk:
            if kiosk.class_period:
                banner = f"Kiosk: {kiosk.name} (Room {kiosk.room or '-'}) • Class: {kiosk.class_period.name} • Teacher: {kiosk.class_period.teacher.full_name}"
            elif kiosk.teacher:
                banner = f"Kiosk: {kiosk.name} (Room {kiosk.room or '-'}) • Teacher: {kiosk.teacher.full_name}"
    resp = make_response(render_template("kiosk/index.html", kiosk_banner=banner))
    # Persist validated token
    if kiosk and not request.cookies.get("kiosk_token"):
        resp.set_cookie("kiosk_token", kiosk.token, max_age=60 * 60 * 8, samesite="Lax")  # 8 hours
    return resp


@bp.route("/data")
def data():
    # Provide JSON for auto-refresh
    now = datetime.utcnow()
    items = (
        db.session.query(Pass, Destination.name)
        .join(Destination, Pass.destination_id == Destination.id)
        .filter(Pass.state == PassState.ACTIVE)
        .order_by(Pass.issued_at.desc())
        .limit(100)
        .all()
    )
    def to_row(p: Pass, dest_name: str):
        remaining = 0
        issued_iso = p.issued_at.isoformat() + "Z" if p.issued_at else None
        expires_iso = None
        if p.expires_at:
            expires_iso = p.expires_at.isoformat() + "Z"
            remaining = max(0, int((p.expires_at - now).total_seconds()))
        return {
            "id": p.id,
            "student": p.student.full_name,
            "destination": dest_name,
            "issued_at": issued_iso,
            "expires_at": expires_iso,
            "remaining_seconds": remaining,
            "staff": ", ".join({a.teacher.full_name for a in p.assignments}) if p.assignments else "",
        }
    return jsonify([to_row(p, dname) for (p, dname) in items])
