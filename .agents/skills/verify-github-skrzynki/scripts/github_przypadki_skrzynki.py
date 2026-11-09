"""Przypadki Skrzynki Zgłoszeń: każda operacja ``GitHubReportBox`` i ``KeyedBox`` na repozytorium próbnym.

Oczekiwany wynik każdego przypadku pochodzi z domeny (docstringi ``report_box`` i ``keyed_box``, ADR 0007, pomiar
limitu treści z #332 przy ``COMMENT_LIMIT``), nie z przebiegu kodu. Przypadki biegną po kolei: późniejszy bierze
numery issue i komentarzy z wcześniejszych (``earlier``), a w odtwarzaniu z faktów swojego nagrania.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import sys
import time
from typing import Final, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))

from rozliczenia.centrum.keyed_box import KeyedBox
from rozliczenia.centrum.report_issue import fingerprint_line
from rozliczenia.centrum.report_box import (
    COMMENT_LIMIT,
    Closure,
    Comment,
    Commented,
    GitHubReportBox,
    Issue,
    Label,
    Refused,
    Rejected,
    Sent,
)

from github_wymiana import CAUGHT_UP, RUN_MARKER, TRIAL, Admin, Case, Facts, LiveTransport

# Odcisk problemu wszystkich Zgłoszeń runu: tak Centrum znajduje otwarte Zgłoszenie (ADR 0007).
FINGERPRINT: Final = "0123456789abcdef"
# Klucz o postaci tokenu fine-grained, którego GitHub nie zna.
BAD_KEY: Final = "github_pat_" + "0" * 82
# Numer issue i identyfikator komentarza, których repozytorium próbne nie ma.
MISSING_ISSUE: Final = 999_999
MISSING_COMMENT: Final = 1
# Archiwum i plik Archiwum, których repozytorium próbne nie ma (puste repozytorium nie ma żadnego Release).
MISSING_ARCHIVE: Final = 1
MISSING_ASSET: Final = 1
# Etykiety, które Maks zakłada w Skrzynce; ``uwaga-taty`` zostaje w repozytorium próbnym bez etykiety.
LABELS_MADE: Final[tuple[Label, ...]] = (
    "zgloszenie",
    "kontrola-ilosci",
    "logi-uruchomienia",
)
ABSENT_LABEL: Final[Label] = "uwaga-taty"
PAGE: Final = 100
SETTLE_S: Final = 90.0
# Komentarz i jego poprawka przyjmują do tylu bajtów UTF-8 (pomiar #332 przy ``COMMENT_LIMIT``).
COMMENT_BYTES: Final = 262_144


@dataclass(frozen=True)
class Client:
    box: GitHubReportBox
    key: str


@dataclass
class SkrzynkaLive:
    """Przebieg na żywo: run, klucz klienta, klient bez nagrywania (przygotowanie), harness i rejestr założonego."""

    run: str
    key: str
    setup: GitHubReportBox
    setup_transport: LiveTransport
    admin: Admin
    ledger: Path
    earlier: dict[str, tuple[Facts, object]] = field(default_factory=dict)

    @property
    def marker(self) -> str:
        return marker(self.run)

    def note(self, entry: Facts) -> None:
        with self.ledger.open("a", encoding="utf-8") as file:
            file.write(json.dumps(entry) + "\n")

    def open(self, label: Label, title: str, body: str) -> int:
        """Issue założone klientem (bez nagrania) jako warunek przypadku; inny wynik niż ``Sent`` przerywa przypadek."""

        outcome = self.setup.open_issue(label, title, body, key=self.key)
        if not isinstance(outcome, Sent):
            raise RuntimeError(f"założenie issue dało {outcome} ({self.setup_transport.last})")
        self.note({"issue": outcome.number})
        return outcome.number

    def comment(self, number: int, body: str) -> int:
        outcome = self.setup.comment(number, body, key=self.key)
        if not isinstance(outcome, Commented):
            raise RuntimeError(f"komentarz dał {outcome} ({self.setup_transport.last})")
        return outcome.id

    def settle(self, label: Label, state: str, numbers: set[int], *, exact: bool = False) -> float:
        """Czeka, aż lista issue GitHuba z etykietą ``label`` pokaże ``numbers`` (z ``exact`` tylko je), i zwraca, po ilu
        sekundach: lista nadąża za założeniem i zamknięciem po kilku sekundach (pomiar 5.11.2026: 98 ze 101), a
        przypadek sprawdza klienta na stanie, który GitHub już pokazuje."""

        started = time.monotonic()
        while True:
            listed = {
                entry["number"]
                for entry in self.admin.pages(f"/repos/{TRIAL}/issues?state={state}&labels={label}")
                if isinstance(entry, dict)
            }
            if numbers <= listed and (not exact or listed == numbers):
                return round(time.monotonic() - started, 1)
            if time.monotonic() - started > SETTLE_S:
                raise RuntimeError(
                    f"lista issue z etykietą {label} ({state}) po {SETTLE_S:.0f} s: {len(listed & numbers)} z {len(numbers)}"
                )
            time.sleep(2)

    def number(self, case: str) -> int:
        """Numer issue z wyniku wcześniejszego przypadku ``case``; bez niego przypadek nie ma warunku."""

        _, outcome = self.earlier.get(case, ({}, None))
        found = outcome[0] if isinstance(outcome, tuple) and outcome else outcome
        if not isinstance(found, Sent):
            raise RuntimeError(f"brak warunku: przypadek {case} nie założył issue ({outcome})")
        return found.number

    def commented(self, case: str) -> Commented:
        _, outcome = self.earlier.get(case, ({}, None))
        if not isinstance(outcome, Commented):
            raise RuntimeError(f"brak warunku: przypadek {case} nie dodał komentarza ({outcome})")
        return outcome


def marker(run: str) -> str:
    return f"<!-- {RUN_MARKER}{run} -->"


def text(facts: Facts) -> str:
    """Treść z faktów: zapisana wprost albo zbudowana z długości i znaku (treści na granicy limitu)."""

    if "tresc" in facts:
        return str(facts["tresc"])
    start, sign, length = (
        str(facts["znacznik"]) + "\n",
        str(facts["znak"]),
        int(cast(int, facts["dlugosc"])),
    )
    return start + sign * (length - len(start))


def _long(live: SkrzynkaLive, length: int, sign: str = "x") -> Facts:
    return {"znacznik": live.marker, "znak": sign, "dlugosc": length}


def _title(live: SkrzynkaLive, case: str) -> str:
    return f"verify-github-skrzynki {live.run}: {case}"


def _int(facts: Facts, name: str) -> int:
    return int(cast(int, facts[name]))


def _expect(outcome: object, expected: object) -> list[str]:
    return [] if outcome == expected else [f"wynik {outcome}, oczekiwane {expected}"]


def _sent(outcome: object) -> list[str]:
    return [] if isinstance(outcome, Sent) and outcome.number > 0 else [f"wynik {outcome}, oczekiwane Sent z numerem"]


def _numbers(outcome: object) -> list[int] | None:
    return [issue.number for issue in outcome] if isinstance(outcome, tuple) else None


# --- zakładanie issue -----------------------------------------------------------------------------------------------


def _prepare_open(live: SkrzynkaLive, earlier: Facts) -> Facts:
    body = f"{live.marker}\n\n## Narzędzie\n\n{fingerprint_line(FINGERPRINT)}\n"
    return {"etykieta": "zgloszenie", "tytul": _title(live, "zalozenie"), "tresc": body}


def _open(client: Client, facts: Facts) -> object:
    label = cast(Label, facts["etykieta"])
    return client.box.open_issue(label, str(facts["tytul"]), text(facts), key=client.key)


def _prepare_absent_label(live: SkrzynkaLive, earlier: Facts) -> Facts:
    status, labels = live.admin.request("GET", f"/repos/{TRIAL}/labels?per_page=100")
    names = {entry.get("name") for entry in labels} if isinstance(labels, list) else None
    if status != 200 or names is None or ABSENT_LABEL in names:
        raise RuntimeError(
            f"brak warunku: etykieta {ABSENT_LABEL} jest w repozytorium próbnym albo lista etykiet dała {status}"
        )
    return {"etykieta": ABSENT_LABEL}


def _list_absent(client: Client, facts: Facts) -> object:
    return client.box.labelled_issues(cast(Label, facts["etykieta"]), include_closed=True, key=client.key)


def _prepare_open_absent(live: SkrzynkaLive, earlier: Facts) -> Facts:
    return {
        "etykieta": ABSENT_LABEL,
        "tytul": _title(live, "bez-etykiety"),
        "tresc": f"{live.marker}\n\nUwaga taty.\n",
    }


def _prepare_label_by_github(live: SkrzynkaLive, earlier: Facts) -> Facts:
    number = live.number("zalozenie-bez-etykiety-w-repo")
    waited = live.settle(ABSENT_LABEL, "open", {number})
    status, _ = live.admin.request("GET", f"/repos/{TRIAL}/labels/{ABSENT_LABEL}")
    return {
        "numer": number,
        "etykieta_zalozona": status == 200,
        CAUGHT_UP: waited,
    }


def _list_label_by_github(client: Client, facts: Facts) -> object:
    return client.box.labelled_issues(ABSENT_LABEL, include_closed=False, key=client.key)


def _judge_label_by_github(facts: Facts, outcome: object) -> list[str]:
    numbers = _numbers(outcome)
    problems = (
        []
        if numbers is not None and _int(facts, "numer") in numbers
        else [f"wynik {outcome}, oczekiwane issue {facts['numer']}"]
    )
    return problems if facts["etykieta_zalozona"] else [*problems, f"GitHub nie założył etykiety {ABSENT_LABEL}"]


def _prepare_long_open(length: int, label: Label) -> Callable[[SkrzynkaLive, Facts], Facts]:
    def prepare(live: SkrzynkaLive, earlier: Facts) -> Facts:
        return {
            "etykieta": label,
            "tytul": _title(live, f"tresc-{length}"),
            **_long(live, length),
        }

    return prepare


# --- komentarze -----------------------------------------------------------------------------------------------------


def _prepare_comment(
    issue_case: str, length: int | None = None, sign: str = "x"
) -> Callable[[SkrzynkaLive, Facts], Facts]:
    def prepare(live: SkrzynkaLive, earlier: Facts) -> Facts:
        content: Facts = {"tresc": f"{live.marker}\n\nKomentarz.\n"} if length is None else _long(live, length, sign)
        return {"numer": live.number(issue_case), **content}

    return prepare


def _prepare_comment_missing(live: SkrzynkaLive, earlier: Facts) -> Facts:
    return {
        "numer": MISSING_ISSUE,
        "tresc": f"{live.marker}\n\nKomentarz do issue, którego nie ma.\n",
    }


def _comment(client: Client, facts: Facts) -> object:
    return client.box.comment(_int(facts, "numer"), text(facts), key=client.key)


def _judge_commented(facts: Facts, outcome: object) -> list[str]:
    if not isinstance(outcome, Commented):
        return [f"wynik {outcome}, oczekiwane Commented"]
    tail = f"/issues/{facts['numer']}#issuecomment-{outcome.id}"
    return [] if outcome.url.endswith(tail) else [f"adres komentarza {outcome.url} nie kończy się na {tail}"]


def _prepare_edit(length: int | None = None) -> Callable[[SkrzynkaLive, Facts], Facts]:
    def prepare(live: SkrzynkaLive, earlier: Facts) -> Facts:
        commented = live.commented("komentarz")
        content: Facts = (
            {"tresc": f"{live.marker}\n\nKomentarz poprawiony.\n"} if length is None else _long(live, length)
        )
        return {"komentarz": commented.id, "adres": commented.url, **content}

    return prepare


def _prepare_edit_missing(live: SkrzynkaLive, earlier: Facts) -> Facts:
    return {
        "komentarz": MISSING_COMMENT,
        "tresc": f"{live.marker}\n\nPoprawka komentarza, którego nie ma.\n",
    }


def _edit(client: Client, facts: Facts) -> object:
    return client.box.edit_comment(_int(facts, "komentarz"), text(facts), key=client.key)


def _judge_edited(facts: Facts, outcome: object) -> list[str]:
    return _expect(outcome, Commented(_int(facts, "komentarz"), str(facts["adres"])))


def _prepare_comments(live: SkrzynkaLive, earlier: Facts) -> Facts:
    commented = live.commented("komentarz")
    edited, _ = live.earlier["poprawka"]
    return {
        "numer": live.number("zalozenie"),
        "komentarz": commented.id,
        "adres": commented.url,
        "tresc": text(edited),
    }


def _comments(client: Client, facts: Facts) -> object:
    return client.box.comments(_int(facts, "numer"), key=client.key)


def _judge_comments(facts: Facts, outcome: object) -> list[str]:
    return _expect(
        outcome,
        (Comment(_int(facts, "komentarz"), str(facts["adres"]), str(facts["tresc"])),),
    )


def _prepare_comment_pages(live: SkrzynkaLive, earlier: Facts) -> Facts:
    number = live.open("logi-uruchomienia", _title(live, "strony-komentarzy"), f"{live.marker}\n")
    ids = [live.comment(number, f"{live.marker}\n\nKomentarz {index}.\n") for index in range(1, PAGE + 2)]
    return {"numer": number, "komentarze": ids}


def _judge_comment_pages(facts: Facts, outcome: object) -> list[str]:
    if not isinstance(outcome, tuple):
        return [f"wynik {outcome}, oczekiwane {PAGE + 1} komentarzy"]
    found = [comment.id for comment in outcome if isinstance(comment, Comment)]
    expected = cast(list[int], facts["komentarze"])
    return (
        []
        if found == expected
        else [f"komentarze {len(found)} (pierwszy {found[:1]}), oczekiwane {len(expected)} w kolejności dodania"]
    )


def _prepare_comments_missing(live: SkrzynkaLive, earlier: Facts) -> Facts:
    return {"numer": MISSING_ISSUE}


# --- issue z etykietą -----------------------------------------------------------------------------------------------


def _prepare_issue_pages(live: SkrzynkaLive, earlier: Facts) -> Facts:
    numbers = [
        live.open(
            "kontrola-ilosci",
            _title(live, f"strony-issue-{index}"),
            f"{live.marker}\n\nIssue {index}.\n",
        )
        for index in range(1, PAGE + 2)
    ]
    return {
        "numery": numbers,
        CAUGHT_UP: live.settle("kontrola-ilosci", "open", set(numbers)),
    }


def _issue_pages(client: Client, facts: Facts) -> object:
    return client.box.labelled_issues("kontrola-ilosci", include_closed=False, key=client.key)


def _judge_issue_pages(facts: Facts, outcome: object) -> list[str]:
    numbers = _numbers(outcome)
    expected = cast(list[int], facts["numery"])
    if numbers is None:
        return [f"wynik {outcome}, oczekiwane {len(expected)} issue"]
    return (
        []
        if sorted(numbers) == sorted(expected)
        else [f"{len(numbers)} issue, oczekiwane dokładnie {len(expected)} założonych"]
    )


def _prepare_closed(live: SkrzynkaLive, earlier: Facts) -> Facts:
    opened, _ = earlier_case(live, "zalozenie")
    closed_from = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(seconds=5)
    numbers: Facts = {}
    for name, reason, body in (
        (
            "nie_planowane",
            "not_planned",
            f"{live.marker}\n\n{fingerprint_line(FINGERPRINT)}\n",
        ),
        ("zrobione", "completed", f"{live.marker}\n\nBez odcisku.\n"),
    ):
        number = live.open("zgloszenie", _title(live, f"zamkniete-{reason}"), body)
        status, _ = live.admin.request(
            "PATCH",
            f"/repos/{TRIAL}/issues/{number}",
            {"state": "closed", "state_reason": reason},
        )
        if status != 200:
            raise RuntimeError(f"przygotowanie: zamknięcie issue {number} ({reason}) dało {status}")
        numbers[name] = number
    every = {
        live.number("zalozenie"),
        *(int(cast(int, number)) for number in numbers.values()),
    }
    live.settle("zgloszenie", "open", {live.number("zalozenie")}, exact=True)
    return {
        "otwarte": live.number("zalozenie"),
        "tresc_otwartego": text(opened),
        CAUGHT_UP: live.settle("zgloszenie", "all", every),
        **numbers,
        "zamknieto_od": closed_from.isoformat(),
    }


def earlier_case(live: SkrzynkaLive, case: str) -> tuple[Facts, object]:
    return live.earlier[case]


def _closed(client: Client, facts: Facts) -> object:
    only_open = client.box.labelled_issues("zgloszenie", include_closed=False, key=client.key)
    every = client.box.labelled_issues("zgloszenie", include_closed=True, key=client.key)
    return (only_open, every)


def _judge_closed(facts: Facts, outcome: object) -> list[str]:
    only_open, every = cast(tuple[object, object], outcome)
    opened, not_planned, done = (
        _int(facts, "otwarte"),
        _int(facts, "nie_planowane"),
        _int(facts, "zrobione"),
    )
    problems = _expect(only_open, (Issue(opened, str(facts["tresc_otwartego"])),))
    if not isinstance(every, tuple) or sorted(_numbers(every) or []) != sorted([opened, not_planned, done]):
        return [
            *problems,
            f"z zamkniętymi: {every}, oczekiwane issue {opened}, {not_planned} i {done}",
        ]
    since = datetime.fromisoformat(str(facts["zamknieto_od"]))
    for issue in every:
        reason = {opened: None, not_planned: "not_planned", done: "completed"}[issue.number]
        closure = issue.closure
        if reason is None and closure is not None:
            problems.append(f"otwarte issue {issue.number} ma zamknięcie {closure}")
        if reason is not None and not (
            isinstance(closure, Closure) and closure.reason == reason and closure.at is not None and closure.at >= since
        ):
            problems.append(f"issue {issue.number}: zamknięcie {closure}, oczekiwane {reason} od {since.isoformat()}")
    return problems


def _prepare_find(live: SkrzynkaLive, earlier: Facts) -> Facts:
    closed, _ = earlier_case(live, "lista-zamkniete")
    return {"otwarte": live.number("zalozenie"), "zamkniete": closed["nie_planowane"]}


def _find(client: Client, facts: Facts) -> object:
    keyed = KeyedBox(client.box, lambda: client.key, clock=time.monotonic)
    line = fingerprint_line(FINGERPRINT)
    return (
        keyed.find_issue("zgloszenie", line, include_closed=False),
        keyed.find_issue("zgloszenie", line, include_closed=True),
    )


def _judge_find(facts: Facts, outcome: object) -> list[str]:
    return _expect(outcome, (_int(facts, "otwarte"), _int(facts, "zamkniete")))


# --- Archiwum okresu -----------------------------------------------------------------------------------------------


def archive_tag(run: str) -> str:
    """Tag Archiwum runu: jak tag Archiwum okresu (``logi-<okres>``), z identyfikatorem runu, po którym sprząta."""

    return f"logi-verify-{run}"


def _prepare_archive(live: SkrzynkaLive, earlier: Facts) -> Facts:
    status, releases = live.admin.request("GET", f"/repos/{TRIAL}/releases?per_page=100")
    if status != 200 or releases != []:
        raise RuntimeError(f"brak warunku: repozytorium próbne ma Release albo lista dała {status}")
    status, _ = live.admin.request("GET", f"/repos/{TRIAL}/commits?per_page=1")
    if status != 409:
        raise RuntimeError(f"brak warunku: repozytorium próbne ma commit (lista commitów {status}, puste daje 409)")
    return {
        "tag": archive_tag(live.run),
        "tytul": f"verify-github-skrzynki {live.run}: Archiwum",
        "tresc": f"{live.marker}\n\nArchiwum okresu w repozytorium bez commitu.\n",
    }


def _archive(client: Client, facts: Facts) -> object:
    return client.box.archive(str(facts["tag"]), key=client.key)


def _open_archive(client: Client, facts: Facts) -> object:
    opened = client.box.open_archive(str(facts["tag"]), str(facts["tytul"]), str(facts["tresc"]), key=client.key)
    return (opened, client.box.archive(str(facts["tag"]), key=client.key))


# --- klucz ----------------------------------------------------------------------------------------------------------


def _no_facts(live: SkrzynkaLive, earlier: Facts) -> Facts:
    return {}


def _judge_key(client: Client, facts: Facts) -> object:
    return KeyedBox(client.box, lambda: client.key, clock=time.monotonic).judge(wait_s=30)


def _prepare_bad_key(live: SkrzynkaLive, earlier: Facts) -> Facts:
    commented = live.commented("komentarz")
    return {
        "numer": live.number("zalozenie"),
        "komentarz": commented.id,
        "tresc": f"{live.marker}\n\nZły klucz.\n",
        "tag": archive_tag(live.run),
    }


def _bad_key(client: Client, facts: Facts) -> object:
    box, number, body = client.box, _int(facts, "numer"), str(facts["tresc"])
    title = "verify-github-skrzynki: zły klucz"
    return {
        "open_issue": box.open_issue("zgloszenie", title, body, key=BAD_KEY),
        "comment": box.comment(number, body, key=BAD_KEY),
        "edit_comment": box.edit_comment(_int(facts, "komentarz"), body, key=BAD_KEY),
        "comments": box.comments(number, key=BAD_KEY),
        "labelled_issues": box.labelled_issues("zgloszenie", include_closed=False, key=BAD_KEY),
        "KeyedBox.judge": KeyedBox(box, lambda: BAD_KEY, clock=time.monotonic).judge(wait_s=30),
        "archive": box.archive(str(facts["tag"]), key=BAD_KEY),
        "open_archive": box.open_archive(str(facts["tag"]), title, body, key=BAD_KEY),
        "upload": box.upload(MISSING_ARCHIVE, "plik.json.gz", "plik", b"\x1f\x8b", key=BAD_KEY),
        "remove": box.remove(MISSING_ASSET, key=BAD_KEY),
    }


def _judge_bad_key(facts: Facts, outcome: object) -> list[str]:
    expected: dict[str, object] = {
        name: Refused()
        for name in (
            "open_issue",
            "comment",
            "edit_comment",
            "comments",
            "labelled_issues",
            "archive",
            "open_archive",
            "upload",
            "remove",
        )
    }
    expected["KeyedBox.judge"] = "refused"
    found = cast(dict[str, object], outcome)
    return [
        f"{name}: wynik {found.get(name)}, oczekiwane {value}"
        for name, value in expected.items()
        if found.get(name) != value
    ]


# --- usunięte issue -------------------------------------------------------------------------------------------------


def _prepare_deleted(live: SkrzynkaLive, earlier: Facts) -> Facts:
    number = live.open(
        "logi-uruchomienia",
        _title(live, "usuniete"),
        f"{live.marker}\n\nIssue, które Maks usunie.\n",
    )
    comment_id = live.comment(number, f"{live.marker}\n\nKomentarz usuniętego issue.\n")
    status, issue = live.admin.request("GET", f"/repos/{TRIAL}/issues/{number}")
    node = issue.get("node_id") if isinstance(issue, dict) else None
    body = issue.get("body") if isinstance(issue, dict) else None
    if status != 200 or not isinstance(node, str) or live.marker not in str(body):
        raise RuntimeError(f"przygotowanie: issue {number} do usunięcia dało {status}")
    status, answer = live.admin.delete_issue(node)
    if status != 200 or (isinstance(answer, dict) and answer.get("errors")):
        raise RuntimeError(f"przygotowanie: usunięcie issue {number} dało {status} {answer}")
    return {
        "numer": number,
        "komentarz": comment_id,
        "tresc": f"{live.marker}\n\nKomentarz po usunięciu.\n",
    }


def _deleted(client: Client, facts: Facts) -> object:
    box, number, body = client.box, _int(facts, "numer"), str(facts["tresc"])
    return {
        "comment": box.comment(number, body, key=client.key),
        "comments": box.comments(number, key=client.key),
        "edit_comment": box.edit_comment(_int(facts, "komentarz"), body, key=client.key),
    }


def _judge_deleted(facts: Facts, outcome: object) -> list[str]:
    found = cast(dict[str, object], outcome)
    return [
        f"{name}: wynik {found.get(name)}, oczekiwane Refused()"
        for name in ("comment", "comments", "edit_comment")
        if found.get(name) != Refused()
    ]


REFUSED: Final = "Refused: Skrzynka odmówiła (report_box.Refused)"
REJECTED: Final = "Rejected: Skrzynka odmówiła tej treści (report_box.Rejected)"
LIMIT_SOURCE: Final = "report_box.COMMENT_LIMIT (pomiar #332: 65 536 znaków przechodzi, 65 537 dostaje 422)"


def _is(expected: object) -> Callable[[Facts, object], list[str]]:
    return lambda facts, outcome: _expect(outcome, expected)


CASES: Final[tuple[Case[SkrzynkaLive, Client], ...]] = (
    Case(
        "zalozenie",
        "Sent z numerem",
        "report_box: „Nowe issue to Sent z numerem”",
        _prepare_open,
        _open,
        lambda f, o: _sent(o),
    ),
    Case(
        "lista-bez-etykiety",
        "pusta krotka: issue z etykietą, której repozytorium nie ma, nie ma",
        "report_box.labelled_issues: issue z etykietą; Refused tylko przy kluczu (ADR 0007)",
        _prepare_absent_label,
        _list_absent,
        _is(()),
    ),
    Case(
        "zalozenie-bez-etykiety-w-repo",
        "Sent z numerem",
        "report_box: „Nowe issue to Sent z numerem”; etykiet kod nie zakłada",
        _prepare_open_absent,
        _open,
        lambda f, o: _sent(o),
    ),
    Case(
        "etykieta-z-githuba",
        "issue założone z etykietą, której repozytorium nie miało, jest w liście z tą etykietą",
        "kolejka szuka issue po etykiecie (ADR 0007); bez etykiety Centrum nie znajdzie Zgłoszenia",
        _prepare_label_by_github,
        _list_label_by_github,
        _judge_label_by_github,
    ),
    Case(
        "zalozenie-na-limicie",
        f"Sent: treść {COMMENT_LIMIT} znaków",
        LIMIT_SOURCE,
        _prepare_long_open(COMMENT_LIMIT, "logi-uruchomienia"),
        _open,
        lambda f, o: _sent(o),
    ),
    Case(
        "zalozenie-ponad-limit",
        REJECTED,
        LIMIT_SOURCE,
        _prepare_long_open(COMMENT_LIMIT + 1, "logi-uruchomienia"),
        _open,
        _is(Rejected()),
    ),
    Case(
        "komentarz",
        "Commented z id i adresem …/issues/<numer>#issuecomment-<id>",
        "report_box: „komentarz … Commented z identyfikatorem i adresem”",
        _prepare_comment("zalozenie"),
        _comment,
        _judge_commented,
    ),
    Case(
        "komentarz-na-limicie",
        f"Commented: {COMMENT_LIMIT} znaków po 4 bajty UTF-8",
        LIMIT_SOURCE + ": komentarz do 262 144 bajtów",
        _prepare_comment("zalozenie-na-limicie", COMMENT_LIMIT, "\U0001f600"),
        _comment,
        _judge_commented,
    ),
    Case(
        "komentarz-na-limicie-bajtow",
        f"Commented: {COMMENT_BYTES} bajtów",
        LIMIT_SOURCE + ": komentarz do 262 144 bajtów",
        _prepare_comment("zalozenie-na-limicie", COMMENT_BYTES),
        _comment,
        _judge_commented,
    ),
    Case(
        "komentarz-ponad-limit",
        REJECTED + f": ponad {COMMENT_BYTES} bajtów",
        LIMIT_SOURCE + ": komentarz do 262 144 bajtów",
        _prepare_comment("zalozenie-na-limicie", COMMENT_BYTES + 1),
        _comment,
        _is(Rejected()),
    ),
    Case(
        "komentarz-brak-issue",
        REFUSED,
        "keyed_box: odmowa komentarza mówi o issue (404), ADR 0007",
        _prepare_comment_missing,
        _comment,
        _is(Refused()),
    ),
    Case(
        "poprawka",
        "Commented z tym samym id i adresem",
        "report_box: „komentarz i jego poprawka (edit_comment) Commented z identyfikatorem i adresem”",
        _prepare_edit(),
        _edit,
        _judge_edited,
    ),
    Case(
        "poprawka-brak-komentarza",
        REFUSED,
        "keyed_box: odmowa poprawki komentarza mówi o issue, nie o kluczu",
        _prepare_edit_missing,
        _edit,
        _is(Refused()),
    ),
    Case(
        "poprawka-ponad-limit",
        REJECTED + f": ponad {COMMENT_BYTES} bajtów",
        LIMIT_SOURCE + ": komentarz do 262 144 bajtów",
        _prepare_edit(COMMENT_BYTES + 1),
        _edit,
        _is(Rejected()),
    ),
    Case(
        "komentarze",
        "komentarze issue po kolei z treścią po poprawce",
        "report_box: „pytanie o komentarze issue (comments) daje je po kolei z treścią”",
        _prepare_comments,
        _comments,
        _judge_comments,
    ),
    Case(
        "komentarze-strony",
        f"wszystkie {PAGE + 1} komentarzy w kolejności dodania",
        "report_box.comments: „Komentarze issue strona po stronie”",
        _prepare_comment_pages,
        _comments,
        _judge_comment_pages,
    ),
    Case(
        "komentarze-brak-issue",
        REFUSED,
        "keyed_box: odmowa pytania o komentarze mówi o issue (404, #402)",
        _prepare_comments_missing,
        _comments,
        _is(Refused()),
    ),
    Case(
        "lista-strony",
        f"dokładnie {PAGE + 1} założonych issue z etykietą",
        "report_box.labelled_issues: „Issue z etykietą strona po stronie”",
        _prepare_issue_pages,
        _issue_pages,
        _judge_issue_pages,
    ),
    Case(
        "lista-zamkniete",
        "bez include_closed tylko otwarte; z include_closed także zamknięte z powodem i czasem",
        "report_box: „labelled_issues daje ich numery, treści i zamknięcie (powód i czas)”",
        _prepare_closed,
        _closed,
        _judge_closed,
    ),
    Case(
        "szukanie-odcisku",
        "otwarte Zgłoszenie z odciskiem; z zamkniętymi najnowsze z odciskiem",
        "report_box.newest_with_line, ADR 0007: jedno otwarte Zgłoszenie na problem",
        _prepare_find,
        _find,
        _judge_find,
    ),
    Case(
        "klucz-przyjety",
        "accepted",
        "keyed_box: każda inna odpowiedź Skrzynki to „klucz przyjęty”",
        _no_facts,
        _judge_key,
        _is("accepted"),
    ),
    Case(
        "archiwum-brak",
        "None: w Skrzynce nie ma Archiwum z tym tagiem",
        "report_box: „archive znajduje je po tagu z jego plikami … albo daje None”",
        _prepare_archive,
        _archive,
        _is(None),
    ),
    Case(
        "archiwum-w-pustym-repo",
        "Rejected, a Archiwum dalej nie ma (None)",
        "report_box: „repozytorium bez commitu odmawia założenia Archiwum (422 albo 409, Rejected)”",
        _prepare_archive,
        _open_archive,
        _is((Rejected(), None)),
    ),
    Case(
        "zly-klucz",
        "Refused w każdej operacji, KeyedBox: refused",
        "report_box.Refused: klucz nieważny; ADR 0007: odmowa przy liście odrzuca klucz",
        _prepare_bad_key,
        _bad_key,
        _judge_bad_key,
    ),
    Case(
        "usuniete-issue",
        "Refused przy komentarzu, komentarzach i poprawce komentarza usuniętego issue",
        "ADR 0007: „Odmowy komentarza werdykt nie liczy, bo to 404 issue, które Maks usunął”; keyed_box (#402)",
        _prepare_deleted,
        _deleted,
        _judge_deleted,
    ),
)

# Czego przebieg nie sprawdza i dlaczego; zawsze w wyniku jako NIESPRAWDZONE.
UNCHECKED: Final = (
    (
        "poprawka-cudzego",
        "poprawka komentarza innego konta: repozytorium próbne ma jedno konto (MAXIMISEART-AI)",
    ),
    (
        "limit-zapytan",
        "403/429 limitu zapytań: wywołanie go wyczerpałoby limit konta Maksa",
    ),
)


def describe(outcome: object) -> str:
    if isinstance(outcome, tuple) and all(isinstance(item, Issue) for item in outcome) and len(outcome) > 3:
        return f"({len(outcome)} issue)"
    if isinstance(outcome, tuple) and all(isinstance(item, Comment) for item in outcome) and len(outcome) > 3:
        return f"({len(outcome)} komentarzy)"
    if isinstance(outcome, tuple) and all(isinstance(item, Issue) for item in outcome):
        return "(" + ", ".join(f"Issue({i.number}, zamknięcie={i.closure})" for i in outcome) + ")"
    if isinstance(outcome, tuple) and all(isinstance(item, Comment) for item in outcome):
        return "(" + ", ".join(f"Comment({c.id})" for c in outcome) + ")"
    if isinstance(outcome, tuple):
        return "(" + ", ".join(describe(item) for item in outcome) + ")"
    if isinstance(outcome, dict):
        return "{" + ", ".join(f"{name}: {describe(value)}" for name, value in outcome.items()) + "}"
    return repr(outcome)


def created(outcome: object) -> list[int]:
    """Numery issue, które wynik mówi, że założył (do rejestru sprzątania)."""

    if isinstance(outcome, Sent):
        return [outcome.number]
    if isinstance(outcome, tuple | list):
        return [number for item in outcome for number in created(item)]
    if isinstance(outcome, dict):
        return [number for item in outcome.values() for number in created(item)]
    return []
