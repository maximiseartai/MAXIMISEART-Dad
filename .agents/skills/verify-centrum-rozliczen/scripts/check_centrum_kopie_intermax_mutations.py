"""Show that the drive of verify-centrum-rozliczen fails on broken variants of its `kopie-intermax` feature.

Each mutation runs the feature on its own copy of the checkout (``tools/lib/silnik_mutacji.py``) and must make it fail.
A mutation whose anchor text is no longer in its file is reported as NIEAKTUALNA: update it to the new code.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / ".agents/skills/verify-centrum-rozliczen/scripts"))

from cele_mutacji_centrum import BUILD, INTERMAX_COPIES, KOPIE
from silnik_mutacji import Edit, Mutation, check_all

MUTATIONS = (
    Mutation(
        "lista Kopii od najstarszej",
        (
            Edit(
                INTERMAX_COPIES,
                "    return sorted(copies, key=lambda copy: (copy.moment, copy.path.name), reverse=True)\n",
                "    return sorted(copies, key=lambda copy: (copy.moment, copy.path.name))\n",
            ),
        ),
        KOPIE,
        "tata szuka najnowszej Kopii na końcu listy",
    ),
    Mutation(
        "lista bez Kopii „przed przywróceniem”",
        (
            Edit(
                INTERMAX_COPIES,
                "'|'.join(map(re.escape, _BEFORE.values()))",
                "re.escape(_BEFORE['ordering'])",
            ),
        ),
        KOPIE,
        "po przywróceniu tata nie widzi Kopii stanu sprzed niego, więc nie cofnie przywrócenia",
    ),
    Mutation(
        "ostrzeżenie bez godziny Kopii",
        (Edit(BUILD, "`Zmiany w INTERMAX wprowadzone po `", "`Zmiany w INTERMAX `"),),
        KOPIE,
        "tata nie wie, od której godziny jego zmiany znikną",
    ),
    Mutation(
        "lista nie czyta się po przywróceniu",
        (Edit(BUILD, "message:lg(e)})).finally(()=>{a(!1),t()})}", "message:lg(e)})).finally(()=>{a(!1)})}"),),
        KOPIE,
        "po przywróceniu lista nie ma nowej Kopii stanu sprzed przywrócenia",
    ),
)


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    raise SystemExit(check_all(MUTATIONS))
