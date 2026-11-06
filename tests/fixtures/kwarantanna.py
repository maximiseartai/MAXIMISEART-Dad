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
    # Windows: Zatrzymanie dla taty bez części strony zamiast strony 404 zlecenia; przyczyna nieustalona (#972).
    "tests/test_centrum_logi_uruchomienia.py::test_logi_zatrzymania_okna_efenix_maja_przyczyne_wiersz_miejsce_w_przebiegu"
    "_i_slad_zlecen_sprzed_niego[D-strona-bledu-http-404]": Kwarantanna(972, date(2026, 11, 12)),
    # Windows: przebieg bez awarii eksploratora Wyceny w efenix zatrzymał się między „Załaduj do zlecenia” a pierwszą
    # ilością; przyczyna nieustalona, a BEZ_AWARII nazywa odtąd Zatrzymanie i ostatnie żądanie (#1008).
    "tests/test_centrum_logi_uruchomienia.py::test_odmowa_zaladuj_do_zlecenia_zabity_proces_przy_niej_i_wznowienie_po_nich"
    "_trzymaja_niezmienniki_bez_znanych_ustalen": Kwarantanna(1008, date(2026, 11, 13)),
}
