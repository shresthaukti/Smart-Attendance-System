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
