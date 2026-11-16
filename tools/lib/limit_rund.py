"""Limit rund przeglądu (skill ``przeglad``, „Kolejne rundy”): PR, który ma ``LIMIT`` rund z ``FAIL``, nie dostaje
kolejnej rundy, więc koordynator zamyka go i otwiera nowy PR ze zmienionym podejściem albo z częścią, którą przegląd
przyjął.

Runda z ``FAIL`` to commit, dla którego PR ma werdykt ``FAIL`` (``werdykt_pr.read``: komentarz albo recenzja konta
z prawem zapisu z linią ``WERDYKT: FAIL <SHA>``), liczony raz, choćby miał kilka werdyktów, tak jak linia ``RUNDA``
trybu ``--przeglad``. Recenzja ``CHANGES_REQUESTED`` bez linii werdyktu rundą nie jest.

Po ``LIMIT`` rundach z ``FAIL`` odmawiają te same przyczyną trzy kroki, przez które idzie każda runda: ``--przeglad``
(krok 1 recenzenta) przed diffem i skillami, ``--werdykt`` przed publikacją, i ``PASS``, i ``FAIL``, oraz zgoda na
merge (warunek 3, a przez niego status ``Werdykt i bramka``, którego wymaga ruleset ``main``), więc ``PASS``
opublikowany z pominięciem ``--werdykt`` też nie scala PR. Wyjście to nowy PR: jego rundy liczą się od zera.

Limit obowiązuje w wątku, którego najstarszy werdykt nie powstał przed wdrożeniem tego modułu (decyzja Q20 ADR 0031:
wątki, które już pracują, kończą po swojemu), co rozstrzyga ``werdykt_pr.rule_applies`` z chwilą
``werdykt_pr.deployment`` dla pliku ``MARKER``.

Granica: narzędzie nie odróżni nowego PR ze zmienionym podejściem od nowego PR z tym samym diffem, więc to ocenia
recenzent pierwszej rundy nowego PR, a usunięty komentarz ``FAIL`` rundą już nie jest.
"""

from __future__ import annotations

from datetime import datetime

from stan_pr import Pull
import werdykt_pr

LIMIT = 3
MARKER = "tools/lib/limit_rund.py"


def failed_rounds(pull: Pull) -> list[str]:
    """SHA commitów z werdyktem ``FAIL`` w kolejności pierwszego takiego werdyktu, każdy raz."""

    failed: list[str] = []
    for verdict in pull.verdicts:
        found = werdykt_pr.read(verdict, pull.head)
        if found is not None and found.decision == "FAIL" and found.commit is not None and found.commit not in failed:
            failed.append(found.commit)
    return failed


def problem(pull: Pull, deployed: datetime | None) -> str | None:
    """Przyczyna odmowy rundy ``pull``, gdy ma ``LIMIT`` rund z ``FAIL``, a limit obowiązuje w wątku (``deployed`` to
    ``werdykt_pr.deployment`` dla ``MARKER``); ``None``, gdy runda może się odbyć."""

    failed = failed_rounds(pull)
    if len(failed) < LIMIT or not werdykt_pr.rule_applies(pull, deployed):
        return None
    commits = ", ".join(sha[:7] for sha in failed)
    return (
        f"limit rund: rund z FAIL {len(failed)} ({commits}), a po {LIMIT}. rundzie z FAIL PR nie dostaje kolejnej"
        f" (skill przeglad, „Kolejne rundy”): zamknij #{pull.number} i otwórz nowy PR ze zmienionym podejściem"
        f" albo z częścią, którą przegląd przyjął, z linkiem do #{pull.number} w „## Why”"
    )


def deployed_problem(pull: Pull) -> str | None:
    """``problem`` z chwilą wdrożenia limitu na bazie ``pull`` pobranej z ``origin``."""

    return problem(pull, werdykt_pr.deployment(pull.base, MARKER))
