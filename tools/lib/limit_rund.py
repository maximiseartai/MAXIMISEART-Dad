"""Limit rund przeglądu (skill ``przeglad``, „Kolejne rundy”): PR, który ma ``LIMIT`` rund z ``FAIL`` od ostatniej
zmiany podejścia, nie dostaje kolejnej rundy, dopóki jego HEAD ma kod, który wskazało pole ``Gdzie`` Ważnych tych rund.

Zmianę podejścia narzędzie widzi w kodzie, nie w zdaniu: to commit, na którym żadna niepusta linia z miejsc ``Gdzie``
Ważnych tych rund (``plik:linia`` w commicie rundy) nie stoi już na swoim miejscu. Linia stoi, gdy diff gita od commitu
rundy do sprawdzanego commitu (``git diff -U0 -w``, odstępy pomija) nie usuwa jej ani nie zmienia, więc linię poznaje
po miejscu, które daje git, a nie po tekście, który plik może mieć drugi raz (``)``, ``continue``). Komentarz PR licznika
nie zeruje, bo przed tą zmianą #2010 dostał przez cztery komentarze ``ZMIANA PODEJŚCIA:`` osiem rund z ``FAIL`` (audyt
17.11.2026). Runda z ``FAIL`` na takim commicie zaczyna nowe liczenie od siebie.

| Przypadek | Wynik |
|---|---|
| diff usuwa linię ``Gdzie`` albo zmienia jej tekst | linia nie stoi |
| linia ma w pliku kopię (``)``, ``]``), a diff usuwa właśnie ją | nie stoi |
| nowy kod ma tę samą linię w tej samej kolejności, więc diff dopasuje do niej linię rundy | stoi (granica: tożsamość linii daje diff gita, jak w ``git blame``) |
| linię przepisano bez zmiany przesłanki (inna nazwa, inny zapis) | nie stoi (granica: przesłankę ocenia recenzent) |
| diff zmienia w linii tylko odstępy | stoi |
| plik ``Gdzie`` usunięto albo przemianowano | nie stoi (granica: przeniesienie kodu do innego pliku) |
| Ważne bez miejsca ``plik:linia`` w ``Gdzie``, z miejscem spoza pliku commitu rundy albo na pustej linii | nie wnosi linii |
| żadne Ważne tych rund nie wnosi linii | zmiany nie widać, kolejną rundę da tylko nowy PR |
| commit rundy, którego checkout nie zna | narzędzie pobiera go z ``origin``; gdy się nie da, jego Ważne nie wnoszą linii |

Wyjście zostaje w tym samym PR, bo bramka korzenia i bramka idiomu czytają werdykty PR, więc Ważne każdej rundy,
także sprzed zmiany podejścia, zostają tam, gdzie merge ich wymaga; nowy PR zaczynałby bez nich.

Runda z ``FAIL`` to commit, dla którego PR ma werdykt ``FAIL`` (``werdykt_pr.read``: komentarz albo recenzja konta
z prawem zapisu z linią ``WERDYKT: FAIL <SHA>``), liczony raz, choćby miał kilka werdyktów, tak jak linia ``RUNDA``
trybu ``--przeglad``. Recenzja ``CHANGES_REQUESTED`` bez linii werdyktu rundą nie jest. Ważne i ich ``Gdzie`` to
jednostki treści werdyktu z renderera GitHuba (``werdykt_pr.rendered``), jak w bramce korzenia: nagłówek ``W<n>.``
i linia akapitu ``Gdzie:`` zaraz po nim.

Po ``LIMIT`` rundach z ``FAIL`` bez zmiany podejścia odmawiają te same przyczyną trzy kroki, przez które idzie każda
runda: ``--przeglad`` (krok 1 recenzenta) przed diffem i skillami, ``--werdykt`` przed publikacją, i ``PASS``, i
``FAIL``, oraz zgoda na merge (warunek 3, a przez niego status ``Werdykt i bramka``, którego wymaga ruleset ``main``),
więc ``PASS`` opublikowany z pominięciem ``--werdykt`` też nie scala PR.

Limit obowiązuje w wątku, którego najstarszy werdykt nie powstał przed wdrożeniem tego modułu (decyzja Q20 ADR 0031:
wątki, które już pracują, kończą po swojemu), co rozstrzyga ``werdykt_pr.rule_applies`` z chwilą
``werdykt_pr.deployment`` dla pliku ``MARKER``.

Granica: narzędzie nie sprawdza, czy nowy kod to naprawdę inne podejście (to ocenia recenzent następnej rundy), a
usunięty komentarz ``FAIL`` rundą już nie jest. PR zamknięty i zastąpiony nowym PR zabiera Ważne ze sobą, bo bramki
czytają tylko werdykty własnego PR; limit do tego nie kieruje, poza PR, którego Ważne nie wnoszą linii.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
import functools
import itertools
import re

import github
import repo
from repo import REMOTE, ROOT
from stan_pr import Pull
import szablon_werdyktu
import werdykt_pr
from werdykt_pr import Verdict

LIMIT = 3
MARKER = "tools/lib/limit_rund.py"
WHERE = "Gdzie:"
# Nagłówek hunka ``git diff -U0``: pierwsza linia i liczba linii starej strony (bez liczby: jedna).
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+", re.MULTILINE)
# Runda z ``FAIL``: commit i pierwszy werdykt ``FAIL`` dla niego w PR.
Round = tuple[str, Verdict]


@dataclass(frozen=True)
class Sources:
    """Skąd limit czyta Ważne i kod: ``content`` daje jednostki treści werdyktu (``werdykt_pr.Content``), ``blob``
    bajty pliku ścieżki w commicie albo ``None``, gdy commit nie ma tego pliku albo go nie ma checkout, a ``removed``
    numery linii pliku ścieżki w pierwszym commicie, które diff do drugiego usuwa albo zmienia."""

    content: werdykt_pr.Content
    blob: Callable[[str, str], bytes | None]
    removed: Callable[[str, str, str], frozenset[int]]

    def lines(self, commit: str, path: str) -> list[str]:
        found = self.blob(commit, path)
        return [] if found is None else found.decode("utf-8", "replace").splitlines()


@dataclass(frozen=True)
class _Rejected:
    """Niepusta linia ``number`` pliku ``path`` z miejsca ``Gdzie`` Ważnego w commicie ``commit`` jego rundy."""

    commit: str
    path: str
    number: int

    def shown(self) -> str:
        return f"{self.path}:{self.number} ({self.commit[:7]})"


def _rejected(rounds: Sequence[Round], sources: Sources) -> list[_Rejected]:
    """Kod z miejsc ``Gdzie`` Ważnych rund ``rounds``, każdy w commicie swojej rundy."""

    found: list[_Rejected] = []
    for commit, verdict in rounds:
        units = sources.content(verdict)
        for heading, where in itertools.pairwise(units):
            major = heading.kind == "h3" and (title := szablon_werdyktu.HEADING.fullmatch(heading.text)) is not None and title[1] == "W"
            if not major or where.kind != "line" or not where.text.startswith(WHERE):
                continue
            for path, first, last in szablon_werdyktu.places(where.text):
                text = sources.lines(commit, path)
                found.extend(
                    _Rejected(commit, path, number) for number in range(first, last + 1) if 0 < number <= len(text) and text[number - 1].strip()
                )
    return found


def _standing(code: Sequence[_Rejected], commit: str, sources: Sources) -> list[_Rejected]:
    """Linie ``code``, których diff od commitu ich rundy do ``commit`` nie usuwa ani nie zmienia."""

    removed = {(line.commit, line.path): sources.removed(line.commit, commit, line.path) for line in code}
    return [line for line in code if line.number not in removed[line.commit, line.path]]


def _changed(rounds: Sequence[Round], commit: str, sources: Sources) -> bool:
    code = _rejected(rounds, sources)
    return bool(code) and not _standing(code, commit, sources)


def failed_rounds(pull: Pull, sources: Sources) -> list[Round]:
    """Rundy z ``FAIL`` od ostatniej zmiany podejścia, po kolei, każdy commit raz z pierwszym werdyktem ``FAIL`` w PR;
    runda na commicie bez kodu ``Gdzie`` ``LIMIT`` rund przed nią zaczyna liczenie od siebie."""

    seen: set[str] = set()
    since: list[Round] = []
    for item in pull.verdicts:
        found = werdykt_pr.read(item, pull.head)
        if found is None or found.decision != "FAIL" or found.commit is None or found.commit in seen:
            continue
        seen.add(found.commit)
        if len(since) >= LIMIT and _changed(since, found.commit, sources):
            since = []
        since.append((found.commit, found))
    return since


def problem(pull: Pull, deployed: datetime | None, sources: Sources) -> str | None:
    """Przyczyna odmowy rundy ``pull``, gdy ma ``LIMIT`` rund z ``FAIL`` od ostatniej zmiany podejścia, a jego HEAD
    nie jest zmianą podejścia; ``None``, gdy runda może się odbyć albo limit nie obowiązuje w wątku (``deployed`` to
    ``werdykt_pr.deployment`` dla ``MARKER``)."""

    if not werdykt_pr.rule_applies(pull, deployed):
        return None
    failed = failed_rounds(pull, sources)
    if len(failed) < LIMIT:
        return None
    code = _rejected(failed, sources)
    left = _standing(code, pull.head, sources)
    if code and not left:
        return None
    commits = ", ".join(commit[:7] for commit, _ in failed)
    where = (
        f"HEAD ma nadal kod z pola Gdzie ich Ważnych: {', '.join(line.shown() for line in left)}"
        if code
        else "pole Gdzie ich Ważnych nie wskazuje żadnej linii kodu, więc zmianę podejścia pokaże tylko nowy PR od main"
    )
    return (
        f"limit rund: rund z FAIL {len(failed)} ({commits}), a {where}; po {LIMIT}. rundzie z FAIL PR nie dostaje"
        f" kolejnej (skill przeglad, „Kolejne rundy”): zmień podejście w #{pull.number} tak, by HEAD nie miał już tych"
        " linii (atak na przesłankę, granica z mechanizmu albo usunięcie z PR części, której przegląd nie przyjął);"
        " komentarz PR licznika nie zeruje"
    )


def _blob(commit: str, path: str) -> bytes | None:
    if repo.commit(ROOT, commit) is None:
        repo.run_git(ROOT, "fetch", "--quiet", "--no-tags", REMOTE, commit, timeout=github.LIMIT_S)
    return repo.blob(ROOT, commit, path)


def _removed(commit: str, later: str, path: str) -> frozenset[int]:
    diff = repo.git(ROOT, "diff", "--no-color", "--no-ext-diff", "-U0", "-w", commit, later, "--", path)
    return frozenset(number for found in HUNK.finditer(diff) for number in range(int(found[1]), int(found[1]) + int(found[2] or 1)))


def deployed_problem(pull: Pull) -> str | None:
    """``problem`` z chwilą wdrożenia limitu na bazie ``pull`` pobranej z ``origin``, z treścią werdyktów z renderera
    GitHuba i kodem z Gita checkoutu."""

    return problem(pull, werdykt_pr.deployment(pull.base, MARKER), Sources(functools.cache(werdykt_pr.rendered(pull)), _blob, _removed))
