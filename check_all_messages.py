"""Check all message content."""
from app import create_app
from app.models import OutboundMessage
from app.extensions import db

app = create_app()
ctx = app.app_context()
ctx.push()

msgs = db.session.query(OutboundMessage).all()
for m in msgs:
    print(f"ID: {m.id}, Lead: {m.lead_id}, Purpose: {m.purpose}, Status: {m.status}")
    print(f"  Content: {m.content[:200]}")
    print()

ctx.pop()