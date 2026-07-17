"""
Skrypt diagnostyczny: Robi screenshot ADB, szuka lootu, i zapisuje obraz z zaznaczonym wykryciem.
Cel: sprawdzić czy wykryte współrzędne lootu odpowiadają faktycznej pozycji przedmiotu na ekranie.
"""
import os, sys, time, subprocess
import cv2
import numpy as np

# Konfiguracja (taka sama jak w rucoy_bot.py)
ADB_PATH = r"D:\Program Files\Nox\bin\nox_adb.exe"
DEVICE = "127.0.0.1:62001"
SCREEN_CENTER = (800, 450)
VISION_DOWNSCALE = 0.5
ITEM_MATCH_THRESHOLD = 0.63
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ITEM_TEMPLATES_DIR = os.path.join(BASE_DIR, "templates", "item_variants")
DEBUG_DIR = os.path.join(BASE_DIR, "debug")
os.makedirs(DEBUG_DIR, exist_ok=True)

def capture_adb():
    cmd = [ADB_PATH, "-s", DEVICE, "exec-out", "screencap", "-p"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, _ = proc.communicate(timeout=3)
    if stdout:
        img_array = np.frombuffer(stdout, dtype=np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        return img
    return None

def find_all_loot(img_bgr):
    """Zwraca listę wszystkich detekcji lootu z pozycjami i score."""
    item_templates_small = []
    item_template_names = []
    for fname in sorted(os.listdir(ITEM_TEMPLATES_DIR)):
        path = os.path.join(ITEM_TEMPLATES_DIR, fname)
        tpl = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if tpl is not None and tpl.size > 0:
            item_templates_small.append(cv2.resize(tpl, None, fx=VISION_DOWNSCALE, fy=VISION_DOWNSCALE))
            item_template_names.append(fname)

    img_small = cv2.resize(img_bgr, None, fx=VISION_DOWNSCALE, fy=VISION_DOWNSCALE)
    img_gray = cv2.cvtColor(img_small, cv2.COLOR_BGR2GRAY)
    # Maskowanie UI
    img_gray[0:int(50*VISION_DOWNSCALE), :] = 0
    img_gray[int(400*VISION_DOWNSCALE):, :] = 0
    img_gray[:, 0:int(75*VISION_DOWNSCALE)] = 0
    scale_back = 1.0 / VISION_DOWNSCALE

    center_x_s = int(SCREEN_CENTER[0] * VISION_DOWNSCALE)
    center_y_s = int(SCREEN_CENTER[1] * VISION_DOWNSCALE)
    roi_w = int(710 * VISION_DOWNSCALE)
    roi_h = int(710 * VISION_DOWNSCALE)
    min_x = max(0, center_x_s - roi_w // 2)
    max_x = min(img_gray.shape[1], center_x_s + roi_w // 2)
    min_y = max(0, center_y_s - roi_h // 2)
    max_y = min(img_gray.shape[0], center_y_s + roi_h // 2)

    crop_gray = img_gray[min_y:max_y, min_x:max_x]

    detections = []
    for idx, template in enumerate(item_templates_small):
        th, tw = template.shape[:2]
        if th >= crop_gray.shape[0] or tw >= crop_gray.shape[1]:
            continue
        result = cv2.matchTemplate(crop_gray, template, cv2.TM_CCOEFF_NORMED)
        locs = np.where(result >= ITEM_MATCH_THRESHOLD)
        for pt in zip(*locs[::-1]):
            score = result[pt[1], pt[0]]
            cx = min_x + pt[0] + tw // 2
            cy = min_y + pt[1] + th // 2
            real_cx = int(cx * scale_back)
            real_cy = int(cy * scale_back)
            detections.append({
                'x': real_cx, 'y': real_cy,
                'score': score,
                'name': item_template_names[idx],
                'tw': int(tw * scale_back), 'th': int(th * scale_back)
            })

    return detections, (int(min_x * scale_back), int(min_y * scale_back), int(max_x * scale_back), int(max_y * scale_back))

# --- MAIN ---
print(f"[Debug] Rozdzielczość oczekiwana: 1600x900, SCREEN_CENTER: {SCREEN_CENTER}")
print(f"[Debug] Pobieram screenshot z ADB...")
frame = capture_adb()
if frame is None:
    print("[BŁĄD] Nie udało się pobrać klatki z ADB!")
    sys.exit(1)

h, w = frame.shape[:2]
print(f"[Debug] Rozmiar klatki ADB: {w}x{h}")

if w != 1600 or h != 900:
    print(f"[!!! PROBLEM !!!] Klatka ADB ma rozmiar {w}x{h}, a oczekiwano 1600x900!")
    print(f"[!!! PROBLEM !!!] Wszystkie współrzędne SCREEN_CENTER, kliknięć i detekcji będą ROZSYNCHRONIZOWANE!")

detections, roi_bounds = find_all_loot(frame)
print(f"[Debug] ROI loot scan: x=[{roi_bounds[0]}..{roi_bounds[2]}], y=[{roi_bounds[1]}..{roi_bounds[3]}]")
print(f"[Debug] Znaleziono {len(detections)} detekcji lootu powyżej progu {ITEM_MATCH_THRESHOLD}:")

# Narysuj detekcje na obrazie
debug_img = frame.copy()
# ROI prostokąt
cv2.rectangle(debug_img, (roi_bounds[0], roi_bounds[1]), (roi_bounds[2], roi_bounds[3]), (255, 255, 0), 2)
# Środek ekranu (postać)
cv2.circle(debug_img, SCREEN_CENTER, 8, (0, 255, 0), -1)
cv2.putText(debug_img, "PLAYER", (SCREEN_CENTER[0]+10, SCREEN_CENTER[1]-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,0), 1)

for i, d in enumerate(detections):
    print(f"  [{i+1}] {d['name']}: pozycja=({d['x']}, {d['y']}), score={d['score']*100:.1f}%, rozmiar={d['tw']}x{d['th']}")
    color = (0, 0, 255)  # czerwone
    cv2.circle(debug_img, (d['x'], d['y']), 12, color, 3)
    cv2.putText(debug_img, f"{d['name']} {d['score']*100:.0f}%", (d['x']+15, d['y']-5), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
    # Wektor od środka
    dx = d['x'] - SCREEN_CENTER[0]
    dy = d['y'] - SCREEN_CENTER[1]
    print(f"       Wektor od SCREEN_CENTER: ({dx}, {dy})")
    cv2.arrowedLine(debug_img, SCREEN_CENTER, (d['x'], d['y']), color, 2)

out_path = os.path.join(DEBUG_DIR, "loot_debug_coords.png")
cv2.imwrite(out_path, debug_img)
print(f"\n[Debug] Zapisano obraz diagnostyczny: {out_path}")
print("[Debug] Otwórz go i sprawdź czy czerwone kółka trafiają w faktyczne przedmioty na podłodze!")
