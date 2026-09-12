# P3 Thermal Studio

Modułowa aplikacja desktopowa do kamer termowizyjnych **P3 (256 × 192)** i **P1 (160 × 120)**. Nowy viewer zastępuje demonstracyjne okno OpenCV interfejsem Tk/ttk: panel ustawień, niezależny od USB interfejs, inspekcja pikseli i bezstratny eksport.

## Uruchomienie

```bash
pip install -e .
p3-viewer                 # P3
p3-viewer --model p1      # P1
p3-viewer --demo          # syntetyczne dane, bez kamery
python p3_viewer.py --demo
```

Wymagany Python ≥ 3.10, NumPy, OpenCV, PyUSB i **Tk 8.6+**. Tk jest składnikiem instalacji Pythona, nie pakietem pip. W Debianie/Ubuntu zapewnia go `python3-tk`, w Arch Linux `tk`; środowisko wirtualne musi korzystać z Pythona z obsługą Tk. Sesja graficzna jest wymagana; aplikacja nie korzysta z backendu Qt biblioteki OpenCV. Pozostałe zależności historyczne pozostają w projekcie na potrzeby eksperymentów.

### Dostęp USB

Linux: utwórz `/etc/udev/rules.d/99-p3-ir.rules`:

```udev
SUBSYSTEM=="usb", ATTR{idVendor}=="3474", ATTR{idProduct}=="45c2", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="3474", ATTR{idProduct}=="45a2", TAG+="uaccess"
```

Przeładuj reguły (`sudo udevadm control --reload-rules`), odłącz i podłącz kamerę. Reguły udostępniają urządzenie aktywnej lokalnej sesji. Windows wymaga backendu libusb/WinUSB; wcześniejsza konfiguracja używała Zadig dla urządzenia o VID `3474` i PID `45C2` lub `45A2`. Obsługa sprzętu na Windows/macOS wymaga osobnego sprawdzenia.

## Temperatura konkretnego piksela

Pod obrazem, **po lewej**, są dwa oddzielne wiersze: powiększenie oraz `Pixel (x, y) / temperatura °C / RAW`. Współrzędne są zerowane od lewego górnego rogu oryginalnego sensora i pozostają poprawne po obrocie, odbiciu oraz przesunięciu obrazu.

Dane kamery mają postać `uint16`, a konwersja wynosi:

```text
°C = RAW / 64 − 273.15
krok kodowania = 0.015625 K
przykład: RAW 19000 → 23.725000 °C
```

Odczyty mają **6 miejsc po przecinku**, co zachowuje pełną rozdzielczość tego kodowania. To precyzja zapisu danych, nie deklaracja dokładności pomiarowej sensora. Pomiary nie są wyprowadzane z RGB, interpolacji ani klatek po filtracji. Pokazywana jest temperatura pozorna dostarczana przez kamerę, bez dodatkowej programowej korekcji emisyjności.

**Ctrl+X** ustawia powiększenie 12800%, z siatką i temperaturą każdego widocznego piksela. Siatka zaczyna się przy 2800%, pełne etykiety przy 9600%, maksimum to 25600%. Przy mniejszej komórce pełny odczyt pozostaje pod obrazem. Wbudowany inspektor RGB OpenCV został całkowicie usunięty.

## Funkcje

| Element | Działanie |
| --- | --- |
| Temperature | Obraz z bieżącej, nieprzetworzonej temperatury |
| Filtered temperature | Wygładzanie czasowe EMA wyłącznie obrazu; regulowany udział nowej klatki |
| Raw counts | Wizualizacja 16-bitowych kodów, zakres w jednostkach RAW |
| Factory brightness | 8-bitowy obraz jasności z kamery; kolory nie oznaczają liniowej skali °C |
| Palette | Inferno, Magma, Viridis, Turbo, Rainbow, White hot, Black hot |
| Auto percentile | Percentyle 1–99 z płynną adaptacją zakresu |
| Fixed | Własny zakres °C; wymaga Apply range i maksimum większego od minimum |
| Enhance contrast / detail | CLAHE i wyostrzanie wizualizacji; wyłącza ilościową legendę |
| Freeze / Resume | Zatrzymuje wyświetlaną klatkę; kamera nadal jest odczytywana |
| Shutter / NUC | Kalibracja migawką wykonywana przez wątek USB |
| Sensor gain | HIGH; LOW dostępny eksperymentalnie, z wykrytym przesunięciem temperatur na firmware 00.00.02.18; AUTO nie jest zaimplementowane |
| Reconnect | Natychmiastowa próba połączenia; bez kamery aplikacja ponawia próby automatycznie co 2 s |
| Save data | NPZ z oryginalnym RAW, jasnością i metadanymi |
| Save image | PNG w rozdzielczości sensora, z aktualną paletą i orientacją |

Min/max i średnia dotyczą całej oryginalnej klatki, również podczas zoomu. W trybie demo wszystkie dane są syntetyczne, a sterowanie sensorem jest niedostępne. **Do pomiarów używaj HIGH**: test fizycznej P3 wykazał w LOW odczyty około −34°C zamiast zakresu około 20–25°C tej samej sceny. NUC nie usunęło różnicy; nie dodano arbitralnej korekcji temperatur.

### Nawigacja

- Kółko myszy lub `+` / `−`: powiększanie; kółko zachowuje punkt pod kursorem.
- Przeciąganie lewym przyciskiem: przesunięcie obrazu.
- Dwuklik lub `Escape`: dopasowanie obrazu do okna.
- `Ctrl+X`: inspekcja temperatur pikseli.
- `Ctrl+S`: zapis danych termicznych.
- Obrót i odbicie: przyciski w panelu bocznym.
- Zamknięcie przez X: zatrzymanie wątku, strumienia i zwolnienie USB; działa także po odłączeniu kamery.

Po odłączeniu kamery **okno pozostaje otwarte**, a obraz zastępuje komunikat o braku kamery. Aplikacja czeka na ponowne podłączenie i automatycznie wznawia podgląd po inicjalizacji. Działa to również przy uruchomieniu bez kamery. Wznowienie wyłącza Freeze; ustawienia obrazu pozostają zachowane. X zamyka aplikację także podczas oczekiwania.

Stare jednoliterowe skróty demonstracyjnego viewera zastępują widoczne kontrolki. Historyczne opcje lock-in nie są przyjmowane przez nowe CLI.

## Dokumentacja i rozwój

- [Architektura, kontrakty modułów i rozbudowa](docs/ARCHITECTURE.md)
- [Dane, eksport, diagnostyka i procedura testów](docs/OPERATIONS.md)
- [Protokół USB](P3_PROTOCOL.md)
- [Historyczny eksperyment lock-in](LOCK-IN.md) — zachowany w `lockin.py`, bez integracji z nowym GUI i bez nowych testów sprzętowych.
- [Archiwum README i zgłoszonych problemów](docs/LEGACY_DEMO.md)

```bash
pip install -e '.[dev]'
python -m pytest -q
# Opcjonalny test rzeczywistego okna, w sesji graficznej:
P3_GUI_TEST=1 python -m pytest tests/gui_test.py -q
```

Testy nie są częścią uruchamiania aplikacji. `p3_camera_test.py` sprawdza bibliotekę; `p3_viewer_test.py` sprawdza nową implementację, a `tests/gui_test.py` jest opcjonalnym testem desktopu.

Projekt niezależny od producenta. Szczegóły protokołu pochodzą z analizy komunikacji USB i eksperymentów. Licencja Apache 2.0. Oryginalny projekt: Joshua V. Dillon; podziękowania autorom protokołu, wcześniejszych rozszerzeń i zdjęć zachowane w dokumentacji historycznej.
