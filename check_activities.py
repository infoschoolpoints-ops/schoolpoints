# -*- coding: utf-8 -*-
import sqlite3

conn = sqlite3.connect('school_points.db')
cursor = conn.cursor()

cursor.execute('SELECT COUNT(*) FROM activities WHERE is_active = 1')
count = cursor.fetchone()[0]
print(f'Active activities: {count}')

cursor.execute('SELECT id, name, is_active FROM activities LIMIT 10')
print('Sample activities:')
for row in cursor.fetchall():
    print(row)

conn.close()
