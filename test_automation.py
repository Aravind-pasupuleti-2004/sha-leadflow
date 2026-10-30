"""Test script to verify automation workflow."""
from app import create_app
from app.models import AutomationEvent, ScheduledJob, OutboundMessage, Lead
from app.services.leads import create_lead
from app.services.validation import normalize_phone, normalize_email
from datetime import date

app = create_app()
# Enable auto opt-in for testing
app.config["AUTOMATION_AUTO_OPT_IN"] = True
ctx = app.app_context()
ctx.push()

# Create a new test lead
data = {
    'name': 'Test Customer 7',
    'phone': '9000000093',
    'email': 'test7@example.com',
    'locality': 'Whitefield',
    'property_type': 'Apartment',
    'project_type': 'Full Home Interiors',
    'budget_min': 1000000,
    'budget_max': 1500000,
    'expected_start': date(2026, 12, 1),
    'requirements': '3BHK apartment, modern luxury interiors, modular kitchen and premium bedroom designs',
    'source': 'Website',
    'status': 'New',
    'normalized_phone': normalize_phone('9000000093'),
    'normalized_email': normalize_email('test7@example.com')
}

print("=== Creating Lead ===")
lead = create_lead(data, app.config, user_id=1)
print(f"Lead created: {lead.id} - {lead.name}")

# Commit the transaction
from app.extensions import db
db.session.commit()

print("\n=== Before Worker ===")
print("AutomationEvents:")
for e in AutomationEvent.query.all():
    print(f"  {e.id}: {e.event_type} - {e.status}")

print("ScheduledJobs:")
for j in ScheduledJob.query.all():
    print(f"  {j.id}: {j.job_type} - {j.status}")

print("OutboundMessages:")
for m in OutboundMessage.query.all():
    print(f"  {m.id}: {m.purpose} - {m.status}")

print("\n=== Running Worker ===")
from app.services.jobs import get_due_jobs, process_job
from app.services.automation import process_pending_automation_events
from app.services.whatsapp import retry_failed_messages

# Process automation events
auto_result = process_pending_automation_events(app.config, limit=50)
print(f"Automation: {auto_result}")

# Process due jobs
jobs = get_due_jobs(limit=50)
print(f"Found {len(jobs)} due jobs")
for job in jobs:
    success = process_job(job, app.config)
    print(f"  Job {job.id} ({job.job_type}): {'completed' if success else 'retry/failed'}")

# Retry failed WhatsApp
retried = retry_failed_messages()
print(f"Retried {retried} failed messages")

print("\n=== After Worker ===")
print("AutomationEvents:")
for e in AutomationEvent.query.all():
    print(f"  {e.id}: {e.event_type} - {e.status}")

print("ScheduledJobs:")
for j in ScheduledJob.query.all():
    print(f"  {j.id}: {j.job_type} - {j.status}")

print("OutboundMessages:")
for m in OutboundMessage.query.all():
    print(f"  {m.id}: {m.purpose} - {m.status} - {m.provider_message_id}")

# Check the lead
lead = db.session.get(Lead, lead.id)
if lead:
    print(f"\nLead {lead.id}: {lead.name}, score={lead.score}, consent={lead.whatsapp_consent.opted_in if lead.whatsapp_consent else None}")
    if lead.outbound_messages:
        for msg in lead.outbound_messages:
            if msg.lead_id == lead.id:
                print(f"  Message ({msg.purpose}): {msg.status}")
                print(f"    Content: {msg.content[:300]}...")
                print(f"    WhatsApp ID: {msg.provider_message_id}")

ctx.pop()