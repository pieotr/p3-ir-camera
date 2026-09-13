# Architektura Thermal Studio

## Podział odpowiedzialności

| Plik | Odpowiedzialność i punkt rozszerzenia |
| --- | --- |
| `p3_viewer.py` | Mały punkt wejścia, argumenty CLI i uruchomienie Tk. Import nie otwiera okna ani USB. |
| `p3_camera.py` | Istniejący protokół, modele, dekodowanie klatek, sterowanie i konwersje radiometryczne. Bez zależności od GUI. |
| `p3_thermal/acquisition.py` | `Frame` i `Acquisition`: jedyny właściciel kamery, kolejka poleceń, ostatnia klatka i zdarzenia statusu. |
| `p3_thermal/processing.py` | `DisplaySettings`, `Processor`, palety, konwersja i orientacja. Filtry mają stan lokalny instancji. |
| `p3_thermal/canvas.py` | `ThermalCanvas`: renderowanie widocznego obszaru, geometria zoom/pan, inspektor i mapowanie kursora. |
| `p3_thermal/app.py` | `ThermalApp`: kontrolki, stan sesji, cykl odświeżania i dialogi. |
| `p3_thermal/export.py` | Zapis/import NPZ, migracja metadanych, JPEG i PNG RAW/kolor. |
| `p3_thermal/palettes.py` | Walidacja definicji, mapowanie absolutnych temperatur, atomowa biblioteka JSON. |
| `p3_thermal/palette_ui.py` | Edytor punktów palety i zarządzanie presetami. |
| `p3_thermal/image_ui.py` | Dialog wyboru formatu, jakości JPEG i legendy eksportu. |

## Przepływ danych

```text
USB / generator demo → Acquisition → Frame(raw, brightness, timestamp)
                                        ├── pomiary / eksport: oryginalny RAW
                                        └── Processor → RGB → orientacja → ThermalCanvas
```

`raw` to macierz H×W `uint16`, `brightness` to H×W `uint8`. Wątek kopiuje obie płaszczyzny przed publikacją. Odbiorcy traktują je jako niemutowalne; `frozen=True` chroni pola `Frame`, ale sam NumPy nie blokuje zapisu do tablic. Timestamp pochodzi z `time.monotonic()` na komputerze, nie z zegara kamery.

Kolejka klatek ma pojemność **1**. Starsze klatki są zastępowane, co zapobiega narastaniu opóźnienia przy wolnym renderowaniu. Utrata klatek w tej kolejce jest zamierzona i nie nadaje się do bezstratnego nagrywania. Zdarzenia i polecenia używają osobnych kolejek. GUI odpytuje je co 40 ms; USB nigdy nie jest wywoływane z callbacku Tk.

## Cykl życia kamery

Wątek wykonuje `connect → init → start_streaming → read_frame_both` i w `finally` zawsze próbuje `disconnect`. `disconnect` zwalnia zasoby libusb również wtedy, gdy zatrzymanie strumienia rzuci wyjątek. Flaga strumienia ustawiana jest już po włączeniu alternatywnego interfejsu, aby częściowo udany start też podlegał cleanup.

Pojedynczy bulk read ma timeout 500 ms. Składanie klatki i odczyt po migawce mają limit 5 s sprawdzany pomiędzy transferami; ostatni transfer może wydłużyć go o swój timeout. Zapobiega to nieskończonemu poszukiwaniu synchronizacji. Krótkie timeouty 500 ms są ponawiane do limitu całej klatki. Zdarzenie anulowania jest sprawdzane pomiędzy transferami, dzięki czemu zamknięcie nie czeka na pełny limit. Nie zmieniono formatu pakietów. Niepoprawne znaczniki klatki są pomijane; timeout polecenia sterującego jest raportowany i pozwala podjąć odbiór klatek; inne wyjątki kończą sesję USB. GUI pozostaje otwarte, usuwa nieaktualne pomiary z widoku i pokazuje brak kamery. Po zakończeniu cleanup odczekuje 2 s i uruchamia nowy wątek akwizycji. Nie ma równoległych prób połączenia; Reconnect pozwala przyspieszyć oczekującą próbę. Pierwsza klatka nowej sesji wznawia podgląd, także jeśli wcześniej używano Freeze. Zamknięcie anuluje timer GUI, więc nie uruchamia kolejnych prób.

Zamknięcie okna ustawia zdarzenie zakończenia, a Tk nadal przetwarza zdarzenia, czekając na cleanup. Podczas sekwencji inicjalizacji lub polecenia sterującego zamknięcie może potrwać kilka sekund. Thread jest daemonem jako zabezpieczenie zakończenia procesu, lecz normalna ścieżka czeka na zwolnienie USB. Zawieszenie samego sterownika systemowego poza timeoutami biblioteki nie jest rozwiązywane przez wymuszone zabijanie wątku.

## Pomiary i obraz

Konwersja działa na `float64`, a format `:.6f` odtwarza wszystkie wartości kodowania 1/64 K. Nie wolno wyznaczać pomiarów z RGB ani z `Processor.previous`. Filtr EMA i normalizacja wpływają wyłącznie na obraz. Render tej samej klatki z tymi samymi ustawieniami jest buforowany w aplikacji, więc obrót/odbicie nie powoduje wielokrotnego filtrowania jednej klatki.

Palety korzystają z LUT OpenCV. Zakres automatyczny to percentyle 1/99 i EMA granic z wagą 0.15. Filtr temperatury ma konfigurowalną wagę 0.05–1, domyślnie 0.35. Przy zmianie ustawień albo ponownym połączeniu stan przetwarzania jest resetowany. Jasność fabryczna i CLAHE nie mają globalnej liniowej zależności kolor–temperatura, dlatego legenda podaje dla nich obserwowane zakresy °C w pasmach jasności, a nie fikcyjną liniową konwersję. Fixed jest pomijane dla Raw counts i Factory brightness.

Obrót to `np.rot90` (przeciwnie do wskazówek zegara), po nim opcjonalne odbicie poziome. Identycznie transformowane są RGB, RAW i mapa oryginalnych współrzędnych sensora. Canvas używa jednej skali i przesunięcia do rysowania i pickingu. Komórka piksela jest wybierana przez `floor`, nie zaokrąglenie. Widoczne etykiety zawsze odczytują RAW tej komórki.

Renderowanie `warpAffine` tworzy bitmapę wielkości widocznego płótna. Nie tworzy ogromnego obrazu całego sensora przy zoomie 256×. Interpolacja nearest-neighbor utrzymuje granice natywnych pikseli; inspektor RGB backendu OpenCV nie jest używany.

## Rozbudowa

- Nowa paleta: dodaj wpis do `PALETTES` i przetestuj RGB oraz legendę.
- Nowy filtr: dodaj tryb do `Processor` i listy źródeł; utrzymuj osobny stan oraz metodę reset. Nie modyfikuj `Frame.raw`.
- ROI: użyj mapy współrzędnych sensora, statystyki oblicz z RAW; osobno ustal semantykę po obrocie i zoomie.
- Korekcja emisyjności: biblioteka zachowuje istniejące funkcje korekcji, lecz nowe GUI pokazuje temperaturę pozorną. Przyszły tryb powinien osobno opisywać wynik modelu korekcji i oryginalny odczyt, zapisywać parametry środowiska oraz odróżniać dokładność modelu od kodowania.
- Rejestracja wideo: własna kolejka z polityką przeciążenia i zapisem metadanych każdej klatki. Obecna kolejka latest-frame nie jest rejestratorem.
- Lock-in: integrator powinien otrzymywać `Frame` i timestamp, bez własnych odczytów USB. Wymaga osobnego sterowania bodźcem, anulowania, bezpiecznego zamykania portu i testów sprzętowych. Nie importujemy `lockin.py` podczas uruchamiania GUI.

## Zgodność

Zachowano polecenie `p3-viewer`, bezpośrednie `python p3_viewer.py` oraz API kamery. Usunięto klasę starego viewera i jego wewnętrzne funkcje ISP; nie są publicznym API nowej aplikacji. Konwersje RAW zwracają teraz dane float64. `set_gain_mode(AUTO)` jawnie zgłasza błąd zamiast pozornie ustawiać nieobsługiwany tryb. Stare eksperymentalne opcje CLI lock-in nie mają odpowiedników w nowym GUI.


## Tryb offline i legenda

`ThermalApp.offline` izoluje importowany `Frame` od zdarzeń kamery. Poll nadal odbiera kolejki, ale nie zastępuje klatki, nie usuwa jej przy rozłączeniu i nie uruchamia nowych sesji podczas analizy pliku. `return_live` przywraca tę ścieżkę. Stan `paused` samodzielnie dotyczy wyłącznie zatrzymania bieżącego podglądu.

`legend_colors` tworzy rampę identyczną z używaną paletą, a canvas rysuje ją od wysokich wartości do niskich. Nieliniowe filtry i Factory brightness przełączają legendę na obserwowane min/max °C w pięciu rozłącznych pasmach indeksu palety: 0–31, 32–95, 96–159, 160–223, 224–255. Przypisanie jest liczone z końcowego obrazu szarości przed LUT i oryginalnego RAW. Brak pikseli w paśmie oznacza brak odczytu, nie interpolację. Własna paleta wyprzedza normalizację, CLAHE i DDE: kolory określają fizyczne progi temperatur, więc filtry nie mogą ich przesuwać. Obszar legendy jest wyłączony z pickingu temperatury piksela.

NPZ wersji 2 zachowuje definicję własnej palety i niezależne ustawienia CLAHE/DDE. RAW i jasność nigdy nie są zmieniane przez przetwarzanie ani orientację. PNG RAW zapisuje uint16; JPEG/kolorowy PNG zapisują wizualizację i mogą mieć dołączony panel legendy. Żadna interpolacja eksportu nie zwiększa rozdzielczości pomiarowej sensora.

DDE korzysta z unsharp masking na float32, z rozmyciem Gaussa sigma 1.2 piksela i regulowaną siłą 0–4 (domyślnie 1.5). Wynik jest zaokrąglany i ograniczany do 8 bitów dopiero na końcu. Siła 0 nie zmienia obrazu; jednorodne obszary bez krawędzi mogą nie wykazywać zmiany przy żadnej sile. Ustawienie jest zapisywane w NPZ.
