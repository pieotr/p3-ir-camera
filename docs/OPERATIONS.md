# Obsługa, dane i weryfikacja

## Typowy pomiar

1. Uruchom `p3-viewer --model p3` lub `--model p1`. Inicjalizacja USB trwa kilka sekund; okno w tym czasie odpowiada na zdarzenia.
2. Wybierz Temperature i paletę. Dla porównywania scen ustaw Fixed oraz wspólne granice °C, a następnie Apply range.
3. Najedź na punkt: wiersz pod obrazem pokazuje współrzędne oryginalnego sensora, sześciocyfrowy odczyt °C i liczbę RAW.
4. Kółkiem przybliż interesujący fragment; Ctrl+X uruchamia inspekcję pikseli. Przeciąganie przesuwa widok. Escape przywraca dopasowanie.
5. Freeze pozwala analizować i zapisać konkretną klatkę. Save data zachowuje wartości sensora; Save image eksportuje sam obraz z paletą.
6. Zamknij przez X i poczekaj na zakończenie cleanup, szczególnie podczas inicjalizacji lub kalibracji.

Nie ma programowego uśredniania odczytu kursora. W trybie Filtered temperature obraz może reagować wolniej niż odczyt z bieżącego RAW — to zamierzona separacja wizualizacji i pomiarów. Średnia całej klatki jest statystyką obliczoną, nie dodatkowym pomiarem sprzętowym.

## Format NPZ

Archiwum można czytać bez aplikacji, bez picklowania obiektów:

```python
import json
import numpy as np

with np.load("capture.npz", allow_pickle=False) as capture:
    raw = capture["raw"]                 # H×W uint16, orientacja sensora
    brightness = capture["brightness"]   # H×W uint8
    metadata = json.loads(str(capture["metadata"]))
    celsius = raw.astype(np.float64) / 64 - 273.15
    print(f"{celsius[10, 20]:.6f} °C")    # sensor x=20, y=10
```

Metadane zawierają model, flagę demo, ustawienia obrazu, obrót i odbicie, czas zapisu UTC, monotoniczny czas pobrania klatki, jednostkę RAW i wzór konwersji. UTC oznacza chwilę zapisu, nie dokładną chwilę ekspozycji. NPZ zachowuje natywną orientację, także jeśli obraz był obrócony. PNG zapisuje obraz z aktualną orientacją i paletą w rozdzielczości sensora, **bez kontrolek, siatki, etykiet i pomiarów**. PNG nie zastępuje danych radiometrycznych. Dialog zapisu obejmuje klatkę obecną w momencie jego otwarcia.

## Diagnostyka

| Objaw | Postępowanie |
| --- | --- |
| Camera not found | Sprawdź model, kabel, identyfikatory USB i dostęp urządzenia. Po podłączeniu poczekaj na automatyczne wznowienie; Reconnect przyspiesza próbę. |
| Access denied / busy | Sprawdź reguły udev/WinUSB oraz czy inna aplikacja nie zajmuje kamery. |
| Brak display / Tk | Uruchom w sesji graficznej i zainstaluj Tk dla używanego Pythona. |
| Disconnected / error | Okno pozostaje otwarte, obraz i pomiary są zastąpione komunikatem o braku kamery. Podłącz ponownie: aplikacja automatycznie wznowi podgląd po inicjalizacji. |
| Nieprawidłowy zakres | Wpisz skończone liczby, maksimum większe od minimum. Odrzucone ustawienie nie zmienia aktywnego przetwarzania. |
| Kolory nie odpowiadają °C | Factory brightness i Enhance są nieliniowe. Użyj Temperature, Fixed i wyłącz Enhance. |
| Początkowo pomijane klatki | Protokół może wymagać odzyskania synchronizacji; użyj `--debug` do diagnostyki. Nie gwarantujemy usunięcia wszystkich początkowych odrzuceń bez testu sprzętowego. |

Freeze nie zatrzymuje strumienia. Reconnect nie uruchamia drugiego wątku, dopóki poprzedni nie zakończy cleanup. Program nie przełącza automatycznie modelu urządzenia.

## Testy wykonane i granice weryfikacji

Automatyczne testy jednostkowe obejmują protokół z istniejącego zestawu, wszystkie 65536 możliwych sześciocyfrowych odczytów temperatur, wszystkie kombinacje obrotu i odbicia, wybór piksela, filtry, tryby źródeł, zapis NPZ, zwolnienie zasobów mimo błędu i zakończenie generatora demo. Opcjonalny test Tk otwiera rzeczywiste okno, przełącza źródła, sprawdza temperatury w etykietach zoomu, orientację i zamknięcie.

Podczas refaktoryzacji podłączono **P3, firmware 00.00.02.18**. Potwierdzono rzeczywiste klatki 256×192 uint16, około 25 klatek/s po rozruchu, działanie migawki, ponowne otwarcie po zamknięciu oraz przejście testu całego GUI z kamerą (tryby źródeł, zoom z temperaturami, obrót/odbicie, zamknięcie). Rozruch do pierwszej klatki trwał około 5 sekund. Wykonano też fizyczne odłączenie USB podczas pracy GUI: aplikacja wykryła błąd urządzenia, a osobny skrypt testowy celowo uruchomił zarejestrowaną procedurę WM_DELETE_WINDOW (tę samą co X); nie jest to zachowanie produkcyjnej aplikacji, okno i wątek zakończyły pracę. Ponowne otwarcie sprawdzono po programowym zamknięciu; automatyczne ponowne połączenie w tym samym oknie sprawdza dodatkowy test GUI z symulowanym urządzeniem (brak kamery przy starcie, odłączenie, ponowne połączenie i zamknięcie podczas oczekiwania). Fizyczne ponowne podłączenie po tej zmianie pozostaje do osobnego testu.

Wykryto ograniczenie: LOW zmieniał zakres tej samej sceny z około 20–25°C na około −34°C. Kalibracja migawką nie usunęła tego przesunięcia; powrót do HIGH przywracał poprzedni zakres. LOW ma zatem status eksperymentalny, a jego odczytów nie należy traktować jako zweryfikowanych temperatur. Nie dopasowano sztucznego offsetu do jednej sceny. Dokumentacja [oryginalnego protokołu](https://github.com/jvdillon/p3-ir-camera/blob/main/P3_PROTOCOL.md) opisuje wspólne kodowanie 1/64 K i komendy gain, lecz nie wyjaśnia zaobserwowanej różnicy. Sporadyczny timeout potwierdzenia polecenia migawki jest raportowany; aplikacja próbuje dalej odbierać klatki zamiast natychmiast kończyć sesję.

Test GUI na Pythonie 3.14 ignoruje tylko znane ostrzeżenie deprecacji struktury ctypes w backendzie libusb0 biblioteki PyUSB; pozostałe ostrzeżenia nadal są błędami testów. Aby powtórzyć test z fizyczną kamerą:

```bash
P3_GUI_TEST=1 P3_GUI_CAMERA=1 python -m pytest tests/gui_test.py -q
```

Dalsza lista kontroli sprzętowej (P1 i pozostałe systemy nie zostały sprawdzone):

1. Otwórz fizyczną kamerę, potwierdź ciągłość klatek i zgodność RAW/64−273.15 z odczytem kursora.
2. Sprawdź obrót, odbicie, skrajne piksele i zoom; odczyt tego samego sensora nie może zależeć od palety.
3. Wykonaj NUC i przełącz HIGH/LOW. Sprawdź dalszy dopływ klatek i komunikaty błędów.
4. Zamknij podczas transmisji i otwórz ponownie. Sprawdź dostęp do USB i synchronizację.
5. Odłącz podczas transmisji, zamknij przez X. Powtórz, tym razem podłącz i poczekaj na automatyczny powrót obrazu bez zamykania okna.
6. Zamknij podczas startu i po nieudanej inicjalizacji. Nie powinien pozostawać proces posiadający USB.
7. Sprawdź eksport NPZ oraz działanie P1 i P3 osobno. Windows/macOS wymagają odrębnego sprawdzenia.

Lock-in, pomiar dokładności absolutnej, korekcja środowiskowa, bezstratne nagrywanie ciągłe i odtwarzanie NPZ w GUI nie są funkcjami zweryfikowanymi lub zaimplementowanymi w tym wydaniu.
