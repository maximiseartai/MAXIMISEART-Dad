# ADR 0027: Wycena w efenix przekazuje gotowe zlecenia do akceptacji w trybie z Przekazaniem

## Status

Zaakceptowana (decyzja Maksa 7.11.2026 po rozmowie z tatą). Odwraca w ADR 0024 tylko punkt „Narzędzie nigdy nie
przekazuje zlecenia do akceptacji ani go nie anuluje” w części o Przekazaniu do akceptacji i odrzucony wariant
„Narzędzie samo przekazuje do akceptacji”. Anulowania narzędzie dalej nie robi, a reszta ADR 0024 zostaje.

## Kontekst

Po Wycenie w efenix tata otwiera w efenix każde gotowe zlecenie, czyli to ze Znacznikiem efenix, i klika zielony
„Zapisz”, żeby przekazać je firmie do akceptacji. Przy ok. 280 zleceniach w okresie to druga, ręczna runda po tych
samych zleceniach, które narzędzie już sprawdziło: wycena jest uzupełniona z Pliku zbiorczego, a kwota końcowa jest
równa `Kwota` (AU). ADR 0024 odłożył Przekazanie, bo nie da się go łatwo cofnąć. Tata zgodził się, żeby narzędzie
robiło je samo, ale chce wybierać przy każdym uruchomieniu.

Czerwony „Zapisz” obok zielonego anuluje zlecenie, a oba otwierają to samo okno dialogowe zmiany statusu. Pomyłka
anulowałaby zlecenie firmy, czego narzędzie nie umie cofnąć.

## Decyzja

- **Wycena w efenix ma dwa tryby, które tata wybiera przy każdym uruchomieniu:** bez Przekazania (jak dotąd: uzupełnia
  wycenę i oznacza gotowe Znacznikiem efenix) i z Przekazaniem (to samo, a gotowe zlecenia przekazuje do akceptacji).
  Żaden tryb nie jest pamiętany, a gdzie tryb nie jest podany (Skrypt dla maszyn bez flagi), obowiązuje tryb bez
  Przekazania.
- **Przekazuje tylko zlecenia gotowe:** bez Ostrzeżenia Emmetta, z kwotą końcową równą `Kwota` (AU), także gotowe z
  wcześniejszego uruchomienia. Błędy i Ostrzeżenia Emmetta zostają tacie nieprzekazane.
- **Przekazanie potwierdza lista zleceń:** po zielonym „Zapisz” narzędzie szuka zlecenia jeszcze raz, a dopiero status
  „Do akceptacji” z realizatorem i adresem z pliku daje Zlecenie przekazane. Inna lista to błąd zlecenia bez
  Znacznika, a Komunikat każe tacie sprawdzić zlecenie w efenix. Gdy efenix po zielonym „Zapisz” odmawia Przekazania
  oknem informacji (brak zdjęć, długości przyłącza, wyceny albo daty wykonania), to też błąd zlecenia bez Znacznika, a
  nie Zatrzymanie: okno niczego nie wysyła, Komunikat mówi tacie, czego efenix brakuje, a Wycena idzie dalej.
- **Zlecenie „Do akceptacji” to wynik, nie błąd, w obu trybach**, tak jak Zlecenie rozliczone: narzędzie go nie otwiera i
  niczego w nim nie zmienia.
- **Zlecenie przekazane ma w `ADRES` ciemniejszy fiolet `B48AFF`, Znacznik przekazania**, a gotowe dalej jasny Znacznik
  efenix `E0CCFF`. Oba nie zaciemniają czarnego tekstu (kontrast 8,0:1 i 14,3:1, WCAG AAA). Znacznik przekazania
  zastępuje Znacznik efenix, a Znacznik efenix nigdy nie zastępuje Znacznika przekazania. Ponowne uruchomienie po
  zgaśnięciu między Przekazaniem a zapisem Znaczników daje więc zleceniu ciemny Znacznik.
- **Okno efenix przepuszcza tylko swoje żądanie Przekazania.** Żądanie zmiany statusu, którego nowy status nie jest
  dokładnie „Do akceptacji”, które dotyczy innego zlecenia niż otwarte w oknie albo które nie przyszło w Przekazaniu (w
  trybie bez Przekazania każde), okno przerywa, zanim dojdzie do efenix, i zatrzymuje Wycenę „do Maksa”. Przekazanie
  innego zlecenia byłoby tak samo nieodwracalne jak anulowanie (przegląd #1067 r1). Strażnik stoi na całej przeglądarce okna, więc obejmuje też ramki i
  okna, które otworzy strona.
- **Przekazanie to zapis w tempie ludzkim** (przerwa przed nim jak przed każdym zapisem), a ponowne szukanie po nim to
  odczyt bez przerwy.

## Odrzucone warianty

- **Zostawić Przekazanie tacie (ADR 0024).** Tata robi wtedy drugą rundę po każdym gotowym zleceniu tylko po to, żeby
  kliknąć jeden przycisk, a narzędzie już wie, które zlecenia są gotowe.
- **Jeden tryb, zawsze z Przekazaniem.** Tata chce móc uruchomić Wycenę, która niczego nie przekazuje, np. gdy chce
  najpierw obejrzeć wynik w Pliku zbiorczym.
- **Pamiętać ostatni tryb.** Przekazania nie da się łatwo cofnąć, więc tata ma wybrać je świadomie przy każdym
  uruchomieniu.
- **Uznać Przekazanie za udane po odpowiedzi efenix.** Postaci odpowiedzi na zmianę statusu nikt nie zmierzył, a lista
  zleceń pokazuje status tak, jak widzi go tata i firma.
- **Przekazywać także zlecenia z Ostrzeżeniem Emmetta.** Takie zlecenie ma w efenix więcej niż Plik zbiorczy, a decyzję,
  kto ma rację, podejmuje tata (ADR 0026).
