"""Show that the Reguły ilości conformance test fails on each single broken rule.

Each mutation runs on its own copy of the checkout (``tools/lib/silnik_mutacji.py``) and must make
``quantity_rules_conformance.py`` fail. A rule of Dad's instruction is broken where it lives: in the Reguły ilości
z Wydania (``reguly_ilosci_domyslne.yaml``), in the Lista Urządzeń z Wydania (``lista_urzadzen_domyslna.yaml``), or
in the engine (``quantity_engine.py``: reading ``URZĄDZENIA``, ``CZYNNOŚCI`` and ``UMOWA``, P, Q and S). A mutation
whose anchor text is no longer in its file exactly once is reported as NIEAKTUALNA: update it to the new code.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))

from silnik_mutacji import Edit, Mutation, check_all

RULES = Path("src/rozliczenia/reguly_ilosci_domyslne.yaml")
DEVICES = Path("src/rozliczenia/lista_urzadzen_domyslna.yaml")
ENGINE = Path("src/rozliczenia/quantity_engine.py")
CHECKER = (".agents/skills/verify-rozliczenia/scripts/quantity_rules_conformance.py",)


def _mutation(name: str, file: Path, anchor: str, replacement: str, harm: str) -> Mutation:
    return Mutation(name, (Edit(file, anchor, replacement),), CHECKER, harm)


_TV_TO_Q = 'Contribution("P/Q", "Q", tv - first_tv)'
_S = "devices = facts.groups[DeviceGroup.ROUTER] + tv + facts.groups[DeviceGroup.EXTENDER]"
_SATURDAY_RULE = """  - id: dodatek-usterka-sobota
    zakres: kazde
    jesli: [{rodzaj: skladnik, skladnik: usterka}, {rodzaj: data, dni: [5], od: "00:00"}]
    to: {rodzaj: wpisz, wpisy: [{kolumna: N, wartosc: 45, razy: raz}]}
"""
_WEEKDAY_SURCHARGE = "{kolumna: N, wartosc: 45, razy: raz}]}\n  - id: dodatek-usterka-sobota"
_SATURDAY_SURCHARGE = "{kolumna: N, wartosc: 45, razy: raz}]}\n  - id: nokia\n"

MUTATIONS = (
    _mutation(
        "fut bez routera w Z zamiast Q",
        ENGINE,
        _TV_TO_Q,
        'Contribution("P/Q", "Q" if first_tv else "Z", tv - first_tv)',
        "fut i n*fut płacą za montaż ONT zamiast za Multiroom",
    ),
    _mutation(
        "multiroom w Z zamiast Q",
        ENGINE,
        _TV_TO_Q,
        'Contribution("P/Q", "Z" if first_tv else "Q", tv - first_tv)',
        "nokia zte 2*fut daje Z=2 i Q=0",
    ),
    _mutation(
        "każde urządzenie TV przy routerze w P",
        ENGINE,
        'Contribution("P/Q", "P", first_tv)',
        'Contribution("P/Q", "P", tv if first_tv else 0)',
        "nokia zte 3*fut daje P=3 zamiast P=1 i Q=2",
    ),
    _mutation("próg dodatku 18:00", RULES, 'od: "17:00"', 'od: "18:00"', "usterka o 17:00 traci 45 zł"),
    _mutation("próg dodatku 16:00", RULES, 'od: "17:00"', 'od: "16:00"', "usterka o 16:00 dostaje 45 zł"),
    _mutation(
        "dodatek dopiero po 17:00",
        ENGINE,
        "facts.started.at >= since",
        "facts.started.at > since",
        "usterka równo o 17:00 traci 45 zł",
    ),
    _mutation("dodatek bez soboty", RULES, _SATURDAY_RULE, "", "sobotnia usterka traci 45 zł"),
    _mutation("dodatek w niedzielę", RULES, "dni: [5]", "dni: [5, 6]", "niedzielna usterka dostaje 45 zł"),
    _mutation("dodatek bez piątku", RULES, "dni: [0, 1, 2, 3, 4]", "dni: [0, 1, 2, 3]", "piątkowa usterka po 17:00 traci 45 zł"),
    Mutation(
        "dodatek 1 zamiast 45",
        (
            Edit(RULES, _WEEKDAY_SURCHARGE, _WEEKDAY_SURCHARGE.replace("wartosc: 45", "wartosc: 1")),
            Edit(RULES, _SATURDAY_SURCHARGE, _SATURDAY_SURCHARGE.replace("wartosc: 45", "wartosc: 1")),
        ),
        CHECKER,
        "N=1 zamiast 45",
    ),
    _mutation(
        "dodatek bez względu na usterkę",
        RULES,
        "jesli: [{rodzaj: skladnik, skladnik: usterka}, {rodzaj: data, dni: [0, 1, 2, 3, 4]",
        "jesli: [{rodzaj: data, dni: [0, 1, 2, 3, 4]",
        "instalacja po 17:00 dostaje 45 zł",
    ),
    _mutation("S bez extendera", ENGINE, _S, "devices = facts.groups[DeviceGroup.ROUTER] + tv", "wifi6extra nie liczy się do Dostarczenia CPE"),
    _mutation(
        "S jako 1 zamiast sumy",
        ENGINE,
        'Contribution("S", "S", devices)',
        'Contribution("S", "S", min(1, devices))',
        "nokia zte fut daje S=1 zamiast S=2",
    ),
    _mutation(
        "usterka w AM zamiast AI",
        RULES,
        "{kolumna: AI, wartosc: 1, razy: liczba, skladnik: usterka}",
        "{kolumna: AM, wartosc: 1, razy: liczba, skladnik: usterka}",
        "usterka płaci za modyfikację sieci",
    ),
    _mutation(
        "usterka hurt nieznana",
        DEVICES,
        "zapisy: [usterka, usterka hurt, usterka wew]",
        "zapisy: [usterka, usterka wew]",
        "usterka hurt staje się wierszem bez reguły",
    ),
    _mutation(
        "gniazdo bez AP",
        RULES,
        "        - {kolumna: AP, wartosc: 1, razy: liczba, skladnik: gniazdo}\n",
        "",
        "gniazdo traci Deinstalację",
    ),
    _mutation(
        "zmiana instalacji w AK",
        RULES,
        "{kolumna: AM, wartosc: 1, razy: liczba, skladnik: zmiana-instalacji}",
        "{kolumna: AK, wartosc: 1, razy: liczba, skladnik: zmiana-instalacji}",
        "zmiana instalacji płaci za sieć domową do 10 m",
    ),
    _mutation(
        "technicolor bez AK",
        RULES,
        "        - {kolumna: AK, wartosc: 1, razy: liczba, skladnik: technicolor}\n",
        "",
        "technicolor traci sieć domową do 10 m",
    ),
    _mutation(
        "gateway z AO bez wzmacniacza",
        RULES,
        "jesli: [{rodzaj: skladnik, skladnik: gateway}, {rodzaj: grupa, grupa: extender}]",
        "jesli: [{rodzaj: skladnik, skladnik: gateway}]",
        "sam gateway dostaje premię za wifi6extra",
    ),
    _mutation(
        "samo nokia z akt int bez O",
        RULES,
        "{rodzaj: czynnosci, tekst: akt int}",
        "{rodzaj: czynnosci, tekst: akt int nigdy}",
        "samo nokia z akt int daje tylko Z, tata dopisuje O",
    ),
    _mutation(
        "akt int także przy routerze",
        RULES,
        "      - {rodzaj: grupa, grupa: router, zaprzeczony: true}\n",
        "",
        "nokia, gateway z akt int daje O=2",
    ),
    _mutation(
        "akt int tylko małymi literami",
        ENGINE,
        'return " ".join(text.casefold().split())',
        'return " ".join(text.split())',
        "samo nokia z AKT INT traci O",
    ),
    _mutation(
        "akt int liczy się do S",
        ENGINE,
        _S,
        f'{_S} + ("akt int" in facts.activities)',
        "samo nokia z akt int dostaje Dostarczenie CPE",
    ),
    _mutation(
        "akt int na każdą sztukę nokia",
        RULES,
        "to: {rodzaj: wpisz, wpisy: [{kolumna: O, wartosc: 1, razy: raz}]}",
        "to: {rodzaj: wpisz, wpisy: [{kolumna: O, wartosc: 1, razy: liczba, skladnik: nokia}]}",
        "nokia nokia z akt int daje O=2",
    ),
    _mutation(
        "sztuki z krotności zamiast z CZYNNOŚCI",
        RULES,
        "{kolumna: AN, wartosc: 1, razy: sztuki",
        "{kolumna: AN, wartosc: 1, razy: liczba",
        "instalacja ręczna 6 szt daje AN=1",
    ),
    _mutation(
        "V instalacji ręcznej bez sztuk",
        RULES,
        "        - {kolumna: V, wartosc: 1, razy: sztuki, skladnik: instalacja-reczna}\n",
        "",
        "instalacja ręczna 6 szt daje V=0",
    ),
    _mutation("sztuki tylko ze spacją", ENGINE, r"\s*szt", r"\s+szt", "instalacja 7szt daje AN=1"),
    _mutation(
        "wizja nieznana",
        DEVICES,
        "zapisy: [instalacja ręczna, wizja]",
        "zapisy: [instalacja ręczna]",
        "wizja staje się wierszem bez reguły",
    ),
    _mutation(
        "T, gdy UMOWA zawiera u",
        ENGINE,
        "return facts.contract_word == word",
        "return word in facts.contract_word",
        "UM-SYN-… dostaje Drukowanie dokumentów",
    ),
    _mutation(
        "prewencja z ilościami",
        RULES,
        "  - {id: z-opisu-prewencja, zakres: kazde, jesli: [{rodzaj: urzadzenia, tryb: dokladnie, tekst: prewencja}], to: {rodzaj: nic}}\n",
        "",
        "prewencja dostaje V",
    ),
    _mutation(
        "XG nie znika",
        ENGINE,
        '.casefold().replace("xg", "")',
        ".casefold()",
        "nokia zte XG staje się wierszem bez reguły",
    ),
    _mutation(
        "krotność bez spacji po gwiazdce",
        ENGINE,
        r'_MULTIPLIER = re.compile(r"\s*\*\s*")',
        r'_MULTIPLIER = re.compile(r"\*")',
        "nokia zte 2* fut staje się wierszem bez reguły",
    ),
    _mutation(
        "bez reguły z ilościami URZĄDZENIA",
        RULES,
        "  - id: nokia-router\n    zakres: znane\n",
        "  - id: nokia-router\n    zakres: kazde\n",
        "nokia zte przeniesienie dostaje O i Z",
    ),
    _mutation(
        "bez reguły bez dodatku",
        RULES,
        "  - id: dodatek-usterka-pn-pt\n    zakres: kazde\n",
        "  - id: dodatek-usterka-pn-pt\n    zakres: znane\n",
        "usterka przeniesienie po 17:00 traci 45 zł",
    ),
)


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    raise SystemExit(check_all(MUTATIONS))
