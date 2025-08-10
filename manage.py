import click
from datetime import timedelta
from app import create_app, db
from app.models.seed import seed_data

app = create_app()


@app.cli.command("init-db")
def init_db():
    """Create all tables."""
    with app.app_context():
        db.create_all()
        click.echo("Database initialized.")


@app.cli.command("drop-db")
def drop_db():
    """Drop all tables."""
    with app.app_context():
        db.drop_all()
        click.echo("Database dropped.")


@app.cli.command("seed")
def seed():
    """Seed initial roles, users, destinations, settings."""
    with app.app_context():
        seed_data()
        click.echo("Seed data inserted.")


if __name__ == "__main__":
    # Convenience run for python manage.py
    app.run(debug=True)
