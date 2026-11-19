"""Katalog repo, który box boat przeniósł w trakcie biegu (``.agents/skills/boat/SKILL.md``).

Box ze snapshotu albo po wznowieniu podaje katalog domowy z montowania FUSE ładowanego leniwie (lazyfs). Po
załadowaniu lazyfs podstawia prawdziwy dysk, a stare drzewo przenosi pod ``KATALOG_ZWOLNIONY``: proces, który już
biegł w katalogu repo, ma wtedy katalog roboczy pod tą ścieżką. Plugin stanu procesu
(``tests/fixtures/stan_procesu.py``) zgłasza taki katalog jako ``KOMUNIKAT``, a nie jako stan zostawiony przez test, i
daje testowi własność junit ``WLASNOSC``; ``tools/szybko.py`` kończy wynikiem ``SZYBKO INFRA`` krok pytest, w którego
junit każdy test, który padł, ma tę własność."""

from __future__ import annotations

KATALOG_ZWOLNIONY = "/var/lib/ascii-lazy/retired/"
KOMUNIKAT = "BOX: boat przeniósł katalog repo w trakcie biegu; to nie test, powtórz bieg"
WLASNOSC = "box_boat_przeniosl_katalog_repo"


def przeniesiony(katalog: str) -> bool:
    """Czy katalog roboczy ``katalog`` to katalog repo, który box przeniósł po załadowaniu dysku."""

    return katalog.startswith(KATALOG_ZWOLNIONY)
