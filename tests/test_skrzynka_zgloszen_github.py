"""Skrzynka Zgłoszeń na GitHubie: odpowiedzi REST zamienione na wyniki skrzynki, z podstawionym transportem HTTP.

Żaden test nie łączy się z prawdziwym GitHubem.
"""

from __future__ import annotations

import http.client
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest

from rozliczenia.centrum.report_box import (
    Closure,
    Comment,
    CommentOutcome,
    CommentsOutcome,
    Commented,
    FindOutcome,
    GitHubReportBox,
    HttpRequest,
    HttpResponse,
    Issue,
    IssuesOutcome,
    Label,
    Refused,
    Rejected,
    SendOutcome,
    Sent,
    Unreachable,
)
from rozliczenia.centrum.keyed_box import KeyedBox, NoKey
from rozliczenia.centrum.outbox import fingerprint_line

from tests.fixtures.clock import ManualClock

TITLE = "BRAK_WZORCA: Nie znaleziono wzorca."
BODY = "## Komunikat\n"
FINGERPRINT = "0123456789abcdef"
KEY = "github_pat_SYNTETYCZNY"


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
}


# Odpowiedź GitHuba na komentarz ponad limit, zmierzona na repozytorium Skrzynki (#332).
TOO_LONG = (
    b'{"message": "Validation Failed", "errors": [{"resource": "IssueComment", "code": "unprocessable", '
    b'"field": "data", "message": "Body is too long (maximum is 65536 characters)"}]}'
)


@pytest.mark.parametrize("status", [400, 413, 422])
@pytest.mark.parametrize("operation", ["open_issue", "comment", "edit_comment"])
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
