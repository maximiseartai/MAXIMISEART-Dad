"""Show that explore_status_okresu.py fails on broken variants of the consumers of the Status okresu, and for each part
of the shape of each known finding and accepted risk of the explorer on a broken variant just outside it
(``BOUNDARIES``).

Each mutation runs on its own copy of the checkout (``tools/lib/silnik_mutacji.py``) and must end the checker's report
with the expected line. A mutation whose anchor text is no longer in its file is reported as NIEAKTUALNA: update it to
the new code.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import sys
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))

from silnik_mutacji import Edit, Mutation, check_all

PERIOD_FOLDER = Path("src/rozliczenia/period_folder.py")
REPORT_ENTERING = Path("src/rozliczenia/report_entering.py")
INPUT_CHECKS = Path("src/rozliczenia/input_checks.py")
PREPARATION_FILES = Path("src/rozliczenia/preparation_files.py")
FILLING = Path("src/rozliczenia/centrum/filling.py")
PERIOD_START = Path("src/rozliczenia/centrum/period_start.py")
SETTLEMENT_KIND = Path("src/rozliczenia/centrum/processes/settlement.py")
EXPLORER_FILE = Path(".agents/skills/verify-status-okresu/scripts/explore_status_okresu.py")
EXPLORER = (EXPLORER_FILE.as_posix(),)
NEW = "STATUS OKRESU: NOWE NARUSZENIE"

PERIOD_FILES_GUARD = "        for target in (folder.internal_settlement, folder.collective_file):\n"

ENTERING_CLOSED_BY_INTERNAL = Mutation(
    "Wpisanie raportów zamyka okres po Rozliczeniu wewnętrznym zamiast po Pliku zbiorczym",
    (
        Edit(
            REPORT_ENTERING,
            "                PeriodFolder(parent, period).observe().collective_file_exists\n",
            "                PeriodFolder(parent, period).observe().internal_settlement_exists\n",
        ),
    ),
    EXPLORER,
    "Wpisanie raportów wpisuje do okresu z samym Plikiem zbiorczym, a okres z samym Rozliczeniem wewnętrznym pomija",
    NEW,
)

SETTLEMENT_WITHOUT_GUARD = Mutation(
    "Sprawdzanie Przebiegu rozliczeń bez Nienadpisywania Folderu rozliczeń pracowników",
    (
        Edit(
            INPUT_CHECKS,
            "    settlement_files.ensure_worker_settlements_absent(folder.worker_settlements)\n",
            '    settlement_files.ensure_worker_settlements_absent(folder.worker_settlements / "nigdzie")\n',
        ),
    ),
    EXPLORER,
    "Przebieg rozliczeń startuje w okresie, który Tablica okresów pokazuje jako zamknięty",
    NEW,
)

BOUNDARIES: Final[Mapping[str, Mapping[str, tuple[Mutation, ...]]]] = {
    "Wpisanie raportów w zamkniętym okresie": {
        # The same consumer acts in a period that is not open for it, in a folder with a Plik zbiorczy.
        "states": (ENTERING_CLOSED_BY_INTERNAL,),
        # Another process acts in the closed period.
        "consumers": (SETTLEMENT_WITHOUT_GUARD,),
    },
    "Przygotowanie w zamkniętym okresie": {
        "states": (
            Mutation(
                "Nienadpisywanie Przygotowania sprawdza tylko Rozliczenie wewnętrzne",
                (Edit(PREPARATION_FILES, PERIOD_FILES_GUARD, "        for target in (folder.internal_settlement,):\n"),),
                EXPLORER,
                "Przygotowanie startuje w okresie, który ma już Plik zbiorczy",
                NEW,
            ),
        ),
        "consumers": (SETTLEMENT_WITHOUT_GUARD,),
    },
    "ADR 0005": {
        "states": (
            Mutation(
                "Nienadpisywanie Przygotowania liczy sam Folder okresu jako plik okresu",
                (
                    Edit(
                        PREPARATION_FILES,
                        PERIOD_FILES_GUARD,
                        "        for target in (folder.internal_settlement, folder.collective_file, folder.directory):\n",
                    ),
                ),
                EXPLORER,
                "Tablica okresów daje „Przygotuj plik zbiorczy” przy pustym Folderze okresu, a Przygotowanie się zatrzymuje",
                NEW,
            ),
        ),
        # Another consumer refuses a period with only the Rozliczenie wewnętrzne, which it should treat as open.
        "consumers": (ENTERING_CLOSED_BY_INTERNAL,),
    },
}
"""Broken variants just outside each part of the shape of each known finding and accepted risk of the explorer
(``StateShape``), by its name and part: the same harm, but with that one part other than its story says, so each must
give a new violation (#920). ``tests/test_mutacje_skilli.py`` reds an entry of ``KNOWN_FINDINGS`` or
``ACCEPTED_RISKS`` with a part without one here."""

MUTATIONS = (
    Mutation(
        "Status okresu bez Folderu rozliczeń pracowników",
        (
            Edit(
                PERIOD_FOLDER,
                '        if self.worker_settlements_folder_exists:\n            return "worker_settlements_ready"\n',
                '        if self.worker_settlements_folder_exists and self.worker_settlement_count > 0:\n'
                '            return "worker_settlements_ready"\n',
            ),
        ),
        EXPLORER,
        "pusty Folder rozliczeń pracowników daje „Plik zbiorczy przygotowany” i krok „Utwórz rozliczenia pracowników”",
        NEW,
    ),
    Mutation(
        "Uzupełnienie po Przebiegu rozliczeń według złego Statusu okresu",
        (
            Edit(
                FILLING,
                '    return folder.observe().status == "worker_settlements_ready"\n',
                '    return folder.observe().status == "collective_file_prepared"\n',
            ),
        ),
        EXPLORER,
        "tata uzupełnia Plik zbiorczy okresu, który już rozliczono, a przed Przebiegiem widzi podgląd bez ilości",
        NEW,
    ),
    Mutation(
        "Wpisanie raportów nie zamyka żadnego okresu",
        (
            Edit(
                REPORT_ENTERING,
                "                for parent in folders.locations.get(period, ())\n",
                "                for parent in folders.locations.get(period, ())[1:]\n",
            ),
        ),
        EXPLORER,
        "Wpisanie raportów wpisuje do INTERMAX w dniach okresu z Plikiem zbiorczym",
        NEW,
    ),
    Mutation(
        "karta Przebiegu rozliczeń daje okres z Rozliczeniami pracowników",
        (
            Edit(
                SETTLEMENT_KIND,
                '            frozenset({"collective_file_prepared"}),\n',
                '            frozenset({"collective_file_prepared", "worker_settlements_ready"}),\n',
            ),
        ),
        EXPLORER,
        "karta obiecuje Przebieg rozliczeń, który zatrzyma się na FOLDER_ROZLICZEN_ISTNIEJE",
        NEW,
    ),
    Mutation(
        "nieczytelny folder czytany jak brak folderu",
        (
            Edit(
                PERIOD_FOLDER,
                "    except OSError as error:\n        raise PeriodFolderInaccessible(folder) from error\n",
                "    except OSError:\n        pass\n",
            ),
        ),
        EXPLORER,
        "Tablica okresów pokazuje „Brak plików okresu” i krok „Przygotuj plik zbiorczy” dla folderu, którego nie odczytała",
        NEW,
    ),
    Mutation(
        "karta Przygotowania pokazuje każdy okres jako Brak plików okresu",
        (
            Edit(
                PERIOD_START,
                "        status_label=period_status_label(status),\n",
                '        status_label=period_status_label("no_period_files"),\n',
            ),
        ),
        EXPLORER,
        "karta startu Przygotowania nazywa zamknięty okres „Brak plików okresu”",
        NEW,
    ),
    Mutation(
        "stan z Plikiem zbiorczym bez dostępu budowany z plikiem, który da się odczytać",
        (
            Edit(
                EXPLORER_FILE,
                "        for path, folder in locked:\n            take_access(path, folder=folder)\n",
                "        for path, folder in locked:\n            if folder:\n                take_access(path, folder=folder)\n",
            ),
        ),
        EXPLORER,
        "sprawdzenie ocenia stan, którego nie zbudowało, i przepuszcza konsumenta, który czyta niedostępny plik jak brak",
        NEW,
    ),
    Mutation(
        "odebranie dostępu bez skutku",
        (Edit(EXPLORER_FILE, "        path.chmod(0)\n", "        pass\n"),),
        EXPLORER,
        "zakres niedostepne przechodzi bez żadnego stanu bez dostępu",
        "STATUS OKRESU: LUKA MODELU",
    ),
    *dict.fromkeys(mutation for parts in BOUNDARIES.values() for mutations in parts.values() for mutation in mutations),
)


if __name__ == "__main__":
    raise SystemExit(check_all(MUTATIONS))
