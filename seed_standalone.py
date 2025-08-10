"""
Standalone seeder for E-Hall Pass.

Usage (Windows):
  .venv\Scripts\python seed_standalone.py

This script creates the app context, ensures tables exist, and inserts demo data.
It bypasses Flask CLI shell/quoting issues.
"""

from __future__ import annotations

from app import create_app, db
from app.models.seed import seed_data


def main() -> None:
    app = create_app()
    with app.app_context():
        print("Ensuring tables exist...")
        db.create_all()
        print("Seeding demo data...")
        seed_data()
        db.session.commit()
        print("Seed complete. You can login with:")
        print("  admin@example.com / password")
        print("  teacher@example.com / password")
        print("  student@example.com / password")


if __name__ == "__main__":
    main()
