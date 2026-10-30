"""Dashboard aggregates derived entirely from database queries."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from ..extensions import db
from ..models import FollowUp, Lead
from ..utils import local_today

CLOSED_STATUSES = {"Won", "Lost"}


def build_dashboard(config, today=None) -> dict:
    today = today or local_today(config.get("TIMEZONE", "Asia/Kolkata"))
    closed = list(CLOSED_STATUSES)

    total = db.session.execute(db.select(func.count(Lead.id))).scalar_one()
    status_rows = db.session.execute(
        db.select(Lead.status, func.count(Lead.id)).group_by(Lead.status)
    ).all()
    source_rows = db.session.execute(
        db.select(Lead.source, func.count(Lead.id)).group_by(Lead.source)
    ).all()
    status_counts = {status: 0 for status in config["LEAD_STATUSES"]}
    status_counts.update({row[0]: row[1] for row in status_rows})
    source_counts = {source: 0 for source in config["LEAD_SOURCES"]}
    source_counts.update({row[0]: row[1] for row in source_rows})

    won = status_counts.get("Won", 0)
    lost = status_counts.get("Lost", 0)
    decided = won + lost
    win_rate = round((won / decided) * 100) if decided else 0
    active = max(0, total - won - lost)

    max_status = max(status_counts.values(), default=0) or 1
    max_source = max(source_counts.values(), default=0) or 1
    pipeline = [
        {
            "status": status,
            "count": status_counts.get(status, 0),
            "share": round((status_counts.get(status, 0) / total) * 100) if total else 0,
            "bar": round((status_counts.get(status, 0) / max_status) * 100),
        }
        for status in config["LEAD_STATUSES"]
    ]
    sources = sorted(
        [
            {
                "source": source,
                "count": count,
                "share": round((count / total) * 100) if total else 0,
                "bar": round((count / max_source) * 100),
            }
            for source, count in source_counts.items()
            if count > 0
        ],
        key=lambda item: item["count"],
        reverse=True,
    )

    threshold = int(config["HIGH_PRIORITY_THRESHOLD"])
    high_priority = db.session.scalars(
        db.select(Lead)
        .where(Lead.score >= threshold, ~Lead.status.in_(closed))
        .order_by(Lead.score.desc(), Lead.updated_at.desc())
        .limit(6)
    ).all()

    overdue = db.session.scalars(
        db.select(FollowUp)
        .options(joinedload(FollowUp.lead))
        .where(FollowUp.status == "pending", FollowUp.due_date < today)
        .order_by(FollowUp.due_date.asc())
        .limit(8)
    ).all()
    due_today = db.session.scalars(
        db.select(FollowUp)
        .options(joinedload(FollowUp.lead))
        .where(FollowUp.status == "pending", FollowUp.due_date == today)
        .order_by(FollowUp.id.asc())
        .limit(8)
    ).all()
    upcoming = db.session.scalars(
        db.select(FollowUp)
        .options(joinedload(FollowUp.lead))
        .where(
            FollowUp.status == "pending",
            FollowUp.due_date > today,
            FollowUp.due_date <= today + timedelta(days=7),
        )
        .order_by(FollowUp.due_date.asc())
        .limit(8)
    ).all()
    open_followups = db.session.execute(
        db.select(func.count(FollowUp.id)).where(FollowUp.status == "pending")
    ).scalar_one()
    completed_followups = db.session.execute(
        db.select(func.count(FollowUp.id)).where(FollowUp.status == "completed")
    ).scalar_one()
    overdue_count = db.session.execute(
        db.select(func.count(FollowUp.id)).where(
            FollowUp.status == "pending", FollowUp.due_date < today
        )
    ).scalar_one()
    due_today_count = db.session.execute(
        db.select(func.count(FollowUp.id)).where(
            FollowUp.status == "pending", FollowUp.due_date == today
        )
    ).scalar_one()
    upcoming_count = db.session.execute(
        db.select(func.count(FollowUp.id)).where(
            FollowUp.status == "pending",
            FollowUp.due_date > today,
            FollowUp.due_date <= today + timedelta(days=7),
        )
    ).scalar_one()

    return {
        "today": today,
        "total": total,
        "active": active,
        "won": won,
        "lost": lost,
        "win_rate": win_rate,
        "pipeline": pipeline,
        "sources": sources,
        "status_counts": status_counts,
        "source_counts": source_counts,
        "high_priority": high_priority,
        "overdue": overdue,
        "due_today": due_today,
        "upcoming": upcoming,
        "open_followups": open_followups,
        "completed_followups": completed_followups,
        "overdue_count": overdue_count,
        "due_today_count": due_today_count,
        "upcoming_count": upcoming_count,
        "threshold": threshold,
    }
