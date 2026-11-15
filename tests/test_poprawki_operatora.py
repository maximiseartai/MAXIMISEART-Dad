"""``tools/poprawki_operatora.py`` wypisuje z bazy T3 Code tylko wiadomości, które operator napisał w oknie T3, z wątków
repo w tygodniu czasu polskiego.

Wymaganie bierzemy z jednostki H programu „11 z 11” (polowanie na powtarzane błędy): poprawki Maksa w wątkach agentów,
bez tekstu, który do wątku włożył agent, zadanie T3 albo serwer. Baza jest syntetyczna, w kształcie bazy stanu serwera
T3 w tym, co narzędzie czyta: tabele projektów, wątków i wiadomości, a w ``payload_json`` wiadomości pola nadawcy
``createdBy`` i ``creationSource`` z kontraktu ``orchestrationV2``. Teksty wiadomości są wymyślone (zdania z
``_zdanie`` i krótkie teksty wpisane w teście, jak ``/compact`` i „tak”), a identyfikatory wątków i katalogi projektów
też, bo repozytorium jest publiczne, a prawdziwa baza niesie prywatne wiadomości operatora.
"""

from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3

import pytest

import poprawki_operatora

WEEK = "2026-11-09"
REPO = "/tmp/projekty/MAXIMISEART-Dad"
OTHER = "/tmp/projekty/inny-projekt"
COORDINATOR = "watek-koordynatora"
CHILD = "watek-dziecka"
STRANGER = "watek-innego-projektu"
SCHEMA = """
CREATE TABLE projection_projects (project_id TEXT PRIMARY KEY, workspace_root TEXT NOT NULL);
CREATE TABLE orchestration_v2_projection_threads (thread_id TEXT PRIMARY KEY, project_id TEXT NOT NULL);
CREATE TABLE orchestration_v2_projection_messages (
  message_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, role TEXT NOT NULL, created_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
"""


def _zdanie(numer: int) -> str:
    return f"zdanie syntetyczne numer {numer}, którego nikt nie napisał w prawdziwym wątku"


def _operator(thread: str, when: str, text: str, source: str = "web") -> tuple[str, str, str, dict[str, object]]:
    return thread, when, "user", {"createdBy": "user", "creationSource": source, "text": text}


def _agent(thread: str, when: str, text: str, source: str, **fields: object) -> tuple[str, str, str, dict[str, object]]:
    return thread, when, "user", {"createdBy": "agent", "creationSource": source, "text": text, **fields}


def _base(path: Path, messages: list[tuple[str, str, str, dict[str, object]]]) -> Path:
    with closing(sqlite3.connect(path)) as db:
        db.executescript(SCHEMA)
        db.executemany("INSERT INTO projection_projects VALUES (?, ?)", [("p-repo", REPO), ("p-inny", OTHER)])
        threads = [(COORDINATOR, "p-repo"), (CHILD, "p-repo"), ("watek-b", "p-repo"), ("watek-c", "p-repo"), (STRANGER, "p-inny")]
        db.executemany("INSERT INTO orchestration_v2_projection_threads VALUES (?, ?)", threads)
        rows = [(f"m{at}", thread, role, when, json.dumps(payload, ensure_ascii=False)) for at, (thread, when, role, payload) in enumerate(messages)]
        db.executemany("INSERT INTO orchestration_v2_projection_messages VALUES (?, ?, ?, ?, ?)", rows)
        db.commit()
    return path


def _run(base: Path, capsys: pytest.CaptureFixture[str], *extra: str) -> tuple[int, list[str]]:
    code = poprawki_operatora.main(["--tydzien", WEEK, "--baza", str(base), *extra])
    return code, capsys.readouterr().out.splitlines()


@pytest.fixture
def week_base(tmp_path: Path) -> Path:
    return _base(
        tmp_path / "statev2.sqlite",
        [
            _operator(COORDINATOR, "2026-11-08T22:59:59.999Z", _zdanie(0)),
            _operator(COORDINATOR, "2026-11-08T23:00:00.000Z", _zdanie(1)),
            _operator(COORDINATOR, "2026-11-10T10:00:00.000Z", f"{_zdanie(2)}\n\nzróbmy to jeszcze raz", source="mobile"),
            (COORDINATOR, "2026-11-10T10:00:30.000Z", "assistant", {"text": _zdanie(3)}),
            (COORDINATOR, "2026-11-10T11:00:00.000Z", "user", {"createdBy": "user", "creationSource": "web", "text": "/compact", "idleCompaction": "onReturn"}),
            (COORDINATOR, "2026-11-10T11:01:00.000Z", "user", {"createdBy": "user", "creationSource": "server", "text": _zdanie(4)}),
            _agent(COORDINATOR, "2026-11-10T12:00:00.000Z", _zdanie(5), "mcp", senderThreadId=CHILD),
            _agent(COORDINATOR, "2026-11-10T12:01:00.000Z", _zdanie(6), "mcp"),
            _agent(COORDINATOR, "2026-11-10T12:02:00.000Z", _zdanie(7), "server", notification={"kind": "pull_request"}),
            _agent(CHILD, "2026-11-10T12:03:00.000Z", _zdanie(8), "mcp", senderThreadId=COORDINATOR),
            _agent(CHILD, "2026-11-10T12:04:00.000Z", _zdanie(9), "provider", senderThreadId=COORDINATOR),
            _operator(STRANGER, "2026-11-10T12:05:00.000Z", _zdanie(10)),
            _operator(CHILD, "2026-11-15T22:59:59.999Z", "tak"),
            _operator(CHILD, "2026-11-15T23:00:00.000Z", _zdanie(11)),
        ],
    )


def test_tydzien_daje_tylko_wiadomosci_napisane_w_oknie_t3_w_watkach_repo(week_base: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, (*lines, last) = _run(week_base, capsys)

    assert code == 0
    assert lines == [
        f"2026-11-09 00:00 | {COORDINATOR} | {_zdanie(1)}",
        f"2026-11-10 11:00 | {COORDINATOR} | {_zdanie(2)} / zróbmy to jeszcze raz",
        f"2026-11-15 23:59 | {CHILD} | tak",
    ]
    assert last == (
        f"POPRAWKI OPERATORA OK | tydzień {WEEK}: 3 wiadomości operatora w 2 wątkach z 10 wiadomości user | "
        "/compact po powrocie 1, agent/mcp 3, agent/provider 1, agent/server 1, user/server 1"
    )


def test_poprawka_wklejona_do_dwoch_watkow_zostaje_w_obu_choc_agent_przekazal_ja_miedzy_wklejeniami(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fix = _zdanie(20)
    base = _base(
        tmp_path / "statev2.sqlite",
        [
            _agent("watek-c", "2026-11-10T09:00:00.000Z", fix, "mcp", senderThreadId=CHILD),
            _operator(COORDINATOR, "2026-11-10T10:00:00.000Z", fix),
            _agent(CHILD, "2026-11-10T10:01:00.000Z", f"{fix}\n\nKontekst", "mcp", senderThreadId=COORDINATOR),
            _operator("watek-b", "2026-11-10T10:05:00.000Z", fix),
        ],
    )

    code, (*lines, _) = _run(base, capsys)

    assert code == 0
    assert lines == [f"2026-11-10 11:00 | {COORDINATOR} | {fix}", f"2026-11-10 11:05 | watek-b | {fix}"]


@pytest.mark.parametrize(
    "payload",
    [{"creationSource": "web", "text": "tak"}, {"createdBy": "user", "creationSource": "terminal", "text": "tak"}],
    ids=["bez-createdBy", "zrodlo-spoza-kontraktu"],
)
def test_wiadomosc_z_nadawca_spoza_kontraktu_t3_konczy_sie_porazka_zamiast_cichego_pominiecia(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], payload: dict[str, object]
) -> None:
    base = _base(tmp_path / "statev2.sqlite", [_operator(COORDINATOR, "2026-11-10T10:00:00.000Z", _zdanie(1)), (COORDINATOR, "2026-11-10T10:01:00.000Z", "user", payload)])

    code, lines = _run(base, capsys)

    assert (code, len(lines)) == (1, 1)
    assert lines[0].startswith(f"POPRAWKI OPERATORA FAIL | baza T3 {base}: ")


@pytest.mark.parametrize("foreign", [True, False], ids=["baza-bez-tabel-t3", "brak-bazy"])
def test_baza_ktorej_narzedzie_nie_przeczyta_konczy_sie_porazka_z_jej_nazwa(tmp_path: Path, capsys: pytest.CaptureFixture[str], foreign: bool) -> None:
    base = tmp_path / "statev2.sqlite"
    if foreign:
        with closing(sqlite3.connect(base)) as db:
            db.execute("CREATE TABLE notatki (tekst TEXT)")
            db.commit()

    code, lines = _run(base, capsys)

    assert (code, len(lines)) == (1, 1)
    assert lines[0].startswith("POPRAWKI OPERATORA FAIL | ")
    assert str(base) in lines[0]


def test_tekst_skrocony_do_limitu_znakow_mowi_ile_mial_znakow(week_base: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _, lines = _run(week_base, capsys, "--znaki", "10")

    assert lines[0].endswith(f"| {_zdanie(1)[:10]}… ({len(_zdanie(1))} zn.)")
