"""
Skrypt szukający pomarańczowej ikony dłoni w prawym górnym rogu ekranu z ADB.
Przeszukuje obszar X=[1400..1600], Y=[150..400] w poszukiwaniu pomarańczowego koloru dłoni.
"""
import os, sys, time, subprocess
import cv2
import numpy as np

ADB_PATH = r"D:\Program Files\Nox\bin\nox_adb.exe"
DEVICE = "127.0.0.1:62001"

def capture_adb():
    cmd = [ADB_PATH, "-s", DEVICE, "exec-out", "screencap", "-p"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, _ = proc.communicate(timeout=3)
    if stdout:
        img_array = np.frombuffer(stdout, dtype=np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        return img
    return None

frame = capture_adb()
if frame is None:
    print("[BŁĄD] Brak klatki z ADB")
    sys.exit(1)

h, w = frame.shape[:2]
print(f"[Debug] Rozmiar klatki ADB: {w}x{h}")

# Obszar prawy górny (pod zębatką)
roi = frame[150:400, 1400:1600]

# Przekształć na HSV i znajdź pomarańczowe piksele łapki
hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
# Pomarańczowy kolor łapki w Rucoy (H: 10..25, S: 150..255, V: 150..255)
lower_orange = np.array([5, 140, 140])
upper_orange = np.array([30, 255, 255])
mask = cv2.inRange(hsv, lower_orange, upper_orange)

orange_y, orange_x = np.where(mask > 0)

if len(orange_x) > 0:
    center_x = int(np.mean(orange_x)) + 1400
    center_y = int(np.mean(orange_y)) + 150
    print(f"[SUKCES] Wykryto pomarańczową łapkę na pozycji: X={center_x}, Y={center_y}")
    print(f"Zakres X: [{np.min(orange_x)+1400}..{np.max(orange_x)+1400}], Zakres Y: [{np.min(orange_y)+150}..{np.max(orange_y)+150}]")
else:
    print("[OSTRZEŻENIE] Brak wykrytej pomarańczowej łapki w bieżącej klatce (brak lootu pod nogami?)")
    # Zapiszmy cropped ROI do analizy
    cv2.imwrite("debug/hand_icon_roi.png", roi)
    print("Zapisano debug/hand_icon_roi.png")
