# Context & Status: Rucoy Online Standalone Archer Bot

Pełna dokumentacja stanu projektu, architektury, parametrów operacyjnych i komend do natychmiastowej kontynuacji pracy od 0.

---

## 1. Architektura i Pakiety Projektu

Projekt opiera się na samodzielnym skrypcie w języku Python ([rucoy_bot.py](file:///c:/VS/rucoy/rucoy_bot.py)), który zarządza całą automatyzacją Rucoy Online na emulatorze Nox Player (rozdzielczość okna 1600x900).

### Wykorzystywane biblioteki:
* `win32gui`, `win32process`, `win32api` – bezpośrednie sterowanie oknem Nox Player bez przenoszenia kursorów użytkownika.
* `mss` – szybkie zrzuty ekranu pamięci podręcznej RAM.
* `opencv-python (cv2)` – detekcja wzorców, czytanie pasków zdrowia/many oraz lootu (`cv2.matchTemplate`).
* `numpy` – numeryczne przeliczanie macierzy pikseli i skalowanie.

---

## 2. Gałęzie Git (Branching Strategy)

* **`master`:** Stabilna wersja bazowa z tradycyjnym sekwencyjnym podchodzeniem.
* **`FAST`:** Zoptymalizowana gałąź dla Nox Player.
* **`bluestack` (AKTYWNA GAŁĄŹ):** Adaptacja bota dla emulatora BlueStacks / HD-Player:
  - Automatyczne wyszukiwanie i dopasowywanie okna `BlueStacks` / `HD-Player`.
  - Stałe tempo 200 ms (`step_delay = 0.20`) na każdy krok trasy.
  - Płynny marsz non-stop bez zatrzymywania się (nieblokująca walka i leczenie).
  - Pre-downscaling wizji o 50% (`VISION_DOWNSCALE = 0.5`) dla 4-krotnego przyspieszenia detekcji.
  - Throttling czasowy skanowania: Jaszczury (0.8 s), Loot (1.3 s).

---

## 3. Struktura Katalogów i Szablonów Graficznych

```
c:/VS/rucoy/
├── rucoy_bot.py                # Główny skrypt bota (FSM, Vision, Controller, CLI)
├── CONTEXT.md                  # Pełny dokument kontekstowy projektu
├── .gitignore                  # Ignorowane pliki tymczasowe i pamięć podręczna Pythona
├── routes/
│   └── l4_route.json           # Ścieżka patrolowa L4 (248 precyzyjnych waypointów)
└── templates/
    ├── lizard_variants/        # Warianty graficzne jaszczurów
    └── item_variants/          # Warianty leżącego lootu
```

---

## 4. Parametry Konfiguracji i Progi Działania

Wszystkie parametry sterujące znajdują się na początku pliku [rucoy_bot.py](file:///c:/VS/rucoy/rucoy_bot.py#L20-L60):

| Parametr | Wartość | Opis |
| :--- | :--- | :--- |
| **Interpreter Python** | `C:/Users/inetk/AppData/Local/Microsoft/WindowsApps/python3.12.exe` | Pełna ścieżka do Pythona 3.12 w systemie Windows. |
| **Emulator** | Nox Player (1600x900) | Tytuł okna: `'Nox'`. Okno automatycznie pozycjonowane przez `WindowManager`. |
| `MATCH_THRESHOLD` | `0.55` (55%) | Próg czułości OpenCV dla jaszczurów. |
| `ITEM_MATCH_THRESHOLD` | `0.50` (50%) | Próg czułości wykrywania lootu. |
| `VISION_DOWNSCALE` | `0.5` (50%) | Przeskalowanie obrazu ekranu i szablonów do 50% (4x szybsza detekcja). |
| `WAYPOINT_STEP_DELAY` | `0.20` s (200 ms) | Stałe tempo wykonywania pojedynczych kroków trasowania w trybie FAST. |
| `HP_POTION_THRESHOLD` | `0.75` (75%) | Poniżej 3/4 HP używana jest mikstura leczenia (Klawisz: `'3'`). Pasek odczytywany na $X=400, Y=18..38$. |
| `MANA_POTION_THRESHOLD` | `0.50` (50%) | Poniżej 1/2 Mana używana jest mikstura many (Klawisz: `'1'`). Pasek odczytywany na $X=400, Y=45..54$. |
| `POTION_COOLDOWN` | `1.0` s | Czas oczekiwania na uleczenie postaci przed kolejnym sprawdzaniem paska. |
| `KEY_SPECIAL_ATTACK` | `'w'` | Klawisz ataku specjalnego Łucznika. |
| `KEY_LOOT` | `'h'` | Klawisz zbierania przedmiotów w emulatorze Nox. |

---

## 5. Zbudowane Tryby i Narzędzia CLI

Wszystkie komendy uruchamiane są z poziomu konsoli PowerShell za pomocą pełnej ścieżki Pythona:

### 1. Uruchomienie bota na trasie L4:
```bash
& C:/Users/inetk/AppData/Local/Microsoft/WindowsApps/python3.12.exe rucoy_bot.py --route l4_route.json
```

### 2. Nagrywanie nowej trasy (Direct Nox API Hook):
```bash
& C:/Users/inetk/AppData/Local/Microsoft/WindowsApps/python3.12.exe rucoy_bot.py --record-route l4_route.json
```
*Kliknięcia są rejestrowane bezpośrednio w Noxie. Zakończenie: naciśnij ENTER lub `q` w konsoli.*

### 3. Kalibracja i dodawanie szablonów jaszczurów:
```bash
& C:/Users/inetk/AppData/Local/Microsoft/WindowsApps/python3.12.exe rucoy_bot.py --calibrate-lizard
```

### 4. Kalibracja i dodawanie szablonów podłogowego lootu:
```bash
& C:/Users/inetk/AppData/Local/Microsoft/WindowsApps/python3.12.exe rucoy_bot.py --calibrate-item
```

---

## 6. Schemat Działania Pętli Głównej (Branch `FAST`)

```mermaid
graph TD
    A[Zrzut ekranu Nox RAM] --> B[Sprawdzenie Pasków HP / Mana -> Użycie Potki bez opóźnień]
    B --> C{Skanowanie Wizji z Throttlingiem}
    C -- Co 0.8s --> D[Skan Jaszczurów 50% Downscale]
    C -- Co 1.3s --> E[Skan Lootu 50% Downscale]
    D & E --> F{Czy mob w zasięgu?}
    F -- Tak --> G[Wyślij Skill 'w' - Nie blokuje ruchu!]
    F -- Nie / Po wysłaniu skilla --> H{Czy pod nogami jest Loot?}
    H -- Tak --> I[Podejdź do lootu -> Klawisz 'h' -> Powrót na trasę]
    H -- Nie --> J[Pobierz kolejny Waypoint z trasy]
    J --> K[Wykonaj pojedynczy krok trasy - 200 ms]
```

---

## 7. Historia Zmian i Osiągnięć (Dziennik Prac)

1. **Optymalizacja wydajności I/O (`DEBUG_MODE = False`):** Usunięto zapisywanie plików obrazów z pamięci dyskowej na każdej klatce. Czas analizy skrócił się z $300-500\text{ms}$ do $<10\text{ms}$.
2. **Rozwiązanie problemu tekstalnego na paskach HP/Mana:** Przesunięto badanie pikseli z zakłóconego tekstem obszaru środkowego na czysty punkt $X=400$, uniezależniając bota od napisu `4,279/4,285`.
3. **Pojedyncza Skala i 50% Downscaling Wizji (`VISION_DOWNSCALE = 0.5`):** Przeskalowanie zrzutu ekranu i szablonów o 50% dało 4-krotny skok wydajności skanowania (z ~300ms do ~60-90ms).
4. **Throttling skanowania wizualnego:** Odseparowanie skanowania jaszczurów (0.8s) i lootu (1.3s) z buforowaniem wyników w pamięci RAM. Dzięki temu 80% klatek wykonuje się natychmiastowo w reżimie 200 ms.
5. **Nieblokująca walka i poruszanie się:** Skille oraz potki są wysyłane asynchronicznie (fire-and-forget), a bota nie zatrzymują już animacje ani sztuczne pauzy `time.sleep` w trakcie strzelania.
6. **Usunięcie opóźnień sterownika:** Usunięto `time.sleep` z `click_relative` oraz zbędne wywołania `focus_window()` na każdej klatce.
7. **Usunięcie SAFE Mode & Kolców:** Na prośbę użytkownika całkowicie wycięto logikę kolców i trybu SAFE dla uproszczenia i przyspieszenia poruszania się.
8. **Usunięcie systemu Anti-Stuck:** Wyeliminowano algorytm wykrywania zacięć (`get_screen_diff`), zapobiegając fałszywym odskokom awaryjnym i zniekształcaniu trasy.
