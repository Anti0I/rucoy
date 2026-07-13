import os
import sys
import time
import random
import json
import ctypes
from ctypes import wintypes
import cv2
import numpy as np
import mss
import pydirectinput

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
MOVEMENT_SPEED_FACTOR = 0.10  # Czas w sekundach na 1 kratkę (płynny marsz bez pauz)
MIN_STEP_DELAY = 0.05          # Minimalne opóźnienie między krokami (brak przestojów)

# Limity i ścieżki
STUCK_TIME_LIMIT = 3.0  # Czas (w sekundach) braku ruchu przed odblokowaniem
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
LIZARD_TEMPLATES_DIR = os.path.join(TEMPLATES_DIR, "lizard_variants")
ITEM_TEMPLATES_DIR = os.path.join(TEMPLATES_DIR, "item_variants")
ROUTES_DIR = os.path.join(BASE_DIR, "routes")
DEBUG_DIR = os.path.join(BASE_DIR, "debug")

# --- Ustawienia detekcji i smyczy bojowej ---
MATCH_THRESHOLD = 0.60          # Próg wykrywania jaszczurów (60% zgodności)
ITEM_MATCH_THRESHOLD = 0.65     # Próg wykrywania leżącego lootu
MAX_ATTACK_DIST_PX = 270        # Maksymalny dystans do moba (blizej niz 5 kratek, ok. 270px)
LEASH_MAX_TILES_X = 6           # Maksymalne odchylenie w osi X od kotwicy trasy (6 kratek)
LEASH_MAX_TILES_Y = 4           # Maksymalne odchylenie w osi Y od kotwicy trasy (4 kratki)
SCALE_RANGE = np.linspace(0.92, 1.08, 3)  # Zoptymalizowany zakres skalowania (3 skale dla błyskawicznego wykrywania)
DEBUG_MODE = False              # Wyłączony zapis na dysk dla maksymalnej płynności i braku zacinek

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
        if not windows:
            return False
        self.hwnd, self.window_title = windows[0]
        return True

    def focus_window(self):
        if not self.hwnd:
            return False
        if user32.IsIconic(self.hwnd):
            user32.ShowWindow(self.hwnd, 9)  # SW_RESTORE
            time.sleep(0.2)
        user32.SetForegroundWindow(self.hwnd)
        time.sleep(0.2)
        return True

    def get_client_rect(self):
        if not self.hwnd:
            return None
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
        self.templates = []       # lista wariantów szablonu jaszczura (grayscale)
        self.item_templates = []  # lista wariantów szablonu lootu/przedmiotów (grayscale)
        self.load_templates()
        self.load_item_templates()
        if DEBUG_MODE:
            os.makedirs(DEBUG_DIR, exist_ok=True)

    def load_templates(self):
        self.templates = []
        if not os.path.isdir(LIZARD_TEMPLATES_DIR):
            print("[Vision] Brak katalogu z wariantami szablonu jaszczura.")
            return False

        for fname in sorted(os.listdir(LIZARD_TEMPLATES_DIR)):
            path = os.path.join(LIZARD_TEMPLATES_DIR, fname)
            tpl = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            if tpl is not None and tpl.size > 0:
                self.templates.append(tpl)

        if self.templates:
            print(f"[Vision] Załadowano {len(self.templates)} wariantów szablonu jaszczura.")
            return True
        print("[Vision] Nie znaleziono żadnych wariantów szablonu jaszczura.")
        return False

    def load_item_templates(self):
        self.item_templates = []
        if not os.path.isdir(ITEM_TEMPLATES_DIR):
            os.makedirs(ITEM_TEMPLATES_DIR, exist_ok=True)
            print("[Vision] Utworzono pusty katalog z wariantami szablonów lootu.")
            return False

        for fname in sorted(os.listdir(ITEM_TEMPLATES_DIR)):
            path = os.path.join(ITEM_TEMPLATES_DIR, fname)
            tpl = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            if tpl is not None and tpl.size > 0:
                self.item_templates.append(tpl)

        if self.item_templates:
            print(f"[Vision] Załadowano {len(self.item_templates)} wariantów szablonu lootu.")
            return True
        print("[Vision] Brak wariantów szablonów lootu w templates/item_variants.")
        return False

    def capture_client_area(self, client_rect):
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
        if not self.templates:
            return None, 0.0

        img_gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        img_gray = self._mask_ui(img_gray)

        best_score = 0.0
        closest_target = None
        closest_dist = float('inf')
        best_size = None
        best_loc = None

        center_x, center_y = SCREEN_CENTER

        for template in self.templates:
            for scale in SCALE_RANGE:
                resized = cv2.resize(template, None, fx=scale, fy=scale)
                th, tw = resized.shape[:2]
                if th >= img_gray.shape[0] or tw >= img_gray.shape[1]:
                    continue
                
                result = cv2.matchTemplate(img_gray, resized, cv2.TM_CCOEFF_NORMED)
                locs = np.where(result >= threshold)
                
                for pt in zip(*locs[::-1]):
                    score = result[pt[1], pt[0]]
                    if score > best_score:
                        best_score = score
                    
                    cx = pt[0] + tw // 2
                    cy = pt[1] + th // 2
                    dist = np.sqrt((cx - center_x) ** 2 + (cy - center_y) ** 2)
                    
                    if dist < closest_dist:
                        closest_dist = dist
                        closest_target = (cx, cy + th + 25)
                        best_loc = pt
                        best_size = (th, tw)

        if DEBUG_MODE and best_loc is not None:
            self._save_debug_frame(img_bgr, best_loc, best_size, best_score, threshold)

        return closest_target, best_score

    def find_loot_target(self, img_bgr, threshold=ITEM_MATCH_THRESHOLD):
        """
        Wyszukuje przedmioty leżące na podłodze. Zwraca najbliższy loot (pozycja środka przedmiotu)
        oraz najwyższy wynik dopasowania.
        """
        if not self.item_templates:
            return None, 0.0

        img_gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        img_gray = self._mask_ui(img_gray)

        best_score = 0.0
        closest_target = None
        closest_dist = float('inf')
        best_size = None
        best_loc = None

        center_x, center_y = SCREEN_CENTER

        for template in self.item_templates:
            for scale in SCALE_RANGE:
                resized = cv2.resize(template, None, fx=scale, fy=scale)
                th, tw = resized.shape[:2]
                if th >= img_gray.shape[0] or tw >= img_gray.shape[1]:
                    continue
                
                result = cv2.matchTemplate(img_gray, resized, cv2.TM_CCOEFF_NORMED)
                locs = np.where(result >= threshold)
                
                for pt in zip(*locs[::-1]):
                    score = result[pt[1], pt[0]]
                    if score > best_score:
                        best_score = score
                    
                    cx = pt[0] + tw // 2
                    cy = pt[1] + th // 2
                    dist = np.sqrt((cx - center_x) ** 2 + (cy - center_y) ** 2)
                    
                    if dist < closest_dist:
                        closest_dist = dist
                        closest_target = (cx, cy)
                        best_loc = pt
                        best_size = (th, tw)

        if DEBUG_MODE and best_loc is not None:
            self._save_loot_debug_frame(img_bgr, best_loc, best_size, best_score, threshold)

        return closest_target, best_score

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
    def click_relative(self, client_rect, relative_x, relative_y, jitter=5):
        abs_x = client_rect["left"] + relative_x + random.randint(-jitter, jitter)
        abs_y = client_rect["top"] + relative_y + random.randint(-jitter, jitter)
        pydirectinput.moveTo(abs_x, abs_y)
        time.sleep(random.uniform(0.02, 0.05))
        pydirectinput.click()

    def press_key(self, key):
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
        self.last_screen = None
        self.last_movement_time = time.time()
        self.last_attack_time = 0
        self.last_hp_pot_time = 0
        self.last_mana_pot_time = 0

        self.anchor_offset_x = 0.0  # Sumaryczne przesunięcie X w kratkach od kotwicy trasy
        self.anchor_offset_y = 0.0  # Sumaryczne przesunięcie Y w kratkach od kotwicy trasy

        self.waypoints = []
        self.wp_index = 0
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

    def get_screen_diff(self, current_screen):
        if self.last_screen is None:
            self.last_screen = current_screen
            return 1.0

        gray_curr = cv2.cvtColor(current_screen, cv2.COLOR_BGR2GRAY)
        gray_last = cv2.cvtColor(self.last_screen, cv2.COLOR_BGR2GRAY)

        if gray_curr.shape != gray_last.shape:
            self.last_screen = current_screen
            return 1.0

        diff = cv2.absdiff(gray_curr, gray_last)
        non_zero = np.count_nonzero(diff > 25)
        self.last_screen = current_screen
        return non_zero / (current_screen.shape[0] * current_screen.shape[1])

    def run_step(self):
        self.window_mgr.focus_window()
        client_rect = self.window_mgr.get_client_rect()
        if not client_rect:
            print("[Bot] Błąd: Brak dostępu do Nox Client.")
            return

        screen = self.vision.capture_client_area(client_rect)

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

        # 2. Anti-Stuck Check
        screen_diff = self.get_screen_diff(screen)
        if screen_diff > 0.01:
            self.last_movement_time = time.time()
        elif time.time() - self.last_movement_time > STUCK_TIME_LIMIT:
            print("[Anti-Stuck] Postać utknęła. Wykonuję skok awaryjny...")
            rx = random.choice([-150, 150])
            ry = random.choice([-150, 150])
            self.controller.click_relative(client_rect, SCREEN_CENTER[0] + rx, SCREEN_CENTER[1] + ry)
            self.last_movement_time = time.time()
            time.sleep(1.0)
            self.anchor_offset_x = 0.0
            self.anchor_offset_y = 0.0
            self.state = BotState.PATROL
            return

        # 3. Skanowanie potworów oraz podłogi (LOOT)
        mob_target, mob_score = self.vision.find_lizard_target(screen)
        loot_target, loot_score = self.vision.find_loot_target(screen)

        if DEBUG_MODE:
            if mob_target:
                print(f"[Vision][DEBUG] MOB score={mob_score:.3f} target={mob_target}")
            if loot_target:
                print(f"[Vision][DEBUG] LOOT score={loot_score:.3f} target={loot_target}")

        # Wyliczenie dystansu kafelkowego i klasyfikacja bliskich/dalekich mobków (Branch: FAST)
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
            if tiles_x_l <= 6.0 and tiles_y_l <= 6.0:
                can_get_loot = True

        # 4. Atakowanie jaszczurów (Strzelanie ze skilla 'w')
        now = time.time()
        if is_close_mob or is_far_mob:
            if now - self.last_attack_time > 0.20:
                tag = "[BLISKI MOB <=3 - STAJĘ]" if is_close_mob else "[MOB W BIEGU]"
                print(f"[FAST Combat] Strzelam ze skilla (Klawisz: {KEY_SPECIAL_ATTACK}) {tag}")
                self.controller.press_key(KEY_SPECIAL_ATTACK)
                self.last_attack_time = now

            # ZATRZYMANIE RUCHU WYŁĄCZNIE DLA MOBÓW BARDZO BLISKO (<= 3 KRATKI)!
            if is_close_mob:
                time.sleep(0.12)
                return  # Wstrzymujemy marsz dopóki bliski mob w zasięgu 3 kratek nie zostanie zabity!
            
        # 5. Priorytetyzacja ruchu (Wykonywana dopóki w zasięgu nie ma mobków)
        if can_get_loot:
            dx = loot_target[0] - SCREEN_CENTER[0]
            dy = loot_target[1] - SCREEN_CENTER[1]

            total_tiles = max(1, int(round((abs(dx) + abs(dy)) / tile_size_px)))
            walk_delay = max(MIN_STEP_DELAY, total_tiles * MOVEMENT_SPEED_FACTOR)

            print(f"[FSM] LOOT DETECTED! Dystans: {total_tiles} kratek (|dx|={abs(dx)}, |dy|={abs(dy)}). Podchodzę na pozycję {loot_target}...")
            self.controller.click_relative(client_rect, loot_target[0], loot_target[1])
            time.sleep(walk_delay)

            print(f"[FSM] Zbieram loot klawiszem '{KEY_LOOT}'...")
            self.controller.press_key(KEY_LOOT)
            time.sleep(0.05)
            self.controller.press_key(KEY_LOOT)
            time.sleep(0.05)

            # Powrót do miejsca wyjściowego
            return_x = SCREEN_CENTER[0] - dx
            return_y = SCREEN_CENTER[1] - dy
            print(f"[FSM] Powracam na pozycję wyjściową sprzed zebrania lootu: ({return_x}, {return_y})...")
            self.controller.click_relative(client_rect, return_x, return_y)
            time.sleep(walk_delay)

        else:
            # Podążanie po nagranej trasie ROUTE (Pojedyncze czyste kliknięcie na wolne pole!)
            if self.waypoints:
                wp = self.waypoints[self.wp_index]
                dx, dy = wp["dx"], wp["dy"]
                tx = SCREEN_CENTER[0] + dx
                ty = SCREEN_CENTER[1] + dy

                total_tiles = max(1, int(round((abs(dx) + abs(dy)) / tile_size_px)))
                step_delay = max(MIN_STEP_DELAY, total_tiles * MOVEMENT_SPEED_FACTOR)

                print(f"[FSM] ROUTE [{self.wp_index + 1}/{len(self.waypoints)}]. Krok ({dx}, {dy}) -> Odległość: {total_tiles} kratek")
                self.controller.click_relative(client_rect, tx, ty)
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
    target_dir = ITEM_TEMPLATES_DIR if target_type == "item" else LIZARD_TEMPLATES_DIR
    target_label = "PRZEDMIOTU (LOOT)" if target_type == "item" else "JASZCZURA"

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
    prefix = "item" if target_type == "item" else "lizard"
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

    controller = GameController()
    bot = RucoyBot(win_mgr, vision, controller, route_filename=selected_route)

    print("\n[+] Wszystko gotowe! Uruchamiam pętlę bota za 5 sekund...")
    print("[+] Przełącz teraz na okno Nox Playera.")
    for i in range(5, 0, -1):
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
        print("\n[+] Bot został zatrzymany przez użytkownika.")


if __name__ == "__main__":
    main()