import sqlite3
conn = sqlite3.connect('instance/sha_leadflow.db')
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = cursor.fetchall()
for t in tables:
    print(t[0])
conn.close()