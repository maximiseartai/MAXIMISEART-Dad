# Przegląd PR: kolejne rundy

Runda po `FAIL` sprawdza diff od przejrzanego SHA do nowego HEAD i to, czy każde znalezisko poprzedniej rundy jest zamknięte.
Zamkniętych znalezisk nie powtarza.
Ważne poprzedniej rundy jest zamknięte, gdy korzeń wyrwano według [`korzen.md`](korzen.md), z dowodem wyrwania i sondą formy siostrzanej.
Nowe znalezisko w kodzie, którego ta runda nie zmieniła, jest Ważne tylko wtedy, gdy to defekt zachowania z dowodem.
Po drugiej rundzie z `FAIL` na tej samej przesłance (ta sama granica albo reguła pada na kolejnym przypadku) kolejna runda zaczyna się od zmiany podejścia: ataku na przesłankę, granicy z mechanizmu albo podziału PR.
Po trzeciej rundzie z `FAIL` bez zmiany podejścia czwartej rundy nie ma, a gdy Ważne dwóch pierwszych rund z `FAIL` trafiają w ten sam plik pola `Gdzie:` albo mają ten sam kod `Korzeń:`, nie ma już trzeciej: `tools/scal_pr.py` odmawia jej w `--przeglad`, w `--werdykt` i przy merge'u (limit rund, `tools/lib/limit_rund.py`), dopóki autor nie zmieni podejścia w tym samym PR i nie opisze tego komentarzem PR z pierwszą linią `ZMIANA PODEJŚCIA: <zdanie>`.
Po szóstej rundzie z `FAIL` PR nie dostaje żadnej rundy, jakiekolwiek ma komentarze, więc zostaje nowy PR od świeżego `origin/main` (#2010: cztery komentarze dały osiem rund z `FAIL`).
Podejście zmienia się w tym samym PR, a nie w nowym, bo bramka korzenia i bramka strażnika czytają tylko werdykty własnego PR, więc nowy PR gubi Ważne rund poprzednika (#1990); część, której przegląd nie przyjął, usuwasz z PR, a jej Ważne dostają w `## Korzeń` szczebel (a) z usuniętym kodem i `Strażnik: brak - usunięte`.
Recenzent rundy po zmianie podejścia sprawdza najpierw, czy diff od ostatniego `FAIL` robi to, co mówi to zdanie; gdy nie robi, to Ważne.
Każdą rundę robi nowy recenzent, który nie pisał kodu, z linkiem do poprzednich werdyktów.
Werdykt dla SHA, który ma już werdykt w tym PR (linia `RUNDA` z `--przeglad` kończy się `czyli dla tego HEAD`), ma w `## Sprawdzone` punkt `Ponowny przegląd: <czemu kolejny przegląd tego SHA i punkty „Do sprawdzenia” ze zlecenia>`, więc ślad na PR mówi, skąd zmiana zgody bez zmiany kodu (#875 r3: `FAIL` po `PASS` po tezie koordynatora); bez niego `--werdykt` i merge odmawiają (`tools/lib/ponowny_przeglad.py`).
