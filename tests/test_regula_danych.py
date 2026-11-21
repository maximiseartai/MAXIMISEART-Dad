from __future__ import annotations

from collections.abc import Callable
from datetime import time
from pathlib import Path
import sys
from types import FrameType
from typing import Any, Final, SupportsIndex

import pytest

from rozliczenia.client_data import (
    MIN_VALUE,
    ForbiddenColumn,
    ForbiddenValues,
    Guarded,
    LogsText,
    Outgoing,
    WithoutSubclasses,
    empty_memory,
    guarded,
    guarded_number,
    logs_text,
    remembered,
    tool,
)
from tests.fixtures.formy_telefonu import CELL_FORMS, PhoneForm
from tests.fixtures.wyciek import zawiera_wartosc
from tests.fixtures.znane_luki import assert_znane_luki, modul, ruff_i_mypy, wymaga_ruff_i_mypy, zapisz

ROOT = Path(__file__).resolve().parents[1]

ADDRESS_NOTE = "Reguła danych: zamaskowano wartość kolumny ADRES w: tekst."
ORANGE_NOTE = "Reguła danych: zamaskowano wartość kolumny NUMER UMOWY/ZLECENIA ORANGE w: tekst."


def test_wartosc_krotsza_niz_piec_znakow_nie_jest_zakazana_a_piec_znakow_juz_jest() -> None:
    forbidden = empty_memory()
    forbidden.remember_value(ForbiddenColumn.ADDRESS, "Lipa")
    forbidden.remember_value(ForbiddenColumn.ADDRESS, " „Lipno")

    wynik = guarded(forbidden, "Lipa kwitnie przy drodze na Lipno", "tekst")

    assert MIN_VALUE == 5
    assert wynik == Guarded(tool("Lipa kwitnie przy drodze na [adres]"), (ADDRESS_NOTE,))


@pytest.mark.parametrize(
    "wartosc",
    [pytest.param("„Lipa", id="znak-przed-pierwszym-slowem"), pytest.param("Bo\n\n\nC", id="odstepy-miedzy-slowami")],
)
def test_dlugosc_wartosci_liczy_sie_od_pierwszego_slowa_po_zwinieciu_odstepow(wartosc: str) -> None:
    forbidden = empty_memory()
    forbidden.remember_value(ForbiddenColumn.ADDRESS, wartosc)

    assert guarded(forbidden, "Lipa i Bo C przy drodze", "tekst") == Guarded(tool("Lipa i Bo C przy drodze"), ())


@pytest.mark.parametrize(
    ("tekst", "wynik"),
    [
        pytest.param("ul. Syntetyczna Długa Boczna Lipowa 5", "[ulica]", id="nazwa-czterech-slow"),
        pytest.param(
            "ul. Syntetyczna Długa Boczna Cicha Lipowa 5",
            "ul. Syntetyczna Długa Boczna Cicha Lipowa 5",
            id="granica-nazwa-pieciu-slow",
        ),
    ],
)
def test_wzmianka_ulicy_ma_nazwe_najwyzej_czterech_slow(tekst: str, wynik: str) -> None:
    assert guarded(empty_memory(), f"klient {tekst}, dzwonić", "tekst") == Guarded(tool(f"klient {wynik}, dzwonić"), ())


@pytest.mark.parametrize("liczba", [pytest.param(48012.75, id="czesc-ulamkowa"), pytest.param(-48012, id="minus")])
def test_liczba_z_zakazana_wartoscia_staje_sie_cala_maska_bez_zadnej_cyfry(liczba: float) -> None:
    forbidden = empty_memory()
    forbidden.remember_value(ForbiddenColumn.ORANGE, 48012)

    assert guarded_number(forbidden, liczba, "tekst") == Guarded(tool("[numer Orange]"), (ORANGE_NOTE,))


def test_liczba_wartosci_pamieci_rosnie_z_kazda_nowa_wartoscia_a_powtorzona_jej_nie_zmienia() -> None:
    forbidden = empty_memory()
    counts = []

    for column, value in (
        (ForbiddenColumn.ADDRESS, "Syntetyczna Lipowa 5"),
        (ForbiddenColumn.ADDRESS, "Syntetyczna Lipowa 5 m 7"),
        (ForbiddenColumn.ADDRESS, "Syntetyczna Lipowa 5"),
        (ForbiddenColumn.ORANGE, "syntetyczna lipowa 5"),
    ):
        forbidden.remember_value(column, value)
        counts.append(remembered(forbidden))

    assert counts == [1, 2, 2, 2]


def _kroki_straznika(forbidden: ForbiddenValues, tekst: str) -> int:
    kroki = 0

    def sledz(frame: FrameType, _event: str, _arg: object) -> Callable[..., Any] | None:
        nonlocal kroki
        if frame.f_code.co_filename != guarded.__code__.co_filename:
            return None
        kroki += 1
        return sledz

    poprzedni = sys.gettrace()
    sys.settrace(sledz)
    try:
        guarded(forbidden, tekst, "tekst")
    finally:
        sys.settrace(poprzedni)
    return kroki


def test_kroki_straznika_nie_zaleza_od_liczby_zapamietanych_wartosci() -> None:
    tekst = "klient Syntetyczna Lipowa 5 dzwonić po 16, " * 20
    mala, duza = empty_memory(), empty_memory()
    for pamiec in (mala, duza):
        pamiec.remember_value(ForbiddenColumn.ADDRESS, "Syntetyczna Lipowa 5")
    for numer in range(1000):
        duza.remember_value(ForbiddenColumn.ADDRESS, f"Inna{numer} Ulica 7")

    assert guarded(duza, tekst, "tekst") == guarded(mala, tekst, "tekst")
    assert _kroki_straznika(duza, tekst) == _kroki_straznika(mala, tekst)


@pytest.mark.parametrize(
    ("typ", "odmowa"),
    [pytest.param(Outgoing, "guarded albo tool", id="Outgoing"), pytest.param(LogsText, "logs_text", id="LogsText")],
)
def test_tekst_do_wysylki_i_plik_logow_bez_dowodu_modulu_to_type_error(typ: type[Outgoing | LogsText], odmowa: str) -> None:
    with pytest.raises(TypeError, match=odmowa):
        typ("Syntetyczna Lipowa 5", object())


@pytest.mark.parametrize(("dowod", "typ"), [pytest.param(tool, Outgoing, id="tool"), pytest.param(logs_text, LogsText, id="logs_text")])
def test_tekst_narzedzia_i_plik_logow_wychodza_znak_w_znak_bez_maskowania(dowod: Callable[[str], str], typ: type) -> None:
    tekst = "Uruchomienie 600123456, ul. Lipowa 5"

    wynik = dowod(tekst)

    assert (type(wynik), str.__str__(wynik)) == (typ, tekst)
    assert guarded(empty_memory(), tekst, "tekst").text == "Uruchomienie [telefon], [ulica]"


def test_klasa_bez_podklas_bez_odmowy_w_naglowku_to_type_error() -> None:
    with pytest.raises(TypeError, match="podaje odmowę"):

        class BezOdmowy(metaclass=WithoutSubclasses):
            pass


def test_z_dwoch_wartosci_od_tego_samego_slowa_maskowana_jest_cala_dluzsza() -> None:
    forbidden = empty_memory()
    forbidden.remember_value(ForbiddenColumn.ADDRESS, "Syntetyczna Lipowa 5")
    forbidden.remember_value(ForbiddenColumn.ADDRESS, "Syntetyczna Lipowa 5 m 7")

    longer = guarded(forbidden, "klient Syntetyczna Lipowa 5 m 7 dzwonić", "tekst")
    shorter = guarded(forbidden, "klient Syntetyczna Lipowa 5, dzwonić", "tekst")

    assert (longer.text, shorter.text) == ("klient [adres] dzwonić", "klient [adres], dzwonić")


def test_numer_orange_ktory_excel_czyta_jako_liczbe_ulamkowa_jest_zamaskowany_w_zapisie_cyfr() -> None:
    forbidden = empty_memory()
    forbidden.remember_value(ForbiddenColumn.ORANGE, 4801234567.0)

    wynik = guarded(forbidden, "umowa 4801234567 aktywna", "tekst")

    assert wynik == Guarded(tool("umowa [numer Orange] aktywna"), (ORANGE_NOTE,))


def test_liczba_z_czescia_ulamkowa_z_zakazanej_kolumny_jest_zamaskowana_razem_z_czescia_ulamkowa() -> None:
    forbidden = empty_memory()
    forbidden.remember_value(ForbiddenColumn.ORANGE, 48012.75)

    wynik = guarded(forbidden, "umowa 48012.75 aktywna", "tekst")

    assert wynik == Guarded(tool("umowa [numer Orange] aktywna"), (ORANGE_NOTE,))


def test_godzina_z_zakazanej_kolumny_nie_jest_zakazana_wartoscia() -> None:
    forbidden = empty_memory()
    forbidden.remember_value(ForbiddenColumn.ADDRESS, time(8, 30))

    assert guarded(forbidden, "przyjazd 08:30:00 rano", "tekst") == Guarded(tool("przyjazd 08:30:00 rano"), ())


def test_wartosc_zapamietana_pod_dwiema_kolumnami_jest_maskowana_jak_pierwsza() -> None:
    forbidden = empty_memory()
    forbidden.remember_value(ForbiddenColumn.ORANGE, "SYN-48012")
    forbidden.remember_value(ForbiddenColumn.ADDRESS, "syn 48012")

    assert guarded(forbidden, "umowa SYN 48012", "tekst") == Guarded(tool("umowa [numer Orange]"), (ORANGE_NOTE,))


def test_kazda_praca_centrum_ma_wlasna_pamiec_zakazanych_wartosci() -> None:
    first, second = empty_memory(), empty_memory()
    first.remember_value(ForbiddenColumn.ADDRESS, "Syntetyczna Lipowa 5")

    assert guarded(second, "Syntetyczna Lipowa 5", "tekst") == Guarded(tool("Syntetyczna Lipowa 5"), ())


def test_wyrocznia_wycieku_w_testach_widzi_numer_zlecenia_tak_jak_straznik() -> None:
    texts = ("ślad d41f94001ab0", "2026-11-12T10:00:00.394001", 'zlecenie "94001"', "#94001, wiersz 18")

    assert [zawiera_wartosc(text, "#94001") for text in texts] == [False, False, True, True]


@pytest.mark.parametrize("form", CELL_FORMS, ids=[form.form for form in CELL_FORMS])
def test_kazda_forma_telefonu_z_tabeli_adr_0025_wychodzi_tak_jak_mowi_tabela(form: PhoneForm) -> None:
    forbidden = empty_memory()
    wynik: Guarded | None
    expected: Guarded | None
    if isinstance(form.value, str):
        text = form.value if form.masked is None else form.masked
        wynik, expected = guarded(forbidden, form.value, "komórka"), Guarded(tool(text), ())
        in_text = guarded(forbidden, f"oddzwonić {form.value}, potem", "tekst")
        assert in_text == Guarded(tool(f"oddzwonić {text}, potem"), ()), "ta sama forma w wolnym tekście"
    else:
        wynik = guarded_number(forbidden, form.value, "komórka")
        expected = None if form.masked is None else Guarded(tool(form.masked), ())

    assert wynik == expected, form.why


DROGI_DO_PUSTEJ_PAMIECI: Final = {
    "pamięć świeżego uchwytu plików taty": (
        """from rozliczenia.client_data import guarded
from rozliczenia.dad_files import DadFiles


def wysylka(komorka: str) -> str:
    return guarded(DadFiles().forbidden, komorka, "treść").text
""",
        'Argument 1 to "guarded" has incompatible type "ForbiddenValues | None"; expected "ForbiddenValues"',
    ),
    "pamięć kontekstu Uruchomienia bez Centrum": (
        """from rozliczenia.client_data import guarded
from rozliczenia.run_context import RunContext


def wysylka(komorka: str) -> str:
    return guarded(RunContext().files.forbidden, komorka, "treść").text
""",
        'Argument 1 to "guarded" has incompatible type "ForbiddenValues | None"; expected "ForbiddenValues"',
    ),
    "pamięć świeżej pracy Centrum": (
        """from pathlib import Path

from rozliczenia.centrum.clock import Clock
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.work import CentrumWork
from rozliczenia.client_data import guarded


def wysylka(komorka: str, log: CentrumLog, zegar: Clock) -> str:
    return guarded(CentrumWork(Path("config"), log, zegar, print, box_prefix=None).forbidden, komorka, "treść").text
""",
        'Missing positional argument "forbidden"',
    ),
    "konstruktor ForbiddenValues": (
        """from rozliczenia.client_data import ForbiddenValues, guarded


def wysylka(komorka: str) -> str:
    return guarded(ForbiddenValues(), komorka, "treść").text
""",
        'Missing positional argument "proof"',
    ),
    "prywatna tabela wartości pamięci: wyczyszczenie zapamiętanych wartości": (
        """from rozliczenia import client_data
from rozliczenia.client_data import ForbiddenValues, guarded


def wysylka(komorka: str, pamiec: ForbiddenValues) -> str:
    client_data._WORDS[pamiec].columns.clear()
    return guarded(pamiec, komorka, "treść").text
""",
        "Private member accessed: `_WORDS`",
    ),
}

ZNANE_LUKI_PAMIECI: Final = {
    "cast pamięci uchwytu": """from typing import cast

from rozliczenia.client_data import ForbiddenValues, guarded
from rozliczenia.dad_files import DadFiles


def wysylka(komorka: str) -> str:
    return guarded(cast(ForbiddenValues, DadFiles().forbidden), komorka, "treść").text
""",
    "prywatna tabela wartości pamięci przez moduł pod nazwą cls": """from rozliczenia import client_data as cls
from rozliczenia.client_data import ForbiddenValues, guarded


def wysylka(komorka: str, pamiec: ForbiddenValues) -> str:
    cls._WORDS[pamiec].columns.clear()
    return guarded(pamiec, komorka, "treść").text
""",
}


def test_pamiec_regula_danych_bez_dowodu_modulu_to_type_error() -> None:
    with pytest.raises(TypeError, match="empty_memory"):
        ForbiddenValues(object())


@wymaga_ruff_i_mypy
def test_straznik_z_pamiecia_spoza_pracy_centrum_nie_przechodzi_mypy_a_znane_luki_przechodza(tmp_path: Path) -> None:
    probki = {opis: kod for opis, (kod, _) in DROGI_DO_PUSTEJ_PAMIECI.items()} | ZNANE_LUKI_PAMIECI
    zgloszenia = ruff_i_mypy(zapisz(probki, tmp_path), sonda=ROOT / "src" / "rozliczenia" / "centrum" / "sonda_pamieci.py")

    assert {opis: zgloszenia[opis] for opis, (_, odrzucenie) in DROGI_DO_PUSTEJ_PAMIECI.items() if not any(odrzucenie in z for z in zgloszenia[opis])} == {}
    assert_znane_luki({opis: zgloszenia[opis] for opis in ZNANE_LUKI_PAMIECI}, "tests/test_regula_danych.py")


_KOMORKA: Final = "Syntetyczna Lipowa 5"

_PAMIEC_W_BIEGU: Final = f"""import types
from typing import Any

from rozliczenia.client_data import ForbiddenValues, Guarded, empty_memory, guarded

pamiec = empty_memory()


class Mixin:
    def __init_subclass__(cls, **kwargs: object) -> None:
        pass


def zla(self: object, text: str, place: str) -> Guarded:
    return Guarded(guarded(pamiec, text, place).text, ({_KOMORKA!r},))


"""
PODKLASY_PAMIECI: Final = {
    "class z bazą przed ForbiddenValues, której __init_subclass__ nie woła super()": (
        "class Pamiec(Mixin, ForbiddenValues):\n    guard = zla\n"
    ),
    "type() z trzema argumentami": 'Pamiec = type("Pamiec", (ForbiddenValues,), {"guard": zla})\n',
    "types.new_class z bazą przed ForbiddenValues": (
        'Pamiec = types.new_class("Pamiec", (Mixin, ForbiddenValues), {}, lambda ns: ns.update(guard=zla))\n'
    ),
    "type.__new__ z metaklasą ForbiddenValues": (
        'Pamiec = type.__new__(type(ForbiddenValues), "Pamiec", (ForbiddenValues,), {"guard": zla})\n'
    ),
    "podklasa metaklasy ForbiddenValues z type.__new__": (
        'Meta: Any = type("Meta", (type(ForbiddenValues),), {"__new__": type.__new__})\n'
        'Pamiec = Meta("Pamiec", (ForbiddenValues,), {"guard": zla})\n'
    ),
}
PODMIANY_METODY_PAMIECI: Final = {
    "setattr na pamięci": 'setattr(pamiec, "remember_value", types.MethodType(lambda self, column, value: None, pamiec))\n',
    "object.__setattr__ na pamięci": (
        'object.__setattr__(pamiec, "remember_value", types.MethodType(lambda self, column, value: None, pamiec))\n'
    ),
}


@pytest.mark.parametrize("kod", PODKLASY_PAMIECI.values(), ids=PODKLASY_PAMIECI.keys())
def test_pamiec_regula_danych_nie_ma_podklas_w_biegu_przy_kazdej_kolejnosci_baz(kod: str, tmp_path: Path) -> None:
    plik = tmp_path / "podklasa.py"
    plik.write_text(_PAMIEC_W_BIEGU + kod, encoding="utf-8")

    with pytest.raises(TypeError, match="Pamięć reguły danych nie ma podklas: maskowanie i uwagi techniczne daje tylko client_data.guarded"):
        modul(plik)


@pytest.mark.parametrize("kod", PODMIANY_METODY_PAMIECI.values(), ids=PODMIANY_METODY_PAMIECI.keys())
def test_metody_pamieci_nie_da_sie_podmienic_na_obiekcie(kod: str, tmp_path: Path) -> None:
    plik = tmp_path / "podmiana.py"
    plik.write_text(_PAMIEC_W_BIEGU + kod, encoding="utf-8")

    with pytest.raises(AttributeError, match="'remember_value' is read-only"):
        modul(plik)


DROGI_DO_UWAG: Final = {
    "podklasa ForbiddenValues": (
        f"""from rozliczenia.client_data import ForbiddenValues, Guarded, guarded


class Pamiec(ForbiddenValues):
    def guard(self, text: str, place: str) -> Guarded:
        return Guarded(guarded(self, text, place).text, ({_KOMORKA!r},))
""",
        'Cannot inherit from final class "ForbiddenValues"',
    ),
    "odbiorca bez właściciela: guard na pamięci": (
        """from rozliczenia.client_data import ForbiddenValues, Guarded


def wyciek(pamiec: ForbiddenValues, komorka: str) -> Guarded:
    return pamiec.guard(komorka, "treść")
""",
        '"ForbiddenValues" has no attribute "guard"',
    ),
    "odbiorca bez właściciela: guard_number na pamięci": (
        """from rozliczenia.client_data import ForbiddenValues, Guarded


def wyciek(pamiec: ForbiddenValues, liczba: int) -> Guarded | None:
    return pamiec.guard_number(liczba, "komórka L6")
""",
        '"ForbiddenValues" has no attribute "guard_number"',
    ),
}

_ATRAPA_PAMIECI: Final = """

class Atrapa:
    def __init__(self, pamiec: ForbiddenValues, komorka: str) -> None:
        self.pamiec = pamiec
        self.komorka = komorka

    def guard(self, text: str, place: str) -> Guarded:
        return Guarded(guarded(self.pamiec, text, place).text, (self.komorka,))

    def guard_number(self, value: int | float, place: str) -> Guarded:
        return self.guard(str(value), place)
"""
ODMOWY_UWAG: Final = {
    "cast: atrapa pamięci w guard_text": """from typing import cast

from rozliczenia.centrum.run_logs_guard import guard_text
from rozliczenia.client_data import ForbiddenValues, Guarded, guarded
"""
    + _ATRAPA_PAMIECI
    + """

def wyciek(pamiec: ForbiddenValues, komorka: str) -> str:
    return guard_text("Postęp.", "postęp Wyceny w efenix", cast(ForbiddenValues, Atrapa(pamiec, komorka))).text
""",
    "cast: owijka prawdziwej pamięci w note_issue": """from typing import cast

from rozliczenia.centrum.dad_notes import note_issue
from rozliczenia.client_data import ForbiddenValues, Guarded, guarded
"""
    + _ATRAPA_PAMIECI
    + """

def wyciek(pamiec: ForbiddenValues, komorka: str) -> str:
    return note_issue("Tytuł", "Treść.", None, None, cast(ForbiddenValues, Atrapa(pamiec, komorka))).body
""",
    "cast: atrapa pamięci w guard_logs": """from typing import cast

from rozliczenia.centrum.run_logs import RunLog
from rozliczenia.centrum.run_logs_guard import guard_logs
from rozliczenia.client_data import ForbiddenValues, Guarded, guarded
"""
    + _ATRAPA_PAMIECI
    + """

def wyciek(pamiec: ForbiddenValues, komorka: str) -> str:
    logi = RunLog.model_validate(
        {
            "schema_version": 1, "run_id": "20261023-204720-settlement", "process": "settlement", "mode": "zapis",
            "period": "08_14_09_2026", "started_at": "2026-10-23T20:47:20Z", "ended_at": "2026-10-23T20:47:21Z",
            "duration_ms": 10, "tool": {"wydanie": None, "commit": "3c1d0a9"}, "result": "OK", "ending": "finished",
            "stop_kind": None, "issue_count": 0, "messages": [], "technical_notes": ["Uwaga narzędzia."], "summary": None,
            "phases": [], "templates": [], "environment": {"system": "Windows-11", "python": "3.12.10", "files": None},
            "trace": None, "diagnosis": None,
        }
    )
    return guard_logs(logi, cast(ForbiddenValues, Atrapa(pamiec, komorka))).text
""",
    "cast: atrapa pamięci w guarded_number": """from typing import cast

from rozliczenia.client_data import ForbiddenValues, Guarded, guarded, guarded_number
"""
    + _ATRAPA_PAMIECI
    + """

def wyciek(pamiec: ForbiddenValues, komorka: str) -> str:
    znaleziony = guarded_number(cast(ForbiddenValues, Atrapa(pamiec, komorka)), 4801234567, "komórka L6")
    return "" if znaleziony is None else znaleziony.text + "".join(znaleziony.notes)
""",
    "cast: atrapa z __class__ ForbiddenValues, którą bierze isinstance": """from typing import cast

from rozliczenia.centrum.run_logs_guard import guard_text
from rozliczenia.client_data import ForbiddenValues, Guarded, guarded
"""
    + _ATRAPA_PAMIECI
    + """

class Przebrana(Atrapa):
    @property
    def __class__(self) -> type:
        return ForbiddenValues


def wyciek(pamiec: ForbiddenValues, komorka: str) -> str:
    return guard_text("Postęp.", "postęp Wyceny w efenix", cast(ForbiddenValues, Przebrana(pamiec, komorka))).text
""",
    "refleksja: przypisanie __class__ obcej klasy z tymi samymi slotami": """from rozliczenia.centrum.run_logs_guard import guard_text
from rozliczenia.client_data import ForbiddenValues, Guarded, guarded


def wyciek(pamiec: ForbiddenValues, komorka: str) -> str:
    tekst = guarded(pamiec, "Postęp.", "postęp Wyceny w efenix").text

    class Obca:
        __slots__ = ("__weakref__",)

        def guard(self, text: str, place: str) -> Guarded:
            return Guarded(tekst, (komorka,))

    object.__setattr__(pamiec, "__class__", Obca)
    return guard_text("Postęp.", "postęp Wyceny w efenix", pamiec).text
""",
    "refleksja: type.__new__ z metaklasą ForbiddenValues i bazą przed nią bez super() w __init_subclass__": """from typing import Any

from rozliczenia.centrum.run_logs_guard import guard_text
from rozliczenia.client_data import ForbiddenValues, Guarded, guarded


class Mixin:
    def __init_subclass__(cls, **kwargs: object) -> None:
        pass


def wyciek(pamiec: ForbiddenValues, komorka: str) -> str:
    def guard(self: object, text: str, place: str) -> Guarded:
        return Guarded(guarded(pamiec, text, place).text, (komorka,))

    def init(self: object) -> None:
        pass

    podklasa: Any = type.__new__(type(ForbiddenValues), "Pamiec", (Mixin, ForbiddenValues), {"__init__": init, "guard": guard})
    return guard_text("Postęp.", "postęp Wyceny w efenix", podklasa()).text
""",
}


@pytest.mark.parametrize("opis", ODMOWY_UWAG.keys())
def test_odbiorca_pamieci_odmawia_obiektu_innego_typu_niz_pamiec_tuz_przed_straznikiem(opis: str, tmp_path: Path) -> None:
    plik = tmp_path / "odbiorca.py"
    plik.write_text(ODMOWY_UWAG[opis], encoding="utf-8")

    with pytest.raises(TypeError, match="Strażnik reguły danych bierze tylko pamięć ForbiddenValues z empty_memory, nie "):
        modul(plik).wyciek(empty_memory(), _KOMORKA)


ZNANE_LUKI_UWAG: Final = {
    'podmiana metody na klasie: setattr(ForbiddenValues, "remember_value", …)': """from rozliczenia.centrum.run_logs_guard import guard_text
from rozliczenia.client_data import ForbiddenColumn, ForbiddenValues


def wyciek(pamiec: ForbiddenValues, komorka: str) -> str:
    zapamietaj = ForbiddenValues.remember_value
    setattr(ForbiddenValues, "remember_value", lambda self, column, value: None)
    try:
        pamiec.remember_value(ForbiddenColumn.ADDRESS, komorka)
    finally:
        setattr(ForbiddenValues, "remember_value", zapamietaj)
    return guard_text(f"Klient {komorka}.", "postęp Wyceny w efenix", pamiec).text
""",
    "typ Any: odbiorca woła guard atrapy typu Any": """from typing import Any

from rozliczenia.client_data import ForbiddenValues, Guarded, guarded
"""
    + _ATRAPA_PAMIECI
    + """

def wyciek(pamiec: ForbiddenValues, komorka: str) -> str:
    atrapa: Any = Atrapa(pamiec, komorka)
    znaleziony: Guarded = atrapa.guard("Postęp.", "postęp Wyceny w efenix")
    return znaleziony.text + "".join(f"\\n- Uwaga techniczna: {uwaga}" for uwaga in znaleziony.notes)
""",
    'refleksja: getattr(obiekt, "guard") na atrapie podanej przez cast': """from typing import cast

from rozliczenia.client_data import ForbiddenValues, Guarded, guarded
"""
    + _ATRAPA_PAMIECI
    + """

def wyciek(pamiec: ForbiddenValues, komorka: str) -> str:
    znaleziony: Guarded = getattr(cast(ForbiddenValues, Atrapa(pamiec, komorka)), "guard")("Postęp.", "postęp Wyceny w efenix")
    return znaleziony.text + "".join(f"\\n- Uwaga techniczna: {uwaga}" for uwaga in znaleziony.notes)
""",
    'podmiana właściciela w module odbiorcy: setattr(run_logs_guard, "guarded", …)': """from rozliczenia.centrum import run_logs_guard
from rozliczenia.client_data import ForbiddenValues, Guarded


def wyciek(pamiec: ForbiddenValues, komorka: str) -> str:
    wlasciciel = getattr(run_logs_guard, "guarded")

    def podmieniony(forbidden: ForbiddenValues, text: str, place: str) -> Guarded:
        return Guarded(wlasciciel(forbidden, text, place).text, (komorka,))

    setattr(run_logs_guard, "guarded", podmieniony)
    try:
        return run_logs_guard.guard_text("Postęp.", "postęp Wyceny w efenix", pamiec).text
    finally:
        setattr(run_logs_guard, "guarded", wlasciciel)
""",
    'podmiana nazwy w module właściciela: setattr(client_data, "_masked", …)': """from rozliczenia import client_data
from rozliczenia.centrum.run_logs_guard import guard_text
from rozliczenia.client_data import ForbiddenColumn, ForbiddenValues


def wyciek(pamiec: ForbiddenValues, komorka: str) -> str:
    pamiec.remember_value(ForbiddenColumn.ADDRESS, komorka)
    maskowanie = getattr(client_data, "_masked")
    setattr(client_data, "_masked", lambda memory, text: (text, set()))
    try:
        return guard_text(f"Klient {komorka}.", "postęp Wyceny w efenix", pamiec).text
    finally:
        setattr(client_data, "_masked", maskowanie)
""",
}


def _wyciek_w_biegu(plik: Path) -> list[str]:
    try:
        tekst = modul(plik).wyciek(empty_memory(), _KOMORKA)
    except (TypeError, AttributeError) as odmowa:
        return [f"bieg {type(odmowa).__name__}: {odmowa}"]
    return [] if _KOMORKA in tekst else [f"bieg: tekst bez wartości komórki: {tekst!r}"]


class _Udawany(str):
    def __getitem__(self, key: SupportsIndex | slice, /) -> str:
        return _KOMORKA


def test_straznik_czyta_znaki_tekstu_raz_wiec_podklasa_str_z_wlasnym_wycinkiem_nie_daje_komorki() -> None:
    pamiec = empty_memory()
    pamiec.remember_value(ForbiddenColumn.ADDRESS, _KOMORKA)

    assert guarded(pamiec, _Udawany("Postęp bez danych."), "tekst").text == "Postęp bez danych."


@wymaga_ruff_i_mypy
def test_uwagi_techniczne_daje_tylko_straznik_pamieci_a_znane_luki_przechodza(tmp_path: Path) -> None:
    probki = {opis: kod for opis, (kod, _) in DROGI_DO_UWAG.items()} | ZNANE_LUKI_UWAG
    pliki = zapisz(probki, tmp_path)
    zgloszenia = ruff_i_mypy(pliki, sonda=ROOT / "src" / "rozliczenia" / "centrum" / "sonda_uwag.py")

    assert {opis: zgloszenia[opis] for opis, (_, odrzucenie) in DROGI_DO_UWAG.items() if not any(odrzucenie in z for z in zgloszenia[opis])} == {}
    assert_znane_luki(
        {opis: zgloszenia[opis] + _wyciek_w_biegu(pliki[opis]) for opis in ZNANE_LUKI_UWAG},
        "tests/test_regula_danych.py (ZNANE_LUKI_UWAG)",
    )
