import sqlite3, bcrypt
conn = sqlite3.connect("attendance.db")
c = conn.cursor()
row = c.execute("SELECT password FROM teachers WHERE username='rajan.thapa'").fetchone()
conn.close()

hashed = row[0]
test_password = "ce2thapa1"
print("Match:", bcrypt.checkpw(test_password.encode(), hashed.encode()))