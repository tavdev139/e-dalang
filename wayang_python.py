
import cv2
import mediapipe as mp
import serial
import time
import os

# ==========================================
# KONFIGURASI
# ==========================================
ARDUINO_PORT = "COM9"
BAUD_RATE = 115200
CAMERA_INDEX = 0

MODEL_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "hand_landmarker.task"
)

# Sudut maksimum mengikuti program Arduino Nano
MAX_ANGLE = 25

# ==========================================
# KONEKSI ARDUINO
# ==========================================
nano = None

try:
    nano = serial.Serial(ARDUINO_PORT, BAUD_RATE, timeout=1)
    time.sleep(2)
    print("Arduino Nano berhasil terhubung!")
except Exception as e:
    print("Arduino Nano gagal terhubung:", e)
    print("Periksa COM9 dan tutup Serial Monitor Arduino IDE.")

# ==========================================
# MEDIAPIPE HAND LANDMARKER
# ==========================================
BaseOptions = mp.tasks.BaseOptions
HandLandmarker = mp.tasks.vision.HandLandmarker
HandLandmarkerOptions = mp.tasks.vision.HandLandmarkerOptions
RunningMode = mp.tasks.vision.RunningMode

options = HandLandmarkerOptions(
    base_options=BaseOptions(model_asset_path=MODEL_PATH),
    running_mode=RunningMode.VIDEO,
    num_hands=2
)

# ==========================================
# FUNGSI GERAK
# ==========================================
def gesture_angle(gesture):
    """Sudut dasar untuk gesture yang terdeteksi."""
    mapping = {
        "TELAPAK": 25,
        "KEPALAN": 0,
        "1 JARI": 15,
        "2 JARI": 20,
        "TIDAK DIKENAL": 0
    }
    return mapping.get(gesture, 0)


def opposite_angle(angle):
    """Membalik sudut agar gerakan kedua wayang berlawanan."""
    return MAX_ANGLE - angle


def send_nano(command):
    if nano is None:
        return

    try:
        nano.write((command + "\n").encode("utf-8"))
    except Exception as e:
        print("Gagal mengirim perintah:", e)


def detect_gesture(hand_landmarks):
    """
    Deteksi sederhana:
    TELAPAK, KEPALAN, 1 JARI, atau 2 JARI.
    """
    lm = hand_landmarks

    # Bandingkan ujung jari dengan sendi di bawahnya.
    # Untuk telunjuk, tengah, manis, kelingking.
    fingers_up = [
        lm[8].y < lm[6].y,    # Telunjuk
        lm[12].y < lm[10].y,  # Jari tengah
        lm[16].y < lm[14].y,  # Jari manis
        lm[20].y < lm[18].y   # Kelingking
    ]

    count = sum(fingers_up)

    if count >= 4:
        return "TELAPAK"
    elif count == 0:
        return "KEPALAN"
    elif fingers_up[0] and fingers_up[1] and count == 2:
        return "2 JARI"
    elif fingers_up[0] and count == 1:
        return "1 JARI"
    else:
        return "TIDAK DIKENAL"


# ==========================================
# KAMERA
# ==========================================
cap = cv2.VideoCapture(CAMERA_INDEX)

if not cap.isOpened():
    print("Kamera tidak terdeteksi!")
    if nano is not None:
        nano.close()
    raise SystemExit

# Posisi tulisan tetap di layar, bukan di tangan.
LEFT_LABEL_POS = (20, 40)
RIGHT_LABEL_POS = (20, 80)
STATUS_POS = (20, 125)

last_sent = {}
last_gesture = {"Left": None, "Right": None}

# ==========================================
# PROGRAM UTAMA
# ==========================================
try:
    with HandLandmarker.create_from_options(options) as landmarker:
        start_time = time.time()

        while True:
            success, frame = cap.read()
            if not success:
                print("Gagal membaca kamera.")
                break

            # Tampilan dicerminkan seperti cermin.
            frame = cv2.flip(frame, 1)
            height, width = frame.shape[:2]

            # Label tetap di pojok layar.
            cv2.putText(
                frame, "TANGAN KIRI",
                LEFT_LABEL_POS,
                cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                (255, 120, 0), 2, cv2.LINE_AA
            )

            cv2.putText(
                frame, "TANGAN KANAN",
                RIGHT_LABEL_POS,
                cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                (0, 0, 255), 2, cv2.LINE_AA
            )

            # MediaPipe VIDEO perlu timestamp yang terus meningkat.
            timestamp_ms = int((time.time() - start_time) * 1000)

            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(
                image_format=mp.ImageFormat.SRGB,
                data=rgb_frame
            )

            result = landmarker.detect_for_video(
                mp_image, timestamp_ms
            )

            found = {"Left": False, "Right": False}

            if result.hand_landmarks and result.handedness:
                for i, hand_landmarks in enumerate(result.hand_landmarks):
                    handedness = result.handedness[i][0].category_name

                    # Karena video dicerminkan, label handedness
                    # MediaPipe dibalik agar sesuai dengan tangan fisik.
                    if handedness == "Left":
                        side = "Right"
                    else:
                        side = "Left"

                    found[side] = True
                    gesture = detect_gesture(hand_landmarks)
                    angle = gesture_angle(gesture)

                    # Gambar landmark tangan.
                    points = []
                    for point in hand_landmarks:
                        px = int(point.x * width)
                        py = int(point.y * height)
                        points.append((px, py))

                    # Hubungkan landmark dengan garis putih.
                    connections = [
                        (0,1),(1,2),(2,3),(3,4),
                        (0,5),(5,6),(6,7),(7,8),
                        (5,9),(9,10),(10,11),(11,12),
                        (9,13),(13,14),(14,15),(15,16),
                        (13,17),(17,18),(18,19),(19,20),
                        (0,17)
                    ]

                    for a, b in connections:
                        cv2.line(
                            frame, points[a], points[b],
                            (255, 255, 255), 2
                        )

                    for point in points:
                        cv2.circle(
                            frame, point, 4,
                            (0, 255, 255), -1
                        )

                    # Label gesture tidak ditempel pada tangan.
                    # Informasi gesture ditampilkan di area status tetap.
                    if side == "Left":
                        cv2.putText(
                            frame, "KIRI: " + gesture,
                            (20, height - 55),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                            (255, 120, 0), 2, cv2.LINE_AA
                        )

                        # Wayang 1: sudut normal.
                        commands = {
                            "W1KIRI": angle,
                            "W1KANAN": angle
                        }

                    else:
                        cv2.putText(
                            frame, "KANAN: " + gesture,
                            (20, height - 25),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                            (0, 0, 255), 2, cv2.LINE_AA
                        )

                        # Wayang 2: sudut kebalikan.
                        reverse_angle = opposite_angle(angle)
                        commands = {
                            "W2KIRI": reverse_angle,
                            "W2KANAN": reverse_angle
                        }

                    # Kirim hanya saat sudut berubah.
                    for key, value in commands.items():
                        if last_sent.get(key) != value:
                            send_nano(f"{key}:{value}")
                            last_sent[key] = value

            # Jika tangan hilang dari kamera, jangan mengirim
            # gerakan acak. Wayang mempertahankan posisi terakhir.
            cv2.imshow("Wayang Gesture - Kiri dan Kanan", frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q") or key == 27:
                break

finally:
    cap.release()
    cv2.destroyAllWindows()

    if nano is not None and nano.is_open:
        nano.close()

    print("Program Wayang Gesture dihentikan.")
