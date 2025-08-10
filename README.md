# E-Hall Pass (Flask + SQLite)

Web-based E-Hall Pass system with roles (Admin, Teacher, Student), local auth, destinations, passes, kiosk, logging, and 5NF SQLite schema.

Highlights:
- Roles: Admin, Teacher, Student
- Local auth with secure password hashing
- Pass lifecycle: Pending → Active → Expired/Cancelled/Denied/Archived
- Kiosk mode (read-only, auto-refresh)
- Admin dashboards (Users, Destinations, Kiosks, Classes/Enrollments, Import, Metrics, Logs, Settings)
- 5NF SQLite with SQLAlchemy models and foreign keys

## Quick start (Windows)

1) Create virtualenv and install deps:
```
python -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt
```

2) Initialize DB and seed (option A: Flask CLI):
```
set FLASK_APP=app
set FLASK_ENV=development
.venv\Scripts\python manage.py init-db
.venv\Scripts\python manage.py seed
```

2-alt) Initialize/seed (option B: standalone)
```
.venv\Scripts\python seed_standalone.py
```
The standalone script ensures tables exist and seeds demo data. It will also print a demo kiosk token.

3) Run server:
```
.venv\Scripts\python -m flask run --debug
```

Visit http://127.0.0.1:5000

Default logins (password: password):
- admin@example.com (Admin)
- teacher@example.com (Teacher)
- student@example.com (Student)

## Admin Features

Users
- Create user with Full name, Email, Role, and Password (Admin sets initial password)
- Activate/Deactivate users
- Reset password per user (inline on Users page)

Destinations
- Create destinations with default minutes and max concurrent (-1 unlimited)
- Update defaults and concurrency caps

Kiosks
- Create kiosk with token; optional binding to Class Period or Teacher
- Toggle active, rotate tokens, bind/unbind to class/teacher

Classes & Enrollments
- Manage Class Periods (name, teacher, optional start/end times, days mask, room, active)
- Enroll/unenroll students into class periods
- Import (CSV) tool provides dry-run and execute for bulk Periods/Enrollments

Settings
- Kiosk auto-refresh seconds
- Near-expiry warning seconds
- Optional future flags (kiosk_strict_binding, enforce_period_time_window, allow_teacher_approval_outside_period)

Metrics
- Top destinations
- Frequent students
- Peak hours

Logs
- Audit of actions: user/destination changes, pass actions, overrides, settings updates
- CSV export

## Passes

Requesting (Students)
- Request a pass to a destination
- Teacher auto-assignment logic:
  1) If a valid kiosk token is present and bound to a class period → assign that period’s teacher
  2) Else if kiosk bound to a teacher → assign that teacher
  3) Else infer from enrollments only if the student has exactly one active teacher across active enrollments
  4) Otherwise, student must select their class period before submitting
- Note: Legacy global kiosk defaults are ignored unless a kiosk token is present (prevents unintended assignment)

Teacher View
- “My Period” page to filter/manage passes for a selected class
- Approve All / Deny / Cancel / Override selected passes
- Approval sets issued_at and expires_at from destination defaults

Kiosk Mode
- Public read-only listing of active passes with time remaining
- Auto-refresh; near-expiry blinking
- Optional chime TODO

## Database (5NF-oriented)
Key tables:
- roles, users
- destinations
- passes (core fact), pass_assignments (pass↔teacher association)
- overrides (pass timer changes)
- logs (audit)
- settings (scoped key/value)
- kiosks (token-bound devices, optional binding to class period or teacher)
- class_periods (teacher-owned classes)
- student_enrollments (student↔class period)

## Project Structure
- app/
  - __init__.py (app factory, CSRF + SECRET_KEY configured)
  - models/
    - core.py (ORM models)
    - seed.py (seed helpers)
  - routes/ (blueprints: auth, main, admin, passes, kiosk)
  - templates/ (Jinja2)
  - static/ (css, js)
- manage.py (CLI for init/seed)
- seed_standalone.py (independent seeding script)
- requirements.txt

## Notes
- Google SSO/QR placeholders remain TODO.
- Kiosk auto-refresh and near-expiry blink implemented in JS/CSS.
- CSV import for classes/enrollments supported (dry-run + execute).
- Admin user password management enabled (create + reset).

## Security & CSRF
- SECRET_KEY is required and set in app/__init__.py (replace in production).
- All forms protected by CSRF via Flask-WTF.

## Development Tips
- If you change models, delete instance/ehallpass.sqlite and re-run seed.
- For kiosk testing, use the token printed by the seeder or create a kiosk in Admin > Kiosks and bind it to a class/teacher, then append ?token=YOURTOKEN to kiosk/student flows as needed.
