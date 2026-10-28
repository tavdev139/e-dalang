import os
import subprocess
import threading
import time
from flask import Flask, render_template, Response, jsonify, request
import mss
import pyautogui
import cv2
import numpy as np

app = Flask(__name__)

process = None
process_output = []

def run_e_dalang():
    global process, process_output
    cmd = ["python", "main.py"]
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    for line in process.stdout:
        print(line, end="")
        process_output.append(line)
        if len(process_output) > 200:
            process_output.pop(0)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/start", methods=["POST"])
def start_app():
    global process
    if process is None or process.poll() is not None:
        threading.Thread(target=run_e_dalang, daemon=True).start()
        return jsonify({"status": "started", "message": "e-dalang started successfully!"})
    return jsonify({"status": "running", "message": "e-dalang is already running."})

@app.route("/stop", methods=["POST"])
def stop_app():
    global process
    if process is not None and process.poll() is None:
        process.terminate()
        return jsonify({"status": "stopped", "message": "e-dalang stopped."})
    return jsonify({"status": "not_running", "message": "e-dalang is not running."})

@app.route("/press/<key>", methods=["POST"])
def press_key(key):
    try:
        if key == "space":
            pyautogui.press("space")
        elif key == "esc":
            pyautogui.press("esc")
        elif key == "f11":
            pyautogui.press("f11")
        elif key == "p":
            pyautogui.press("p")
        else:
            pyautogui.press(key)
        return jsonify({"status": "success", "key": key})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/logs")
def get_logs():
    return jsonify({"logs": process_output})

def generate_frames():
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        while True:
            try:
                screenshot = sct.grab(monitor)
                img = np.array(screenshot)
                frame = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                frame = cv2.resize(frame, (1024, 576))
                ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if not ret:
                    continue
                frame_bytes = buffer.tobytes()
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            except Exception as e:
                print("Frame gen error:", e)
            time.sleep(0.05)

@app.route("/video_feed")
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == "__main__":
    # Auto-start e-dalang on container boot
    threading.Thread(target=run_e_dalang, daemon=True).start()
    print("Starting e-dalang Web Wrapper on port 7860")
    app.run(host="0.0.0.0", port=7860, debug=False)
