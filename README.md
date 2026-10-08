# Smart Attendance System
A barcode-based attendance tracking web app designed around KU classrooms. Teachers open a class session, students scan their ID card barcodes, and attendance is recorded in real time with dashboards, notifications, and teacher–student chat.

## Features
 
**Teachers**
- Secure login (bcrypt-hashed passwords)
- Open and close attendance sessions per subject, following the weekly routine or an alternate slot
- Scan student ID barcodes from the dashboard using a phone camera (e.g. DroidCam) or webcam
- Live attendance view while a session is running
- Full attendance reports per subject, with CSV export (optional date range)
- Chat with students per subject


**Students**
- Login and personal dashboard with per-subject attendance counts and percentages
- Day-by-day attendance record
- Notification each time attendance is marked
- Chat with teachers, with unsend support
- Weekly class routine view
  
**System**
- Duplicate-scan protection (one record per student, subject, and day)
- Students and teachers imported in bulk from Excel sheets
- Mobile-friendly UI
- Docker + Gunicorn ready for deployment (tested on Render)

## Tech Stack
 
| Layer | Tools |
|---|---|
| Backend | Python, Flask, Gunicorn |
| Database | SQLite |
| Barcode scanning | OpenCV, pyzbar |
| Auth | bcrypt |
| Data import / export | openpyxl, CSV |
| Frontend | HTML, CSS, JavaScript (Jinja2 templates) |
| Deployment | Docker, Render |

## Project Structure
 
```
Smart-Attendance-System/
├── app.py                  # Flask app: routes, APIs, dashboards, chat, CSV export
├── database.py             # Schema, migrations, queries, Excel import, routine seeding
├── attendance.py           # Core scan logic + CLI attendance simulator
├── setup.py                # One-time DB creation, Excel import, routine seeding
├── scanning.py             # Standalone desktop barcode scanner (IP camera / webcam)
├── scanningtry.py          # Experimental barcode + face recognition scanner
├── register_faces.py       # Experimental face enrollment (InsightFace)
├── templates/              # Jinja2 pages (login, dashboards, chat)
├── static/                 # CSS and routine page
├── students.xlsx           # Student list (import source)
├── teachers.xlsx           # Teacher list (import source)
├── requirements.txt
└── Dockerfile
```
 
> `add_today_session.py`, `adjust_today.py`, `backfill_attendance.py`, `boost_attendance.py`, `fix_student_attendance.py`, and the `check*.py` files are one-off maintenance and debugging scripts.
