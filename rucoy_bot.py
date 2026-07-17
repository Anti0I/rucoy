import os
import sys
import time
import random
import json
import ctypes
import subprocess
from ctypes import wintypes
import cv2
import numpy as np
import mss
import pydirectinput

# ==============================================================================
# 0. STEROWANIE I EKRAN W TLE (ADB CONTROLLER)
# ==============================================================================
class ADBController:
    def __init__(self, adb_path=None, device_address="127.0.0.1:62001"):
        self.device_address = device_address
        self.adb_path = adb_path or self._find_adb()
        self.connected = False

    def _find_adb(self):
        possible_paths = [
            r"D:\Program Files\Nox\bin\nox_adb.exe",
            r"C:\Program Files (x86)\Bignox\Nox\bin\nox_adb.exe",
            r"C:\Program Files\Nox\bin\nox_adb.exe",
            r"C:\Program Files (x86)\Nox\bin\nox_adb.exe",
            "adb.exe"
        ]
        for path in possible_paths:
            if os.path.exists(path):
                return path
        return "adb"

    def connect(self):
        try:
            res = subprocess.run([self.adb_path, "connect", self.device_address], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
            stdout_text = res.stdout.lower()
            if "connected" in stdout_text or "already connected" in stdout_text:
                self.connected = True
                print(f"[ADB] Połączono z emulatorem w tle: {self.device_address} (ścieżka: {self.adb_path})")
                return True
            else:
                print(f"[ADB] Status połączenia ADB: {res.stdout.strip()}")
                self.connected = True
                return True
        except Exception as e:
            print(f"[ADB] Ostrzeżenie przy łączeniu z ADB: {e}")
        return False

    def tap(self, x, y):
        """Wysyła tapnięcie w punkt (X, Y) w tle bez używania myszki systemowej."""
        cmd = [self.adb_path, "-s", self.device_address, "shell", "input", "tap", str(int(x)), str(int(y))]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def press_key(self, key):
        """
        Zamiast wysyłać komendy ADB keyevent (które w grze Rucoy traktowane są jako pisanie na klawiaturze fizycznej
        i wymuszają otwarcie okna czatu), wykonujemy bezpośrednie tąpnięcia ADB w wirtualne ikony skilli/potek na ekranie.
        """
        key_str = str(key).lower()
        button_coords = {
            'w': (100, 540),   # Przycisk ataku specjalnego (Skill Archer 'w')
            '3': (120, 830),   # Przycisk mikstury leczenia (HP)
            '1': (120, 700),   # Przycisk mikstury many (Mana)
            'h': (1545, 245),  # Przycisk zbierania lootu z podłogi (pomarańczowa łapka '✋ H' przy samej prawej krawędzi pod zębatką)
        }
        if key_str in button_coords:
            x, y = button_coords[key_str]
            self.tap(x, y)
            return f"OnScreenButton({x},{y})"
        elif key_str in ['back', 'esc']:
            cmd = [self.adb_path, "-s", self.device_address, "shell", "input", "keyevent", "111"]
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return "KEYCODE_ESCAPE(111)"
        return None

    def capture_frame(self):
        """Przechwytuje klatkę ekranu bezpośrednio z Androida w tle."""
        cmd = [self.adb_path, "-s", self.device_address, "exec-out", "screencap", "-p"]
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, _ = proc.communicate(timeout=2)
            if stdout:
                img_array = np.frombuffer(stdout, dtype=np.uint8)
                img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                return img
        except Exception as e:
            print(f"[ADB] Błąd pobierania klatki ekranu: {e}")
        return None

# ==============================================================================
# 1. KONFIGURACJA
# ==============================================================================
WINDOW_TITLE_SUBSTRING = "Nox"  # Szukane okno emulatora Nox
TARGET_RESOLUTION = (1600, 900)  # Docelowa rozdzielczość

# Współrzędne pasków HP i Many (wyznaczone precyzyjnie z pikseli obrazu Nox 1600x900)
HP_BAR_REGION = (10, 4, 485, 44)
MANA_BAR_REGION = (10, 46, 485, 54)

# Skróty klawiszowe (ustawione w Nox)
KEY_SPECIAL_ATTACK = 'w'
KEY_HEAL_POTION = '3'
KEY_MANA_POTION = '1'
KEY_LOOT = 'h'  # Klawisz zbierania przedmiotów z podłogi

# Progi procentowe i czasowe użycia potionów
HP_POTION_THRESHOLD = 0.75    # Użyj potiona leczenia poniżej 3/4 (75%) HP
MANA_POTION_THRESHOLD = 0.50  # Użyj potiona many poniżej 1/2 (50%) Mana
POTION_COOLDOWN = 1.0        # Odczekaj 1s po wypiciu potki, aby gra zdążyła uleczyć postać przed kolejnym odczytem

# Ustawienia prędkości chodzenia bota
WAYPOINT_STEP_DELAY = 0.18   # Opóźnienie między krokami trasy (180 ms)
MOVEMENT_SPEED_FACTOR = 0.10  # Czas w sekundach na 1 kratkę (płynny marsz bez pauz)
MIN_STEP_DELAY = 0.05          # Minimalne opóźnienie między krokami (brak przestojów)

# Limity i ścieżki
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
LIZARD_TEMPLATES_DIR = os.path.join(TEMPLATES_DIR, "lizard_variants")
ITEM_TEMPLATES_DIR = os.path.join(TEMPLATES_DIR, "item_variants")
SPIKE_TEMPLATES_DIR = os.path.join(TEMPLATES_DIR, "spike_variants")
ROUTES_DIR = os.path.join(BASE_DIR, "routes")
DEBUG_DIR = os.path.join(BASE_DIR, "debug")

# --- Ustawienia detekcji, kolców i smyczy bojowej ---
MATCH_THRESHOLD = 0.55          # Próg wykrywania jaszczurów (55% zgodności)
ITEM_MATCH_THRESHOLD = 0.63     # Próg wykrywania leżącego lootu (63% zgodności)
MAX_ATTACK_DIST_PX = 270        # Maksymalny dystans do moba (blizej niz 5 kratek, ok. 270px)
LEASH_MAX_TILES_X = 6           # Maksymalne odchylenie w osi X od kotwicy trasy (6 kratek)
LEASH_MAX_TILES_Y = 4           # Maksymalne odchylenie w osi Y od kotwicy trasy (4 kratki)
SCALE_RANGE = np.array([1.0])           # Jedna skala (mamy wystarczająco dużo wariantów szablonów)
DEBUG_MODE = False                       # Wyłączony zapis na dysk dla maksymalnej płynności
VISION_DOWNSCALE = 0.5                   # Przeskalowanie obrazu do 50% przy skanowaniu (4x szybciej)

# Wirtualny środek ekranu (pozycja naszej postaci)
SCREEN_CENTER = (800, 450)

# Trasa patrolowa (kliki relatywne od środka ekranu)
WAYPOINTS = [
    (250, 0),    # Krok na Wschód
    (250, 0),
    (0, 200),    # Krok na Południe
    (-250, 0),   # Krok na Zachód
    (-250, 0),
    (0, -200)    # Krok na Północ
]

# ==============================================================================
# 2. ZARZĄDZANIE OKNEM SYSTEMOWYM
# ==============================================================================
user32 = ctypes.windll.user32
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, ctypes.c_void_p)


def enum_windows_callback(hwnd, extra_list):
    length = user32.GetWindowTextLengthW(hwnd)
    if length > 0:
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value
        if user32.IsWindowVisible(hwnd) and ("Nox" in title or "nox" in title.lower()):
            extra_list.append((hwnd, title))
    return True


class WindowManager:
    def __init__(self, title_substring="Nox"):
        self.title_substring = title_substring
        self.hwnd = None
        self.window_title = ""

    def find_window(self):
        windows = []
        callback = EnumWindowsProc(lambda hwnd, lparam: enum_windows_callback(hwnd, windows))
        user32.EnumWindows(callback, 0)
        if windows:
            self.hwnd, self.window_title = windows[0]
            return True
        else:
            self.window_title = "Nox Player (Background ADB Mode)"
            return True

    def focus_window(self):
        if not self.hwnd:
            return False
        if user32.IsIconic(self.hwnd):
            user32.ShowWindow(self.hwnd, 9)  # SW_RESTORE
            time.sleep(0.2)
        try:
            user32.SetForegroundWindow(self.hwnd)
        except Exception:
            pass
        time.sleep(0.2)
        return True

    def get_client_rect(self):
        if not self.hwnd:
            return {"left": 0, "top": 0, "width": 1600, "height": 900}
        rect_struct = wintypes.RECT()
        user32.GetClientRect(self.hwnd, ctypes.byref(rect_struct))
        point = wintypes.POINT(0, 0)
        user32.ClientToScreen(self.hwnd, ctypes.byref(point))
        return {
            "left": point.x,
            "top": point.y,
            "width": rect_struct.right - rect_struct.left,
            "height": rect_struct.bottom - rect_struct.top
        }

    def resize_and_position(self, width=1600, height=900):
        if not self.hwnd:
            return False
        w_rect = wintypes.RECT()
        c_rect = wintypes.RECT()
        user32.GetWindowRect(self.hwnd, ctypes.byref(w_rect))
        user32.GetClientRect(self.hwnd, ctypes.byref(c_rect))
        border_width = (w_rect.right - w_rect.left) - c_rect.right
        border_height = (w_rect.bottom - w_rect.top) - c_rect.bottom
        new_w = width + border_width
        new_h = height + border_height
        user32.SetWindowPos(self.hwnd, 0, w_rect.left, w_rect.top, new_w, new_h, 0x0010 | 0x0004)
        time.sleep(0.3)
        return True


# ==============================================================================
# 3. DETEKCJA OBRAZU
# ==============================================================================
class GameVision:
    def __init__(self):
        self.sct = mss.MSS()
        self.templates = []          # pełna rozdzielczość
        self.templates_small = []    # przeskalowane 50% do szybkiego skanowania
        self.item_templates = []
        self.item_templates_small = []
        self.item_template_names = []
        self.load_templates()
        self.load_item_templates()
        if DEBUG_MODE:
            os.makedirs(DEBUG_DIR, exist_ok=True)

    def load_templates(self):
        """Ładuje wszystkie warianty szablonów jaszczura z folderu templates/lizard_variants."""
        if not os.path.exists(LIZARD_TEMPLATES_DIR):
            print(f"[Vision] Brak folderu {LIZARD_TEMPLATES_DIR}")
            return False

        for fname in sorted(os.listdir(LIZARD_TEMPLATES_DIR)):
            path = os.path.join(LIZARD_TEMPLATES_DIR, fname)
            tpl = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            if tpl is not None and tpl.size > 0:
                self.templates.append(tpl)
                self.templates_small.append(cv2.resize(tpl, None, fx=VISION_DOWNSCALE, fy=VISION_DOWNSCALE))

        if self.templates:
            print(f"[Vision] Załadowano {len(self.templates)} wariantów szablonu jaszczura.")
            return True
        print("[Vision] Brak wariantów szablonów w templates/lizard_variants.")
        return False

    def load_item_templates(self):
        """Ładuje wszystkie warianty szablonów lootu z folderu templates/item_variants."""
        if not os.path.exists(ITEM_TEMPLATES_DIR):
            return False

        for fname in sorted(os.listdir(ITEM_TEMPLATES_DIR)):
            path = os.path.join(ITEM_TEMPLATES_DIR, fname)
            tpl = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            if tpl is not None and tpl.size > 0:
                self.item_templates.append(tpl)
                self.item_templates_small.append(cv2.resize(tpl, None, fx=VISION_DOWNSCALE, fy=VISION_DOWNSCALE))
                self.item_template_names.append(fname)

        if self.item_templates:
            print(f"[Vision] Załadowano {len(self.item_templates)} wariantów szablonu lootu.")
            return True
        print("[Vision] Brak wariantów szablonów lootu w templates/item_variants.")
        return False



    def capture_client_area(self, client_rect, adb_controller=None):
        if adb_controller and adb_controller.connected:
            frame = adb_controller.capture_frame()
            if frame is not None:
                return frame

        monitor = {
            "top": client_rect["top"],
            "left": client_rect["left"],
            "width": client_rect["width"],
            "height": client_rect["height"]
        }
        screenshot = self.sct.grab(monitor)
        img = np.array(screenshot)
        return img[:, :, :3]

    def _mask_ui(self, img_gray):
        """Wyczernia obszary interfejsu, żeby detekcja nie łapała UI zamiast mobków."""
        masked = img_gray.copy()
        masked[0:100, :] = 0            # Menu górne
        masked[800:900, :] = 0          # Czat na dole
        masked[:, 0:150] = 0            # Panel skilli (lewy)
        masked[600:900, 1400:1600] = 0  # Panel broni (prawy dolny róg)
        return masked

    def find_lizard_target(self, img_bgr, threshold=MATCH_THRESHOLD):
        """
        Multi-scale, multi-template matching.
        Wyszukuje wszystkie dopasowania na ekranie, wylicza dystans euklidesowy
        do środka ekranu (gracza) i zwraca NAJBLIŻSZY cel.
        """
        if not self.templates_small:
            return None, 0.0

        img_small = cv2.resize(img_bgr, None, fx=VISION_DOWNSCALE, fy=VISION_DOWNSCALE)
        img_gray = cv2.cvtColor(img_small, cv2.COLOR_BGR2GRAY)
        h_s, w_s = img_gray.shape[:2]
        img_gray[0:int(50*VISION_DOWNSCALE), :] = 0
        img_gray[int(400*VISION_DOWNSCALE):, :] = 0
        img_gray[:, 0:int(75*VISION_DOWNSCALE)] = 0
        scale_back = 1.0 / VISION_DOWNSCALE

        best_score = 0.0
        closest_target = None
        closest_dist = float('inf')
        best_size = None
        best_loc = None

        center_x, center_y = SCREEN_CENTER

        center_x_s = int(center_x * VISION_DOWNSCALE)
        center_y_s = int(center_y * VISION_DOWNSCALE)

        for template in self.templates_small:
            th, tw = template.shape[:2]
            if th >= img_gray.shape[0] or tw >= img_gray.shape[1]:
                continue
            
            result = cv2.matchTemplate(img_gray, template, cv2.TM_CCOEFF_NORMED)
            locs = np.where(result >= threshold)
            
            for pt in zip(*locs[::-1]):
                score = result[pt[1], pt[0]]
                if score > best_score:
                    best_score = score
                
                cx = pt[0] + tw // 2
                cy = pt[1] + th // 2
                dist = np.sqrt((cx - center_x_s) ** 2 + (cy - center_y_s) ** 2)
                
                if dist < closest_dist:
                    closest_dist = dist
                    # Przelicz współrzędne z powrotem na pełną rozdzielczość
                    real_cx = int(cx * scale_back)
                    real_cy = int(cy * scale_back)
                    closest_target = (real_cx, real_cy + int(th * scale_back) + 25)
                    best_loc = pt
                    best_size = (th, tw)

        return closest_target, best_score

    def find_loot_target(self, img_bgr, threshold=ITEM_MATCH_THRESHOLD, blacklist=None):
        """
        Wyszukuje przedmioty leżące na podłodze. Zwraca najbliższy loot (pozycja środka przedmiotu),
        wynik dopasowania oraz nazwę pliku wykrytego przedmiotu.
        Ignoruje pozycje znajdujące się na aktywnej czarnej liście.
        """
        if not self.item_templates_small:
            return None, 0.0, None

        img_small = cv2.resize(img_bgr, None, fx=VISION_DOWNSCALE, fy=VISION_DOWNSCALE)
        img_gray = cv2.cvtColor(img_small, cv2.COLOR_BGR2GRAY)
        # Maskowanie UI (menu, czat)
        img_gray[0:int(50*VISION_DOWNSCALE), :] = 0
        img_gray[int(400*VISION_DOWNSCALE):, :] = 0
        img_gray[:, 0:int(75*VISION_DOWNSCALE)] = 0
        scale_back = 1.0 / VISION_DOWNSCALE

        best_score = 0.0
        closest_target = None
        closest_dist = float('inf')
        best_size = None
        best_loc = None
        best_name = None

        center_x, center_y = SCREEN_CENTER
        center_x_s = int(center_x * VISION_DOWNSCALE)
        center_y_s = int(center_y * VISION_DOWNSCALE)

        # Wycięcie obszaru ROI 710x710 px wokół postaci (+1 kratka w każdą stronę, ok. 355x355 px w skalowanym obrazie)
        roi_w = int(710 * VISION_DOWNSCALE)
        roi_h = int(710 * VISION_DOWNSCALE)
        min_x = max(0, center_x_s - roi_w // 2)
        max_x = min(img_gray.shape[1], center_x_s + roi_w // 2)
        min_y = max(0, center_y_s - roi_h // 2)
        max_y = min(img_gray.shape[0], center_y_s + roi_h // 2)

        crop_gray = img_gray[min_y:max_y, min_x:max_x]

        now_t = time.time()
        active_blacklist = [b for b in (blacklist or []) if now_t - b[2] < 25.0]

        for idx, template in enumerate(self.item_templates_small):
            th, tw = template.shape[:2]
            if th >= crop_gray.shape[0] or tw >= crop_gray.shape[1]:
                continue
            
            result = cv2.matchTemplate(crop_gray, template, cv2.TM_CCOEFF_NORMED)
            locs = np.where(result >= threshold)
            
            for pt in zip(*locs[::-1]):
                score = result[pt[1], pt[0]]
                cx = min_x + pt[0] + tw // 2
                cy = min_y + pt[1] + th // 2
                real_cx = int(cx * scale_back)
                real_cy = int(cy * scale_back)

                # Sprawdzenie czy cel nie znajduje się w odległości < 50px od zablokowanego lootu
                is_blacklisted = False
                for bx, by, _ in active_blacklist:
                    if np.sqrt((real_cx - bx) ** 2 + (real_cy - by) ** 2) < 50.0:
                        is_blacklisted = True
                        break

                if is_blacklisted:
                    continue

                if score > best_score:
                    best_score = score
                
                dist = np.sqrt((cx - center_x_s) ** 2 + (cy - center_y_s) ** 2)
                
                if dist < closest_dist:
                    closest_dist = dist
                    closest_target = (real_cx, real_cy)
                    best_loc = (min_x + pt[0], min_y + pt[1])
                    best_size = (th, tw)
                    best_name = self.item_template_names[idx] if idx < len(self.item_template_names) else "Item"

        return closest_target, best_score, best_name


    def _save_loot_debug_frame(self, img_bgr, loc, size, score, threshold):
        h, w = size
        vis = img_bgr.copy()
        color = (255, 255, 0) if score >= threshold else (0, 0, 255)
        cv2.rectangle(vis, loc, (loc[0] + w, loc[1] + h), color, 2)
        cv2.putText(vis, f"LOOT score={score:.3f}", (loc[0], max(loc[1] - 10, 15)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        cv2.imwrite(os.path.join(DEBUG_DIR, "last_loot_match.png"), vis)

    def _save_debug_frame(self, img_bgr, loc, size, score, threshold):
        h, w = size
        vis = img_bgr.copy()
        color = (0, 255, 0) if score >= threshold else (0, 0, 255)
        cv2.rectangle(vis, loc, (loc[0] + w, loc[1] + h), color, 2)
        cv2.putText(vis, f"score={score:.3f}", (loc[0], max(loc[1] - 10, 15)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        cv2.imwrite(os.path.join(DEBUG_DIR, "last_match.png"), vis)

    def is_stat_low(self, img_bgr, stat_name, threshold=0.75):
        """
        Sprawdza, czy pasek HP lub Many spadł poniżej bezpiecznego poziomu.
        Badamy prawą krawędź paska HP (x=445), całkowicie wolną od napisu cyfrowego.
        """
        if stat_name == "hp":
            left, top, right, bottom = HP_BAR_REGION
            # Czerwony kolor HP w BGR (Czerwony dominujący)
            def is_valid_color(pixel):
                b, g, r = int(pixel[0]), int(pixel[1]), int(pixel[2])
                return r > (g + 35) and r > (b + 35) and r > 110
            
            # Punkt x=400 jest prawą krawędzią czerwonego paska, idealną i czystą przy pełnym HP
            threshold_x = 400
            y_range = range(18, 38)
        else:
            left, top, right, bottom = MANA_BAR_REGION
            # Błękitny/Niebieski kolor Many w BGR
            def is_valid_color(pixel):
                b, g, r = int(pixel[0]), int(pixel[1]), int(pixel[2])
                return b > (r + 30) and b > 110
            
            total_width = right - left
            threshold_x = int(left + total_width * threshold)
            y_range = range(45, 54)

        if threshold_x >= img_bgr.shape[1]:
            return False

        # Skanujemy pionową kolumnę Y w wolnym od tekstu obszarze paska
        has_color = False
        for y in y_range:
            if y < img_bgr.shape[0]:
                if is_valid_color(img_bgr[y, threshold_x]):
                    has_color = True
                    break

        if DEBUG_MODE and not has_color and stat_name == "hp":
            print(f"[DEBUG_HP_FAIL] stat={stat_name} thresh_x={threshold_x} Brak czerwieni w czystym obszarze Y={y_range}")

        return not has_color


# ==============================================================================
# 4. STEROWANIE MYSZKĄ I KLAWIATURĄ
# ==============================================================================
pydirectinput.FAILSAFE = False


class GameController:
    def __init__(self, adb_controller=None):
        self.adb = adb_controller

    def click_relative(self, client_rect, relative_x, relative_y, jitter=3):
        abs_x = relative_x + random.randint(-jitter, jitter)
        abs_y = relative_y + random.randint(-jitter, jitter)

        # 1. Bezwzględna ochrona interfejsu UI w Rucoy:
        # Górny pasek/ikona czatu (Y < 105), dolny pasek czatu (Y > 795), lewy panel skilli (X < 155), prawy panel broni (X > 1400 i Y > 600)
        abs_y = max(105, min(795, abs_y))
        abs_x = max(155, min(1590, abs_x))
        if abs_y > 600 and abs_x > 1400:
            abs_x = 1395

        # 2. Ochrona ciała postaci gracza na środku ekranu (800x450):
        # Tąpnięcie bezpośrednio w ciało postaci (X: 760..840, Y: 380..500) otwiera ekwipunek.
        if 760 <= abs_x <= 840 and 380 <= abs_y <= 500:
            if abs_y < 450:
                abs_y = 360  # Odsuwamy lekko nad ciało postaci
            else:
                abs_y = 530  # Odsuwamy lekko pod stopy postaci

        if self.adb and self.adb.connected:
            print(f"[ADB Tap] Tapnięcie na ekranie: ({abs_x}, {abs_y}) [Wektor od środka: ({relative_x - SCREEN_CENTER[0]}, {relative_y - SCREEN_CENTER[1]})]")
            self.adb.tap(abs_x, abs_y)
        else:
            screen_x = client_rect["left"] + abs_x
            screen_y = client_rect["top"] + abs_y
            print(f"[Mouse Click] Kliknięcie myszą: ({screen_x}, {screen_y}) [Względne: ({abs_x}, {abs_y})]")
            pydirectinput.moveTo(screen_x, screen_y)
            pydirectinput.click()

    def press_key(self, key):
        if self.adb and self.adb.connected:
            code = self.adb.press_key(key)
            print(f"[ADB Key] Klawisz: '{key}' (ADB KEYCODE_{code})")
        else:
            print(f"[Mouse Key] Klawisz: '{key}'")
            pydirectinput.press(key)


# ==============================================================================
# 5. PĘTLA GŁÓWNA I MASZYNA STANÓW
# ==============================================================================
# ==============================================================================
# 5. PĘTLA GŁÓWNA I MASZYNA STANÓW
# ==============================================================================
class BotState:
    PATROL = "PATROL"
    ATTACK = "ATTACK"


class RucoyBot:
    def __init__(self, window_mgr, vision, controller, route_filename=None):
        self.window_mgr = window_mgr
        self.vision = vision
        self.controller = controller

        self.state = BotState.PATROL
        self.last_attack_time = 0
        self.last_hp_pot_time = 0
        self.last_mana_pot_time = 0

        self.anchor_offset_x = 0.0
        self.anchor_offset_y = 0.0

        # Timery i cache skanowania wizualnego (throttling)
        self.last_lizard_scan_time = 0
        self.last_loot_scan_time = 0
        self.cached_mob_target = None
        self.cached_mob_score = 0.0
        self.cached_loot_target = None
        self.cached_loot_score = 0.0
        self.cached_loot_name = None
        self.loot_blacklist = []  # Czarna lista niepodnoszalnych pozycji lootu [(x, y, timestamp)]

        self.waypoints = []
        self.wp_index = 0
        self.last_wp_vector = None
        if route_filename:
            self.load_route(route_filename)
        else:
            default_l4 = os.path.join(ROUTES_DIR, "l4_route.json")
            if os.path.isfile(default_l4):
                self.load_route("l4_route.json")

    def load_route(self, route_filename):
        if not route_filename.endswith(".json"):
            route_filename += ".json"
        path = os.path.join(ROUTES_DIR, route_filename)
        if not os.path.isfile(path):
            print(f"[Route] Ostrzeżenie: Plik trasy {path} nie istnieje.")
            return False

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.waypoints = data.get("waypoints", [])
                print(f"[Route] Załadowano ścieżkę '{route_filename}' z {len(self.waypoints)} waypointami.")
                return True
        except Exception as e:
            print(f"[Route] Błąd podczas ładowania trasy {path}: {e}")
            return False



    def run_step(self):
        client_rect = self.window_mgr.get_client_rect()
        if not client_rect:
            print("[Bot] Błąd: Brak dostępu do Nox Client.")
            return

        screen = self.vision.capture_client_area(client_rect, adb_controller=self.controller.adb)

        # 1. Survival Check (Priorytet najwyższy z regulowanym POTION_COOLDOWN)
        now_pot = time.time()
        if self.vision.is_stat_low(screen, "hp", HP_POTION_THRESHOLD):
            if now_pot - self.last_hp_pot_time > POTION_COOLDOWN:
                print(f"[Survival] Niskie HP! Używam mikstury leczenia (Klawisz: {KEY_HEAL_POTION}).")
                self.controller.press_key(KEY_HEAL_POTION)
                self.last_hp_pot_time = now_pot

        if self.vision.is_stat_low(screen, "mana", MANA_POTION_THRESHOLD):
            if now_pot - self.last_mana_pot_time > POTION_COOLDOWN:
                print(f"[Survival] Niska Mana! Używam mikstury many (Klawisz: {KEY_MANA_POTION}).")
                self.controller.press_key(KEY_MANA_POTION)
                self.last_mana_pot_time = now_pot

        # 2. Skanowanie wizualne z throttlingiem czasowym (NIE co klatkę!)
        now_scan = time.time()

        # Lizardy: co 0.6s
        if now_scan - self.last_lizard_scan_time > 0.6:
            self.cached_mob_target, self.cached_mob_score = self.vision.find_lizard_target(screen)
            self.last_lizard_scan_time = now_scan

        # Loot: co 0.4s (szybkie wykrywanie nowych dropów)
        if now_scan - self.last_loot_scan_time > 0.4:
            self.cached_loot_target, self.cached_loot_score, self.cached_loot_name = self.vision.find_loot_target(screen, blacklist=self.loot_blacklist)
            self.last_loot_scan_time = now_scan

        mob_target = self.cached_mob_target
        mob_score = self.cached_mob_score
        loot_target = self.cached_loot_target
        loot_score = self.cached_loot_score
        loot_name = self.cached_loot_name

        # Wyliczenie dystansu kafelkowego i klasyfikacja bliskich/dalekich mobków
        tile_size_px = 54.3
        is_close_mob = False
        is_far_mob = False

        if mob_target:
            dx = mob_target[0] - SCREEN_CENTER[0]
            dy = mob_target[1] - SCREEN_CENTER[1]
            tiles_x = abs(dx) / tile_size_px
            tiles_y = abs(dy) / tile_size_px

            if tiles_x <= 3.0 and tiles_y <= 3.0 and (tiles_x > 0.4 or tiles_y > 0.4):
                is_close_mob = True
            elif tiles_x <= 6.0 and tiles_y <= 6.0:
                is_far_mob = True

        can_get_loot = False
        if loot_target:
            dx_l = loot_target[0] - SCREEN_CENTER[0]
            dy_l = loot_target[1] - SCREEN_CENTER[1]
            tiles_x_l = abs(dx_l) / tile_size_px
            tiles_y_l = abs(dy_l) / tile_size_px
            if tiles_x_l <= 7.0 and tiles_y_l <= 7.0:
                can_get_loot = True

        # 4. RUCH i ATAK — ZAWSZE się wykonują (potki/strzały nie blokują!)
        if can_get_loot:
            # KROK 0: Czekaj 0.35s na wyhamowanie postaci z bieżącego kroku przed pomiarem
            print(f"[Loot] Przedmiot dostrzeżony. Wyhamowuję ruch do świeżego pomiaru...")
            time.sleep(0.35)

            # KROK 1: Świeży screenshot TERAZ (postać całkowicie nieruchoma)
            fresh_screen = self.vision.capture_client_area(client_rect, adb_controller=self.controller.adb)
            fresh_loot, fresh_score, fresh_name = self.vision.find_loot_target(fresh_screen, blacklist=self.loot_blacklist)

            if fresh_loot is None:
                print(f"[Loot] Świeży skan na zatrzymanej postaci nie potwierdził lootu (fałszywy alarm). Kontynuuję trasę.")
                self.cached_loot_target = None
                self.cached_loot_score = 0.0
            else:
                # KROK 2: Użyj ŚWIEŻYCH i precyzyjnych współrzędnych ze stabilnego obrazu
                dx = fresh_loot[0] - SCREEN_CENTER[0]
                dy = fresh_loot[1] - SCREEN_CENTER[1]

                total_tiles = max(1, int(round((abs(dx) + abs(dy)) / tile_size_px)))
                walk_time = max(0.6, total_tiles * 0.18 + 0.20)

                item_label = f" [{fresh_name}]" if fresh_name else ""
                print(f"[FSM] LOOT CONFIRMED{item_label} ({fresh_score*100:.0f}%)! Świeże współrzędne: {fresh_loot}, dystans: {total_tiles} kratek (marsz: {walk_time:.2f}s)...")
                self.controller.click_relative(client_rect, fresh_loot[0], fresh_loot[1])
                time.sleep(walk_time)

                print(f"[Loot] Podnoszę przedmioty (pojedyncze kliknięcie ikony '{KEY_LOOT}')...")
                self.controller.press_key(KEY_LOOT)
                time.sleep(0.15)

                # KROK 3: Precyzyjny powrót na punkt wyjściowy trasy sprzed odskoku
                return_x = SCREEN_CENTER[0] - dx
                return_y = SCREEN_CENTER[1] - dy
                print(f"[Loot] Wracam na punkt wyjściowy trasy sprzed odskoku: ({return_x}, {return_y}) (marsz: {walk_time:.2f}s)...")
                self.controller.click_relative(client_rect, return_x, return_y)
                time.sleep(walk_time)

                # Rejestracja w czarnej liście + wyczyszczenie cache i wymuszenie natychmiastowego skanu w następnej klatce
                self.loot_blacklist.append((fresh_loot[0], fresh_loot[1], time.time()))
                self.cached_loot_target = None
                self.cached_loot_score = 0.0
        else:
            # Podążanie po nagranej trasie ROUTE
            if self.waypoints:
                wp = self.waypoints[self.wp_index]
                dx, dy = wp["dx"], wp["dy"]
                tx = SCREEN_CENTER[0] + dx
                ty = SCREEN_CENTER[1] + dy

                # Wykrywanie ostrego zakrętu 90° (zmiana kierunku poziomego na pionowy lub odwrotnie)
                extra_corner_delay = 0.0
                if self.last_wp_vector is not None:
                    prev_dx, prev_dy = self.last_wp_vector
                    if (abs(prev_dx) > 40 and abs(dy) > 40) or (abs(prev_dy) > 40 and abs(dx) > 40):
                        extra_corner_delay = 0.12  # +120ms na stabilizację na rogu zakrętu
                        print(f"[Corner Fix] Wykryto zakręt 90° na wp {self.wp_index + 1} (Wektor {prev_dx},{prev_dy} -> {dx},{dy})! Wyhamowuję o +120ms...")

                self.last_wp_vector = (dx, dy)
                wp_num = self.wp_index + 1
                step_delay = WAYPOINT_STEP_DELAY + extra_corner_delay

                print(f"[FSM] ROUTE [{wp_num}/{len(self.waypoints)}]. Wektor ({dx}, {dy}) -> Cel: ({tx}, {ty}) ({int(step_delay*1000)}ms)")
                self.controller.click_relative(client_rect, tx, ty)

                # Atakowanie jaszczurów po kliknięciu ruchu z buforem 80ms (eliminacja nakładania paczek ADB)
                now = time.time()
                if (is_close_mob or is_far_mob) and (now - self.last_attack_time > 0.20):
                    tag = "[BLISKI MOB <=3]" if is_close_mob else "[MOB W BIEGU]"
                    time.sleep(0.08)
                    print(f"[Combat] Skill '{KEY_SPECIAL_ATTACK}' {tag}")
                    self.controller.press_key(KEY_SPECIAL_ATTACK)
                    self.last_attack_time = now
                    time.sleep(max(0.0, step_delay - 0.08))
                else:
                    time.sleep(step_delay)

                self.wp_index = (self.wp_index + 1) % len(self.waypoints)
            else:
                dx, dy = random.choice([(380, 0), (-380, 0), (0, 380), (0, -380)])
                tx = SCREEN_CENTER[0] + dx
                ty = SCREEN_CENTER[1] + dy
                print(f"[FSM] PATROL (LOSOWY). Offset ({dx}, {dy})")
                self.controller.click_relative(client_rect, tx, ty)
                time.sleep(random.uniform(1.2, 1.8))


# ==============================================================================
# 6. NARZĘDZIA KALIBRACJI I NAGRYWANIA TRAS
# ==============================================================================
def record_route_tool(win_mgr, route_filename="l4_route.json"):
    """
    Bezpośrednie nagrywanie trasy w prawdziwym oknie Nox Player!
    Bez zbędnych okien podglądu OpenCV – po prostu klikasz w grze, a skrypt automatycznie zapisuje Twoje kroki.
    """
    import msvcrt

    os.makedirs(ROUTES_DIR, exist_ok=True)
    if not route_filename.endswith(".json"):
        route_filename += ".json"
    out_path = os.path.join(ROUTES_DIR, route_filename)

    print(f"\n==================================================")
    print(f"  TRYB NAGRYWANIA TRASY DLA NOX PLAYER: {route_filename}")
    print(f"==================================================")
    win_mgr.focus_window()
    win_mgr.resize_and_position(*TARGET_RESOLUTION)
    time.sleep(0.5)

    client_rect = win_mgr.get_client_rect()
    if not client_rect:
        print("[-] Błąd: Nie można pobrać wymiarów okna Nox.")
        return False

    recorded_waypoints = []
    print("[*] --- INSTRUKCJA ---")
    print("[*] 1. Przejdź do okna Nox Playera i KLIKAJ MYSZĄ BEZPOŚREDNIO W GRZE tak jak zwykle grasz.")
    print("[*] 2. Możesz bójkę, zbierać loot i chodzić – skrypt sam wykrywa Twoje kliknięcia w oknie Noxa!")
    print("[*] 3. Gdy przejdziesz całe kółko L4, naciśnij ENTER lub q w tym oknie konsoli (lub Ctrl+C), aby zapisać trasę.\n")

    user32 = ctypes.windll.user32
    was_pressed = False

    try:
        while True:
            # Weryfikacja naciśnięcia klawisza w konsoli (ENTER lub 'q')
            if msvcrt.kbhit():
                key = msvcrt.getch()
                if key in [b'\r', b'\n', b'q', b'Q']:
                    print("[+] Wykryto klawisz zakończenia nagrywania w konsoli.")
                    break

            state = user32.GetAsyncKeyState(0x01)
            is_down = bool(state & 0x8000)

            if is_down and not was_pressed:
                was_pressed = True
                pt = wintypes.POINT()
                user32.GetCursorPos(ctypes.byref(pt))

                rel_x = pt.x - client_rect["left"]
                rel_y = pt.y - client_rect["top"]

                # Sprawdzamy czy kliknięcie nastąpiło wewnątrz obszaru gry w Noxie
                if 0 <= rel_x <= client_rect["width"] and 0 <= rel_y <= client_rect["height"]:
                    # Ignorujemy kliknięcia w Paski UI (Górne menu, Czat na dole, panel umiejętności)
                    if not (rel_y < 100 or rel_y > 800 or rel_x < 150 or (rel_y > 600 and rel_x > 1400)):
                        dx = rel_x - SCREEN_CENTER[0]
                        dy = rel_y - SCREEN_CENTER[1]
                        recorded_waypoints.append({"dx": int(dx), "dy": int(dy)})
                        print(f"[+ Krok {len(recorded_waypoints)}] Zarejestrowano klik w Noxie: rel=({rel_x}, {rel_y}) -> Wektor ({dx}, {dy})")

            elif not is_down:
                was_pressed = False

            time.sleep(0.03)

    except KeyboardInterrupt:
        print("\n[+] Zakończono nagrywanie skrótem Ctrl+C.")

    if not recorded_waypoints:
        print("[-] Nie zarejestrowano żadnych punktów trasy.")
        return False

    data = {
        "route_name": route_filename,
        "waypoints": recorded_waypoints
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\n[+] Pomyślnie zapisano trasę z {len(recorded_waypoints)} waypointami do: {out_path}")
    print(f"[+] Aby uruchomić bota na tej trasie, wpisz: python rucoy_bot.py --route {route_filename}")
    return True


def manual_crop_tool(win_mgr, target_type="lizard"):
    """
    Ręczne wycinanie wariantów szablonu: target_type="lizard" lub target_type="item".
    Uruchamiane z rucoy_bot.py --calibrate (lub --calibrate-lizard / --calibrate-item)
    """
    if target_type == "item":
        target_dir = ITEM_TEMPLATES_DIR
        target_label = "PRZEDMIOTU (LOOT)"
        prefix = "item"
    elif target_type == "spike":
        target_dir = SPIKE_TEMPLATES_DIR
        target_label = "KOLCÓW (PUŁAPKI)"
        prefix = "spike"
    else:
        target_dir = LIZARD_TEMPLATES_DIR
        target_label = "JASZCZURA"
        prefix = "lizard"

    print(f"\n--- Tryb ręcznej kalibracji szablonu {target_label} ---")
    win_mgr.focus_window()
    win_mgr.resize_and_position(*TARGET_RESOLUTION)
    time.sleep(1.0)

    client_rect = win_mgr.get_client_rect()
    if not client_rect:
        print("[-] Błąd: Nie można pobrać wymiarów okna Nox.")
        return False

    print(f"[*] Ustaw widok tak, aby {target_label} był widoczny na mapie.")
    print("[*] Zrzut ekranu za 3 sekundy...")
    for i in range(3, 0, -1):
        print(f"{i}...")
        time.sleep(1.0)

    sct = mss.MSS()
    monitor = {
        "top": client_rect["top"],
        "left": client_rect["left"],
        "width": client_rect["width"],
        "height": client_rect["height"]
    }
    screen = np.array(sct.grab(monitor))[:, :, :3]

    preview_path = os.path.join(BASE_DIR, "preview_alignment.png")
    cv2.imwrite(preview_path, screen)
    print(f"[+] Zapisano zrzut: {preview_path}")

    print(f"[*] W oknie podglądu zaznacz myszką obszar ({target_label}), potem ENTER.")
    roi = cv2.selectROI(f"Zaznacz {target_label} (ENTER = zatwierdz, ESC = anuluj)", screen, showCrosshair=True)
    cv2.destroyAllWindows()

    x, y, w, h = roi
    if w == 0 or h == 0:
        print("[-] Anulowano - nie zaznaczono obszaru.")
        return False

    crop = screen[y:y + h, x:x + w]

    os.makedirs(target_dir, exist_ok=True)
    existing_files = [f for f in os.listdir(target_dir) if f.startswith(f"{prefix}_") and f.endswith(".png")]
    max_idx = 0
    for fname in existing_files:
        try:
            num = int(fname.replace(f"{prefix}_", "").replace(".png", ""))
            if num > max_idx:
                max_idx = num
        except ValueError:
            pass

    out_path = os.path.join(target_dir, f"{prefix}_{max_idx + 1}.png")
    cv2.imwrite(out_path, crop)

    print(f"[+] Zapisano wariant szablonu {target_label}: {out_path}")
    print("[*] Powtórz ten tryb kilka razy w różnych miejscach mapy (trawa/piasek/woda),")
    print("[*] żeby zebrać kilka wariantów tła pod wzorcem.")
    return True


# ==============================================================================
# GŁÓWNY PUNKT WEJŚCIA
# ==============================================================================
def main():
    print("==================================================")
    print("        Rucoy Online Standalone Archer Bot        ")
    print("==================================================")

    win_mgr = WindowManager(WINDOW_TITLE_SUBSTRING)
    if not win_mgr.find_window():
        print("[-] Błąd: Nie znaleziono emulatora Nox Player! Upewnij się, że jest włączony.")
        sys.exit(1)

    print(f"[Init] Znaleziono okno emulatora: '{win_mgr.window_title}'")
    win_mgr.focus_window()
    win_mgr.resize_and_position(*TARGET_RESOLUTION)

    # Sprawdzanie argumentów dla nagrywania tras
    for i, arg in enumerate(sys.argv):
        if arg.startswith("--record-route"):
            rec_filename = "l4_route.json"
            if "=" in arg:
                rec_filename = arg.split("=")[1]
            elif i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith("-"):
                rec_filename = sys.argv[i + 1]
            record_route_tool(win_mgr, rec_filename)
            sys.exit(0)

    # Tryby kalibracji:
    if "--calibrate-item" in sys.argv:
        manual_crop_tool(win_mgr, target_type="item")
        sys.exit(0)
    elif "--calibrate-spike" in sys.argv or "--calibrate-spikes" in sys.argv:
        manual_crop_tool(win_mgr, target_type="spike")
        sys.exit(0)
    elif "--calibrate" in sys.argv or "--calibrate-lizard" in sys.argv:
        manual_crop_tool(win_mgr, target_type="lizard")
        sys.exit(0)

    # Sprawdzanie argumentu wyboru trasy
    selected_route = None
    for i, arg in enumerate(sys.argv):
        if arg.startswith("--route="):
            selected_route = arg.split("=")[1]
        elif arg == "--route" and i + 1 < len(sys.argv):
            selected_route = sys.argv[i + 1]

    vision = GameVision()

    if not vision.templates:
        print("[*] Ostrzeżenie: Brak wariantów szablonu jaszczura.")
        print("[*] Możesz dodać je komendą: python rucoy_bot.py --calibrate")

    if not vision.item_templates:
        print("[*] Informacja: Brak wariantów szablonów lootu w templates/item_variants.")
        print("[*] Możesz dodać przedmioty komendą: python rucoy_bot.py --calibrate-item")

    if not vision.templates and not vision.item_templates:
        print("[-] Brak jakichkolwiek szablonów! Uruchom najpierw kalibrację.")
        sys.exit(1)

    # Inicjalizacja sterownika ADB w tle (chyba że podano flagę --no-adb)
    use_adb = "--no-adb" not in sys.argv
    adb_ctrl = ADBController()
    if use_adb:
        adb_ctrl.connect()

    controller = GameController(adb_controller=adb_ctrl if use_adb else None)
    bot = RucoyBot(win_mgr, vision, controller, route_filename=selected_route)

    print("\n[+] Wszystko gotowe! Uruchamiam pętlę bota w TLE za 3 sekundy...")
    if adb_ctrl.connected and use_adb:
        print("[+] TRYB W TLE AKTYWNY (ADB): Możesz zminimalizować/przykryć Noxa i swobodnie korzystać z komputera.")
    else:
        print("[!] TRYB MYSZY SYSTEMOWEJ (ADB wyłączone): Bot przejmuje myszkę.")

    for i in range(3, 0, -1):
        print(f"{i}...")
        time.sleep(1.0)

    print("[+] Pętla aktywna. Ctrl+C aby zatrzymać.")
    if DEBUG_MODE:
        print(f"[+] Debug: podgląd dopasowania zapisywany na bieżąco w {DEBUG_DIR}/last_match.png i last_loot_match.png")

    try:
        while True:
            bot.run_step()
            time.sleep(0.01)
    except KeyboardInterrupt:
        print("\n[+] Bot został zatrzymany przez użytkownika (Ctrl+C). Wyłączam.")
        sys.exit(0)


if __name__ == "__main__":
    main()