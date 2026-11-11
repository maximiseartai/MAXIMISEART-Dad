"""Kwarantanna niestabilnych testów (ADR 0020): test z wpisem biegnie jako ``xfail(strict=False)``, także na `main`.

Klucz to id testu pytest (``tests/test_x.py::test_y[parametry]``), a wpis to issue ``Flaky test: <test>`` i dzień, do którego
kwarantanna trwa. Test w kwarantannie nie czerwieni ``Required CI status``, ale ``tests/conftest.py`` daje mu w junit
własność ``kwarantanna``, z której jego wynik trafia do artefaktu ``kwarantanna-*`` runu `main`, a ``tools/wydanie.py``
nie wydaje commitu, na którym padł albo nie ma zapisu przejścia. Powód porażki testu z kwarantanny jest tylko w logu
zadania pytest, w linii ``KWARANTANNA |`` podsumowania z ``tests/conftest.py``, bo junit i artefakt mają sam wynik.
Reguły wpisu sprawdza ``tests/test_kwarantanna.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Kwarantanna:
    issue: int  # numer issue ``Flaky test: <test>`` w tym repozytorium
    do: date  # ostatni dzień kwarantanny, najwyżej 7 dni od dziś


KWARANTANNA: dict[str, Kwarantanna] = {
    # Windows: przebieg bez awarii eksploratora Wyceny w efenix zatrzymał się między „Załaduj do zlecenia” a pierwszą
    # ilością; przyczyna nieustalona, a BEZ_AWARII nazywa odtąd Zatrzymanie i ostatnie żądanie (#1008). Od #1009 dalej
    # pada na Windows (7 z 430 przebiegów na `main` do 11.11), a powód pokaże dopiero linia KWARANTANNA | w logu zadania.
    "tests/test_centrum_logi_uruchomienia.py::test_odmowa_zaladuj_do_zlecenia_zabity_proces_przy_niej_i_wznowienie_po_nich"
    "_trzymaja_niezmienniki_bez_znanych_ustalen": Kwarantanna(1008, date(2026, 11, 18)),
    # Windows 3.14: dziecko ze sprawdzeniem przeplotów nic nie wypisało przez 100 s, a straż STALL_SECONDS nie zgłosiła
    # LUKI MODELU; 600 przebiegów sondy na runnerach bez zawieszenia, przyczyna nieustalona (#1239).
    "tests/test_jedno_uruchomienie_naraz.py::test_watek_modelu_czekajacy_poza_modelem_konczy_sprawdzenie_luka_modelu_z_nazwa"
    "_i_krokiem": Kwarantanna(1239, date(2026, 11, 16)),
}
