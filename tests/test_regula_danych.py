"""Reguła danych (ADR 0025) na interfejsie ``client_data``: które wartości strażnik zna i jak je maskuje.

Strażnika wołają cztery wysyłki Centrum (Logi, Zgłoszenie, Kontrola ilości, Uwaga taty), więc macierz reguły jest tu raz,
a każda wysyłka ma swój test przez HTTP API. Położenie wartości w tekście, wielkość liter i znaki między jej słowami
sprawdzają własności w ``test_wlasnosci_dopasowania_tekstu.py``. Wartości są syntetyczne.
"""

from __future__ import annotations

from datetime import time
from pathlib import Path
from typing import Final

import pytest

from rozliczenia.client_data import MIN_VALUE, ForbiddenColumn, Guarded, empty_memory, free_text, tool
from tests.fixtures.formy_telefonu import CELL_FORMS, PhoneForm
from tests.fixtures.wyciek import zawiera_wartosc
from tests.fixtures.znane_luki import assert_znane_luki, ruff_i_mypy, wymaga_ruff_i_mypy, zapisz

ROOT = Path(__file__).resolve().parents[1]

ADDRESS_NOTE = "Reguła danych: zamaskowano wartość kolumny ADRES w: tekst."
ORANGE_NOTE = "Reguła danych: zamaskowano wartość kolumny NUMER UMOWY/ZLECENIA ORANGE w: tekst."


def test_wartosc_krotsza_niz_piec_znakow_nie_jest_zakazana_a_piec_znakow_juz_jest() -> None:
    forbidden = empty_memory()
    forbidden.remember_value(ForbiddenColumn.ADDRESS, "Lipa")
    forbidden.remember_value(ForbiddenColumn.ADDRESS, " „Lipno")

    guarded = forbidden.guard("Lipa kwitnie przy drodze na Lipno", "tekst")

    assert MIN_VALUE == 5
    assert guarded == Guarded(tool("Lipa kwitnie przy drodze na [adres]"), (ADDRESS_NOTE,))


def test_z_dwoch_wartosci_od_tego_samego_slowa_maskowana_jest_cala_dluzsza() -> None:
    forbidden = empty_memory()
    forbidden.remember_value(ForbiddenColumn.ADDRESS, "Syntetyczna Lipowa 5")
    forbidden.remember_value(ForbiddenColumn.ADDRESS, "Syntetyczna Lipowa 5 m 7")

    longer = forbidden.guard("klient Syntetyczna Lipowa 5 m 7 dzwonić", "tekst")
    shorter = forbidden.guard("klient Syntetyczna Lipowa 5, dzwonić", "tekst")

    assert (longer.text, shorter.text) == ("klient [adres] dzwonić", "klient [adres], dzwonić")


def test_numer_orange_ktory_excel_czyta_jako_liczbe_ulamkowa_jest_zamaskowany_w_zapisie_cyfr() -> None:
    forbidden = empty_memory()
    forbidden.remember_value(ForbiddenColumn.ORANGE, 4801234567.0)

    guarded = forbidden.guard("umowa 4801234567 aktywna", "tekst")

    assert guarded == Guarded(tool("umowa [numer Orange] aktywna"), (ORANGE_NOTE,))


def test_liczba_z_czescia_ulamkowa_z_zakazanej_kolumny_jest_zamaskowana_razem_z_czescia_ulamkowa() -> None:
    # Tylko liczba całkowita zapisana jako ułamek traci część po przecinku (``shown``); inna zostaje w zapisie Excela.
    forbidden = empty_memory()
    forbidden.remember_value(ForbiddenColumn.ORANGE, 48012.75)

    guarded = forbidden.guard("umowa 48012.75 aktywna", "tekst")

    assert guarded == Guarded(tool("umowa [numer Orange] aktywna"), (ORANGE_NOTE,))


def test_godzina_z_zakazanej_kolumny_nie_jest_zakazana_wartoscia() -> None:
    # Godzina, jak data, nie wskazuje klienta, a zamaskowałaby każdą tę samą godzinę w Logach.
    forbidden = empty_memory()
    forbidden.remember_value(ForbiddenColumn.ADDRESS, time(8, 30))

    assert forbidden.guard("przyjazd 08:30:00 rano", "tekst") == Guarded(tool("przyjazd 08:30:00 rano"), ())


def test_wartosc_zapamietana_pod_dwiema_kolumnami_jest_maskowana_jak_pierwsza() -> None:
    forbidden = empty_memory()
    forbidden.remember_value(ForbiddenColumn.ORANGE, "SYN-48012")
    forbidden.remember_value(ForbiddenColumn.ADDRESS, "syn 48012")

    assert forbidden.guard("umowa SYN 48012", "tekst") == Guarded(tool("umowa [numer Orange]"), (ORANGE_NOTE,))


def test_kazda_praca_centrum_ma_wlasna_pamiec_zakazanych_wartosci() -> None:
    first, second = empty_memory(), empty_memory()
    first.remember_value(ForbiddenColumn.ADDRESS, "Syntetyczna Lipowa 5")

    assert second.guard("Syntetyczna Lipowa 5", "tekst") == Guarded(tool("Syntetyczna Lipowa 5"), ())


def test_wyrocznia_wycieku_w_testach_widzi_numer_zlecenia_tak_jak_straznik() -> None:
    texts = ("ślad d41f94001ab0", "2026-11-12T10:00:00.394001", 'zlecenie "94001"', "#94001, wiersz 18")

    assert [zawiera_wartosc(text, "#94001") for text in texts] == [False, False, True, True]


def test_wyrocznia_wycieku_w_testach_nie_przyjmuje_numeru_ktorego_straznik_nie_szuka() -> None:
    with pytest.raises(ValueError, match="krótszej niż 5 znaków"):
        zawiera_wartosc("#9401, wiersz 18", "#9401")


def test_numer_zlecenia_po_krzyzyku_nie_jest_telefonem_a_te_same_cyfry_bez_krzyzyka_sa() -> None:
    # NUMER ZL. to „#” i numer, który może wyjść (ADR 0025); dziś ma 8 cyfr, a 9 cyfr to kształt telefonu.
    assert free_text("zlecenie #123456789 zrobione") == "zlecenie #123456789 zrobione"
    assert free_text("zlecenie 123456789 zrobione, oddzwonić +48123456789") == "zlecenie [telefon] zrobione, oddzwonić [telefon]"


@pytest.mark.parametrize("form", CELL_FORMS, ids=[form.form for form in CELL_FORMS])
def test_kazda_forma_telefonu_z_tabeli_adr_0025_wychodzi_tak_jak_mowi_tabela(form: PhoneForm) -> None:
    """Telefon jest ``[telefon]`` w komórce z tekstem, w wolnym tekście i w komórce, którą Excel trzyma jako liczbę
    (także z ``+48`` albo ``0048`` zgubionym przez format General), znane granice wychodzą bez maski, a ilość, kwota,
    ``NUMER ZL.`` i data wychodzą bez zmian; uwagi technicznej telefon nie daje (ADR 0025)."""

    forbidden = empty_memory()
    guarded: Guarded | None
    expected: Guarded | None
    if isinstance(form.value, str):
        text = form.value if form.masked is None else form.masked
        guarded, expected = forbidden.guard(form.value, "komórka"), Guarded(tool(text), ())
        in_text = forbidden.guard(f"oddzwonić {form.value}, potem", "tekst")
        assert in_text == Guarded(tool(f"oddzwonić {text}, potem"), ()), "ta sama forma w wolnym tekście"
    else:
        guarded = forbidden.guard_number(form.value, "komórka")
        expected = None if form.masked is None else Guarded(tool(form.masked), ())

    assert guarded == expected, form.why


_POST = """\
from rozliczenia.centrum.outbox import NewIssue, Post

"""

# Znane luki jednej drogi wyjścia (tests/fixtures/znane_luki.py): opis postaci → nowy producent w src/rozliczenia/centrum,
# który daje kolejce wartość z komórki taty bez strażnika pracy Centrum, a przechodzi przez mypy i ruff z konfiguracją src/.
ZNANE_LUKI: Final = {
    "cast na Outgoing": _POST
    + """from typing import cast

from rozliczenia.client_data import Outgoing


def wysylka(komorka: str) -> Post:
    return Post(NewIssue("uwaga-taty", "Uwaga"), None, "r", None, (cast(Outgoing, komorka),))
""",
    "wartość typu Any": _POST
    + """from typing import Any


def wysylka(wiersz: dict[str, Any]) -> Post:
    return Post(NewIssue("uwaga-taty", "Uwaga"), None, "r", None, (wiersz["ADRES"],))
""",
    "str.__new__ z klasą Outgoing": _POST
    + """from rozliczenia.client_data import Outgoing


def wysylka(komorka: str) -> Post:
    return Post(NewIssue("uwaga-taty", "Uwaga"), None, "r", None, (str.__new__(Outgoing, komorka),))
""",
    "dowód z getattr modułu": _POST
    + """from rozliczenia import client_data


def wysylka(komorka: str) -> Post:
    tekst = client_data.Outgoing(komorka, getattr(client_data, "_PASSED"))
    return Post(NewIssue("uwaga-taty", "Uwaga"), None, "r", None, (tekst,))
""",
    "tool przez importlib": _POST
    + """import importlib


def wysylka(komorka: str) -> Post:
    tekst = importlib.import_module("rozliczenia.client_data").tool(komorka)
    return Post(NewIssue("uwaga-taty", "Uwaga"), None, "r", None, (tekst,))
""",
    "tool zaimportowane z noqa": _POST
    + """from rozliczenia.client_data import tool  # noqa: TID251


def wysylka(komorka: str) -> Post:
    return Post(NewIssue("uwaga-taty", "Uwaga"), None, "r", None, (tool(komorka),))
""",
    "goły napis z type: ignore": _POST
    + """def wysylka(komorka: str) -> Post:
    return Post(NewIssue("uwaga-taty", "Uwaga"), None, "r", None, (komorka,))  # type: ignore[arg-type]
""",
    "tytuł celu z komórki": _POST
    + """from rozliczenia.client_data import ForbiddenValues


def wysylka(komorka: str, pamiec: ForbiddenValues) -> Post:
    tekst = pamiec.guard("Uwaga", "treść").text
    return Post(NewIssue("uwaga-taty", komorka), None, "r", None, (tekst,))
""",
    "plik Archiwum z komórki": """\
from rozliczenia.centrum.outbox import ArchiveFile, PeriodThread, Post
from rozliczenia.client_data import ForbiddenValues


def wysylka(komorka: str, pamiec: ForbiddenValues) -> Post:
    cel = PeriodThread("logi-uruchomienia", "- Logi", "reuse", "Logi")
    plik = ArchiveFile("logi-08_14_09_2026", "Logi", "Opis", "logi.json", komorka)
    return Post(cel, "08_14_09_2026", "r", None, (pamiec.guard("Logi", "treść").text,), plik)
""",
}


@wymaga_ruff_i_mypy
def test_znane_luki_jednej_drogi_wyjscia_przechodza_przez_mypy_i_ruff(tmp_path: Path) -> None:
    zgloszenia = ruff_i_mypy(zapisz(ZNANE_LUKI, tmp_path), sonda=ROOT / "src" / "rozliczenia" / "centrum" / "sonda_luki.py")

    assert_znane_luki(zgloszenia, "tests/test_regula_danych.py")
