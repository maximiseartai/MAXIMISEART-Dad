"""``tools/poprawki_operatora.py`` wypisuje z bazy T3 Code tylko wiadomości, które operator napisał w oknie T3, z wątków
repo w tygodniu czasu polskiego.

Wymaganie bierzemy z jednostki H programu „11 z 11” (polowanie na powtarzane błędy): poprawki Maksa w wątkach agentów,
bez tekstu, który do wątku włożył agent, zadanie T3 albo serwer, i bez cichego zera z wejścia, którego narzędzie nie
przeczytało (#1914 r3 i r4: tydzień bez wiadomości operatora w wątkach repo to porażka, nie zero). Baza jest syntetyczna, w kształcie bazy stanu serwera
T3 w tym, co narzędzie czyta: tabele projektów, wątków i wiadomości, a w ``payload_json`` wiadomości pola nadawcy
``createdBy`` i ``creationSource`` z kontraktu ``orchestrationV2``. Teksty wiadomości są wymyślone (zdania z
``_zdanie`` i krótkie teksty wpisane w teście, jak ``/compact`` i „tak”), a identyfikatory wątków i katalogi projektów
też, bo repozytorium jest publiczne, a prawdziwa baza niesie prywatne wiadomości operatora.
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import subprocess

import pytest

from tests.fixtures.znane_luki import assert_znane_luki
import poprawki_operatora
from tydzien_polski import WARSAW

WEEK = "2026-11-02"
REPO = "/tmp/projekty/MAXIMISEART-Dad"
OTHER = "/tmp/projekty/inny-projekt"
COORDINATOR = "watek-koordynatora"
CHILD = "watek-dziecka"
STRANGER = "watek-innego-projektu"
LATER = (
    STRANGER,
    "2026-11-09T08:00:00.000Z",
    "assistant",
    {"text": "odpowiedź po końcu tygodnia"},
)
SCHEMA = """
CREATE TABLE projection_projects (project_id TEXT PRIMARY KEY, workspace_root TEXT NOT NULL);
CREATE TABLE orchestration_v2_projection_threads (thread_id TEXT PRIMARY KEY, project_id TEXT NOT NULL);
CREATE TABLE orchestration_v2_projection_messages (
  message_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, role TEXT NOT NULL, created_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
"""


def _zdanie(numer: int) -> str:
    return (
        f"zdanie syntetyczne numer {numer}, którego nikt nie napisał w prawdziwym wątku"
    )


def _operator(
    thread: str, when: object, text: str, source: str = "web"
) -> tuple[str, object, str, dict[str, object]]:
    return (
        thread,
        when,
        "user",
        {"createdBy": "user", "creationSource": source, "text": text},
    )


def _agent(
    thread: str, when: str, text: str, source: str, **fields: object
) -> tuple[str, str, str, dict[str, object]]:
    return (
        thread,
        when,
        "user",
        {"createdBy": "agent", "creationSource": source, "text": text, **fields},
    )


def _base(
    path: Path,
    messages: list[tuple[str, object, str, dict[str, object]]],
    repo: str = REPO,
    later: bool = True,
    ids: tuple[str, ...] = (),
    other: str = OTHER,
) -> Path:
    """Baza T3 z wiadomościami ``messages``; ``later`` dokłada odpowiedź po końcu tygodnia, czyli bazę, którą T3 dalej
    pisze, ``ids`` daje identyfikatory pierwszych wiadomości zamiast ``m<numer>``, a ``other`` to katalog projektu wątku
    ``STRANGER``."""

    with closing(sqlite3.connect(path)) as db:
        db.executescript(SCHEMA)
        db.executemany(
            "INSERT INTO projection_projects VALUES (?, ?)",
            [("p-repo", repo), ("p-inny", other)],
        )
        threads = [
            (COORDINATOR, "p-repo"),
            (CHILD, "p-repo"),
            ("watek-b", "p-repo"),
            ("watek-c", "p-repo"),
            (STRANGER, "p-inny"),
        ]
        db.executemany(
            "INSERT INTO orchestration_v2_projection_threads VALUES (?, ?)", threads
        )
        everything = [*messages, LATER] if later else messages
        named = [*ids, *(f"m{at}" for at in range(len(ids), len(everything)))]
        rows = [
            (named[at], thread, role, when, json.dumps(payload, ensure_ascii=False))
            for at, (thread, when, role, payload) in enumerate(everything)
        ]
        db.executemany(
            "INSERT INTO orchestration_v2_projection_messages VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        db.commit()
    return path


def _run(
    base: Path, capsys: pytest.CaptureFixture[str], *extra: str
) -> tuple[int, list[str]]:
    code = poprawki_operatora.main(["--tydzien", WEEK, "--baza", str(base), *extra])
    return code, capsys.readouterr().out.splitlines()


@pytest.fixture
def week_base(tmp_path: Path) -> Path:
    return _base(
        tmp_path / "statev2.sqlite",
        [
            _operator(COORDINATOR, "2026-11-01T22:59:59.999Z", _zdanie(0)),
            _operator(COORDINATOR, "2026-11-01T23:00:00.000Z", _zdanie(1)),
            _operator(
                COORDINATOR,
                "2026-11-03T10:00:00.000Z",
                f"{_zdanie(2)}\n\nzróbmy to jeszcze raz",
                source="mobile",
            ),
            (
                COORDINATOR,
                "2026-11-03T10:00:30.000Z",
                "assistant",
                {"text": _zdanie(3)},
            ),
            (
                COORDINATOR,
                "2026-11-03T11:00:00.000Z",
                "user",
                {
                    "createdBy": "user",
                    "creationSource": "web",
                    "text": "/compact",
                    "idleCompaction": "onReturn",
                },
            ),
            (
                COORDINATOR,
                "2026-11-03T11:01:00.000Z",
                "user",
                {"createdBy": "user", "creationSource": "server", "text": _zdanie(4)},
            ),
            _agent(
                COORDINATOR,
                "2026-11-03T12:00:00.000Z",
                _zdanie(5),
                "mcp",
                senderThreadId=CHILD,
            ),
            _agent(COORDINATOR, "2026-11-03T12:01:00.000Z", _zdanie(6), "mcp"),
            _agent(
                COORDINATOR,
                "2026-11-03T12:02:00.000Z",
                _zdanie(7),
                "server",
                notification={"kind": "pull_request"},
            ),
            _agent(
                CHILD,
                "2026-11-03T12:03:00.000Z",
                _zdanie(8),
                "mcp",
                senderThreadId=COORDINATOR,
            ),
            _agent(
                CHILD,
                "2026-11-03T12:04:00.000Z",
                _zdanie(9),
                "provider",
                senderThreadId=COORDINATOR,
            ),
            _operator(STRANGER, "2026-11-03T12:05:00.000Z", _zdanie(10)),
            _operator(CHILD, "2026-11-08T22:59:59.999Z", "tak"),
            _operator(CHILD, "2026-11-08T23:00:00.000Z", _zdanie(11)),
        ],
    )


def test_tydzien_daje_tylko_wiadomosci_napisane_w_oknie_t3_w_watkach_repo(
    week_base: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, (*lines, last) = _run(week_base, capsys)

    assert code == 0
    assert lines == [
        f"2026-11-02 00:00 | {COORDINATOR} | {_zdanie(1)}",
        f"2026-11-03 11:00 | {COORDINATOR} | {_zdanie(2)} / zróbmy to jeszcze raz",
        f"2026-11-08 23:59 | {CHILD} | tak",
    ]
    assert last == (
        f"POPRAWKI OPERATORA OK | tydzień {WEEK}: 3 wiadomości operatora w 2 wątkach z 10 wiadomości user | "
        "/compact po powrocie 1, agent/mcp 3, agent/provider 1, agent/server 1, user/server 1"
    )


def test_poprawka_wklejona_do_dwoch_watkow_zostaje_w_obu_choc_agent_przekazal_ja_miedzy_wklejeniami(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fix = _zdanie(20)
    base = _base(
        tmp_path / "statev2.sqlite",
        [
            _agent(
                "watek-c", "2026-11-03T09:00:00.000Z", fix, "mcp", senderThreadId=CHILD
            ),
            _operator(COORDINATOR, "2026-11-03T10:00:00.000Z", fix),
            _agent(
                CHILD,
                "2026-11-03T10:01:00.000Z",
                f"{fix}\n\nKontekst",
                "mcp",
                senderThreadId=COORDINATOR,
            ),
            _operator("watek-b", "2026-11-03T10:05:00.000Z", fix),
        ],
    )

    code, (*lines, _) = _run(base, capsys)

    assert code == 0
    assert lines == [
        f"2026-11-03 11:00 | {COORDINATOR} | {fix}",
        f"2026-11-03 11:05 | watek-b | {fix}",
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {"creationSource": "web", "text": "tak"},
        {"createdBy": "user", "creationSource": "terminal", "text": "tak"},
    ],
    ids=["bez-createdBy", "zrodlo-spoza-kontraktu"],
)
def test_wiadomosc_z_nadawca_spoza_kontraktu_t3_konczy_sie_porazka_zamiast_cichego_pominiecia(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], payload: dict[str, object]
) -> None:
    base = _base(
        tmp_path / "statev2.sqlite",
        [
            _operator(COORDINATOR, "2026-11-03T10:00:00.000Z", _zdanie(1)),
            (COORDINATOR, "2026-11-03T10:01:00.000Z", "user", payload),
        ],
    )

    code, lines = _run(base, capsys)

    assert (code, len(lines)) == (1, 1)
    assert lines[0].startswith(f"POPRAWKI OPERATORA FAIL | baza T3 {base}: ")


@pytest.mark.parametrize(
    "foreign", [True, False], ids=["baza-bez-tabel-t3", "brak-bazy"]
)
def test_baza_ktorej_narzedzie_nie_przeczyta_konczy_sie_porazka_z_jej_nazwa(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], foreign: bool
) -> None:
    base = tmp_path / "statev2.sqlite"
    if foreign:
        with closing(sqlite3.connect(base)) as db:
            db.execute("CREATE TABLE notatki (tekst TEXT)")
            db.commit()

    code, lines = _run(base, capsys)

    assert (code, len(lines)) == (1, 1)
    assert lines[0].startswith("POPRAWKI OPERATORA FAIL | ")
    assert str(base) in lines[0]


def test_tekst_skrocony_do_limitu_znakow_mowi_ile_mial_znakow(
    week_base: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, lines = _run(week_base, capsys, "--znaki", "10")

    assert lines[0].endswith(f"| {_zdanie(1)[:10]}… ({len(_zdanie(1))} zn.)")


def test_powod_odmowy_zgody_wpisany_w_oknie_jest_wiadomoscia_operatora_a_wznowienie_serwera_nie(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    server = {"createdBy": "user", "creationSource": "server"}
    base = _base(
        tmp_path / "statev2.sqlite",
        [
            (
                COORDINATOR,
                "2026-11-03T10:00:00.000Z",
                "user",
                {**server, "text": _zdanie(30)},
            ),
            (
                COORDINATOR,
                "2026-11-03T10:01:00.000Z",
                "user",
                {**server, "text": _zdanie(31)},
            ),
        ],
        ids=("approval-feedback:prosba-1", "limit-resume:watek-koordynatora:1"),
    )

    code, (*lines, last) = _run(base, capsys)

    assert code == 0
    assert lines == [f"2026-11-03 11:00 | {COORDINATOR} | {_zdanie(30)}"]
    assert last.endswith("z 2 wiadomości user | user/server 1")


ZNANE_LUKI: dict[str, tuple[str, dict[str, object]]] = {
    "nadawca z bazy nie odróżnia okna od agenta: odpowiedź operatora na pytanie dostawcy (async-answer) ma user/server jak odpowiedź agenta przez t3_pending_request": (
        "async-answer:prosba-2",
        {"createdBy": "user", "creationSource": "server", "text": _zdanie(40)},
    )
}


def test_znane_luki_nadawcy_operatora(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    zgloszenia: dict[str, list[str]] = {}
    for at, (opis, (message_id, payload)) in enumerate(ZNANE_LUKI.items()):
        written = _operator(CHILD, "2026-11-03T10:05:00.000Z", _zdanie(41))
        base = _base(
            tmp_path / f"statev2-{at}.sqlite",
            [(COORDINATOR, "2026-11-03T10:00:00.000Z", "user", payload), written],
            ids=(message_id,),
        )
        code, (*lines, _) = _run(base, capsys)
        assert code == 0, opis
        zgloszenia[opis] = [
            f"wypisana jako wiadomość operatora: {line}"
            for line in lines
            if str(payload["text"]) in line
        ]

    assert_znane_luki(zgloszenia, "tests/test_poprawki_operatora.py (ZNANE_LUKI)")


@pytest.mark.parametrize(
    ("created_at", "repo", "later", "reason"),
    [
        (
            1762160400000,
            REPO,
            True,
            "created_at wiadomości poza zapisem toISOString: tekst w innym zapisie 1",
        ),
        (
            "2026-11-03T10:00:00.000Z",
            "/home/inny/maximiseart-dad",
            True,
            "żaden projekt T3 nie jest repo: katalog MAXIMISEART-Dad albo checkout z origin maximiseartai/maximiseart-dad",
        ),
        (
            "2026-11-03T10:00:00.000Z",
            REPO,
            False,
            "najnowsza wiadomość bazy (2026-11-03T10:00:00.000Z) jest sprzed końca tygodnia 2026-11-08T23:00:00.000Z",
        ),
    ],
    ids=[
        "created_at-liczba-milisekund",
        "katalog-pod-inna-nazwa-bez-checkoutu-repo",
        "baza-ktorej-t3-juz-nie-pisze",
    ],
)
def test_baza_z_ktorej_narzedzie_nie_przeczyta_tygodnia_konczy_sie_porazka_z_powodem_zamiast_zera(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    created_at: object,
    repo: str,
    later: bool,
    reason: str,
) -> None:
    """Sondy W1 #1914 r3: każda baza ma w tygodniu wiadomość operatora, której narzędzie nie przeczyta."""

    base = _base(
        tmp_path / "statev2.sqlite",
        [_operator(COORDINATOR, created_at, _zdanie(50))],
        repo=repo,
        later=later,
    )

    code, lines = _run(base, capsys)

    assert (code, len(lines)) == (1, 1)
    assert lines[0].startswith(f"POPRAWKI OPERATORA FAIL | baza T3 {base}: {reason}")


@pytest.mark.parametrize(
    ("repo_messages", "other", "last"),
    [
        (
            [
                _agent(
                    COORDINATOR,
                    "2026-11-03T09:00:00.000Z",
                    _zdanie(60),
                    "server",
                    notification={"kind": "pull_request"},
                ),
                _agent(CHILD, "2026-11-04T09:00:00.000Z", _zdanie(61), "mcp"),
            ],
            "/tmp/nowe-miejsce/MAXIMISEART-Dad-nowy",
            "0 wiadomości operatora w wątkach MAXIMISEART-Dad z 2 wiadomości user | inne projekty T3 tej bazy: MAXIMISEART-Dad-nowy 2",
        ),
        (
            [
                (
                    COORDINATOR,
                    "2026-11-03T09:00:00.000Z",
                    "assistant",
                    {"text": _zdanie(60)},
                )
            ],
            OTHER,
            "0 wiadomości operatora w wątkach MAXIMISEART-Dad z 0 wiadomości user | inne projekty T3 tej bazy: inny-projekt 2",
        ),
    ],
    ids=[
        "stary-projekt-z-wiadomosciami-agentow-po-przeniesieniu-repo",
        "watki-repo-bez-wiadomosci-user",
    ],
)
def test_tydzien_bez_wiadomosci_operatora_w_watkach_repo_konczy_sie_porazka_z_liczba_z_innych_projektow(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    repo_messages: list[tuple[str, object, str, dict[str, object]]],
    other: str,
    last: str,
) -> None:
    """Sonda W1 #1914 r4: repo przeniesione do katalogu, który nie jest checkoutem repo, a stary projekt dostaje tylko
    wiadomości agentów; zero operatora w wątkach repo nie jest linią ``OK``. Wiadomość agenta i nadawca spoza kontraktu
    w innym projekcie nie liczą się do jego wiadomości operatora."""

    operator = [
        _operator(STRANGER, "2026-11-03T10:00:00.000Z", _zdanie(62)),
        _operator(STRANGER, "2026-11-05T10:00:00.000Z", _zdanie(63)),
    ]
    noise: list[tuple[str, object, str, dict[str, object]]] = [
        _agent(STRANGER, "2026-11-05T10:01:00.000Z", _zdanie(64), "mcp"),
        (
            STRANGER,
            "2026-11-05T10:02:00.000Z",
            "user",
            {"creationSource": "web", "text": "tak"},
        ),
    ]
    base = _base(
        tmp_path / "statev2.sqlite", [*repo_messages, *operator, *noise], other=other
    )

    code, lines = _run(base, capsys)

    assert (code, lines) == (1, [f"POPRAWKI OPERATORA FAIL | tydzień {WEEK}: {last}"])


def test_tydzien_ktory_jeszcze_trwa_konczy_sie_porazka(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = _base(
        tmp_path / "statev2.sqlite",
        [_operator(COORDINATOR, "2026-11-03T10:00:00.000Z", _zdanie(70))],
    )

    code = poprawki_operatora.main(
        ["--tydzien", datetime.now(WARSAW).date().isoformat(), "--baza", str(base)]
    )

    lines = capsys.readouterr().out.splitlines()
    assert (code, len(lines)) == (1, 1)
    assert " jeszcze trwa: kończy się " in lines[0]


def _checkout(path: Path, origin: str) -> str:
    """Katalog projektu T3, który jest checkoutem gita z ``origin``; nazwa katalogu jest dowolna."""

    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(
        ["git", "-C", str(path), "remote", "add", "origin", origin], check=True
    )
    return str(path)


def _week(
    thread: str, days: tuple[int, ...]
) -> list[tuple[str, object, str, dict[str, object]]]:
    return [
        _operator(thread, f"2026-11-0{day}T10:00:00.000Z", _zdanie(80 + at))
        for at, day in enumerate(days)
    ]


@pytest.mark.parametrize(
    ("old", "new", "kept", "origin", "name"),
    [
        (
            (3, 4, 4),
            (6, 7, 8),
            6,
            "https://github.com/maximiseartai/MAXIMISEART-Dad.git",
            "narzedzie-taty",
        ),
        (
            (3,),
            (4, 5, 6, 6, 7, 8),
            7,
            "git@github.com:maximiseartai/MAXIMISEART-Dad",
            "MAXIMISEART-Dad-nowy",
        ),
        (
            (),
            (3, 4, 5, 6),
            4,
            "https://github.com/maximiseartai/maximiseart-dad/",
            "maximiseart-dad",
        ),
    ],
    ids=[
        "przeniesienie-w-srode",
        "przeniesienie-w-poniedzialek-po-jednej-wiadomosci",
        "przeniesienie-na-caly-tydzien",
    ],
)
def test_repo_przeniesione_do_checkoutu_pod_inna_nazwa_liczy_sie_w_calosci(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    old: tuple[int, ...],
    new: tuple[int, ...],
    kept: int,
    origin: str,
    name: str,
) -> None:
    """W1 #1914 r5: projekt T3 należy do repo po origin gita, nie po nazwie katalogu, więc repo przeniesione w tygodniu
    do checkoutu o innej nazwie daje pełną liczbę wiadomości operatora ze starego i nowego projektu."""

    agents = [
        _agent(
            COORDINATOR,
            "2026-11-07T09:00:00.000Z",
            _zdanie(79),
            "server",
            notification={"kind": "pull_request"},
        )
    ]
    base = _base(
        tmp_path / "statev2.sqlite",
        [*_week(COORDINATOR, old), *agents, *_week(STRANGER, new)],
        other=_checkout(tmp_path / name, origin),
    )

    code, (*lines, last) = _run(base, capsys)

    assert (code, len(lines)) == (0, kept)
    assert last.startswith(
        f"POPRAWKI OPERATORA OK | tydzień {WEEK}: {kept} wiadomości operatora w "
    )


def test_klon_pod_inna_nazwa_jako_jedyny_projekt_repo_jest_repo(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Klon na og-box w katalogu o innej nazwie i bez starego projektu ``MAXIMISEART-Dad``: wejście jest żywe."""

    clone = _checkout(
        tmp_path / "klon", "https://github.com/maximiseartai/MAXIMISEART-Dad"
    )
    base = _base(
        tmp_path / "statev2.sqlite",
        _week(COORDINATOR, (3, 5)),
        repo=clone,
        other=_checkout(tmp_path / "obcy", "https://github.com/ktos/inne-repo.git"),
    )

    code, (*lines, _) = _run(base, capsys)

    assert (code, len(lines)) == (0, 2)


def test_checkout_z_obcym_origin_nie_jest_repo(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Projekt z origin innego repo (także fork o tej samej nazwie repo) nie liczy się do wątków repo."""

    foreign = _checkout(
        tmp_path / "MAXIMISEART-Dad-fork",
        "https://github.com/ktos/MAXIMISEART-Dad-fork.git",
    )
    base = _base(tmp_path / "statev2.sqlite", _week(STRANGER, (3, 5)), other=foreign)

    code, lines = _run(base, capsys)

    assert (code, lines) == (
        1,
        [
            f"POPRAWKI OPERATORA FAIL | tydzień {WEEK}: 0 wiadomości operatora w wątkach MAXIMISEART-Dad z 0 wiadomości user | inne projekty T3 tej bazy: MAXIMISEART-Dad-fork 2"
        ],
    )


def test_git_dir_odziedziczony_z_hooka_nie_robi_obcego_katalogu_repo(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Narzędzie uruchomione z hooka gita repo dziedziczy ``GIT_DIR`` repo; katalog projektu bez gita dalej nie jest repo."""

    repo_git = (
        Path(
            _checkout(
                tmp_path / "repo",
                "https://github.com/maximiseartai/MAXIMISEART-Dad.git",
            )
        )
        / ".git"
    )
    plain = tmp_path / "zwykly-katalog"
    plain.mkdir()
    monkeypatch.setenv("GIT_DIR", str(repo_git))
    base = _base(tmp_path / "statev2.sqlite", _week(STRANGER, (3,)), other=str(plain))

    code, lines = _run(base, capsys)

    assert code == 1
    assert lines[0].endswith("inne projekty T3 tej bazy: zwykly-katalog 1")
