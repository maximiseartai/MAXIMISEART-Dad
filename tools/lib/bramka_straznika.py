from __future__ import annotations

from dataclasses import dataclass
import shlex
import subprocess
import sys
import time
from typing import final

import github
import potomne
import rejestr_korzeni
from repo import REMOTE, ROOT
import repo
from stan_pr import Pull, Waiting
import straznik
import strazniki_przeniesione
import szablon_werdyktu
import szczebel_straznika
import werdykt_pr

ZASADY = """Warunek 5 merge'a ([ADR 0042](../../docs/adr/0042-straznik-przy-pierwszym-waznym.md)): każde Ważne werdyktu
``FAIL`` tego PR ma w swoim bloku sekcji ``## Korzeń`` linię ``Strażnik: <selektor>`` (``straznik.parse``), a dowód
strażnika przechodzi: ``tools/na_scalonych_pr.py --straznik <selektor> --z-commita <HEAD PR> --wazne <PR>/W<n>/r<k>``
z kodu bazy PR, tym samym Pythonem, jedno wywołanie na selektor ze wszystkimi jego Ważnymi. Przechodzi tylko kod 0
z ostatnią linią ``DOWÓD OK``; co liczy dowód, mówi ``straznik``, a w jakim środowisku, ``srodowisko_ci``.

Wpis ``strazniki_przeniesione.PLIK``, który PR dodaje albo zmienia (strażnik przeniesiony Ważnego scalonego PR,
``strazniki_przeniesione.ZASADY``), dostaje ten sam dowód ze swoim selektorem i Ważnym, także w PR bez werdyktu
``FAIL``, i tę samą regułę szczebla (``_rung``) z polem ``Mechanizm:`` tego Ważnego z werdyktów jego PR, w wątku tego
PR; wpis, którego narzędzie nie wczyta, wpis Ważnego tego PR, PR niescalonego albo Ważnego, którego PR nie ma, to odmowa.

Selektor wybiera autor tylko spośród tych, które przyjmuje szczebel z pola ``Mechanizm:`` Ważnego
(``szczebel_straznika``, ADR 0046); selektor, którego szczebel nie przyjmuje, to odmowa bez dowodu, a ``pytest
<węzeł>`` przy szczeblu ``test`` dostaje dowód z ``--chroniony-wlasciciel``.

Warunek obowiązuje od własnego wdrożenia (``MARKER``: ADR 0042, jak szablon werdyktu od ADR 0031;
``werdykt_pr.rule_applies``, decyzja Q20 ADR 0031), więc wątek z werdyktem sprzed niego kończy po staremu, z polem
``Dowód:`` w bloku Ważnego. Tak samo dowód testu (``TEST_MARKER``): w wątku z werdyktem sprzed niego ``brak - test``
przechodzi jak przed nim (``--przed-dowodem-testu``), a w nowszym to odmowa, bo strażnik-test ma dowód z mutacją
recenzenta (``pytest <węzeł>``). Brak linii
i selektor spoza listy zgłasza bramka korzenia (warunek 4), więc tu taki blok nie dostaje dowodu.

Błąd renderera GitHuba to ``stan_pr.Waiting``, bo mija przy następnym runie. Dowody PR mają razem
``PROOF_TIMEOUT_S``: job ``dowod`` statusu „Werdykt i bramka” ma 20 min (``.github/workflows/werdykt-i-bramka.yml``),
więc przekroczony czas jest przyczyną w statusie, zanim Actions zabije job. Moduł bierze tylko bibliotekę
standardową, bo job ``status`` uruchamia ``tools/scal_pr.py`` Pythonem runnera bez zależności; dowód potrzebuje
dodatku dev bazy i uv, buduje środowisko Required CI z drzewa PR i wykonuje kod PR (backend budowy i pakiety
z ``pyproject.toml`` PR, wtyczki mypy z jego konfiguracji), więc biegnie tylko w jobie ``dowod`` bez prawa zapisu
i przy merge'u.
"""

MARKER = "docs/adr/0042-straznik-przy-pierwszym-waznym.md"  # plik, którego dodanie do bazy PR to chwila wdrożenia warunku
TEST_MARKER = "tools/lib/mutacja_recenzenta.py"  # plik, którego dodanie do bazy PR to chwila wdrożenia dowodu testu
PROOF = ROOT / "tools" / "na_scalonych_pr.py"
PROOF_OK = "DOWÓD OK |"
PROOF_TIMEOUT_S = 900


def applies(pull: Pull) -> bool:
    """Czy warunek obowiązuje w wątku ``pull``: wdrożony na bazie PR, a najstarszy werdykt nie sprzed wdrożenia."""

    return werdykt_pr.rule_applies(pull, werdykt_pr.deployment(pull.base, MARKER))


def needed(pull: Pull) -> bool:
    """Czy warunek 5 ma czego dowodzić: PR ma werdykt ``FAIL``, a warunek obowiązuje w jego wątku (``applies``), albo
    PR dodaje lub zmienia wpis strażnika przeniesionego (``moved``)."""

    try:
        entries = moved(pull)
    except ValueError:
        return True
    return _own(pull) or bool(entries)


def moved(pull: Pull) -> list[strazniki_przeniesione.Moved]:
    if not (after := strazniki_przeniesione.at(ROOT, pull.head)):
        return []
    try:
        fork = repo.merge_base(ROOT, f"{REMOTE}/{pull.base}", pull.head)
    except subprocess.CalledProcessError as error:
        raise ValueError(f"{strazniki_przeniesione.PLIK}: bez merge-base HEAD {pull.head[:7]} z {REMOTE}/{pull.base} nie wiem, które wpisy PR zmienia ({error.stderr or error})") from None
    before = strazniki_przeniesione.at(ROOT, fork)
    return [entry for key, entry in after.items() if before.get(key) != entry]


def _own(pull: Pull) -> bool:
    return any(str(verdict.get("body") or "").lstrip().startswith("WERDYKT: FAIL") for verdict in pull.verdicts) and applies(pull)


def problems(pull: Pull) -> list[str]:
    """Przyczyny odmowy merge'a ``pull`` z warunku 5; HEAD i baza PR są już pobrane z ``origin``."""

    try:
        entries = moved(pull)
    except ValueError as error:
        return [f"strażnik: {error}"]
    own = _own(pull)
    if not own and not entries:
        return []
    try:
        majors = rejestr_korzeni.majors(werdykt_pr.rounds(pull, werdykt_pr.rendered(pull)))[0] if own else {}
        section = rejestr_korzeni.section(szablon_werdyktu.items(github.html_markdownu(pull.body, pull.repository))) if majors else None
        cited = [(entry, _cited(pull, entry)) for entry in entries]
    except Exception as error:  # noqa: BLE001 - każdy błąd renderera to oczekiwanie z przyczyną
        return [Waiting(f"strażnik: GitHub nie wyrenderował werdyktów albo opisu PR ({error}), uruchom ponownie")]
    blocks = {block.heading: block for block in section.blocks} if section else {}
    refused: list[str] = []
    wanted: dict[tuple[straznik.Guard, bool], list[_Ruled]] = {}
    for heading, major in majors.items():
        guard = blocks[heading].selector() if heading in blocks else None
        if guard is None:
            continue
        label, round_ = heading.split(" r")
        ruled = _Ruled(pull, major, guard, f"{pull.number}/{label}/r{round_}")
        if reason := ruled.refusal:
            refused.append(
                f"strażnik: Ważne {ruled.case}: {reason}; wpisz w jego bloku sekcji ## Korzeń przyjęty selektor i sprawdź go poleceniem tools/na_scalonych_pr.py --straznik '<selektor>' --z-commita {pull.head} --wazne {ruled.case}, "
                f"a gdy ten szczebel nie działa (ADR 0046), recenzent następnej rundy zmienia go punktem „{szablon_werdyktu.MECHANISM_START}{label} r{round_}: <szczebel> - zdanie” w ## {szablon_werdyktu.CHECKED}"
            )
        else:
            wanted.setdefault((guard, ruled.owner), []).append(ruled)
    for entry, found in cited:
        case = f"{entry.pull}/{entry.major.replace(' ', '/')}"
        if isinstance(found, str):
            refused.append(f"strażnik: wpis {case} w {strazniki_przeniesione.PLIK}: {found}")
            continue
        ruled = _Ruled(*found, entry.guard, case)
        if reason := ruled.refusal:
            refused.append(f"strażnik: wpis {case} w {strazniki_przeniesione.PLIK}: {reason}; wpisz w nim przyjęty selektor i sprawdź go poleceniem tools/na_scalonych_pr.py --straznik '<selektor>' --z-commita {pull.head} --wazne {case}")
        else:
            wanted.setdefault((entry.guard, ruled.owner), []).append(ruled)
    deadline = time.monotonic() + PROOF_TIMEOUT_S
    return [*refused, *(reason for rulings in wanted.values() for reason in _proved(pull, rulings, deadline - time.monotonic()))]


@final
@dataclass(frozen=True)
class _Ruled:
    thread: Pull
    major: rejestr_korzeni.Major
    guard: straznik.Guard
    case: str

    @property
    def refusal(self) -> str | None:
        return szczebel_straznika.refusal(self.major.mechanism, self.guard) if szczebel_straznika.applies(self.thread) else None

    @property
    def owner(self) -> bool:
        return szczebel_straznika.owner_applies(self.thread) and szczebel_straznika.needs_owner(self.major.mechanism, self.guard)


def _cited(pull: Pull, entry: strazniki_przeniesione.Moved) -> tuple[Pull, rejestr_korzeni.Major] | str:
    if entry.pull == pull.number:
        return "wpis przenosi strażnika Ważnego scalonego PR, a Ważne tego PR ma strażnika tylko w swoim bloku sekcji ## Korzeń: usuń wpis"
    cited = rejestr_korzeni.pull(pull.repository, entry.pull)
    if cited.state != "MERGED":
        return f"PR #{entry.pull} nie jest scalony ({cited.state}), a wpis przenosi strażnika Ważnego scalonego PR: usuń wpis"
    known = rejestr_korzeni.majors(werdykt_pr.rounds(cited, werdykt_pr.from_graphql))[0]
    if entry.major not in known:
        return f"PR #{entry.pull} nie ma Ważnego {entry.major} w werdyktach FAIL: popraw klucz wpisu"
    return cited, known[entry.major]


def _proved(pull: Pull, rulings: list[_Ruled], left: float) -> list[str]:
    guard, owner, cases = rulings[0].guard, rulings[0].owner, [ruled.case for ruled in rulings]
    before = guard.kind is straznik.Kind.TESTS and not werdykt_pr.rule_applies(pull, werdykt_pr.deployment(pull.base, TEST_MARKER))
    flags = [*(["--przed-dowodem-testu"] if before else []), *(["--chroniony-wlasciciel"] if owner else [])]
    arguments = ["--straznik", str(guard), "--z-commita", pull.head, *(part for case in cases for part in ("--wazne", case)), *flags]
    late = f"strażnik: {guard}: dowody strażników tego PR nie skończyły się w {PROOF_TIMEOUT_S} s, uruchom ponownie"
    if left <= 0:
        return [late]
    try:
        done = potomne.run([sys.executable, str(PROOF), *arguments], cwd=ROOT, timeout=left, echo=True)
    except subprocess.TimeoutExpired:
        return [late]
    lines = (done.stdout + done.stderr).strip().splitlines()
    last = lines[-1] if lines else ""
    if done.returncode == 0 and last.startswith(PROOF_OK):
        return []
    return [
        f"strażnik: Ważne {', '.join(cases)} ma Strażnik: {guard}, a jego dowód nie przeszedł (kod {done.returncode}): {last or 'bez wyniku'}; "
        f"popraw strażnika albo wybierz inny z listy i sprawdź go poleceniem tools/na_scalonych_pr.py {shlex.join(arguments)}"
    ]
