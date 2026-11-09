"""Show that the drive of verify-centrum-rozliczen fails on broken variants of its `uporzadkowanie-intermax` feature.

Each mutation runs the feature on its own copy of the checkout (``tools/mutacje.py``) and must make it fail.
A mutation whose anchor text is no longer in its file is reported as NIEAKTUALNA: update it to the new code.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / ".agents/skills/verify-centrum-rozliczen/scripts"))

from cele_mutacji_centrum import APP, BUILD, INTERMAX_KIND, INTERMAX_ORDERING, INTERMAX_RUN, RUN_VIEW, UPORZADKOWANIE
from mutacje import Edit, Mutation, check_all

MUTATIONS = (
    Mutation(
        "karta bez braku INTERMAX w Ustawieniach",
        (Edit(INTERMAX_RUN, "            blocker=_KIND.settings_blocker(settings),\n", "            blocker=None,\n"),),
        UPORZADKOWANIE,
        "bez wskazanego INTERMAX karta nie mówi tacie, co ustawić",
    ),
    Mutation(
        "karta nie widzi INTERMAX otwartego w Excelu",
        (
            Edit(
                INTERMAX_RUN,
                '            open_in_excel=[] if register is None else open_in_excel([InputWorkbook(_VIEW.register_name, register, "data_file")]),\n',
                "            open_in_excel=[],\n",
            ),
        ),
        UPORZADKOWANIE,
        "tata uruchamia Uporządkowanie przy otwartym INTERMAX i dostaje dopiero Zatrzymanie",
    ),
    Mutation(
        "karta bez Dni uporządkowanych",
        (Edit(INTERMAX_RUN, "ordered=day.ordered)", "ordered=False)"),),
        UPORZADKOWANIE,
        "tata nie widzi na karcie, które dni są już uporządkowane",
    ),
    Mutation(
        "karta z wklejonym dniem po dzisiejszym",
        (
            Edit(
                INTERMAX_ORDERING,
                "shown = ordered | {",
                "shown = ordered | {order.when.date() for area in _paste_areas(register)"
                " for order in raw_orders.pasted(area.rows_from_bottom(), area.columns)"
                " if isinstance(order, raw_orders.RawOrder)} | {",
            ),
        ),
        UPORZADKOWANIE,
        "karta pokazuje wklejony, nieuporządkowany dzień po dzisiejszym, choć ma pokazywać tylko uporządkowane",
    ),
    Mutation(
        "dni nie czytane po Uporządkowaniu",
        (
            Edit(
                INTERMAX_RUN,
                "(last.register, last.version, last.today) == (register, version, today)",
                "(last.register, last.today) == (register, today)",
            ),
        ),
        UPORZADKOWANIE,
        "po Uporządkowaniu karta dalej pokazuje wklejony dzień jako nieuporządkowany",
    ),
    Mutation(
        "wynik bez nazwy Kopii INTERMAX",
        (Edit(INTERMAX_KIND, "        intermax_copy=summary.copy_name,\n", "        intermax_copy=None,\n"),),
        UPORZADKOWANIE,
        "tata nie wie, która Kopia INTERMAX ma stan sprzed zapisu",
    ),
    Mutation(
        "wynik otwiera Plik zbiorczy zamiast INTERMAX",
        (Edit(INTERMAX_KIND, '    result_action="open_order_register",\n', '    result_action="open_collective_file",\n'),),
        UPORZADKOWANIE,
        "akcja po wyniku nie otwiera uporządkowanego INTERMAX",
    ),
    Mutation(
        "Zatrzymanie proponuje Rejestr zleceń zamiast INTERMAX",
        (Edit(INTERMAX_KIND, '    register_name="INTERMAX",\n', ""),),
        UPORZADKOWANIE,
        "karta mówi „INTERMAX”, a przycisk Zatrzymania „Otwórz Rejestr zleceń”: dwie nazwy jednego pliku",
    ),
    Mutation(
        "karta bez ostatniego Uporządkowania",
        (Edit(APP, "lambda: cards.latest(intermax.key)", "lambda: None"),),
        UPORZADKOWANIE,
        "karta nie pokazuje wyniku ostatniego Uporządkowania z Logów",
    ),
    Mutation(
        "Diagnoza bez sprawdzenia INTERMAX",
        (
            Edit(
                INTERMAX_KIND,
                '    checks=("tata_settings", "files_in_onedrive", "intermax", *TAIL),\n',
                '    checks=("tata_settings", "files_in_onedrive", *TAIL),\n',
            ),
        ),
        UPORZADKOWANIE,
        "Diagnoza Zatrzymania „do Maksa” nie sprawdza INTERMAX",
    ),
    Mutation(
        "Metryki INTERMAX z trybem DRY-RUN",
        (Edit(RUN_VIEW, '        return (RunMode.RUN,)\n', '        return (RunMode.RUN, RunMode.DRY_RUN)\n'),),
        UPORZADKOWANIE,
        "Metryki proponują przy INTERMAX tryb DRY-RUN, którego Uporządkowanie nie ma, z pustym wykresem",
    ),
    Mutation(
        "Metryki INTERMAX po DRY-RUN Przygotowania bez wciśniętego trybu",
        (Edit(BUILD, "d=u.some(e=>e.value===i)?i:u[0]?.value??i;", "d=i;"),),
        UPORZADKOWANIE,
        "po DRY-RUN Przygotowania Metryki INTERMAX nie mają wciśniętego trybu, a wykres mówi, że procesu nie uruchomiono",
    ),
)


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    raise SystemExit(check_all(MUTATIONS))
