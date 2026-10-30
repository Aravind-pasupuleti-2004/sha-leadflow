import re

# Read the file
with open('E:\\sha interiors\\app\\services\\leads.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix create_lead function
old_create = '''def create_lead(data: dict, config, user_id: int | None = None) -> Lead:
    lead = Lead(**data)
    recalculate_score(lead, config)
    db.session.add(lead)
    db.sessi
enqueue_automation(lead, config, user_id)
    return leadon.flush()
    log_activity(lead, "created", "Lead created", user_id=user_id)'''

new_create = '''def create_lead(data: dict, config, user_id: int | None = None) -> Lead:
    lead = Lead(**data)
    recalculate_score(lead, config)
    db.session.add(lead)
    db.session.flush()
    log_activity(lead, "created", "Lead created", user_id=user_id)
    enqueue_automation(lead, config, user_id)
    return lead'''

content = content.replace(old_create, new_create)

# Write back
with open('E:\\sha interiors\\app\\services\\leads.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Fixed create_lead")