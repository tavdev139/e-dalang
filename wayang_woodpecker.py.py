
import cv2
import mediapipe as mp
import serial
import time
import os

# =====================================
# KONFIGURASI
# =====================================
NANO_PORT = "COM9"
BAUD_RATE = 115200
CAMERA_INDEX = 0

MODEL_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "hand_landmarker.task"
)

# Gestur harus stabil sebelum perintah dikirim
STABIL_SECONDS = 0.30

# =====================================
# DETEKSI TELAPAK / KEPALAN
# =====================================
def deteksi_gestur(hand):
    # Empat ujung jari dan sendi di bawahnya
    ujung = [8, 12, 16, 20]
    sendi = [6, 10, 14, 18]

    jumlah_terbuka = 0

    for tip, pip in zip(ujung, sendi):
        if hand[tip].y < hand[pip].y:
            jumlah_terbuka += 1

    if jumlah_terbuka >= 3:
        return "telapak"

    return "kepalan"


# =====================================
# GAMBAR TANGAN
# =====================================
KONEKSI = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20),
    (0, 17)
]


def gambar_tangan(frame, hand, side, gesture):
    tinggi, lebar = frame.shape[:2]
    titik = []

    for lm in hand:
        x = int(lm.x * lebar)
        y = int(lm.y * tinggi)
        titik.append((x, y))

    # Kiri biru, kanan merah
    warna = (255, 100, 0) if side == "left" else (0, 0, 255)

    for a, b in KONEKSI:
        cv2.line(
            frame, titik[a], titik[b],
            (255, 255, 255), 2
        )

    for p in titik:
        cv2.circle(frame, p, 4, warna, -1)

    nama = "WAYANG 1" if side == "left" else "WAYANG 2"
    teks = f"{nama}: {gesture.upper()}"

    x_teks = max(10, min(lebar - 260, titik[0][0] - 50))
    y_teks = max(30, titik[0][1] - 20)

    cv2.putText(
        frame, teks, (x_teks, y_teks),
        cv2.FONT_HERSHEY_SIMPLEX, 0.65,
        warna, 2
    )


# =====================================
# PROGRAM UTAMA
# =====================================
def main():
    if not os.path.isfile(MODEL_PATH):
        print("Model tidak ditemukan:", MODEL_PATH)
        return

    arduino = None
    camera = None
    detector = None

    try:
        print("Menghubungkan Arduino Nano...")

        arduino = serial.Serial(
            NANO_PORT,
            BAUD_RATE,
            timeout=0.1,
            write_timeout=1
        )

        # Nano biasanya reset ketika serial dibuka
        time.sleep(2)
        print("Arduino Nano terhubung.")

        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision

        options = vision.HandLandmarkerOptions(
            base_options=mp_python.BaseOptions(
                model_asset_path=MODEL_PATH
            ),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=2,
            min_hand_detection_confidence=0.6,
            min_hand_presence_confidence=0.6,
            min_tracking_confidence=0.6
        )

        detector = vision.HandLandmarker.create_from_options(options)

        camera = cv2.VideoCapture(CAMERA_INDEX)

        if not camera.isOpened():
            raise RuntimeError("Webcam tidak bisa dibuka.")

        # Simpan status masing-masing tangan secara terpisah
        kandidat = {"left": None, "right": None}
        sejak = {"left": 0.0, "right": 0.0}
        status_terkirim = {"left": None, "right": None}

        timestamp_sebelumnya = 0

        print("\nE-DALANG SIAP")
        print("Tangan kiri = Wayang 1")
        print("Tangan kanan = Wayang 2")
        print("Telapak dan kepalan menghasilkan gerakan berlawanan.")
        print("Tekan Q pada jendela kamera untuk keluar.")

        while True:
            berhasil, frame = camera.read()

            if not berhasil:
                print("Gagal membaca webcam.")
                break

            # Tampilan selfie
            frame = cv2.flip(frame, 1)

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = mp.Image(
                image_format=mp.ImageFormat.SRGB,
                data=rgb
            )

            timestamp = int(time.monotonic() * 1000)
            timestamp = max(
                timestamp, timestamp_sebelumnya + 1
            )
            timestamp_sebelumnya = timestamp

            hasil = detector.detect_for_video(image, timestamp)
            sekarang = time.monotonic()

            tangan_terdeteksi = {}

            if hasil.hand_landmarks and hasil.handedness:
                for i, hand in enumerate(hasil.hand_landmarks):
                    if i >= len(hasil.handedness):
                        continue

                    if not hasil.handedness[i]:
                        continue

                    label = (
                        hasil.handedness[i][0]
                        .category_name.lower()
                    )

                    if label not in ("left", "right"):
                        continue

                    gesture = deteksi_gestur(hand)
                    tangan_terdeteksi[label] = (hand, gesture)

            # Setiap tangan hanya mengendalikan wayangnya sendiri
            for side in ("left", "right"):
                if side not in tangan_terdeteksi:
                    kandidat[side] = None
                    continue

                hand, gesture = tangan_terdeteksi[side]

                if kandidat[side] != gesture:
                    kandidat[side] = gesture
                    sejak[side] = sekarang

                elif (
                    sekarang - sejak[side] >= STABIL_SECONDS
                    and status_terkirim[side] != gesture
                ):
                    if side == "left":
                        perintah = (
                            "P" if gesture == "telapak" else "F"
                        )
                    else:
                        perintah = (
                            "H" if gesture == "telapak" else "G"
                        )

                    arduino.write(perintah.encode("ascii"))
                    status_terkirim[side] = gesture

                    print(
                        "WAYANG 1" if side == "left"
                        else "WAYANG 2",
                        ":", gesture.upper()
                    )

                gambar_tangan(frame, hand, side, gesture)

            cv2.putText(
                frame,
                "E-DALANG | Q = KELUAR",
                (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (0, 255, 0),
                2
            )

            cv2.imshow("E-DALANG - Kontrol Wayang", frame)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    except Exception as error:
        print("\nTERJADI ERROR:")
        print(error)

    finally:
        if detector is not None:
            detector.close()

        if camera is not None:
            camera.release()

        cv2.destroyAllWindows()

        if arduino is not None and arduino.is_open:
            arduino.close()

        print("Program E-DALANG berhenti.")


if __name__ == "__main__":
    main()
