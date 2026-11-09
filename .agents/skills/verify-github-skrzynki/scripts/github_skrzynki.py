"""Klienty GitHuba Centrum (Skrzynka Zgłoszeń, Aktualność narzędzia) na prawdziwym GitHubie i na jego nagraniach.

Tryby (opis w ``SKILL.md`` skilla ``verify-github-skrzynki``):

- ``doctor``: tylko odczyt; klucz klienta i jego rodzaj, klucz ``gh`` do sprzątania, repozytoria próbne (prywatne, bez
  pozostałości runów, Archiwum z commitem), limity zapytań.
- ``na-zywo``: przypadki ``--feature`` (``skrzynka``, ``archiwum``, ``aktualnosc``) przez prawdziwy kod klienta na
  repozytoriach próbnych i publicznym repozytorium narzędzia, z nagraniem każdej wymiany, potem ``wiernosc-atrap`` na nowych
  nagraniach i sprzątanie; z ``--zapisz-nagrania`` nagrania zastępują ``nagrania/`` skilla.
- ``odtworz``: bez sieci; ten sam klient na nagraniach ``nagrania/`` i wierność atrap testów (podstawa ``ci:``).

Ostatnia linia: ``VERIFY OK | …`` (kod 0) tylko wtedy, gdy każdy przypadek z tabel dał oczekiwany wynik, a każdy wiersz
wierności się zgadza; brakujący przypadek, wyjątek albo rozjazd to ``VERIFY FAIL | …`` (kod 1). ``NIESPRAWDZONE``
wymienia, czego przebieg nie sprawdza; kod 2: Doctor odmówił albo złe wywołanie.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import subprocess
import sys
import traceback
from typing import Any, Final, Generic, TypeVar
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))

from rozliczenia.centrum import report_box
from rozliczenia.centrum.github import API
from rozliczenia.centrum.report_box import GitHubReportBox
from rozliczenia.tool_files import REPOSITORY as TOOL_REPOSITORY

from skrypt_skilla import Parser, create_run_root, new_run

import github_przypadki_aktualnosci as aktualnosc
import github_przypadki_archiwum as archiwum
import github_przypadki_skrzynki as skrzynka
import github_sprzatanie
import github_wiernosc
from github_wymiana import (
    RUN_MARKER,
    TRIAL,
    TRIAL_ARCHIVE,
    TRIALS,
    Admin,
    Case,
    Exchange,
    Facts,
    GitHubProxy,
    LiveTransport,
    Pace,
    Recorder,
    ReplayTransport,
    gh_token,
    read_recording,
    token_kind,
    token_slug,
    write_recording,
)

ROOT = Path(__file__).resolve().parents[4]
SKILL: Final = Path(__file__).resolve().parents[1]
RECORDINGS: Final = SKILL / "nagrania"
REPLAY_KEY: Final = "github_pat_ODTWORZENIE"
# Zapytania z kluczem, których potrzebuje ``skrzynka`` (przygotowanie stron to ponad 200 zapisów), i bez klucza
# ``aktualnosc`` (tagi, czubek, porównania z wyszukiwaniem binarnym).
NEEDED_WITH_KEY: Final = 600
NEEDED_WITHOUT_KEY: Final = 40
FINE_GRAINED: Final = "fine-grained"

Live = TypeVar("Live")
Client = TypeVar("Client")


@dataclass(frozen=True)
class Result:
    case: str
    facts: Facts
    exchanges: list[Exchange]
    outcome: str
    expected: str
    problems: list[str]

    @property
    def ok(self) -> bool:
        return not self.problems


@dataclass(frozen=True)
class LiveRun:
    """Przebieg na żywo: klucz klienta, harness z kluczem ``gh``, katalog runu (stan sprzed runu i księga funkcji,
    które piszą) i klucz Aktualności (``None``: bez klucza, jak Centrum taty bez pliku klucza)."""

    key: str
    admin: Admin
    root: Path
    freshness_key: str | None


def _short(path: str) -> str:
    return path.replace(f"/repos/{report_box.REPOSITORY}", "…").replace(f"/repos/{TOOL_REPOSITORY}", "…")


def report_line(feature: str, result: Result) -> str:
    asked = ", ".join(_short(exchange.describe()) for exchange in result.exchanges[:4])
    if len(result.exchanges) > 4:
        asked += f", … ({len(result.exchanges)} wymian)"
    verdict = "OK" if result.ok else "ROZJAZD: " + "; ".join(result.problems)
    return f"PRZYPADEK {feature}/{result.case} | GitHub: {asked or '-'} | klient: {result.outcome} | oczekiwane: {result.expected} | {verdict}"


def _run_case(
    case: Case[Live, Client],
    facts: Facts | None,
    prepare: Callable[[], Facts],
    check: Callable[[Facts], tuple[object, list[Exchange], list[str]]],
    describe: Callable[[object], str],
) -> tuple[Result, object]:
    try:
        facts = prepare() if facts is None else facts
    except Exception as error:  # noqa: BLE001 - każda porażka przygotowania to rozjazd przypadku, nie koniec przebiegu
        return Result(case.id, {}, [], "-", case.expected, [f"przygotowanie: {error}"]), None
    try:
        outcome, exchanges, problems = check(facts)
    except Exception:  # noqa: BLE001 - wyjątek klienta to rozjazd przypadku: klient nie rzuca wyjątków sieci
        return Result(
            case.id,
            facts,
            [],
            "-",
            case.expected,
            [f"wyjątek klienta: {traceback.format_exc(limit=3)}"],
        ), None
    problems = [*case.judge(facts, outcome), *problems]
    return Result(case.id, facts, exchanges, describe(outcome), case.expected, problems), outcome


# --- przebieg na żywo -----------------------------------------------------------------------------------------------


def live_skrzynka(context: LiveRun) -> list[Result]:
    key, admin, root, pace = context.key, context.admin, context.root, context.admin.pace
    recorder = Recorder()
    transport = LiveTransport(recorder, pace)
    box = GitHubReportBox(transport=transport)
    run = json.loads((root / github_sprzatanie.RUN_FILE).read_text(encoding="utf-8"))["run"]
    setup = LiveTransport(Recorder(), pace)
    live = skrzynka.SkrzynkaLive(
        run,
        key,
        GitHubReportBox(transport=setup),
        setup,
        admin,
        root / github_sprzatanie.LEDGER,
    )
    for label in skrzynka.LABELS_MADE:
        status, _ = admin.request(
            "POST",
            f"/repos/{TRIAL}/labels",
            {"name": label, "color": "ededed", "description": f"{RUN_MARKER}{run}"},
        )
        if status != 201:
            raise RuntimeError(f"harness: etykieta {label} → {status} (jest już w repozytorium próbnym?)")
    client = skrzynka.Client(box, key)
    results = []
    for case in skrzynka.CASES:

        def check(
            facts: Facts, case: Case[skrzynka.SkrzynkaLive, skrzynka.Client] = case
        ) -> tuple[object, list[Exchange], list[str]]:
            with recorder.case() as exchanges:
                outcome = case.check(client, facts)
            for number in skrzynka.created(outcome):
                live.note({"issue": number})
            return outcome, exchanges, []

        result, outcome = _run_case(case, None, partial(case.prepare, live, {}), check, skrzynka.describe)
        live.earlier[case.id] = (result.facts, outcome)
        results.append(result)
    status, labels = admin.request("GET", f"/repos/{TRIAL}/labels?per_page=100")
    for label in labels if status == 200 and isinstance(labels, list) else []:
        if isinstance(label, dict) and label.get("name") == skrzynka.ABSENT_LABEL:
            live.note({"etykieta": skrzynka.ABSENT_LABEL, "zrodlo": "github"})
    return results


def live_archiwum(context: LiveRun) -> list[Result]:
    key, admin, root, pace = context.key, context.admin, context.root, context.admin.pace
    recorder = Recorder()
    box = GitHubReportBox(transport=LiveTransport(recorder, pace, trial=TRIAL_ARCHIVE))
    run = json.loads((root / github_sprzatanie.RUN_FILE).read_text(encoding="utf-8"))["run"]
    setup = LiveTransport(Recorder(), pace, trial=TRIAL_ARCHIVE)
    live = archiwum.ArchiwumLive(
        run, key, GitHubReportBox(transport=setup), setup, admin, root / github_sprzatanie.LEDGER
    )
    client = skrzynka.Client(box, key)
    results = []
    for case in archiwum.CASES:

        def check(
            facts: Facts, case: Case[archiwum.ArchiwumLive, skrzynka.Client] = case
        ) -> tuple[object, list[Exchange], list[str]]:
            with recorder.case() as exchanges:
                outcome = case.check(client, facts)
            for release in archiwum.created(outcome):
                live.note({"release": release})
            return outcome, exchanges, []

        result, outcome = _run_case(case, None, partial(case.prepare, live, {}), check, archiwum.describe)
        live.earlier[case.id] = (result.facts, outcome)
        results.append(result)
    return results


def live_aktualnosc(context: LiveRun) -> list[Result]:
    token = context.freshness_key
    oracle = aktualnosc.Oracle.read()
    live = aktualnosc.AktualnoscLive(oracle)
    results = []
    with GitHubProxy(token=token) as proxy:
        client = aktualnosc.Client(proxy)
        for case in aktualnosc.CASES:
            proxy.take()

            def check(
                facts: Facts,
                case: Case[aktualnosc.AktualnoscLive, aktualnosc.Client] = case,
            ) -> tuple[object, list[Exchange], list[str]]:
                outcome = case.check(client, facts)
                return outcome, proxy.take(), list(proxy.problems)

            result, _ = _run_case(case, None, partial(case.prepare, live, {}), check, aktualnosc.describe)
            results.append(result)
    return results


# --- odtwarzanie ----------------------------------------------------------------------------------------------------


def stored_recordings() -> dict[str, dict[str, object]]:
    """Nagrania skilla po nazwie: ``aktualnosc`` i ``skrzynka-<rodzaj klucza>`` dla każdego klucza, którym biegły."""

    return {path.stem: read_recording(path) for path in sorted(RECORDINGS.glob("*.json"))}


def feature_of(name: str) -> str:
    return name.split("-", 1)[0]


def by_feature(
    recordings: dict[str, dict[str, list[Exchange]]],
) -> dict[str, dict[str, list[Exchange]]]:
    """Wymiany przypadków każdej funkcji ze wszystkich jej nagrań (każdego klucza) razem."""

    merged: dict[str, dict[str, list[Exchange]]] = {}
    for name, cases in recordings.items():
        for case, exchanges in cases.items():
            merged.setdefault(feature_of(name), {}).setdefault(case, []).extend(exchanges)
    return merged


def _cases_of(document: dict[str, object]) -> dict[str, list[Exchange]]:
    return {case: _exchanges(entry) for case, entry in _entries(document).items()}


def _entries(recording: dict[str, object]) -> dict[str, dict[str, object]]:
    cases = recording.get("przypadki")
    assert isinstance(cases, dict)
    return cases


def _exchanges(entry: dict[str, object]) -> list[Exchange]:
    found = entry.get("wymiany")
    assert isinstance(found, list)
    return [Exchange.of_json(item) for item in found]


def _facts(entry: dict[str, object]) -> Facts:
    found = entry.get("fakty")
    assert isinstance(found, dict)
    return found


def replay(name: str, recording: dict[str, object]) -> list[Result]:
    """Przypadki funkcji nagrania ``name`` (``skrzynka-<rodzaj klucza>``, ``aktualnosc``) na jego wymianach."""

    each = feature(feature_of(name))
    play = each.replay
    assert play is not None, f"funkcja {each.name} nie ma odtwarzania"
    entries = _entries(recording)
    results = []
    for case in each.cases:
        entry = entries.get(case.id)
        if entry is None:
            results.append(
                Result(
                    case.id,
                    {},
                    [],
                    "-",
                    case.expected,
                    [f"nagranie {name} nie ma przypadku {case.id}"],
                )
            )
            continue
        exchanges = _exchanges(entry)

        def check(
            facts: Facts,
            case: Case[Any, Any] = case,
            exchanges: list[Exchange] = exchanges,
        ) -> tuple[object, list[Exchange], list[str]]:
            outcome, problems = play(case, facts, exchanges)
            return outcome, exchanges, problems

        result, _ = _run_case(case, _facts(entry), dict, check, each.describe)
        results.append(result)
    return results


def replay_box(case: Case[Live, skrzynka.Client], facts: Facts, exchanges: list[Exchange]) -> tuple[object, list[str]]:
    """Klient Skrzynki (Zgłoszenia i Archiwum Logów okresu) na nagranych wymianach przypadku."""

    transport = ReplayTransport(exchanges)
    outcome = case.check(skrzynka.Client(GitHubReportBox(transport=transport), REPLAY_KEY), facts)
    return outcome, transport.finish()


def replay_aktualnosc(
    case: Case[aktualnosc.AktualnoscLive, aktualnosc.Client],
    facts: Facts,
    exchanges: list[Exchange],
) -> tuple[object, list[str]]:
    with GitHubProxy(replay=exchanges) as proxy:
        outcome = case.check(aktualnosc.Client(proxy), facts)
        return outcome, [
            *proxy.problems,
            *(f"klient nie zapytał o nagrane {item}" for item in proxy.unused()),
        ]


# --- Doctor ---------------------------------------------------------------------------------------------------------


def client_key(path: Path | None) -> str:
    return gh_token() if path is None else path.read_text(encoding="utf-8").strip().lstrip("﻿")


def _unauthenticated_remaining() -> int | None:
    request = urllib.request.Request(f"{API}/rate_limit", headers={"User-Agent": "verify-github-skrzynki"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            document = json.loads(response.read())
    except (OSError, ValueError):
        return None
    remaining = document.get("resources", {}).get("core", {}).get("remaining")
    return remaining if isinstance(remaining, int) else None


def doctor(key: str, admin: Admin, *, features: Sequence[str], freshness_with_key: bool) -> tuple[bool, str]:
    problems: list[str] = []
    facts = [f"klucz={token_kind(key)}", f"sprzatanie={token_kind(admin.token)}"]
    if not all(trial.startswith(report_box.REPOSITORY + "-") for trial in TRIALS):
        problems.append(f"adres Skrzynki nie jest tym, który skill zna: {report_box.REPOSITORY}")
    selected = [each for each in FEATURES if each.name in features]
    trials = [each.repository for each in selected if each.writes]
    client = Admin(key, Pace())
    for trial in trials:
        status, repository = admin.request("GET", f"/repos/{trial}")
        if status != 200 or not isinstance(repository, dict):
            problems.append(f"repozytorium próbne {trial} → {status}")
        else:
            if repository.get("full_name") != trial or repository.get("private") is not True:
                problems.append(
                    f"{trial} nie jest prywatnym repozytorium próbnym: {repository.get('full_name')}, prywatne={repository.get('private')}"
                )
            if (
                not isinstance(repository.get("permissions"), dict)
                or repository["permissions"].get("admin") is not True
            ):
                problems.append(f"klucz gh nie jest administratorem {trial}: sprzątanie nie usunie issue ani tagów")
            facts.append(f"repo={trial} prywatne")
        status, _ = client.request("GET", f"/repos/{trial}")
        if status != 200:
            problems.append(f"klucz klienta nie widzi repozytorium próbnego {trial} ({status})")
    if trials:
        status, limits = client.request("GET", "/rate_limit")
        remaining = limits.get("resources", {}).get("core", {}).get("remaining") if isinstance(limits, dict) else None
        facts.append(f"limit={remaining}")
        if not isinstance(remaining, int) or remaining < NEEDED_WITH_KEY:
            problems.append(f"limit zapytań klucza klienta {remaining} < {NEEDED_WITH_KEY}")
        left = github_sprzatanie.leftovers(admin)
        facts.append(f"pozostalosci={len(left)}")
        if left:
            problems.append(
                f"pozostałości wcześniejszych runów: {', '.join(left[:5])} (sprzątnij je skryptem sprzątania ich runu)"
            )
    for each in selected:
        problems += each.baseline(admin)
    if any(each.live is not None and not each.writes for each in selected):
        if freshness_with_key:
            _, limits = admin.request("GET", "/rate_limit")
            remaining = (
                limits.get("resources", {}).get("core", {}).get("remaining") if isinstance(limits, dict) else None
            )
        else:
            remaining = _unauthenticated_remaining()
        facts.append(f"limit_aktualnosci={remaining}{' (klucz gh)' if freshness_with_key else ' (bez klucza)'}")
        if not isinstance(remaining, int) or remaining < NEEDED_WITHOUT_KEY:
            problems.append(
                f"limit zapytań Aktualności {remaining} < {NEEDED_WITHOUT_KEY}: poczekaj albo --aktualnosc-z-kluczem"
            )
    line = " | ".join(facts)
    return (
        (not problems, f"DOCTOR OK | {line}")
        if not problems
        else (False, f"DOCTOR FAIL | {'; '.join(problems)} | {line}")
    )


def _box_baseline(admin: Admin) -> list[str]:
    _, labels = admin.request("GET", f"/repos/{TRIAL}/labels?per_page=100")
    names = {entry.get("name") for entry in labels} if isinstance(labels, list) else set()
    present = sorted(names & {*skrzynka.LABELS_MADE, skrzynka.ABSENT_LABEL})
    return [f"repozytorium próbne ma już etykiety Skrzynki {present}: run zakłada je sam"] if present else []


def _archive_baseline(admin: Admin) -> list[str]:
    """Repozytorium próbne Archiwum jak w ``features/README.md``: co najmniej jeden commit, bez Release'ów i tagów."""

    problems = []
    status, commits = admin.request("GET", f"/repos/{TRIAL_ARCHIVE}/commits?per_page=1")
    if status != 200 or not commits:
        problems.append(f"{TRIAL_ARCHIVE} nie ma commitu (lista commitów {status}): Release potrzebuje commitu")
    for name in ("releases", "tags"):
        status, entries = admin.request("GET", f"/repos/{TRIAL_ARCHIVE}/{name}?per_page=100")
        if status != 200 or entries != []:
            problems.append(f"{TRIAL_ARCHIVE} ma {name} albo lista dała {status}: przebieg zaczyna bez nich")
    return problems


# --- rejestr funkcji ------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Feature(Generic[Live, Client]):
    """Funkcja ``--feature``: jej plik ``features/<name>.md`` i wszystko, czego tryby potrzebują.

    ``cases`` to tabela przypadków (``github_przypadki_*.py``), które ``replay`` gra na nagraniu, a ``live`` na
    ``repository``: funkcja na repozytorium próbnym pisze (katalog runu, stan sprzed runu, sprzątanie, nagranie na
    każdy rodzaj klucza), a na repozytorium narzędzia tylko czyta. ``baseline`` to stan repozytorium, od którego
    przebieg zaczyna (Doctor), ``unchecked`` to przypadki, których przebieg nie sprawdza, z powodem.
    """

    name: str
    cases: Sequence[Case[Live, Client]] = ()
    describe: Callable[[object], str] = repr
    replay: Callable[[Case[Live, Client], Facts, list[Exchange]], tuple[object, list[str]]] | None = None
    live: Callable[[LiveRun], list[Result]] | None = None
    repository: str | None = None
    baseline: Callable[[Admin], list[str]] = lambda admin: []
    unchecked: Sequence[tuple[str, str]] = ()

    @property
    def writes(self) -> bool:
        return self.repository in TRIALS


FEATURES: Final[tuple[Feature[Any, Any], ...]] = (
    Feature(
        "skrzynka",
        cases=skrzynka.CASES,
        describe=skrzynka.describe,
        replay=replay_box,
        live=live_skrzynka,
        repository=TRIAL,
        baseline=_box_baseline,
        unchecked=skrzynka.UNCHECKED,
    ),
    Feature(
        "archiwum",
        cases=archiwum.CASES,
        describe=archiwum.describe,
        replay=replay_box,
        live=live_archiwum,
        repository=TRIAL_ARCHIVE,
        baseline=_archive_baseline,
        unchecked=archiwum.UNCHECKED,
    ),
    Feature(
        "aktualnosc",
        cases=aktualnosc.CASES,
        describe=aktualnosc.describe,
        replay=replay_aktualnosc,
        live=live_aktualnosc,
        repository=TOOL_REPOSITORY,
    ),
    # Bez sieci: atrapy testów wobec nagrań każdej funkcji.
    Feature("wiernosc-atrap"),
)
LIVE: Final = tuple(each.name for each in FEATURES if each.live is not None)


def feature(name: str) -> Feature[Any, Any]:
    [found] = [each for each in FEATURES if each.name == name]
    return found


# --- wynik ----------------------------------------------------------------------------------------------------------


def unchecked(kinds: dict[str, str]) -> list[str]:
    lines = [f"NIESPRAWDZONE | {each.name}/{name} | {why}" for each in FEATURES for name, why in each.unchecked]
    for each in FEATURES:
        box_kinds = sorted(kind for name, kind in kinds.items() if feature_of(name) == each.name)
        if each.writes and box_kinds and FINE_GRAINED not in box_kinds:
            lines.append(
                f"NIESPRAWDZONE | {each.name}/klucz-taty | przebieg kluczem {', '.join(box_kinds)}, a klucz taty to "
                f"{FINE_GRAINED} (Issues i Contents RW): uruchom na-zywo --klucz-plik z tokenem fine-grained repozytoriów próbnych"
            )
    if kinds.get("aktualnosc") not in (None, "bez klucza"):
        lines.append(
            f"NIESPRAWDZONE | aktualnosc/bez-klucza | Aktualność pytana kluczem {kinds['aktualnosc']}, a Centrum taty bez pliku klucza pyta bez klucza"
        )
    return lines


def recording(name: str, results: list[Result], kind: str) -> dict[str, object]:
    head = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return {
        "nagrano": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "commit": head,
        "klucz": kind,
        "repozytorium": feature(feature_of(name)).repository,
        "przypadki": {
            result.case: {
                "fakty": result.facts,
                "wymiany": [exchange.to_json() for exchange in result.exchanges],
                "wynik": result.outcome,
            }
            for result in results
        },
    }


def finish(
    lines: list[str],
    results: dict[str, list[Result]],
    differences: list[str],
    evidence: Path,
    kinds: dict[str, str],
    features: Sequence[str],
) -> int:
    for feature, found in results.items():
        lines += [report_line(feature, result) for result in found]
    lines += [f"RÓŻNICA | wiernosc-atrap | {difference}" for difference in differences]
    lines += unchecked(kinds)
    failed = [f"{feature}/{result.case}" for feature, found in results.items() for result in found if not result.ok]
    if differences:
        failed.append(f"wiernosc-atrap ({len(differences)})")
    total = sum(len(found) for found in results.values())
    passed = total - sum(1 for found in results.values() for result in found if not result.ok)
    keys = ",".join(f"{feature}:{kind}" for feature, kind in kinds.items())
    common = f"features={','.join(features)} | przypadki={passed}/{total} | klucze={keys} | evidence={evidence}"
    lines.append(f"VERIFY OK | {common}" if not failed else f"VERIFY FAIL | rozjazdy={', '.join(failed)} | {common}")
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "przebieg.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0 if not failed else 1


def _features(value: str, allowed: Sequence[str]) -> tuple[str, ...]:
    return tuple(allowed) if value == "all" else (value,)


def main() -> int:
    parser = Parser(description=__doc__.splitlines()[0])
    parser.add_argument("tryb", choices=("doctor", "na-zywo", "odtworz"))
    parser.add_argument("--feature", choices=(*(each.name for each in FEATURES), "all"), default="all")
    parser.add_run_dir()
    parser.add_argument(
        "--klucz-plik",
        type=Path,
        help="plik z kluczem klienta (np. token fine-grained repozytorium próbnego); domyślnie gh auth token",
    )
    parser.add_argument(
        "--aktualnosc-z-kluczem",
        action="store_true",
        help="Aktualność pyta kluczem gh (limit 5000/h) zamiast bez klucza jak Centrum",
    )
    parser.add_argument(
        "--zapisz-nagrania",
        action="store_true",
        help="nagrania przebiegu na żywo zastępują nagrania/ skilla",
    )
    arguments = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(3)
    if arguments.tryb == "odtworz":
        return replay_all(
            _features(arguments.feature, [each.name for each in FEATURES]),
            arguments.run_dir / "evidence" / f"odtworzenie-{stamp}",
        )
    if arguments.feature == "wiernosc-atrap":
        parser.error("wiernosc-atrap biegnie bez sieci: odtworz --feature wiernosc-atrap")
    features = _features(arguments.feature, LIVE)
    admin = Admin(gh_token(), Pace())
    key = client_key(arguments.klucz_plik)
    healthy, line = doctor(key, admin, features=features, freshness_with_key=arguments.aktualnosc_z_kluczem)
    if arguments.tryb == "doctor" or not healthy:
        print(line)
        return 0 if healthy else 2
    return live_all(features, key, admin, arguments, stamp, line)


def live_all(
    features: Sequence[str],
    key: str,
    admin: Admin,
    arguments: argparse.Namespace,
    stamp: str,
    doctor_line: str,
) -> int:
    run = new_run(arguments.run_dir, f"github-{stamp}")
    (run.evidence / "doctor.txt").write_text(doctor_line + "\n", encoding="utf-8")
    selected = [each for each in FEATURES if each.name in features]
    freshness_key = admin.token if arguments.aktualnosc_z_kluczem else None
    # Nagranie funkcji, która pisze, ma rodzaj klucza klienta w nazwie, bo każdy rodzaj nagrywa się osobno.
    names = {each.name: f"{each.name}-{token_slug(key)}" if each.writes else each.name for each in selected}
    freshness_kind = "bez klucza" if freshness_key is None else f"{token_kind(admin.token)} (gh)"
    kinds = {names[each.name]: token_kind(key) if each.writes else freshness_kind for each in selected}
    context = LiveRun(key, admin, run.root, freshness_key)
    results: dict[str, list[Result]] = {}
    lines = [doctor_line]
    restored = True
    if any(each.writes for each in selected):
        root = create_run_root(run.root)
        before = github_sprzatanie.state(admin)
        (root / github_sprzatanie.RUN_FILE).write_text(
            json.dumps(
                {"run": stamp, "dowody": str(run.evidence), "stan_przed": before},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        try:
            for each in selected:
                if not each.writes or each.live is None:
                    continue
                name = names[each.name]
                try:
                    results[name] = each.live(context)
                except Exception:  # noqa: BLE001 - przerwany przebieg to VERIFY FAIL, a sprzątanie biegnie i tak
                    results[name] = [
                        Result(
                            "przebieg",
                            {},
                            [],
                            "-",
                            "-",
                            [f"wyjątek harnessu: {traceback.format_exc(limit=3)}"],
                        )
                    ]
        finally:
            restored, cleaned = github_sprzatanie.clean(root)
            lines.append(cleaned[-1])
            (run.evidence / "harness.txt").write_text("\n".join(admin.log) + "\n", encoding="utf-8")
    for each in selected:
        if not each.writes and each.live is not None:
            results[names[each.name]] = each.live(context)
    recordings = {name: _cases_of(document) for name, document in stored_recordings().items()}
    for name, found in results.items():
        document = recording(name, found, kinds[name])
        write_recording(run.evidence / "nagrania" / f"{name}.json", document)
        if arguments.zapisz_nagrania:
            write_recording(RECORDINGS / f"{name}.json", document)
        recordings[name] = {result.case: result.exchanges for result in found}
    _, differences = fidelity(lines, by_feature(recordings))
    if not restored:
        differences.append("repozytorium próbne nie wróciło do stanu sprzed runu (sprzatanie.txt)")
    return finish(lines, results, differences, run.evidence, kinds, [*features, "wiernosc-atrap"])


def fidelity(lines: list[str], recordings: dict[str, dict[str, list[Exchange]]]) -> tuple[list[str], list[str]]:
    found, differences = github_wiernosc.compare(recordings)
    lines += found
    return found, differences


def replay_all(features: Sequence[str], evidence: Path) -> int:
    results: dict[str, list[Result]] = {}
    kinds: dict[str, str] = {}
    lines: list[str] = []
    stored = stored_recordings()
    differences = [
        f"brak nagrania funkcji {feature} w {RECORDINGS}"
        for feature in features
        if feature in LIVE and not any(feature_of(name) == feature for name in stored)
    ]
    for name, document in stored.items():
        lines.append(
            f"NAGRANIE | {name} | {document.get('nagrano')} | klucz {document.get('klucz')} | commit {str(document.get('commit'))[:9]}"
        )
        kinds[name] = str(document.get("klucz"))
        if feature_of(name) in features:
            results[name] = replay(name, document)
    if "wiernosc-atrap" in features:
        differences += fidelity(
            lines,
            by_feature({name: _cases_of(document) for name, document in stored.items()}),
        )[1]
    return finish(lines, results, differences, evidence, kinds, features)


if __name__ == "__main__":
    raise SystemExit(main())
