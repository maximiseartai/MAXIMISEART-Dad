"""Wierność atrap GitHuba w testach: czy odpowiedzi, którymi testy zastępują GitHuba, mają kształt nagranych.

Testy klienta Skrzynki (``ScriptedTransport`` w ``tests/test_skrzynka_zgloszen_github.py``) i Aktualności narzędzia
(serwer ``_GitHub`` w ``tests/test_aktualnosc_narzedzia.py``) piszą odpowiedzi GitHuba same. To sprawdzenie
uruchamia testy z ``MAPPING`` w tym procesie (pytest), zapisuje każdą odpowiedź atrapy i porównuje ją z nagraną
odpowiedzią prawdziwego GitHuba w tej samej sytuacji (przypadek nagrania i rodzaj pytania):

- status: każdy status, którym GitHub odpowiedział w tej sytuacji, atrapa też daje;
- kształt: przy odpowiedzi 2xx pole, które czyta klient (``FIELDS``) i które daje atrapa, ma wśród swoich typów typ,
  który dał GitHub (``null`` u GitHuba niczego nie wymaga). Pole, które ma tylko atrapa albo którego atrapa nie daje,
  nie jest różnicą: testy celowo podają odpowiedzi w innym kształcie albo niepełne, a pole, którego GitHub nie daje,
  a klient czyta, łapie przebieg na żywo.

Nagłówka ``Link`` sprawdzenie nie porównuje: klient czyta z niego tylko ``rel="next"``, a to sprawdza przypadek
``tagi-strony`` na żywo i w odtwarzaniu.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Final

import pytest

from github_wymiana import Exchange

ROOT = Path(__file__).resolve().parents[4]

# Klasy atrap GitHuba w modułach testów: transporty HTTP klienta Skrzynki (z ``__call__``).
TRANSPORTS: Final = ("ScriptedTransport", "GitHubOnTransport")
BOX_TESTS: Final = "tests/test_skrzynka_zgloszen_github.py"
FRESHNESS_TESTS: Final = "tests/test_aktualnosc_narzedzia.py"

# Rodzaj pytania z metody i ścieżki (bez hosta i repozytorium).
_KINDS: Final = (
    ("zalozenie", "POST", re.compile(r".*/issues$")),
    ("komentarz", "POST", re.compile(r".*/issues/\d+/comments$")),
    ("poprawka", "PATCH", re.compile(r".*/issues/comments/\d+$")),
    ("komentarze", "GET", re.compile(r".*/issues/\d+/comments\?.*")),
    ("lista", "GET", re.compile(r".*/issues\?.*")),
    ("zalozenie-archiwum", "POST", re.compile(r".*-zgloszenia/releases$")),
    ("archiwa", "GET", re.compile(r".*-zgloszenia/releases\?.*")),
    ("pliki-archiwum", "GET", re.compile(r".*/releases/\d+/assets\?.*")),
    ("wysylka-pliku", "POST", re.compile(r".*/releases/\d+/assets\?.*")),
    ("usuniecie-pliku", "DELETE", re.compile(r".*/releases/assets/\d+$")),
    ("tagi", "GET", re.compile(r".*/tags(\?.*)?$")),
    ("czubek", "GET", re.compile(r".*/git/ref/heads/main$")),
    ("porownanie", "GET", re.compile(r".*/compare/[^/]+\.\.\.[^/?]+(\?.*)?$")),
    ("pr-commitu", "GET", re.compile(r".*/commits/[^/]+/pulls$")),
    ("wydania", "GET", re.compile(r".*/releases(\?.*)?$")),
)

# Pola, które klient czyta z odpowiedzi 2xx danego rodzaju (``[]``: wpis listy).
FIELDS: Final[Mapping[str, frozenset[str]]] = {
    "zalozenie": frozenset({"number"}),
    "komentarz": frozenset({"id", "html_url"}),
    "poprawka": frozenset({"id", "html_url"}),
    "komentarze": frozenset({"[].id", "[].html_url", "[].body"}),
    "lista": frozenset({"[].number", "[].body", "[].state", "[].state_reason", "[].closed_at"}),
    "zalozenie-archiwum": frozenset({"id"}),
    "archiwa": frozenset({"[].id", "[].tag_name"}),
    "pliki-archiwum": frozenset({"[].id", "[].name", "[].label", "[].state"}),
    "wysylka-pliku": frozenset({"id", "name", "label", "state"}),
    "usuniecie-pliku": frozenset(),
    "tagi": frozenset({"[].name", "[].commit.sha"}),
    "czubek": frozenset({"object.sha"}),
    "porownanie": frozenset({"status", "ahead_by"}),
    "pr-commitu": frozenset({"[].merge_commit_sha", "[].merged_at", "[].base.ref"}),
    "wydania": frozenset({"[].tag_name", "[].body", "[].published_at", "[].draft", "[].prerelease"}),
}


@dataclass(frozen=True)
class Row:
    """Sytuacja z nagrania (``case`` z ``feature``, rodzaj pytania ``kind``) i testy, których atrapa ją odtwarza."""

    feature: str
    case: str
    kind: str
    tests: tuple[str, ...]


EMPTY_REPOSITORY_TEST: Final = "test_odmowa_archiwum_zatrzymuje_tylko_plik_logow_a_zgloszenie_za_nimi_dochodzi_w_tym_samym_przejsciu_bez_komunikatu"


def _box(name: str) -> str:
    return f"{BOX_TESTS}::{name}"


def _fresh(name: str) -> str:
    return f"{FRESHNESS_TESTS}::{name}"


MAPPING: Final = (
    Row(
        "skrzynka",
        "zalozenie",
        "zalozenie",
        (_box("test_utworzone_issue_to_wyslane_zgloszenie_z_numerem"),),
    ),
    Row(
        "skrzynka",
        "zalozenie-ponad-limit",
        "zalozenie",
        (_box("test_odmowa_tresci_wysylki_to_odmowa_tej_wysylki_a_nie_brak_sieci[open_issue-422]"),),
    ),
    Row(
        "skrzynka",
        "komentarz",
        "komentarz",
        (_box("test_przyjety_komentarz_ma_identyfikator_i_adres"),),
    ),
    Row(
        "skrzynka",
        "komentarz-ponad-limit",
        "komentarz",
        (_box("test_odmowa_tresci_wysylki_to_odmowa_tej_wysylki_a_nie_brak_sieci[comment-422]"),),
    ),
    Row(
        "skrzynka",
        "komentarz-brak-issue",
        "komentarz",
        (_box("test_odmowa_przy_komentarzu_to_odmowa_skrzynki[404]"),),
    ),
    Row(
        "skrzynka",
        "poprawka",
        "poprawka",
        (_box("test_poprawiony_komentarz_ma_ten_sam_identyfikator_i_adres_a_skrzynka_dostaje_nowa_tresc"),),
    ),
    Row(
        "skrzynka",
        "poprawka-brak-komentarza",
        "poprawka",
        (_box("test_odmowa_przy_poprawce_komentarza_to_odmowa_skrzynki[404]"),),
    ),
    Row(
        "skrzynka",
        "poprawka-ponad-limit",
        "poprawka",
        (_box("test_odmowa_tresci_wysylki_to_odmowa_tej_wysylki_a_nie_brak_sieci[edit_comment-422]"),),
    ),
    Row(
        "skrzynka",
        "komentarze-strony",
        "komentarze",
        (_box("test_komentarze_issue_sa_zbierane_ze_wszystkich_stron"),),
    ),
    Row(
        "skrzynka",
        "komentarze-brak-issue",
        "komentarze",
        (_box("test_porazka_strony_komentarzy_to_porazka_calosci[usuniete-issue]"),),
    ),
    Row(
        "skrzynka",
        "lista-strony",
        "lista",
        (_box("test_issue_z_etykieta_sa_zbierane_ze_wszystkich_stron"),),
    ),
    Row(
        "skrzynka",
        "lista-zamkniete",
        "lista",
        (_box("test_zamkniete_issue_ma_powod_i_czas_zamkniecia_a_otwarte_nie"),),
    ),
    Row(
        "skrzynka",
        "archiwum-brak",
        "archiwa",
        (_box("test_bez_release_z_tagiem_okresu_archiwum_jeszcze_nie_ma"),),
    ),
    # Repozytorium bez commitu: atrapa GitHuba w pamięci (``GitHubOnTransport``) z 409 (#860) i 422 (repozytorium próbne).
    Row(
        "skrzynka",
        "archiwum-w-pustym-repo",
        "zalozenie-archiwum",
        (
            _box(f"{EMPTY_REPOSITORY_TEST}[puste-repozytorium]"),
            _box(f"{EMPTY_REPOSITORY_TEST}[puste-repozytorium-422]"),
        ),
    ),
    Row(
        "skrzynka",
        "zly-klucz",
        "zalozenie",
        (_box("test_odmowa_autoryzacji_to_odmowa_skrzynki[401]"),),
    ),
    Row(
        "skrzynka",
        "zly-klucz",
        "lista",
        (_box("test_odmowa_autoryzacji_przy_szukaniu_to_odmowa_skrzynki[401]"),),
    ),
    Row(
        "skrzynka",
        "zly-klucz",
        "komentarz",
        (_box("test_odmowa_przy_komentarzu_to_odmowa_skrzynki[401]"),),
    ),
    Row(
        "skrzynka",
        "zly-klucz",
        "poprawka",
        (_box("test_odmowa_przy_poprawce_komentarza_to_odmowa_skrzynki[401]"),),
    ),
    # ADR 0007 i keyed_box (#402): usunięte issue to 404, więc atrapa usuniętego issue odpowiada 404.
    Row(
        "skrzynka",
        "usuniete-issue",
        "komentarz",
        (_box("test_odmowa_przy_komentarzu_to_odmowa_skrzynki[404]"),),
    ),
    Row(
        "skrzynka",
        "usuniete-issue",
        "komentarze",
        (_box("test_porazka_strony_komentarzy_to_porazka_calosci[usuniete-issue]"),),
    ),
    Row(
        "skrzynka",
        "usuniete-issue",
        "poprawka",
        (_box("test_odmowa_przy_poprawce_komentarza_to_odmowa_skrzynki[404]"),),
    ),
    Row(
        "aktualnosc",
        "tagi-strony",
        "tagi",
        (_fresh("test_najnowsze_wydanie_ze_wszystkich_stron_listy_tagow"),),
    ),
    Row(
        "aktualnosc",
        "najnowsze-wydanie",
        "czubek",
        (_fresh("test_najnowsze_wydanie_to_najwyzszy_numer_a_nie_ostatni_tag_alfabetycznie"),),
    ),
    Row(
        "aktualnosc",
        "linia-scalenie-pr",
        "pr-commitu",
        (_fresh("test_wydanie_ze_scalenia_pr_daleko_na_linii_main_to_cztery_pytania_bez_wzgledu_na_odleglosc"),),
    ),
    Row(
        "aktualnosc",
        "linia-bez-pr",
        "porownanie",
        # Wyszukiwanie binarne na `main` z merge'ami pyta o tip~k dalej niż linia pierwszych rodziców (404, jak przed
        # pierwszym commitem), a w atrapie „daleko” linia jest dłuższa niż ``ahead_by``: obie atrapy razem.
        (
            _fresh("test_wydanie_daleko_na_linii_main_kosztuje_tylko_logarytm_porownan"),
            _fresh("test_wydanie_na_pierwszym_commicie_repozytorium_jest_na_main"),
        ),
    ),
    Row(
        "aktualnosc",
        "poza-linia",
        "porownanie",
        (_fresh("test_wydanie_z_galezi_wciagnietej_mergem_nie_jest_na_main_i_ta_odpowiedz_zostaje_w_pamieci"),),
    ),
    Row(
        "aktualnosc",
        "przed-poczatkiem",
        "porownanie",
        (_fresh("test_wydanie_na_pierwszym_commicie_repozytorium_jest_na_main"),),
    ),
    Row(
        "aktualnosc",
        "opublikowane",
        "wydania",
        (_fresh("test_lista_wydan_ma_tylko_opublikowane_wydania_z_notka_i_czasem_publikacji"),),
    ),
)


def kind(method: str, path: str) -> str | None:
    return next(
        (name for name, verb, pattern in _KINDS if verb == method and pattern.fullmatch(path)),
        None,
    )


@dataclass(frozen=True)
class Fake:
    method: str
    path: str
    status: int
    body: bytes


def _shape(value: object, prefix: str = "") -> Iterator[tuple[str, str]]:
    """Pary (ścieżka pola, typ JSON); wpis listy to ``[]``."""

    if isinstance(value, dict):
        for name, item in value.items():
            path = f"{prefix}.{name}" if prefix else str(name)
            yield path, _type(item)
            yield from _shape(item, path)
    elif isinstance(value, list):
        for item in value:
            path = f"{prefix}.[]" if prefix else "[]"
            yield path, _type(item)
            yield from _shape(item, path)


def _type(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    return {int: "int", float: "float", str: "str", list: "list", dict: "object"}.get(type(value), type(value).__name__)


def _parsed(body: bytes) -> object:
    try:
        return json.loads(body)
    except ValueError:
        return None


class _Capture:
    """Plugin pytesta: zapisuje odpowiedzi atrap z ``ScriptedTransport`` i serwera ``_GitHub`` każdego testu."""

    def __init__(self) -> None:
        self.fakes: dict[str, list[Fake]] = defaultdict(list)
        self.outcomes: dict[str, str] = {}

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_call(self, item: pytest.Item) -> Iterator[None]:
        module: Any = getattr(item, "module", None)
        node = item.nodeid
        undo: list[Callable[[], None]] = []
        for name in TRANSPORTS:
            transport = getattr(module, name, None)
            if transport is not None:
                undo.append(self._wrap(transport, node))
        handler = getattr(module, "_GitHub", None)
        if handler is not None:
            original_get = handler.do_GET

            def do_get(served: Any) -> None:
                real = served.wfile
                tee = _Tee(real)
                served.wfile = tee
                try:
                    original_get(served)
                finally:
                    served.wfile = real
                    fake = _from_raw(served.path, bytes(tee.data))
                    if fake is not None:
                        self.fakes[node].append(fake)

            handler.do_GET = do_get
            undo.append(lambda: setattr(handler, "do_GET", original_get))
        try:
            yield
        finally:
            for step in undo:
                step()

    def _wrap(self, transport: Any, node: str) -> Callable[[], None]:
        """Zapis każdej odpowiedzi transportu-atrapy ``transport`` (klasy z ``__call__``) w teście ``node``."""

        original_call = transport.__call__

        def call(scripted: Any, request: Any) -> Any:
            response = original_call(scripted, request)
            self.fakes[node].append(
                Fake(
                    request.method,
                    _strip_host(request.url),
                    response.status,
                    response.body,
                )
            )
            return response

        transport.__call__ = call
        return lambda: setattr(transport, "__call__", original_call)

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if report.when == "call" or report.outcome != "passed":
            self.outcomes[report.nodeid] = report.outcome


class _Tee:
    def __init__(self, real: Any) -> None:
        self._real = real
        self.data = bytearray()

    def write(self, data: bytes) -> int:
        self.data += data
        return int(self._real.write(data))

    def flush(self) -> None:
        self._real.flush()


def _from_raw(path: str, raw: bytes) -> Fake | None:
    head, _, body = bytes(raw).partition(b"\r\n\r\n")
    status_line = head.split(b"\r\n", 1)[0].split()
    if len(status_line) < 2 or not status_line[1].isdigit():
        return None
    return Fake("GET", path, int(status_line[1]), body)


def _strip_host(url: str) -> str:
    return re.sub(r"^https?://[^/]+", "", url)


def capture(tests: tuple[str, ...]) -> tuple[dict[str, list[Fake]], list[str]]:
    """Odpowiedzi atrap testów ``tests`` i problemy (test, który nie przeszedł albo którego nie ma)."""

    plugin = _Capture()
    arguments = [
        "-q",
        "-p",
        "no:cacheprovider",
        "--rootdir",
        str(ROOT),
        "-c",
        str(ROOT / "pyproject.toml"),
    ]
    code = pytest.main([*arguments, *(str(ROOT / test) for test in tests)], plugins=[plugin])
    ran = {node.replace("\\", "/") for node in plugin.outcomes}
    problems = [f"test atrapy {test} nie biegł: nie ma go albo zmienił nazwę" for test in tests if test not in ran]
    problems += [f"test atrapy {node} → {outcome}" for node, outcome in plugin.outcomes.items() if outcome != "passed"]
    if code not in (0,) and not problems:
        problems.append(f"pytest testów atrap zakończył się kodem {code}")
    return plugin.fakes, problems


def compare(
    recordings: Mapping[str, Mapping[str, list[Exchange]]],
) -> tuple[list[str], list[str]]:
    """Linie wyniku i różnice; ``recordings`` to wymiany przypadków każdej funkcji."""

    tests = tuple(dict.fromkeys(test for row in MAPPING for test in row.tests))
    fakes, problems = capture(tests)
    lines: list[str] = []
    differences = list(problems)
    for row in MAPPING:
        real = [
            exchange
            for exchange in recordings.get(row.feature, {}).get(row.case, [])
            if kind(exchange.method, exchange.path) == row.kind
        ]
        faked = [fake for test in row.tests for fake in fakes.get(test, []) if kind(fake.method, fake.path) == row.kind]
        found = _row(row, real, faked)
        differences += found
        lines.append(f"WIERNOŚĆ | {row.case} | {row.kind} | " + ("OK" if not found else "RÓŻNICA"))
    covered = {(row.feature, row.case, row.kind) for row in MAPPING}
    for feature, cases in recordings.items():
        for case, exchanges in cases.items():
            for exchange in exchanges:
                answer = kind(exchange.method, exchange.path)
                if answer is not None and (feature, case, answer) not in covered:
                    lines.append(f"BEZ ATRAPY | {case} | {answer} {exchange.status}")
    return list(dict.fromkeys(lines)), differences


def _row(row: Row, real: list[Exchange], faked: list[Fake]) -> list[str]:
    label = f"{row.case} ({row.kind})"
    if not real:
        return [f"{label}: nagranie nie ma takiej wymiany"]
    if not faked:
        return [f"{label}: testy {', '.join(row.tests)} nie dały atrapy tego rodzaju"]
    statuses = {fake.status for fake in faked}
    problems = [
        f"{label}: GitHub odpowiada {status} na {exchange.method} {exchange.path.split('?')[0]}, atrapa {sorted(statuses)}"
        for exchange in real
        for status in [exchange.status]
        if status not in statuses
    ]
    read = FIELDS[row.kind]
    for status in sorted(
        {exchange.status for exchange in real if exchange.status is not None and 200 <= exchange.status < 300}
        & statuses
    ):
        expected = {
            pair
            for exchange in real
            if exchange.status == status
            for pair in _shape(exchange.body)
            if pair[0] in read and pair[1] != "null"
        }
        given: dict[str, set[str]] = defaultdict(set)
        for fake in faked:
            if fake.status == status:
                for path, type_ in _shape(_parsed(fake.body)):
                    given[path].add(type_)
        problems += [
            f"{label}: atrapa {status} ma pole {path} tylko typu {sorted(given[path])}, a GitHub daje {type_}"
            for path, type_ in sorted(expected)
            if path in given and type_ not in given[path]
        ]
    return list(dict.fromkeys(problems))
