"""Moduł Legendy czynności na swoim interfejsie (ADR 0038): ``ActivityLegend.read`` i parser pliku ``legenda-czynnosci.yaml``.

Moduł jest szwem: liczą nim Przygotowanie pliku zbiorczego, Ilości do uzupełnienia, Kontrola ilości, podgląd zmiany
legendy, brama i Wpisanie raportów, więc macierz reguł jest tu raz. Oczekiwania pochodzą z maila taty z 15.11.2026,
ADR 0039 (w kolumnie zawsze tylko 1, kwoty w ``AS`` się sumują), ADR 0041 (zwykły opis obok kodów nie jest błędem,
własny zapis kodu to zwykły opis, Błąd opisu to tylko kod z liczbą spoza przedziałów, kolumna trafiona drugi raz i dwa
kolory) i opisu modułu ``activity_legend``. Przykłady Hypothesis są deterministyczne (``derandomize=True``, bez bazy
przykładów).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from itertools import product
import re

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from rozliczenia.activity_legend import (
    NO_CODES,
    NUMBER,
    ActivityCode,
    ActivityLegend,
    CellFill,
    ColumnByNumber,
    ColumnTwice,
    DescriptionError,
    DescriptionRead,
    FillColour,
    FixedColumn,
    LegendProblem,
    LegendRefused,
    NumberOutOfRange,
    NumberRange,
    TwoColours,
    WithCodes,
)
from rozliczenia.activity_legend_file import DEFAULT_ACTIVITY_LEGEND, dump_activity_legend, parse_activity_legend

PROPERTY = settings(derandomize=True, database=None, deadline=None, max_examples=200)


def _read(text: str) -> DescriptionRead:
    return DEFAULT_ACTIVITY_LEGEND.read(text, fault=False)


def _codes(text: str) -> WithCodes:
    read = _read(text)
    assert isinstance(read, WithCodes), read
    return read


def _problems(text: str, legend: ActivityLegend = DEFAULT_ACTIVITY_LEGEND) -> tuple[object, ...]:
    read = legend.read(text, fault=False)
    assert isinstance(read, DescriptionError), read
    return read.problems


@pytest.mark.parametrize(
    ("text", "column"),
    [
        ("instutp1m", "AL"),
        ("instutp15m", "AL"),
        ("instutp16m", "AJ"),
        ("instutp30m", "AJ"),
        ("instwewrg610m", "AK"),
        ("instwewrg611m", "AL"),
        ("instwewrg615m", "AL"),
        ("instwewrg616m", "AJ"),
        ("instwewrg630m", "AJ"),
    ],
)
def test_liczba_z_kodu_wybiera_kolumne_przedzialem(text: str, column: str) -> None:
    assert dict(_codes(text).quantities) == {column: 1}


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("instutp0m", NumberOutOfRange("instutp", "instutp{n}m", 0)),
        ("instutp31m", NumberOutOfRange("instutp", "instutp{n}m", 31)),
        ("instwewrg60m", NumberOutOfRange("instwewrg6", "instwewrg6{n}m", 0)),
        ("instwewrg631m", NumberOutOfRange("instwewrg6", "instwewrg6{n}m", 31)),
    ],
)
def test_liczba_spoza_przedzialow_to_blad_opisu_z_kodem_i_liczba(text: str, problem: NumberOutOfRange) -> None:
    assert _problems(text) == (problem,)


@pytest.mark.parametrize(
    "text",
    [
        "inst 20m",
        "Inst 20 m",
        "spaw pg",
        "dzielnik 1/2",
        "spawpgspawez",
        "inst20mspawpg",
        "xinst20m",
        "ąinst20m",
        "2inst20m",
        "Montażinst20m",
        "inst20m/spawpg",
        "rt25",
        "art2",
        "instmdic",
        "dzielnika1/2",
        "pz",
        "instwew",
    ],
)
def test_slowo_ktore_nie_jest_w_calosci_zapisem_kodu_to_zwykly_opis_bez_dopasowania_samo_i_obok_kodu(text: str) -> None:
    assert _read(text) == NO_CODES
    assert _read(f"spawgnd {text}") == _read("spawgnd")


@pytest.mark.parametrize(
    "text",
    ["montaż ONT", "utp18m", "tak, wymiana routera", "Podłączyłem lokal, klient zadowolony", "", "   ", "tak", "Nie.", "TAK, nie!", "-", "/ /", "\n"],
)
def test_opis_bez_zadnego_kodu_to_brak_kodu_bez_bledu_opisu(text: str) -> None:
    read = _read(text)

    assert (read, read.spelled) == (NO_CODES, ())


@pytest.mark.parametrize(
    "text",
    ["inst30m Podłączyłem lokal, klient zadowolony.", "Podłączyłem lokal: inst30m", "tak inst30m instmdic", "INST30M - dzielnik 1/2"],
)
def test_zwykly_opis_obok_kodu_wyznacza_to_samo_co_sam_kod(text: str) -> None:
    read, alone = _codes(text), _codes("inst30m")

    assert (dict(read.quantities), read.amount, dict(read.fills), read.found) == (
        dict(alone.quantities),
        alone.amount,
        dict(alone.fills),
        alone.found,
    )


@pytest.mark.parametrize(
    ("text", "spelled"),
    [
        ("inst30m instmdic", ("inst30m",)),
        ("Spawpg, montaż INST025m dzielnik1/2", ("spawpg", "inst25m", "dzielnik1/2")),
        ("instutp40m i spawpg", ("instutp40m", "spawpg")),
        ("inst20m inst30m", ("inst20m", "inst30m")),
    ],
)
def test_kody_z_opisu_w_zapisie_legendy_w_kolejnosci_z_opisu_takze_przy_bledzie_opisu(text: str, spelled: tuple[str, ...]) -> None:
    assert _read(text).spelled == spelled


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("instmdik inst20m", ColumnTwice("Y", ("instmdik", "inst"))),
        ("inst20m inst30m", ColumnTwice("Y", ("inst", "inst"))),
        ("inst20m, inst20m", ColumnTwice("Y", ("inst", "inst"))),
        ("spawpg spawez", ColumnTwice("AB", ("spawpg", "spawez"))),
        ("instutp12m instwewrg612m", ColumnTwice("AL", ("instutp", "instwewrg6"))),
        ("rt2 bypas5m", ColumnTwice("AM", ("rt2", "bypas"))),
    ],
)
def test_drugi_kod_w_tej_samej_kolumnie_ilosci_uslug_to_blad_opisu_takze_ten_sam_kod(text: str, problem: ColumnTwice) -> None:
    assert _problems(text) == (problem,)


def test_kwoty_w_as_sie_sumuja_takze_tego_samego_kodu_i_nie_sa_bledem() -> None:
    assert (_codes("spawpg dzielnik1/2").amount, _codes("dzielnik1/2, dzielnik1/2").amount) == (120, 100)
    assert _codes("pz15m pz20m").amount == 960


def test_rozne_kody_w_roznych_kolumnach_wyznaczaja_kazdy_swoje() -> None:
    read = _codes("spawpg, dzielnik1/2 inst25m instutp17m rt2")

    assert dict(read.quantities) == {"Y": 1, "AB": 1, "AJ": 1, "AM": 1}
    assert read.amount == 120
    assert dict(read.fills) == {"AF": FillColour.GREEN, "AM": FillColour.RED, "AS": FillColour.RED}
    assert [found.code for found in read.found] == ["spawpg", "dzielnik1/2", "inst", "instutp", "rt2"]


_RT2_OUTSIDE_FAULTS = ActivityLegend(
    tuple(replace(code, counts_in_fault=False) if code.id == "rt2" else code for code in DEFAULT_ACTIVITY_LEGEND.codes)
)


@pytest.mark.parametrize("text", ["rt2", "RT2, wymiana kabla", "rt2 rt2"])
def test_kod_ktory_w_usterce_sie_nie_liczy_jest_w_usterce_kodem_bez_ilosci_kwoty_i_kolorow(text: str) -> None:
    read = _RT2_OUTSIDE_FAULTS.read(text, fault=True)

    assert isinstance(read, WithCodes), read
    assert (dict(read.quantities), read.amount, dict(read.fills), set(read.spelled)) == ({}, 0, {}, {"rt2"})


@pytest.mark.parametrize(
    ("text", "alone"),
    [("rt2 bypas5m", "bypas5m"), ("rt2 instwew15m spawpg", "instwew15m spawpg"), ("instutp40m rt2", "instutp40m")],
)
def test_kod_ktory_w_usterce_sie_nie_liczy_nie_zmienia_w_usterce_wyniku_innych_kodow(text: str, alone: str) -> None:
    read, without = _RT2_OUTSIDE_FAULTS.read(text, fault=True), _RT2_OUTSIDE_FAULTS.read(alone, fault=True)

    if isinstance(without, DescriptionError):
        assert isinstance(read, DescriptionError) and read.problems == without.problems
    else:
        assert isinstance(read, WithCodes) and isinstance(without, WithCodes)
        assert (dict(read.quantities), read.amount, dict(read.fills)) == (dict(without.quantities), without.amount, dict(without.fills))


@pytest.mark.parametrize("text", ["rt2", "rt2 bypas5m", "spawpg rt2"])
def test_poza_usterka_i_przy_kodzie_ktory_liczy_sie_w_usterce_wynik_jest_jak_bez_usterki(text: str) -> None:
    outside = _RT2_OUTSIDE_FAULTS.read(text, fault=False)

    assert outside == DEFAULT_ACTIVITY_LEGEND.read(text, fault=False) == DEFAULT_ACTIVITY_LEGEND.read(text, fault=True)


def _coloured(column: str) -> ActivityLegend:
    """Trzy kody, które wypełniają kolumnę ``column``: zielony, czerwony i drugi zielony."""

    return ActivityLegend(
        (
            ActivityCode("zielony", ("zielony",), fills=(CellFill(column, FillColour.GREEN),)),
            ActivityCode("czerwony", ("czerwony",), fills=(CellFill(column, FillColour.RED),)),
            ActivityCode("tez-zielony", ("tezzielony",), fills=(CellFill(column, FillColour.GREEN),)),
        )
    )


@pytest.mark.parametrize("column", ["AF", "AS"])
def test_dwa_rozne_kolory_w_jednej_kolumnie_to_blad_opisu_a_ten_sam_kolor_dwa_razy_nie(column: str) -> None:
    legend = _coloured(column)

    assert _problems("zielony czerwony zielony", legend) == (TwoColours(column, ("zielony", "czerwony", "zielony")),)
    read = legend.read("zielony tezzielony", fault=False)
    assert isinstance(read, WithCodes) and dict(read.fills) == {column: FillColour.GREEN}


def test_powody_bledu_ida_najpierw_kodami_spoza_przedzialow_w_kolejnosci_z_opisu_potem_kolumnami_kazdy_raz() -> None:
    assert _problems("instmdik montaż instutp40m inst20m instwewrg60m instutp40m") == (
        NumberOutOfRange("instutp", "instutp{n}m", 40),
        NumberOutOfRange("instwewrg6", "instwewrg6{n}m", 0),
        ColumnTwice("Y", ("instmdik", "inst")),
    )


_ONLY_ONE = "a słowo w opisie może pasować tylko do jednego zapisu."


@pytest.mark.parametrize(
    ("codes", "field", "message"),
    [
        (
            (ActivityCode("inst", ("inst{n}m",), FixedColumn("Y")), ActivityCode("inst20", ("inst20m",), FixedColumn("AA"))),
            "kody[inst20].zapisy[0]",
            f"Zapis „inst20m” i zapis „inst#m” kodu „inst#m” pasują do tego samego słowa „inst20m”, {_ONLY_ONE}",
        ),
        (
            (ActivityCode("rt2", ("rt2",), FixedColumn("AM")), ActivityCode("rt", ("rt{n}",), FixedColumn("AK"))),
            "kody[rt].zapisy[0]",
            f"Zapis „rt#” i zapis „rt2” kodu „rt2” pasują do tego samego słowa „rt2”, {_ONLY_ONE}",
        ),
        (
            (ActivityCode("utp", ("utp{n}m", "utp1{n}m"), ColumnByNumber((NumberRange(1, 15, "AL"), NumberRange(16, 30, "AJ")))),),
            "kody[utp].zapisy[1]",
            f"Zapis „utp1#m” i zapis „utp#m” tego kodu pasują do tego samego słowa „utp11m”, {_ONLY_ONE}",
        ),
        (
            (ActivityCode("spawpg", ("spawpg", "spawpg"), FixedColumn("AB")),),
            "kody[spawpg].zapisy[1]",
            "Zapis „spawpg” jest w tym kodzie dwa razy.",
        ),
        (
            (ActivityCode("spawpg", ("spawpg",), FixedColumn("AB")), ActivityCode("spawez", ("spawez", "spawpg"), FixedColumn("AB"))),
            "kody[spawez].zapisy[1]",
            "Zapis „spawpg” ma już kod „spawpg”.",
        ),
    ],
)
def test_legenda_z_dwoma_zapisami_do_tego_samego_slowa_nie_powstaje_a_zdanie_podaje_to_slowo(
    codes: tuple[ActivityCode, ...], field: str, message: str
) -> None:
    with pytest.raises(LegendRefused) as refused:
        ActivityLegend(codes)

    assert refused.value.problem == LegendProblem(field, message)


@pytest.mark.parametrize("word", ["tak", "nie"])
def test_legenda_z_zapisem_tak_albo_nie_nie_powstaje_bo_ten_zapis_nigdy_niczego_nie_wpisze(word: str) -> None:
    """Słowa ``tak`` i ``nie`` mogą stać w opisie obok kodów i nie są kodem (ADR 0039), więc kod z takim zapisem nigdy
    niczego by nie wpisał: legenda go nie przyjmuje, a zdanie przy polu zapisu mówi tacie dlaczego."""

    codes = (ActivityCode("inst", ("inst{n}m",), FixedColumn("Y")), ActivityCode("zgoda", ("spawpg", word), FixedColumn("AB")))

    with pytest.raises(LegendRefused) as refused:
        ActivityLegend(codes)

    assert refused.value.problem == LegendProblem(
        "kody[zgoda].zapisy[1]",
        f"Zapis „{word}” to słowo, które w opisie może stać obok kodów i nie jest kodem, więc ten zapis nigdy niczego nie "
        "wpisze.",
    )


# Zapisy z małego alfabetu, żeby dwa z nich często pasowały do tego samego słowa: od „a”, z „a”, „b”, „1” i „2” i
# najwyżej jednym miejscem na liczbę.
_SMALL_SPELLING = st.builds(
    lambda head, number, tail: f"a{head}{NUMBER if number else ''}{tail}",
    st.text(alphabet="ab12", max_size=2),
    st.booleans(),
    st.text(alphabet="ab12", max_size=2),
)


def _words(spelling: str, other: str) -> Iterator[str]:
    """Słowa zapisu ``spelling``, wśród których jest każde słowo wspólne z zapisem ``other``, jeśli jakieś istnieje: liczba
    z cyfr 0, 1 i 2 o najwyżej tylu cyfrach, ile cyfr ma ``other`` poza liczbą, i jednej więcej (cyfrę liczby ``other``
    zastępuje jedna cyfra)."""

    if NUMBER not in spelling:
        yield spelling
        return
    longest = sum(char.isdigit() for char in other.replace(NUMBER, "")) + 1
    for size in range(1, longest + 1):
        for digits in product("012", repeat=size):
            yield spelling.replace(NUMBER, "".join(digits))


def _matches(spelling: str, word: str) -> bool:
    return re.fullmatch("[0-9]+".join(re.escape(part) for part in spelling.split(NUMBER)), word) is not None


@PROPERTY
@given(first=_SMALL_SPELLING, second=_SMALL_SPELLING)
def test_legenda_odmawia_dokladnie_wtedy_gdy_jakies_slowo_pasuje_do_obu_zapisow(first: str, second: str) -> None:
    common = [word for word in _words(first, second) if _matches(second, word)]
    codes = (ActivityCode("a", (first,), FixedColumn("Y")), ActivityCode("b", (second,), FixedColumn("AB")))

    try:
        ActivityLegend(codes)
    except LegendRefused as refused:
        assert common, refused.problem
        assert refused.problem.field == "kody[b].zapisy[0]"
    else:
        assert common == []


_SPELLINGS = tuple(spelling for code in DEFAULT_ACTIVITY_LEGEND.codes for spelling in code.spellings)
# Zapis z Legendy z Wydania z liczbą z przedziałów (1–30 pasuje do każdego kodu z przedziałami).
_CODE = st.sampled_from(_SPELLINGS).flatmap(lambda spelling: st.integers(1, 30).map(lambda number: spelling.replace(NUMBER, str(number))))
_BETWEEN = st.lists(st.sampled_from((" ", ", ", ". ", "; ", " tak ", " nie ", " TAK, ", " - ", "!", "\n", " / ")), min_size=1, max_size=3)
# Litery i cyfry tekstu Wykonawcy; poza nimi są litery, które ``casefold`` rozkłada na literę i znak diakrytyczny (``İ``).
_WORD_CHARACTERS = "abcdefghijklmnopqrstuvwxyząćęłńóśźżABCDEFGHIJKLMNOPQRSTUVWXYZĄĆĘŁŃÓŚŹŻ0123456789"


@st.composite
def _cased(draw: st.DrawFn, code: str) -> str:
    """Kod tak, jak mógł go zapisać Wykonawca na telefonie: każda litera małą albo wielką."""

    upper = draw(st.integers(0, 2 ** len(code) - 1))
    return "".join(char.upper() if upper >> index & 1 else char for index, char in enumerate(code))


def _one_per_column(codes: list[str]) -> bool:
    read = _read(" ".join(codes))
    return isinstance(read, WithCodes)


@PROPERTY
@given(data=st.data(), codes=st.lists(_CODE, min_size=1, max_size=4))
def test_wielkosc_liter_interpunkcja_tak_i_nie_nie_zmieniaja_wyniku_samych_kodow(data: st.DataObject, codes: list[str]) -> None:
    assume(_one_per_column(codes))
    plain = _codes(" ".join(codes))
    written = "".join("".join(data.draw(_BETWEEN)) + data.draw(_cased(code)) for code in codes)

    read = _codes(written + "".join(data.draw(_BETWEEN)))

    assert (dict(read.quantities), read.amount, dict(read.fills)) == (dict(plain.quantities), plain.amount, dict(plain.fills))


@PROPERTY
@given(
    data=st.data(),
    codes=st.lists(_CODE, min_size=0, max_size=3),
    word=st.text(alphabet=_WORD_CHARACTERS, min_size=1, max_size=12),
)
def test_slowo_spoza_legendy_w_dowolnym_miejscu_opisu_nie_zmienia_wyniku(
    data: st.DataObject, codes: list[str], word: str
) -> None:
    assume(_read(word) == NO_CODES)
    position = data.draw(st.integers(0, len(codes)))
    words = [*codes[:position], word, *codes[position:]]

    read = _read(data.draw(st.sampled_from((" ", ", ", ".\n"))).join(words))

    assert read == _read(" ".join(codes))


@PROPERTY
@given(first=_CODE, second=_CODE)
def test_kody_sklejone_bez_odstepu_to_jedno_slowo_zwyklego_opisu(first: str, second: str) -> None:
    assert _read(first + second) == NO_CODES


@PROPERTY
@given(word=st.text(alphabet=_WORD_CHARACTERS, min_size=1, max_size=12), code=_CODE)
def test_kod_w_srodku_albo_na_koncu_dluzszego_slowa_nie_jest_kodem(word: str, code: str) -> None:
    assert _read(word + code) == NO_CODES
    assert _read(code + word) == NO_CODES


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
        (_document({"id": "a", "zapisy": ["x"], "kolumna": "Y", "w_usterce": "nie"}), "kody[a].w_usterce"),
        (_document({"id": "a", "zapisy": ["x"], "kolumna": "Y", "w_usterce": 0}), "kody[a].w_usterce"),
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
            ActivityCode("e", ("rt2",), FixedColumn("AM"), counts_in_fault=False),
        )
    )

    assert parse_activity_legend(dump_activity_legend(legend)) == legend
