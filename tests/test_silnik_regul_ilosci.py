"""Silnik Reguł ilości (ADR 0033) na swoim interfejsie: ``evaluate``, niezmienniki typów i pliki reguł.

Zachowania, których Reguły ilości z Wydania nie dotykają, więc nie sprawdzają ich testy instrukcji taty
(``test_ilosci_uslug.py``, ``test_ilosci_tylko_dla_inea.py``): pierwszeństwo „``URZĄDZENIA`` są dokładnie tekstem”, trzy zakresy reguły,
zaprzeczenie każdego warunku, zlecenie bez ``DATA``, suma reguł i jej źródła, mnożniki i każda odmowa z polem. Na
końcu jeden przebieg procesów pokazuje, że każdy z nich liczy Regułami ilości ze swojego wejścia.
Oczekiwania pochodzą z ADR 0033 i z docstringów ``quantity_engine``, nie z przebiegu kodu.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, time
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st
from openpyxl import load_workbook
import pytest
import yaml

from rozliczenia import collective_file, quantity_check, tool_files
from rozliczenia.collective_layout import QUANTITY_COLUMNS, QUANTITY_LETTERS
from rozliczenia.collective_preparation import PreparationInputs, prepare_collective_file
from rozliczenia.dad_files import DadFiles
from rozliczenia.engine import SettlementInputs, run_settlements
from rozliczenia.order_facts import MissingHeaders
from rozliczenia.quantities_to_fill import FillKind, RowState, fill_hint, quantities_to_fill
from rozliczenia.quantity_engine import (
    ActivitiesContain,
    Component,
    Condition,
    ContainsComponent,
    ContractFirstWord,
    Contribution,
    DeviceGroup,
    DeviceList,
    DevicesText,
    Fill,
    FromDescription,
    HasGroup,
    LeaveEmpty,
    Multiplier,
    OrderContent,
    QuantityRule,
    QuantityRules,
    QuantityRulesRefused,
    RuleResult,
    RulesProblem,
    Scope,
    ServiceQuantities,
    StartedAt,
    TextMode,
    WithoutRule,
    Write,
    WriteNothing,
    evaluate,
    without_components,
)
from rozliczenia.quantity_rules_file import (
    DEFAULT_QUANTITY_RULES,
    dump_device_list,
    dump_quantity_rules,
    parse_device_list,
    parse_quantity_rules,
)
from rozliczenia.run_context import RunContext
from atrapy.preparation import PERIOD, cell_values, make_preparation_fixture, register_order
from atrapy.settlement import worker_list, write_template
from atrapy.workbooks import active_worksheet

DEVICES = DeviceList(
    (
        Component("router", ("ruter", "ruter duzy"), DeviceGroup.ROUTER),
        Component("tv", ("dekoder",), DeviceGroup.TV),
        Component("wzmacniacz", ("wzmacniacz",), DeviceGroup.EXTENDER),
        Component("kabel", ("kabel",)),
    )
)
MONDAY_EVENING = datetime(2026, 11, 9, 18, 30)


def _rules(*rules: QuantityRule) -> QuantityRules:
    return QuantityRules(rules, DEVICES)


def _rule(
    rule_id: str, *conditions: Condition, action: Fill | WriteNothing | LeaveEmpty | None = None, scope: Scope = Scope.EVERY
) -> QuantityRule:
    return QuantityRule(rule_id, conditions, scope, action or _fill("N", 1))


def _fill(column: str, value: int, multiplier: Multiplier = Multiplier.ONCE, component: str | None = None) -> Fill:
    return Fill((Write(column, value, multiplier, component),))


def _order(devices: str, activities: str = "", contract: str = "", started: datetime | None = MONDAY_EVENING) -> OrderContent:
    return OrderContent.of(contract, devices, activities, started)


def _quantities(result: RuleResult) -> dict[str, int]:
    return dict(result.quantities)


def test_pasujace_reguly_sumuja_sie_w_kolumnie_a_wynik_mowi_ktora_regula_ile_dala() -> None:
    rules = _rules(
        _rule("a", ContainsComponent("kabel"), action=_fill("Z", 2)),
        _rule("b", ContainsComponent("kabel"), action=_fill("Z", 3)),
        _rule("c", ContainsComponent("tv"), action=_fill("Z", 5)),
    )

    result = evaluate(rules, _order("kabel"))

    assert isinstance(result, ServiceQuantities)
    assert _quantities(result) == {"Z": 5}
    assert result.contributions == (Contribution("a", "Z", 2), Contribution("b", "Z", 3))
    assert result.fired == ("a", "b")


def test_mnozniki_raz_liczba_skladnika_z_krotnoscia_i_sztuki_z_czynnosci_razy_wystapienia() -> None:
    rules = _rules(
        _rule("raz", action=_fill("Z", 7)),
        _rule("liczba", action=_fill("AE", 2, Multiplier.COMPONENT, "kabel")),
        _rule("sztuki", action=_fill("AN", 1, Multiplier.PIECES, "kabel")),
    )

    result = evaluate(rules, _order("3*kabel 2 * kabel", "kabel 4 szt"))

    assert _quantities(result) == {"Z": 7, "AE": 10, "AN": 8}
    assert _quantities(evaluate(rules, _order("kabel", "bez liczby"))) == {"Z": 7, "AE": 2, "AN": 1}


def test_nic_nie_wpisuj_wygrywa_z_kazda_regula_wpisz_a_zostaw_pusta_dziala_obok() -> None:
    rules = _rules(
        _rule("ilosc", ContainsComponent("kabel"), action=_fill("Z", 1)),
        _rule("dokladnie", DevicesText(TextMode.EXACTLY, "kabel"), action=_fill("AE", 1)),
        _rule("z-opisu", ContainsComponent("kabel"), action=WriteNothing()),
        _rule("inea", DevicesText(TextMode.CONTAINS, "kab"), action=LeaveEmpty(("AP",))),
    )

    result = evaluate(rules, _order("kabel"))

    assert result == FromDescription(frozenset({"AP"}), ("z-opisu", "inea"))
    assert _quantities(result) == {}


def test_dokladnie_tekstem_liczy_tylko_swoje_reguly_bez_p_q_i_s_takze_przy_skladniku_spoza_listy() -> None:
    rules = _rules(
        _rule("suma", ContainsComponent("router"), action=_fill("Z", 1)),
        _rule("dokladnie", DevicesText(TextMode.EXACTLY, "ruter dekoder obcy"), action=_fill("AE", 4)),
        _rule("inea", DevicesText(TextMode.CONTAINS, "dekoder"), action=LeaveEmpty(("AK",))),
    )

    result = evaluate(rules, _order("Ruter, DEKODER  obcy"))

    assert result == ServiceQuantities({"AE": 4}, frozenset({"AK"}), (Contribution("dokladnie", "AE", 4),), ("dokladnie", "inea"))
    assert isinstance(evaluate(rules, _order("ruter dekoder")), ServiceQuantities)
    assert _quantities(evaluate(rules, _order("ruter dekoder"))) == {"Z": 1, "P": 1, "S": 2}


def test_zaprzeczone_dokladnie_tekstem_nie_ma_pierwszenstwa() -> None:
    rules = _rules(
        _rule("suma", ContainsComponent("kabel"), action=_fill("Z", 1)),
        _rule("nie-dokladnie", DevicesText(TextMode.EXACTLY, "ruter", negated=True), action=_fill("AE", 1)),
    )

    assert _quantities(evaluate(rules, _order("kabel"))) == {"Z": 1, "AE": 1}


@pytest.mark.parametrize(
    ("devices", "fired", "kind"),
    [
        ("kabel", ("znane", "kazde"), ServiceQuantities),
        ("kabel obcy", ("nieznane", "kazde"), WithoutRule),
        ("obcy", ("nieznane", "kazde"), WithoutRule),
    ],
)
def test_zakres_reguly_decyduje_czy_dziala_przy_skladniku_spoza_listy(devices: str, fired: tuple[str, ...], kind: type) -> None:
    rules = _rules(
        _rule("znane", scope=Scope.KNOWN),
        _rule("nieznane", scope=Scope.UNKNOWN),
        _rule("kazde", scope=Scope.EVERY),
    )

    result = evaluate(rules, _order(devices))

    assert (type(result), result.fired) == (kind, fired)


def test_przy_skladniku_spoza_listy_warunek_skladnika_widzi_znane_skladniki() -> None:
    rules = _rules(_rule("kabel", ContainsComponent("kabel"), scope=Scope.UNKNOWN))

    assert evaluate(rules, _order("obcy kabel")).fired == ("kabel",)
    assert evaluate(rules, _order("obcy")).fired == ()


# Każdy z sześciu warunków ADR 0033: zlecenie, przy którym jest prawdziwy, i takie, przy którym nie jest.
CONDITIONS = [
    pytest.param(ContainsComponent("kabel"), _order("2*kabel"), _order("ruter"), id="skladnik"),
    pytest.param(DevicesText(TextMode.EMPTY), _order(" , xg"), _order("kabel"), id="puste"),
    pytest.param(DevicesText(TextMode.EXACTLY, "ruter duzy"), _order("RUTER,duzyXG"), _order("ruter duzy kabel"), id="dokladnie"),
    pytest.param(DevicesText(TextMode.CONTAINS, "kab el"), _order("KAB\u00a0 EL2"), _order("kab,el"), id="zawieraja"),
    pytest.param(DevicesText(TextMode.CONTAINS, "łą"), _order("Ł" + "a\u0328"), _order("la"), id="zawieraja-nfd"),
    pytest.param(ActivitiesContain("akt int"), _order("kabel", "xAKT   intx"), _order("kabel", "akt  in t"), id="czynnosci"),
    pytest.param(ContractFirstWord("u"), _order("kabel", contract=" U 12"), _order("kabel", contract="u/12"), id="umowa"),
    pytest.param(
        StartedAt(frozenset({0, 5}), time(17)),
        _order("kabel", started=datetime(2026, 11, 9, 17, 0, 59)),
        _order("kabel", started=datetime(2026, 11, 9, 16, 59, 59)),
        id="data-godzina",
    ),
    pytest.param(
        StartedAt(frozenset({0, 5}), time(17)),
        _order("kabel", started=datetime(2026, 11, 14, 23, 59)),
        _order("kabel", started=datetime(2026, 11, 15, 23, 59)),
        id="data-dzien",
    ),
    pytest.param(HasGroup(DeviceGroup.TV), _order("dekoder"), _order("ruter wzmacniacz"), id="grupa"),
]


@pytest.mark.parametrize(("condition", "holds", "fails"), CONDITIONS)
def test_warunek_dziala_tylko_gdy_jest_prawdziwy_a_zaprzeczony_odwrotnie(
    condition: Condition, holds: OrderContent, fails: OrderContent
) -> None:
    rules = _rules(_rule("warunek", condition))
    negated = _rules(_rule("warunek", type(condition)(**{**vars(condition), "negated": True})))

    assert (evaluate(rules, holds).fired, evaluate(rules, fails).fired) == (("warunek",), ())
    assert (evaluate(negated, holds).fired, evaluate(negated, fails).fired) == ((), ("warunek",))


def test_zlecenie_bez_daty_nie_spelnia_warunku_daty_ani_zaprzeczonego_a_reszta_regul_dziala() -> None:
    late = StartedAt(frozenset(range(7)), time(0))
    rules = _rules(
        _rule("data", late),
        _rule("nie-data", StartedAt(late.days, late.since, negated=True)),
        _rule("inea", DevicesText(TextMode.CONTAINS, "kabel"), action=LeaveEmpty(("AP",))),
    )

    result = evaluate(rules, _order("kabel", started=None))

    assert (result.fired, result.leave_empty) == (("inea",), frozenset({"AP"}))


@pytest.mark.parametrize(
    ("devices", "expected"),
    [
        ("ruter dekoder dekoder", {"P": 1, "Q": 1, "S": 3}),
        ("2*ruter 3*dekoder wzmacniacz", {"P": 1, "Q": 2, "S": 6}),
        ("dekoder dekoder", {"Q": 2, "S": 2}),
        ("ruter wzmacniacz kabel", {"S": 2}),
        ("kabel", {}),
    ],
)
def test_wbudowane_p_q_i_s_pierwszy_tv_do_p_przy_routerze_a_s_to_liczba_urzadzen_z_grup(
    devices: str, expected: dict[str, int]
) -> None:
    assert _quantities(evaluate(_rules(), _order(devices))) == expected


def test_przy_skladniku_spoza_listy_nie_ma_p_q_ani_s() -> None:
    result = evaluate(_rules(), _order("ruter dekoder obcy"))

    assert (type(result), _quantities(result)) == (WithoutRule, {})


def test_skladnik_to_najdluzszy_zapis_od_lewej_a_krotnosc_tylko_przed_pierwszym_slowem() -> None:
    rules = _rules(
        _rule("ruter", action=_fill("O", 1, Multiplier.COMPONENT, "router")),
        _rule("kabel", action=_fill("Z", 1, Multiplier.COMPONENT, "kabel")),
    )

    assert _quantities(evaluate(rules, _order("2*ruter duzy kabel"))) == {"O": 2, "Z": 1, "S": 2}
    assert isinstance(evaluate(rules, _order("ruter 2*duzy")), WithoutRule)
    assert isinstance(evaluate(rules, _order("0*kabel")), WithoutRule)


def test_kolumny_regul_i_kolumny_wiersza_bez_reguly_wynikaja_z_regul() -> None:
    rules = _rules(
        _rule("t", scope=Scope.UNKNOWN, action=_fill("T", 1)),
        _rule("z", scope=Scope.KNOWN, action=_fill("Z", 1)),
        _rule("v", scope=Scope.EVERY, action=Fill((Write("V", 1), Write("T", 1)))),
        _rule("inea", action=LeaveEmpty(("AK",))),
        _rule("inea-2", action=LeaveEmpty(("AE", "AK"))),
    )

    assert rules.rule_columns == ("P", "Q", "S", "T", "V", "Z")
    assert rules.without_rule_columns == ("T", "V")
    assert rules.leave_empty_columns == ("AK", "AE")


def test_reguly_z_wydania_licza_dzisiejsze_kolumny_kontroli_ilosci() -> None:
    assert DEFAULT_QUANTITY_RULES.rule_columns == (
        "N", "O", "P", "Q", "S", "T", "V", "Z", "AE", "AG", "AI", "AK", "AM", "AN", "AO", "AP",
    )  # fmt: skip
    assert DEFAULT_QUANTITY_RULES.without_rule_columns == ("V", "T", "N")
    assert DEFAULT_QUANTITY_RULES.leave_empty_columns == ("AP", "AK")


def _device_list(*components: Component) -> DeviceList:
    return DeviceList(components)


@pytest.mark.parametrize(
    ("build", "field"),
    [
        pytest.param(lambda: _device_list(Component("", ("a",))), "urzadzenia[].id", id="skladnik-bez-nazwy"),
        pytest.param(lambda: _device_list(Component("a", ("a",)), Component("a", ("b",))), "urzadzenia[a].id", id="dwa-razy"),
        pytest.param(lambda: _device_list(Component("a", ())), "urzadzenia[a].zapisy", id="bez-zapisu"),
        pytest.param(lambda: _device_list(Component("a", ("Kabel",))), "urzadzenia[a].zapisy", id="wielka-litera"),
        pytest.param(lambda: _device_list(Component("a", ("kabel  2",))), "urzadzenia[a].zapisy", id="dwie-spacje"),
        pytest.param(lambda: _device_list(Component("a", ("kabelxg",))), "urzadzenia[a].zapisy", id="xg"),
        pytest.param(lambda: _device_list(Component("a", ("2*kabel",))), "urzadzenia[a].zapisy", id="gwiazdka"),
        pytest.param(lambda: _device_list(Component("a", ("kabel",)), Component("b", ("kabel",))), "urzadzenia[b].zapisy", id="zapis-u-dwoch"),
        pytest.param(lambda: _rules(_rule("x"), _rule("x")), "reguly[x].id", id="regula-dwa-razy"),
        pytest.param(lambda: _rules(_rule(" x")), "reguly[ x].id", id="regula-ze-spacja"),
        pytest.param(lambda: _rules(_rule("x", ContainsComponent("brak"))), "reguly[x].jesli[0].skladnik", id="nieznany-skladnik"),
        pytest.param(lambda: _rules(_rule("x", DevicesText(TextMode.EMPTY, "a"))), "reguly[x].jesli[0].tekst", id="puste-z-tekstem"),
        pytest.param(lambda: _rules(_rule("x", DevicesText(TextMode.EXACTLY, ""))), "reguly[x].jesli[0].tekst", id="dokladnie-pusty"),
        pytest.param(lambda: _rules(_rule("x", DevicesText(TextMode.EXACTLY, "a,b"))), "reguly[x].jesli[0].tekst", id="dokladnie-przecinek"),
        pytest.param(lambda: _rules(_rule("x", DevicesText(TextMode.CONTAINS, "Ab"))), "reguly[x].jesli[0].tekst", id="zawieraja-wielka"),
        pytest.param(lambda: _rules(_rule("x", ActivitiesContain("akt  int"))), "reguly[x].jesli[0].tekst", id="czynnosci-spacje"),
        pytest.param(lambda: _rules(_rule("x", ContractFirstWord("u 1"))), "reguly[x].jesli[0].slowo", id="umowa-dwa-slowa"),
        pytest.param(lambda: _rules(_rule("x", StartedAt(frozenset(), time(1)))), "reguly[x].jesli[0].dni", id="bez-dni"),
        pytest.param(lambda: _rules(_rule("x", StartedAt(frozenset({-1}), time(1)))), "reguly[x].jesli[0].dni", id="dzien-minus-1"),
        pytest.param(lambda: _rules(_rule("x", StartedAt(frozenset({7}), time(1)))), "reguly[x].jesli[0].dni", id="dzien-7"),
        pytest.param(lambda: _rules(_rule("x", StartedAt(frozenset({True}), time(1)))), "reguly[x].jesli[0].dni", id="dzien-true"),
        pytest.param(lambda: _rules(_rule("x", StartedAt(frozenset({False}), time(1)))), "reguly[x].jesli[0].dni", id="dzien-false"),
        pytest.param(lambda: _rules(_rule("x", StartedAt(frozenset({1}), time(1, 0, 5)))), "reguly[x].jesli[0].od", id="sekundy"),
        pytest.param(lambda: _rules(_rule("x", action=Fill(()))), "reguly[x].to.wpisy", id="wpisz-bez-kolumny"),
        pytest.param(lambda: _rules(_rule("x", action=_fill("M", 1))), "reguly[x].to.wpisy[0].kolumna", id="kolumna-spoza-n-ap"),
        pytest.param(lambda: _rules(_rule("x", action=_fill("AQ", 1))), "reguly[x].to.wpisy[0].kolumna", id="kolumna-aq"),
        pytest.param(lambda: _rules(_rule("x", action=_fill("S", 1))), "reguly[x].to.wpisy[0].kolumna", id="kolumna-s"),
        pytest.param(lambda: _rules(_rule("x", action=_fill("P", 1))), "reguly[x].to.wpisy[0].kolumna", id="kolumna-p"),
        pytest.param(lambda: _rules(_rule("x", action=_fill("Q", 1))), "reguly[x].to.wpisy[0].kolumna", id="kolumna-q"),
        pytest.param(lambda: _rules(_rule("x", action=_fill("Z", 0))), "reguly[x].to.wpisy[0].wartosc", id="wartosc-0"),
        pytest.param(lambda: _rules(_rule("x", action=_fill("Z", 1000))), "reguly[x].to.wpisy[0].wartosc", id="wartosc-1000"),
        pytest.param(lambda: _rules(_rule("x", action=_fill("Z", True))), "reguly[x].to.wpisy[0].wartosc", id="wartosc-true"),
        pytest.param(lambda: _rules(_rule("x", action=_fill("Z", 1, Multiplier.ONCE, "kabel"))), "reguly[x].to.wpisy[0].skladnik", id="raz-ze-skladnikiem"),
        pytest.param(lambda: _rules(_rule("x", action=_fill("Z", 1, Multiplier.COMPONENT))), "reguly[x].to.wpisy[0].skladnik", id="liczba-bez-skladnika"),
        pytest.param(lambda: _rules(_rule("x", action=_fill("Z", 1, Multiplier.PIECES, "brak"))), "reguly[x].to.wpisy[0].skladnik", id="sztuki-nieznany"),
        pytest.param(lambda: _rules(_rule("x", action=LeaveEmpty(()))), "reguly[x].to.kolumny", id="pusta-bez-kolumny"),
        pytest.param(lambda: _rules(_rule("x", action=LeaveEmpty(("AT",)))), "reguly[x].to.kolumny", id="pusta-spoza-n-ap"),
    ],
)
def test_regula_albo_skladnik_z_bledem_nie_powstaje_a_odmowa_wskazuje_pole(build: object, field: str) -> None:
    assert callable(build)
    with pytest.raises(QuantityRulesRefused) as refused:
        build()

    assert refused.value.problem.field == field
    assert refused.value.problem.message


def test_granice_wartosci_i_kolumn_reguly_sa_dozwolone() -> None:
    rules = _rules(
        _rule("n", action=_fill("N", 1)),
        _rule("ap", action=Fill((Write("AP", 999, Multiplier.COMPONENT, "kabel"),))),
        _rule("inea", action=LeaveEmpty(("N", "AP"))),
        _rule("dni", StartedAt(frozenset({0, 6}), time(23, 59))),
    )

    assert _quantities(evaluate(rules, _order("kabel", started=datetime(2026, 11, 15, 23, 59)))) == {"N": 2, "AP": 999}


def test_reguly_z_wydania_wczytuja_sie_a_zapis_i_odczyt_daja_te_same_reguly() -> None:
    devices = parse_device_list(yaml.safe_load(yaml.safe_dump(dump_device_list(DEFAULT_QUANTITY_RULES.devices), allow_unicode=True)))
    assert devices == DEFAULT_QUANTITY_RULES.devices
    document = yaml.safe_load(yaml.safe_dump(dump_quantity_rules(DEFAULT_QUANTITY_RULES), allow_unicode=True))

    assert parse_quantity_rules(document, devices) == DEFAULT_QUANTITY_RULES
    assert len(DEFAULT_QUANTITY_RULES.rules) == 21
    assert len(DEFAULT_QUANTITY_RULES.devices.components) == 12


def test_kazdy_rodzaj_warunku_i_dzialania_przechodzi_przez_plik_bez_zmiany() -> None:
    rules = _rules(
        _rule(
            "wszystko",
            ContainsComponent("kabel", negated=True),
            DevicesText(TextMode.EMPTY),
            DevicesText(TextMode.EXACTLY, "ruter duzy"),
            DevicesText(TextMode.CONTAINS, "ąę"),
            ActivitiesContain("akt int"),
            ContractFirstWord("u"),
            StartedAt(frozenset({4, 5}), time(7, 5)),
            HasGroup(DeviceGroup.EXTENDER, negated=True),
            action=Fill((Write("Z", 2), Write("AE", 3, Multiplier.PIECES, "kabel"), Write("AG", 1, Multiplier.COMPONENT, "router"))),
            scope=Scope.UNKNOWN,
        ),
        _rule("nic", action=WriteNothing(), scope=Scope.KNOWN),
        _rule("inea", action=LeaveEmpty(("AK", "AP"))),
    )
    text = yaml.safe_dump(dump_quantity_rules(rules), allow_unicode=True)

    assert parse_quantity_rules(yaml.safe_load(text), DEVICES) == rules


def _document(rule: object) -> dict[str, object]:
    return {"schema_version": 1, "reguly": [rule]}


GOOD_RULE: dict[str, object] = {"id": "r", "zakres": "kazde", "jesli": [], "to": {"rodzaj": "nic"}}


@pytest.mark.parametrize(
    ("document", "field"),
    [
        pytest.param(None, "plik", id="pusty-plik"),
        pytest.param({"reguly": []}, "schema_version", id="bez-wersji"),
        pytest.param({"schema_version": 2, "reguly": []}, "schema_version", id="inna-wersja"),
        pytest.param({"schema_version": True, "reguly": []}, "schema_version", id="wersja-true"),
        pytest.param({"schema_version": 1, "reguly": [], "inne": 1}, "inne", id="nieznany-klucz-pliku"),
        pytest.param({"schema_version": 1, "reguly": {}}, "reguly", id="reguly-nie-lista"),
        pytest.param(_document({**GOOD_RULE, "kolejnosc": 1}), "reguly[0].kolejnosc", id="nieznane-pole-reguly"),
        pytest.param(_document({"id": "r", "jesli": [], "to": {"rodzaj": "nic"}}), "reguly[0].zakres", id="brak-zakresu"),
        pytest.param(_document({**GOOD_RULE, "id": 5}), "reguly[0].id", id="id-liczba"),
        pytest.param(_document({**GOOD_RULE, "zakres": "wszystkie"}), "reguly[r].zakres", id="zly-zakres"),
        pytest.param(_document({**GOOD_RULE, "jesli": [{"rodzaj": "kolor"}]}), "reguly[r].jesli[0].rodzaj", id="nieznany-warunek"),
        pytest.param(
            _document({**GOOD_RULE, "jesli": [{"rodzaj": "skladnik", "skladnik": "kabel", "tekst": "a"}]}),
            "reguly[r].jesli[0].tekst",
            id="pole-innego-warunku",
        ),
        pytest.param(
            _document({**GOOD_RULE, "jesli": [{"rodzaj": "skladnik", "skladnik": "kabel", "zaprzeczony": "tak"}]}),
            "reguly[r].jesli[0].zaprzeczony",
            id="zaprzeczony-tekst",
        ),
        pytest.param(
            _document({**GOOD_RULE, "jesli": [{"rodzaj": "urzadzenia", "tryb": "dokladnie"}]}),
            "reguly[r].jesli[0].tekst",
            id="dokladnie-bez-tekstu",
        ),
        pytest.param(
            _document({**GOOD_RULE, "jesli": [{"rodzaj": "urzadzenia", "tryb": "puste", "tekst": "a"}]}),
            "reguly[r].jesli[0].tekst",
            id="puste-z-tekstem",
        ),
        pytest.param(
            _document({**GOOD_RULE, "jesli": [{"rodzaj": "data", "dni": [0], "od": 1020}]}),
            "reguly[r].jesli[0].od",
            id="godzina-bez-cudzyslowu",
        ),
        pytest.param(
            _document({**GOOD_RULE, "jesli": [{"rodzaj": "data", "dni": [0], "od": "24:00"}]}),
            "reguly[r].jesli[0].od",
            id="godzina-24",
        ),
        pytest.param(
            _document({**GOOD_RULE, "jesli": [{"rodzaj": "data", "dni": [True], "od": "17:00"}]}),
            "reguly[r].jesli[0].dni",
            id="dzien-true",
        ),
        pytest.param(
            _document({**GOOD_RULE, "jesli": [{"rodzaj": "grupa", "grupa": "telefon"}]}),
            "reguly[r].jesli[0].grupa",
            id="nieznana-grupa",
        ),
        pytest.param(_document({**GOOD_RULE, "to": {"rodzaj": "nic", "kolumny": ["AP"]}}), "reguly[r].to.kolumny", id="nic-z-kolumnami"),
        pytest.param(
            _document({**GOOD_RULE, "to": {"rodzaj": "wpisz", "wpisy": [{"kolumna": "Z", "wartosc": True, "razy": "raz"}]}}),
            "reguly[r].to.wpisy[0].wartosc",
            id="wartosc-true",
        ),
        pytest.param(
            _document({**GOOD_RULE, "to": {"rodzaj": "wpisz", "wpisy": [{"kolumna": "Z", "wartosc": 1, "razy": "dwa"}]}}),
            "reguly[r].to.wpisy[0].razy",
            id="zly-mnoznik",
        ),
        pytest.param(
            _document({**GOOD_RULE, "jesli": [{"rodzaj": "skladnik", "skladnik": "brak"}]}),
            "reguly[r].jesli[0].skladnik",
            id="niezmiennik-typu",
        ),
    ],
)
def test_plik_regul_z_bledem_daje_pierwszy_problem_z_polem(document: object, field: str) -> None:
    problem = parse_quantity_rules(document, DEVICES)

    assert isinstance(problem, RulesProblem), problem
    assert problem.field == field


@pytest.mark.parametrize(
    ("document", "field"),
    [
        pytest.param({"schema_version": 1, "urzadzenia": [{"id": "a", "zapisy": ["a"], "grupa": "telefon"}]}, "urzadzenia[a].grupa", id="zla-grupa"),
        pytest.param({"schema_version": 1, "urzadzenia": [{"id": "a", "zapisy": "a"}]}, "urzadzenia[a].zapisy", id="zapisy-nie-lista"),
        pytest.param({"schema_version": 1, "urzadzenia": [{"id": "a", "zapisy": [1]}]}, "urzadzenia[a].zapisy", id="zapis-liczba"),
        pytest.param({"schema_version": 1, "urzadzenia": [{"id": "a", "zapisy": ["a"], "grupa": None}]}, "urzadzenia[a].grupa", id="grupa-null"),
        pytest.param({"schema_version": 1, "urzadzenia": [{"zapisy": ["a"]}]}, "urzadzenia[0].id", id="bez-id"),
        pytest.param({"schema_version": 1, "urzadzenia": [{"id": "a", "zapisy": ["A"]}]}, "urzadzenia[a].zapisy", id="niezmiennik-typu"),
    ],
)
def test_plik_listy_urzadzen_z_bledem_daje_pierwszy_problem_z_polem(document: object, field: str) -> None:
    problem = parse_device_list(document)

    assert isinstance(problem, RulesProblem), problem
    assert problem.field == field


# Każdy proces liczy Regułami ilości ze swojego wejścia (ADR 0033, US 14): Przygotowanie Ilości usług, Przebieg Ilości
# tylko dla INEA, Kontrola ilości regułami swojego Przebiegu, a Uzupełnienie regułami podanymi przy odczycie. Reguły
# różnią się od Reguł ilości z Wydania w każdej kolumnie, więc proces, który liczy innymi, daje inne komórki.
OWN_RULES = QuantityRules(
    (
        QuantityRule("fut", (ContainsComponent("fut"),), Scope.KNOWN, _fill("AA", 7)),
        QuantityRule("fut-bez-aa", (DevicesText(TextMode.CONTAINS, "fut"),), Scope.EVERY, LeaveEmpty(("AA",))),
        QuantityRule("nieznane", (), Scope.UNKNOWN, _fill("T", 1)),
    ),
    DEFAULT_QUANTITY_RULES.devices,
)
TUESDAY = datetime(2026, 9, 8, 10)


def _quantities_in(path: Path, row: int) -> dict[str, object]:
    [values] = cell_values(path, min_row=row, max_row=row, min_col=QUANTITY_COLUMNS.start, max_col=QUANTITY_COLUMNS.stop - 1)
    return {letter: value for letter, value in zip(QUANTITY_LETTERS, values, strict=True) if value not in (None, 0)}


def _tata_writes(path: Path, cells: dict[str, int]) -> None:
    workbook = load_workbook(path)
    try:
        for reference, value in cells.items():
            active_worksheet(workbook)[reference] = value
        workbook.save(path)
    finally:
        workbook.close()


def test_przygotowanie_przebieg_kontrola_i_uzupelnienie_licza_regulami_ilosci_ze_swojego_wejscia(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(
        tmp_path,
        [
            register_order(1, TUESDAY) | {"URZĄDZENIA": "fut"},
            register_order(2, TUESDAY) | {"URZĄDZENIA": "foo"},
            register_order(3, TUESDAY) | {"URZĄDZENIA": "prewencja"},
        ],
    )
    worker_template = tmp_path / tool_files.WORKER_TEMPLATE.name
    write_template(worker_template)

    preparation = prepare_collective_file(
        PreparationInputs(
            fixture.register_path,
            fixture.periods_directory,
            PERIOD,
            worker_list(),
            fixture.internal_template_path,
            fixture.collective_template_path,
            quantity_rules=OWN_RULES,
        ),
        RunContext(),
    )
    prepared = [_quantities_in(preparation.collective_file, row) for row in (18, 19, 20)]
    _tata_writes(preparation.collective_file, {"AA18": 6, "V19": 1})
    settlement = run_settlements(
        SettlementInputs(preparation.collective_file, worker_list(), worker_template, quantity_rules=OWN_RULES),
        RunContext(),
    )
    check = quantity_check.check(settlement.orders, settlement.quantity_rules)
    read = collective_file.read_numbered_orders(preparation.collective_file, DadFiles())
    assert not isinstance(read, MissingHeaders)
    to_fill = quantities_to_fill(read.rows, OWN_RULES, settled=False)

    assert prepared == [{"Q": 1, "S": 1, "AA": 7}, {"T": 1}, {"T": 1}], "prewencja nie jest tu z opisu"
    [worker_file] = (result.output_file for result in settlement.results if result.rows)
    assert _quantities_in(worker_file, 18) == {"Q": 1, "S": 1}
    assert dict(settlement.inea_only_cleared) == {"AA": 1}
    assert isinstance(check, quantity_check.QuantityCheck)
    assert (check.compared, check.unruled_rows, check.from_description) == (1, 2, 0)
    assert [(difference.column, difference.rule, difference.tata) for difference in check.differences] == [("AA", 7, 6)]
    assert dict(check.unruled["foo"].values) == {("V", 1): 1}, "V nie jest kolumną reguł dla składnika spoza listy"
    assert "AA" not in check.other_columns
    assert [(kind.kind, [(row.number, row.state) for row in kind.rows]) for kind in to_fill.kinds] == [
        (FillKind.WITHOUT_RULE, [(19, RowState.DONE), (20, RowState.TO_FILL)]),
        (FillKind.FROM_DESCRIPTION, []),
    ]
    assert fill_hint(FillKind.WITHOUT_RULE, OWN_RULES) == "Dopisz ilości poza T."


def test_podpowiedz_wiersza_bez_reguly_wymienia_kolumny_regul_dla_skladnika_spoza_listy() -> None:
    only_known = _rules(_rule("z", scope=Scope.KNOWN, action=_fill("Z", 1)))

    assert fill_hint(FillKind.WITHOUT_RULE, DEFAULT_QUANTITY_RULES) == "Dopisz ilości poza V, T i N."
    assert fill_hint(FillKind.WITHOUT_RULE, only_known) == "Dopisz ilości."
    assert fill_hint(FillKind.FROM_DESCRIPTION, only_known) == "Wpisz ilości według opisu technika."


# Słowa URZĄDZENIA zleceń w teście reguł bez składnika: każdy zapis Listy Urządzeń z Wydania, krotność i słowo spoza listy.
_RELEASE_WORDS = (*sorted({spelling for component in DEFAULT_QUANTITY_RULES.devices.components for spelling in component.spellings}), "2*fut", "ont x")
_NEVER_SPELLED = "zapis spoza zlecen"


@settings(derandomize=True, database=None, deadline=None, max_examples=300)
@given(
    st.sampled_from([component.id for component in DEFAULT_QUANTITY_RULES.devices.components]),
    st.lists(st.sampled_from(_RELEASE_WORDS), max_size=4),
    st.sampled_from(("", "instalacja", "montaż 2 szt", "akt int")),
    st.sampled_from(("u", "a")),
    st.sampled_from((datetime(2026, 9, 14, 9), datetime(2026, 9, 18, 18), datetime(2026, 9, 19, 10), None)),
)
def test_reguly_z_wydania_bez_skladnika_licza_jak_z_tym_skladnikiem_ktorego_zapisu_nie_ma_w_zadnym_zleceniu(
    absent: str, words: list[str], activities: str, contract: str, started: datetime | None
) -> None:
    """Reguły bez składnika (``without_components``) z listą bez niego dają każdemu zleceniu ten sam wynik co reguły z tym
    składnikiem na liście, gdy żadne zlecenie nie ma jego zapisu: rodzaj, ilości, puste kolumny i reguły, które zadziałały."""

    components = DEFAULT_QUANTITY_RULES.devices.components
    never_found = QuantityRules(
        DEFAULT_QUANTITY_RULES.rules,
        DeviceList(tuple(replace(component, spellings=(_NEVER_SPELLED,)) if component.id == absent else component for component in components)),
    )
    without = QuantityRules(
        without_components(DEFAULT_QUANTITY_RULES.rules, frozenset({absent})),
        DeviceList(tuple(component for component in components if component.id != absent)),
    )
    order = OrderContent.of(contract, " ".join(words), activities, started)

    assert evaluate(without, order) == evaluate(never_found, order)


@pytest.mark.parametrize("devices", ["ruter", "ruter kabel", "dekoder", "2*ruter wzmacniacz", ""])
def test_regula_bez_skladnika_traci_tylko_jego_wpis_i_warunek_a_liczy_jak_z_nieznalezionym(devices: str) -> None:
    """Reguła z wpisem razy liczba składnika, którego warunki nie wymagają, i reguła z warunkiem „nie zawierają” go liczą
    bez tego składnika tak samo jak z nim, gdy żadne zlecenie nie ma jego zapisu."""

    rules = (
        _rule("ruter-i-kable", ContainsComponent("router"), action=Fill((Write("N", 1), Write("O", 1, Multiplier.COMPONENT, "kabel")))),
        _rule("bez-kabla", ContainsComponent("kabel", negated=True), action=_fill("T", 1)),
        _rule("kabel", ContainsComponent("kabel"), action=_fill("V", 1)),
    )
    never_found = QuantityRules(rules, DeviceList((*DEVICES.components[:3], Component("kabel", (_NEVER_SPELLED,)))))
    without = QuantityRules(without_components(rules, frozenset({"kabel"})), DeviceList(DEVICES.components[:3]))

    assert evaluate(without, _order(devices)) == evaluate(never_found, _order(devices))
