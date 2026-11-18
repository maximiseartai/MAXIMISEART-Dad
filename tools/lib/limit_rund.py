"""Limit rund przeglądu (skill ``przeglad``, „Kolejne rundy”): PR, który ma ``LIMIT`` rund z ``FAIL``, nie dostaje
kolejnej rundy, dopóki autor nie zmieni podejścia w tym samym PR i nie zapisze tego komentarzem PR, którego pierwsza
niepusta linia to ``ZMIANA PODEJŚCIA: <zdanie>`` (``DECLARATION``). Po ``END`` (``2 * LIMIT``) rundach z ``FAIL`` PR nie
dostaje już żadnej rundy, jakiekolwiek komentarze ma, więc zostaje mu tylko nowy PR od ``main``: koniec liczą same
rundy z ``FAIL``, bo komentarz zmiany podejścia autor może dopisać, zmienić i usunąć (przed tą granicą #2010 dostał
osiem rund z ``FAIL`` przez cztery komentarze, a Maks 17.11.2026: „9 runda to przesada”).

Wyjście zostaje w tym samym PR, bo bramka korzenia i bramka idiomu czytają werdykty PR, więc Ważne każdej rundy,
także sprzed zmiany podejścia, zostają tam, gdzie merge ich wymaga; nowy PR zaczynałby bez nich.

Runda z ``FAIL`` to commit, dla którego PR ma werdykt ``FAIL`` (``werdykt_pr.read``: komentarz albo recenzja konta
z prawem zapisu z linią ``WERDYKT: FAIL <SHA>``), liczony raz, choćby miał kilka werdyktów, tak jak linia ``RUNDA``
trybu ``--przeglad``. Recenzja ``CHANGES_REQUESTED`` bez linii werdyktu rundą nie jest. Zmiana podejścia to komentarz
albo recenzja konta z prawem zapisu (nie ``PENDING``) z linią ``DECLARATION`` i niepustym zdaniem; liczy się tylko
wtedy, gdy powstała po ``LIMIT``-tej rundzie z ``FAIL``, więc komentarz napisany zawczasu, po każdej rundzie, rundy
nie daje.

Po ``LIMIT`` rundach z ``FAIL`` bez zmiany podejścia i po ``END`` rundach z ``FAIL`` odmawiają te same przyczyną trzy
kroki, przez które idzie każda runda: ``--przeglad`` (krok 1 recenzenta) przed diffem i skillami, ``--werdykt`` przed publikacją,
i ``PASS``, i ``FAIL``, oraz zgoda na merge (warunek 3, a przez niego status ``Werdykt i bramka``, którego wymaga ruleset ``main``),
więc ``PASS`` opublikowany z pominięciem ``--werdykt`` też nie scala PR.

Limit obowiązuje w wątku, którego najstarszy werdykt nie powstał przed wdrożeniem tego modułu (decyzja Q20 ADR 0031:
wątki, które już pracują, kończą po swojemu), co rozstrzyga ``werdykt_pr.rule_applies`` z chwilą
``werdykt_pr.deployment`` dla pliku ``MARKER``.

Granica: narzędzie nie sprawdza, czy podejście naprawdę się zmieniło (zdanie komentarza i diff od ostatniego ``FAIL``
ocenia recenzent następnej rundy), a usunięty komentarz ``FAIL`` rundą już nie jest. Nowy PR po PR zamkniętym
z limitem zaczyna bez jego Ważnych, bo bramki czytają tylko werdykty własnego PR; kod zamkniętego PR nie wszedł do
``main``, więc nic go nie blokuje.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from stan_pr import Pull
import werdykt_pr

LIMIT = 3
END = 2 * LIMIT
MARKER = "tools/lib/limit_rund.py"
DECLARATION = "ZMIANA PODEJŚCIA: "


def _declares(item: dict[str, object]) -> bool:
    """Czy komentarz albo recenzja ``item`` to zmiana podejścia konta z prawem zapisu; linie są bez odstępów na
    brzegach, więc linia z samym ``DECLARATION`` się z nim nie zaczyna, a zdanie po nim nie jest puste."""

    if item.get("authorAssociation") not in werdykt_pr.TRUSTED or item.get("state") == "PENDING":
        return False
    lines = werdykt_pr.text_lines(item.get("body", ""))
    return bool(lines) and lines[0].startswith(DECLARATION)


@dataclass(frozen=True)
class Rounds:
    """Rundy z ``FAIL`` PR: SHA commitów w kolejności pierwszego takiego werdyktu, każdy raz, i czy po ``LIMIT``-tej
    z nich PR ma zmianę podejścia."""

    failed: tuple[str, ...]
    changed: bool


def failed_rounds(pull: Pull) -> Rounds:
    failed: list[str] = []
    changed = False
    for item in pull.verdicts:
        if _declares(item):
            changed = changed or len(failed) >= LIMIT
            continue
        found = werdykt_pr.read(item, pull.head)
        if found is not None and found.decision == "FAIL" and found.commit is not None and found.commit not in failed:
            failed.append(found.commit)
    return Rounds(tuple(failed), changed)


def problem(pull: Pull, deployed: datetime | None) -> str | None:
    """Przyczyna odmowy rundy ``pull``, gdy ma ``END`` rund z ``FAIL`` albo ``LIMIT`` bez zmiany podejścia po nich, a limit
    obowiązuje w wątku (``deployed`` to ``werdykt_pr.deployment`` dla ``MARKER``); ``None``, gdy runda może się odbyć."""

    rounds = failed_rounds(pull)
    if len(rounds.failed) < LIMIT or (rounds.changed and len(rounds.failed) < END) or not werdykt_pr.rule_applies(pull, deployed):
        return None
    commits = ", ".join(sha[:7] for sha in rounds.failed)
    if len(rounds.failed) >= END:
        return (
            f"limit rund: rund z FAIL {len(rounds.failed)} ({commits}), a po {END}. rundzie z FAIL #{pull.number} nie dostaje"
            f" żadnej kolejnej (skill przeglad, „Kolejne rundy”), także po komentarzu „{DECLARATION}<zdanie>”: zamknij"
            f" #{pull.number} komentarzem z powodem i zacznij nowy PR od świeżego origin/main z innym podejściem"
        )
    return (
        f"limit rund: rund z FAIL {len(rounds.failed)} ({commits}) bez zmiany podejścia, a po {LIMIT}. rundzie z FAIL PR nie"
        f" dostaje kolejnej (skill przeglad, „Kolejne rundy”): zmień podejście w #{pull.number} (atak na przesłankę,"
        f" granica z mechanizmu albo usunięcie z PR części, której przegląd nie przyjął) i opisz je komentarzem PR"
        f" z pierwszą linią „{DECLARATION}<zdanie>”; po {END}. rundzie z FAIL PR nie dostaje żadnej"
    )


def deployed_problem(pull: Pull) -> str | None:
    """``problem`` z chwilą wdrożenia limitu na bazie ``pull`` pobranej z ``origin``."""

    return problem(pull, werdykt_pr.deployment(pull.base, MARKER))
