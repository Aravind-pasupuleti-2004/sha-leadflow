"""Test opt-out processing."""
from app import create_app
from app.models import Lead, InboundMessage, WhatsAppConsent, ScheduledJob
from app.extensions import db
from app.services.whatsapp.webhook import process_inbound_message

app = create_app()
ctx = app.app_context()
ctx.push()

# Get lead 30
lead = db.session.get(Lead, 30)
print(f"Lead: {lead.name}, Phone: {lead.normalized_phone}")
print(f"Consent before: {lead.whatsapp_consent.opted_in if lead.whatsapp_consent else None}")
print(f"Scheduled jobs before: {len(lead.scheduled_jobs)}")
for job in lead.scheduled_jobs:
    print(f"  Job {job.id}: {job.job_type} - {job.status}")

# Simulate STOP message
payload = {
    "entry": [{
        "changes": [{
            "value": {
                "messages": [{
                    "id": "wamid.stop123",
                    "from": "919000000093",
                    "timestamp": "1700000100",
                    "type": "text",
                    "text": {"body": "STOP"}
                }],
                "contacts": [{"wa_id": "919000000093"}]
            },
            "field": "messages"
        }]
    }]
}

print("\n=== Processing STOP Message ===")
result = process_inbound_message(payload)
print(f"Result: {result}")

# Check lead state after
lead = db.session.get(Lead, 30)
print(f"\nConsent after: {lead.whatsapp_consent.opted_in if lead.whatsapp_consent else None}")
print(f"Opted out at: {lead.whatsapp_consent.opted_out_at if lead.whatsapp_consent else None}")
print(f"Scheduled jobs after: {len(lead.scheduled_jobs)}")
for job in lead.scheduled_jobs:
    print(f"  Job {job.id}: {job.job_type} - {job.status}")

ctx.pop()