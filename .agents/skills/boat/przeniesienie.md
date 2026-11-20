# Katalog repo przeniesiony w trakcie biegu

Box ze snapshotu albo po wznowieniu z dysku podaje `/home/user` z montowania FUSE ładowanego leniwie (lazyfs, `/var/lib/ascii-lazy/`).
Po załadowaniu (`HYDRATION-DONE` w `/var/lib/ascii-lazy/daemon.out`) lazyfs w pierwszej przerwie w odczytach podstawia prawdziwy dysk, a stare drzewo przenosi pod `/var/lib/ascii-lazy/retired/` (linia `retired /home/user ->` w tym samym pliku; 19.11.2026 w 16–29 s od startu boxa).
`boatbox` czeka z synchronizacją i poleceniem, aż `$HOME` boxa przestanie być montowaniem FUSE, więc przeniesienie trafia już tylko w polecenie, które ruszyło po 10 minutach czekania.
Polecenie, które już biegło w katalogu repo, ma wtedy katalog roboczy pod tą ścieżką, więc każdy worker pytest pada raz z komunikatem `BOX: boat przeniósł katalog repo w trakcie biegu; to nie test, powtórz bieg`.
To nie wygaśnięcie `BOATBOX_IDLE_MIN`: w każdym sprawdzonym takim biegu 19.11.2026 box był świeżo utworzony albo wznowiony, jego `hydratedAt` z `boat info <id> --json` wypadł w trakcie biegu, a następny bieg na tym samym boxie przeszedł.
Wznowienie nie zawsze ładuje dysk od nowa, a `hydrated` w `boat info` zostaje wtedy `true` z poprzedniego ładowania, więc o tym, czy box jeszcze ładuje dysk, mówi tylko sam box: `findmnt -n -o FSTYPE --mountpoint "$HOME"` daje wtedy typ `fuse…`.
Box wyjaśnia tylko katalog roboczy, który jest dokładnie oczekiwanym katalogiem po przeniesieniu (`box_boat.przeniesienie`): podkatalog, do którego test wszedł sam, inny stan zostawiony w tym samym teście (zmienna, plik, wątek) i błąd teardownu dalej są porażką testu.
Sesja pytest, której każda porażka to sam komunikat boxa, kończy się kodem 75 (`KOD_WYJSCIA` z `tools/lib/box_boat.py`, który rozstrzyga wszystkie trzy granice), a inna porażka obok, także porażka całej sesji jak `DRZEWO REPO`, daje kod 1.
