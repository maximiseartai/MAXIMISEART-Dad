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


KWARANTANNA: dict[str, Kwarantanna] = {}
