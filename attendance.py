import sqlite3
from datetime import date, datetime

DB_FILE = "attendance.db"

def process_scan(student_id, subject_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("SELECT 1 FROM students WHERE student_id = ?", (student_id,))
    student = c.fetchone()
    if not student:
        conn.close()
        return "R"  

    if not is_session_open(subject_id):
        conn.close()
        return "S"  

    today = str(date.today())
    try:
        c.execute(
            "INSERT INTO attendance (student_id, subject_id, date, time) VALUES (?, ?, ?, ?)",
            (student_id, subject_id, today, datetime.now().strftime("%H:%M:%S"))
        )
        conn.commit()
        conn.close()
        return "G"  
    except sqlite3.IntegrityError:
        conn.close()
        return "Y" 


def is_session_open(subject_id, date_str=None):
    if date_str is None:
        date_str = str(date.today())
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        """SELECT 1 FROM active_sessions 
           WHERE session_id IN (
               SELECT session_id FROM sessions WHERE subject_id = ? AND date = ?
           )""",
        (subject_id, date_str)
    )
    result = c.fetchone() is not None
    conn.close()
    return result

def open_session(subject_id, room="Default Room"):
    today = str(date.today())
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Create or reuse session
    c.execute(
        "INSERT OR IGNORE INTO sessions (subject_id, date, room) VALUES (?, ?, ?)",
        (subject_id, today, room)
    )
    conn.commit()
    c.execute("SELECT session_id FROM sessions WHERE subject_id = ? AND date = ?", (subject_id, today))
    session = c.fetchone()
    if session:
        session_id = session[0]
        try:
            c.execute("INSERT INTO active_sessions (session_id, opened_at) VALUES (?, ?)",
                      (session_id, datetime.now().isoformat()))
            conn.commit()
        except sqlite3.IntegrityError:
            pass 
    conn.close()

def close_session(subject_id):
    today = str(date.today())
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT session_id FROM sessions WHERE subject_id = ? AND date = ?", (subject_id, today))
    session = c.fetchone()
    if session:
        c.execute("DELETE FROM active_sessions WHERE session_id = ?", (session[0],))
        conn.commit()
    conn.close()


def main():
    subject_id = input("Enter the subject ID for today: ").strip()
    print(f"Attendance system ready for subject: {subject_id}")

    open_session(subject_id)
    print("Session started. Type Student IDs to simulate scanning.\n")

    while True:
        student_id = input("Scan/Type Student ID (or 'stop' to end): ").strip()
        if not student_id:
            continue
        if student_id.lower() == "stop":
            close_session(subject_id)
            print("Session closed.")
            break

        result = process_scan(student_id, subject_id)
        messages = {
            "G": " ✅ Attendance marked successfully",
            "Y": " ⚠️ Already marked today",
            "R": " ❌ Student not found",
            "S": " ⚠️ Session not open"
        }
        print(messages[result])

if __name__ == "__main__":
    main()
