# check_db.py
import sqlite3

conn = sqlite3.connect('attendance.db')
cursor = conn.cursor()

print("=== STUDENTS ===")
cursor.execute("SELECT * FROM students")
for row in cursor.fetchall():
    print(row)

print("\n=== STUDENT FACES ===")
cursor.execute("SELECT student_id, image_path, length(embedding) FROM student_faces")
for row in cursor.fetchall():
    print(row)

conn.close()