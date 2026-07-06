import sqlite3

conn = sqlite3.connect(r"C:\Users\User\Desktop\flask\attendance.db")
cur = conn.cursor()

cur.execute("SELECT email, password FROM teachers LIMIT 5")
print(cur.fetchall())

conn.close()