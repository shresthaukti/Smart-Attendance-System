import cv2
from insightface.app import FaceAnalysis
import database as db

face_app = FaceAnalysis(name='buffalo_l')
face_app.prepare(ctx_id=-1, det_size=(640, 640))

student_id = input("Enter student ID: ")
if not db.student_exists(student_id):
    print(f"Student {student_id} not found in database. Run setup.py first.")
    exit()

cap = cv2.VideoCapture(0)
print("Press SPACE to capture, Q to quit")

while True:
    ret, frame = cap.read()
    cv2.imshow("Register Face - " + student_id, frame)
    key = cv2.waitKey(1)

    if key == ord(' '):
        faces = face_app.get(frame)
        if faces:
            embedding = faces[0].normed_embedding
            db.register_student_face(student_id, "live_capture", embedding)
            name = db.get_student_name(student_id)
            print(f"✓ Face registered for {name} ({student_id})")
            break
        else:
            print("No face detected, try again")
    elif key == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()