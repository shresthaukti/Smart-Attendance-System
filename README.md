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

## Getting Started
 
### Prerequisites
- Python 3.12+
- The ZBar library (required by `pyzbar`)
  - Windows: bundled with the `pyzbar` wheel
  - Ubuntu/Debian: `sudo apt install libzbar0`
  - macOS: `brew install zbar`
### Installation
 
```bash
git clone https://github.com/shresthaukti/Smart-Attendance-System.git
cd Smart-Attendance-System
 
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate
 
pip install -r requirements.txt
```
 
### Set up the database
 
`setup.py` creates all tables, imports users from `students.xlsx` and `teachers.xlsx`, and seeds the CE-II/II subjects and weekly routine.
 
```bash
python setup.py
```
 
To reset everything, delete `attendance.db` and run `setup.py` again.
 
### Run the app
 
```bash
python app.py
```
 
Open <http://127.0.0.1:5000>.
 
### Using it from a phone
 
Browsers only allow camera access over HTTPS. At the bottom of `app.py`, replace the `app.run(...)` call with:
 
```python
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True, ssl_context="adhoc")
```
 
Then open `https://<your-computer-ip>:5000` on a phone connected to the same network and accept the self-signed certificate warning.
 
### Docker
 
```bash
docker build -t smart-attendance .
docker run -p 5000:5000 smart-attendance
```
 
## How It Works
 
1. A teacher logs in and opens a session for a subject (matched to the weekly routine or an alternate slot).
2. Students present their ID card barcodes to the camera.
3. The scan is decoded, validated against the student list, and checked for an open session.
4. The record is saved, the student gets a notification, and the teacher's live view updates.
Each scan returns one of four outcomes:
 
| Code | Meaning |
|---|---|
| `G` | Attendance marked |
| `Y` | Already marked today |
| `R` | Student not found |
| `S` | Session not open |
 
## Key Endpoints
 
| Route | Purpose |
|---|---|
| `/student-login`, `/teacher-login` | Authentication |
| `/student-dashboard`, `/teacher-dashboard` | Role dashboards |
| `/api/session/open`, `/api/session/close`, `/api/session/status` | Session control |
| `/api/decode-frame`, `/api/scan-barcode`, `/scan` | Barcode scanning |
| `/api/live-attendance` | Live attendance feed |
| `/export/attendance` | CSV export |
| `/api/student/attendance` | Student attendance data |
| `/api/notifications` | Student notifications |
| `/api/chat/...` | Student–teacher messaging |
 
## Database
 
SQLite with tables for `students`, `teachers`, `subjects`, `routine`, `sessions`, `active_sessions`, `attendance`, `notifications`, and `chat_messages` (plus `student_faces` and `unrecognized_logs` for the experimental face-recognition scripts).
 
## Known Limitations
 
- Face recognition (`scanningtry.py`, `register_faces.py`) is experimental and needs `insightface`, which is not in `requirements.txt`.
- SQLite on free hosting tiers such as Render uses an ephemeral filesystem, so data resets on redeploy.
- Before any public deployment, move the Flask `secret_key` in `app.py` to an environment variable.
