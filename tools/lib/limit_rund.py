from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from stan_pr import Pull
import szablon_werdyktu
import werdykt_pr

ZASADY = """Limit rund przeglądu (skill ``przeglad``, ``rundy.md``): PR, który ma ``LIMIT`` rund z ``FAIL``, nie dostaje
kolejnej rundy, dopóki autor nie zmieni podejścia w tym samym PR i nie zapisze tego komentarzem PR, którego pierwsza
niepusta linia to ``ZMIANA PODEJŚCIA: <zdanie>`` (``DECLARATION``). Próg spada do ``REPEAT`` rund, gdy Ważne
dwóch pierwszych rund z ``FAIL`` trafiają w ten sam plik pola ``Gdzie:`` albo mają ten sam kod pola ``Korzeń:``
(``szablon_werdyktu.Root``), bo kolejna runda w tym samym miejscu zwykle znów pada na tej samej przesłance. Po
``END`` (``2 * LIMIT``) rundach z ``FAIL`` PR nie dostaje już żadnej rundy, jakiekolwiek komentarze ma, więc zostaje
mu tylko nowy PR od ``main``: koniec liczą same rundy z ``FAIL``, bo komentarz zmiany podejścia autor może dopisać,
zmienić i usunąć (przed tą granicą #2010 dostał osiem rund z ``FAIL`` przez cztery komentarze, a Maks 17.11.2026:
„9 runda to przesada”).

Wyjście zostaje w tym samym PR, bo bramka korzenia i bramka strażnika czytają werdykty PR, więc Ważne każdej rundy,
także sprzed zmiany podejścia, zostają tam, gdzie merge ich wymaga; nowy PR zaczynałby bez nich.

Runda z ``FAIL`` to commit, dla którego PR ma werdykt ``FAIL`` (``werdykt_pr.read``: komentarz albo recenzja konta
z prawem zapisu z linią ``WERDYKT: FAIL <SHA>``), liczony raz, choćby miał kilka werdyktów, tak jak linia ``RUNDA``
trybu ``--przeglad``. Recenzja ``CHANGES_REQUESTED`` bez linii werdyktu rundą nie jest. Zmiana podejścia to komentarz
albo recenzja konta z prawem zapisu (nie ``PENDING``) z linią ``DECLARATION`` i niepustym zdaniem; liczy się tylko
wtedy, gdy powstała po ``LIMIT``-tej rundzie z ``FAIL``, więc komentarz napisany zawczasu, po każdej rundzie, rundy
nie daje. Zmiana podejścia po rundzie, po której PR ma ``REPEAT`` rund z ``FAIL`` w tym samym miejscu, liczy się
tak samo. Miejsce rundy to pliki i kody Ważnych każdego jej werdyktu ``FAIL`` z treści, którą GitHub wyrenderował:
z pola ``bodyHTML``, gdy je ma (skan rejestru korzeni), a inaczej przez ``POST /markdown``; błąd renderera to odmowa
z przyczyną.

Po ``LIMIT`` (albo ``REPEAT``) rundach z ``FAIL`` bez zmiany podejścia i po ``END`` rundach z ``FAIL`` odmawiają te
same przyczyną trzy kroki, przez które idzie każda runda: ``--przeglad`` (krok 1 recenzenta) przed diffem i skillami, ``--werdykt`` przed publikacją,
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

LIMIT = 3
REPEAT = 2
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
    """Rundy z ``FAIL`` PR: SHA commitów w kolejności pierwszego takiego werdyktu, każdy raz, werdykty ``FAIL`` każdego
    z nich i liczba rund z ``FAIL`` przed każdą zmianą podejścia."""

    failed: tuple[str, ...]
    verdicts: dict[str, list[werdykt_pr.Verdict]]
    changes: tuple[int, ...]


def failed_rounds(pull: Pull) -> Rounds:
    failed: list[str] = []
    verdicts: dict[str, list[werdykt_pr.Verdict]] = {}
    changes: list[int] = []
    for item in pull.verdicts:
        if _declares(item):
            changes.append(len(failed))
            continue
        found = werdykt_pr.read(item, pull.head)
        if found is not None and found.decision == "FAIL" and found.commit is not None:
            if found.commit not in verdicts:
                failed.append(found.commit)
            verdicts.setdefault(found.commit, []).append(found)
    return Rounds(tuple(failed), verdicts, tuple(changes))


def _place(pull: Pull, verdicts: Sequence[werdykt_pr.Verdict]) -> tuple[frozenset[str], frozenset[str]]:
    units = [werdykt_pr.from_graphql(verdict) if verdict.html is not None else werdykt_pr.rendered(pull)(verdict) for verdict in verdicts]
    majors = [root for found in units for root in szablon_werdyktu.findings(found).majors]
    return frozenset(file for root in majors for file in root.files), frozenset(root.code for root in majors if root.code)


def _repeated(pull: Pull, rounds: Rounds) -> str | None:
    first, second = (_place(pull, rounds.verdicts[commit]) for commit in rounds.failed[:REPEAT])
    return ", ".join([*sorted(first[0] & second[0]), *sorted(first[1] & second[1])]) or None


def problem(pull: Pull, deployed: datetime | None) -> str | None:
    """Przyczyna odmowy rundy ``pull``, gdy ma ``END`` rund z ``FAIL`` albo ``LIMIT`` (``REPEAT`` w tym samym miejscu)
    bez zmiany podejścia po nich, a limit obowiązuje w wątku (``deployed`` to ``werdykt_pr.deployment`` dla ``MARKER``);
    ``None``, gdy runda może się odbyć."""

    rounds = failed_rounds(pull)
    if len(rounds.failed) < REPEAT or not werdykt_pr.rule_applies(pull, deployed):
        return None
    commits = ", ".join(sha[:7] for sha in rounds.failed)
    if len(rounds.failed) >= END:
        return (
            f"limit rund: rund z FAIL {len(rounds.failed)} ({commits}), a po {END}. rundzie z FAIL #{pull.number} nie dostaje"
            f" żadnej kolejnej (skill przeglad, rundy.md), także po komentarzu „{DECLARATION}<zdanie>”: zamknij"
            f" #{pull.number} komentarzem z powodem i zacznij nowy PR od świeżego origin/main z innym podejściem"
        )
    try:
        repeated = _repeated(pull, rounds)
    except Exception as error:  # noqa: BLE001 - każdy błąd renderera to odmowa z przyczyną
        return f"limit rund: GitHub nie wyrenderował werdyktu FAIL ({error}), uruchom ponownie"
    threshold = REPEAT if repeated else LIMIT
    if len(rounds.failed) < threshold or any(change >= threshold for change in rounds.changes):
        return None
    change = (
        f"zmień podejście w #{pull.number} (atak na przesłankę, granica z mechanizmu albo usunięcie z PR części, której"
        f" przegląd nie przyjął) i opisz je komentarzem PR z pierwszą linią „{DECLARATION}<zdanie>”; po {END}. rundzie"
        f" z FAIL PR nie dostaje żadnej"
    )
    if repeated and len(rounds.failed) < LIMIT:
        return (
            f"limit rund: rund z FAIL {len(rounds.failed)} ({commits}) bez zmiany podejścia, a ich Ważne trafiają w to samo"
            f" miejsce ({repeated}), więc po {REPEAT}. rundzie z FAIL PR nie dostaje kolejnej (skill przeglad,"
            f" rundy.md): {change}"
        )
    return (
        f"limit rund: rund z FAIL {len(rounds.failed)} ({commits}) bez zmiany podejścia, a po {LIMIT}. rundzie z FAIL PR nie"
        f" dostaje kolejnej (skill przeglad, rundy.md): {change}"
    )


def deployed_problem(pull: Pull) -> str | None:
    """``problem`` z chwilą wdrożenia limitu na bazie ``pull`` pobranej z ``origin``."""

    return problem(pull, werdykt_pr.deployment(pull.base, MARKER))
