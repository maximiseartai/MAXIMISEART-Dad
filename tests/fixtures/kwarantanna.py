"""Kwarantanna niestabilnych testów (ADR 0020): test z wpisem biegnie jako ``xfail(strict=False)``, także na `main`.

Klucz to id testu pytest (``tests/test_x.py::test_y[parametry]``), a wpis to issue ``Flaky test: <test>`` i dzień, do którego
kwarantanna trwa. Test w kwarantannie nie czerwieni ``Required CI status``, ale ``tests/conftest.py`` daje mu w junit
własność ``kwarantanna``, z której jego wynik trafia do artefaktu ``kwarantanna-*`` runu `main`, a ``tools/wydanie.py``
nie wydaje commitu, na którym padł albo nie ma zapisu przejścia. Reguły wpisu sprawdza ``tests/test_kwarantanna.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Kwarantanna:
    issue: int  # numer issue ``Flaky test: <test>`` w tym repozytorium
    do: date  # ostatni dzień kwarantanny, najwyżej 7 dni od dziś


KWARANTANNA: dict[str, Kwarantanna] = {
    # Okno czyta treść odpowiedzi „Załaduj do zlecenia”, którą przeładowanie strony porzuca (#895); zdejmij z naprawą #895.
    "tests/test_centrum_logi_uruchomienia.py::test_dziennik_wyceny_w_efenix_ktorego_nie_da_sie_zapisac_nie_zatrzymuje_wyceny_i_ma_jedna_linie_na_wycene_w_dzienniku_centrum": Kwarantanna(
        896, date(2026, 11, 12)
    ),
}
