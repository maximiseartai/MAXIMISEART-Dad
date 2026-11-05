"""Reguły, które dopasowują tekst z plików taty, jako własności Hypothesis: położenie, interpunkcja, wielkość liter.

Recenzje łapały reguły sprawdzone tylko w jednym położeniu tekstu: słowo wyłącznie na początku i nigdy z przecinkiem
zaraz po nim (#460, ``technicolor,`` z Rejestru), fraza ``akt int`` jako fragment (#473), warianty dopisku ``S.A.`` i
wielkość liter (#557). Reguła danych (ADR 0025) maskuje telefony, ulice i wartości ``ADRES`` w wolnym tekście taty. Tu każda reguła dostaje wygenerowany zapis tego samego zlecenia, a oczekiwanie pochodzi z
GLOSSARY.md, ADR 0012, 0018 i 0019 oraz docstringów: zwykle to wynik tej samej reguły dla zapisu kanonicznego.

Przykłady są deterministyczne (``derandomize=True``, bez bazy przykładów), więc każdy przebieg i CI sprawdzają te same.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path
import re

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from rozliczenia import client_data
from rozliczenia.engine import run_settlements
from rozliczenia.quantity_rules import OrderContent, QuantityColumn, RuleResult, WithoutRule, evaluate
from rozliczenia.raw_orders import (
    SHIFT,
    CellFacts,
    OrderColumns,
    Placement,
    RawBlock,
    RowFacts,
    plan_day,
    recognize,
    shifts,
)
from tests.fixtures.formy_telefonu import MASKED, PHONE
from tests.fixtures.settlement import CellValue, make_fixture, write_quantity_source

PROPERTY = settings(derandomize=True, database=None, deadline=None, max_examples=100)

# Składniki URZĄDZENIA z instrukcji taty (spec #268) i z docstringu Reguł ilości, w zapisie z Rejestru.
COMPONENTS = (
    "nokia",
    "nokia zte",
    "nokia getewayHomeBox",
    "technicolor",
    "gateway",
    "zyxel",
    "fut",
    "globo",
    "stb2",
    "wifi6extra",
    "usterka",
    "usterka hurt",
    "usterka wew",
    "gniazdo",
    "zmiana instalacji w lokalu abonenta",
    "instalacja ręczna",
    "wizja",
)
# Litery bez ``x``, bo doklejone ``xg`` znika z URZĄDZENIA (docstring Reguł ilości).
LETTERS = "abcdefghijklmnopqrstuvwyząćęłńóśźżABCDEFGHIJKLMNOPQRSTUVWYZĄĆĘŁŃÓŚŹŻ"
SEPARATORS = (" ", "  ", ",", ", ", " ,", ",,", " , ")
TUESDAY_MORNING = datetime(2026, 10, 27, 9)


def _rules(devices: str, activities: str = "") -> RuleResult:
    return evaluate(OrderContent.of("", devices, activities, TUESDAY_MORNING))


@st.composite
def _mixed_case(draw: st.DrawFn, text: str) -> str:
    upper = draw(st.integers(0, 2 ** len(text) - 1))
    return "".join(char.upper() if upper >> index & 1 else char.lower() for index, char in enumerate(text))


@st.composite
def _written(draw: st.DrawFn, components: Sequence[tuple[int, str]]) -> str:
    """URZĄDZENIA tak, jak mógł je zapisać technik: wielkość liter, przecinki i spacje, ``n*`` ze spacjami, ``xg``."""

    text = draw(st.sampled_from(("", " ", ",")))
    for count, name in components:
        if count > 1:
            text += f"{count}{draw(st.sampled_from(('', ' ')))}*{draw(st.sampled_from(('', ' ')))}"
        words = draw(_mixed_case(name)).split(" ")
        text += words[0] + "".join(draw(st.sampled_from(SEPARATORS)) + word for word in words[1:])
        text += draw(st.sampled_from(("", "", "xg", "XG", "Xg", " xg", ",XG")))
        text += draw(st.sampled_from(SEPARATORS))
    return text


def _canonical(components: Sequence[tuple[int, str]]) -> str:
    return " ".join(f"{count}*{name}" if count > 1 else name for count, name in components)


_COUNTED_COMPONENTS = st.lists(st.tuples(st.integers(1, 3), st.sampled_from(COMPONENTS)), min_size=1, max_size=4)


@PROPERTY
@given(st.data(), _COUNTED_COMPONENTS)
def test_reguly_ilosci_czytaja_urzadzenia_bez_wielkosci_liter_z_przecinkami_jak_spacjami_i_bez_doklejonego_xg(
    data: st.DataObject, components: list[tuple[int, str]]
) -> None:
    written = data.draw(_written(components))

    assert _rules(written) == _rules(_canonical(components))


@PROPERTY
@given(_COUNTED_COMPONENTS.flatmap(lambda components: st.tuples(st.just(components), st.permutations(components))))
def test_skladnik_urzadzen_daje_te_same_ilosci_uslug_w_kazdym_miejscu_urzadzen(
    orders: tuple[list[tuple[int, str]], list[tuple[int, str]]],
) -> None:
    components, reordered = orders

    assert _rules(_canonical(reordered)) == _rules(_canonical(components))


@PROPERTY
@given(st.data(), st.lists(st.sampled_from(COMPONENTS), min_size=1, max_size=4))
def test_skladnik_z_doklejonymi_literami_to_skladnik_ktorego_reguly_ilosci_nie_znaja(
    data: st.DataObject, components: list[str]
) -> None:
    glued = data.draw(st.integers(0, len(components) - 1))
    before = data.draw(st.text(LETTERS, max_size=3))
    after = data.draw(st.text(LETTERS, min_size=0 if before else 1, max_size=3))
    words = components[glued].split(" ")
    words[0] = before + words[0]
    words[-1] += after
    devices = " ".join([*components[:glued], " ".join(words), *components[glued + 1 :]])

    assert isinstance(_rules(devices), WithoutRule), devices


# Tekst CZYNNOŚCI bez ``k``, więc bez frazy ``akt int``.
WITHOUT_PHRASE = "abcdefghijlmnopqrstuvwxyzABCDEFGHIJLMNOPQRSTUVWXYZąćęłńóśźżĄĆĘŁŃÓŚŹŻ 0123456789,.;:-()/"


@PROPERTY
@given(
    st.data(),
    st.integers(1, 3),
    st.text(WITHOUT_PHRASE, max_size=8),
    st.text(WITHOUT_PHRASE, max_size=8),
)
def test_samo_nokia_z_akt_int_w_dowolnym_miejscu_czynnosci_daje_jedno_o_na_zlecenie(
    data: st.DataObject, pieces: int, before: str, after: str
) -> None:
    devices = data.draw(st.sampled_from((" ".join(["nokia"] * pieces), f"{pieces}*nokia", ", ".join(["NOKIA"] * pieces))))
    phrase = data.draw(_mixed_case("akt" + data.draw(st.sampled_from((" ", "  ", "   "))) + "int"))
    again = data.draw(st.sampled_from(("", " akt int", ",AKT INT")))

    with_phrase = _rules(devices, before + phrase + after + again)

    assert with_phrase.quantities.get(QuantityColumn.O) == 1, (devices, before + phrase + after + again)
    assert with_phrase == _rules(devices, "akt int")
    assert QuantityColumn.O not in _rules(devices, before + after).quantities


# Ilości tylko dla INEA (ADR 0018): kolumna → słowo w URZĄDZENIA. Oba słowa mają ``o``, a wypełnienie wiersza nie,
# więc wiersz zawiera słowo tylko wtedy, gdy test je wstawił.
INEA_ONLY = {"AP": "gniazdo", "AK": "technicolor"}
FILLER = "abcdefghijklmnpqrstuvwxyząćęłńśźż0123456789*"


@st.composite
def _inea_row(draw: st.DrawFn) -> tuple[dict[str, CellValue], set[str]]:
    """Wiersz danych z URZĄDZENIA (D), AP i AK oraz kolumnami, których słowo test wstawił do URZĄDZENIA."""

    pieces = draw(st.lists(st.text(FILLER, min_size=1, max_size=6), max_size=3))
    columns = {column for column in INEA_ONLY if draw(st.booleans())}
    for column in sorted(columns):
        word = draw(_mixed_case(INEA_ONLY[column]))
        pieces.append(draw(st.sampled_from(("", ",", "(", "2*", "a", "ż"))) + word + draw(st.sampled_from(("", ",", ".", ")", "y", "ów"))))
    ordered = draw(st.permutations(pieces))
    devices = "".join(piece + draw(st.sampled_from(("", " ", ", ", ","))) for piece in ordered)
    values: dict[str, CellValue] = {column: draw(st.sampled_from((None, 0, 1, 2))) for column in INEA_ONLY}
    return {"D": devices, **values}, columns


def test_ilosci_tylko_dla_inea_przy_slowie_w_dowolnym_miejscu_urzadzen_bez_wzgledu_na_wielkosc_liter_i_liczbe(
    tmp_path: Path,
) -> None:
    source_path, _, config_path = make_fixture(tmp_path)
    template_path = tmp_path / "Wzorzec rozliczenia pracownika.xlsx"

    @settings(PROPERTY, max_examples=12)
    @given(st.lists(_inea_row(), min_size=1, max_size=10))
    def cleared_cells_match_words(rows: list[tuple[dict[str, CellValue], set[str]]]) -> None:
        write_quantity_source(source_path, [cells for cells, _ in rows])

        preview = run_settlements(source_path, config_path, worker_template_path=template_path, dry_run=True)

        expected = {column: sum(1 for cells, words in rows if column in words and cells[column] is not None) for column in INEA_ONLY}
        assert {str(column): count for column, count in preview.inea_only_cleared.items()} == expected, [cells["D"] for cells, _ in rows]

    cleared_cells_match_words()


# Kolumny arkusza zleceń INTERMAX w testach rozpoznania: tylko te, które czyta Kolor operatora i Wpis.
COLUMNS = OrderColumns(first=1, date=2, worker=3, last=8, devices=4, activities=5, contract_number=6)
# Nazwy operatorów z GLOSSARY.md (Kolor operatora, Wpis urządzenia i czynności INTERMAX) w zapisie z niego.
OPERATORS = ("TMOBILE", "T-Mobile", "ORANGE", "Netia", "INEA", "P4", "Plus", "VECTRA", "SYSTEMIA")
WHOLESALE_INSTALLATION = "Instalacja Hurt"
OTHER_OPERATOR = "OXYLION"
# GLOSSARY.md, Kolor operatora: kto ma w ``CZYNNOŚCI`` i ``NUMER UMOWY`` jasny niebieski każdego innego operatora.
LIGHT_BLUE_ACTIVITIES = {"P4", "Plus", "VECTRA", "SYSTEMIA"}
LIGHT_BLUE_CONTRACT_NUMBER = {*LIGHT_BLUE_ACTIVITIES, "Netia"}
# GLOSSARY.md, Wpis urządzenia i czynności INTERMAX: jedyny z ``OPERATORS`` bez Wpisu.
WITHOUT_ENTRY = {"INEA"}


def _placement(activities: str, devices: str) -> Placement:
    """Surowe zlecenie z ``CZYNNOŚCI`` i ``URZĄDZENIA`` z aplikacji na dole arkusza po rozpoznaniu i planie dnia."""

    values = {COLUMNS.date: datetime(2026, 10, 26, 9), COLUMNS.worker: "jan.nowak", COLUMNS.devices: devices, COLUMNS.activities: activities}
    row = RowFacts(30, {column: CellFacts(value, ("Arial", 10.0), False) for column, value in values.items()}, False)
    block = recognize([row], COLUMNS)
    assert isinstance(block, RawBlock), block
    return plan_day(block, [row], COLUMNS, date(2026, 10, 26)).placements[0]


@st.composite
def _spaced(draw: st.DrawFn, name: str) -> str:
    """``name`` w dowolnej wielkości liter ze spacjami i myślnikami między znakami."""

    letters = draw(_mixed_case(name))
    return letters[0] + "".join(draw(st.sampled_from(("", "", " ", "-", " - ", "  "))) + letter for letter in letters[1:])


# Każdy operator osobno: losowanie z listy nie trafiało na Netię (dwa różne Kolory) ani SYSTEMIA (recenzja #631),
# a wynik dla zapisu kanonicznego ma kotwicę w GLOSSARY, bo zepsuty operator psuje też ten wynik.
@pytest.mark.parametrize("name", OPERATORS)
@PROPERTY
@given(data=st.data())
def test_kolor_operatora_i_wpis_nie_zaleza_od_wielkosci_liter_spacji_myslnikow_ani_dopisku_sa(
    data: st.DataObject, name: str
) -> None:
    written = data.draw(_spaced(name))
    suffix = data.draw(st.sampled_from(("", "S.A.", "SA", "S.A", "S. A.")))
    if suffix:
        written += data.draw(st.sampled_from((" ", "-", " - ", "  "))) + data.draw(_mixed_case(suffix))
    written = data.draw(st.sampled_from(("", " ", "  "))) + written + data.draw(st.sampled_from(("", " ", "  ")))

    placed = _placement(written, data.draw(_spaced(WHOLESALE_INSTALLATION)))
    canonical = _placement(name, WHOLESALE_INSTALLATION)
    other = _placement(OTHER_OPERATOR, WHOLESALE_INSTALLATION).color

    assert placed.color == canonical.color, written
    assert (placed.color.activities == other.activities, placed.color.contract_number == other.contract_number) == (
        name in LIGHT_BLUE_ACTIVITIES,
        name in LIGHT_BLUE_CONTRACT_NUMBER,
    ), written
    if name in WITHOUT_ENTRY:
        assert placed.entry is None, written
    else:
        assert placed.entry is not None, written
        assert canonical.entry is not None
        assert (placed.entry.operator, placed.entry.devices) == (canonical.entry.operator, canonical.entry.devices)
        assert placed.entry.activities == written.strip() + canonical.entry.activities.removeprefix(name)


@PROPERTY
@given(st.sampled_from(OPERATORS), st.text(LETTERS, max_size=3), st.text(LETTERS, max_size=3))
def test_nazwa_operatora_z_doklejonymi_literami_to_inny_operator(name: str, before: str, after: str) -> None:
    assume(before or after)
    # Doklejone ``SA`` (``NetiaSA``) czeka na Decyzję Maksa: GLOSSARY nie mówi, czy dopisek bez spacji to dalej Netia.
    assume(after.casefold() != "sa")
    other = _placement(OTHER_OPERATOR, WHOLESALE_INSTALLATION)

    placed = _placement(before + name + after, WHOLESALE_INSTALLATION)

    assert (placed.color, placed.entry) == (other.color, None), before + name + after


@pytest.mark.parametrize("written", ["NetiaSA", "NetiaS.A."])
@pytest.mark.xfail(strict=True, reason="Decyzja Maksa: czy dopisek S.A. bez spacji przed nim to dalej Netia (GLOSSARY: nazwa nie zależy od spacji)")
def test_netia_z_dopiskiem_sa_bez_spacji_to_netia(written: str) -> None:
    placed, netia = _placement(written, WHOLESALE_INSTALLATION), _placement("Netia", WHOLESALE_INSTALLATION)

    assert placed.color == netia.color
    assert placed.entry is not None


# Reguła danych (ADR 0025, docstring ``client_data``): telefon w tekście z tabeli form telefonu, który strażnik maskuje w
# całości, wzmianka ulicy „ul.”, „os.”, „al.”, „pl.” z nazwą i numerem, wartość ADRES bez wielkości liter i z dowolnymi znakami
# spoza słów między jej słowami: odstępami, końcem linii i tym, czym producent zapisał komórkę (⏎, \| tabeli Markdown).
PHONES = tuple(form.value for form in MASKED if isinstance(form.value, str) and form.masked == PHONE)
STREETS = ("ul. Kwiatowa 5", "ul.Kwiatowa 5/3", "os. Tysiąclecia 12 m 4", "al. 3 Maja 5", "pl. Jana Pawła II 2a")
FREE_TEXT = "abcdefghijklmnopqrstuvwyząćęłńóśźżABCDEFGHIJKLMNOPQRSTUVWYZĄĆĘŁŃÓŚŹŻ .,;:()„”-"
GUARDED_ADDRESS = "Syntetyczna Rubinowa 7/3 Kraków"
BETWEEN_WORDS = (" ", "  ", "\n", " \t", "\r\n", "/", " / ", "-", "⏎", "\\|", "`` ", ", ")


@PROPERTY
@given(
    st.sampled_from(PHONES + STREETS),
    st.text(FREE_TEXT, max_size=12),
    st.sampled_from(("", " ", ",", "(", "„", ": ")),
    st.sampled_from(("", " ", ",", ")", "”", ".")),
    st.text(FREE_TEXT, max_size=12),
    st.data(),
)
def test_telefon_i_ulica_w_dowolnym_miejscu_wolnego_tekstu_sa_zamaskowane_a_reszta_tekstu_zostaje(
    sensitive: str, before: str, opening: str, closing: str, after: str, data: st.DataObject
) -> None:
    assume(not before[-1:].isalnum() or (opening and not opening[-1].isalnum()))
    written = data.draw(_mixed_case(sensitive)) if sensitive in STREETS else sensitive
    mask = "[ulica]" if sensitive in STREETS else "[telefon]"
    assume(not after[:1].isalnum() or (closing and not closing.isalnum()))
    assume(client_data.free_text(before + after) == before + after)

    guarded = client_data.ForbiddenValues().guard(f"{before}{opening}{written}{closing}{after}", "własność")

    assert guarded == client_data.Guarded(f"{before}{opening}{mask}{closing}{after}", ())


@PROPERTY
@given(st.text(FREE_TEXT, max_size=12), st.data())
def test_wartosc_adresu_przeczytana_z_pliku_jest_zamaskowana_w_kazdym_zapisie_z_uwaga_bez_wartosci(
    before: str, data: st.DataObject
) -> None:
    forbidden = client_data.ForbiddenValues()
    forbidden.remember_value(client_data.ForbiddenColumn.ADDRESS, f"  {GUARDED_ADDRESS} ")
    words = re.findall(r"\w+", GUARDED_ADDRESS)
    written = "".join(
        data.draw(_mixed_case(word)) + (data.draw(st.sampled_from(BETWEEN_WORDS)) if index < len(words) - 1 else "")
        for index, word in enumerate(words)
    )
    assume(not before[-1:].isalnum())

    guarded = forbidden.guard(f"{before}{written}, dalej", "komórka L6")

    assert guarded == client_data.Guarded(
        f"{before}[adres], dalej", ("Reguła danych: zamaskowano wartość kolumny ADRES w: komórka L6.",)
    )
    assert forbidden.guard(f"{before}{written}ów", "komórka L6").notes == (), "dłuższe słowo to inny tekst"


# Układ arkusza zleceń taty: A bez nagłówka, DATA GODZ. POCZ. w C, ADRES (zakazana) w E, UWAGI w O.
INTERMAX_COLUMNS = OrderColumns(first=2, date=3, worker=10, last=15, devices=7, activities=8, contract_number=11)
INTERMAX_SHIFTS = shifts([], INTERMAX_COLUMNS, forbidden={5, 11}, headed=set(range(2, 16)))
DATE_TRACES = ("11:00", "11.00", "26.10", "26-10-26", "2026", "26.10.2026 11:00", "2026-10-26")
"""Ślady daty i godziny z docstringu ``raw_orders._DATE_TRACE``."""


def _pasted_row(under_date: object) -> RowFacts:
    """Wklejony wiersz z wyglądem z aplikacji: data z godziną w kolumnie A, a ``under_date`` pod ``DATA GODZ. POCZ.``."""

    look = ("Roboto", 4.0)
    cells = {1: CellFacts(datetime(2026, 10, 26, 11), look, False), 3: CellFacts(under_date, look, False)}
    return RowFacts(12, cells, False)


@PROPERTY
@given(
    st.sampled_from(DATE_TRACES),
    st.text(LETTERS + " ", max_size=8),
    st.sampled_from(("", " ", ",", "(", "godz.", "dn. ")),
    st.sampled_from(("", " ", ",", ")", ".", "r.")),
    st.text(LETTERS + " ", max_size=8),
)
def test_tekst_z_data_albo_godzina_w_dowolnym_miejscu_pod_data_zostawia_wiersz_w_obu_polozeniach(
    trace: str, before: str, opening: str, closing: str, after: str
) -> None:
    """Wiersz bez przesunięcia może mieć w kolumnie bez nagłówka datę z godziną, a pod ``DATA GODZ. POCZ.`` datę jako
    tekst (#917): tekst ze śladem daty albo godziny gdziekolwiek, z literami i interpunkcją wokół, w dowolnej wielkości
    liter, nie przeczy położeniu bez przesunięcia, więc wiersz ma oba położenia (``raw_orders.Shifts``)."""

    assert INTERMAX_SHIFTS.possible(_pasted_row(f"{before}{opening}{trace}{closing}{after}")) == (0, SHIFT)


@pytest.mark.parametrize("under_date", [None, "", "  ", "-", "?", "12", "26 10", 46321, 46321.5])
def test_pusta_data_liczba_albo_tekst_bez_litery_pod_data_zostawia_wiersz_w_obu_polozeniach(under_date: object) -> None:
    """Pusta komórka, liczba i tekst bez litery pod ``DATA GODZ. POCZ.`` mogą być datą wiersza bez przesunięcia, także
    z datą z godziną w kolumnie bez nagłówka, więc nie przeczą temu położeniu i wiersz ma oba (#917)."""

    assert INTERMAX_SHIFTS.possible(_pasted_row(under_date)) == (0, SHIFT)


@pytest.mark.parametrize(
    "address", ["Ulica 101", "Wrzosowa 12/4 Kórnik", "OS. LECHA 3 m. 4", "ul. 3 Maja 12", "62-035 Kórnik, Polna 7"]
)
def test_adres_pod_data_z_data_z_godzina_w_kolumnie_bez_naglowka_to_wiersz_przesuniety(address: str) -> None:
    """Przesunięty pierwszy wiersz wklejenia ma datę z godziną dwie kolumny na lewo od ``DATA GODZ. POCZ.``, a pod nią
    ``ADRES``: tekst z literą bez śladu daty ani godziny, któremu położenie bez przesunięcia przeczy (#917)."""

    assert INTERMAX_SHIFTS.possible(_pasted_row(address)) == (SHIFT,)

