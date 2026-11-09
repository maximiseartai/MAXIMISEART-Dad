"""Show that the cleanup tests fail when a run of this skill again leaves workbooks or a growing Excel behind (#390).

Each mutation runs on its own copy of the checkout (``tools/lib/silnik_mutacji.py``) with
``tests/test_sprzatanie_excela.py``, which fakes Excel's AppleScript, so it also runs on
Windows in CI. A mutation whose anchor text is no longer in its file exactly once is reported
as NIEAKTUALNA: update it to the new code.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))

from silnik_mutacji import Edit, Mutation, check_all

EXCEL = Path(".agents/skills/verify-skoroszyty-w-excelu/scripts/excel.py")
RUNNER = Path(".agents/skills/verify-skoroszyty-w-excelu/scripts/run_excel_verification.py")
TESTS = ("tests/test_sprzatanie_excela.py",)

MUTATIONS = (
    Mutation(
        "sprzątanie połyka ExcelDialog",
        (Edit(EXCEL, "open_paths() if running() else []", "_open_paths_quietly()"),),
        TESTS,
        "przy oknie dialogowym run usuwa biurko pod otwartymi skoroszytami i raportuje scratch_removed=true",
    ),
    Mutation(
        "biurko usunięte mimo niezamkniętych skoroszytów",
        (Edit(RUNNER, "    if left_open:\n        notes.append", "    if False:\n        notes.append"),),
        TESTS,
        "w Excelu zostają okna plików, których już nie ma",
    ),
    Mutation(
        "bez zamykania skoroszytów martwych runów na starcie",
        (Edit(RUNNER, "    stale = excel.close_under(excel.DESK)\n", "    stale: list[str] = []\n"),),
        TESTS,
        "skoroszyty runów zabitych przed sprzątaniem zbierają się w Excelu z runu na run",
    ),
    Mutation(
        "run nie sprząta po martwych runach",
        (Edit(RUNNER, "        _sweep(run)\n", ""),),
        TESTS,
        "skoroszyty i biurka runów zabitych przed sprzątaniem zostają, a doctor odmawia następnego runu",
    ),
    Mutation(
        "Excel kończony tylko, gdy run go uruchomił",
        (
            Edit(
                RUNNER,
                'notes.append(f"excel_quit={str(excel.quit_if_idle()).lower()}")',
                'notes.append(f"excel_quit={str(run.started_excel is not None and excel.quit_if_idle()).lower()}")',
            ),
        ),
        TESTS,
        "zastany Excel bez skoroszytów działa dalej i rośnie z runu na run aż do zawieszenia",
    ),
    Mutation(
        "Excel kończony mimo skoroszytu Maksa",
        (Edit(EXCEL, "    if held:\n        return False\n", ""),),
        TESTS,
        "run zamyka Excela z otwartym plikiem Maksa",
    ),
    Mutation(
        "Excel z oknem dialogowym zatrzymany mimo skoroszytu użytkownika",
        (Edit(RUNNER, " and not _holds_others(run.desk):", ":"),),
        TESTS,
        "run zabija Excela, w którym użytkownik otworzył w trakcie runu swój skoroszyt, i ten skoroszyt przepada",
    ),
    Mutation(
        "nieudane zamknięcie Excela wychodzi ze sprzątania",
        (Edit(RUNNER, '        notes.append(f"excel_quit_failed=', '        raise\n        notes.append(f"excel_quit_failed='),),
        TESTS,
        "Excel, który nie odpowie na quit, kończy run tracebackiem bez linii VERIFY, cleanup.txt i usunięcia biurka",
    ),
)


if __name__ == "__main__":
    raise SystemExit(check_all(MUTATIONS))
