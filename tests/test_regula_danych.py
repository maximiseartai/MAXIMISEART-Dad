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

from rozliczenia.client_data import MIN_VALUE, ForbiddenColumn, ForbiddenValues, Guarded, empty_memory, free_text, tool
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


def wysylka(komorka: str, cel: NewIssue) -> Post:
    return Post(cel, None, "r", None, (cast(Outgoing, komorka),))
""",
    "wartość typu Any": _POST
    + """from typing import Any


def wysylka(wiersz: dict[str, Any], cel: NewIssue) -> Post:
    return Post(cel, None, "r", None, (wiersz["ADRES"],))
""",
    "str.__new__ z klasą Outgoing": _POST
    + """from rozliczenia.client_data import Outgoing


def wysylka(komorka: str, cel: NewIssue) -> Post:
    return Post(cel, None, "r", None, (str.__new__(Outgoing, komorka),))
""",
    "dowód z getattr modułu": _POST
    + """from rozliczenia import client_data


def wysylka(komorka: str, cel: NewIssue) -> Post:
    tekst = client_data.Outgoing(komorka, getattr(client_data, "_PASSED"))
    return Post(cel, None, "r", None, (tekst,))
""",
    "tool przez importlib": _POST
    + """import importlib


def wysylka(komorka: str, cel: NewIssue) -> Post:
    tekst = importlib.import_module("rozliczenia.client_data").tool(komorka)
    return Post(cel, None, "r", None, (tekst,))
""",
    "tool zaimportowane z noqa": _POST
    + """from rozliczenia.client_data import tool  # noqa: TID251


def wysylka(komorka: str, cel: NewIssue) -> Post:
    return Post(cel, None, "r", None, (tool(komorka),))
""",
    "goły napis z type: ignore": _POST
    + """def wysylka(komorka: str, cel: NewIssue) -> Post:
    return Post(cel, None, "r", None, (komorka,))  # type: ignore[arg-type]
""",
    "object.__setattr__ na częściach gotowej wysyłki": """from rozliczenia.centrum.outbox import Post


def wysylka(komorka: str, post: Post) -> Post:
    object.__setattr__(post, "parts", (komorka,))
    return post
""",
}

_CEL: Final = """\
from rozliczenia.centrum.outbox import NewIssue, OpenIssue, PeriodThread, Post
from rozliczenia.client_data import ForbiddenValues


def wysylka(komorka: str, pamiec: ForbiddenValues) -> Post:
    tekst = pamiec.guard("Uwaga", "treść").text
    return Post({cel}, None, "r", None, (tekst,))
"""
_GOTOWY_CEL: Final = "from rozliczenia.centrum.outbox import NewIssue, Post\n\n\n"

# Drogi do pola tekstowego celu wysyłki z wartością z komórki taty bez strażnika (każde pole każdego celu i ich formy
# siostrzane) → zgłoszenie mypy albo ruff, które każdą odrzuca w nowym module ``src/rozliczenia/centrum``.
DROGI_DO_CELU: Final = {
    **{
        f"{cel.split('(')[0]} {pole} z komórki": (_CEL.format(cel=cel), 'has incompatible type "str"; expected "Outgoing"')
        for pole, cel in (
            ("title", 'NewIssue("uwaga-taty", komorka)'),
            ("line", 'PeriodThread("kontrola-ilosci", komorka, "new_issue", tekst)'),
            ("title", 'PeriodThread("kontrola-ilosci", tekst, "new_issue", komorka)'),
            ("line", 'OpenIssue("zgloszenie", komorka, tekst, tekst)'),
            ("title", 'OpenIssue("zgloszenie", tekst, komorka, tekst)'),
            ("again", 'OpenIssue("zgloszenie", tekst, tekst, komorka)'),
        )
    },
    "podklasa celu": (_GOTOWY_CEL + "class Cel(NewIssue):\n    pass\n", 'Cannot inherit from final class "NewIssue"'),
    "własny cel": (
        _GOTOWY_CEL
        + """from dataclasses import dataclass

from rozliczenia.client_data import Outgoing


@dataclass(frozen=True)
class Cel:
    label: str
    title: str


def wysylka(komorka: str, tekst: Outgoing) -> Post:
    return Post(Cel("uwaga-taty", komorka), None, "r", None, (tekst,))
""",
        'Argument 1 to "Post" has incompatible type "Cel"',
    ),
    "dataclasses.replace celu": (
        _GOTOWY_CEL
        + """import dataclasses


def wysylka(komorka: str, cel: NewIssue) -> NewIssue:
    return dataclasses.replace(cel, title=komorka)
""",
        'Argument "title" to "replace" of "NewIssue" has incompatible type "str"',
    ),
    "__replace__ celu": (
        _GOTOWY_CEL + 'def wysylka(komorka: str, cel: NewIssue) -> NewIssue:\n    return cel.__replace__(title=komorka)\n',
        'Argument "title" to "__replace__" of "NewIssue" has incompatible type "str"',
    ),
    "copy.replace celu": (
        _GOTOWY_CEL + 'import copy\n\n\ndef wysylka(komorka: str, cel: NewIssue) -> NewIssue:\n    return copy.replace(cel, title=komorka)\n',
        "`copy.replace` is banned",
    ),
    "tytuł Uwagi taty z komórki": (
        """from rozliczenia.centrum.case_delivery import note_post
from rozliczenia.centrum.outbox import Post
from rozliczenia.client_data import Outgoing


def wysylka(komorka: str, tekst: Outgoing) -> Post:
    return note_post("n", komorka, tekst, logs_on_the_way=False)
""",
        'Argument 2 to "note_post" has incompatible type "str"; expected "Outgoing"',
    ),
    "tytuł Zgłoszenia z komórki": (
        """from rozliczenia.centrum.outbox import OpenIssue
from rozliczenia.centrum.reports import report_target


def wysylka(komorka: str) -> OpenIssue:
    return report_target("0123456789abcdef", komorka)
""",
        'Argument 2 to "report_target" has incompatible type "str"; expected "Outgoing"',
    ),
}

# Znane luki celu wysyłki (tests/fixtures/znane_luki.py): postaci, które dają polu tekstowemu celu wartość z komórki taty
# bez strażnika, a mypy i ruff ich nie łapią.
ZNANE_LUKI_CELU: Final = {
    "object.__setattr__ na gotowym celu": _GOTOWY_CEL
    + """def wysylka(komorka: str, cel: NewIssue, post: Post) -> Post:
    object.__setattr__(cel, "title", komorka)
    return Post(cel, None, "r", None, post.parts)
""",
    "zapis do __dict__ gotowego celu": _GOTOWY_CEL
    + """def wysylka(komorka: str, cel: NewIssue, post: Post) -> Post:
    cel.__dict__["title"] = komorka
    return Post(cel, None, "r", None, post.parts)
""",
    "cast na Outgoing w tytule celu": _GOTOWY_CEL
    + """from typing import cast

from rozliczenia.client_data import Outgoing


def wysylka(komorka: str, post: Post) -> Post:
    return Post(NewIssue("uwaga-taty", cast(Outgoing, komorka)), None, "r", None, post.parts)
""",
    "tytuł celu typu Any": _GOTOWY_CEL
    + """from typing import Any


def wysylka(wiersz: dict[str, Any], post: Post) -> Post:
    return Post(NewIssue("uwaga-taty", wiersz["ADRES"]), None, "r", None, post.parts)
""",
}


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
    "konstruktor ForbiddenValues": (
        """from rozliczenia.client_data import ForbiddenValues


def wysylka(komorka: str) -> str:
    return ForbiddenValues().guard(komorka, "treść").text
""",
        'Missing positional argument "proof"',
    ),
}

# Znane luki pustej pamięci (tests/fixtures/znane_luki.py): postaci, które dają strażnika bez pamięci pracy Centrum, a
# mypy i ruff ich nie łapią.
ZNANE_LUKI_PAMIECI: Final = {
    "cast pamięci uchwytu": """from typing import cast

from rozliczenia.client_data import ForbiddenValues
from rozliczenia.dad_files import DadFiles


def wysylka(komorka: str) -> str:
    return cast(ForbiddenValues, DadFiles().forbidden).guard(komorka, "treść").text
""",
}


@wymaga_ruff_i_mypy
def test_znane_luki_jednej_drogi_wyjscia_przechodza_przez_mypy_i_ruff(tmp_path: Path) -> None:
    zgloszenia = ruff_i_mypy(zapisz(ZNANE_LUKI, tmp_path), sonda=ROOT / "src" / "rozliczenia" / "centrum" / "sonda_luki.py")

    assert_znane_luki(zgloszenia, "tests/test_regula_danych.py")


@wymaga_ruff_i_mypy
def test_pole_tekstowe_celu_wysylki_z_komorki_bez_straznika_nie_przechodzi_mypy_a_znane_luki_przechodza(tmp_path: Path) -> None:
    probki = {opis: kod for opis, (kod, _) in DROGI_DO_CELU.items()} | ZNANE_LUKI_CELU
    zgloszenia = ruff_i_mypy(zapisz(probki, tmp_path), sonda=ROOT / "src" / "rozliczenia" / "centrum" / "sonda_celu.py")

    assert {opis: zgloszenia[opis] for opis, (_, odrzucenie) in DROGI_DO_CELU.items() if not any(odrzucenie in z for z in zgloszenia[opis])} == {}
    assert_znane_luki({opis: zgloszenia[opis] for opis in ZNANE_LUKI_CELU}, "tests/test_regula_danych.py (ZNANE_LUKI_CELU)")


@pytest.mark.parametrize("proof", [None, object()])
def test_pamiec_regula_danych_bez_dowodu_modulu_to_type_error(proof: object) -> None:
    with pytest.raises(TypeError, match="empty_memory"):
        ForbiddenValues(proof)


@wymaga_ruff_i_mypy
def test_straznik_z_pamiecia_spoza_pracy_centrum_nie_przechodzi_mypy_a_znane_luki_przechodza(tmp_path: Path) -> None:
    probki = {opis: kod for opis, (kod, _) in DROGI_DO_PUSTEJ_PAMIECI.items()} | ZNANE_LUKI_PAMIECI
    zgloszenia = ruff_i_mypy(zapisz(probki, tmp_path), sonda=ROOT / "src" / "rozliczenia" / "centrum" / "sonda_pamieci.py")

    assert {opis: zgloszenia[opis] for opis, (_, odrzucenie) in DROGI_DO_PUSTEJ_PAMIECI.items() if not any(odrzucenie in z for z in zgloszenia[opis])} == {}
    assert_znane_luki({opis: zgloszenia[opis] for opis in ZNANE_LUKI_PAMIECI}, "tests/test_regula_danych.py")
