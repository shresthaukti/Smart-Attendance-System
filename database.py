import sqlite3
import bcrypt
import numpy as np
from datetime import datetime, date as date_class

DB_FILE = "attendance.db"

# ── PASSWORD HASHING ──────────────────────────────────────────────────────────

def hash_password(plain_password: str) -> str:
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(plain_password.encode("utf-8"), salt)
    return hashed.decode("utf-8")

def check_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8")
    )

# ── DATABASE CREATION ─────────────────────────────────────────────────────────

def create_database():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS students (
            student_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            course TEXT NOT NULL,
            year INTEGER NOT NULL,
            email TEXT,
            password TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS student_faces (
            face_id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            image_path TEXT,
            embedding BLOB NOT NULL,
            FOREIGN KEY(student_id) REFERENCES students(student_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS unrecognized_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            image_path TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS subjects (
            subject_id TEXT PRIMARY KEY,
            subject_name TEXT NOT NULL,
            course TEXT NOT NULL,
            year INTEGER NOT NULL,
            room TEXT NOT NULL,
            teacher_name TEXT NOT NULL
        )
    """)

    # attendance now includes check_out_time for session duration tracking
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            subject_id TEXT NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            check_out_time TEXT,
            UNIQUE(student_id, subject_id, date),
            FOREIGN KEY(student_id) REFERENCES students(student_id),
            FOREIGN KEY(subject_id) REFERENCES subjects(subject_id)
        )
    """)

    # sessions now includes is_alternate flag for non-routine classes
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id TEXT NOT NULL,
            date TEXT NOT NULL,
            room TEXT NOT NULL,
            start_time TEXT,
            end_time TEXT,
            notes TEXT,
            is_alternate INTEGER DEFAULT 0,
            UNIQUE(subject_id, date),
            FOREIGN KEY(subject_id) REFERENCES subjects(subject_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS active_sessions (
            session_id INTEGER PRIMARY KEY,
            opened_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES sessions(session_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS teachers (
            teacher_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            email TEXT,
            phone TEXT,
            department TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS routine (
            routine_id INTEGER PRIMARY KEY AUTOINCREMENT,
            course TEXT NOT NULL,
            year INTEGER NOT NULL,
            section TEXT NOT NULL,
            day TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            subject_id TEXT NOT NULL,
            room TEXT,
            FOREIGN KEY(subject_id) REFERENCES subjects(subject_id)
        )
    """)

    conn.commit()
    conn.close()
    print(f"Database created: {DB_FILE}")
    print("  - students table")
    print("  - subjects table")
    print("  - attendance table (with check_out_time)")
    print("  - sessions table (with is_alternate)")
    print("  - active_sessions table")
    print("  - teachers table (bcrypt passwords)")
    print("  - routine table")


def migrate_existing_db():
    """
    Run this ONCE if you already have an attendance.db from before this update.
    Adds the new columns to existing tables without losing any data.
    Safe to run multiple times.
    """
    conn = sqlite3.connect(DB_FILE)
    try:
        conn.execute("ALTER TABLE attendance ADD COLUMN check_out_time TEXT")
        print("Migration: added check_out_time to attendance.")
    except sqlite3.OperationalError:
        print("Migration: check_out_time already exists, skipping.")
    try:
        conn.execute("ALTER TABLE sessions ADD COLUMN is_alternate INTEGER DEFAULT 0")
        print("Migration: added is_alternate to sessions.")
    except sqlite3.OperationalError:
        print("Migration: is_alternate already exists, skipping.")
    conn.commit()
    conn.close()


# ── FACE DATA UTILITIES ───────────────────────────────────────────────────────

def register_student_face(student_id: str, image_path: str, embedding_array: np.ndarray):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    binary_embedding = embedding_array.tobytes()
    cursor.execute("""
        INSERT INTO student_faces (student_id, image_path, embedding)
        VALUES (?, ?, ?)
    """, (student_id, image_path, binary_embedding))
    conn.commit()
    conn.close()

def load_known_face_dataset():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT sf.student_id, s.name, sf.embedding
        FROM student_faces sf
        JOIN students s ON sf.student_id = s.student_id
    """)
    rows = cursor.fetchall()
    conn.close()
    dataset = {}
    for student_id, name, blob in rows:
        vector = np.frombuffer(blob, dtype=np.float32)
        dataset[student_id] = {"name": name, "embedding": vector}
    return dataset

def log_unrecognized_detection(image_path: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    now_str = datetime.now().isoformat()
    cursor.execute("""
        INSERT INTO unrecognized_logs (image_path, timestamp)
        VALUES (?, ?)
    """, (image_path, now_str))
    conn.commit()
    conn.close()

# ── ATTENDANCE ────────────────────────────────────────────────────────────────

def save_attendance_record(student_id: str, subject_id: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    today_str = str(date_class.today())
    time_str = datetime.now().strftime("%H:%M:%S")
    try:
        cursor.execute("""
            INSERT INTO attendance (student_id, subject_id, date, time)
            VALUES (?, ?, ?, ?)
        """, (student_id, subject_id, today_str, time_str))
        conn.commit()
        success = True
    except sqlite3.IntegrityError:
        success = False
    finally:
        conn.close()
    return success

def checkout_all_present_students(subject_id: str, date_str=None):
    """
    Called when a teacher closes a session. Stamps check_out_time for every
    student who was marked present today but hasn't checked out yet.
    This gives you the session-start → session-end duration per student.
    """
    if date_str is None:
        date_str = str(date_class.today())
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    now = datetime.now().strftime("%H:%M:%S")
    cursor.execute("""
        UPDATE attendance SET check_out_time = ?
        WHERE subject_id = ? AND date = ? AND check_out_time IS NULL
    """, (now, subject_id, date_str))
    conn.commit()
    conn.close()

def mark_student_checkout(student_id: str, subject_id: str, date_str=None):
    """Stamp check_out_time for one student (e.g. early leave)."""
    if date_str is None:
        date_str = str(date_class.today())
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        UPDATE attendance SET check_out_time = ?
        WHERE student_id = ? AND subject_id = ? AND date = ?
    """, (datetime.now().strftime("%H:%M:%S"), student_id, subject_id, date_str))
    conn.commit()
    conn.close()

# ── ROUTINE ───────────────────────────────────────────────────────────────────

def get_routine_for_course(course, year, section="CE-II/II"):
    """Get the weekly timetable for a course/year/section, ordered by day and time."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.day, r.start_time, r.end_time, r.subject_id,
               s.subject_name, r.room, s.teacher_name
        FROM routine r
        JOIN subjects s ON r.subject_id = s.subject_id
        WHERE r.course = ? AND r.year = ? AND r.section = ?
        ORDER BY
            CASE r.day
                WHEN 'Sunday'    THEN 0 WHEN 'Monday'  THEN 1
                WHEN 'Tuesday'   THEN 2 WHEN 'Wednesday' THEN 3
                WHEN 'Thursday'  THEN 4 WHEN 'Friday'  THEN 5
                WHEN 'Saturday'  THEN 6 ELSE 7 END,
            r.start_time
    """, (course, year, section))
    result = cursor.fetchall()
    conn.close()
    return result

def get_todays_routine_subjects(course, year, section="CE-II/II"):
    """
    Returns only today's scheduled classes for a course/year/section.
    Used on the teacher dashboard to show quick-pick buttons for sessions.
    Each entry: (day, start_time, end_time, subject_id, subject_name, room, teacher_name)
    """
    today_day = date_class.today().strftime("%A")
    all_routine = get_routine_for_course(course, year, section)
    return [r for r in all_routine if r[0] == today_day]

# ── SESSION MANAGEMENT ────────────────────────────────────────────────────────

def get_session_for_date(subject_id, date):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT session_id, subject_id, date, room, start_time, end_time, notes, is_alternate
        FROM sessions WHERE subject_id = ? AND date = ?
    """, (subject_id, date))
    result = cursor.fetchone()
    conn.close()
    return result

def is_session_open(subject_id, date_str=None):
    if date_str is None:
        date_str = str(date_class.today())
    session = get_session_for_date(subject_id, date_str)
    if not session:
        return False
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM active_sessions WHERE session_id = ?", (session[0],))
    result = cursor.fetchone() is not None
    conn.close()
    return result

def open_session(subject_id, date_str=None):
    if date_str is None:
        date_str = str(date_class.today())
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    session = get_session_for_date(subject_id, date_str)
    if not session:
        default_room = conn.execute(
            "SELECT room FROM subjects WHERE subject_id = ?", (subject_id,)
        ).fetchone()
        if not default_room:
            conn.close()
            return False
        cursor.execute(
            "INSERT INTO sessions (subject_id, date, room) VALUES (?, ?, ?)",
            (subject_id, date_str, default_room[0])
        )
        conn.commit()
        session = get_session_for_date(subject_id, date_str)
    if not session:
        conn.close()
        return False
    session_id = session[0]
    now = datetime.now().isoformat()
    try:
        cursor.execute(
            "INSERT INTO active_sessions (session_id, opened_at) VALUES (?, ?)",
            (session_id, now)
        )
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False

def close_session(subject_id, date_str=None):
    if date_str is None:
        date_str = str(date_class.today())
    session = get_session_for_date(subject_id, date_str)
    if not session:
        return False
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM active_sessions WHERE session_id = ?", (session[0],))
    conn.commit()
    conn.close()
    return True

def open_session_for_routine(course, year, section, subject_id,
                              room=None, date_str=None, is_alternate=False):
    """
    Opens a session, linked to the routine table.

    - Normal class (is_alternate=False):
        Checks that this subject is actually scheduled today in the routine.
        If it's not, returns (False, error_message) — nothing is opened.
    - Alternate class (is_alternate=True):
        Skips the routine check entirely — use for substitute teachers,
        makeup classes, or any class outside the normal timetable.

    Returns (success: bool, message: str).
    """
    if date_str is None:
        date_str = str(date_class.today())

    today_day = date_class.today().strftime("%A")

    if not is_alternate:
        todays_classes = get_todays_routine_subjects(course, year, section)
        scheduled_ids = [r[3] for r in todays_classes]
        if subject_id not in scheduled_ids:
            return False, (
                f"'{subject_id}' is not on today's ({today_day}) routine for "
                f"{course} year {year}. Tick 'Alternate class' to override."
            )

    if room is None:
        conn = sqlite3.connect(DB_FILE)
        row = conn.execute(
            "SELECT room FROM subjects WHERE subject_id=?", (subject_id,)
        ).fetchone()
        conn.close()
        room = row[0] if row else "Default Room"

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO sessions (subject_id, date, room, is_alternate)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(subject_id, date) DO UPDATE SET
            room=excluded.room,
            is_alternate=excluded.is_alternate
    """, (subject_id, date_str, room, 1 if is_alternate else 0))
    conn.commit()
    conn.close()

    open_session(subject_id, date_str)
    label = "alternate class" if is_alternate else "scheduled class"
    return True, f"Session opened ({label})."

def create_or_update_session(subject_id, date, room, start_time=None,
                              end_time=None, notes=""):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO sessions (subject_id, date, room, start_time, end_time, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(subject_id, date) DO UPDATE SET
                room=excluded.room, start_time=excluded.start_time,
                end_time=excluded.end_time, notes=excluded.notes
        """, (subject_id, date, room, start_time, end_time, notes))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error creating session: {e}")
        conn.close()
        return False

def get_all_sessions_for_subject(subject_id, limit=30):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT session_id, subject_id, date, room, start_time, end_time, notes, is_alternate
        FROM sessions WHERE subject_id = ?
        ORDER BY date DESC LIMIT ?
    """, (subject_id, limit))
    result = cursor.fetchall()
    conn.close()
    return result

def get_current_active_subject():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT s.subject_id FROM active_sessions axs
        JOIN sessions s ON axs.session_id = s.session_id
        LIMIT 1
    """)
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else "DEFAULT_SUB"

def get_room_for_subject_date(subject_id, date):
    session = get_session_for_date(subject_id, date)
    if session:
        return session[3]
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT room FROM subjects WHERE subject_id = ?", (subject_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

# ── STUDENT QUERIES ───────────────────────────────────────────────────────────

def student_exists(student_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM students WHERE student_id = ?", (student_id,))
    result = cursor.fetchone() is not None
    conn.close()
    return result

def get_student_name(student_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM students WHERE student_id = ?", (student_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def get_students_for_course(course, year):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT student_id, name FROM students WHERE course = ? AND year = ?",
        (course, year)
    )
    result = cursor.fetchall()
    conn.close()
    return result

def get_subjects_for_student(student_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT course, year FROM students WHERE student_id = ?", (student_id,))
    student = cursor.fetchone()
    if not student:
        conn.close()
        return []
    course, year = student
    cursor.execute(
        "SELECT subject_id, subject_name, room, teacher_name FROM subjects WHERE course = ? AND year = ?",
        (course, year)
    )
    result = cursor.fetchall()
    conn.close()
    return result

def get_all_subjects():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT subject_id, subject_name, room, teacher_name FROM subjects")
    result = cursor.fetchall()
    conn.close()
    return result

def get_attendance_for_student_subject(student_id, subject_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT date, time FROM attendance WHERE student_id = ? AND subject_id = ? ORDER BY date DESC",
        (student_id, subject_id)
    )
    result = cursor.fetchall()
    conn.close()
    return result

def get_attendance_count_for_student_subject(student_id, subject_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(DISTINCT date) FROM attendance WHERE student_id = ? AND subject_id = ?",
        (student_id, subject_id)
    )
    result = cursor.fetchone()[0]
    conn.close()
    return result

def get_total_class_days(subject_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(DISTINCT date) FROM attendance WHERE subject_id = ?",
        (subject_id,)
    )
    result = cursor.fetchone()[0]
    conn.close()
    return result if result > 0 else 1

def get_todays_attendance(subject_id):
    today = str(date_class.today())
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT s.student_id, s.name, a.time
        FROM attendance a
        JOIN students s ON a.student_id = s.student_id
        WHERE a.subject_id = ? AND a.date = ?
        ORDER BY a.time ASC
    """, (subject_id, today))
    result = cursor.fetchall()
    conn.close()
    return result

def get_full_attendance_report(subject_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT DISTINCT course, year FROM subjects WHERE subject_id = ?",
        (subject_id,)
    )
    course_year = cursor.fetchone()
    if not course_year:
        conn.close()
        return []
    course, year = course_year
    cursor.execute("""
        SELECT s.student_id, s.name, COUNT(DISTINCT a.date) as days_present
        FROM students s
        LEFT JOIN attendance a ON s.student_id = a.student_id AND a.subject_id = ?
        WHERE s.course = ? AND s.year = ?
        GROUP BY s.student_id
        ORDER BY s.name ASC
    """, (subject_id, course, year))
    result = cursor.fetchall()
    conn.close()
    return result

# ── TEACHER AUTH ──────────────────────────────────────────────────────────────

def verify_teacher_login(username, password):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT teacher_id, name, department, email, password FROM teachers WHERE username = ?",
        (username,)
    )
    result = cursor.fetchone()
    conn.close()
    if result and check_password(password, result[4]):
        return {
            "teacher_id": result[0],
            "name": result[1],
            "department": result[2],
            "email": result[3],
        }
    return None

def get_teacher_by_id(teacher_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT teacher_id, name, username, email, phone, department FROM teachers WHERE teacher_id = ?",
        (teacher_id,)
    )
    result = cursor.fetchone()
    conn.close()
    if result:
        return {
            "teacher_id": result[0], "name": result[1],
            "username": result[2],   "email": result[3],
            "phone": result[4],      "department": result[5],
        }
    return None

def get_all_teachers():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT teacher_id, name, username, email, phone, department FROM teachers")
    result = cursor.fetchall()
    conn.close()
    return result

# ── EXCEL IMPORT ──────────────────────────────────────────────────────────────

def import_students_from_excel(filepath: str) -> dict:
    try:
        from openpyxl import load_workbook
    except ImportError:
        return {"inserted": 0, "skipped": 0, "errors": ["openpyxl not installed"]}

    wb = load_workbook(filepath)
    ws = wb.active
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    inserted = skipped = 0
    errors = []

    for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if not any(row):
            continue
        if len(row) < 4:
            errors.append(f"Row {i}: not enough columns")
            continue
        student_id, name, course, year = row[0], row[1], row[2], row[3]
        email    = row[4] if len(row) > 4 else None
        password = row[5] if len(row) > 5 else None
        if not all([student_id, name, course, year]):
            errors.append(f"Row {i}: missing required field")
            continue
        try:
            year = int(year)
        except (ValueError, TypeError):
            errors.append(f"Row {i}: year must be a number")
            continue
        try:
            hashed_pw = hash_password(str(password)) if password else None
            cursor.execute(
                "INSERT OR IGNORE INTO students (student_id, name, course, year, email, password) VALUES (?, ?, ?, ?, ?, ?)",
                (str(student_id).strip(), str(name).strip(), str(course).strip(), year,
                 str(email).strip() if email else None, hashed_pw)
            )
            inserted += 1 if cursor.rowcount > 0 else 0
            skipped  += 1 if cursor.rowcount == 0 else 0
        except sqlite3.Error as e:
            errors.append(f"Row {i}: {e}")

    conn.commit()
    conn.close()
    print(f"Students import complete — inserted: {inserted}, skipped: {skipped}, errors: {len(errors)}")
    return {"inserted": inserted, "skipped": skipped, "errors": errors}

def import_teachers_from_excel(filepath: str) -> dict:
    try:
        from openpyxl import load_workbook
    except ImportError:
        return {"inserted": 0, "skipped": 0, "errors": ["openpyxl not installed"]}

    wb = load_workbook(filepath)
    ws = wb.active
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    inserted = skipped = 0
    errors = []

    for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if not any(row):
            continue
        if len(row) < 6:
            errors.append(f"Row {i}: not enough columns")
            continue
        name, email, phone, department, username, password = (
            row[0], row[1], row[2], row[3], row[4], row[5]
        )
        if not all([name, username, password]):
            errors.append(f"Row {i}: name, username, password required")
            continue
        hashed = hash_password(str(password))
        try:
            cursor.execute(
                "INSERT OR IGNORE INTO teachers (name, username, password, email, phone, department) VALUES (?, ?, ?, ?, ?, ?)",
                (str(name).strip(), str(username).strip(), hashed,
                 str(email).strip() if email else None,
                 str(phone).strip() if phone else None,
                 str(department).strip() if department else None)
            )
            inserted += 1 if cursor.rowcount > 0 else 0
            skipped  += 1 if cursor.rowcount == 0 else 0
        except sqlite3.Error as e:
            errors.append(f"Row {i}: {e}")

    conn.commit()
    conn.close()
    print(f"Teachers import complete — inserted: {inserted}, skipped: {skipped}, errors: {len(errors)}")
    return {"inserted": inserted, "skipped": skipped, "errors": errors}

# ── SEED DATA ─────────────────────────────────────────────────────────────────

def populate_ce2_data():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    course, year, section = "CE", 2, "CE-II/II"
    subjects = [
        ("COMP232", "Database Management Systems",              course, year, "9-404",               "Mr. Bipesh Subedi"),
        ("COMP204", "Data Communication and Networking",        course, year, "10-103",              "Mr. Gobinda Subedi"),
        ("COMP231", "Microprocessor and Assembly Language",     course, year, "9-402",               "Prof. Dr. Gajendra Sharma"),
        ("MATH207", "Differential Equations and Complex Variables", course, year, "9-302 (Computer Lab)", "Mohan Chandra Adhikari"),
        ("MCSC202", "Numerical Methods",                        course, year, "9-402",               "Dr. Sushil Ghimire"),
    ]
    for sub in subjects:
        cursor.execute(
            "INSERT OR IGNORE INTO subjects (subject_id, subject_name, course, year, room, teacher_name) VALUES (?, ?, ?, ?, ?, ?)",
            sub
        )
    cursor.execute("DELETE FROM routine WHERE course=? AND year=? AND section=?", (course, year, section))
    routine_rows = [
        ("Tuesday",   "09:00", "10:00", "COMP232", "9-404"),
        ("Tuesday",   "12:00", "13:00", "COMP204", "10-103"),
        ("Wednesday", "11:00", "12:00", "MATH207", "9-302 (Computer Lab)"),
        ("Wednesday", "14:00", "15:00", "COMP204", "9-402"),
        ("Thursday",  "09:00", "10:00", "MCSC202", "9-402"),
        ("Thursday",  "12:00", "13:00", "COMP231", "9-402"),
        ("Thursday",  "14:00", "15:00", "MATH207", "9-402"),
        ("Friday",    "09:00", "10:00", "COMP232", "9-402"),
        ("Friday",    "12:00", "13:00", "COMP231", "9-310"),
        ("Friday",    "14:00", "15:00", "MCSC202", "9-404"),
    ]
    for day, start, end, subject_id, room in routine_rows:
        cursor.execute(
            "INSERT INTO routine (course, year, section, day, start_time, end_time, subject_id, room) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (course, year, section, day, start, end, subject_id, room)
        )
    conn.commit()
    conn.close()
    print("CE-II/II subjects and routine seeded.")

def populate_ce1_data():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    course, year, section = "CE", 1, "CE-I/II"
    cursor.execute(
        "INSERT OR IGNORE INTO subjects (subject_id, subject_name, course, year, room, teacher_name) VALUES (?, ?, ?, ?, ?, ?)",
        ("MATH104", "Advanced Calculus", course, year, "9-301 (Graduate Room)", "Dr. Sushil Ghimire")
    )
    cursor.execute("DELETE FROM routine WHERE course=? AND year=? AND section=?", (course, year, section))
    routine_rows = [
        ("Monday",    "09:00", "10:00", "MATH104", "9-301 (Graduate Room)"),
        ("Wednesday", "09:00", "10:00", "MATH104", "TTC"),
        ("Thursday",  "12:00", "13:00", "MATH104", "TTC"),
    ]
    for day, start, end, subject_id, room in routine_rows:
        cursor.execute(
            "INSERT INTO routine (course, year, section, day, start_time, end_time, subject_id, room) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (course, year, section, day, start, end, subject_id, room)
        )
    conn.commit()
    conn.close()
    print("CE-I/II (MATH104) subjects and routine seeded.")

if __name__ == "__main__":
    print("Initializing Smart Attendance System database...")
    create_database()
    print("Database ready.")
    print()
    print("To import data from Excel, run: python setup.py")
