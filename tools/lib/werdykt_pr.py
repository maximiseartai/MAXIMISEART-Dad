"""Werdykty to komentarze i recenzje PR kont z prawem zapisu (``OWNER``, ``MEMBER``, ``COLLABORATOR``), w kolejności
utworzenia; nieopublikowana recenzja (``PENDING``) się nie liczy. Werdykt to komentarz albo recenzja, której pierwsza
niepusta linia, bez odstępów na brzegach, to dokładnie ``WERDYKT: PASS <SHA>`` albo ``WERDYKT: FAIL <SHA>``, gdzie
``<SHA>`` to pełny SHA HEAD PR małymi literami. ``FAIL`` jest sprzeciwem bez względu na dalsze linie, tak jak
recenzja w stanie ``CHANGES_REQUESTED``. ``PASS`` jest zgodą tylko wtedy, gdy przechodzi reguły ``--werdykt`` (niżej),
bez względu na to, jak go opublikowano; inaczej to odmowa ``werdykt: PASS dla <sha> nie
przechodzi reguł --werdykt (<przyczyny>)`` z poleceniem ``--werdykt``. Inny tekst, także ``FAIL`` w prozie albo
werdykt ze skróconym SHA, nie jest werdyktem. Zgodę pisze niezależny recenzent, nie autor zmiany: ``PASS`` mówi,
że przegląd nie znalazł problemów, a skille ``verify-*`` z linii ``SKILLE VERIFY`` ``tools/skille_dla_zmiany.py``
przeszły na tym SHA (ich polecenia z linii ``LICZY CI`` w CI, reszta workflow u agenta). Rozstrzyga najnowszy werdykt
dla HEAD: sprzeciw po ``PASS`` odbiera zgodę, nowszy ``PASS`` ją przywraca, a werdykt starszego commitu nie
przechodzi na nowy push. Komentarz edytowany liczy się z treścią po edycji, ale w miejscu utworzenia, a ukryty komentarz nadal się liczy.

``--werdykt <plik>`` publikuje plik jako komentarz PR (``gh pr comment --body-file``), gdy przechodzi te same reguły
co zgoda przy merge'u: pierwsza niepusta linia
to ``WERDYKT: PASS <SHA>`` albo ``WERDYKT: FAIL <SHA>`` z pełnym SHA bieżącego HEAD PR, druga to ``Znaleziska: N
(Ważne a, Drobne b)`` z ``N = a + b``, ``PASS`` ma zero Ważnych, ``FAIL`` co najmniej jedno, a Drobnych jest
najwyżej trzy, a w wątku z szablonem treść pod nimi idzie za szablonem ze skilla ``przeglad`` (``szablon_werdyktu``:
Ważne z polami ``Gdzie``, ``Dowód``, ``Korzeń`` i ``Szczebel``, Drobne z polem ``Gdzie``, na końcu ``## Sprawdzone``,
a kod korzenia z zamkniętej listy albo ``NOWY`` spoza niej). Czy wątek ma szablon, rozstrzyga jedna funkcja,
``template_applies``, i przy publikacji, i przy zgodzie na merge (ADR 0031, decyzja Q20): szablon obowiązuje, gdy
jest wdrożony na bazie PR (``szablon_werdyktu.deployed``), a najstarszy werdykt PR, dowolnego commitu, nie powstał
przed chwilą wdrożenia (``createdAt`` komentarza albo ``submittedAt`` recenzji z GitHuba, których komentarzem nie da
się zmienić). Wątek, którego pierwszy werdykt jest starszy, kończy po staremu: tylko dwie pierwsze linie. Werdykt bez
czasu, którego GitHub nie podał, wątku nie postarza, tak jak werdykt w komentarzu edytowanym (``includesCreatedEdit``),
który nadal jest werdyktem: komentarzem, także edytowanym, nie da się przesunąć chwili wdrożenia ani postarzyć wątku. Merge liczy więc ``PASS`` w wątku z szablonem jako zgodę tylko
wtedy, gdy przechodzi szablon, także gdy opublikowano go z pominięciem ``--werdykt``, a odmowa podaje przyczyny
i wzór. Inaczej niczego nie publikuje i kończy się linią ``WERDYKT ODMOWA | #N | <przyczyny>``, w której
każda przyczyna mówi, co poprawić w pliku. Opublikowany werdykt kończy się linią ``WERDYKT OK | #N <sha> | <PASS
albo FAIL> | <adres komentarza>``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import re
from typing import Literal

import github
from stan_pr import Pull
import szablon_werdyktu

VERDICT_LINE = re.compile(r"WERDYKT: (PASS|FAIL) ([0-9a-f]{40})")
FINDINGS_LINE = re.compile(r"Znaleziska: (\d+) \(Ważne (\d+), Drobne (\d+)\)")
MAX_MINOR = 3
TRUSTED = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})


class Stance(Enum):
    CONSENT = "PASS"
    OBJECTION = "FAIL"
    BROKEN_CONSENT = "PASS poza regułami --werdykt"


@dataclass(frozen=True)
class Verdict:
    when: str
    login: str
    first_lines: tuple[str, ...]
    decision: Literal["PASS", "FAIL"] | None
    commit: str | None
    stance: Stance | None
    problems: tuple[str, ...]
    body: str


def read(verdict: dict[str, object], head: str) -> Verdict | None:
    if verdict["authorAssociation"] not in TRUSTED or verdict.get("state") == "PENDING":
        return None
    lines = text_lines(verdict["body"])
    found = VERDICT_LINE.fullmatch(lines[0]) if lines else None
    changes_requested = verdict.get("state") == "CHANGES_REQUESTED"
    if found is None and not changes_requested:
        return None
    decision: Literal["PASS", "FAIL"] | None = None if found is None else "PASS" if found[1] == "PASS" else "FAIL"
    commit = found[2] if found else None
    problems = tuple(file_problems(str(verdict["body"]), head)) if decision == "PASS" and commit == head else ()
    if changes_requested or (decision == "FAIL" and commit == head):
        stance: Stance | None = Stance.OBJECTION
    else:
        stance = None if commit != head else Stance.BROKEN_CONSENT if problems else Stance.CONSENT
    author = verdict.get("author")
    login = str(author.get("login", "?")) if isinstance(author, dict) else "?"
    when = str(verdict.get("createdAt") or verdict.get("submittedAt") or "?")
    return Verdict(when, login, tuple(lines[:2]), decision, commit, stance, problems, str(verdict["body"]))


def text_lines(body: object) -> list[str]:
    """Niepuste linie tekstu bez odstępów na brzegach: pierwsza to linia werdyktu, druga linia znalezisk."""

    return [line.strip() for line in str(body).splitlines() if line.strip()]


def consent_problem(pull: Pull, deployed: datetime | None) -> str | None:
    """Przyczyna odmowy merge'a PR, gdy najnowszy werdykt dla jego HEAD nie jest zgodą; ``deployed`` to chwila
    wdrożenia szablonu na bazie PR (``szablon_werdyktu.deployed``)."""

    head = pull.head
    publish = f"tools/scal_pr.py {pull.number} --werdykt PLIK"
    latest = None
    for verdict in pull.verdicts:
        found = read(verdict, head)
        latest = found if found is not None and found.stance is not None else latest
    if latest is None:
        return f"werdykt: brak komentarza ani recenzji „WERDYKT: PASS {head}”; opublikuj werdykt przez {publish}"
    problems = list(latest.problems)
    if latest.stance is Stance.CONSENT and template_applies(pull, deployed):
        problems = _template_problems(latest.body, pull)
    if problems:
        return f"werdykt: PASS dla {head[:7]} nie przechodzi reguł --werdykt ({'; '.join(problems)}); popraw plik werdyktu i opublikuj go przez {publish}"
    return None if latest.stance is Stance.CONSENT else f"werdykt: FAIL dla {head[:7]} bez nowszego „WERDYKT: PASS {head}”"


def history(verdicts: Sequence[dict[str, object]], head: str) -> list[str]:
    """Linie werdyktów PR w kolejności utworzenia i linia ``RUNDA`` o ostatnim z nich."""

    shown, last, failed = [], None, set()
    for verdict in filter(None, (read(verdict, head) for verdict in verdicts)):
        if verdict.decision is None or verdict.commit is None:
            shown.append(f"WERDYKT | {verdict.when} {verdict.login} | recenzja CHANGES_REQUESTED | {' | '.join(verdict.first_lines)}")
            continue
        last = (verdict.decision, verdict.commit)
        if verdict.decision == "FAIL":
            failed.add(verdict.commit)
        which = "inny commit" if verdict.commit != head else f"HEAD, {verdict.stance.value}" if verdict.stance is Stance.BROKEN_CONSENT else "HEAD"
        shown.append(f"WERDYKT | {verdict.when} {verdict.login} | {which} | {' | '.join(verdict.first_lines)}")
    if last is None:
        return [*shown, "RUNDA | 1: PR nie ma werdyktu"]
    rounds = f"rund z FAIL: {len(failed)}, ostatni werdykt {last[0]} dla {last[1][:7]}"
    if last[1] == head:
        return [*shown, f"RUNDA | {rounds}, czyli dla tego HEAD"]
    return [*shown, f"RUNDA | {rounds}; zmiana od niego: git diff {last[1]} {head}"]


def file_problems(text: str, head: str) -> list[str]:
    """Co poprawić w pliku werdyktu dla ``head``; pusta lista, gdy obie pierwsze linie są zgodne z ``--help``."""

    lines = text_lines(text)
    first, second = [*lines, "", ""][:2]
    verdict = VERDICT_LINE.fullmatch(first)
    findings = FINDINGS_LINE.fullmatch(second)
    problems = []
    if verdict is None:
        problems.append(f"pierwsza linia „{first}” to nie „WERDYKT: PASS {head}” ani „WERDYKT: FAIL {head}”")
    elif verdict[2] != head:
        problems.append(f"werdykt dla {verdict[2][:7]}, a HEAD PR to {head}: przejrzyj git diff {verdict[2]} {head} i wpisz SHA HEAD")
    if findings is None:
        return [*problems, f"druga linia „{second}” to nie „Znaleziska: N (Ważne a, Drobne b)”"]
    total, major, minor = map(int, findings.groups())
    if total != major + minor:
        problems.append(f"Znaleziska: {total}, a Ważne {major} i Drobne {minor} dają {major + minor}")
    if minor > MAX_MINOR:
        problems.append(f"Drobne {minor}: podaj najwyżej {MAX_MINOR}, najważniejsze")
    if verdict is not None and (verdict[1] == "FAIL") != (major > 0):
        problems.append(f"{verdict[1]} z Ważne {major}: FAIL daje tylko Ważne znalezisko, a PASS jest bez Ważnych")
    return problems


def publish_problems(text: str, pull: Pull, deployed: datetime | None) -> list[str]:
    """Co poprawić w pliku werdyktu przed publikacją na ``pull``: dwie pierwsze linie, a w wątku z szablonem
    (``template_applies``) także treść według ``szablon_werdyktu``."""

    problems = file_problems(text, pull.head)
    return [*problems, *_template_problems(text, pull)] if template_applies(pull, deployed) else problems


def template_applies(pull: Pull, deployed: datetime | None) -> bool:
    """Czy werdykt na ``pull`` idzie za szablonem: szablon jest wdrożony (``deployed`` to nie ``None``), a najstarszy
    werdykt PR (z linią ``WERDYKT:``, od konta z prawem zapisu) nie powstał przed chwilą ``deployed`` (decyzja Q20).
    Werdykt w komentarzu edytowanym (``includesCreatedEdit``) wątku nie postarza, bo jego treść mogła powstać później."""

    if deployed is None:
        return False
    found = (read(verdict, pull.head) for verdict in pull.verdicts if not verdict.get("includesCreatedEdit"))
    moments = [_moment(verdict.when) for verdict in found if verdict is not None and verdict.decision is not None]
    known = [moment for moment in moments if moment is not None]
    return not known or min(known) >= deployed


def _moment(when: str) -> datetime | None:
    try:
        return datetime.fromisoformat(when)
    except ValueError:
        return None


def _content(text: str) -> tuple[str, tuple[int, int] | None]:
    """Treść pod dwiema pierwszymi niepustymi liniami ``text`` i liczby Ważnych i Drobnych z linii ``Znaleziska:``
    (``None``, gdy jej nie ma)."""

    lines = str(text).splitlines()
    filled = [index for index, line in enumerate(lines) if line.strip()]
    rest = "\n".join(lines[filled[1] + 1 :]) if len(filled) > 1 else ""
    findings = FINDINGS_LINE.fullmatch(lines[filled[1]].strip()) if len(filled) > 1 else None
    return rest, (int(findings[2]), int(findings[3])) if findings else None


def _html(rest: str, pull: Pull) -> str:
    return github.html_markdownu(rest, pull.repository) if rest.strip() else ""


def _template_problems(text: str, pull: Pull) -> list[str]:
    """Przyczyny ``szablon_werdyktu`` dla treści pod dwiema pierwszymi niepustymi liniami ``text``, którą renderuje GitHub."""

    rest, declared = _content(text)
    try:
        html = _html(rest, pull)
    except Exception as error:  # noqa: BLE001 - każdy błąd renderera (gh z błędem albo po czasie, pusty HTML) to odmowa z przyczyną
        return [f"GitHub nie wyrenderował treści werdyktu ({error}), uruchom ponownie"]
    return szablon_werdyktu.problems(html, declared, lambda: szablon_werdyktu.pull_codes(pull))


@dataclass(frozen=True)
class Round:
    """Runda przeglądu: ``number``-ty werdykt PR (od 1, w kolejności utworzenia, dowolnego commitu), liczba Ważnych
    z jego linii ``Znaleziska:`` (``None``, gdy jej nie ma) i kody korzeni jego treści z ``szablon_werdyktu.findings``."""

    number: int
    verdict: Verdict
    declared_majors: int | None
    findings: szablon_werdyktu.Findings


def rounds(pull: Pull) -> list[Round]:
    """Rundy przeglądu ``pull``: werdykty z linią ``WERDYKT:`` od kont z prawem zapisu, jak przy zgodzie na merge.

    Treść każdego czyta renderer GitHuba; błąd renderera to wyjątek."""

    found = [verdict for verdict in (read(verdict, pull.head) for verdict in pull.verdicts) if verdict is not None and verdict.decision is not None]
    result = []
    for number, verdict in enumerate(found, start=1):
        rest, declared = _content(verdict.body)
        result.append(Round(number, verdict, declared[0] if declared else None, szablon_werdyktu.findings(_html(rest, pull))))
    return result
