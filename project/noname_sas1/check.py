import sqlite3, bcrypt
conn = sqlite3.connect("attendance.db")
c = conn.cursor()
row = c.execute("SELECT password FROM teachers WHERE username='bipesh.subedi'").fetchone()
conn.close()

hashed = row[0]
test_password = "ce2subedi1"
print("Match:", bcrypt.checkpw(test_password.encode(), hashed.encode()))