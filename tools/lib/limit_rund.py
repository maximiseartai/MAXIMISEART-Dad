"""Limit rund przeglądu (skill ``przeglad``, „Kolejne rundy”): PR, który ma ``LIMIT`` rund z ``FAIL`` od ostatniej
zmiany podejścia, nie dostaje kolejnej rundy, dopóki autor nie zmieni podejścia w tym samym PR i nie zapisze tego
komentarzem PR, którego pierwsza niepusta linia to ``ZMIANA PODEJŚCIA: <zdanie>`` (``DECLARATION``).

Wyjście zostaje w tym samym PR, bo bramka korzenia i bramka idiomu czytają werdykty PR, więc Ważne każdej rundy,
także sprzed zmiany podejścia, zostają tam, gdzie merge ich wymaga; nowy PR zaczynałby bez nich.

Runda z ``FAIL`` to commit, dla którego PR ma werdykt ``FAIL`` (``werdykt_pr.read``: komentarz albo recenzja konta
z prawem zapisu z linią ``WERDYKT: FAIL <SHA>``), liczony raz, choćby miał kilka werdyktów, tak jak linia ``RUNDA``
trybu ``--przeglad``. Recenzja ``CHANGES_REQUESTED`` bez linii werdyktu rundą nie jest. Zmiana podejścia to komentarz
albo recenzja konta z prawem zapisu (nie ``PENDING``) z linią ``DECLARATION`` i niepustym zdaniem; zeruje licznik tylko
wtedy, gdy powstała po ``LIMIT``-tej rundzie z ``FAIL`` od poprzedniej zmiany, więc komentarz napisany zawczasu, po
każdej rundzie, licznika nie zeruje.

Po ``LIMIT`` rundach z ``FAIL`` bez zmiany podejścia odmawiają te same przyczyną trzy kroki, przez które idzie każda
runda: ``--przeglad`` (krok 1 recenzenta) przed diffem i skillami, ``--werdykt`` przed publikacją, i ``PASS``, i
``FAIL``, oraz zgoda na merge (warunek 3, a przez niego status ``Werdykt i bramka``, którego wymaga ruleset ``main``),
więc ``PASS`` opublikowany z pominięciem ``--werdykt`` też nie scala PR.

Limit obowiązuje w wątku, którego najstarszy werdykt nie powstał przed wdrożeniem tego modułu (decyzja Q20 ADR 0031:
wątki, które już pracują, kończą po swojemu), co rozstrzyga ``werdykt_pr.rule_applies`` z chwilą
``werdykt_pr.deployment`` dla pliku ``MARKER``.

Granica: narzędzie nie sprawdza, czy podejście naprawdę się zmieniło (zdanie komentarza i diff od ostatniego ``FAIL``
ocenia recenzent następnej rundy), a usunięty komentarz ``FAIL`` rundą już nie jest. PR zamknięty i zastąpiony nowym
PR zabiera Ważne ze sobą, bo bramki czytają tylko werdykty własnego PR; limit do tego nie kieruje.
"""

from __future__ import annotations

from datetime import datetime

from stan_pr import Pull
import werdykt_pr

LIMIT = 3
MARKER = "tools/lib/limit_rund.py"
DECLARATION = "ZMIANA PODEJŚCIA: "


def _declares(item: dict[str, object]) -> bool:
    """Czy komentarz albo recenzja ``item`` to zmiana podejścia konta z prawem zapisu; linie są bez odstępów na
    brzegach, więc linia z samym ``DECLARATION`` się z nim nie zaczyna, a zdanie po nim nie jest puste."""

    if item.get("authorAssociation") not in werdykt_pr.TRUSTED or item.get("state") == "PENDING":
        return False
    lines = werdykt_pr.text_lines(item.get("body", ""))
    return bool(lines) and lines[0].startswith(DECLARATION)


def failed_rounds(pull: Pull) -> list[str]:
    """SHA commitów z werdyktem ``FAIL`` od ostatniej zmiany podejścia, która zerowała licznik, w kolejności pierwszego
    takiego werdyktu, każdy raz w całym PR."""

    seen: set[str] = set()
    since: list[str] = []
    for item in pull.verdicts:
        if _declares(item):
            since = [] if len(since) >= LIMIT else since
            continue
        found = werdykt_pr.read(item, pull.head)
        if found is not None and found.decision == "FAIL" and found.commit is not None and found.commit not in seen:
            seen.add(found.commit)
            since.append(found.commit)
    return since


def problem(pull: Pull, deployed: datetime | None) -> str | None:
    """Przyczyna odmowy rundy ``pull``, gdy ma ``LIMIT`` rund z ``FAIL`` od ostatniej zmiany podejścia, a limit
    obowiązuje w wątku (``deployed`` to ``werdykt_pr.deployment`` dla ``MARKER``); ``None``, gdy runda może się odbyć."""

    failed = failed_rounds(pull)
    if len(failed) < LIMIT or not werdykt_pr.rule_applies(pull, deployed):
        return None
    commits = ", ".join(sha[:7] for sha in failed)
    return (
        f"limit rund: rund z FAIL {len(failed)} ({commits}) bez zmiany podejścia, a po {LIMIT}. rundzie z FAIL PR nie"
        f" dostaje kolejnej (skill przeglad, „Kolejne rundy”): zmień podejście w #{pull.number} (atak na przesłankę,"
        f" granica z mechanizmu albo usunięcie z PR części, której przegląd nie przyjął) i opisz je komentarzem PR"
        f" z pierwszą linią „{DECLARATION}<zdanie>”"
    )


def deployed_problem(pull: Pull) -> str | None:
    """``problem`` z chwilą wdrożenia limitu na bazie ``pull`` pobranej z ``origin``."""

    return problem(pull, werdykt_pr.deployment(pull.base, MARKER))
