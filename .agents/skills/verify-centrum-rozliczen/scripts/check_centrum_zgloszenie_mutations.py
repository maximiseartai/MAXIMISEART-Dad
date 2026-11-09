"""Show that the drive of verify-centrum-rozliczen fails on broken variants of its `zgloszenie` feature.

Each mutation runs the feature on its own copy of the checkout (``tools/mutacje.py``) and must make it fail.
A mutation whose anchor text is no longer in its file is reported as NIEAKTUALNA: update it to the new code.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / ".agents/skills/verify-centrum-rozliczen/scripts"))

from cele_mutacji_centrum import BUILD, DAD_CASES, KEYED_BOX, OUTBOX, REPORTS, ZGLOSZENIE
from mutacje import Edit, Mutation, check_all

MUTATIONS = (
    Mutation(
        "odmowa Skrzynki nie odrzuca klucza",
        (
            Edit(
                KEYED_BOX,
                "            self._verdict = _Verdict(digest, isinstance(outcome, Refused), asked_at)\n",
                "            self._verdict = _Verdict(digest, False, asked_at)\n",
            ),
        ),
        ZGLOSZENIE,
        "Konfiguracja mówi „Zgłoszenia: gotowe” o kluczu, którego Skrzynka odmawia",
    ),
    Mutation(
        "kolejka nie ponawia wysyłki po porażce",
        (
            Edit(
                OUTBOX,
                "waiting = self._stopped_on is not None or self._read_failed or self._archive_refused\n",
                "waiting = self._read_failed or self._archive_refused\n",
            ),
        ),
        ZGLOSZENIE,
        "Zgłoszenie bez sieci nie wysyła się samo po powrocie sieci",
    ),
    Mutation(
        "Zgłoszenie odrzucone przez Skrzynkę czeka na internet",
        # Obie drogi do „odrzucone”: odpowiedź na „Wyślij do Maksa” i odrzucenie, które kolejka zgłasza później.
        (
            Edit(
                DAD_CASES,
                'return common_contract.Rejected(state="rejected")',
                'return common_contract.Queued(state="queued", waits_for="internet")',
            ),
            Edit(
                REPORTS,
                'self._show(common_contract.Rejected(state="rejected"))',
                'self._show(common_contract.Queued(state="queued", waits_for="internet"))',
            ),
        ),
        ZGLOSZENIE,
        "tata czeka na internet, który nie naprawi treści odrzuconej przez Skrzynkę (Q17)",
    ),
    Mutation(
        "powrót problemu z otwartym Zgłoszeniem czeka na kliknięcie",
        (
            Edit(
                REPORTS,
                "            if comeback is None or self._returned or not isinstance(self._state, diagnosis_contract.ReportWaiting):\n",
                "            if True:\n",
            ),
        ),
        ZGLOSZENIE,
        "Maks nie widzi w otwartym Zgłoszeniu, że problem wraca, bo tata nie ma przycisku (#820)",
    ),
    Mutation(
        "brak Tokenu do Zgłoszeń obiecuje wysyłkę",
        (Edit(BUILD, "`Token do Zgłoszeń nie działa. Skontaktuj się z Maksem.`", "`Wyślę do Maksa, gdy będzie internet.`"),),
        ZGLOSZENIE,
        "bez tokenu tata czyta, że Zgłoszenie wyjdzie samo, zamiast skontaktować się z Maksem (Q17)",
    ),
)


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    raise SystemExit(check_all(MUTATIONS))
