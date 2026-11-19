"""Katalog repo, który box boat przeniósł w trakcie biegu (``.agents/skills/boat/SKILL.md``).

Box ze snapshotu albo po wznowieniu startuje na dysku ładowanym leniwie. Gdy boat kończy jego ładowanie (``hydrated``
w ``boat info``), podmienia drzewo ``/home`` na pełne, a stare przenosi pod ``KATALOG_ZWOLNIONY``: proces, który
już biegł w katalogu repo, ma wtedy katalog roboczy pod tą ścieżką. Plugin stanu procesu
(``tests/fixtures/stan_procesu.py``) zgłasza taki katalog jako ``KOMUNIKAT``, a nie jako stan zostawiony przez test, a
``tools/szybko.py`` kończy bieg z tym komunikatem wynikiem ``SZYBKO INFRA``."""

from __future__ import annotations

KATALOG_ZWOLNIONY = "/var/lib/ascii-lazy/retired/"
KOMUNIKAT = "BOX: boat przeniósł katalog repo w trakcie biegu; to nie test, powtórz bieg"


def przeniesiony(katalog: str) -> bool:
    """Czy katalog roboczy ``katalog`` to katalog repo, który box przeniósł po załadowaniu dysku."""

    return katalog.startswith(KATALOG_ZWOLNIONY)
