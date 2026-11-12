"""Początki ostatnich linii narzędzi, które czyta inne narzędzie, hook albo CI: piszący i czytający biorą je stąd.

Czytający nie importuje piszącego, bo leży niżej (moduł ``tools/lib``, hook na systemowym Pythonie 3.9) albo uruchamia
go z innego commitu (``tools/scal_pr.py --przeglad`` z HEAD PR), więc prefiks ma jedno źródło tutaj. Moduł używa tylko biblioteki
standardowej i działa pod Pythonem 3.9 macOS (``per-file-target-version`` w ``pyproject.toml``).
"""

# ``tools/lib/silnik_mutacji.py`` (``check_all``) kończy nią każdy skrypt mutacji skilla, który przeszedł; czyta
# ``tools/ci/wykonaj_zadanie.py``.
MUTACJE_OK = "MUTACJE OK"
# ``tools/skille_dla_zmiany.py``; czytają ``tools/lib/kontekst_przegladu.py`` (``scal_pr.py --przeglad``) i brama ``tools/hooks/pre-push``.
SKILLE_VERIFY = "SKILLE VERIFY: "
# ``tools/skille_dla_zmiany.py`` pisze ją przed ostatnią linią, gdy jakiś skill obowiązuje; brama ``tools/hooks/pre-push``
# drukuje ją razem z ostatnią linią.
CO_DALEJ = "CO DALEJ: "
# ``tools/praca_w_toku.py --aktualizacja``; czyta brama ``tools/hooks/pre-push``.
AKTUALIZACJA = "AKTUALIZACJA: "
# ``tools/ci_lokalnie.py``; czyta status ``scalenie z main`` (``tools/lib/werdykt_scalenia.py``).
CI_LOKALNIE_OK = "CI LOKALNIE OK"
CI_LOKALNIE_FAIL = "CI LOKALNIE FAIL | "
