
import cv2
import time
import serial
import mediapipe as mp

from mediapipe.tasks import python
from mediapipe.tasks.python import vision

# ==================================================
# KONFIGURASI
# ==================================================
NANO_PORT = "COM9"
GRBL_PORT = "COM4"
BAUD = 115200

MODEL_PATH = "hand_landmarker.task"

# Rentang koordinat awal stepper dalam mm.
# Pastikan rentang ini aman untuk mekanisme fisikmu.
X_MIN, X_MAX = 0.0, 50.0
Y_MIN, Y_MAX = 0.0, 50.0

# Gerakan stepper hanya diperbarui jika perubahan
# posisi target minimal 5 mm.
LANGKAH_MIN_MM = 5.0
KECEPATAN_GRBL = 300

# Perintah servo Nano yang digunakan sketch saat ini:
# F = Wayang 1 mengepal
# P = Wayang 1 telapak
# G = Wayang 2 mengepal
# H = Wayang 2 telapak

# ==================================================
# KONEKSI SERIAL
# ==================================================
nano = None
grbl = None
cap = None
landmarker = None


def kirim_grbl(perintah):
    """Kirim perintah gerak ke Woodpecker."""
    global grbl

    grbl.write((perintah + "\n").encode("ascii"))
    grbl.flush()

    # Tunggu jawaban GRBL agar perintah tidak menumpuk.
    deadline = time.time() + 3.0

    while time.time() < deadline:
        jawaban = grbl.readline().decode(
            "ascii", errors="replace"
        ).strip()

        if jawaban == "ok":
            return True

        if jawaban.startswith("error"):
            print("GRBL menolak perintah:", jawaban)
            return False

    print("Peringatan: respons GRBL belum diterima.")
    return False


def batasi(nilai, minimum, maksimum):
    return max(minimum, min(maksimum, nilai))


def posisi_ke_mm(x_normal, minimum, maksimum):
    """
    x_normal: posisi horizontal 0.0 sampai 1.0.
    Sisi kiri gambar = koordinat minimum.
    Sisi kanan gambar = koordinat maksimum.
    """
    return minimum + x_normal * (maksimum - minimum)


def jari_terangkat(hand):
    """
    Mengembalikan True jika jari telunjuk, tengah,
    manis, dan kelingking terangkat.
    Menggunakan landmark MediaPipe.
    """
    lm = hand

    telunjuk = lm[8].y < lm[6].y
    tengah = lm[12].y < lm[10].y
    manis = lm[16].y < lm[14].y
    kelingking = lm[20].y < lm[18].y

    return telunjuk and tengah and manis and kelingking


def kepalan(hand):
    lm = hand

    telunjuk = lm[8].y > lm[6].y
    tengah = lm[12].y > lm[10].y
    manis = lm[16].y > lm[14].y
    kelingking = lm[20].y > lm[18].y

    return telunjuk and tengah and manis and kelingking


def tentukan_sisi(handedness):
    """
    MediaPipe mengidentifikasi label Left / Right.
    Karena tampilan webcam bisa dicerminkan, label
    dapat berbeda dengan sisi pada layar.
    """
    if not handedness:
        return None

    return handedness[0].category_name.lower()


def main():
    global nano, grbl, cap, landmarker

    try:
        print("Menghubungkan Arduino Nano...")
        nano = serial.Serial(
            NANO_PORT, BAUD, timeout=0.1,
            write_timeout=1
        )
        time.sleep(2)
        nano.reset_input_buffer()
        print("Nano terhubung.")

        print("Menghubungkan Woodpecker...")
        grbl = serial.Serial(
            GRBL_PORT, BAUD, timeout=1,
            write_timeout=2
        )
        time.sleep(2)
        grbl.reset_input_buffer()

        # GRBL biasanya mengirim banner saat serial dibuka.
        # Jangan mengirim gerakan sebelum kamera aktif.
        print("Woodpecker terhubung.")

        print("Menyiapkan model MediaPipe...")
        base_options = python.BaseOptions(
            model_asset_path=MODEL_PATH
        )

        options = vision.HandLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.VIDEO,
            num_hands=2,
            min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.5
        )

        landmarker = vision.HandLandmarker.create_from_options(
            options
        )

        cap = cv2.VideoCapture(0)

        if not cap.isOpened():
            raise RuntimeError("Webcam tidak bisa dibuka.")

        # Gunakan koordinat absolut GRBL.
        # Tidak melakukan homing otomatis.
        if not kirim_grbl("G21"):
            raise RuntimeError("GRBL gagal menerima G21.")

        if not kirim_grbl("G90"):
            raise RuntimeError("GRBL gagal menerima G90.")

        # Target awal agar motor tidak langsung berpindah
        # hanya karena program baru dijalankan.
        target_x = None
        target_y = None

        # Hindari pengiriman perintah servo berulang.
        status_servo = {
            "left": None,
            "right": None
        }

        waktu_terakhir = 0
        nomor_frame = 0

        print("\nE-DALANG berjalan.")
        print("Tekan Q pada jendela kamera untuk berhenti.")
        print("Perhatikan gerakan mesin saat pengujian.")

        while True:
            sukses, frame = cap.read()

            if not sukses:
                print("Gagal membaca webcam.")
                break

            # Cerminkan gambar supaya gerakan terasa alami.
            frame = cv2.flip(frame, 1)
            tinggi, lebar = frame.shape[:2]

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(
                image_format=mp.ImageFormat.SRGB,
                data=rgb
            )

            nomor_frame += 1
            timestamp_ms = int(time.monotonic() * 1000)

            result = landmarker.detect_for_video(
                mp_image, timestamp_ms
            )

            tangan_terlihat = {
                "left": False,
                "right": False
            }

            if result.hand_landmarks:
                for i, hand in enumerate(result.hand_landmarks):
                    handedness = (
                        result.handedness[i]
                        if i < len(result.handedness)
                        else []
                    )

                    sisi = tentukan_sisi(handedness)

                    if sisi not in ("left", "right"):
                        continue

                    tangan_terlihat[sisi] = True

                    # Gambar titik landmark.
                    for titik in hand:
                        px = int(titik.x * lebar)
                        py = int(titik.y * tinggi)

                        cv2.circle(
                            frame, (px, py), 3,
                            (0, 255, 255), -1
                        )

                    # Pusat tangan dari landmark pergelangan.
                    wrist_x = hand[0].x

                    # Kiri -> X, kanan -> Y.
                    # Posisi horizontal dipetakan ke 0–50 mm.
                    if sisi == "left":
                        nilai_target = posisi_ke_mm(
                            wrist_x, X_MIN, X_MAX
                        )

                        # Inisialisasi pertama hanya menetapkan
                        # target software; tidak langsung bergerak.
                        if target_x is None:
                            target_x = nilai_target

                        elif abs(nilai_target - target_x) >= LANGKAH_MIN_MM:
                            target_x = nilai_target

                            perintah = (
                                f"G1 X{target_x:.1f} "
                                f"F{KECEPATAN_GRBL}"
                            )
                            print("Wayang 1 / X:", perintah)
                            kirim_grbl(perintah)

                    elif sisi == "right":
                        nilai_target = posisi_ke_mm(
                            wrist_x, Y_MIN, Y_MAX
                        )

                        if target_y is None:
                            target_y = nilai_target

                        elif abs(nilai_target - target_y) >= LANGKAH_MIN_MM:
                            target_y = nilai_target

                            perintah = (
                                f"G1 Y{target_y:.1f} "
                                f"F{KECEPATAN_GRBL}"
                            )
                            print("Wayang 2 / Y:", perintah)
                            kirim_grbl(perintah)

                    # Kontrol servo: telapak dan kepalan.
                    if jari_terangkat(hand):
                        nama_gesture = "TELAPAK"
                        perintah_servo = (
                            "P" if sisi == "left" else "H"
                        )
                    elif kepalan(hand):
                        nama_gesture = "KEPALAN"
                        perintah_servo = (
                            "F" if sisi == "left" else "G"
                        )
                    else:
                        nama_gesture = "LAINNYA"
                        perintah_servo = None

                    if perintah_servo is not None:
                        if status_servo[sisi] != perintah_servo:
                            nano.write(
                                perintah_servo.encode("ascii")
                            )
                            nano.flush()
                            status_servo[sisi] = perintah_servo

                    label = (
                        f"{sisi.upper()} - {nama_gesture}"
                    )

                    cv2.putText(
                        frame, label,
                        (15, 35 if sisi == "left" else 70),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.7, (0, 255, 0), 2
                    )

            # Jika tangan hilang, tunggu sampai muncul lagi.
            # Tidak mengirim perintah gerak baru.
            cv2.imshow("E-DALANG - Hand Tracking", frame)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    except Exception as e:
        print("\nTERJADI ERROR:", e)

    finally:
        print("\nMenghentikan program...")

        if cap is not None:
            cap.release()

        if landmarker is not None:
            landmarker.close()

        cv2.destroyAllWindows()

        if nano is not None and nano.is_open:
            nano.close()

        if grbl is not None and grbl.is_open:
            grbl.close()

        print("Koneksi serial ditutup.")


if __name__ == "__main__":
    main()
