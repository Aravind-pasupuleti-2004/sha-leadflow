"""Flask CLI commands for setup, demo data, and score maintenance."""

from __future__ import annotations

import os
import time
from datetime import timedelta

import click
from flask import current_app
from flask.cli import with_appcontext
from sqlalchemy import func

from .extensions import db
from .models import FollowUp, Lead, User, utcnow
from .services.leads import create_lead
from .services.scoring import recalculate_score
from .services.validation import EMAIL_RE, normalize_email, normalize_phone
from .services.jobs import get_due_jobs, process_job
from .services.automation import process_pending_automation_events
from .services.whatsapp import retry_failed_messages
from .utils import local_today


def _create_admin(email: str, password: str, name: str, force: bool = False) -> bool:
    normalized = normalize_email(email)
    if not normalized or not EMAIL_RE.match(normalized):
        raise click.ClickException("Provide a valid administrator email address.")
    if len(password) < 10 or password in {
        "change-this-before-first-run",
        "replace-with-a-long-random-value",
    }:
        raise click.ClickException(
            "Use a unique password with at least 10 characters (not the example placeholder)."
        )
    existing = db.session.scalars(db.select(User).where(User.normalized_email == normalized)).first()
    if existing and not force:
        click.echo("An administrator with that email already exists. Use --force to reset it.")
        return False
    if existing:
        existing.name = name.strip() or existing.name
        existing.email = normalized
        existing.set_password(password)
        existing.is_active = True
        db.session.commit()
        click.echo("Administrator password updated.")
        return True
    user = User(
        name=name.strip() or "SHA Administrator",
        email=normalized,
        normalized_email=normalized,
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    click.echo("Administrator created.")
    return True


@click.command("create-admin")
@click.option("--email", envvar="ADMIN_EMAIL", help="Administrator email.")
@click.option("--password", envvar="ADMIN_PASSWORD", help="Administrator password.")
@click.option("--name", envvar="ADMIN_NAME", default="SHA Administrator")
@click.option("--force", is_flag=True, help="Reset the password if the user exists.")
@with_appcontext
def create_admin(email, password, name, force):
    """Create the first administrator account (or reset it with --force)."""
    if not email:
        email = click.prompt("Email")
    if not password:
        password = click.prompt("Password", hide_input=True, confirmation_prompt=True)
    _create_admin(email, password, name, force=force)


@click.command("bootstrap-admin")
@with_appcontext
def bootstrap_admin():
    """Create the admin from env vars only if the user table is empty."""
    if db.session.scalar(db.select(func.count(User.id))):
        click.echo("Users already exist; bootstrap skipped.")
        return
    email = os.environ.get("ADMIN_EMAIL", "")
    password = os.environ.get("ADMIN_PASSWORD", "")
    name = os.environ.get("ADMIN_NAME", "SHA Administrator")
    if not email or not password:
        click.echo("ADMIN_EMAIL / ADMIN_PASSWORD not set; bootstrap skipped.")
        return
    _create_admin(email, password, name)


@click.command("recalc-scores")
@with_appcontext
def recalc_scores():
    """Recompute deterministic scores after changing scoring configuration."""
    leads = db.session.scalars(db.select(Lead)).all()
    for lead in leads:
        recalculate_score(lead, current_app.config)
    db.session.commit()
    click.echo(f"Recalculated {len(leads)} lead score(s).")


@click.command("init-db")
@with_appcontext
def init_db():
    """Apply Alembic migrations without requiring the Flask-Migrate CLI."""
    from flask_migrate import upgrade

    upgrade()
    click.echo("Database migrations applied.")


@click.command("seed-demo")
@with_appcontext
def seed_demo():
    """Insert fictional demo leads and follow-ups into an empty database."""
    if db.session.scalar(db.select(func.count(Lead.id))):
        raise click.ClickException("Leads already exist; demo data was not inserted.")
    if db.session.scalar(db.select(func.count(User.id))) == 0:
        click.echo("Note: create an administrator with `flask create-admin` before signing in.")

    today = local_today(current_app.config["TIMEZONE"])
    samples = [
        {
            "name": "Ananya Rao",
            "phone": "9000000001",
            "email": "ananya.rao@example.com",
            "locality": "Indiranagar",
            "property_type": "Apartment",
            "project_type": "Full Home Interiors",
            "budget_min": 900000,
            "budget_max": 1400000,
            "expected_start": today + timedelta(days=25),
            "requirements": "3BHK full interiors, moving in by December. Need a quote and site visit. Budget approved.",
            "source": "Instagram",
            "status": "Qualified",
        },
        {
            "name": "Rohan Iyer",
            "phone": "9000000002",
            "email": "rohan.iyer@example.com",
            "locality": "Whitefield",
            "property_type": "Villa",
            "project_type": "Full Home Interiors",
            "budget_min": 2000000,
            "budget_max": 3000000,
            "expected_start": today + timedelta(days=70),
            "requirements": "4BHK villa with wardrobes, kitchen, and false ceiling. Finalising designers now.",
            "source": "Referral",
            "status": "Contacted",
        },
        {
            "name": "Meera Nair",
            "phone": "9000000003",
            "email": "meera.nair@example.com",
            "locality": "HSR Layout",
            "property_type": "Apartment",
            "project_type": "Modular Kitchen",
            "budget_min": 250000,
            "budget_max": 400000,
            "expected_start": today + timedelta(days=15),
            "requirements": "Need a modular kitchen urgently before handover. Site visit requested.",
            "source": "Website",
            "status": "New",
        },
        {
            "name": "Kabir Shah",
            "phone": "9000000004",
            "email": "kabir.shah@example.com",
            "locality": "Jayanagar",
            "property_type": "Independent House",
            "project_type": "Renovation",
            "budget_min": 1500000,
            "budget_max": 2500000,
            "expected_start": today + timedelta(days=150),
            "requirements": "Renovating the ground floor; need design and execution support.",
            "source": "Walk-in",
            "status": "Proposal Sent",
        },
        {
            "name": "Sana Kulkarni",
            "phone": "9000000005",
            "email": "sana.kulkarni@example.com",
            "locality": "Koramangala",
            "property_type": "Office",
            "project_type": "Renovation",
            "budget_min": 800000,
            "budget_max": 1200000,
            "expected_start": today + timedelta(days=45),
            "requirements": "Office reception and cabins refresh; work should finish before the team moves in.",
            "source": "Google",
            "status": "Qualified",
        },
        {
            "name": "Arjun Menon",
            "phone": "9000000006",
            "email": "arjun.menon@example.com",
            "locality": "Electronic City",
            "property_type": "Apartment",
            "project_type": "Wardrobes",
            "budget_min": 150000,
            "budget_max": 250000,
            "expected_start": None,
            "requirements": "Only wardrobes for two bedrooms; comparing quotes.",
            "source": "Google",
            "status": "Contacted",
        },
        {
            "name": "Diya Bhat",
            "phone": "9000000007",
            "email": "diya.bhat@example.com",
            "locality": "Yelahanka",
            "property_type": "Villa",
            "project_type": "Full Home Interiors",
            "budget_min": 3000000,
            "budget_max": 4500000,
            "expected_start": today + timedelta(days=110),
            "requirements": "New villa handover in three months; full turnkey interiors required.",
            "source": "Instagram",
            "status": "New",
        },
        {
            "name": "Vihaan Reddy",
            "phone": "9000000008",
            "email": "vihaan.reddy@example.com",
            "locality": "JP Nagar",
            "property_type": "Apartment",
            "project_type": "Single Room",
            "budget_min": 80000,
            "budget_max": 120000,
            "expected_start": today - timedelta(days=10),
            "requirements": "Single room makeover; ready to start immediately.",
            "source": "WhatsApp",
            "status": "Won",
        },
        {
            "name": "Ira Sen",
            "phone": "9000000009",
            "email": "ira.sen@example.com",
            "locality": "Hebbal",
            "property_type": "Apartment",
            "project_type": "Full Home Interiors",
            "budget_min": 600000,
            "budget_max": 900000,
            "expected_start": today + timedelta(days=35),
            "requirements": "2BHK with false ceiling, kitchen, and wardrobes; quote requested.",
            "source": "Website",
            "status": "Lost",
        },
        {
            "name": "Naina Gupta",
            "phone": "9000000010",
            "email": "naina.gupta@example.com",
            "locality": "Sarjapur Road",
            "property_type": "Apartment",
            "project_type": "Modular Kitchen",
            "budget_min": 200000,
            "budget_max": 350000,
            "expected_start": today + timedelta(days=200),
            "requirements": "Kitchen update next year; exploring options.",
            "source": "Referral",
            "status": "New",
        },
        {
            "name": "Aditya Pillai",
            "phone": "9000000011",
            "email": "aditya.pillai@example.com",
            "locality": "Malleshwaram",
            "property_type": "Independent House",
            "project_type": "Renovation",
            "budget_min": 1000000,
            "budget_max": 1800000,
            "expected_start": today + timedelta(days=80),
            "requirements": "Old house renovation; would like a site visit.",
            "source": "Google",
            "status": "Contacted",
        },
        {
            "name": "Tara Joshi",
            "phone": "9000000012",
            "email": "tara.joshi@example.com",
            "locality": "Whitefield",
            "property_type": "Apartment",
            "project_type": "Wardrobes",
            "budget_min": None,
            "budget_max": None,
            "expected_start": None,
            "requirements": "Looking for wardrobe ideas; budget not decided.",
            "source": "Other",
            "status": "New",
        },
    ]

    created = []
    for sample in samples:
        data = dict(sample)
        data["normalized_phone"] = normalize_phone(data["phone"])
        data["normalized_email"] = normalize_email(data["email"])
        lead = create_lead(data, current_app.config)
        created.append(lead)
    db.session.commit()

    followups = [
        (created[1], "Send revised scope and budget outline", today - timedelta(days=3), "Reference the villa walkthrough notes."),
        (created[3], "Follow up on proposal feedback", today - timedelta(days=1), "Proposal shared last week."),
        (created[0], "Confirm site visit slot", today, "Confirm Saturday morning."),
        (created[2], "Call to confirm kitchen measurements", today + timedelta(days=2), None),
        (created[6], "Share portfolio and book discovery call", today + timedelta(days=5), "Send villa portfolio link."),
    ]
    for lead, title, due, notes in followups:
        db.session.add(
            FollowUp(lead=lead, title=title, due_date=due, notes=notes)
        )
    completed = FollowUp(
        lead=created[8],
        title="Send final thank-you note",
        due_date=today - timedelta(days=5),
        notes="Kept as an example of a completed task.",
        status="completed",
        completed_at=utcnow(),
    )
    db.session.add(completed)
    db.session.commit()
    click.echo(f"Seeded {len(created)} fictional leads and {len(followups) + 1} follow-ups.")
    click.echo("All demo records use example.com addresses and 90000000xx phone numbers.")


def register_cli(app) -> None:
    app.cli.add_command(create_admin)
    app.cli.add_command(bootstrap_admin)
    app.cli.add_command(recalc_scores)
    app.cli.add_command(init_db)
    app.cli.add_command(seed_demo)
    app.cli.add_command(run_worker)


@click.command("run-worker")
@click.option("--interval", default=30, help="Polling interval in seconds.", type=int)
@click.option("--once", is_flag=True, help="Run once and exit (for testing).")
@click.option("--no-automation", is_flag=True, help="Skip automation event processing.")
@click.option("--no-whatsapp-retry", is_flag=True, help="Skip WhatsApp retry processing.")
@with_appcontext
def run_worker(interval: int, once: bool, no_automation: bool, no_whatsapp_retry: bool):
    """Run the background worker for scheduled jobs and automation events.

    This command runs continuously, polling for due jobs and pending automation events.
    Use --once for a single iteration (useful for testing/CI).
    """
    click.echo(f"Starting background worker (interval={interval}s)...")
    if once:
        click.echo("Running single iteration (--once mode)")

    iteration = 0
    while True:
        iteration += 1
        try:
            with current_app.app_context():
                # 1. Process pending automation events (qualify, send_initial, schedule_followup)
                if not no_automation:
                    auto_result = process_pending_automation_events(current_app.config, limit=50)
                    if auto_result["processed"] > 0 or auto_result["failed"] > 0:
                        click.echo(
                            f"  [Automation] Processed: {auto_result['processed']}, "
                            f"Failed: {auto_result['failed']}, Skipped: {auto_result['skipped']}"
                        )

                # 2. Process due scheduled jobs (follow-ups)
                jobs = get_due_jobs(limit=50)
                if jobs:
                    click.echo(f"  [Jobs] Found {len(jobs)} due job(s)")
                    for job in jobs:
                        success = process_job(job, current_app.config)
                        status = "completed" if success else "retry/failed"
                        click.echo(f"    Job {job.id} ({job.job_type}): {status}")

                # 3. Retry failed WhatsApp messages
                if not no_whatsapp_retry:
                    retried = retry_failed_messages()
                    if retried:
                        click.echo(f"  [WhatsApp] Retried {retried} failed message(s)")

        except Exception as e:
            click.echo(f"Worker error: {e}", err=True)
            current_app.logger.exception("Worker iteration failed")

        if once:
            click.echo("Single iteration complete.")
            break

        time.sleep(interval)
