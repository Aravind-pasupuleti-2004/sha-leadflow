"""Test inbound webhook processing."""
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

# Simulate inbound WhatsApp message from the customer
payload = {
    "entry": [{
        "changes": [{
            "value": {
                "messages": [{
                    "id": "wamid.test123",
                    "from": "919000000093",  # Lead's phone with country code
                    "timestamp": "1700000000",
                    "type": "text",
                    "text": {"body": "Yes, I'm interested. Can we schedule a call for tomorrow?"}
                }],
                "contacts": [{"wa_id": "919000000093"}]
            },
            "field": "messages"
        }]
    }]
}

print("\n=== Processing Inbound Message ===")
result = process_inbound_message(payload)
print(f"Result: {result}")

# Check lead state after
lead = db.session.get(Lead, 30)
print(f"\nConsent after: {lead.whatsapp_consent.opted_in if lead.whatsapp_consent else None}")
print(f"Scheduled jobs after: {len(lead.scheduled_jobs)}")
for job in lead.scheduled_jobs:
    print(f"  Job {job.id}: {job.job_type} - {job.status}")

# Check inbound message
inbound = db.session.query(InboundMessage).filter(InboundMessage.provider_message_id == "wamid.test123").first()
if inbound:
    print(f"\nInbound message: {inbound.content}")
    print(f"Opt-out detected: {inbound.opt_out_detected}")

ctx.pop()