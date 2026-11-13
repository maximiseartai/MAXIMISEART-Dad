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

from rozliczenia.client_data import MIN_VALUE, ForbiddenColumn, ForbiddenValues, Guarded, free_text, tool
from tests.fixtures.formy_telefonu import CELL_FORMS, PhoneForm
from tests.fixtures.wyciek import zawiera_wartosc
from tests.fixtures.znane_luki import assert_znane_luki, ruff_i_mypy, wymaga_ruff_i_mypy, zapisz

ROOT = Path(__file__).resolve().parents[1]

ADDRESS_NOTE = "Reguła danych: zamaskowano wartość kolumny ADRES w: tekst."
ORANGE_NOTE = "Reguła danych: zamaskowano wartość kolumny NUMER UMOWY/ZLECENIA ORANGE w: tekst."


def test_wartosc_krotsza_niz_piec_znakow_nie_jest_zakazana_a_piec_znakow_juz_jest() -> None:
    forbidden = ForbiddenValues()
    forbidden.remember_value(ForbiddenColumn.ADDRESS, "Lipa")
    forbidden.remember_value(ForbiddenColumn.ADDRESS, " „Lipno")

    guarded = forbidden.guard("Lipa kwitnie przy drodze na Lipno", "tekst")

    assert MIN_VALUE == 5
    assert guarded == Guarded(tool("Lipa kwitnie przy drodze na [adres]"), (ADDRESS_NOTE,))


def test_z_dwoch_wartosci_od_tego_samego_slowa_maskowana_jest_cala_dluzsza() -> None:
    forbidden = ForbiddenValues()
    forbidden.remember_value(ForbiddenColumn.ADDRESS, "Syntetyczna Lipowa 5")
    forbidden.remember_value(ForbiddenColumn.ADDRESS, "Syntetyczna Lipowa 5 m 7")

    longer = forbidden.guard("klient Syntetyczna Lipowa 5 m 7 dzwonić", "tekst")
    shorter = forbidden.guard("klient Syntetyczna Lipowa 5, dzwonić", "tekst")

    assert (longer.text, shorter.text) == ("klient [adres] dzwonić", "klient [adres], dzwonić")


def test_numer_orange_ktory_excel_czyta_jako_liczbe_ulamkowa_jest_zamaskowany_w_zapisie_cyfr() -> None:
    forbidden = ForbiddenValues()
    forbidden.remember_value(ForbiddenColumn.ORANGE, 4801234567.0)

    guarded = forbidden.guard("umowa 4801234567 aktywna", "tekst")

    assert guarded == Guarded(tool("umowa [numer Orange] aktywna"), (ORANGE_NOTE,))


def test_liczba_z_czescia_ulamkowa_z_zakazanej_kolumny_jest_zamaskowana_razem_z_czescia_ulamkowa() -> None:
    # Tylko liczba całkowita zapisana jako ułamek traci część po przecinku (``shown``); inna zostaje w zapisie Excela.
    forbidden = ForbiddenValues()
    forbidden.remember_value(ForbiddenColumn.ORANGE, 48012.75)

    guarded = forbidden.guard("umowa 48012.75 aktywna", "tekst")

    assert guarded == Guarded(tool("umowa [numer Orange] aktywna"), (ORANGE_NOTE,))


def test_godzina_z_zakazanej_kolumny_nie_jest_zakazana_wartoscia() -> None:
    # Godzina, jak data, nie wskazuje klienta, a zamaskowałaby każdą tę samą godzinę w Logach.
    forbidden = ForbiddenValues()
    forbidden.remember_value(ForbiddenColumn.ADDRESS, time(8, 30))

    assert forbidden.guard("przyjazd 08:30:00 rano", "tekst") == Guarded(tool("przyjazd 08:30:00 rano"), ())


def test_wartosc_zapamietana_pod_dwiema_kolumnami_jest_maskowana_jak_pierwsza() -> None:
    forbidden = ForbiddenValues()
    forbidden.remember_value(ForbiddenColumn.ORANGE, "SYN-48012")
    forbidden.remember_value(ForbiddenColumn.ADDRESS, "syn 48012")

    assert forbidden.guard("umowa SYN 48012", "tekst") == Guarded(tool("umowa [numer Orange]"), (ORANGE_NOTE,))


def test_kazda_praca_centrum_ma_wlasna_pamiec_zakazanych_wartosci() -> None:
    first, second = ForbiddenValues(), ForbiddenValues()
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

    forbidden = ForbiddenValues()
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


# Drogi do strażnika z pamięcią, która nie jest pamięcią pracy Centrum (przegląd #1660, W2) → zgłoszenie mypy, które
# każdą odrzuca w nowym module ``src/rozliczenia/centrum``.
DROGI_DO_PUSTEJ_PAMIECI: Final = {
    "pamięć świeżego uchwytu plików taty": (
        """from rozliczenia.dad_files import DadFiles


def wysylka(komorka: str) -> str:
    return DadFiles().forbidden.guard(komorka, "treść").text
""",
        'Item "None" of "ForbiddenValues | None" has no attribute "guard"',
    ),
    "pamięć kontekstu Uruchomienia bez Centrum": (
        """from rozliczenia.run_context import RunContext


def wysylka(komorka: str) -> str:
    return RunContext().files.forbidden.guard(komorka, "treść").text
""",
        'Item "None" of "ForbiddenValues | None" has no attribute "guard"',
    ),
    "pamięć świeżej pracy Centrum": (
        """from pathlib import Path

from rozliczenia.centrum.clock import Clock
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.work import CentrumWork


def wysylka(komorka: str, log: CentrumLog, zegar: Clock) -> str:
    return CentrumWork(Path("config"), log, zegar, print).forbidden.guard(komorka, "treść").text
""",
        'Missing positional argument "forbidden"',
    ),
}

# Znane luki pustej pamięci (tests/fixtures/znane_luki.py): postaci, które dają strażnika bez pamięci pracy Centrum, a
# mypy i ruff ich nie łapią.
ZNANE_LUKI_PAMIECI: Final = {
    "konstruktor ForbiddenValues": """from rozliczenia.client_data import ForbiddenValues


def wysylka(komorka: str) -> str:
    return ForbiddenValues().guard(komorka, "treść").text
""",
    "cast pamięci uchwytu": """from typing import cast

from rozliczenia.client_data import ForbiddenValues
from rozliczenia.dad_files import DadFiles


def wysylka(komorka: str) -> str:
    return cast(ForbiddenValues, DadFiles().forbidden).guard(komorka, "treść").text
""",
}


@wymaga_ruff_i_mypy
def test_straznik_z_pamiecia_spoza_pracy_centrum_nie_przechodzi_mypy_a_znane_luki_przechodza(tmp_path: Path) -> None:
    probki = {opis: kod for opis, (kod, _) in DROGI_DO_PUSTEJ_PAMIECI.items()} | ZNANE_LUKI_PAMIECI
    zgloszenia = ruff_i_mypy(zapisz(probki, tmp_path), sonda=ROOT / "src" / "rozliczenia" / "centrum" / "sonda_pamieci.py")

    assert {opis: zgloszenia[opis] for opis, (_, odrzucenie) in DROGI_DO_PUSTEJ_PAMIECI.items() if not any(odrzucenie in z for z in zgloszenia[opis])} == {}
    assert_znane_luki({opis: zgloszenia[opis] for opis in ZNANE_LUKI_PAMIECI}, "tests/test_regula_danych.py")
