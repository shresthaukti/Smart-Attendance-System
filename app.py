from flask import Flask, render_template, request, redirect, url_for, session, jsonify, Response
import sqlite3
import bcrypt
import csv
import io
from datetime import date, datetime
from pyzbar.pyzbar import decode
import cv2
import numpy as np
import time

app = Flask(__name__)
app.secret_key = "ku_smart_attendance_secret_2026"

import os
DB_FILE = os.path.join(os.path.dirname(__file__), "attendance.db")


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def check_password(plain, hashed):
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def home():
    return render_template("main.html")


# ── STUDENT AUTH ──────────────────────────────────────────────────────────────

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
            session["student_id"]   = row["student_id"]
            session["student_name"] = row["name"]
            return redirect(url_for("student_dashboard"))
        return render_template("studentlogin.html", error="Invalid Student ID or password")
    return render_template("studentlogin.html")

@app.route("/student-logout")
def student_logout():
    session.pop("student_id", None)
    session.pop("student_name", None)
    return redirect(url_for("home"))


# ── TEACHER AUTH ──────────────────────────────────────────────────────────────

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
            session["teacher_id"]    = row["teacher_id"]
            session["teacher_name"]  = row["name"]
            session["teacher_dept"]  = row["department"]
            session["teacher_email"] = row["email"]
            return redirect(url_for("teacher_dashboard"))
        return render_template("teacherlogin.html", error="Invalid username or password")
    return render_template("teacherlogin.html")

@app.route("/teacher-logout")
def teacher_logout():
    session.pop("teacher_id", None)
    session.pop("teacher_name", None)
    return redirect(url_for("home"))


# ── STUDENT DASHBOARD ─────────────────────────────────────────────────────────

@app.route("/student-dashboard")
def student_dashboard():
    if "student_id" not in session:
        return redirect(url_for("student_login"))

    student_id = session["student_id"]
    conn = get_db()

    student = conn.execute(
        "SELECT student_id, name, course, year, email FROM students WHERE student_id = ?",
        (student_id,)
    ).fetchone()

    subjects = conn.execute(
        "SELECT subject_id, subject_name, room, teacher_name FROM subjects WHERE course=? AND year=?",
        (student["course"], student["year"])
    ).fetchall()

    from database import get_routine_for_course
    routine_rows = get_routine_for_course(student["course"], student["year"])
    routine = [
        {"day": r[0], "start_time": r[1], "end_time": r[2],
         "subject_id": r[3], "subject_name": r[4], "room": r[5], "teacher_name": r[6]}
        for r in routine_rows
    ]

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
        ).fetchone()[0] or 1
        pct = round((present / total_days) * 100)
        subject_stats.append({
            "subject_id": sid, "subject_name": sub["subject_name"],
            "teacher": sub["teacher_name"], "room": sub["room"],
            "present": present, "total": total_days, "percent": pct,
        })
        total_present += present
        total_classes += total_days

    overall_pct  = round((total_present / total_classes) * 100) if total_classes > 0 else 0
    absent_total = total_classes - total_present
    conn.close()

    return render_template(
        "studentdashboard.html",
        student=student, subjects=subjects, subject_stats=subject_stats,
        overall_pct=overall_pct, total_present=total_present,
        absent_total=absent_total, total_classes=total_classes, routine=routine,
    )


# ── STUDENT ATTENDANCE (AJAX) ─────────────────────────────────────────────────

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
        "SELECT subject_id FROM subjects WHERE course=? AND year=?",
        (student["course"], student["year"])
    ).fetchall()
    sub_ids = [s["subject_id"] for s in subs]

    query  = """SELECT a.date, a.subject_id, s.subject_name, a.time
                FROM attendance a
                JOIN subjects s ON a.subject_id = s.subject_id
                WHERE a.student_id = ?"""
    params = [student_id]
    if subject_id and subject_id in sub_ids:
        query += " AND a.subject_id = ?"
        params.append(subject_id)
    if filter_date:
        query += " AND a.date = ?"
        params.append(filter_date)
    query += " ORDER BY a.date DESC"

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return jsonify([
        {"date": r["date"], "subject_id": r["subject_id"],
         "subject_name": r["subject_name"], "time": r["time"], "status": "present"}
        for r in rows
    ])


# ── TEACHER DASHBOARD ─────────────────────────────────────────────────────────

@app.route("/teacher-dashboard")
def teacher_dashboard():
    if "teacher_id" not in session:
        return redirect(url_for("teacher_login"))

    teacher_name = session["teacher_name"]
    conn = get_db()

    subjects = conn.execute(
        "SELECT subject_id, subject_name, room, course, year FROM subjects WHERE teacher_name=?",
        (teacher_name,)
    ).fetchall()

    selected_sub = request.args.get("subject", subjects[0]["subject_id"] if subjects else None)
    today        = str(date.today())

    today_present    = []
    absent_students  = []
    all_students     = []
    monthly_stats    = []
    routine          = []
    todays_classes   = []   # ← NEW: today's routine classes for quick-open buttons
    session_open     = False
    roster_warning   = None

    if selected_sub:
        # Session state
        sub_session = conn.execute(
            "SELECT session_id FROM sessions WHERE subject_id=? AND date=?",
            (selected_sub, today)
        ).fetchone()
        if sub_session:
            active = conn.execute(
                "SELECT 1 FROM active_sessions WHERE session_id=?",
                (sub_session["session_id"],)
            ).fetchone()
            session_open = active is not None

        # Today's present
        today_present = conn.execute("""
            SELECT s.student_id, s.name, a.time
            FROM attendance a
            JOIN students s ON a.student_id = s.student_id
            WHERE a.subject_id=? AND a.date=?
            ORDER BY a.time ASC
        """, (selected_sub, today)).fetchall()

        sub_info = conn.execute(
            "SELECT course, year FROM subjects WHERE subject_id=?", (selected_sub,)
        ).fetchone()

        if sub_info:
            all_students = conn.execute(
                "SELECT student_id, name FROM students WHERE course=? AND year=?",
                (sub_info["course"], sub_info["year"])
            ).fetchall()

            # 60-student roster warning
            if len(all_students) > 60:
                roster_warning = (
                    f"This class has {len(all_students)} students, above the 60-student cap. "
                    f"Duplicate names are fine as long as Student IDs are unique."
                )

            present_ids     = {r["student_id"] for r in today_present}
            absent_students = [s for s in all_students if s["student_id"] not in present_ids]

            total_days = conn.execute(
                "SELECT COUNT(DISTINCT date) FROM attendance WHERE subject_id=?", (selected_sub,)
            ).fetchone()[0] or 1

            for stu in all_students:
                present_count = conn.execute(
                    "SELECT COUNT(DISTINCT date) FROM attendance WHERE student_id=? AND subject_id=?",
                    (stu["student_id"], selected_sub)
                ).fetchone()[0]
                pct = round((present_count / total_days) * 100)
                monthly_stats.append({
                    "name": stu["name"], "student_id": stu["student_id"],
                    "total": total_days, "present": present_count,
                    "absent": total_days - present_count, "percent": pct,
                    "status": "good" if pct >= 75 else "low"
                })

            # ── NEW: today's routine classes for quick-open buttons ──────────
            from database import get_todays_routine_subjects
            todays_classes = [
                {"subject_id": r[3], "subject_name": r[4],
                 "start_time": r[1], "end_time": r[2], "room": r[5]}
                for r in get_todays_routine_subjects(sub_info["course"], sub_info["year"])
            ]

            # Full weekly routine
            from database import get_routine_for_course
            routine = [
                {"day": r[0], "start_time": r[1], "end_time": r[2],
                 "subject_id": r[3], "subject_name": r[4], "room": r[5], "teacher_name": r[6]}
                for r in get_routine_for_course(sub_info["course"], sub_info["year"])
            ]

    class_stats = []
    for sub in subjects:
        total_days = conn.execute(
            "SELECT COUNT(DISTINCT date) FROM attendance WHERE subject_id=?", (sub["subject_id"],)
        ).fetchone()[0] or 1
        total_stu = conn.execute(
            "SELECT COUNT(*) FROM students WHERE course=? AND year=?",
            (sub["course"], sub["year"])
        ).fetchone()[0] or 1
        total_present_count = conn.execute(
            "SELECT COUNT(*) FROM attendance WHERE subject_id=?", (sub["subject_id"],)
        ).fetchone()[0]
        avg_pct = round((total_present_count / (total_days * total_stu)) * 100)
        class_stats.append({
            "subject_id": sub["subject_id"],
            "subject_name": sub["subject_name"],
            "percent": avg_pct
        })

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
        todays_classes=todays_classes,   # ← NEW
        class_stats=class_stats,
        session_open=session_open,
        roster_warning=roster_warning,   # ← NEW
        today=today,
    )


# ── SESSION CONTROL (AJAX) ────────────────────────────────────────────────────

@app.route("/api/session/open", methods=["POST"])
def api_open_session():
    """
    Opens a session for a subject, cross-checked against the routine table.
    If is_alternate=true, skips the routine check (for substitute/extra classes).
    """
    if "teacher_id" not in session:
        return jsonify({"ok": False})

    data         = request.json
    subject_id   = data.get("subject_id")
    is_alternate = bool(data.get("is_alternate", False))

    conn     = get_db()
    sub_info = conn.execute(
        "SELECT course, year FROM subjects WHERE subject_id=?", (subject_id,)
    ).fetchone()
    conn.close()

    if not sub_info:
        return jsonify({"ok": False, "message": "Unknown subject"})

    from database import open_session_for_routine
    success, message = open_session_for_routine(
        course=sub_info["course"],
        year=sub_info["year"],
        section="CE-II/II",     # update if you add more sections
        subject_id=subject_id,
        is_alternate=is_alternate,
    )
    return jsonify({"ok": success, "message": message})


@app.route("/api/session/close", methods=["POST"])
def api_close_session():
    """
    Closes a session and stamps check_out_time for all present students,
    giving a session-start → session-end duration per student in the export.
    """
    if "teacher_id" not in session:
        return jsonify({"ok": False})

    subject_id = request.json.get("subject_id")
    today_str  = str(date.today())

    conn = get_db()
    sess = conn.execute(
        "SELECT session_id FROM sessions WHERE subject_id=? AND date=?",
        (subject_id, today_str)
    ).fetchone()
    if sess:
        conn.execute("DELETE FROM active_sessions WHERE session_id=?", (sess["session_id"],))
        conn.commit()
    conn.close()

    # Stamp check_out_time for everyone who was present
    from database import checkout_all_present_students
    checkout_all_present_students(subject_id, today_str)

    return jsonify({"ok": True})


# ── NEW: today's routine (AJAX) ───────────────────────────────────────────────

@app.route("/api/todays-routine")
def api_todays_routine():
    """
    Returns today's scheduled classes for a given course/year.
    Called by the teacher dashboard to populate quick-open session buttons.
    """
    if "teacher_id" not in session:
        return jsonify([])
    course = request.args.get("course", "CE")
    year   = int(request.args.get("year", 2))

    from database import get_todays_routine_subjects
    classes = get_todays_routine_subjects(course, year)
    return jsonify([
        {"subject_id": r[3], "subject_name": r[4],
         "start_time": r[1], "end_time": r[2], "room": r[5]}
        for r in classes
    ])


# ── BARCODE DECODE (from camera feed via browser) ─────────────────────────────

@app.route('/api/decode-frame', methods=['POST'])
def decode_frame():
    decode_start = time.perf_counter()
    if 'frame' not in request.files:
        return jsonify({"success": False})
    img_bytes = request.files['frame'].read()
    npimg = np.frombuffer(img_bytes, np.uint8)
    frame = cv2.imdecode(npimg, cv2.IMREAD_COLOR)
    if frame is None:
        return jsonify({"success": False})
    barcodes = decode(frame)
    print(f"PYZBAR DECODE: {(time.perf_counter() - decode_start)*1000:.2f} ms")
    if not barcodes:
        return jsonify({"success": False})
    barcode = barcodes[0].data.decode("utf-8")
    return jsonify({"success": True, "barcode": barcode})


# ── SCAN FROM DASHBOARD ───────────────────────────────────────────────────────

@app.route("/api/scan-barcode", methods=["POST"])
def api_scan_barcode():
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
    name = ""
    if result_code in ("G", "Y"):
        conn = get_db()
        row  = conn.execute("SELECT name FROM students WHERE student_id=?", (student_id,)).fetchone()
        conn.close()
        name = row["name"] if row else student_id

    return jsonify({"result": result_code, "message": messages.get(result_code, "Unknown"), "name": name})


# ── SCAN FROM scanning.py (HTTP POST) ────────────────────────────────────────

@app.route("/scan", methods=["POST"])
def scan_from_phone():
    data = request.get_json()
    if not data:
        return jsonify({"result": "R", "message": "No data"}), 400
    student_id    = data.get("student_id", "").strip()
    subject_id    = data.get("subject_id", "").strip()
    scan_duration = data.get("scan_duration", None)
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
    if scan_duration and result_code == "G":
        print(f"[SCAN] {student_id} → {subject_id} | duration: {scan_duration:.2f}s")
    return jsonify({"result": result_code, "message": messages.get(result_code, "Unknown")})


# ── LIVE ATTENDANCE (AJAX auto-refresh) ──────────────────────────────────────

@app.route("/api/live-attendance")
def api_live_attendance():
    db_start = time.perf_counter()
    if "teacher_id" not in session:
        return jsonify([])
    subject_id = request.args.get("subject", "")
    if not subject_id:
        return jsonify([])

    conn  = get_db()
    today = str(date.today())
    rows  = conn.execute("""
        SELECT s.student_id, s.name, a.time
        FROM attendance a
        JOIN students s ON a.student_id = s.student_id
        WHERE a.subject_id = ? AND a.date = ?
        ORDER BY a.time ASC
    """, (subject_id, today)).fetchall()
    conn.close()
    print(f"ATTENDANCE PROCESS: {(time.perf_counter() - db_start)*1000:.2f} ms")
    return jsonify([
        {"student_id": r["student_id"], "name": r["name"], "time": r["time"]}
        for r in rows
    ])


# ── EXPORT CSV ────────────────────────────────────────────────────────────────

@app.route("/export/attendance")
def export_attendance():
    """
    Export attendance as CSV, filtered by subject and optional date range.
    Query params:
      subject    — subject_id (required)
      start_date — e.g. 2026-06-01 (optional)
      end_date   — e.g. 2026-06-30 (optional)

    Example: /export/attendance?subject=COMP232&start_date=2026-06-01&end_date=2026-06-30
    """
    if "teacher_id" not in session:
        return redirect(url_for("teacher_login"))

    subject_id = request.args.get("subject", "")
    start_date = request.args.get("start_date", "")
    end_date   = request.args.get("end_date", "")

    query  = """
        SELECT s.student_id, s.name, a.date, a.time, a.check_out_time
        FROM attendance a
        JOIN students s ON a.student_id = s.student_id
        WHERE a.subject_id = ?
    """
    params = [subject_id]
    if start_date:
        query += " AND a.date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND a.date <= ?"
        params.append(end_date)
    query += " ORDER BY a.date DESC, s.name ASC"

    conn = get_db()
    rows = conn.execute(query, params).fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Student ID", "Name", "Date", "Check-in Time", "Check-out Time"])
    for r in rows:
        writer.writerow([r["student_id"], r["name"], r["date"], r["time"], r["check_out_time"] or ""])
    output.seek(0)

    filename = f"attendance_{subject_id}"
    if start_date or end_date:
        filename += f"_{start_date or 'start'}_to_{end_date or 'end'}"

    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename={filename}.csv"}
    )


if __name__ == "__main__":
    app.run(debug=True)
    
    #for runninf in mobile phone change the above code to:
#if __name__ == "__main__":
    #app.run(host="0.0.0.0", port=5000, debug=True, ssl_context="adhoc")