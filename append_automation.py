def process_pending_automation_events(config: dict, limit: int = 50) -> dict:
    """Process pending automation events (QUALIFY, SEND_INITIAL, SCHEDULE_FOLLOWUP).

    This should be called by a background worker or scheduled task.
    Returns a summary of processed events.
    """
    from ...models import AutomationEvent, AutomationEventStatus, AutomationEventType

    now_utc = datetime.now(timezone.utc)

    # Get pending events ordered by creation time
    events = db.session.scalars(
        db.select(AutomationEvent)
        .where(AutomationEvent.status == AutomationEventStatus.PENDING)
        .order_by(AutomationEvent.created_at.asc())
        .limit(limit)
    ).all()

    results = {"processed": 0, "failed": 0, "skipped": 0, "details": []}

    for event in events:
        lead = db.session.get(Lead, event.lead_id)
        if not lead:
            event.status = AutomationEventStatus.FAILED
            event.last_error = "Lead not found"
            event.completed_at = now_utc
            results["failed"] += 1
            results["details"].append({"event_id": event.id, "status": "failed", "reason": "Lead not found"})
            continue

        try:
            if event.event_type == AutomationEventType.QUALIFY:
                # Already done at lead creation, just mark complete
                event.status = AutomationEventStatus.COMPLETED
                event.completed_at = now_utc

            elif event.event_type == AutomationEventType.SEND_INITIAL:
                send_initial_message(lead, config, user_id=event.payload.get("user_id"))
                event.status = AutomationEventStatus.COMPLETED
                event.completed_at = now_utc

            elif event.event_type == AutomationEventType.SCHEDULE_FOLLOWUP:
                schedule_followups(lead, config, user_id=event.payload.get("user_id"))
                event.status = AutomationEventStatus.COMPLETED
                event.completed_at = now_utc

            else:
                event.status = AutomationEventStatus.FAILED
                event.last_error = f"Unknown event type: {event.event_type}"
                results["failed"] += 1
                results["details"].append({"event_id": event.id, "status": "failed", "reason": "Unknown event type"})
                continue

            results["processed"] += 1
            results["details"].append({"event_id": event.id, "status": "completed", "type": event.event_type})

        except Exception as e:
            event.attempts += 1
            event.last_error = str(e)
            if event.attempts >= event.max_attempts:
                event.status = AutomationEventStatus.FAILED
                event.completed_at = now_utc
                results["failed"] += 1
                results["details"].append({"event_id": event.id, "status": "failed", "reason": str(e)})
            else:
                # Will retry next cycle
                results["skipped"] += 1
                results["details"].append({"event_id": event.id, "status": "retry", "attempt": event.attempts})

    if events:
        db.session.commit()

    return results