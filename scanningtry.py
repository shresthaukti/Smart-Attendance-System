import cv2
import numpy as np
import os
import time
from pyzbar.pyzbar import decode, ZBarSymbol
from insightface.app import FaceAnalysis
import database as db

os.makedirs("unrecognized_faces", exist_ok=True)
db.create_database()

face_app = FaceAnalysis(name='buffalo_l')
face_app.prepare(ctx_id=-1, det_size=(640, 640))

known_students = db.load_known_face_dataset()
print(f"Loaded {len(known_students)} student face profiles from database.")

seen_barcodes = set()
status_message = ""
status_color = (255, 255, 255)
barcode_cooldowns = {}

def calculate_similarity(embedding1, embedding2):
    return np.dot(embedding1, embedding2) / (np.linalg.norm(embedding1) * np.linalg.norm(embedding2))

def process_classroom_faces(frame, target_subject, threshold=0.45):
    global known_students
    faces = face_app.get(frame)
    recognized_count = 0
    unrecognized_count = 0

    for face in faces:
        bbox = face.bbox.astype(int)
        detected_embedding = face.normed_embedding
        match_found = False
        matched_name = "Unknown"
        matched_id = None

        for student_id, data in known_students.items():
            if data["embedding"] is None:
                continue
            similarity = calculate_similarity(detected_embedding, data["embedding"])
            if similarity > threshold:
                match_found = True
                matched_id = student_id
                matched_name = data["name"]
                break

        if match_found:
            db.save_attendance_record(matched_id, target_subject)
            seen_barcodes.add(matched_id)
            recognized_count += 1
            cv2.rectangle(frame, (bbox[0], bbox[1]), (bbox[2], bbox[3]), (0, 255, 0), 2)
            cv2.putText(frame, matched_name, (bbox[0], bbox[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
        else:
            unrecognized_count += 1
            cv2.rectangle(frame, (bbox[0], bbox[1]), (bbox[2], bbox[3]), (0, 0, 255), 2)
            cv2.putText(frame, "Unrecognized", (bbox[0], bbox[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)

    return f"Faces: {len(faces)} | Matched: {recognized_count} | Unknown: {unrecognized_count}"


cap = cv2.VideoCapture(0)

while cap.isOpened():
    success, frame = cap.read()
    if not success:
        break

    frame = cv2.resize(frame, (800, 600))
    frame = cv2.flip(frame, 1)

    current_subject = db.get_current_active_subject()

    # ← face scanning runs every frame now, no barcode needed
    face_summary = process_classroom_faces(frame, current_subject)
    status_message = face_summary
    status_color = (0, 255, 0)

    # ← fixed barcode decode
    detectedBarcodes = decode(frame, symbols=[ZBarSymbol.QRCODE, ZBarSymbol.CODE128, ZBarSymbol.CODE39, ZBarSymbol.EAN13])

    if detectedBarcodes:
        for barcode in detectedBarcodes:
            barcode_data = barcode.data.decode("utf-8")
            x, y, w, h = barcode.rect
            current_time = time.time()

            if barcode_data not in barcode_cooldowns or (current_time - barcode_cooldowns[barcode_data]) > 5:
                barcode_cooldowns[barcode_data] = current_time

                if db.student_exists(barcode_data):
                    student_name = db.get_student_name(barcode_data)
                    if barcode_data in seen_barcodes:
                        status_message = f"Duplicate: {student_name}"
                        status_color = (0, 255, 255)
                    else:
                        db.save_attendance_record(barcode_data, current_subject)
                        seen_barcodes.add(barcode_data)
                        status_message = f"Verified: {student_name}"
                        status_color = (0, 255, 0)
                else:
                    status_message = f"Unknown ID: {barcode_data}"
                    status_color = (0, 165, 255)

            cv2.rectangle(frame, (x, y), (x + w, y + h), status_color, 2)
            cv2.putText(frame, barcode_data, (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, status_color, 2)

    if status_message:
        cv2.rectangle(frame, (20, 20), (780, 100), (0, 0, 0), -1)
        cv2.putText(frame, status_message, (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, status_color, 1, cv2.LINE_AA)
        cv2.putText(frame, f"Subject: {current_subject} | Q to quit", (30, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)

    cv2.imshow("Scanner", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()