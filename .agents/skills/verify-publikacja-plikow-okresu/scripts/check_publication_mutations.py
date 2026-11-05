"""Show that explore_publication.py fails on broken variants of the publication code, and for each part of the shape
of each accepted risk of the explorer on a broken variant just outside it (``BOUNDARIES``).

Each mutation runs on its own copy of the checkout (``tools/mutacje.py``) and must
end the checker's report with the expected line. A mutation whose anchor text is no
longer in ``preparation_files.py`` is reported as NIEAKTUALNA: update it to the new code.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import sys
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))

from mutacje import Edit, Mutation, check_all

VERIFIED = Path("src/rozliczenia/preparation_files.py")
EXPLORER = (".agents/skills/verify-publikacja-plikow-okresu/scripts/explore_publication.py",)
NEW = "PUBLIKACJA: NOWE NARUSZENIE"

WITHOUT_ROLLBACK = Mutation(
    "bez wycofania opublikowanego pliku",
    (Edit(VERIFIED, "                target.unlink(missing_ok=True)\n", "                pass\n"),),
    EXPLORER,
    "po błędzie zostaje samo Rozliczenie wewnętrzne",
    NEW,
)

ROLLBACK_RETRIED = Mutation(
    "wycofanie ponawia usunięcie opublikowanego pliku, którego nie udało się usunąć",
    (
        Edit(
            VERIFIED,
            "            except OSError as exc:\n"
            "                raise StopError(messages.write_failed_with_file_left(period_directory, target.name)) from exc\n",
            "            except OSError:\n"
            "                try:\n"
            "                    target.unlink(missing_ok=True)\n"
            "                except OSError as exc:\n"
            "                    raise StopError(messages.write_failed_with_file_left(period_directory, target.name)) from exc\n",
        ),
    ),
    EXPLORER,
    "proces zamknięty po nieudanym wycofaniu, przed jego ponowieniem, zostawia samo Rozliczenie wewnętrzne bez komunikatu",
    NEW,
)

BOUNDARIES: Final[Mapping[str, Mapping[str, tuple[Mutation, ...]]]] = {
    "ADR 0005": {
        # Not killed at all: the run goes on after the failed rename and stops with Rozliczenie wewnętrzne left.
        "killed_before": (WITHOUT_ROLLBACK,),
        "left": (
            Mutation(
                "ADR 0005 poza swoimi plikami: pliki okresu przenoszone w odwrotnej kolejności",
                (Edit(VERIFIED, "        for filename in files.filenames:\n", "        for filename in reversed(files.filenames):\n"),),
                EXPLORER,
                "proces zamknięty między dwoma os.rename zostawia sam Plik zbiorczy, którego instrukcja taty nie opisuje",
                NEW,
            ),
        ),
        # The rollback's os.unlink failed (issue #92), and the process was killed before the retry.
        "unlink_failed": (ROLLBACK_RETRIED,),
    },
}
"""Broken variants just outside each part of the shape of each accepted risk and known finding of the explorer
(``RiskShape``), by its name and part: the same harm as the risk's, but with that one part other than its story says,
so each must give a new violation (#920). ``tests/test_mutacje_skilli.py`` reds an entry of ``ACCEPTED_RISKS`` or
``KNOWN_FINDINGS`` with a part without one here."""

MUTATIONS = (
    Mutation(
        "os.replace zamiast os.rename",
        (Edit(VERIFIED, "            os.rename(staged_directory / filename, target)\n", "            os.replace(staged_directory / filename, target)\n"),),
        EXPLORER,
        "plik taty o nazwie pliku okresu zostaje zastąpiony",
        NEW,
    ),
    Mutation(
        "nieudane wycofanie zgłaszane jak zwykły błąd zapisu",
        (Edit(VERIFIED, "                raise StopError(messages.write_failed_with_file_left(period_directory, target.name)) from exc\n", "                raise\n"),),
        EXPLORER,
        "zostaje Rozliczenie wewnętrzne, a komunikat mówi, że nie utworzono żadnego pliku",
        NEW,
    ),
    Mutation(
        "zapis na listę do wycofania przed os.rename",
        (Edit(VERIFIED, "            os.rename(staged_directory / filename, target)\n            published.append(target)\n", "            published.append(target)\n            os.rename(staged_directory / filename, target)\n"),),
        EXPLORER,
        "wycofanie usuwa plik taty",
        NEW,
    ),
    Mutation(
        "błąd sprzątania katalogu tymczasowego jako błąd zapisu",
        (Edit(VERIFIED, ", ignore_cleanup_errors=True\n", "\n"),),
        EXPLORER,
        "oba pliki okresu są w Folderze okresu, a komunikat mówi, że nie utworzono żadnego pliku",
        NEW,
    ),
    Mutation(
        "shutil.move zamiast os.rename",
        (Edit(VERIFIED, "            os.rename(staged_directory / filename, target)\n", "            __import__('shutil').move(staged_directory / filename, target)\n"),),
        EXPLORER,
        "przy zajętej nazwie shutil.move kopiuje plik i nadpisuje cel",
        "PUBLIKACJA: LUKA MODELU",
    ),
    *dict.fromkeys(mutation for parts in BOUNDARIES.values() for mutations in parts.values() for mutation in mutations),
)


if __name__ == "__main__":
    raise SystemExit(check_all(MUTATIONS))
