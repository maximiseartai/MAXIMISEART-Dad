"""Show that explore_intermax.py fails on broken variants of the INTERMAX save, and for each part of the shape of each
known finding of the explorer on a broken variant just outside it (``BOUNDARIES``).

Each mutation runs on its own copy of the checkout (``tools/lib/silnik_mutacji.py``) and must end the checker's report with the
expected line. A mutation whose anchor text is no longer in its file is reported as NIEAKTUALNA: update it to the new
code.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import sys
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))

from silnik_mutacji import Edit, Mutation, check_all

REPLACE = Path("src/rozliczenia/intermax_replace.py")
RESTORE = Path("src/rozliczenia/intermax_restore.py")
COPIES = Path("src/rozliczenia/intermax_copies.py")
SAVE = Path("src/rozliczenia/workbook_save.py")
EXPLORER = (".agents/skills/verify-zapis-intermax/scripts/explore_intermax.py",)
NEW = "INTERMAX: NOWE NARUSZENIE"

READ_BEFORE_PAUSE = Mutation(
    "ponowny odczyt INTERMAX przed przerwą zamiast po niej",
    (
        Edit(REPLACE, "            waiting.pause(_PAUSE_S)\n            try:\n", "            try:\n"),
        Edit(
            REPLACE,
            "            if not unchanged:\n                raise _Refused(Refusal.ONEDRIVE_HOLDS)\n",
            "            if not unchanged:\n                raise _Refused(Refusal.ONEDRIVE_HOLDS)\n            waiting.pause(_PAUSE_S)\n",
        ),
    ),
    EXPLORER,
    "zmiana pracownika, którą OneDrive wgrał w przerwie przed ponowną próbą, przepada przy tej próbie",
    NEW,
)
COMPARED_WITH_REFUSED = Mutation(
    "ponowny odczyt INTERMAX porównany z bajtami tuż po odmowie OneDrive zamiast z przeczytanymi",
    (
        Edit(
            REPLACE,
            "            waiting.pause(_PAUSE_S)\n            try:\n                unchanged = disk.read(target) == current\n",
            "            try:\n                seen = disk.read(target)\n                waiting.pause(_PAUSE_S)\n"
            "                unchanged = disk.read(target) == seen\n",
        ),
    ),
    EXPLORER,
    "zmiana pracownika, którą OneDrive wgrał przed odmową podmiany, przepada przy ponownej próbie",
    NEW,
)

OWN_BYTES_REPLACED = Mutation(
    "podmiana, gdy INTERMAX zmienił się po odczycie, najpierw zapisuje na nim nowy plik runu",
    (
        Edit(
            REPLACE,
            "                disk.replace(temporary, target)\n",
            "                seen = target.read_bytes()\n"
            "                if seen != current:\n"
            "                    target.write_bytes(content)\n"
            "                try:\n"
            "                    disk.replace(temporary, target)\n"
            "                except BaseException:\n"
            "                    if seen != current:\n"
            "                        target.write_bytes(seen)\n"
            "                    raise\n",
        ),
    ),
    EXPLORER,
    "zmiana pracownika, którą OneDrive wgrał po odczycie, przepada pod plikiem runu zapisanym przed podmianą",
    NEW,
)
COPY_OF_NEW = Mutation(
    "Kopia INTERMAX z nowym plikiem runu, gdy INTERMAX zmienił się przed zapisem Kopii",
    (
        Edit(
            REPLACE,
            "            disk.create(copy.path, current)\n",
            "            disk.create(copy.path, current if register.read_bytes() == current else content)\n",
        ),
    ),
    EXPLORER,
    "po zmianie pracownika żadna Kopia nie ma ani tej zmiany, ani INTERMAX, który run przeczytał",
    NEW,
)

CHANGE_AFTER_READ: Final[Mapping[str, tuple[Mutation, ...]]] = {
    "came_before": (READ_BEFORE_PAUSE,),
    "refusals_after": (COMPARED_WITH_REFUSED,),
    "lost": (OWN_BYTES_REPLACED,),
}
BOUNDARIES: Final[Mapping[str, Mapping[str, tuple[Mutation, ...]]]] = {
    "BEZ_UTRATY_ZMIAN": CHANGE_AFTER_READ,
    "KOPIA_ZASTAPIONEGO": {**CHANGE_AFTER_READ, "copy": (COPY_OF_NEW,)},
}
"""Broken variants just outside each part of the shape of each known finding of the explorer (``FindingShape``), by
its name and part: the same harm as the finding's, but with that one part other than its story says, so each must give
a new violation (#920). ``tests/test_mutacje_skilli.py`` reds an entry of ``KNOWN_FINDINGS`` with a part without one
here. Both findings share the parts of how the worker's change was lost, and the same worker's change breaks both
rules; only KOPIA_ZASTAPIONEGO has a part for the Kopia."""

MUTATIONS = (
    Mutation(
        "podmiana bez Kopii INTERMAX",
        (Edit(REPLACE, "            disk.create(copy.path, current)\n", "            pass\n"),),
        EXPLORER,
        "INTERMAX zmieniony bez Kopii, z której tata by go przywrócił",
        NEW,
    ),
    Mutation(
        "Kopia z innych bajtów niż przeczytane",
        (Edit(REPLACE, "            disk.create(copy.path, current)\n", '            disk.create(copy.path, b"")\n'),),
        EXPLORER,
        "Kopia INTERMAX nie przywraca stanu sprzed podmiany",
        NEW,
    ),
    Mutation(
        "Kopia zostaje po nieudanej podmianie",
        (
            Edit(
                REPLACE,
                "        if not replaced:\n            for copy in made:\n                _forget(copy.path, disk)\n",
                "        pass\n",
            ),
        ),
        EXPLORER,
        "Zatrzymanie przy INTERMAX otwartym w Excelu albo trzymanym przez OneDrive zostawia Kopię, choć INTERMAX się "
        "nie zmienił",
        NEW,
    ),
    Mutation(
        "Kopia o zajętej nazwie usuwana po błędzie jej zapisu",
        (Edit(REPLACE, "            if not taken:\n                made.append(copy)", "            if True:\n                made.append(copy)"),),
        EXPLORER,
        "drugie przywrócenie w tej samej sekundzie usuwa Kopię stanu sprzed pierwszego",
        NEW,
    ),
    Mutation(
        "błąd sprawdzenia nazwy Kopii wychodzi wyjątkiem",
        (
            Edit(
                REPLACE,
                "        try:\n            taken = disk.exists(copy.path)",
                "        taken = disk.exists(copy.path)\n        try:\n            pass",
            ),
        ),
        EXPLORER,
        "folder Kopii bez dostępu daje błąd nieoczekiwany zamiast Komunikatu dla taty",
        NEW,
    ),
    Mutation(
        "nieudane usunięcie starych Kopii wychodzi wyjątkiem",
        (Edit(REPLACE, "    except OSError:\n        return False\n", "    except ValueError:\n        return False\n"),),
        EXPLORER,
        "podmieniony INTERMAX kończy się nieoczekiwanym błędem zamiast ostrzeżenia",
        NEW,
    ),
    Mutation(
        "plik tymczasowy zostaje po nieudanej podmianie",
        (
            Edit(
                SAVE,
                '            raise WorkbookSaveError(target, SaveProblem.REPLACE) from exc\n    finally:\n        temporary_path.unlink(missing_ok=True)\n',
                '            raise WorkbookSaveError(target, SaveProblem.REPLACE) from exc\n    finally:\n        pass\n',
            ),
        ),
        EXPLORER,
        "obok INTERMAX w OneDrive zostaje plik tymczasowy",
        NEW,
    ),
    Mutation(
        "ponowna próba podmiany bez ponownego odczytu INTERMAX",
        (Edit(REPLACE, "            if not unchanged:\n                raise _Refused(Refusal.ONEDRIVE_HOLDS)\n", ""),),
        EXPLORER,
        "zmiana pracownika, którą OneDrive wgrał, gdy odmówił podmiany, przepada przy ponownej próbie",
        NEW,
    ),
    Mutation(
        "stare Kopie sortowane odwrotnie",
        (
            Edit(
                COPIES,
                "    return sorted(copies, key=lambda copy: (copy.moment, copy.path.name), reverse=True)\n",
                "    return sorted(copies, key=lambda copy: (copy.moment, copy.path.name))\n",
            ),
        ),
        EXPLORER,
        "od 11. podmiany limit Kopii usuwa świeżą Kopię zaraz po podmianie",
        NEW,
    ),
    # Jedna Kopia mniej, a nie jedna Kopia: przy [1:] podmiana usuwa 10 Kopii, każdą za punktem eksploratora, więc
    # harmonogramów jest 5,9 razy więcej (14255 zamiast 2407) i mutacja doszła w CI do limitu --limit-s (#963).
    Mutation(
        "zostaje KEPT - 1 Kopii zamiast KEPT",
        (Edit(COPIES, "    return listed(directory)[KEPT:]\n", "    return listed(directory)[KEPT - 1 :]\n"),),
        EXPLORER,
        "tata ma dziewięć Kopii INTERMAX zamiast dziesięciu",
        NEW,
    ),
    Mutation(
        "Kopie ułożone po nazwie zamiast po chwili z nazwy",
        (
            Edit(
                COPIES,
                "    return sorted(copies, key=lambda copy: (copy.moment, copy.path.name), reverse=True)\n",
                "    return sorted(copies, key=lambda copy: copy.path.name, reverse=True)\n",
            ),
        ),
        EXPLORER,
        "limit 10 usuwa świeże Kopie „przed przywróceniem”, bo ich nazwa stoi wcześniej w alfabecie",
        NEW,
    ),
    Mutation(
        "Kopia nadpisuje Kopię o tej samej nazwie",
        (Edit(REPLACE, "os.O_WRONLY | os.O_CREAT | os.O_EXCL", "os.O_WRONLY | os.O_CREAT | os.O_TRUNC"),),
        EXPLORER,
        "drugie przywrócenie w tej samej sekundzie nadpisuje Kopię stanu sprzed pierwszego",
        NEW,
    ),
    Mutation(
        "Kopia nadpisuje Kopię o tej samej nazwie, a zajęta nazwa nie zatrzymuje",
        (
            Edit(REPLACE, "os.O_WRONLY | os.O_CREAT | os.O_EXCL", "os.O_WRONLY | os.O_CREAT | os.O_TRUNC"),
            Edit(REPLACE, "            taken = disk.exists(copy.path)  #", "            taken = disk.exists(copy.path) and False  #"),
        ),
        EXPLORER,
        "udane drugie przywrócenie w tej samej sekundzie nadpisuje Kopię stanu sprzed pierwszego",
        NEW,
    ),
    Mutation(
        "przywrócenie podmienia INTERMAX bajtami sprzed przywrócenia",
        (
            Edit(
                RESTORE,
                "        content = workbook_files.workbook_content(chosen.path)\n",
                "        content = workbook_files.workbook_content(register)\n",
            ),
        ),
        EXPLORER,
        "tata klika „Przywróć tę kopię”, a INTERMAX dalej ma zepsuty stan",
        NEW,
    ),
    Mutation(
        "nieudana podmiana usuwa wszystkie Kopie",
        (
            Edit(
                REPLACE,
                "            for copy in made:\n                _forget(copy.path, disk)\n",
                "            for old in list(copies.iterdir()):\n                _forget(old, disk)\n",
            ),
        ),
        EXPLORER,
        "Zatrzymanie przy INTERMAX otwartym w Excelu usuwa wcześniejsze Kopie taty",
        NEW,
    ),
    *dict.fromkeys(mutation for parts in BOUNDARIES.values() for mutations in parts.values() for mutation in mutations),
)

if __name__ == "__main__":
    raise SystemExit(check_all(MUTATIONS))
