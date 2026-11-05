"""Reguła danych (ADR 0025) na interfejsie ``client_data``: które wartości strażnik zna i jak je maskuje.

Strażnika wołają cztery wysyłki Centrum (Logi, Zgłoszenie, Kontrola ilości, Uwaga taty), więc macierz reguły jest tu raz,
a każda wysyłka ma swój test przez HTTP API. Położenie wartości w tekście, wielkość liter i znaki między jej słowami
sprawdzają własności w ``test_wlasnosci_dopasowania_tekstu.py``. Wartości są syntetyczne.
"""

from __future__ import annotations

from dataclasses import replace

from hypothesis import given, settings
from hypothesis import strategies as st
import pytest

from rozliczenia.client_data import (
    MIN_VALUE,
    CellPlace,
    CopiedCell,
    ForbiddenColumn,
    ForbiddenValues,
    Guarded,
    free_text,
)
from tests.fixtures.formy_telefonu import CELL_FORMS, PhoneForm

ADDRESS_NOTE = "Reguła danych: zamaskowano wartość kolumny ADRES w: tekst."
ORANGE_NOTE = "Reguła danych: zamaskowano wartość kolumny NUMER UMOWY/ZLECENIA ORANGE w: tekst."


def test_wartosc_krotsza_niz_piec_znakow_nie_jest_zakazana_a_piec_znakow_juz_jest() -> None:
    forbidden = ForbiddenValues()
    forbidden.remember_value(ForbiddenColumn.ADDRESS, "Lipa")
    forbidden.remember_value(ForbiddenColumn.ADDRESS, " „Lipno")

    guarded = forbidden.guard("Lipa kwitnie przy drodze na Lipno", "tekst")

    assert MIN_VALUE == 5
    assert guarded == Guarded("Lipa kwitnie przy drodze na [adres]", (ADDRESS_NOTE,))


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

    assert guarded == Guarded("umowa [numer Orange] aktywna", (ORANGE_NOTE,))


def test_wartosc_zapamietana_pod_dwiema_kolumnami_jest_maskowana_jak_pierwsza() -> None:
    forbidden = ForbiddenValues()
    forbidden.remember_value(ForbiddenColumn.ORANGE, "SYN-48012")
    forbidden.remember_value(ForbiddenColumn.ADDRESS, "syn 48012")

    assert forbidden.guard("umowa SYN 48012", "tekst") == Guarded("umowa [numer Orange]", (ORANGE_NOTE,))


def test_kazda_praca_centrum_ma_wlasna_pamiec_zakazanych_wartosci() -> None:
    first, second = ForbiddenValues(), ForbiddenValues()
    first.remember_value(ForbiddenColumn.ADDRESS, "Syntetyczna Lipowa 5")

    assert second.guard("Syntetyczna Lipowa 5", "tekst") == Guarded("Syntetyczna Lipowa 5", ())


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
        guarded, expected = forbidden.guard(form.value, "komórka"), Guarded(text, ())
        in_text = forbidden.guard(f"oddzwonić {form.value}, potem", "tekst")
        assert in_text == Guarded(f"oddzwonić {text}, potem", ()), "ta sama forma w wolnym tekście"
    else:
        guarded = forbidden.guard_number(form.value, "komórka")
        expected = None if form.masked is None else Guarded(form.masked, ())

    assert guarded == expected, form.why


# --- Wartość z wiersza z dwoma położeniami (opcja 3, #913, ADR 0025) ------------------------------------------------
# Wiersz Rejestru zleceń, który może stać przesunięty, daje pamięci wartości z obu położeń z miejscem komórki. Strażnik
# maskuje taką wartość w jej komórce Kopii wejścia (w tej samej wersji pliku), pod ADRES i NUMER UMOWY, w wolnym tekście
# (każdy tekst poza komórką Kopii i komórka Kopii pod nagłówkiem innym niż zwykła kolumna) i w innym pliku, ale nie w
# zwykłej kolumnie innego wiersza pliku o tej samej nazwie.
REGISTER = "ZLECENIA INTERMAX OD 08_11_2021.xlsx"
READ = "a" * 64
"""Skrót bajtów przeczytanej wersji Rejestru."""
SAVED = "b" * 64
"""Skrót bajtów wersji, którą zapisało Uporządkowanie."""
SECOND = CellPlace(REGISTER, READ, "ZLECENIA", 12, 9)
"""``NUMER ZL.`` (I) wiersza z dwoma położeniami: w położeniu przesuniętym stoi tu ``NUMER UMOWY``."""
PLACED = "ZL-SYN-48012"
OTHER_ROW = replace(SECOND, row=13)
SCOPE = {
    "własna_komórka": (SECOND, "NUMER ZL.", True),
    "numer_zl_innego_wiersza": (OTHER_ROW, "NUMER ZL.", False),
    "urzadzenia_innego_wiersza": (replace(OTHER_ROW, column=7), "URZĄDZENIA", False),
    "data_innego_wiersza": (replace(OTHER_ROW, column=3), "DATA GODZ. POCZ.", False),
    "data_w_pliku_zbiorczym_pod_naglowkiem_docelowym": (replace(OTHER_ROW, column=3), "DATA", False),
    "wykonawca_innego_wiersza": (replace(OTHER_ROW, column=10), "WYKONAWCA", False),
    "adres_innego_wiersza": (replace(OTHER_ROW, column=5), "ADRES", True),
    "numer_umowy_innego_wiersza": (replace(OTHER_ROW, column=11), "NUMER UMOWY", True),
    "numer_umowy_orange_innego_wiersza": (replace(OTHER_ROW, column=11), "NUMER UMOWY/ZLECENIA ORANGE", True),
    "czynnosci_zrealizowane": (replace(OTHER_ROW, column=13), "CZYNNOŚCI ZREALIZOWANE", True),
    "zwrot": (replace(OTHER_ROW, column=14), "ZWROT", True),
    "uwagi": (replace(OTHER_ROW, column=15), "UWAGI", True),
    "akcje": (replace(OTHER_ROW, column=2), "AKCJE", True),
    "kolumna_bez_naglowka": (replace(OTHER_ROW, column=1), None, True),
    "nieznany_naglowek": (replace(OTHER_ROW, column=20), "NR SERYJNY", True),
    "inny_plik": (replace(OTHER_ROW, file="Rozliczenie 08_14_09_2026 - zbiorcze.xlsx"), "NUMER ZL.", True),
    "ta_sama_komorka_w_innej_wersji_pliku": (replace(SECOND, content=SAVED), "NUMER ZL.", False),
}


@pytest.mark.parametrize(("place", "header", "masked"), SCOPE.values(), ids=SCOPE.keys())
def test_wartosc_z_wiersza_z_dwoma_polozeniami_jest_maskowana_tylko_w_swojej_komorce_zakazanych_kolumnach_wolnym_tekscie_i_innym_pliku(
    place: CellPlace, header: str | None, masked: bool
) -> None:
    forbidden = ForbiddenValues()
    forbidden.remember_value(ForbiddenColumn.ORANGE, PLACED, SECOND)

    guarded = forbidden.guard(f"nr {PLACED}", "komórka", CopiedCell(place, header))

    assert guarded.text == ("nr [numer Orange]" if masked else f"nr {PLACED}")
    assert forbidden.guard(f"tata pisze {PLACED}", "Uwaga taty") == Guarded(
        "tata pisze [numer Orange]",
        ("Reguła danych: zamaskowano wartość kolumny NUMER UMOWY/ZLECENIA ORANGE w: Uwaga taty.",),
    ), "każdy tekst poza komórką Kopii to wolny tekst"


@pytest.mark.parametrize("first_from_two_positions", [True, False], ids=["najpierw_z_miejscem", "najpierw_wszedzie"])
def test_wartosc_poznana_takze_z_wiersza_z_jednym_polozeniem_jest_maskowana_wszedzie(first_from_two_positions: bool) -> None:
    forbidden = ForbiddenValues()
    learnt = [(ForbiddenColumn.ORANGE, PLACED, SECOND), (ForbiddenColumn.ORANGE, PLACED, None)]
    for column, value, place in learnt if first_from_two_positions else reversed(learnt):
        forbidden.remember_value(column, value, place)

    assert forbidden.guard(PLACED, "komórka", CopiedCell(OTHER_ROW, "NUMER ZL.")).text == "[numer Orange]"


def test_liczba_z_wiersza_z_dwoma_polozeniami_jest_maskowana_w_swojej_komorce_a_w_innym_wierszu_nie() -> None:
    forbidden = ForbiddenValues()
    forbidden.remember_value(ForbiddenColumn.ORANGE, 4801234567, SECOND)

    own = forbidden.guard_number(4801234567, "komórka", CopiedCell(SECOND, "NUMER ZL."))
    other = forbidden.guard_number(4801234567, "komórka", CopiedCell(OTHER_ROW, "NUMER ZL."))

    assert (own is not None and own.text, other) == ("[numer Orange]", None)


def test_uporzadkowanie_przenosi_wlasna_komorke_do_wiersza_dnia_tylko_w_zapisanej_wersji_pliku() -> None:
    """Wiersz 12, przesunięty, idzie do wiersza dnia 30 dwie kolumny w prawo: w zapisanej wersji jego komórka jest w
    wierszu 30, a w przeczytanej wersji wiersz 30 to inny wiersz."""

    forbidden = ForbiddenValues()
    forbidden.remember_value(ForbiddenColumn.ORANGE, PLACED, SECOND)

    forbidden.moved(READ, SAVED, "ZLECENIA", {12: (30, 2), 13: (31, 0)})

    moved = replace(SECOND, content=SAVED, row=30, column=11)
    cells = {"zapisana": moved, "przeczytana": replace(moved, content=READ), "zapisana_bez_przesuniecia": replace(moved, column=9)}
    assert {name: forbidden.guard(PLACED, "komórka", CopiedCell(place, "NUMER ZL.")).text for name, place in cells.items()} == {
        "zapisana": "[numer Orange]",
        "przeczytana": PLACED,
        "zapisana_bez_przesuniecia": PLACED,
    }
    assert forbidden.guard(PLACED, "komórka", CopiedCell(SECOND, "NUMER ZL.")).text == "[numer Orange]"


@settings(derandomize=True, database=None, deadline=None, max_examples=60)
@given(
    header=st.sampled_from(["NUMER ZL.", "URZĄDZENIA", "WYKONAWCA", "DATA GODZ. POCZ."]),
    upper=st.booleans(),
    spaces=st.sampled_from(["", " ", "  ", "\u00a0"]),
    suffix=st.sampled_from(["", " DODATKOWE", "X"]),
)
def test_zwykla_kolumna_to_naglowek_po_normalizacji_a_dluzszy_naglowek_to_wolny_tekst(
    header: str, upper: bool, spaces: str, suffix: str
) -> None:
    """Nagłówek zwykłej kolumny z pliku taty w dowolnej wielkości liter i z odstępami na brzegach to ta sama kolumna, a
    nagłówek z dopiskiem albo sklejony z innym słowem nie, więc w nim wartość z miejscem jest zamaskowana."""

    written = spaces + (header.upper() if upper else header.lower()) + suffix + spaces
    forbidden = ForbiddenValues()
    forbidden.remember_value(ForbiddenColumn.ORANGE, PLACED, SECOND)

    guarded = forbidden.guard(PLACED, "komórka", CopiedCell(OTHER_ROW, written))

    assert guarded.text == ("[numer Orange]" if suffix else PLACED)

