import re

with open('E:\\sha interiors\\app\\services\\leads.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Remove the recalculate_score function from leads.py
pattern = r'\n\ndef recalculate_score\(lead: Lead, config, today: date \| None = None\) -> dict:.*?(?=\n\ndef )'
content = re.sub(pattern, '\n', content, flags=re.DOTALL)

with open('E:\\sha interiors\\app\\services\\leads.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Removed recalculate_score from leads.py")