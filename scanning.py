# scanning.py — Person C
# Barcode attendance via phone IP camera
# Tracks scan duration + timestamp, saves to database

import cv2
import time
from pyzbar.pyzbar import decode
import database as db

# Phone IP camera URL (update IP if it changes)
CAMERA_URL = "http://192.168.101.7:4747/video"
# To use webcam instead: cv2.VideoCapture(0)

cap = cv2.VideoCapture(CAMERA_URL)

seen_barcodes = set()       # prevent duplicates this session
barcode_cooldowns = {}      # prevent re-scan within 5 seconds
barcode_first_seen = {}     # track when barcode first appeared (for duration)

status_message = ""
status_color = (255, 255, 255)

def clean_barcode(raw):
    """Strip ]C1 prefix from ID card barcodes"""
    if raw.startswith("]C1"):
        return raw[3:]
    return raw.strip()

while cap.isOpened():
    success, frame = cap.read()
    if not success:
        break

    frame = cv2.resize(frame, (800, 600))
    frame = cv2.flip(frame, 1)

    current_subject = db.get_current_active_subject()
    detectedBarcodes = decode(frame)

    if detectedBarcodes:
        for barcode in detectedBarcodes:
            raw_data = barcode.data.decode("utf-8")
            student_id = clean_barcode(raw_data)
            x, y, w, h = barcode.rect
            current_time = time.time()

            # Track when this barcode first appeared in frame
            if student_id not in barcode_first_seen:
                barcode_first_seen[student_id] = current_time

            # -------------------------------------------------------------
            # FIXED COLOR LOGIC FOR COOLDOWN / ACTIVE SCANS
            # -------------------------------------------------------------
            last_scan = barcode_cooldowns.get(student_id, 0)
            if (current_time - last_scan) < 5:
                # If it's on a cooldown, match its color to its known database status
                if not db.student_exists(student_id):
                    current_barcode_color = (0, 165, 255)  # ORANGE
                elif student_id in seen_barcodes:
                    current_barcode_color = (0, 255, 255)  # YELLOW
                else:
                    current_barcode_color = (0, 255, 0)    # GREEN
                
                # Draw box and text, then skip database saving
                cv2.rectangle(frame, (x, y), (x + w, y + h), current_barcode_color, 2)
                cv2.putText(frame, student_id, (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, current_barcode_color, 2)
                continue

            # Calculate scan duration
            scan_duration = current_time - barcode_first_seen[student_id]
            scan_timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

            barcode_cooldowns[student_id] = current_time
            barcode_first_seen.pop(student_id, None)  # reset for next scan

            # Determine identity and state
            if not db.student_exists(student_id):
                status_message = f"Unknown ID: {student_id}"
                status_color = (0, 165, 255)  # ORANGE

            elif student_id in seen_barcodes:
                student_name = db.get_student_name(student_id)
                status_message = f"Already marked: {student_name}"
                status_color = (0, 255, 255)  # YELLOW

            else:
                student_name = db.get_student_name(student_id)
                db.save_attendance_record(student_id, current_subject)
                seen_barcodes.add(student_id)
                status_message = (
                    f"Marked: {student_name} | "
                    f"{scan_timestamp} | "
                    f"Scan time: {scan_duration:.2f}s"
                )
                status_color = (0, 255, 0)  # GREEN
                print(f"[{scan_timestamp}] {student_name} ({student_id}) "
                      f"— {scan_duration:.2f}s — Subject: {current_subject}")

            # Draw the box and text for the newly processed frames
            cv2.rectangle(frame, (x, y), (x + w, y + h), status_color, 2)
            cv2.putText(frame, student_id, (x, y - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, status_color, 2)

    # Clear first_seen for barcodes no longer in frame
    visible_ids = {clean_barcode(b.data.decode("utf-8")) for b in detectedBarcodes}
    for sid in list(barcode_first_seen.keys()):
        if sid not in visible_ids:
            barcode_first_seen.pop(sid, None)

    # Status overlay banner across the top
    if status_message:
        cv2.rectangle(frame, (0, 0), (800, 80), (0, 0, 0), -1)
        cv2.putText(frame, status_message, (10, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, status_color, 2)
        cv2.putText(frame, f"Subject: {current_subject} | Q to quit",
                    (10, 68), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)

    cv2.imshow("Scanner", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()