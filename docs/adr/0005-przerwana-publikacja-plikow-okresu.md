# ADR 0005: Przerwana publikacja plików okresu jako zaakceptowane ryzyko

## Status

Zaakceptowana. Rozstrzyga issue #91. Zmieniona 2026-11-05: decyzja Maksa
obejmuje też proces zabity w trakcie wycofania po nieudanym drugim `os.rename`
(PR #948, issue #920).

## Kontekst

Przygotowanie pliku zbiorczego obiecuje, że oba pliki okresu powstają razem
albo żaden (`GLOSSARY.md`). Gdy Folder okresu jeszcze nie istnieje, cały
katalog tymczasowy staje się Folderem okresu w jednym `rename`, więc obietnica
obowiązuje bez wyjątków. Gdy Folder okresu już istnieje, `_publish` przenosi
Rozliczenie wewnętrzne i Plik zbiorczy dwoma osobnymi `os.rename`. Windows nie
pozwala, żeby dwa pliki pojawiły się w istniejącym folderze atomowo. Jeśli
proces zginie między tymi wywołaniami (tata zamknie okno, zabraknie prądu), w
Folderze okresu zostaje samo Rozliczenie wewnętrzne.

Drugi przypadek zaczyna się, gdy drugi `os.rename` (Pliku zbiorczego) nie
powiedzie się, na przykład bo plik trzyma antywirus albo OneDrive. Wtedy
`_publish` wycofuje publikację: w `except OSError` usuwa już przeniesione
Rozliczenie wewnętrzne (`target.unlink(missing_ok=True)`). Jeśli proces zginie
po błędzie drugiego `os.rename`, a przed końcem tego usuwania, w Folderze okresu
też zostaje samo Rozliczenie wewnętrzne. Sprawdzenie
`verify-publikacja-plikow-okresu` pokazało ten przypadek osobno dopiero w #948,
bo wcześniej oba miały ten sam podpis.

## Decyzja

Akceptujemy to ryzyko i nie zmieniamy kodu publikacji. Okno trwa mikrosekundy.
Skutek jest jawny i bezpieczny: następne Uruchomienie procesu zatrzymuje się na
`PLIK_OKRESU_ISTNIEJE` (Nienadpisywanie), wskazuje plik i każe go przenieść
albo usunąć. Instrukcja taty opisuje, jak rozpoznać taki niedokończony zapis.

Tak samo akceptujemy proces zabity w trakcie wycofania (decyzja Maksa z
2026-11-05, PR #948). W kodzie `_publish` (`src/rozliczenia/preparation_files.py`)
między błędem drugiego `os.rename` a usunięciem pierwszego pliku nie ma innego
wywołania systemu plików. Pętla `except` idzie po liście z jednym plikiem i od
razu woła `unlink`. Okno trwa więc mikrosekundy, jak między dwoma `os.rename`,
a wymaga jeszcze nieudanego `os.rename`, więc zdarza się rzadziej. Skutek jest
ten sam: w Folderze okresu zostaje samo Rozliczenie wewnętrzne, a następne
Uruchomienie zatrzymuje się na `PLIK_OKRESU_ISTNIEJE` i wskazuje ten plik, bo
to jedyny plik okresu w Folderze okresu. Gdy obok leży plik taty o nazwie
Pliku zbiorczego (Konsekwencje), też wskazuje Rozliczenie wewnętrzne, bo
`ensure_period_files_absent` sprawdza je pierwsze. Nic nie zostaje nadpisane.
Jeśli proces zginie w trakcie samego `unlink`, plik albo zniknął (nie zostaje
żaden plik okresu), albo został (jak wyżej). Opis niedokończonego zapisu w
instrukcji taty (samo Rozliczenie wewnętrzne bez Pliku zbiorczego po
uruchomieniu, które nie doszło do wyniku) pasuje do tego przypadku bez zmian.

Odrzucone kierunki:

- **Podfolder publikowany jednym `rename`** zmienia układ Folderu okresu, do
  którego tata jest przyzwyczajony.
- **Dokończenie publikacji przez następne uruchomienie** z pozostałości katalogu
  tymczasowego wymaga przeszukiwania folderu okresów, nowego komunikatu, obsługi
  dwóch uruchomień naraz i rozbudowy sprawdzenia o uruchomienia po kolei. To
  dużo kodu jak na ryzyko tej skali.
- **Osobny komunikat o przerwanym zapisie** daje niewiele ponad obecny
  komunikat `PLIK_OKRESU_ISTNIEJE`, a kosztuje to samo rozpoznawanie
  pozostałości.

## Konsekwencje

- `explore_publication.py` zgłasza oba przypadki jako `ZAAKCEPTOWANE RYZYKO`
  (`ACCEPTED_RISKS`), a nie jako znane ustalenie. Inny ślad naruszenia
  RAZEM_ALBO_ZADEN nadal jest błędem sprawdzenia, także zabicie po nieudanym
  `os.unlink` wycofania (przypadek #92 niżej).
- Gdy drugi `os.rename` nie powiedzie się, bo tata (albo OneDrive) w tej samej
  chwili położył w Folderze okresu plik o nazwie Pliku zbiorczego, po zabiciu
  w trakcie wycofania obok Rozliczenia wewnętrznego leży ten plik taty. Wtedy opis
  niedokończonego zapisu z instrukcji nie pasuje, ale następne Uruchomienie i
  tak zatrzymuje się na `PLIK_OKRESU_ISTNIEJE` i nic nie nadpisuje. To wymaga
  pliku taty w tych samych mikrosekundach i zabicia procesu zaraz potem, więc nie
  zmieniamy z tego powodu instrukcji.
- Decyzja nie obejmuje nieudanego wycofania po błędzie zapisu (issue #92). Tam
  proces działa dalej, a `unlink` zgłasza błąd, więc proces mówi tacie prawdę
  komunikatem `BLAD_ZAPISU_POZOSTAL_PLIK`. Zabicie w trakcie wycofania to inny
  przypadek: wycofanie nie zdążyło się skończyć i nikt nie wydaje komunikatu.
- Do decyzji trzeba wrócić, jeśli publikacja zacznie trwać dłużej, na przykład
  przez kopiowanie zamiast przenoszenia albo przez folder sieciowy.
