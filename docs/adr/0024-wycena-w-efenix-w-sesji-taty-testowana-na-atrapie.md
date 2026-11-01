# ADR 0024: Wycena w efenix w sesji taty, testowana na Atrapie efenix

## Status

Zaakceptowana (grilling 1.11.2026). Szczegóły procesu ustala jego specyfikacja.

## Kontekst

Tata po Uzupełnieniu pliku zbiorczego przepisuje ręcznie Ilości usług każdego
zlecenia do wyceny w efenix, systemie firmy, z którą się rozlicza. To ok. 280
zleceń w okresie. efenix to mała aplikacja jednoosobowej firmy bez API do
wycen. Ilość zapisuje się w nim na serwerze od razu po wyjściu z pola, a
zielony „Zapisz” przekazuje zlecenie firmie do akceptacji. Na tym samym
efenix tata codziennie pracuje naprawdę.

## Decyzja

- **Narzędzie pracuje w efenix tylko w sesji, którą otworzył tata.** Tata
  loguje się sam w oknie przeglądarki, które otwiera Centrum rozliczeń, a
  narzędzie przejmuje to okno. Hasła nie widzi i nie przechowuje.
- **Narzędzie nigdy nie przekazuje zlecenia do akceptacji ani go nie
  anuluje.** Uzupełnia wycenę, a gotowe zlecenie oznacza w Pliku zbiorczym
  Znacznikiem efenix. Przekazanie do akceptacji należy do taty.
- **Każdy test i każda próba w trakcie budowy biegnie na Atrapie efenix**:
  lokalnej imitacji stron i odpowiedzi efenix z wymyślonymi zleceniami.
  Prawdziwy efenix widzi tylko Uruchomienie procesu taty. Rekonesans na
  prawdziwym efenix jest wyłącznie do odczytu.
- **Tempo jest ludzkie:** ok. 20 s na zlecenie, nie sekundy.

## Odrzucone warianty

- **Import albo API od autora efenix.** Nie istnieje. Prośba do autora zostaje
  otwarta, ale na nią nie czekamy.
- **Próby na prawdziwym efenix.** Każda wpisana ilość od razu trafia na
  serwer, a załadowanie Wyceny Emmetta czyści wycenę zlecenia. Pomyłka
  psuje pracę taty i trafia do firmy.
- **Narzędzie samo przekazuje do akceptacji.** Tego nie da się łatwo cofnąć.
  Wrócimy do tego najwcześniej po kilku czystych okresach.
