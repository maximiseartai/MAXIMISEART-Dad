"""Reguła danych (ADR 0025) na interfejsie ``client_data``: które wartości strażnik zna i jak je maskuje.

Strażnika wołają cztery wysyłki Centrum (Logi, Zgłoszenie, Kontrola ilości, Uwaga taty), więc macierz reguły jest tu raz,
a każda wysyłka ma swój test przez HTTP API. Położenie wartości w tekście, wielkość liter i znaki między jej słowami
sprawdzają własności w ``test_wlasnosci_dopasowania_tekstu.py``. Wartości są syntetyczne.
"""

from __future__ import annotations

from datetime import time
from pathlib import Path
from typing import Final, SupportsIndex

import pytest

from rozliczenia.client_data import MIN_VALUE, ForbiddenColumn, ForbiddenValues, Guarded, empty_memory, free_text, guarded, guarded_number, tool
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
    # Tylko liczba całkowita zapisana jako ułamek traci część po przecinku (``shown``); inna zostaje w zapisie Excela.
    forbidden = empty_memory()
    forbidden.remember_value(ForbiddenColumn.ORANGE, 48012.75)

    wynik = guarded(forbidden, "umowa 48012.75 aktywna", "tekst")

    assert wynik == Guarded(tool("umowa [numer Orange] aktywna"), (ORANGE_NOTE,))


def test_godzina_z_zakazanej_kolumny_nie_jest_zakazana_wartoscia() -> None:
    # Godzina, jak data, nie wskazuje klienta, a zamaskowałaby każdą tę samą godzinę w Logach.
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


# Drogi do strażnika z pamięcią, która nie jest pamięcią pracy Centrum (przegląd #1660, W2) → zgłoszenie mypy albo ruff,
# które każdą odrzuca w nowym module ``src/rozliczenia/centrum``.
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
    return guarded(CentrumWork(Path("config"), log, zegar, print).forbidden, komorka, "treść").text
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

# Znane luki pustej pamięci (tests/fixtures/znane_luki.py): postaci, które dają strażnika bez pamięci pracy Centrum, a
# mypy i ruff ich nie łapią.
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


_KOMORKA: Final = "Syntetyczna Lipowa 5"

# Podklasa pamięci i podmiana jej metody w biegu (przegląd #1688, runda 2, W1): uwagi techniczne i maskowanie daje tylko
# ForbiddenValues.guard. Moduł każdej próbki robi przy wczytaniu podklasę albo podmienia metodę pamięci.
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


# Podklasa pamięci z własnymi uwagami technicznymi i odbiorca, który woła strażnika na pamięci obok guarded (przegląd
# #1704, runda 2, W1) → zgłoszenie mypy, które każdą odrzuca w nowym module src/rozliczenia/centrum.
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

# Pamięć, której typ nie jest dokładnie ForbiddenValues, u odbiorcy pamięci (przegląd #1704, runda 1, W1): moduł próbki
# ma ``wyciek(pamiec, komorka)``, które daje odbiorcy taki obiekt, a właściciel (client_data.guarded) odmawia go tuż
# przed wywołaniem strażnika.
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
    "typ Any: atrapa pamięci w guard_text": """from typing import Any

from rozliczenia.centrum.run_logs_guard import guard_text
from rozliczenia.client_data import ForbiddenValues, Guarded, guarded
"""
    + _ATRAPA_PAMIECI
    + """

def wyciek(pamiec: ForbiddenValues, komorka: str) -> str:
    atrapa: Any = Atrapa(pamiec, komorka)
    return guard_text("Postęp.", "postęp Wyceny w efenix", atrapa).text
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


# Znane luki uwag technicznych (tests/fixtures/znane_luki.py): „klasa: postać” → moduł src, którego ``wyciek(pamiec,
# komorka)`` daje tekst z wartością komórki (bez maski albo w uwadze technicznej), a ruff, mypy i bieg go nie zatrzymują.
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
    """Zgłoszenie biegu próbki: wyjątek albo tekst bez wartości komórki, czyli próbka nie daje uwagi spoza strażnika."""

    try:
        tekst = modul(plik).wyciek(empty_memory(), _KOMORKA)
    except (TypeError, AttributeError) as odmowa:
        return [f"bieg {type(odmowa).__name__}: {odmowa}"]
    return [] if _KOMORKA in tekst else [f"bieg: tekst bez wartości komórki: {tekst!r}"]


class _Udawany(str):
    """Tekst, którego wycinek daje wartość komórki, choć jego znaki jej nie mają."""

    def __getitem__(self, key: SupportsIndex | slice, /) -> str:
        return _KOMORKA


def test_straznik_czyta_znaki_tekstu_raz_wiec_podklasa_str_z_wlasnym_wycinkiem_nie_daje_komorki() -> None:
    """Strażnik szuka wartości w znakach tekstu, a sklejał wynik z wycinków, więc podklasa ``str`` z własnym wycinkiem
    dawała do wysyłki to, czego strażnik nie widział; teraz kopiuje znaki do ``str`` (``str.__str__``) przed sprawdzeniem
    (#1551, przegląd #1723)."""

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
