"""Warunek 5 merge'a ([ADR 0042](../../docs/adr/0042-straznik-przy-pierwszym-waznym.md)): każde Ważne werdyktu
``FAIL`` tego PR ma w swoim bloku sekcji ``## Korzeń`` linię ``Strażnik: <selektor>`` (``straznik.parse``), a dowód
strażnika przechodzi: ``tools/na_scalonych_pr.py --straznik <selektor> --z-commita <HEAD PR> --wazne <PR>/W<n>/r<k>``
z kodu bazy PR, tym samym Pythonem, jedno wywołanie na selektor ze wszystkimi jego Ważnymi. Przechodzi tylko kod 0
z ostatnią linią ``DOWÓD OK``; co liczy dowód, mówi ``straznik``, a w jakim środowisku, ``srodowisko_ci``.

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

from __future__ import annotations

import shlex
import subprocess
import sys
import time

import github
import potomne
import rejestr_korzeni
from repo import ROOT
from stan_pr import Pull, Waiting
import straznik
import szablon_werdyktu
import werdykt_pr

MARKER = "docs/adr/0042-straznik-przy-pierwszym-waznym.md"  # plik, którego dodanie do bazy PR to chwila wdrożenia warunku
TEST_MARKER = "tools/lib/mutacja_recenzenta.py"  # plik, którego dodanie do bazy PR to chwila wdrożenia dowodu testu
PROOF = ROOT / "tools" / "na_scalonych_pr.py"
PROOF_OK = "DOWÓD OK |"
PROOF_TIMEOUT_S = 900


def applies(pull: Pull) -> bool:
    """Czy warunek obowiązuje w wątku ``pull``: wdrożony na bazie PR, a najstarszy werdykt nie sprzed wdrożenia."""

    return werdykt_pr.rule_applies(pull, werdykt_pr.deployment(pull.base, MARKER))


def needed(pull: Pull) -> bool:
    """Czy warunek 5 ma czego dowodzić: PR ma werdykt ``FAIL``, a warunek obowiązuje w jego wątku (``applies``)."""

    return any(str(verdict.get("body") or "").lstrip().startswith("WERDYKT: FAIL") for verdict in pull.verdicts) and applies(pull)


def problems(pull: Pull) -> list[str]:
    """Przyczyny odmowy merge'a ``pull`` z warunku 5; HEAD i baza PR są już pobrane z ``origin``."""

    if not needed(pull):
        return []
    try:
        majors = rejestr_korzeni.majors(werdykt_pr.rounds(pull, werdykt_pr.rendered(pull)))[0]
        section = rejestr_korzeni.section(szablon_werdyktu.items(github.html_markdownu(pull.body, pull.repository))) if majors else None
    except Exception as error:  # noqa: BLE001 - każdy błąd renderera to oczekiwanie z przyczyną
        return [Waiting(f"strażnik: GitHub nie wyrenderował werdyktów albo opisu PR ({error}), uruchom ponownie")]
    blocks = {block.heading: block for block in section.blocks} if section else {}
    wanted: dict[straznik.Guard, list[str]] = {}
    for heading in majors:
        text = blocks[heading].guard() if heading in blocks else None
        try:
            guard = straznik.parse(text) if text is not None else None
        except ValueError:
            guard = None
        if guard is not None:
            label, round_ = heading.split(" r")
            wanted.setdefault(guard, []).append(f"{pull.number}/{label}/r{round_}")
    deadline = time.monotonic() + PROOF_TIMEOUT_S
    return [reason for guard, cases in wanted.items() for reason in _proved(pull, guard, cases, deadline - time.monotonic())]


def _proved(pull: Pull, guard: straznik.Guard, cases: list[str], left: float) -> list[str]:
    before = guard.kind is straznik.Kind.TESTS and not werdykt_pr.rule_applies(pull, werdykt_pr.deployment(pull.base, TEST_MARKER))
    arguments = ["--straznik", str(guard), "--z-commita", pull.head, *(part for case in cases for part in ("--wazne", case)), *(["--przed-dowodem-testu"] if before else [])]
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
