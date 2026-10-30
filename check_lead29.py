"""Check message for lead 29."""
from app import create_app
from app.models import OutboundMessage
from app.extensions import db

app = create_app()
ctx = app.app_context()
ctx.push()

msgs = db.session.query(OutboundMessage).filter(OutboundMessage.lead_id == 29).all()
print(f"Count: {len(msgs)}")
for m in msgs:
    print(f"  {m.id}: {m.purpose} - {m.content[:200]}")

ctx.pop()