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

Metadane zawierają model, flagę demo, ustawienia obrazu, obrót i odbicie, czas zapisu UTC, monotoniczny czas pobrania klatki, jednostkę RAW i wzór konwersji. UTC oznacza chwilę zapisu, nie dokładną chwilę ekspozycji. NPZ zachowuje natywną orientację, także jeśli obraz był obrócony. Save image rozróżnia natywny 16-bitowy PNG RAW od kolorowego PNG. PNG RAW zachowuje radiometryczne kody sensora, ale nie zawiera osobnego kanału jasności ani metadanych NPZ. Kolorowe obrazy nie zastępują danych radiometrycznych. Dialog zapisu obejmuje klatkę obecną w momencie jego otwarcia.

## Diagnostyka

| Objaw | Postępowanie |
| --- | --- |
| Camera not found | Sprawdź model, kabel, identyfikatory USB i dostęp urządzenia. Po podłączeniu poczekaj na automatyczne wznowienie; Reconnect przyspiesza próbę. |
| Access denied / busy | Sprawdź reguły udev/WinUSB oraz czy inna aplikacja nie zajmuje kamery. |
| Brak display / Tk | Uruchom w sesji graficznej i zainstaluj Tk dla używanego Pythona. |
| Disconnected / error | Okno pozostaje otwarte, obraz i pomiary są zastąpione komunikatem o braku kamery. Podłącz ponownie: aplikacja automatycznie wznowi podgląd po inicjalizacji. |
| Nieprawidłowy zakres | Wpisz skończone liczby, maksimum większe od minimum. Odrzucone ustawienie nie zmienia aktywnego przetwarzania. |
| Kolory nie odpowiadają °C | Factory brightness, CLAHE i DDE nie mają liniowej zależności kolor–temperatura. Użyj Temperature, Fixed i wyłącz CLAHE/DDE albo wybierz własną paletę o progach °C. |
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

Lock-in i X³ pozostają niezaimplementowane. Korekcja środowiskowa ma status eksperymentalny, a nagrywanie raportuje odrzucenia przy przeciążeniu. Dokładność absolutna korekcji i długie nagrania na sprzęcie nie zostały zweryfikowane.


## Zapis obrazów

| Format | Co jest zapisywane |
| --- | --- |
| JPEG | Aktualny kolorowy obraz, powiększenie bicubic 1–8× (domyślnie 3×), jakość 1–100 (domyślnie 95). Wygładzenie nie dodaje pomiarów sensora. |
| PNG native RAW | Oryginalna macierz uint16, natywna orientacja, bez skalowania, palety, legendy i filtrów. Może wyglądać ciemno w zwykłej przeglądarce. |
| PNG current color | Bezstratny zapis aktualnego RGB z orientacją i filtrami, w rozdzielczości sensora. |
| NPZ (Save data) | Obie płaszczyzny kamery, metadane i definicja aktywnej palety użytkownika. Format do ponownego otwierania w aplikacji. |

Opcja **Include legend** dołącza pasek po prawej stronie JPEG/kolorowego PNG; zmienia rozmiar wynikowego obrazu. Nie dotyczy PNG RAW. Eksport obejmuje całą klatkę, bez przycinania do widocznego zoomu, siatki pikseli czy znaczników min/max.

## Import zamrożonej klatki

Open RAW przyjmuje NPZ zapisane przez nowy viewer i wcześniejsze NPZ z tablicami `raw`, `brightness` oraz opcjonalnymi metadanymi. Open RAW przyjmuje również samodzielne NPY uint16 i natywne 16-bitowe PNG RAW. Nie zawierają kanału fabrycznej jasności ani metadanych; Factory brightness jest dla nich niedostępne. Import weryfikuje typy, rozmiar, jednostkę i ustawienia; nie używa pickle. Limit rozpakowanej zawartości wynosi 32 MB.

Przywracane są zapisane ustawienia obrazu i orientacja. Paleta niestandardowa zapisana w NPZ jest dodawana do biblioteki; konflikt z istniejącą, inną paletą otrzymuje nową nazwę. Fabryczne palety nie są nadpisywane. Zapisane klatki wersji 1 z połączonym `detail` odtwarzają oba filtry CLAHE/DDE. Wersja 2 zapisuje je osobno.

Import pozostaje zamrożony mimo napływu klatek lub utraty USB. Kamera może w tym czasie nadal przesyłać dane, ale nie sterujemy jej ustawieniami z trybu analizy pliku. Return to live przywraca akwizycję i automatyczne ponawianie połączenia. Filtr czasowy dla pojedynczej importowanej klatki nie ma historii do uśredniania.

## Palety użytkownika

W Palettes wybierz New, nadaj nazwę i dodaj co najmniej dwa punkty °C/#RRGGBB. Color otwiera wybór koloru, Update zmienia zaznaczony punkt, Remove usuwa punkt. Save and use sortuje temperatury i zapisuje preset. Temperatury nie mogą się powtarzać. Edit pozwala poprawiać preset; nowa nazwa tworzy kopię.

`linear` interpoluje kanały RGB pomiędzy punktami. `steps` przypisuje kolor punktu aż do następnego progu (próg należy do nowego pasma). Poniżej minimum i powyżej maksimum używane są kolory końcowe. Legenda odwzorowuje tę samą funkcję co obraz.

Format przenośnego JSON:

```json
{
  "version": 1,
  "name": "PCB 15–50 C",
  "interpolation": "linear",
  "stops": [[15, "#0000FF"], [25, "#00FF00"], [50, "#FF0000"]]
}
```

Biblioteka znajduje się w `$XDG_CONFIG_HOME/p3-thermal-studio/palettes.json`, a jeśli ta zmienna nie jest ustawiona — w `%APPDATA%/p3-thermal-studio/palettes.json` na Windows lub `~/.config/p3-thermal-studio/palettes.json`. Zapis jest atomowy. Uszkodzona biblioteka nie jest automatycznie nadpisywana; komunikat w panelu wskazuje błąd. Import/edycja istniejącej palety prosi o potwierdzenie zastąpienia. Nazwy fabryczne są zarezerwowane i chronione również w warstwie danych.


## Siła DDE i legenda przy CLAHE

W Filters zaznacz DDE i ustaw DDE strength (0–4, domyślnie 1.5). DDE wyostrza krawędzie, więc na gładkiej powierzchni efekt może być niewielki. Duże wartości mogą uwydatnić szum i obwódki. Porównuj na zamrożonej klatce, przełączając DDE przy stałej palecie i zakresie. CLAHE ma osobny przełącznik.

Przy CLAHE/DDE oraz Factory brightness pasek jest opisany `°C min/max`. Przy każdym z pięciu pasm podaje dwie liczby: najniższą i najwyższą temperaturę RAW pikseli, które trafiły do tego pasma w wyświetlanej klatce. Kreska oznacza brak takich pikseli. Nie jest to jednoznaczna kalibracja koloru: zakresy mogą się pokrywać lub zmieniać kolejność. Dokładny odczyt konkretnego piksela pozostaje pod obrazem. Eksportowana legenda przedstawia te same zakresy, zapisane jako min/max obok paska.


Pełna instrukcja ROI, profili, izoterm, warstw emisyjności i nagrywania jest w [ANALYSIS.md](ANALYSIS.md).
