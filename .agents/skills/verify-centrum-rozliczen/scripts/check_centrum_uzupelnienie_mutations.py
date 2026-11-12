"""Show that the drive of verify-centrum-rozliczen fails on broken variants of its `uzupelnienie` feature.

Each mutation runs the feature on its own copy of the checkout (``tools/lib/silnik_mutacji.py``) and must make it fail.
A mutation whose anchor text is no longer in its file is reported as NIEAKTUALNA: update it to the new code.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / ".agents/skills/verify-centrum-rozliczen/scripts"))

from cele_mutacji_centrum import BUILD, FILLING, LIVE_FILE, QUANTITIES_TO_FILL, UZUPELNIENIE, WORKBOOK_FILES
from silnik_mutacji import Edit, Mutation, check_all

MUTATIONS = (
    Mutation(
        "karta z Logów bez podsumowania",
        (Edit(BUILD, "action:a.button,filling:!0}),a.dialog", "action:a.button,filling:!1}),a.dialog"),),
        UZUPELNIENIE,
        "po ponownym starcie Centrum karta Przygotowania nie mówi tacie, co zostało do uzupełnienia",
    ),
    Mutation(
        "karta wyniku pokazuje starą kopię podsumowania",
        (Edit(BUILD, "[e],{fresh:!0}),r=", "[e],{fresh:!1}),r="),),
        UZUPELNIENIE,
        "zaraz po Przygotowaniu karta wyniku pokazuje przez sekundę stan sprzed niego, np. „Nie ma Pliku zbiorczego”",
    ),
    Mutation(
        "karta wyniku bez odpowiedzi serwera jest pusta",
        (Edit(BUILD, "what:`Pliku zbiorczego`,message:", "what:`Pliku zbiorczego`,className:`hidden`,message:"),),
        UZUPELNIENIE,
        "gdy Centrum nie odpowie, pod wynikiem Przygotowania jest pusto i tata nie wie, że nic nie odczytano",
    ),
    Mutation(
        "podsumowanie bez Pliku zbiorczego proponuje go otworzyć",
        (Edit(FILLING, "collective_file_exists=file_state(path) == \"file\"", "collective_file_exists=True"),),
        UZUPELNIENIE,
        "tata klika „Otwórz Plik zbiorczy” w okresie bez pliku i dostaje tylko „Nie udało się otworzyć”",
    ),
    Mutation(
        "plik blokady Excela blokuje odczyt Uzupełnienia",
        (Edit(WORKBOOK_FILES, "    if is_open_in_excel(path) and not despite_excel_lock:\n", "    if is_open_in_excel(path):\n"),),
        UZUPELNIENIE,
        "tata z Plikiem zbiorczym otwartym w Excelu widzi Komunikat zamiast swoich postępów",
    ),
    Mutation(
        "wpis taty nie robi wiersza",
        (Edit(QUANTITIES_TO_FILL, "CellSource.EMPTY if value == 0 else CellSource.TATA", "CellSource.EMPTY"),),
        UZUPELNIENIE,
        "wiersz, który tata uzupełnił w Excelu, zostaje na liście do zrobienia",
    ),
    Mutation(
        "znacznik zapisu się nie zmienia",
        (Edit(LIVE_FILE, '    return f"{status.st_mtime_ns}-{status.st_size}"\n', '    return "zapis"\n'),),
        UZUPELNIENIE,
        "tata wpisuje w Excelu, a strona Uzupełnienia stoi, dopóki jej nie odświeży",
    ),
    Mutation(
        "nieudany odczyt od razu Komunikatem",
        (Edit(FILLING, "        if failing.kept is not None:\n", "        if False:\n"),),
        UZUPELNIENIE,
        "każdy zapis Excela albo synchronizacja OneDrive miga tacie Komunikatem zamiast ostatniego stanu",
    ),
    Mutation(
        "nieudane pytanie o znacznik zapisu zostawia stary widok",
        (Edit(BUILD, "version!==t.version}catch{return!0}", "version!==t.version}catch{return!1}"),),
        UZUPELNIENIE,
        "gdy Centrum nie odpowiada, strona Uzupełnienia pokazuje stare ilości jak na żywo, a tata wpisuje w Excelu i nic się nie zmienia",
    ),
    Mutation(
        "strona rodzaju gubi CZYNNOŚCI ZREALIZOWANE",
        (Edit(FILLING, "                texts=list(row.texts),\n", '                texts=[*row.texts[:-1], ""],\n'),),
        UZUPELNIENIE,
        "tata nie rozpozna zlecenia po opisie technika i musi szukać wiersza w Excelu",
    ),
    Mutation(
        "ustawienie Przebiegu nie wymienia wierszy bez ilości",
        (Edit(QUANTITIES_TO_FILL, "for row in kind.rows if not row.done))", "for row in kind.rows if False))"),),
        UZUPELNIENIE,
        "tata potwierdza Gotowość, a okno „Uruchomić z zapisem?” milczy o wierszach, w których nie ma ilości",
    ),
    Mutation(
        "po Przebiegu rozliczeń wiersz bez wpisu taty dalej czeka na tatę",
        (
            Edit(
                QUANTITIES_TO_FILL,
                "state = RowState.WITHOUT_QUANTITY if settled else RowState.TO_FILL",
                "state = RowState.TO_FILL",
            ),
        ),
        UZUPELNIENIE,
        "po Przebiegu tata widzi żółte wiersze do uzupełnienia zamiast szarych „bez ilości”, które zostały na zerach",
    ),
    Mutation(
        "nieczytelny Plik zbiorczy psuje ustawienie Przebiegu",
        (
            Edit(
                FILLING,
                '    except WorkbookError:\n        return filling_contract.WithoutQuantityUnread(state="unread")\n',
                "    except WorkbookError:\n        raise\n",
            ),
        ),
        UZUPELNIENIE,
        "przy uszkodzonym Pliku zbiorczym jednego okresu tata nie może uruchomić żadnego Przebiegu rozliczeń",
    ),
)


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    raise SystemExit(check_all(MUTATIONS))
