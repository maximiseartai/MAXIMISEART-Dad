"""Moduł Legendy czynności na swoim interfejsie (ADR 0038): ``read_codes`` i parser pliku ``legenda-czynnosci.yaml``.

Moduł jest szwem: liczą nim Przygotowanie pliku zbiorczego, Ilości do uzupełnienia, Kontrola ilości, podgląd zmiany
legendy i brama, więc macierz reguł jest tu raz. Oczekiwania pochodzą z maila taty z 15.11.2026, ADR 0038 i opisu
modułu ``activity_legend``. Przykłady Hypothesis są deterministyczne (``derandomize=True``, bez bazy przykładów).
"""

from __future__ import annotations

from collections import Counter

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from rozliczenia.activity_legend import (
    ActivityCode,
    ActivityLegend,
    CellFill,
    CodesRead,
    ColumnByNumber,
    FillColour,
    FixedColumn,
    NUMBER,
    LegendProblem,
    NumberRange,
    read_codes,
)
from rozliczenia.activity_legend_file import DEFAULT_ACTIVITY_LEGEND, dump_activity_legend, parse_activity_legend

PROPERTY = settings(derandomize=True, database=None, deadline=None, max_examples=200)


def _read(text: str) -> CodesRead:
    return read_codes(DEFAULT_ACTIVITY_LEGEND, text)


@pytest.mark.parametrize(
    ("text", "column"),
    [
        ("instutp0m", None),
        ("instutp1m", "AL"),
        ("instutp15m", "AL"),
        ("instutp16m", "AJ"),
        ("instutp30m", "AJ"),
        ("instutp31m", None),
        ("instwewrg60m", None),
        ("instwewrg610m", "AK"),
        ("instwewrg611m", "AL"),
        ("instwewrg615m", "AL"),
        ("instwewrg616m", "AJ"),
        ("instwewrg630m", "AJ"),
        ("instwewrg631m", None),
    ],
)
def test_liczba_z_kodu_wybiera_kolumne_przedzialem_a_spoza_przedzialow_niczego_nie_wpisuje(text: str, column: str | None) -> None:
    read = _read(text)

    if column is None:
        assert (read.quantities, read.amount, dict(read.fills), read.found) == ({}, 0, {}, ())
        assert [found.code for found in read.out_of_range] == ["instutp" if text.startswith("instutp") else "instwewrg6"]
        assert read.only_codes is False
    else:
        assert dict(read.quantities) == {column: 1}
        assert read.out_of_range == ()
        assert read.only_codes is True


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("instwewrg610m", "instwewrg6"),
        ("instwew10m", "instwew"),
        ("inst10m", "inst"),
        ("instmdik", "instmdik"),
        ("spawmufakan", "spawmufakan"),
        ("spawmufaziem", "spawmufaziem"),
    ],
)
def test_dluzszy_zapis_wygrywa_z_krotszym_a_dopasowany_tekst_nie_liczy_sie_drugi_raz(text: str, code: str) -> None:
    assert [found.code for found in _read(text).found] == [code]


# Zapisy, które pracownicy piszą bez liczby (pytania do taty: „samo instwew”), więc krótszy pasuje do początku dłuższego.
_NESTED = ActivityLegend(
    (
        ActivityCode("inst", ("inst",), FixedColumn("Y")),
        ActivityCode("instwew", ("instwew",), fills=(CellFill("AF", FillColour.GREEN),)),
        ActivityCode("instwewrg6", ("instwewrg6{n}m",), ColumnByNumber((NumberRange(1, 10, "AK"),))),
    )
)


@pytest.mark.parametrize(
    ("text", "codes"),
    [("instwewrg65m", ["instwewrg6"]), ("instwew", ["instwew"]), ("inst", ["inst"]), ("inst instwew instwewrg65m", ["inst", "instwew", "instwewrg6"])],
)
def test_dluzszy_zapis_wygrywa_z_krotszym_ktory_pasuje_do_jego_poczatku(text: str, codes: list[str]) -> None:
    assert [found.code for found in read_codes(_NESTED, text).found] == codes


@pytest.mark.parametrize("text", ["xinst20m", "ąinst20m", "2inst20m", "Montażinst20m", "spawanie gniazda", "instalacja 20m", "rt25", "art2"])
def test_kod_nie_zaczyna_sie_w_srodku_slowa_a_zwykle_slowa_nie_sa_kodem(text: str) -> None:
    assert _read(text).found == ()


_SPELLINGS = tuple(spelling for code in DEFAULT_ACTIVITY_LEGEND.codes for spelling in code.spellings)
# Zapis z Legendy z Wydania z liczbą, także spoza przedziałów (0, 31…), tak jak mógł go napisać Wykonawca.
_CODE = st.sampled_from(_SPELLINGS).flatmap(lambda spelling: st.integers(0, 40).map(lambda number: spelling.replace(NUMBER, str(number))))


def _outcome(read: CodesRead) -> tuple[object, ...]:
    return (
        Counter(found.code for found in read.found),
        Counter(found.code for found in read.out_of_range),
        dict(read.quantities),
        read.amount,
        dict(read.fills),
        read.only_codes,
    )


@PROPERTY
@given(first=_CODE, second=_CODE)
def test_kody_sklejone_bez_spacji_licza_sie_oba_w_kazdej_kolejnosci(first: str, second: str) -> None:
    separated = _outcome(_read(f"{first}, {second}"))

    assert _outcome(_read(first + second)) == separated
    assert _outcome(_read(second + first)) == separated


# Litery i cyfry tekstu Wykonawcy; poza nimi są litery, które ``casefold`` rozkłada na literę i znak diakrytyczny (``İ``).
_WORD_CHARACTERS = "abcdefghijklmnopqrstuvwxyząćęłńóśźżABCDEFGHIJKLMNOPQRSTUVWXYZĄĆĘŁŃÓŚŹŻ0123456789"


@PROPERTY
@given(before=st.just("") | _CODE, word=st.text(alphabet=_WORD_CHARACTERS, min_size=1, max_size=12), code=_CODE)
def test_kod_po_literze_albo_cyfrze_zwyklego_slowa_nie_pasuje(before: str, word: str, code: str) -> None:
    assume(_read(word) == _read(""))

    assert _outcome(_read(before + word + code)) == _outcome(_read(before + word))


def test_wypelnienie_kolumny_daje_pierwszy_w_tekscie_kod() -> None:
    legend = ActivityLegend(
        (
            ActivityCode("zielony", ("zielony",), fills=(CellFill("AF", FillColour.GREEN),)),
            ActivityCode("czerwony", ("czerwony",), fills=(CellFill("AF", FillColour.RED),)),
        )
    )

    assert dict(read_codes(legend, "zielony czerwony").fills) == {"AF": FillColour.GREEN}
    assert dict(read_codes(legend, "czerwony zielony").fills) == {"AF": FillColour.RED}


def test_kod_spoza_przedzialow_obok_dzialajacego_kodu_wyklucza_same_kody() -> None:
    read = _read("inst20m instutp99m")

    assert [found.code for found in read.found] == ["inst"]
    assert [found.code for found in read.out_of_range] == ["instutp"]
    assert read.only_codes is False


def test_kazde_wystapienie_kodu_sie_dodaje_a_rozne_kody_sumuja_sie_takze_w_as() -> None:
    read = _read("spawpg, spawpg dzielnik 1/2 inst25m inst utp17m instmdik")

    assert dict(read.quantities) == {"Y": 2, "AB": 2, "AJ": 1}
    assert read.amount == 190
    assert dict(read.fills) == {"AS": FillColour.RED}
    assert [found.code for found in read.found] == ["spawpg", "spawpg", "dzielnik1/2", "inst", "instutp", "instmdik"]


def test_tekst_z_kodem_i_zwyklym_opisem_wyznacza_wartosci_kodu_ale_nie_jest_z_samych_kodow() -> None:
    read = _read("20 m patchcord dzielnik 1/2")

    assert (read.amount, read.only_codes) == (50, False)


# Pierwsze litery zapisów legendy z Wydania; tekst bez nich nie może zawierać kodu, bo zapis zaczyna się od litery.
_FIRST_LETTERS = frozenset(spelling[0] for code in DEFAULT_ACTIVITY_LEGEND.codes for spelling in code.spellings)
_WITHOUT_CODES = st.text(
    alphabet=st.characters(
        blacklist_characters="".join(_FIRST_LETTERS | {letter.upper() for letter in _FIRST_LETTERS}),
        blacklist_categories=["Cs"],
    ),
    max_size=60,
).filter(lambda text: not any(letter in text.casefold() for letter in _FIRST_LETTERS))


@PROPERTY
@given(text=_WITHOUT_CODES)
def test_tekst_bez_kodu_daje_pusty_wynik(text: str) -> None:
    read = _read(text)

    assert (read.found, dict(read.quantities), read.amount, dict(read.fills), read.out_of_range, read.only_codes) == (
        (),
        {},
        0,
        {},
        (),
        False,
    )


_SAMPLES = ("inst20m", "instmdic", "instutp17m", "instwewrg612m", "rt2", "bypas2m", "spawgnd", "spawpg", "dzielnik1/2", "pz20m", "instwew15m")
_BETWEEN = st.lists(st.sampled_from((" ", ", ", ". ", "; ", " tak ", " nie ", " TAK, ", " - ", "!", "\n", "/ ")), min_size=0, max_size=3)


@st.composite
def _written(draw: st.DrawFn, codes: list[str]) -> str:
    """Kody tak, jak mógł je zapisać Wykonawca: wielkość liter, spacje w środku kodu, ale nie w środku liczby."""

    text = ""
    for code in codes:
        upper = draw(st.integers(0, 2 ** len(code) - 1))
        spaced = draw(st.integers(0, 2 ** len(code) - 1))
        text += "".join(
            (char.upper() if upper >> index & 1 else char)
            + (" " if spaced >> index & 1 and index < len(code) - 1 and not (char + code[index + 1]).isdigit() else "")
            for index, char in enumerate(code)
        )
        text += " "
    return text


@PROPERTY
@given(data=st.data(), codes=st.lists(st.sampled_from(_SAMPLES), min_size=1, max_size=4))
def test_tak_nie_i_interpunkcja_nie_zmieniaja_rozstrzygniecia_same_kody(data: st.DataObject, codes: list[str]) -> None:
    plain = _read(" ".join(codes))
    joined = "".join("".join(data.draw(_BETWEEN)) + data.draw(_written([code])) for code in codes) + "".join(data.draw(_BETWEEN))

    read = _read(joined)

    assert plain.only_codes is True
    assert (read.only_codes, dict(read.quantities), read.amount, dict(read.fills)) == (
        True,
        dict(plain.quantities),
        plain.amount,
        dict(plain.fills),
    )
    assert _read(joined + " montaż").only_codes is False


def test_legenda_z_wydania_czyta_sie_z_powrotem_w_ten_sam_typ() -> None:
    assert parse_activity_legend(dump_activity_legend(DEFAULT_ACTIVITY_LEGEND)) == DEFAULT_ACTIVITY_LEGEND


def _document(*codes: dict[str, object]) -> dict[str, object]:
    return {"schema_version": 1, "kody": list(codes)}


@pytest.mark.parametrize(
    ("document", "field"),
    [
        (_document({"id": "a", "zapisy": ["spawpg"], "kolumna": "AB"}, {"id": "b", "zapisy": ["spawpg"], "kolumna": "AC"}), "kody[b].zapisy[0]"),
        (
            _document({"id": "a", "zapisy": ["utp{n}m"], "przedzialy": [{"od": 1, "do": 15, "kolumna": "AL"}, {"od": 15, "do": 30, "kolumna": "AJ"}]}),
            "kody[a].przedzialy",
        ),
        (_document({"id": "a", "zapisy": ["utp{n}m"], "przedzialy": [{"od": 0, "do": 15, "kolumna": "AL"}]}), "kody[a].przedzialy[0]"),
        (_document({"id": "a", "zapisy": ["utp{n}m"], "przedzialy": [{"od": 10, "do": 5, "kolumna": "AL"}]}), "kody[a].przedzialy[0]"),
        (_document({"id": "a", "zapisy": ["utp{n}m"], "przedzialy": []}), "kody[a].przedzialy"),
        (_document({"id": "a", "zapisy": ["utp"], "przedzialy": [{"od": 1, "do": 15, "kolumna": "AL"}]}), "kody[a].zapisy[0]"),
        (_document({"id": "a", "zapisy": ["spawpg"]}), "kody[a]"),
        (_document({"id": "a", "zapisy": ["spawpg"], "kolumna": "P"}), "kody[a].kolumna"),
        (_document({"id": "a", "zapisy": ["spawpg"], "kolumna": "S"}), "kody[a].kolumna"),
        (_document({"id": "a", "zapisy": ["spawpg"], "kolumna": "AQ"}), "kody[a].kolumna"),
        (_document({"id": "a", "zapisy": ["spawpg"], "kolumna": "AS"}), "kody[a].kolumna"),
        (_document({"id": "a", "zapisy": ["spawpg"], "kolumna": "M"}), "kody[a].kolumna"),
        (_document({"id": "a", "zapisy": ["utp{n}m"], "przedzialy": [{"od": 1, "do": 5, "kolumna": "Q"}]}), "kody[a].przedzialy[0].kolumna"),
        (_document({"id": "a", "zapisy": ["spawpg"], "wypelnienia": [{"kolumna": "AT", "kolor": "zielony"}]}), "kody[a].wypelnienia[0]"),
        (_document({"id": "a", "zapisy": ["spawpg"], "wypelnienia": [{"kolumna": "AF", "kolor": "niebieski"}]}), "kody[a].wypelnienia[0].kolor"),
        (
            _document({"id": "a", "zapisy": ["spawpg"], "wypelnienia": [{"kolumna": "AF", "kolor": "zielony"}, {"kolumna": "AF", "kolor": "czerwony"}]}),
            "kody[a].wypelnienia[1]",
        ),
        (_document({"id": "a", "zapisy": ["spawpg"], "kwota": 0}), "kody[a].kwota"),
        (_document({"id": "a", "zapisy": ["spawpg"], "kwota": 1000}), "kody[a].kwota"),
        (_document({"id": "a", "zapisy": ["spawpg"], "kwota": True}), "kody[a].kwota"),
        (_document({"id": "a", "zapisy": ["spawpg"], "kolumna": "AB", "wartosc": 0}), "kody[a].wartosc"),
        (_document({"id": "a", "zapisy": ["spawpg"], "kwota": 70, "wartosc": 2}), "kody[a].wartosc"),
        (_document({"id": "a", "zapisy": ["spaw pg"], "kolumna": "AB"}), "kody[a].zapisy[0]"),
        (_document({"id": "a", "zapisy": ["SpawPG"], "kolumna": "AB"}), "kody[a].zapisy[0]"),
        (_document({"id": "a", "zapisy": ["20m"], "kolumna": "Y"}), "kody[a].zapisy[0]"),
        (_document({"id": "a", "zapisy": ["inst{n}m{n}"], "kolumna": "Y"}), "kody[a].zapisy[0]"),
        (_document({"id": "a", "zapisy": [], "kolumna": "Y"}), "kody[a].zapisy"),
        (_document({"id": "a", "zapisy": ["x"], "kolumna": "Y"}, {"id": "a", "zapisy": ["y"], "kolumna": "Y"}), "kody[a].id"),
        (_document({"id": " a", "zapisy": ["x"], "kolumna": "Y"}), "kody[ a].id"),
        (_document({"id": "a", "zapisy": ["x"], "kolumna": "Y", "przedzialy": []}), "kody[a].przedzialy"),
        (_document({"id": "a", "zapisy": ["x"], "kolumna": "Y", "kolor": "zielony"}), "kody[0].kolor"),
        (_document({"id": "a", "kolumna": "Y"}), "kody[0].zapisy"),
        ({"schema_version": 2, "kody": []}, "schema_version"),
        ({"schema_version": 1}, "kody"),
        ([], "plik"),
    ],
)
def test_parser_odmawia_z_polem(document: object, field: str) -> None:
    problem = parse_activity_legend(document)

    assert isinstance(problem, LegendProblem)
    assert problem.field == field, problem.message


def test_legenda_z_kazdym_dzialaniem_czyta_sie_z_powrotem_w_ten_sam_typ() -> None:
    legend = ActivityLegend(
        (
            ActivityCode("a", ("utp{n}m", "instutp{n}"), ColumnByNumber((NumberRange(1, 15, "AL"), NumberRange(16, 30, "AJ"))), 2),
            ActivityCode("b", ("spawpg",), FixedColumn("AB"), amount=70, fills=(CellFill("AS", FillColour.RED),)),
            ActivityCode("c", ("instwew{n}m",), fills=(CellFill("AF", FillColour.GREEN),)),
            ActivityCode("d", ("dzielnik1/2",), amount=50),
        )
    )

    assert parse_activity_legend(dump_activity_legend(legend)) == legend
