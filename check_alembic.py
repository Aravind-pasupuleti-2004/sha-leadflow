import sqlite3
conn = sqlite3.connect('instance/sha_leadflow.db')
cursor = conn.cursor()
cursor.execute("SELECT * FROM alembic_version")
print('Alembic version:', cursor.fetchall())
conn.close()