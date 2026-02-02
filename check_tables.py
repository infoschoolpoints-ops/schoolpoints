# -*- coding: utf-8 -*-
import sqlite3

conn = sqlite3.connect('school_points.db')
cursor = conn.cursor()

cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = cursor.fetchall()
print('Tables in database:')
for table in tables:
    print(f'  - {table[0]}')

# Check for scheduled_services which might be what we're looking for
cursor.execute("SELECT COUNT(*) FROM scheduled_services")
count = cursor.fetchone()[0]
print(f'\nScheduled services (challenges): {count}')

if count > 0:
    cursor.execute("SELECT id, product_id FROM scheduled_services LIMIT 5")
    print('Sample scheduled services:')
    for row in cursor.fetchall():
        print(f'  ID: {row[0]}, Product ID: {row[1]}')

conn.close()
