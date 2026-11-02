"""Show that explore_intermax.py fails on broken variants of the INTERMAX save.

Each mutation runs on its own copy of the checkout (``tools/mutacje.py``) and must end the checker's report with the
expected line. A mutation whose anchor text is no longer in its file is reported as NIEAKTUALNA: update it to the new
code.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))

from mutacje import Edit, Mutation, check_all

REPLACE = Path("src/rozliczenia/intermax_replace.py")
RESTORE = Path("src/rozliczenia/intermax_restore.py")
COPIES = Path("src/rozliczenia/intermax_copies.py")
SAVE = Path("src/rozliczenia/workbook_save.py")
EXPLORER = (".agents/skills/verify-zapis-intermax/scripts/explore_intermax.py",)
NEW = "INTERMAX: NOWE NARUSZENIE"

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
    Mutation(
        "zostaje jedna Kopia zamiast KEPT",
        (Edit(COPIES, "    return listed(directory)[KEPT:]\n", "    return listed(directory)[1:]\n"),),
        EXPLORER,
        "tata ma jedną Kopię INTERMAX zamiast dziesięciu",
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
)

if __name__ == "__main__":
    raise SystemExit(check_all(MUTATIONS))
