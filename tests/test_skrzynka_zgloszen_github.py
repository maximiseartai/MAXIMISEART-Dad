"""Skrzynka Zgłoszeń na GitHubie: odpowiedzi REST zamienione na wyniki skrzynki, z podstawionym transportem HTTP.

Żaden test nie łączy się z prawdziwym GitHubem. Nagrania prawdziwego GitHuba skilla ``verify-github-skrzynki``
odtwarzają się tak samo na każdej maszynie, choć bajty gzipu ``ArchiveFile.packed`` zależą od Pythona i zlib.
"""

from __future__ import annotations

import gzip
import http.client
import itertools
import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from rozliczenia.centrum.github import HttpRequest, HttpResponse, headers
from rozliczenia.centrum.report_box import (
    Archive,
    Asset,
    Closure,
    Comment,
    CommentOutcome,
    CommentsOutcome,
    Commented,
    FindOutcome,
    GitHubReportBox,
    Issue,
    IssuesOutcome,
    Label,
    Refused,
    Rejected,
    Removed,
    SendOutcome,
    Sent,
    Unreachable,
)
from rozliczenia.centrum.keyed_box import KeyedBox, NoKey
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.outbox import ArchiveFile, Outbox, PeriodThread, Post
from rozliczenia.centrum.report_issue import fingerprint_line
from rozliczenia.centrum.reports import report_target
from rozliczenia.centrum import report_box
from rozliczenia.client_data import logs_text, tool

from tests.fixtures.clock import ManualClock
from tests.fixtures.potomne import wait_for
from tests.fixtures.github_api import Answer, github_api
from tests.fixtures.proxy_systemu import system_proxy
from atrapy.sluchacz_kolejki import QueueListener

import github_przypadki_archiwum
import github_skrzynki
import github_wymiana

SKILL = Path(__file__).resolve().parents[1] / ".agents" / "skills" / "verify-github-skrzynki"

TITLE = "BRAK_WZORCA: Nie znaleziono wzorca."
BODY = "## Komunikat\n"
FINGERPRINT = "0123456789abcdef"
KEY = "github_pat_SYNTETYCZNY"
# Prawdziwy transport Skrzynki z chwili importu: autouse ``bez_skrzynki_zgloszen_na_githubie`` (``tests/conftest.py``)
# podmienia ``urllib_transport`` w module.
SKRZYNKA_TRANSPORT = report_box.urllib_transport


@dataclass
class ScriptedTransport:
    """Transport HTTP, który zapisuje żądania i odpowiada przygotowaną odpowiedzią albo brakiem sieci."""

    answer: Callable[[], HttpResponse]
    requests: list[HttpRequest] = field(default_factory=list)

    def __call__(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        return self.answer()


def send_with(
    answer: Callable[[], HttpResponse], label: Label = "zgloszenie"
) -> tuple[SendOutcome, ScriptedTransport]:
    transport = ScriptedTransport(answer)
    return GitHubReportBox(transport=transport).open_issue(label, TITLE, BODY, key=KEY), transport


def no_network() -> HttpResponse:
    raise OSError("brak sieci")


def cut_off() -> HttpResponse:
    raise http.client.IncompleteRead(b"{")


def test_utworzone_issue_to_wyslane_zgloszenie_z_numerem() -> None:
    outcome, transport = send_with(lambda: HttpResponse(201, json.dumps({"number": 42, "title": "x"}).encode()))

    assert outcome == Sent(42)
    [request] = transport.requests
    assert (request.method, request.url) == (
        "POST",
        "https://api.github.com/repos/MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia/issues",
    )
    assert request.headers["Authorization"] == f"Bearer {KEY}"
    assert request.body is not None
    assert json.loads(request.body) == {"title": TITLE, "body": BODY, "labels": ["zgloszenie"]}
    assert KEY not in repr(request)


def test_skrzynka_pyta_github_naglowkami_api_rest_z_wersja_api_i_kluczem_taty() -> None:
    # Nagłówki z dokumentacji REST API GitHuba: typ odpowiedzi, wersja API, obowiązkowy User-Agent i klucz.
    _, transport = send_with(lambda: HttpResponse(201, json.dumps({"number": 42}).encode()))

    [request] = transport.requests
    assert {name: request.headers[name] for name in ("Accept", "X-GitHub-Api-Version", "User-Agent", "Authorization")} == {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "centrum-rozliczen",
        "Authorization": f"Bearer {KEY}",
    }


def test_skrzynka_laczy_sie_z_githubem_przez_proxy_z_ustawien_systemu(monkeypatch: pytest.MonkeyPatch) -> None:
    with system_proxy(monkeypatch) as proxied:
        outcome = GitHubReportBox(transport=SKRZYNKA_TRANSPORT).labelled_issues("zgloszenie", include_closed=False, key=KEY)

    assert outcome == Unreachable()
    assert proxied == ["CONNECT api.github.com:443"]


@pytest.mark.parametrize("same_server_hops", [0, 1], ids=["wprost", "po-przekierowaniu-na-tym-samym-serwerze"])
def test_klucz_taty_nie_idzie_za_przekierowaniem_skrzynki_na_inny_serwer(same_server_hops: int) -> None:
    # Serwer pod innym portem to inny origin, jak inny host: klucz taty tam nie idzie, także gdy wcześniej przeszedł
    # przekierowanie na tym samym serwerze.
    with github_api({"/lista": Answer(body=[])}) as elsewhere, github_api({}) as box:
        box.answers = {
            **{f"/{hop}": Answer(302, headers={"Location": f"{box.url}/{hop + 1}"}) for hop in range(same_server_hops)},
            f"/{same_server_hops}": Answer(301, headers={"Location": f"{elsewhere.url}/lista"}),
        }
        answer = SKRZYNKA_TRANSPORT(HttpRequest("GET", f"{box.url}/0", headers(KEY), None))

    assert answer.status == 200
    assert [asked.authorization for asked in box.asked] == [f"Bearer {KEY}"] * (same_server_hops + 1)
    assert [asked.authorization for asked in elsewhere.asked] == [None]


def test_przekierowanie_skrzynki_na_adres_z_nieczytelnym_portem_to_skrzynka_nieosiagalna(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Z takim adresem urllib się nie połączy, więc Skrzynka czeka jak bez sieci i ponawia później.
    listed = f"/repos/{report_box.REPOSITORY}/issues?state=open&labels=zgloszenie&per_page=100&page=1"
    with github_api({listed: Answer(301, headers={"Location": "http://127.0.0.1:abc/lista"})}) as box:
        monkeypatch.setattr(report_box, "API", box.url)
        outcome = GitHubReportBox(transport=SKRZYNKA_TRANSPORT).labelled_issues("zgloszenie", include_closed=False, key=KEY)

    assert outcome == Unreachable()
    assert [asked.path for asked in box.asked] == [listed]


def test_przeniesione_repozytorium_zgloszen_odpowiada_skrzynce_z_kluczem_taty_pod_adresem_przekierowania(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GitHub przekierowuje przeniesione albo przemianowane repozytorium (301) na ``/repositories/<id>/…`` tego samego
    hosta, a prywatne repozytorium Zgłoszeń bez klucza odpowiada 404, czyli odmową Skrzynki."""

    listed = "issues?state=open&labels=zgloszenie&per_page=100&page=1"
    with github_api({f"/repositories/1/{listed}": Answer(body=[])}, private=True) as box:
        moved = Answer(301, headers={"Location": f"{box.url}/repositories/1/{listed}"})
        box.answers = {**box.answers, f"/repos/{report_box.REPOSITORY}/{listed}": moved}
        monkeypatch.setattr(report_box, "API", box.url)
        outcome = GitHubReportBox(transport=SKRZYNKA_TRANSPORT).labelled_issues("zgloszenie", include_closed=False, key=KEY)

    assert outcome == ()
    assert [asked.authorization for asked in box.asked] == [f"Bearer {KEY}"] * 2


@pytest.mark.parametrize("label", ["kontrola-ilosci", "logi-uruchomienia"])
def test_issue_dostaje_etykiete_swojego_rodzaju(label: Label) -> None:
    outcome, transport = send_with(lambda: HttpResponse(201, json.dumps({"number": 7}).encode()), label)

    assert outcome == Sent(7)
    [request] = transport.requests
    assert request.body is not None
    assert json.loads(request.body)["labels"] == [label]


@pytest.mark.parametrize("status", [401, 403, 404])
def test_odmowa_autoryzacji_to_odmowa_skrzynki(status: int) -> None:
    outcome, _ = send_with(lambda: HttpResponse(status, b'{"message": "Bad credentials"}'))

    assert outcome == Refused()


@pytest.mark.parametrize(
    "answer",
    [
        no_network,
        cut_off,
        lambda: HttpResponse(502, b"<html>Bad gateway</html>"),
        lambda: HttpResponse(201, b"to nie jest JSON"),
    ],
    ids=["brak-sieci", "urwana-odpowiedz", "awaria-githuba", "nieczytelna-odpowiedz"],
)
def test_brak_sieci_albo_niezwykla_odpowiedz_to_skrzynka_nieosiagalna(answer: Callable[[], HttpResponse]) -> None:
    outcome, _ = send_with(answer)

    assert outcome == Unreachable()


ISSUES = "https://api.github.com/repos/MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia/issues"
OTHER_FINGERPRINT = "fedcba9876543210"


def issue(number: int, fingerprint: str) -> dict[str, object]:
    return {"number": number, "body": f"## Narzędzie\n\n- Odcisk problemu: {fingerprint}\n- Commit: abc\n"}


def pages(*answers: list[dict[str, object]]) -> Callable[[], HttpResponse]:
    remaining: Iterator[list[dict[str, object]]] = iter(answers)
    return lambda: HttpResponse(200, json.dumps(next(remaining)).encode())


def issues_with(
    answer: Callable[[], HttpResponse], *, include_closed: bool = False
) -> tuple[IssuesOutcome, ScriptedTransport]:
    transport = ScriptedTransport(answer)
    box = GitHubReportBox(transport=transport)
    return box.labelled_issues("kontrola-ilosci", include_closed=include_closed, key=KEY), transport


def test_otwarte_issue_z_etykieta_to_ich_numery_i_tresci() -> None:
    outcome, transport = issues_with(
        pages([{"number": 3, "body": "a\r\nb", "state": "open"}, {"number": 8, "body": None}, {"body": "bez numeru"}])
    )

    assert outcome == (Issue(3, "a\r\nb"), Issue(8, ""))
    [request] = transport.requests
    assert (request.method, request.url, request.body) == (
        "GET",
        f"{ISSUES}?state=open&labels=kontrola-ilosci&per_page=100&page=1",
        None,
    )
    assert request.headers["Authorization"] == f"Bearer {KEY}"


def test_z_zamknietymi_to_wszystkie_issue_z_etykieta() -> None:
    _, transport = issues_with(pages([]), include_closed=True)

    [request] = transport.requests
    assert request.url == f"{ISSUES}?state=all&labels=kontrola-ilosci&per_page=100&page=1"


def test_issue_z_etykieta_sa_zbierane_ze_wszystkich_stron() -> None:
    full_page = [{"number": number, "body": ""} for number in range(200, 100, -1)]

    outcome, transport = issues_with(pages(full_page, [{"number": 5, "body": "ostatnie"}]))

    assert isinstance(outcome, tuple)
    assert [found.number for found in outcome] == [*range(200, 100, -1), 5]
    assert [request.url.rsplit("=", 1)[1] for request in transport.requests] == ["1", "2"]


@pytest.mark.parametrize("status", [401, 403, 404])
def test_odmowa_autoryzacji_przy_szukaniu_to_odmowa_skrzynki(status: int) -> None:
    outcome, _ = issues_with(lambda: HttpResponse(status, b'{"message": "Bad credentials"}'))

    assert outcome == Refused()


@pytest.mark.parametrize(
    "answer",
    [
        no_network,
        cut_off,
        lambda: HttpResponse(502, b"<html>Bad gateway</html>"),
        lambda: HttpResponse(200, b'{"message": "to nie jest lista"}'),
    ],
    ids=["brak-sieci", "urwana-odpowiedz", "awaria-githuba", "nieczytelna-odpowiedz"],
)
def test_brak_sieci_albo_niezwykla_odpowiedz_przy_szukaniu_to_skrzynka_nieosiagalna(
    answer: Callable[[], HttpResponse],
) -> None:
    outcome, _ = issues_with(answer)

    assert outcome == Unreachable()


def test_brak_sieci_na_drugiej_stronie_to_skrzynka_nieosiagalna() -> None:
    full_page = [issue(number, OTHER_FINGERPRINT) for number in range(100, 200)]
    answers = iter([lambda: HttpResponse(200, json.dumps(full_page).encode()), no_network])

    outcome, _ = issues_with(lambda: next(answers)())

    assert outcome == Unreachable()


def find_with(answer: Callable[[], HttpResponse]) -> tuple[FindOutcome | NoKey, ScriptedTransport]:
    transport = ScriptedTransport(answer)
    box = KeyedBox(GitHubReportBox(transport=transport), lambda: KEY, clock=ManualClock())
    return box.find_issue("zgloszenie", fingerprint_line(FINGERPRINT), include_closed=False), transport


def test_otwarte_issue_z_odciskiem_problemu_to_znalezione_zgloszenie() -> None:
    outcome, transport = find_with(
        pages([issue(3, OTHER_FINGERPRINT), issue(7, FINGERPRINT), {"number": 8, "body": None}])
    )

    assert outcome == 7
    [request] = transport.requests
    assert request.url == f"{ISSUES}?state=open&labels=zgloszenie&per_page=100&page=1"


def test_z_kilku_issue_z_wierszem_wygrywa_najnowsze() -> None:
    outcome, _ = find_with(pages([issue(4, FINGERPRINT), issue(9, FINGERPRINT), issue(6, FINGERPRINT)]))

    assert outcome == 9


def test_wiersz_musi_byc_caly_a_nie_poczatkiem_innego() -> None:
    prefixed = {"number": 4, "body": f"x {fingerprint_line(FINGERPRINT)}"}

    outcome, _ = find_with(pages([issue(3, FINGERPRINT + "0"), prefixed]))

    assert outcome is None


def test_bez_otwartego_issue_z_odciskiem_nie_ma_zgloszenia_takze_po_przejrzeniu_kolejnych_stron() -> None:
    full_page = [issue(number, OTHER_FINGERPRINT) for number in range(100, 200)]
    outcome, transport = find_with(pages(full_page, [issue(5, OTHER_FINGERPRINT)]))

    assert outcome is None
    assert [request.url.rsplit("=", 1)[1] for request in transport.requests] == ["1", "2"]


def test_otwarte_issue_z_odciskiem_na_drugiej_stronie_to_znalezione_zgloszenie() -> None:
    full_page = [issue(number, OTHER_FINGERPRINT) for number in range(100, 200)]
    outcome, _ = find_with(pages(full_page, [issue(42, FINGERPRINT)]))

    assert outcome == 42


@pytest.mark.parametrize(
    ("answer", "expected"),
    [(lambda: HttpResponse(401, b"{}"), Refused()), (no_network, Unreachable())],
    ids=["odmowa", "brak-sieci"],
)
def test_porazka_skrzynki_przy_szukaniu_wiersza_to_ta_sama_porazka(
    answer: Callable[[], HttpResponse], expected: Refused | Unreachable
) -> None:
    outcome, _ = find_with(answer)

    assert outcome == expected


CLOSED_AT = "2026-10-20T09:15:00Z"
CLOSED_MOMENT = datetime(2026, 10, 20, 9, 15, tzinfo=timezone.utc)


def test_zamkniete_issue_ma_powod_i_czas_zamkniecia_a_otwarte_nie() -> None:
    def entry(number: int, state: str, reason: object, closed_at: object = CLOSED_AT) -> dict[str, object]:
        return {"number": number, "body": "", "state": state, "state_reason": reason, "closed_at": closed_at}

    outcome, _ = issues_with(
        pages(
            [
                entry(1, "closed", "completed"),
                entry(2, "closed", "not_planned"),
                entry(3, "closed", "duplicate"),
                entry(4, "closed", None),
                entry(5, "closed", "zablokowane"),
                entry(6, "closed", "completed", closed_at="wczoraj"),
                entry(7, "closed", "completed", closed_at="2026-10-20T09:15:00"),
                entry(8, "open", "reopened", closed_at=None),
            ]
        ),
        include_closed=True,
    )

    assert outcome == (
        Issue(1, "", Closure("completed", CLOSED_MOMENT)),
        Issue(2, "", Closure("not_planned", CLOSED_MOMENT)),
        Issue(3, "", Closure("duplicate", CLOSED_MOMENT)),
        Issue(4, "", Closure(None, CLOSED_MOMENT)),
        Issue(5, "", Closure(None, CLOSED_MOMENT)),
        Issue(6, "", Closure("completed", None)),
        Issue(7, "", Closure("completed", None)),
        Issue(8, ""),
    )


COMMENT_URL = "https://github.com/MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia/issues/12#issuecomment-901"


def comment_with(answer: Callable[[], HttpResponse]) -> tuple[CommentOutcome, ScriptedTransport]:
    transport = ScriptedTransport(answer)
    return GitHubReportBox(transport=transport).comment(12, BODY, key=KEY), transport


def test_przyjety_komentarz_ma_identyfikator_i_adres() -> None:
    outcome, transport = comment_with(
        lambda: HttpResponse(201, json.dumps({"id": 901, "html_url": COMMENT_URL, "body": BODY}).encode())
    )

    assert outcome == Commented(901, COMMENT_URL)
    [request] = transport.requests
    assert (request.method, request.url) == ("POST", f"{ISSUES}/12/comments")
    assert request.headers["Authorization"] == f"Bearer {KEY}"
    assert request.body is not None
    assert json.loads(request.body) == {"body": BODY}


@pytest.mark.parametrize("status", [401, 403, 404])
def test_odmowa_przy_komentarzu_to_odmowa_skrzynki(status: int) -> None:
    outcome, _ = comment_with(lambda: HttpResponse(status, b'{"message": "Not Found"}'))

    assert outcome == Refused()


@pytest.mark.parametrize(
    "answer",
    [
        no_network,
        cut_off,
        lambda: HttpResponse(502, b"<html>Bad gateway</html>"),
        lambda: HttpResponse(201, json.dumps({"id": 901}).encode()),
        lambda: HttpResponse(201, json.dumps({"id": "901", "html_url": COMMENT_URL}).encode()),
        lambda: HttpResponse(201, b"[]"),
    ],
    ids=["brak-sieci", "urwana-odpowiedz", "awaria-githuba", "bez-adresu", "id-tekstem", "nie-obiekt"],
)
def test_brak_sieci_albo_niezwykla_odpowiedz_przy_komentarzu_to_skrzynka_nieosiagalna(
    answer: Callable[[], HttpResponse],
) -> None:
    outcome, _ = comment_with(answer)

    assert outcome == Unreachable()


def edit_with(answer: Callable[[], HttpResponse]) -> tuple[CommentOutcome, ScriptedTransport]:
    transport = ScriptedTransport(answer)
    return GitHubReportBox(transport=transport).edit_comment(901, BODY, key=KEY), transport


def test_poprawiony_komentarz_ma_ten_sam_identyfikator_i_adres_a_skrzynka_dostaje_nowa_tresc() -> None:
    outcome, transport = edit_with(
        lambda: HttpResponse(200, json.dumps({"id": 901, "html_url": COMMENT_URL, "body": BODY}).encode())
    )

    assert outcome == Commented(901, COMMENT_URL)
    [request] = transport.requests
    assert (request.method, request.url) == ("PATCH", f"{ISSUES}/comments/901")
    assert request.headers["Authorization"] == f"Bearer {KEY}"
    assert request.body is not None
    assert json.loads(request.body) == {"body": BODY}


@pytest.mark.parametrize("status", [401, 403, 404])
def test_odmowa_przy_poprawce_komentarza_to_odmowa_skrzynki(status: int) -> None:
    outcome, _ = edit_with(lambda: HttpResponse(status, b'{"message": "Not Found"}'))

    assert outcome == Refused()


@pytest.mark.parametrize(
    "answer",
    [
        no_network,
        cut_off,
        lambda: HttpResponse(502, b"<html>Bad gateway</html>"),
        lambda: HttpResponse(201, json.dumps({"id": 901, "html_url": COMMENT_URL}).encode()),
        lambda: HttpResponse(200, json.dumps({"id": 901}).encode()),
    ],
    ids=["brak-sieci", "urwana-odpowiedz", "awaria-githuba", "nie-200", "bez-adresu"],
)
def test_brak_sieci_albo_niezwykla_odpowiedz_przy_poprawce_komentarza_to_skrzynka_nieosiagalna(
    answer: Callable[[], HttpResponse],
) -> None:
    outcome, _ = edit_with(answer)

    assert outcome == Unreachable()


def comments_with(answer: Callable[[], HttpResponse]) -> tuple[CommentsOutcome, ScriptedTransport]:
    transport = ScriptedTransport(answer)
    return GitHubReportBox(transport=transport).comments(12, key=KEY), transport


def test_komentarze_issue_to_ich_identyfikatory_adresy_i_tresci_po_kolei() -> None:
    outcome, transport = comments_with(
        pages(
            [
                {"id": 901, "html_url": COMMENT_URL, "body": "pierwszy\r\n<!-- znacznik -->"},
                {"id": 902, "html_url": f"{COMMENT_URL}2", "body": None},
                {"id": "903", "html_url": COMMENT_URL, "body": "id tekstem"},
                {"id": 904, "body": "bez adresu"},
            ]
        )
    )

    assert outcome == (Comment(901, COMMENT_URL, "pierwszy\r\n<!-- znacznik -->"), Comment(902, f"{COMMENT_URL}2", ""))
    [request] = transport.requests
    assert (request.method, request.url, request.body) == ("GET", f"{ISSUES}/12/comments?per_page=100&page=1", None)
    assert request.headers["Authorization"] == f"Bearer {KEY}"


def test_komentarze_issue_sa_zbierane_ze_wszystkich_stron() -> None:
    full_page = [{"id": number, "html_url": f"{COMMENT_URL}{number}", "body": ""} for number in range(1, 101)]

    outcome, transport = comments_with(pages(full_page, [{"id": 101, "html_url": COMMENT_URL, "body": "ostatni"}]))

    assert isinstance(outcome, tuple)
    assert [found.id for found in outcome] == list(range(1, 102))
    assert [request.url for request in transport.requests] == [
        f"{ISSUES}/12/comments?per_page=100&page={page}" for page in (1, 2)
    ]


@pytest.mark.parametrize(
    ("answers", "expected"),
    [
        ((lambda: HttpResponse(404, b'{"message": "Not Found"}'),), Refused()),
        ((lambda: HttpResponse(200, b'{"message": "to nie jest lista"}'),), Unreachable()),
        (
            (
                lambda: HttpResponse(200, json.dumps([{"id": n, "html_url": COMMENT_URL} for n in range(100)]).encode()),
                no_network,
            ),
            Unreachable(),
        ),
    ],
    ids=["usuniete-issue", "nieczytelna-odpowiedz", "brak-sieci-na-drugiej-stronie"],
)
def test_porazka_strony_komentarzy_to_porazka_calosci(
    answers: tuple[Callable[[], HttpResponse], ...], expected: CommentsOutcome
) -> None:
    remaining = iter(answers)

    outcome, _ = comments_with(lambda: next(remaining)())

    assert outcome == expected


OPERATIONS: dict[str, Callable[[GitHubReportBox, str], object]] = {
    "open_issue": lambda box, key: box.open_issue("kontrola-ilosci", TITLE, BODY, key=key),
    "comment": lambda box, key: box.comment(12, BODY, key=key),
    "edit_comment": lambda box, key: box.edit_comment(901, BODY, key=key),
    "comments": lambda box, key: box.comments(12, key=key),
    "labelled_issues": lambda box, key: box.labelled_issues("kontrola-ilosci", include_closed=True, key=key),
    "archive": lambda box, key: box.archive("logi-08_14_09_2026", key=key),
    "open_archive": lambda box, key: box.open_archive("logi-08_14_09_2026", "Logi", "Opis", key=key),
    "upload": lambda box, key: box.upload(9, "logi.json.gz", "logi.json.gz (wersja 1)", b"\x1f\x8b", key=key),
    "remove": lambda box, key: box.remove(77, key=key),
}


# Odpowiedź GitHuba na komentarz ponad limit, zmierzona na repozytorium Skrzynki (#332).
TOO_LONG = (
    b'{"message": "Validation Failed", "errors": [{"resource": "IssueComment", "code": "unprocessable", '
    b'"field": "data", "message": "Body is too long (maximum is 65536 characters)"}]}'
)


@pytest.mark.parametrize("status", [400, 413, 422])
@pytest.mark.parametrize("operation", ["open_issue", "comment", "edit_comment", "open_archive", "upload"])
def test_odmowa_tresci_wysylki_to_odmowa_tej_wysylki_a_nie_brak_sieci(operation: str, status: int) -> None:
    transport = ScriptedTransport(lambda: HttpResponse(status, TOO_LONG))

    outcome = OPERATIONS[operation](GitHubReportBox(transport=transport), KEY)

    assert outcome == Rejected()


@pytest.mark.parametrize("key", ["\ufeffgithub_pat_SYNTETYCZNY", "github_pat_SYNTETYCZNY\nX-Inny: 1", "kluczóś"])
@pytest.mark.parametrize("operation", OPERATIONS)
def test_klucz_ktorego_nie_da_sie_wyslac_w_naglowku_to_odmowa_skrzynki_bez_zapytania(key: str, operation: str) -> None:
    transport = ScriptedTransport(lambda: HttpResponse(201, json.dumps({"number": 42}).encode()))

    outcome = OPERATIONS[operation](GitHubReportBox(transport=transport), key)

    assert (outcome, transport.requests) == (Refused(), [])


# Odpowiedzi GitHuba na przekroczony limit zapytań: podstawowy (403) i „secondary” (403 albo 429).
RATE_LIMITS = {
    "podstawowy-403": (403, b'{"message": "API rate limit exceeded for user ID 1.", "documentation_url": "..."}'),
    "secondary-403": (403, b'{"message": "You have exceeded a secondary rate limit. Please wait a few minutes."}'),
    "secondary-429": (429, b'{"message": "You have exceeded a secondary rate limit."}'),
}


@pytest.mark.parametrize("answer", RATE_LIMITS.values(), ids=RATE_LIMITS.keys())
@pytest.mark.parametrize("operation", OPERATIONS)
def test_limit_zapytan_githuba_to_brak_sieci_a_nie_odmowa_klucza(operation: str, answer: tuple[int, bytes]) -> None:
    transport = ScriptedTransport(lambda: HttpResponse(*answer))

    outcome = OPERATIONS[operation](GitHubReportBox(transport=transport), KEY)

    assert outcome == Unreachable()


@pytest.mark.parametrize("operation", OPERATIONS)
def test_403_bez_limitu_zapytan_to_odmowa_klucza(operation: str) -> None:
    transport = ScriptedTransport(
        lambda: HttpResponse(403, b'{"message": "Resource not accessible by personal access token"}')
    )

    outcome = OPERATIONS[operation](GitHubReportBox(transport=transport), KEY)

    assert outcome == Refused()


RELEASES = "https://api.github.com/repos/MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia/releases"
UPLOADS = "https://uploads.github.com/repos/MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia/releases"
TAG = "logi-08_14_09_2026"
ASSET = "20261023T204720Z-settlement-627b45fe219e4274b722953c34d4af54.json.gz"


def test_archiwum_okresu_to_release_z_tagiem_z_listy_wydan_repozytorium_z_jego_plikami() -> None:
    transport = ScriptedTransport(
        pages(
            [{"id": 4, "tag_name": "logi-01_07_09_2026"}, {"id": 5, "tag_name": TAG}, {"tag_name": "bez-id"}],
            [
                {"id": 11, "name": ASSET, "label": f"{ASSET} (wersja 7)", "state": "uploaded"},
                {"id": 12, "name": "urwany.json.gz", "label": None, "state": "starter"},
                {"name": "bez-id.json.gz"},
            ],
        )
    )

    outcome = GitHubReportBox(transport=transport).archive(TAG, key=KEY)

    assert outcome == Archive(5, (Asset(11, ASSET, f"{ASSET} (wersja 7)", True), Asset(12, "urwany.json.gz", "", False)))
    assert [(request.method, request.url, request.body) for request in transport.requests] == [
        ("GET", f"{RELEASES}?per_page=100&page=1", None),
        ("GET", f"{RELEASES}/5/assets?per_page=100&page=1", None),
    ]
    assert all(request.headers["Authorization"] == f"Bearer {KEY}" for request in transport.requests)


def test_pliki_archiwum_sa_zbierane_ze_wszystkich_stron() -> None:
    full_page = [{"id": index, "name": f"{index}.json.gz", "label": "", "state": "uploaded"} for index in range(100)]
    transport = ScriptedTransport(
        pages([{"id": 5, "tag_name": TAG}], full_page, [{"id": 100, "name": ASSET, "label": "", "state": "uploaded"}])
    )

    outcome = GitHubReportBox(transport=transport).archive(TAG, key=KEY)

    assert isinstance(outcome, Archive)
    assert [asset.id for asset in outcome.assets] == list(range(101))
    assert [request.url.rsplit("=", 1)[1] for request in transport.requests] == ["1", "1", "2"]


@pytest.mark.parametrize("operation", ["archive", "open_archive", "upload", "remove"])
def test_odmowa_autoryzacji_przy_archiwum_to_odmowa_skrzynki(operation: str) -> None:
    transport = ScriptedTransport(lambda: HttpResponse(401, b'{"message": "Bad credentials"}'))

    outcome = OPERATIONS[operation](GitHubReportBox(transport=transport), KEY)

    assert outcome == Refused()


def test_bez_release_z_tagiem_okresu_archiwum_jeszcze_nie_ma() -> None:
    transport = ScriptedTransport(pages([{"id": 4, "tag_name": "logi-01_07_09_2026"}]))

    assert GitHubReportBox(transport=transport).archive(TAG, key=KEY) is None
    assert len(transport.requests) == 1


def test_brak_sieci_przy_plikach_archiwum_to_skrzynka_nieosiagalna() -> None:
    answers = iter([lambda: HttpResponse(200, json.dumps([{"id": 5, "tag_name": TAG}]).encode()), no_network])

    outcome = GitHubReportBox(transport=ScriptedTransport(lambda: next(answers)())).archive(TAG, key=KEY)

    assert outcome == Unreachable()


def test_zalozone_archiwum_to_release_z_tagiem_ktory_nie_jest_najnowszym_wydaniem() -> None:
    transport = ScriptedTransport(lambda: HttpResponse(201, json.dumps({"id": 9, "tag_name": TAG}).encode()))

    outcome = GitHubReportBox(transport=transport).open_archive(TAG, "Logi Uruchomień", "Opis.", key=KEY)

    assert outcome == Archive(9, ())
    [request] = transport.requests
    assert (request.method, request.url, request.headers["Content-Type"]) == ("POST", RELEASES, "application/json")
    assert request.body is not None
    assert json.loads(request.body) == {
        "tag_name": TAG,
        "name": "Logi Uruchomień",
        "body": "Opis.",
        "make_latest": "false",
    }


def test_plik_idzie_na_adres_wysylki_plikow_z_nazwa_i_etykieta_a_wynik_to_plik_archiwum() -> None:
    label = f"{ASSET} (wersja 20261023T204720846240Z-0001)"
    transport = ScriptedTransport(
        lambda: HttpResponse(201, json.dumps({"id": 77, "name": ASSET, "label": label, "state": "uploaded"}).encode())
    )

    outcome = GitHubReportBox(transport=transport).upload(9, ASSET, label, b"\x1f\x8bspakowane", key=KEY)

    assert outcome == Asset(77, ASSET, label, True)
    [request] = transport.requests
    address = urlsplit(request.url)
    assert (request.method, f"{address.scheme}://{address.netloc}{address.path}") == ("POST", f"{UPLOADS}/9/assets")
    assert parse_qs(address.query) == {"name": [ASSET], "label": [label]}
    assert (request.body, request.headers["Content-Type"]) == (b"\x1f\x8bspakowane", "application/octet-stream")


def test_usuniety_plik_archiwum_to_odpowiedz_bez_tresci() -> None:
    transport = ScriptedTransport(lambda: HttpResponse(204, b""))

    outcome = GitHubReportBox(transport=transport).remove(77, key=KEY)

    assert outcome == Removed()
    [request] = transport.requests
    assert (request.method, request.url, request.body) == ("DELETE", f"{RELEASES}/assets/77", None)


@pytest.mark.parametrize(
    ("operation", "answer"),
    [
        ("open_archive", lambda: HttpResponse(201, json.dumps({"tag_name": TAG}).encode())),
        ("open_archive", lambda: HttpResponse(200, json.dumps({"id": 9}).encode())),
        ("upload", lambda: HttpResponse(201, json.dumps({"id": 77}).encode())),
        ("upload", lambda: HttpResponse(200, json.dumps({"id": 77, "name": ASSET}).encode())),
        ("remove", lambda: HttpResponse(200, b"{}")),
        ("archive", lambda: HttpResponse(200, b'{"message": "to nie jest lista"}')),
    ],
    ids=["release-bez-id", "release-nie-201", "plik-bez-nazwy", "plik-nie-201", "usuniecie-nie-204", "lista-nie-lista"],
)
def test_niezwykla_odpowiedz_przy_archiwum_to_skrzynka_nieosiagalna(
    operation: str, answer: Callable[[], HttpResponse]
) -> None:
    outcome = OPERATIONS[operation](GitHubReportBox(transport=ScriptedTransport(answer)), KEY)

    assert outcome == Unreachable()


# Odpowiedzi GitHuba na założenie Release w repozytorium bez commitu: 409 z repozytorium Skrzynki 2026-11-04 (opis PR
# #860) i 422 z repozytorium próbnego 2026-11-05 kluczem OAuth i fine-grained (nagrania ``verify-github-skrzynki``).
EMPTY_REPOSITORY = {
    "message": "Git Repository is empty.",
    "documentation_url": "https://docs.github.com/rest/releases/releases#create-a-release",
    "status": "409",
}
EMPTY_REPOSITORY_VALIDATION = {
    "message": "Validation Failed",
    "errors": [{"resource": "Release", "code": "custom", "message": "Repository is empty."}],
    "documentation_url": "https://docs.github.com/rest/releases/releases#create-a-release",
    "status": "422",
}
EMPTY_REPOSITORY_ANSWERS = {
    "puste-repozytorium": (409, EMPTY_REPOSITORY),
    "puste-repozytorium-422": (422, EMPTY_REPOSITORY_VALIDATION),
}


# Odpowiedzi GitHuba na plik o nazwie, która już jest w Release, i na Release z tagiem, który już ma Release
# (repozytorium próbne z commitem 2026-11-05, nagrania ``verify-github-skrzynki``).
SAME_NAME = {
    "message": "Validation Failed",
    "errors": [{"resource": "ReleaseAsset", "code": "already_exists", "field": "name"}],
}
SAME_TAG = {
    "message": "Validation Failed",
    "errors": [{"resource": "Release", "code": "already_exists", "field": "tag_name"}],
    "status": "422",
}


@dataclass
class GitHubOnTransport:
    """GitHub REST dla Skrzynki w pamięci, za transportem HTTP: issue z komentarzami i Release'y z plikami.

    Zna tylko zapytania, które wysyła ``GitHubReportBox``, i jak GitHub nie trzyma dwóch plików jednej nazwy w jednym
    Release ani dwóch Release'ów jednego tagu (422). ``refuse_releases``: klucz bez uprawnienia do treści repozytorium (403 przy każdym zapytaniu o
    Release'y i ich pliki). ``empty_repository``: repozytorium bez żadnego commitu, jak repozytorium Skrzynki
    2026-11-04: lista Release'ów jest pusta, a założenie Release to ta odpowiedź (``EMPTY_REPOSITORY_ANSWERS``).
    """

    issues: dict[int, dict[str, Any]] = field(default_factory=dict)
    releases: dict[int, dict[str, Any]] = field(default_factory=dict)
    assets: dict[int, dict[str, Any]] = field(default_factory=dict)
    data: dict[int, bytes] = field(default_factory=dict)
    refuse_releases: bool = False
    empty_repository: tuple[int, object] | None = None
    requests: list[tuple[str, str]] = field(default_factory=list)
    _ids: Iterator[int] = field(default_factory=lambda: itertools.count(101))

    def __call__(self, request: HttpRequest) -> HttpResponse:
        address = urlsplit(request.url)
        path, query = address.path.removeprefix("/repos/MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia"), parse_qs(address.query)
        self.requests.append((request.method, path))
        body: Any = json.loads(request.body or b"null") if request.headers.get("Content-Type") == "application/json" else None
        if path.startswith("/releases") and self.refuse_releases:
            return self._answer(403, {"message": "Resource not accessible by personal access token"})
        match request.method, path.split("/")[1:]:
            case "GET", ["issues"]:
                label = query["labels"][0]
                return self._page([issue for issue in self.issues.values() if issue["label"] == label], query)
            case "POST", ["issues"]:
                number = len(self.issues) + 1
                self.issues[number] = {"number": number, "body": body["body"], "label": body["labels"][0], "comments": []}
                return self._answer(201, {"number": number})
            case "GET", ["issues", number, "comments"]:
                return self._page(self.issues[int(number)]["comments"], query)
            case "POST", ["issues", number, "comments"]:
                comment = {"id": next(self._ids), "html_url": f"https://github.com/c/{number}", "body": body["body"]}
                self.issues[int(number)]["comments"].append(comment)
                return self._answer(201, comment)
            case "PATCH", ["issues", "comments", comment_id]:
                comment = next(c for i in self.issues.values() for c in i["comments"] if c["id"] == int(comment_id))
                comment["body"] = body["body"]
                return self._answer(200, comment)
            case "GET", ["releases"]:
                return self._page(list(self.releases.values()), query)
            case "POST", ["releases"] if self.empty_repository is not None:
                return self._answer(*self.empty_repository)
            case "POST", ["releases"] if any(r["tag_name"] == body["tag_name"] for r in self.releases.values()):
                return self._answer(422, SAME_TAG)
            case "POST", ["releases"]:
                release = {"id": next(self._ids), "tag_name": body["tag_name"], "name": body["name"]}
                self.releases[release["id"]] = release
                return self._answer(201, release)
            case "GET", ["releases", release_id, "assets"]:
                return self._page([a for a in self.assets.values() if a["release"] == int(release_id)], query)
            case "POST", ["releases", release_id, "assets"]:
                name, label = query["name"][0], query["label"][0]
                if any(a["release"] == int(release_id) and a["name"] == name for a in self.assets.values()):
                    return self._answer(422, SAME_NAME)
                asset_id = next(self._ids)
                self.data[asset_id] = request.body or b""
                self.assets[asset_id] = {"id": asset_id, "name": name, "label": label, "state": "uploaded", "release": int(release_id)}
                return self._answer(201, self.assets[asset_id])
            case "DELETE", ["releases", "assets", asset_id]:
                del self.assets[int(asset_id)]
                return HttpResponse(204, b"")
            case _:
                raise AssertionError(f"GitHubReportBox nie wysyła {request.method} {path}")

    def files(self, tag: str) -> dict[str, str]:
        """Pliki Release z tagiem ``tag`` po nazwie, rozpakowane."""

        [release] = [release["id"] for release in self.releases.values() if release["tag_name"] == tag]
        mine = [asset for asset in self.assets.values() if asset["release"] == release]
        return {asset["name"]: gzip.decompress(self.data[asset["id"]]).decode("utf-8") for asset in mine}

    @staticmethod
    def _page(entries: list[Any], query: dict[str, list[str]]) -> HttpResponse:
        size, page = int(query["per_page"][0]), int(query["page"][0])
        return HttpResponse(200, json.dumps(entries[(page - 1) * size : page * size]).encode())

    @staticmethod
    def _answer(status: int, document: object) -> HttpResponse:
        return HttpResponse(status, json.dumps(document).encode())


def test_archiwum_z_tagiem_ktory_juz_ma_release_to_odmowa_tresci_a_archiwum_zostaje_jedno() -> None:
    box = GitHubReportBox(transport=GitHubOnTransport())
    opened = box.open_archive(TAG, "Logi Uruchomień", "Opis.", key=KEY)

    outcome = box.open_archive(TAG, "Logi Uruchomień", "Opis.", key=KEY)

    assert (outcome, box.archive(TAG, key=KEY)) == (Rejected(), opened)


def test_plik_o_nazwie_ktora_jest_juz_w_archiwum_to_odmowa_tresci_a_pierwszy_plik_zostaje() -> None:
    box = GitHubReportBox(transport=GitHubOnTransport())
    opened = box.open_archive(TAG, "Logi Uruchomień", "Opis.", key=KEY)
    assert isinstance(opened, Archive)
    first = box.upload(opened.id, ASSET, f"{ASSET} (wersja 1)", b"\x1f\x8bpierwszy", key=KEY)
    assert isinstance(first, Asset)

    outcome = box.upload(opened.id, ASSET, f"{ASSET} (wersja 2)", b"\x1f\x8bdrugi", key=KEY)

    assert (outcome, box.archive(TAG, key=KEY)) == (Rejected(), Archive(opened.id, (first,)))


LOGS = PeriodThread("logi-uruchomienia", tool("- Logi Uruchomienia okresu: 08_14_09_2026"), "reuse", tool("Logi Uruchomienia 08_14_09_2026"))


def logs_post(text: str) -> Post:
    archive = ArchiveFile(TAG, "Logi Uruchomień 08_14_09_2026", "Opis.", ASSET.removesuffix(".gz"), logs_text(text))
    return Post(LOGS, "08_14_09_2026", "627b45fe219e4274b722953c34d4af54", tool("Logi okresu"), (tool("podsumowanie\n"),), archive)


def github_queue(tmp_path: Path, github: GitHubOnTransport) -> Outbox:
    clock = ManualClock()
    keyed = KeyedBox(GitHubReportBox(transport=github), lambda: KEY, clock=clock)
    log = CentrumLog(tmp_path / "logs" / "centrum-rozliczen.log")
    return Outbox(tmp_path / "kolejka", keyed, log, clock=clock, listener=QueueListener())


def test_skrzynka_githuba_zaklada_archiwum_okresu_wysyla_plik_a_po_diagnozie_podmienia_go_bez_drugiego_pliku(
    tmp_path: Path,
) -> None:
    github = GitHubOnTransport()
    queue = github_queue(tmp_path, github)

    queue.post(logs_post("{\"diagnosis\": null}\n"))
    assert wait_for(lambda: not list((tmp_path / "kolejka").glob("*.json")))
    first = list(github.requests)
    queue.post(logs_post("{\"diagnosis\": \"BRAK_WZORCA\"}\n"))
    assert wait_for(lambda: not list((tmp_path / "kolejka").glob("*.json")) and len(github.requests) > len(first) + 4)

    assert first == [
        ("GET", "/issues"),
        ("GET", "/releases"),
        ("POST", "/releases"),
        ("POST", "/releases/101/assets"),
        ("POST", "/issues"),
        ("POST", "/issues/1/comments"),
    ]
    assert github.requests[len(first) :] == [
        ("GET", "/issues"),
        ("GET", "/issues/1/comments"),
        ("GET", "/releases"),
        ("GET", "/releases/101/assets"),
        ("DELETE", "/releases/assets/102"),
        ("POST", "/releases/101/assets"),
        ("PATCH", "/issues/comments/103"),
    ]
    assert github.files(TAG) == {ASSET: "{\"diagnosis\": \"BRAK_WZORCA\"}\n"}
    [release] = github.releases.values()
    assert release["name"] == "Logi Uruchomień 08_14_09_2026"


def test_klucz_bez_uprawnienia_do_tresci_repozytorium_zostawia_plik_w_kolejce_a_komentarz_idzie_z_dopiskiem(
    tmp_path: Path,
) -> None:
    github = GitHubOnTransport(refuse_releases=True)
    queue = github_queue(tmp_path, github)

    queue.post(logs_post("{}\n"))
    # Przejście zamienia plik kolejki na plik ze znacznikiem części, a na Windows odczyt w trakcie zamiany pada
    # (PermissionError), więc test czyta plik dopiero po przejściu.
    assert not queue.wait_delivered("", "zgloszenie", timeout_s=30), "przejście kolejki się skończyło"

    assert "przyczyna=odmowa-archiwum" in (tmp_path / "logs" / "centrum-rozliczen.log").read_text("utf-8")
    [queued] = (tmp_path / "kolejka").glob("*.json")
    assert json.loads(queued.read_text("utf-8"))["delivered_parts"] == 1
    assert github.releases == {}
    [comment] = github.issues[1]["comments"]
    assert re.search(rf"Plik `{re.escape(ASSET)}` czeka w Kolejce wysyłki", str(comment["body"]))


REPORT = report_target(FINGERPRINT, tool(TITLE))


def queued_before_start(directory: Path, *posts: Post) -> None:
    """Pliki kolejki z poprzedniej pracy Centrum w tej kolejności, nazwane jak w ``Outbox.post``."""

    directory.mkdir(parents=True)
    for place, post in enumerate(posts):
        name = f"20261023T10150{place}000000Z-{place + 1:04d}-{post.target.label}-{post.run_id[:8]}.json"
        (directory / name).write_text(post.to_json(), encoding="utf-8")


@pytest.mark.parametrize("refusal", [*EMPTY_REPOSITORY_ANSWERS, "bez-uprawnienia"])
def test_odmowa_archiwum_zatrzymuje_tylko_plik_logow_a_zgloszenie_za_nimi_dochodzi_w_tym_samym_przejsciu_bez_komunikatu(
    tmp_path: Path, refusal: str
) -> None:
    """Repozytorium Skrzynki bez commitu (409 albo 422 na założenie Archiwum) i Token bez uprawnienia do treści repozytorium (403)
    to odmowa Archiwum, która trwa, aż Maks coś zmieni: zatrzymuje tylko plik Logów. Komentarz Logów idzie z dopiskiem,
    a Zgłoszenie, które czeka w kolejce za nimi, dochodzi w tym samym przejściu, a klucz taty zostaje przyjęty, więc tata
    nie dostaje Komunikatu (spec #837, #844)."""

    github = GitHubOnTransport(
        empty_repository=EMPTY_REPOSITORY_ANSWERS.get(refusal), refuse_releases=refusal == "bez-uprawnienia"
    )
    clock = ManualClock()
    keyed = KeyedBox(GitHubReportBox(transport=github), lambda: KEY, clock=clock)
    listener = QueueListener()
    log = tmp_path / "logs" / "centrum-rozliczen.log"
    queue = Outbox(tmp_path / "kolejka", keyed, CentrumLog(log), clock=clock, listener=listener)
    report_run = "9b1c2d3e4f5a6b7c3f2a9c1b8e7d4f0a"
    report = Post(REPORT, "08_14_09_2026", report_run, None, (tool(f"Zgłoszenie\n\n{fingerprint_line(FINGERPRINT)}\n"),))
    queued_before_start(tmp_path / "kolejka", logs_post("{}\n"), report)

    queue.resume()

    assert not queue.wait_delivered("", "zgloszenie", timeout_s=30), "przejście kolejki się skończyło"
    left = sorted((tmp_path / "kolejka").glob("*.json"))
    assert [path.name.split("-", 2)[2] for path in left] == ["logi-uruchomienia-627b45fe.json"]
    assert json.loads(left[0].read_text("utf-8"))["delivered_parts"] == 1
    assert [run_id for run_id, _ in listener.numbers] == ["627b45fe219e4274b722953c34d4af54", report_run]
    [logs_issue, report_issue] = github.issues.values()
    assert (report_issue["label"], len(logs_issue["comments"])) == ("zgloszenie", 1)
    assert re.search(rf"Plik `{re.escape(ASSET)}` czeka w Kolejce wysyłki", str(logs_issue["comments"][0]["body"]))
    asked = [request for request in github.requests if request[1].startswith("/releases")]
    assert (asked, github.releases) == (
        [("GET", "/releases"), ("POST", "/releases")] if refusal in EMPTY_REPOSITORY_ANSWERS else [("GET", "/releases")],
        {},
    )
    lines = log.read_text("utf-8")
    assert ("przyczyna=odmowa-archiwum" in lines, "przyczyna=brak-sieci" in lines) == (True, False)
    assert keyed.judge(wait_s=0) == "accepted"


@pytest.mark.parametrize("system", [3, 19, 255, 10], ids=["linux", "macos-python-3-12", "python-3-13", "windows-zlib"])
def test_nagranie_archiwum_odtwarza_sie_przy_gzipie_innej_maszyny(monkeypatch: pytest.MonkeyPatch, system: int) -> None:
    """``ArchiveFile.packed`` daje na Windows w CI (Python 3.14) inne bajty niż na Macu, na którym powstało nagranie
    (run 41959078147, bajt systemu w nagłówku 255 zamiast 19): odtwarzanie Archiwum nie zależy od bajtów gzipu maszyny."""

    compress = gzip.compress

    def compress_like_other_machine(data: bytes, compresslevel: int = 9, *, mtime: float | None = None) -> bytes:
        packed = compress(data, compresslevel=1, mtime=mtime)  # inny poziom: deflate innej biblioteki
        return packed[:9] + bytes([system]) + packed[10:]

    monkeypatch.setattr(gzip, "compress", compress_like_other_machine)
    recording = github_wymiana.read_recording(SKILL / "nagrania" / "archiwum-fine-grained.json")

    results = github_skrzynki.replay("archiwum-fine-grained", recording)

    assert [(result.case, result.problems) for result in results if not result.ok] == []
    assert len(results) == len(github_przypadki_archiwum.CASES)
