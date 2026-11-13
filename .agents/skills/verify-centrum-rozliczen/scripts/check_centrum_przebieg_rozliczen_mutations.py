"""Show that the drive of verify-centrum-rozliczen fails on broken variants of its `przebieg-rozliczen` feature.

Each mutation runs the feature on its own copy of the checkout (``tools/lib/silnik_mutacji.py``) and must make it fail.
A mutation whose anchor text is no longer in its file is reported as NIEAKTUALNA: update it to the new code.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / ".agents/skills/verify-centrum-rozliczen/scripts"))

from cele_mutacji_centrum import BUILD, PRZEBIEG, RUN_VIEW, SETTLEMENT_KIND, SETTLEMENT_MESSAGES
from silnik_mutacji import Edit, Mutation, check_all

MUTATIONS = (
    Mutation(
        "stopka karty startu zawsze o pliku danych",
        (Edit(RUN_VIEW, "        return None if template_open and not data_file_open else self.reminder\n", "        return self.reminder\n"),),
        PRZEBIEG,
        "gdy Uruchom blokuje tylko pozostawiony ~$ Wzorca, stopka każe zamknąć Plik zbiorczy",
    ),
    Mutation(
        "Nowe Uruchomienie procesu bez ponownego odczytu",
        (Edit(BUILD, "&&(c.current=r,t())},[r,t])", "&&(c.current=r)},[r,t])"),),
        PRZEBIEG,
        "po usunięciu ~$ karta startu pokazuje stare ostrzeżenie aż do powrotu do okna",
    ),
    Mutation(
        "po Przebiegu rozliczeń akcją główną jest Plik zbiorczy",
        (Edit(SETTLEMENT_KIND, '        result_action="open_worker_settlements_folder",\n', '        result_action="open_collective_file",\n'),),
        PRZEBIEG,
        "po zapisie Rozliczeń pracowników karta proponuje otwarcie Pliku zbiorczego zamiast ich folderu",
    ),
    Mutation(
        "pusty szablon nie jest oznaczony",
        (Edit(SETTLEMENT_KIND, '                empty=result.status == "PUSTY_SZABLON",\n', "                empty=False,\n"),),
        PRZEBIEG,
        "Rozliczenie pracownika bez zleceń wygląda jak zapisane, bez oznaczenia „pusty”",
    ),
    Mutation(
        "Zatrzymanie na nieznanym Wykonawcy odsyła do Podglądu po wiersze",
        (
            Edit(
                SETTLEMENT_MESSAGES,
                '        action=f"{_FIX_UNMAPPED_WORKER} {_SAVE_AND_RETRY}",\n        setting="wykonawcy",\n    )\n\n\n'
                "def rows_without_worker(",
                '        action=f"{_PREVIEW_PROBLEMS} {_FIX_UNMAPPED_WORKER} {_SAVE_AND_RETRY}",\n        setting="wykonawcy",\n'
                '    )\n\n\ndef rows_without_worker(',
            ),
        ),
        PRZEBIEG,
        "„Co zrobić” przy Wykonawcy spoza konfiguracji obiecuje wiersze, których Podgląd bez zapisu nie podaje",
    ),
)


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    raise SystemExit(check_all(MUTATIONS))
