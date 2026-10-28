import serial
import time

print("Menghubungkan ke Arduino...")

arduino = serial.Serial("COM9", 115200, timeout=1)

time.sleep(2)

print("TERHUBUNG!")

while True:

    print("KIRI -> 0")
    arduino.write(b"KIRI:0\n")
    time.sleep(2)

    print("KIRI -> 180")
    arduino.write(b"KIRI:180\n")
    time.sleep(2)

    print("KANAN -> 0")
    arduino.write(b"KANAN:0\n")
    time.sleep(2)

    print("KANAN -> 180")
    arduino.write(b"KANAN:180\n")
    time.sleep(2)