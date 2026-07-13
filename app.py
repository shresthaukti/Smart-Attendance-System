from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import sqlite3
import bcrypt
from datetime import date, datetime
from flask import request, jsonify
from pyzbar.pyzbar import decode
import cv2
import numpy as np
import time

app = Flask(__name__)
app.secret_key = "ku_smart_attendance_secret_2026"

import os
DB_FILE = os.path.join(os.path.dirname(__file__), "attendance.db")

import database as db
db.migrate_sessions_table()
db.migrate_communication_tables()


# ── Helpers ──────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def check_password(plain, hashed):
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def home():
    return render_template("main.html")


# ── STUDENT AUTH ─────────────────────────────────────────────────────────────

@app.route("/student-login", methods=["GET", "POST"])
def student_login():
    if request.method == "POST":
        student_id = request.form.get("student_id", "").strip()
        password   = request.form.get("password", "")

        conn = get_db()
        row = conn.execute(
            "SELECT student_id, name, password FROM students WHERE student_id = ?", (student_id,)
        ).fetchone()
        conn.close()

        if row and check_password(password, row["password"]):
            session["student_id"] = row["student_id"]
            session["student_name"] = row["name"]
            return redirect(url_for("student_dashboard"))
        else:
            return render_template("studentlogin.html", error="Invalid Student ID or password")

    return render_template("studentlogin.html")


@app.route("/student-logout")
def student_logout():
    session.pop("student_id", None)
    session.pop("student_name", None)
    return redirect(url_for("home"))


# ── TEACHER AUTH ─────────────────────────────────────────────────────────────

@app.route("/teacher-login", methods=["GET", "POST"])
def teacher_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        conn = get_db()
        row = conn.execute(
            "SELECT teacher_id, name, department, email, password FROM teachers WHERE username = ?",
            (username,)
        ).fetchone()
        conn.close()

        if row and check_password(password, row["password"]):
            session["teacher_id"]   = row["teacher_id"]
            session["teacher_name"] = row["name"]
            session["teacher_dept"] = row["department"]
            session["teacher_email"]= row["email"]
            return redirect(url_for("teacher_dashboard"))
        else:
            return render_template("teacherlogin.html", error="Invalid username or password")

    return render_template("teacherlogin.html")


@app.route("/teacher-logout")
def teacher_logout():
    session.pop("teacher_id", None)
    session.pop("teacher_name", None)
    return redirect(url_for("home"))


# ── STUDENT DASHBOARD ────────────────────────────────────────────────────────

@app.route("/student-dashboard")
def student_dashboard():
    if "student_id" not in session:
        return redirect(url_for("student_login"))

    student_id = session["student_id"]
    conn = get_db()

    # Student info
    student = conn.execute(
        "SELECT student_id, name, course, year, email FROM students WHERE student_id = ?",
        (student_id,)
    ).fetchone()

    # Subjects for this student's course/year
    subjects = conn.execute(
        "SELECT subject_id, subject_name, room, teacher_name FROM subjects WHERE course=? AND year=?",
        (student["course"], student["year"])
    ).fetchall()

    # Weekly routine for this student's course/year
    from database import get_routine_for_course
    routine_rows = get_routine_for_course(student["course"], student["year"])
    routine = [
        {
            "day": r[0], "start_time": r[1], "end_time": r[2],
            "subject_id": r[3], "subject_name": r[4], "room": r[5], "teacher_name": r[6]
        }
        for r in routine_rows
    ]

    # Per-subject attendance summary
    subject_stats = []
    total_present = 0
    total_classes = 0
    for sub in subjects:
        sid = sub["subject_id"]
        present = conn.execute(
            "SELECT COUNT(DISTINCT date) FROM attendance WHERE student_id=? AND subject_id=?",
            (student_id, sid)
        ).fetchone()[0]
        total_days = conn.execute(
            "SELECT COUNT(DISTINCT date) FROM attendance WHERE subject_id=?", (sid,)
        ).fetchone()[0]
        if total_days == 0:
            total_days = 1
        pct = round((present / total_days) * 100)
        subject_stats.append({
            "subject_id": sid,
            "subject_name": sub["subject_name"],
            "teacher": sub["teacher_name"],
            "room": sub["room"],
            "present": present,
            "total": total_days,
            "percent": pct,
        })
        total_present += present
        total_classes += total_days

    overall_pct = round((total_present / total_classes) * 100) if total_classes > 0 else 0
    absent_total = total_classes - total_present

    conn.close()

    return render_template(
        "studentdashboard.html",
        student=student,
        subjects=subjects,
        subject_stats=subject_stats,
        overall_pct=overall_pct,
        total_present=total_present,
        absent_total=absent_total,
        total_classes=total_classes,
        routine=routine,
    )


# ── STUDENT ATTENDANCE (AJAX) ────────────────────────────────────────────────

@app.route("/api/student/attendance")
def api_student_attendance():
    if "student_id" not in session:
        return jsonify([])
    student_id  = session["student_id"]
    subject_id  = request.args.get("subject", "")
    filter_date = request.args.get("date", "")

    conn = get_db()
    student = conn.execute(
        "SELECT course, year FROM students WHERE student_id=?", (student_id,)
    ).fetchone()

    subs = conn.execute(
        "SELECT subject_id, subject_name FROM subjects WHERE course=? AND year=?",
        (student["course"], student["year"])
    ).fetchall()
    sub_ids = {s["subject_id"]: s["subject_name"] for s in subs}

    # Filter to one subject if requested
    target_subs = [subject_id] if (subject_id and subject_id in sub_ids) else list(sub_ids.keys())

    # All sessions (class days) for these subjects.
    # DISTINCT + "did anyone actually scan that day" — same fix as CSV export:
    # a test/alternate session opened with zero scans shouldn't create a
    # row here, and re-opening one multiple times in a day shouldn't
    # duplicate the row either.
    placeholders = ",".join("?" * len(target_subs))
    session_query = f"""
        SELECT DISTINCT s.date, s.subject_id FROM sessions s
        WHERE s.subject_id IN ({placeholders})
        AND EXISTS (
            SELECT 1 FROM attendance a
            WHERE a.subject_id = s.subject_id AND a.date = s.date
        )
    """
    session_params = target_subs[:]
    if filter_date:
        session_query += " AND s.date = ?"
        session_params.append(filter_date)
    session_query += " ORDER BY s.date DESC"
    all_sessions = conn.execute(session_query, session_params).fetchall()

    # All attendance records for this student
    att_query = f"""
        SELECT date, subject_id, time FROM attendance
        WHERE student_id = ? AND subject_id IN ({placeholders})
    """
    att_params = [student_id] + target_subs
    if filter_date:
        att_query += " AND date = ?"
        att_params.append(filter_date)
    att_rows = conn.execute(att_query, att_params).fetchall()
    conn.close()

    # Build a lookup: (date, subject_id) -> time
    present_map = {(r["date"], r["subject_id"]): r["time"] for r in att_rows}

    result = []
    for s in all_sessions:
        key = (s["date"], s["subject_id"])
        if key in present_map:
            result.append({
                "date":         s["date"],
                "subject_id":   s["subject_id"],
                "subject_name": sub_ids.get(s["subject_id"], ""),
                "time":         present_map[key],
                "status":       "present"
            })
        else:
            result.append({
                "date":         s["date"],
                "subject_id":   s["subject_id"],
                "subject_name": sub_ids.get(s["subject_id"], ""),
                "time":         None,
                "status":       "absent"
            })

    return jsonify(result)


# ── NOTIFICATIONS AND CHAT ────────────────────────────────────────────────

def _teacher_subjects(conn, teacher_id):
    """Subjects owned by the signed-in teacher (the app stores teacher names on subjects)."""
    return conn.execute(
        """SELECT subject_id, subject_name, course, year FROM subjects
           WHERE teacher_name = (SELECT name FROM teachers WHERE teacher_id=?)
           ORDER BY subject_id""", (teacher_id,)
    ).fetchall()


@app.route("/api/notifications")
def api_notifications():
    if "student_id" not in session:
        return jsonify([]), 401
    conn = get_db()
    rows = conn.execute(
        """SELECT notification_id, message, created_at FROM notifications
           WHERE student_id=? AND read_at IS NULL AND expires_at > datetime('now')
           ORDER BY created_at ASC""", (session["student_id"],)
    ).fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])


@app.route("/api/notifications/<int:notification_id>/read", methods=["POST"])
def api_read_notification(notification_id):
    if "student_id" not in session:
        return jsonify({"ok": False}), 401
    conn = get_db()
    cur = conn.execute(
        "UPDATE notifications SET read_at=CURRENT_TIMESTAMP WHERE notification_id=? AND student_id=?",
        (notification_id, session["student_id"])
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": cur.rowcount == 1})


@app.route("/student-chat")
def student_chat():
    if "student_id" not in session:
        return redirect(url_for("student_login"))
    conn = get_db()
    student = conn.execute("SELECT name, course, year FROM students WHERE student_id=?", (session["student_id"],)).fetchone()
    subjects = conn.execute(
        """SELECT s.subject_id, s.subject_name, s.teacher_name, t.teacher_id
           FROM subjects s JOIN teachers t ON trim(lower(t.name))=trim(lower(s.teacher_name))
           WHERE s.course=? AND s.year=? ORDER BY s.subject_id""",
        (student["course"], student["year"])
    ).fetchall()
    conn.close()
    return render_template("studentchat.html", student=student, subjects=subjects)


@app.route("/teacher-chat")
def teacher_chat():
    if "teacher_id" not in session:
        return redirect(url_for("teacher_login"))
    conn = get_db()
    subjects = _teacher_subjects(conn, session["teacher_id"])
    conn.close()
    return render_template("teacherchat.html", teacher_name=session["teacher_name"], subjects=subjects)


@app.route("/api/chat/student/messages")
def api_student_messages():
    if "student_id" not in session:
        return jsonify([]), 401
    subject_id = request.args.get("subject", "")
    conn = get_db()
    params = [session["student_id"]]
    where = "student_id=?"
    if subject_id:
        where += " AND subject_id=?"
        params.append(subject_id)
    # Reading a conversation clears only messages actually delivered to this student.
    conn.execute(f"UPDATE chat_messages SET read_at=CURRENT_TIMESTAMP WHERE {where} AND sender_role='teacher' AND read_at IS NULL", params)
    rows = conn.execute(
        f"""SELECT message_id, subject_id, sender_role,
                   CASE WHEN unsent_at IS NULL THEN body ELSE 'Message unsent.' END AS body,
                   created_at, unsent_at
            FROM chat_messages WHERE {where} ORDER BY created_at ASC, message_id ASC""", params
    ).fetchall()
    conn.commit()
    conn.close()
    return jsonify([dict(row) for row in rows])


@app.route("/api/chat/student/conversations")
def api_student_conversations():
    """One private inbox row for each teacher/class available to this student."""
    if "student_id" not in session:
        return jsonify([]), 401
    conn = get_db()
    rows = conn.execute(
        """SELECT s.subject_id, s.subject_name, s.teacher_name,
                   SUM(CASE WHEN m.sender_role='teacher' AND m.read_at IS NULL
                                  AND m.unsent_at IS NULL THEN 1 ELSE 0 END) AS unread_count,
                   MAX(m.created_at) AS last_message_at
            FROM subjects s
            JOIN students st ON st.student_id=? AND s.course=st.course AND s.year=st.year
            JOIN teachers t ON trim(lower(t.name))=trim(lower(s.teacher_name))
            LEFT JOIN chat_messages m ON m.student_id=st.student_id
                                     AND m.teacher_id=t.teacher_id AND m.subject_id=s.subject_id
            GROUP BY s.subject_id, s.subject_name, s.teacher_name
            ORDER BY unread_count DESC, last_message_at DESC, s.teacher_name""",
        (session["student_id"],)
    ).fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])


@app.route("/api/chat/student/send", methods=["POST"])
def api_student_send():
    if "student_id" not in session:
        return jsonify({"ok": False, "message": "Please sign in."}), 401
    data = request.get_json() or {}
    subject_id, body = data.get("subject_id", "").strip(), data.get("body", "").strip()
    if not subject_id or not body or len(body) > 1000:
        return jsonify({"ok": False, "message": "Choose a class and enter a message up to 1000 characters."}), 400
    conn = get_db()
    row = conn.execute(
        """SELECT t.teacher_id FROM subjects s JOIN students st ON st.student_id=?
           JOIN teachers t ON trim(lower(t.name))=trim(lower(s.teacher_name))
           WHERE s.subject_id=? AND s.course=st.course AND s.year=st.year""",
        (session["student_id"], subject_id)
    ).fetchone()
    if not row:
        conn.close()
        return jsonify({"ok": False, "message": "That class or teacher is unavailable."}), 403
    cur = conn.execute(
        """INSERT INTO chat_messages (student_id, teacher_id, subject_id, sender_role, body)
           VALUES (?, ?, ?, 'student', ?)""", (session["student_id"], row["teacher_id"], subject_id, body)
    )
    conn.commit()
    message_id = cur.lastrowid
    conn.close()
    return jsonify({"ok": True, "message_id": message_id})


@app.route("/api/chat/student/unsend/<int:message_id>", methods=["POST"])
def api_student_unsend(message_id):
    if "student_id" not in session:
        return jsonify({"ok": False}), 401
    conn = get_db()
    cur = conn.execute(
        """UPDATE chat_messages SET unsent_at=CURRENT_TIMESTAMP, body=''
           WHERE message_id=? AND student_id=? AND sender_role='student' AND unsent_at IS NULL""",
        (message_id, session["student_id"])
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": cur.rowcount == 1})


@app.route("/api/chat/teacher/messages")
def api_teacher_messages():
    if "teacher_id" not in session:
        return jsonify([]), 401
    subject_id = request.args.get("subject", "")
    student_id = request.args.get("student_id", "")
    if not student_id:
        return jsonify([])
    conn = get_db()
    params = [session["teacher_id"], student_id]
    where = "m.teacher_id=? AND m.student_id=?"
    if subject_id:
        where += " AND m.subject_id=?"
        params.append(subject_id)
    conn.execute(f"UPDATE chat_messages AS m SET read_at=CURRENT_TIMESTAMP WHERE {where} AND sender_role='student' AND read_at IS NULL", params)
    rows = conn.execute(
        f"""SELECT m.message_id, m.student_id, st.name AS student_name, m.subject_id,
                   m.sender_role, CASE WHEN m.unsent_at IS NULL THEN m.body ELSE 'Message unsent.' END AS body,
                   m.created_at, m.unsent_at
            FROM chat_messages m JOIN students st ON st.student_id=m.student_id
            WHERE {where} ORDER BY m.created_at ASC, m.message_id ASC""", params
    ).fetchall()
    conn.commit()
    conn.close()
    return jsonify([dict(row) for row in rows])


@app.route("/api/chat/teacher/conversations")
def api_teacher_conversations():
    """Private student conversations; optional class filter is for the teacher inbox."""
    if "teacher_id" not in session:
        return jsonify([]), 401
    subject_id = request.args.get("subject", "")
    conn = get_db()
    params = [session["teacher_id"]]
    where = "m.teacher_id=?"
    if subject_id:
        where += " AND m.subject_id=?"
        params.append(subject_id)
    rows = conn.execute(
        f"""SELECT m.student_id, st.name AS student_name, m.subject_id,
                   MAX(m.created_at) AS last_message_at,
                   SUM(CASE WHEN m.sender_role='student' AND m.read_at IS NULL
                                  AND m.unsent_at IS NULL THEN 1 ELSE 0 END) AS unread_count
            FROM chat_messages m JOIN students st ON st.student_id=m.student_id
            WHERE {where}
            GROUP BY m.student_id, st.name, m.subject_id
            ORDER BY unread_count DESC, last_message_at DESC, st.name""", params
    ).fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])


@app.route("/api/chat/teacher/reply", methods=["POST"])
def api_teacher_reply():
    if "teacher_id" not in session:
        return jsonify({"ok": False}), 401
    data = request.get_json() or {}
    student_id, subject_id, body = data.get("student_id", "").strip(), data.get("subject_id", "").strip(), data.get("body", "").strip()
    if not student_id or not subject_id or not body or len(body) > 1000:
        return jsonify({"ok": False, "message": "Select a student and enter a message up to 1000 characters."}), 400
    conn = get_db()
    allowed = conn.execute(
        """SELECT 1 FROM subjects s JOIN students st ON st.student_id=?
           WHERE s.subject_id=? AND s.teacher_name=(SELECT name FROM teachers WHERE teacher_id=?)
             AND s.course=st.course AND s.year=st.year""", (student_id, subject_id, session["teacher_id"])
    ).fetchone()
    if not allowed:
        conn.close()
        return jsonify({"ok": False, "message": "You can only reply to students in your classes."}), 403
    conn.execute("""INSERT INTO chat_messages (student_id, teacher_id, subject_id, sender_role, body)
                    VALUES (?, ?, ?, 'teacher', ?)""", (student_id, session["teacher_id"], subject_id, body))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/chat/unread-count")
def api_chat_unread_count():
    conn = get_db()
    if "student_id" in session:
        count = conn.execute("SELECT COUNT(*) FROM chat_messages WHERE student_id=? AND sender_role='teacher' AND read_at IS NULL AND unsent_at IS NULL", (session["student_id"],)).fetchone()[0]
    elif "teacher_id" in session:
        count = conn.execute("SELECT COUNT(*) FROM chat_messages WHERE teacher_id=? AND sender_role='student' AND read_at IS NULL AND unsent_at IS NULL", (session["teacher_id"],)).fetchone()[0]
    else:
        conn.close()
        return jsonify({"count": 0}), 401
    conn.close()
    return jsonify({"count": count})


# ── TEACHER DASHBOARD ────────────────────────────────────────────────────────

@app.route("/teacher-dashboard")
def teacher_dashboard():
    if "teacher_id" not in session:
        return redirect(url_for("teacher_login"))

    teacher_name = session["teacher_name"]
    conn = get_db()

    # Subjects this teacher teaches
    subjects = conn.execute(
        "SELECT subject_id, subject_name, room, course, year FROM subjects WHERE teacher_name=?",
        (teacher_name,)
    ).fetchall()

    # Default to first subject
    selected_sub = request.args.get("subject", subjects[0]["subject_id"] if subjects else None)

    today = str(date.today())
    today_present = []
    absent_students = []
    all_students = []
    monthly_stats = []
    session_open = False

    if selected_sub:
        # Check if session is open
        # Check if any active session exists for this subject today
        session_open = conn.execute("""
            SELECT 1
            FROM active_sessions a
            JOIN sessions s
            ON a.session_id = s.session_id
            WHERE s.subject_id = ?
            AND s.date = ?
            LIMIT 1
        """, (selected_sub, today)).fetchone() is not None

        # Today's present students
        today_present = conn.execute("""
            SELECT s.student_id, s.name, a.time
            FROM attendance a
            JOIN students s ON a.student_id = s.student_id
            WHERE a.subject_id=? AND a.date=?
            ORDER BY a.time ASC
        """, (selected_sub, today)).fetchall()

        # Get course/year for this subject
        sub_info = conn.execute(
            "SELECT course, year FROM subjects WHERE subject_id=?", (selected_sub,)
        ).fetchone()

        if sub_info:
            # All enrolled students
            all_students = conn.execute(
                "SELECT student_id, name FROM students WHERE course=? AND year=?",
                (sub_info["course"], sub_info["year"])
            ).fetchall()

            present_ids = {r["student_id"] for r in today_present}
            absent_students = [s for s in all_students if s["student_id"] not in present_ids]

            # Monthly stats
            total_days = conn.execute(
                "SELECT COUNT(DISTINCT date) FROM attendance WHERE subject_id=?", (selected_sub,)
            ).fetchone()[0] or 1

            for stu in all_students:
                present_count = conn.execute(
                    "SELECT COUNT(DISTINCT date) FROM attendance WHERE student_id=? AND subject_id=?",
                    (stu["student_id"], selected_sub)
                ).fetchone()[0]
                absent_count = total_days - present_count
                pct = round((present_count / total_days) * 100)
                monthly_stats.append({
                    "name": stu["name"],
                    "student_id": stu["student_id"],
                    "total": total_days,
                    "present": present_count,
                    "absent": absent_count,
                    "percent": pct,
                    "status": "good" if pct >= 75 else "low"
                })

    # Class-wise attendance percentages for sidebar
    class_stats = []
    for sub in subjects:
        total_days = conn.execute(
            "SELECT COUNT(DISTINCT date) FROM attendance WHERE subject_id=?", (sub["subject_id"],)
        ).fetchone()[0] or 1
        total_stu = conn.execute(
            "SELECT COUNT(*) FROM students WHERE course=? AND year=?",
            (sub["course"], sub["year"])
        ).fetchone()[0] or 1
        total_possible = total_days * total_stu
        total_present_count = conn.execute(
            "SELECT COUNT(*) FROM attendance WHERE subject_id=?", (sub["subject_id"],)
        ).fetchone()[0]
        avg_pct = round((total_present_count / total_possible) * 100) if total_possible > 0 else 0
        class_stats.append({"subject_id": sub["subject_id"], "subject_name": sub["subject_name"], "percent": avg_pct})

    # Weekly routine for the selected subject's course/year
    routine = []
    if selected_sub:
        sub_info = conn.execute(
            "SELECT course, year FROM subjects WHERE subject_id=?", (selected_sub,)
        ).fetchone()
        if sub_info:
            from database import get_routine_for_course
            routine_rows = get_routine_for_course(sub_info["course"], sub_info["year"])
            routine = [
                {
                    "day": r[0], "start_time": r[1], "end_time": r[2],
                    "subject_id": r[3], "subject_name": r[4], "room": r[5], "teacher_name": r[6]
                }
                for r in routine_rows
            ]

    conn.close()

    return render_template(
        "teacherdashboard.html",
        teacher_name=teacher_name,
        teacher_dept=session.get("teacher_dept", "DoCSE"),
        teacher_email=session.get("teacher_email", ""),
        subjects=subjects,
        selected_sub=selected_sub,
        today_present=today_present,
        absent_students=absent_students,
        all_students=all_students,
        monthly_stats=monthly_stats,
        routine=routine,
        class_stats=class_stats,
        session_open=session_open,
        today=today,
    )


# ── SESSION CONTROL (AJAX) ───────────────────────────────────────────────────

@app.route("/api/session/open", methods=["POST"])
def api_open_session():
    if "teacher_id" not in session:
        return jsonify({"ok": False})
    data = request.json or {}
    subject_id = data.get("subject_id")
    alternate = bool(data.get("is_alternate", False))
    if not subject_id:
        return jsonify({"ok": False, "message": "Missing subject_id"})

    # Block silent auto-opening on non-routine days — teacher must explicitly
    # tick "alternate/substitute class" if today isn't a scheduled day.
    if not alternate:
        conn = get_db()
        sub = conn.execute(
            "SELECT course, year FROM subjects WHERE subject_id=?", (subject_id,)
        ).fetchone()
        conn.close()
        if not sub:
            return jsonify({"ok": False, "message": "Subject not found"})

        from database import get_routine_slot_for_today
        day_name = date.today().strftime("%A")
        routine_id = get_routine_slot_for_today(subject_id, sub["course"], sub["year"], day_name)
        if routine_id is None:
            return jsonify({
                "ok": False,
                "message": "This subject isn't on today's routine. Tick 'alternate/substitute class' to open it anyway."
            })

    session_id = db.open_routine_or_alternate_session(subject_id, force_alternate=alternate)
    if session_id is None:
        return jsonify({"ok": False, "message": "Subject not found"})

    return jsonify({"ok": True, "session_id": session_id, "alternate": alternate})


@app.route("/api/session/close", methods=["POST"])
def api_close_session():
    if "teacher_id" not in session:
        return jsonify({"ok": False})
    data = request.json or {}
    subject_id = data.get("subject_id")
    session_id = data.get("session_id")  # optional: close one specific open session
    if not subject_id and not session_id:
        return jsonify({"ok": False, "message": "Missing subject_id or session_id"})

    if session_id:
        db.close_active_session_by_id(session_id)
    else:
        # No specific session_id given — close every open session for this
        # subject today (routine class + any alternate classes running).
        for s_id, routine_id, is_alt, start_time in db.get_open_sessions_for_subject_today(subject_id):
            db.close_active_session_by_id(s_id)

    return jsonify({"ok": True})


@app.route("/api/session/status")
def api_session_status():
    """Returns all currently-open sessions for a subject today, including
    alternate classes, so the UI can show session duration / multiple slots."""
    if "teacher_id" not in session:
        return jsonify({"sessions": []})
    subject_id = request.args.get("subject", "")
    if not subject_id:
        return jsonify({"sessions": []})
    rows = db.get_open_sessions_for_subject_today(subject_id)
    return jsonify({
        "sessions": [
            {"session_id": r[0], "routine_id": r[1], "is_alternate": bool(r[2]), "start_time": r[3]}
            for r in rows
        ]
    })

@app.route('/api/decode-frame', methods=['POST'])
def decode_frame():

    decode_start = time.perf_counter()

    if 'frame' not in request.files:
        return jsonify({"success": False})

    file = request.files['frame']

    img_bytes = file.read()

    npimg = np.frombuffer(img_bytes, np.uint8)
    frame = cv2.imdecode(npimg, cv2.IMREAD_COLOR)

    if frame is None:
        return jsonify({"success": False})

    barcodes = decode(frame)

    decode_end = time.perf_counter()

    print(
        f"PYZBAR DECODE: {(decode_end - decode_start)*1000:.2f} ms"
    )

    if not barcodes:
        return jsonify({"success": False})

    barcode = barcodes[0].data.decode("utf-8")

    return jsonify({
        "success": True,
        "barcode": barcode
    })

# ── SCAN FROM DASHBOARD (integrated camera) ──────────────────────────────────

@app.route("/api/scan-barcode", methods=["POST"])
def api_scan_barcode():

    """Called by the teacher dashboard when it detects a barcode from the camera feed"""
    if "teacher_id" not in session:
        return jsonify({"result": "R", "message": "Not logged in"})
    data = request.get_json()
    if not data:
        return jsonify({"result": "R", "message": "No data"})

    student_id = data.get("student_id", "").strip()
    subject_id = data.get("subject_id", "").strip()

    if student_id.startswith("]C1"):
        student_id = student_id[3:]

    if not student_id or not subject_id:
        return jsonify({"result": "R", "message": "Missing fields"})

    from attendance import process_scan
    result_code = process_scan(student_id, subject_id)

    messages = {
        "G": "Attendance marked",
        "Y": "Already marked today",
        "R": "Student not found",
        "S": "Session not open — open the session first"
    }

    # Fetch student name for display if successful
    name = ""
    if result_code in ("G", "Y"):
        conn = get_db()
        row = conn.execute("SELECT name FROM students WHERE student_id=?", (student_id,)).fetchone()
        conn.close()
        name = row["name"] if row else student_id

    return jsonify({"result": result_code, "message": messages.get(result_code, "Unknown"), "name": name})


# ── SCAN FROM PHONE / scanning.py ────────────────────────────────────────────

@app.route("/scan", methods=["POST"])
def scan_from_phone():
    """Receives barcode scan from scanning.py or phone app via HTTP POST"""
    data = request.get_json()
    if not data:
        return jsonify({"result": "R", "message": "No data"}), 400

    student_id = data.get("student_id", "").strip()
    subject_id = data.get("subject_id", "").strip()
    scan_duration = data.get("scan_duration", None)  # seconds, float

    if student_id.startswith("]C1"):
        student_id = student_id[3:]

    if not student_id or not subject_id:
        return jsonify({"result": "R", "message": "Missing fields"}), 400

    from attendance import process_scan
    result_code = process_scan(student_id, subject_id)

    messages = {
        "G": "Attendance marked successfully",
        "Y": "Already marked today",
        "R": "Student not found",
        "S": "Session not open"
    }

    # Log scan duration to console
    if scan_duration and result_code == "G":
        print(f"[SCAN] {student_id} → {subject_id} | duration: {scan_duration:.2f}s")

    return jsonify({
        "result": result_code,
        "message": messages.get(result_code, "Unknown")
    })


# ── LIVE ATTENDANCE (AJAX auto-refresh) ──────────────────────────────────────

@app.route("/api/live-attendance")
def api_live_attendance():
    db_start = time.perf_counter()
    """Returns today's present students for a subject — called every 5s by teacher dashboard"""
    if "teacher_id" not in session:
        return jsonify([])
    subject_id = request.args.get("subject", "")
    if not subject_id:
        return jsonify([])

    conn = get_db()
    today = str(date.today())
    rows = conn.execute("""
        SELECT s.student_id, s.name, a.time
        FROM attendance a
        JOIN students s ON a.student_id = s.student_id
        WHERE a.subject_id = ? AND a.date = ?
        ORDER BY a.time ASC
    """, (subject_id, today)).fetchall()
    conn.close()

    db_end = time.perf_counter()
    print(
        f"ATTENDANCE PROCESS: {(db_end - db_start)*1000:.2f} ms"
    )
    return jsonify([
        {"student_id": r["student_id"], "name": r["name"], "time": r["time"]}
        for r in rows
    ])
# ── EXPORT CSV ───────────────────────────────────────────────────────────────

@app.route("/export/attendance")
def export_attendance():
    """
    Export attendance as a CSV register, like a manual attendance sheet:

        Student Name, 2026-06-01, 2026-06-02, 2026-06-03, ...
        Aashish Rai,  Present,    Absent,     Present,    ...
        Bina Shah,    Absent,     Present,    Present,    ...

    Column 1 is the student's name, every column after that is one class
    date (every session actually opened for this subject, from the
    `sessions` table), and each cell says Present or Absent for that
    student on that date.

    Query params:
      subject    — subject_id (required)
      start_date — e.g. 2026-06-01 (optional)
      end_date   — e.g. 2026-06-30 (optional)
    """
    if "teacher_id" not in session:
        return redirect(url_for("teacher_login"))
    subject_id = request.args.get("subject", "")
    from_date = request.args.get("start_date", "")
    to_date = request.args.get("end_date", "")

    conn = get_db()

    # 1. Every class date actually held for this subject (the columns).
    #    DISTINCT + "at least one scan happened" so opening a session just to
    #    test something (no one scans) doesn't create a phantom Absent-only
    #    column, and repeated test-opens on the same day don't duplicate it.
    sess_query = """
        SELECT DISTINCT s.date FROM sessions s
        WHERE s.subject_id=?
        AND EXISTS (
            SELECT 1 FROM attendance a
            WHERE a.subject_id = s.subject_id AND a.date = s.date
        )
    """
    sess_params = [subject_id]
    if from_date:
        sess_query += " AND s.date >= ?"
        sess_params.append(from_date)
    if to_date:
        sess_query += " AND s.date <= ?"
        sess_params.append(to_date)
    sess_query += " ORDER BY s.date ASC"
    session_dates = [r["date"] for r in conn.execute(sess_query, sess_params).fetchall()]

    # 2. Every student enrolled in this subject (the rows) — pulled via the
    #    subject's course/year so students with zero check-ins still appear
    #    (they'll just be Absent on every date).
    sub_info = conn.execute(
        "SELECT course, year FROM subjects WHERE subject_id=?", (subject_id,)
    ).fetchone()
    if sub_info:
        students = conn.execute(
            "SELECT student_id, name FROM students WHERE course=? AND year=? ORDER BY name ASC",
            (sub_info["course"], sub_info["year"])
        ).fetchall()
    else:
        students = []

    # 3. Every check-in for this subject in range, to know who was present when.
    att_query = """
        SELECT a.student_id, a.date
        FROM attendance a
        WHERE a.subject_id=?
    """
    att_params = [subject_id]
    if from_date:
        att_query += " AND a.date >= ?"
        att_params.append(from_date)
    if to_date:
        att_query += " AND a.date <= ?"
        att_params.append(to_date)
    att_rows = conn.execute(att_query, att_params).fetchall()
    conn.close()

    present_dates_by_student = {}
    for r in att_rows:
        present_dates_by_student.setdefault(r["student_id"], set()).add(r["date"])

    from flask import Response
    import csv, io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Student Name"] + session_dates + ["Days Present", "Total Days", "Attendance %"])

    total_days = len(session_dates)
    for stu in students:
        present_set = present_dates_by_student.get(stu["student_id"], set())
        row = [stu["name"]]
        present_count = 0
        for d in session_dates:
            is_present = d in present_set
            row.append("Present" if is_present else "Absent")
            if is_present:
                present_count += 1
        pct = round((present_count / total_days) * 100) if total_days > 0 else 0
        row += [present_count, total_days, f"{pct}%"]
        writer.writerow(row)
    output.seek(0)

    fname_suffix = subject_id
    if from_date or to_date:
        fname_suffix += f"_{from_date or 'start'}_to_{to_date or 'end'}"

    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename=attendance_{fname_suffix}.csv"}
    )

if __name__ == "__main__":
    app.run(debug=True)
    
    #for runninf in mobile phone change the above code to:
#if __name__ == "__main__":
    #app.run(host="0.0.0.0", port=5000, debug=True, ssl_context="adhoc")
