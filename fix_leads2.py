import re

# Read the file
with open('E:\\sha interiors\\app\\services\\leads.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find and replace the corrupted create_lead function
# The function starts at "def create_lead" and ends before "def update_lead"
pattern = r'def create_lead\(data: dict, config, user_id: int \| None = None\) -> Lead:.*?(?=\n\ndef update_lead)'

replacement = '''def create_lead(data: dict, config, user_id: int | None = None) -> Lead:
    lead = Lead(**data)
    recalculate_score(lead, config)
    db.session.add(lead)
    db.session.flush()
    log_activity(lead, "created", "Lead created", user_id=user_id)
    enqueue_automation(lead, config, user_id)
    return lead'''

content = re.sub(pattern, replacement, content, flags=re.DOTALL)

# Write back
with open('E:\\sha interiors\\app\\services\\leads.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Fixed create_lead")