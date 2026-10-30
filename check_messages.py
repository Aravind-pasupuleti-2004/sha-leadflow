"""Check message content for a specific lead."""
from app import create_app
from app.models import OutboundMessage, Lead
from app.extensions import db

app = create_app()
ctx = app.app_context()
ctx.push()

# Check lead 29
lead = db.session.get(Lead, 29)
if lead:
    print(f"Lead {lead.id}: {lead.name}")
    print(f"  Score: {lead.score}")
    print(f"  Requirements: {lead.requirements}")
    print(f"  Project: {lead.project_type} in {lead.locality}")
    print()
    
    msgs = db.session.query(OutboundMessage).filter(OutboundMessage.lead_id == 29).all()
    for m in msgs:
        print(f"Message ({m.purpose}): {m.status}")
        print(f"  Content: {m.content[:500]}")
        print(f"  WhatsApp ID: {m.provider_message_id}")
        print()

ctx.pop()