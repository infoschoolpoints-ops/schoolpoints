# -*- coding: utf-8 -*-
"""
יצירת טבלת activities אם היא לא קיימת
"""
import sqlite3

conn = sqlite3.connect('school_points.db')
cursor = conn.cursor()

# Create activities table
cursor.execute('''
    CREATE TABLE IF NOT EXISTS activities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT,
        points INTEGER DEFAULT 0,
        print_code TEXT,
        is_active INTEGER DEFAULT 1,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
''')

# Create activity_claims table
cursor.execute('''
    CREATE TABLE IF NOT EXISTS activity_claims (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        activity_id INTEGER NOT NULL,
        student_id INTEGER NOT NULL,
        claimed_at TEXT DEFAULT CURRENT_TIMESTAMP,
        points_awarded INTEGER DEFAULT 0,
        FOREIGN KEY (activity_id) REFERENCES activities(id),
        FOREIGN KEY (student_id) REFERENCES students(id)
    )
''')

# Create activity_schedules table
cursor.execute('''
    CREATE TABLE IF NOT EXISTS activity_schedules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        activity_id INTEGER NOT NULL,
        day_of_week INTEGER,
        start_time TEXT,
        end_time TEXT,
        max_claims_per_day INTEGER DEFAULT 0,
        is_active INTEGER DEFAULT 1,
        FOREIGN KEY (activity_id) REFERENCES activities(id)
    )
''')

conn.commit()
conn.close()

print("Activities tables created successfully!")
print("You can now add challenges through 'ניהול אתגרים'")
