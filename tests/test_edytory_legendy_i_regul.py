from __future__ import annotations

from datetime import time

import pytest

from rozliczenia.activity_legend import NUMBER, ActivityCode, CellFill, FillColour, FixedColumn
from rozliczenia.activity_legend_file import DEFAULT_ACTIVITY_LEGEND
from rozliczenia.centrum import legend_forms, rule_forms
from rozliczenia.centrum.contract import activity_legend as legend_contract
from rozliczenia.centrum.contract import quantity_rules as rules_contract
from rozliczenia.centrum.legend_sentences import code_sentence
from rozliczenia.centrum.rule_sentences import plain_sentence, rule_sentence
from rozliczenia.centrum.settings import messages
from rozliczenia.centrum.settings.files import FieldPath, FieldProblem
from rozliczenia.quantity_engine import ContainsComponent, DeviceList, Fill, QuantityRule, Scope, StartedAt, Write


def _code_form(*spellings: str) -> legend_contract.ActivityCodeForm:
    return legend_contract.ActivityCodeForm(spellings=list(spellings), column=None, value=1, amount=20, fills=[], counts_in_fault=True)


def _added_code(form: legend_contract.ActivityCodeForm, used: frozenset[str]) -> ActivityCode:
    added = legend_forms.edited(DEFAULT_ACTIVITY_LEGEND.codes, legend_contract.AddActivityCode(kind="add", code=form), used)
    assert isinstance(added, tuple), added
    return added[-1]


@pytest.mark.parametrize(
    ("spellings", "used", "identifier"),
    [
        pytest.param(("Listwa #m",), frozenset(), "listwa", id="czesc-przed-miejscem-na-liczbe"),
        pytest.param(("listwa#m",), frozenset({"listwa"}), "listwa-2", id="zajete-w-historii-z-numerem-2"),
        pytest.param(("listwa#m",), frozenset({"listwa", "listwa-2"}), "listwa-3", id="kolejny-wolny-numer"),
    ],
)
def test_nowy_kod_legendy_ma_id_z_pierwszego_zapisu_przed_miejscem_na_liczbe_a_zajete_z_kolejnym_numerem(
    spellings: tuple[str, ...], used: frozenset[str], identifier: str
) -> None:
    assert _added_code(_code_form(*spellings), used).id == identifier


def test_powtorzony_i_pusty_zapis_formularza_kodu_odpadaja_a_kod_ma_jeden_zapis() -> None:
    added = _added_code(_code_form("listwa#m", "", "Listwa #m"), frozenset())

    assert added.spellings == (f"listwa{NUMBER}m",)


def test_kolumna_wypelnienia_w_zdaniu_kodu_to_sama_litera_takze_gdy_ma_nazwe_pozycji_cennika() -> None:
    code = ActivityCode("rt9", ("rt9",), FixedColumn("AM"), fills=(CellFill("AM", FillColour.RED),))

    assert plain_sentence(code_sentence(code, {"AM": "Router"})) == "rt9: 1 w Router (AM), AM na czerwono."


def _rule_form(since: str) -> rules_contract.RuleForm:
    return rules_contract.RuleForm(
        scope="every",
        conditions=[rules_contract.DateCondition(kind="date", days=[0], since=since, negated=False)],
        action=rules_contract.FillAction(
            kind="fill", writes=[rules_contract.RuleWrite(column="N", value=45, multiplier="once", component=None)]
        ),
    )


@pytest.mark.parametrize("since", ["24:00", "12:60"])
def test_godzina_warunku_daty_spoza_zegara_to_odmowa_formularza_przy_polu_od(since: str) -> None:
    edit = rules_contract.AddRule(kind="add", rule=_rule_form(since))

    assert rule_forms.edited((), edit, frozenset()) == FieldProblem(FieldPath("jesli", 0, "od"), messages.rule_hour())


def test_nowa_regula_dostaje_najmniejszy_numer_ktorego_nie_ma_zadna_regula_ani_historia() -> None:
    existing = (QuantityRule("regula-2", (), Scope.EVERY, Fill((Write("N", 1),))),)

    added = rule_forms.edited(existing, rules_contract.AddRule(kind="add", rule=_rule_form("17:00")), frozenset({"regula-3"}))

    assert isinstance(added, tuple), added
    assert [rule.id for rule in added] == ["regula-2", "regula-1"]


@pytest.mark.parametrize(
    ("days", "shown"),
    [
        pytest.param({5, 6}, "sobota, niedziela", id="dwa-dni-z-rzedu-po-przecinku"),
        pytest.param({0, 1, 2}, "poniedziałek–środa", id="trzy-dni-z-rzedu-jako-przedzial"),
        pytest.param({0, 1, 3, 4, 5}, "poniedziałek, wtorek, czwartek–sobota", id="przedzial-obok-dwoch-dni"),
    ],
)
def test_dni_warunku_daty_w_zdaniu_reguly_po_kolei_a_trzy_i_wiecej_z_rzedu_jako_przedzial(days: set[int], shown: str) -> None:
    rule = QuantityRule("dodatek", (StartedAt(frozenset(days), time(17, 0)),), Scope.EVERY, Fill((Write("N", 45),)))

    assert plain_sentence(rule_sentence(rule, DeviceList(()), {})) == f"Jeśli DATA to {shown} od 17:00, to wpisz 45 w N."


def test_skladnik_spoza_listy_bez_nazwy_od_wolajacego_ma_w_zdaniu_reguly_swoj_identyfikator() -> None:
    rule = QuantityRule("modem", (ContainsComponent("modem-x"),), Scope.KNOWN, Fill((Write("N", 1),)))

    assert plain_sentence(rule_sentence(rule, DeviceList(()), {})) == "Jeśli URZĄDZENIA zawierają „modem-x”, to wpisz 1 w N."
