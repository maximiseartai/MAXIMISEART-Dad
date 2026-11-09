"""Show that the Reguły ilości conformance test fails on each single broken rule.

Each mutation runs on its own copy of the checkout (``tools/lib/silnik_mutacji.py``) and must make
``quantity_rules_conformance.py`` fail. A mutation whose anchor text is no longer in
``quantity_rules.py`` exactly once is reported as NIEAKTUALNA: update it to the new code.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))

from silnik_mutacji import Edit, Mutation, check_all

RULES = Path("src/rozliczenia/quantity_rules.py")
CHECKER = (".agents/skills/verify-rozliczenia/scripts/quantity_rules_conformance.py",)


def _mutation(name: str, anchor: str, replacement: str, harm: str) -> Mutation:
    return Mutation(name, (Edit(RULES, anchor, replacement),), CHECKER, harm)


MUTATIONS = (
    _mutation(
        "fut bez routera w Z zamiast Q",
        "        quantities[_Q.Q] += tv_devices\n",
        "        quantities[_Q.Z] += tv_devices\n",
        "fut i n*fut płacą za montaż ONT zamiast za Multiroom",
    ),
    _mutation(
        "multiroom w Z zamiast Q",
        "quantities[_Q.Q] += tv_devices - 1",
        "quantities[_Q.Z] += tv_devices - 1",
        "nokia zte 2*fut daje Z=2 i Q=0",
    ),
    _mutation(
        "każde urządzenie TV przy routerze w P",
        "        quantities[_Q.P] += 1\n",
        "        quantities[_Q.P] += tv_devices\n",
        "nokia zte 3*fut daje P=3 zamiast P=1 i Q=2",
    ),
    _mutation("próg dodatku 18:00", "time(17))", "time(18))", "usterka o 17:00 traci 45 zł"),
    _mutation("próg dodatku 16:00", "time(17))", "time(16))", "usterka o 16:00 dostaje 45 zł"),
    _mutation(
        "dodatek dopiero po 17:00",
        "started.at >= late_from",
        "started.at > late_from",
        "usterka równo o 17:00 traci 45 zł",
    ),
    _mutation("dodatek bez soboty", ", 5: time.min}", "}", "sobotnia usterka traci 45 zł"),
    _mutation("dodatek w niedzielę", "5: time.min}", "5: time.min, 6: time.min}", "niedzielna usterka dostaje 45 zł"),
    _mutation("dodatek bez piątku", "range(5)", "range(4)", "piątkowa usterka po 17:00 traci 45 zł"),
    _mutation("dodatek 1 zamiast 45", "_LATE_FAULT_SURCHARGE: Final = 45", "_LATE_FAULT_SURCHARGE: Final = 1", "N=1 zamiast 45"),
    _mutation(
        "dodatek bez względu na usterkę",
        "if _is_late(order.started) and any(component.kind is _Kind.FAULT for component, _ in components):",
        "if _is_late(order.started):",
        "instalacja po 17:00 dostaje 45 zł",
    ),
    _mutation(
        "S bez AG",
        " + quantities[_Q.AG]\n",
        "\n",
        "wifi6extra nie liczy się do Dostarczenia CPE",
    ),
    _mutation(
        "S jako 1 zamiast sumy",
        "quantities[_Q.S] = quantities[_Q.O] + quantities[_Q.P] + quantities[_Q.Q] + quantities[_Q.AG]",
        "quantities[_Q.S] = min(1, quantities[_Q.O] + quantities[_Q.P] + quantities[_Q.Q] + quantities[_Q.AG])",
        "nokia zte fut daje S=1 zamiast S=2",
    ),
    _mutation("usterka w AM zamiast AI", "_FAULT = _Component({_Q.AI: 1}", "_FAULT = _Component({_Q.AM: 1}", "usterka płaci za modyfikację sieci"),
    _mutation("usterka hurt nieznana", '    "usterka hurt": _FAULT,\n', "", "usterka hurt staje się wierszem bez reguły"),
    _mutation("gniazdo bez AP", "_Component({_Q.AE: 1, _Q.AP: 1})", "_Component({_Q.AE: 1})", "gniazdo traci Deinstalację"),
    _mutation("zmiana instalacji w AK", "_Component({_Q.AM: 1})", "_Component({_Q.AK: 1})", "zmiana instalacji płaci za sieć domową do 10 m"),
    _mutation(
        "technicolor bez AK",
        "_Component({_Q.O: 1, _Q.Z: 1, _Q.AK: 1}, _Kind.ROUTER)",
        "_Component({_Q.O: 1, _Q.Z: 1}, _Kind.ROUTER)",
        "technicolor traci sieć domową do 10 m",
    ),
    _mutation(
        "gateway z AO bez wzmacniacza",
        "_Component({_Q.O: 1}, _Kind.ROUTER, with_extender={_Q.AO: 1})",
        "_Component({_Q.O: 1, _Q.AO: 1}, _Kind.ROUTER)",
        "sam gateway dostaje premię za wifi6extra",
    ),
    _mutation(
        "samo nokia z akt int bez O",
        '_Component({_Q.Z: 1}, without_router=("akt int", {_Q.O: 1}))',
        "_Component({_Q.Z: 1})",
        "samo nokia z akt int daje tylko Z, tata dopisuje O",
    ),
    _mutation(
        "akt int także przy routerze",
        "    if not count_of[_Kind.ROUTER]:\n",
        "    if True:\n",
        "nokia, gateway z akt int daje O=2",
    ),
    _mutation(
        "akt int tylko małymi literami",
        'phrases = " ".join(activities.casefold().split())',
        'phrases = " ".join(activities.split())',
        "samo nokia z AKT INT traci O",
    ),
    _mutation(
        "akt int liczy się do S",
        "                quantities.update(added)\n",
        "                quantities.update({**added, _Q.S: quantities[_Q.S] + 1})\n",
        "samo nokia z akt int dostaje Dostarczenie CPE",
    ),
    _mutation(
        "akt int na każdą sztukę nokia",
        "        for phrase, added in once.items():\n",
        "        for phrase, added in [component.without_router for component, _ in components if component.without_router]:\n",
        "nokia nokia z akt int daje O=2",
    ),
    _mutation(
        "akt int przy routerze z urządzeniem TV",
        "    if not count_of[_Kind.ROUTER]:\n",
        "    if not count_of[_Kind.ROUTER] or count_of[_Kind.TV]:\n",
        "nokia, gateway fut z akt int daje O=2",
    ),
    _mutation(
        "sztuki z krotności zamiast z CZYNNOŚCI",
        "per_order = pieces if component.kind is _Kind.PIECES else count",
        "per_order = count",
        "instalacja ręczna 6 szt daje AN=1",
    ),
    _mutation(
        "V instalacji ręcznej bez sztuk",
        "_Component({_Q.AN: 1, _Q.V: 1}, _Kind.PIECES)",
        "_Component({_Q.AN: 1}, _Kind.PIECES)",
        "instalacja ręczna 6 szt daje V=1",
    ),
    _mutation("sztuki tylko ze spacją", r"\s*szt", r"\s+szt", "instalacja 7szt daje AN=1"),
    _mutation("wizja nieznana", '    "wizja": _MANUAL_INSTALLATION,\n', "", "wizja staje się wierszem bez reguły"),
    _mutation(
        "T, gdy UMOWA zawiera u",
        "if _first_word(order.contract) == _PRINTING_CONTRACT:",
        "if _PRINTING_CONTRACT in str(order.contract).casefold():",
        "UM-SYN-… dostaje Drukowanie dokumentów",
    ),
    _mutation("prewencja z ilościami", 'frozenset({"prewencja", "niedostępność usług"})', 'frozenset({"niedostępność usług"})', "prewencja dostaje V"),
    _mutation(
        "XG nie znika",
        '.casefold().replace("xg", "")',
        ".casefold()",
        "nokia zte XG staje się wierszem bez reguły",
    ),
    _mutation(
        "krotność bez spacji po gwiazdce",
        r'_MULTIPLIER = re.compile(r"\s*\*\s*")',
        r'_MULTIPLIER = re.compile(r"\*")',
        "nokia zte 2* fut staje się wierszem bez reguły",
    ),
    _mutation(
        "bez reguły z ilościami URZĄDZENIA",
        "        return WithoutRule(_nonzero(quantities))",
        "        return WithoutRule(_nonzero({**quantities, **_device_quantities(components, "")}))",
        "nokia zte przeniesienie dostaje O, S, Z",
    ),
    _mutation(
        "bez reguły bez dodatku",
        "        return WithoutRule(_nonzero(quantities))",
        "        return WithoutRule(_nonzero({**quantities, _Q.N: 0}))",
        "usterka przeniesienie po 17:00 traci 45 zł",
    ),
)


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    raise SystemExit(check_all(MUTATIONS))
