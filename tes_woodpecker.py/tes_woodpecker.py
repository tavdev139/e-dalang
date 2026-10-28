
import serial
import time

PORT = "COM4"
BAUD = 115200

try:
    print("Menghubungkan ke Woodpecker...")

    grbl = serial.Serial(
        PORT,
        BAUD,
        timeout=2,
        write_timeout=2
    )

    time.sleep(2)
    grbl.reset_input_buffer()

    grbl.write(b"?")
    grbl.flush()

    time.sleep(0.5)
    jawaban = grbl.read_all().decode(
        "ascii",
        errors="replace"
    )

    print("\nRespons Woodpecker:")
    print(jawaban if jawaban.strip()
          else "Belum ada respons status.")

    grbl.close()
    print("\nTes komunikasi selesai.")

except Exception as e:
    print("\nGagal terhubung:", e)
    print("Periksa nomor COM dan tutup software CNC.")
