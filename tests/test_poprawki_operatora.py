"""``tools/poprawki_operatora.py`` wypisuje z transkryptów Claude Code tylko wiadomości, które napisał operator, w tygodniu
czasu polskiego.

Wymaganie bierzemy z jednostki H programu „11 z 11” (polowanie na powtarzane błędy): poprawki Maksa w wątkach agentów,
bez powiadomień o PR, wyników delegatów, pulsów i streszczeń kontekstu. Transkrypty są syntetyczne, w kształcie, w jakim
Claude Code zapisuje je dla wątku T3 Code: jeden rekord JSON na linię w ``<katalog>/<projekt>/<sesja>.jsonl``.
Każdy tekst wiadomości daje ``_zdanie``, a sesje i katalogi są wymyślone, bo repozytorium jest publiczne, a prawdziwe
transkrypty niosą prywatne wiadomości operatora.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import poprawki_operatora

WEEK = "2026-11-09"
COORDINATOR = "-tmp-MAXIMISEART-Dad-koordynator"
CHILD = "-tmp-MAXIMISEART-Dad-dziecko"
OTHER = "-tmp-inny-projekt"
SESSION = "aaaa0001-sesja-koordynatora"


def _zdanie(numer: int) -> str:
    """Wymyślone zdanie wiadomości; różne numery różnią się w pierwszych ``KEY`` znakach."""

    return f"zdanie syntetyczne numer {numer}, którego nikt nie napisał w prawdziwym wątku"


PULSE = _zdanie(3)
RELAY = f"Od wątku B:\n\n{_zdanie(4)}"
BRIEF = _zdanie(5)


def _user(text: object, when: str, **fields: object) -> dict[str, object]:
    return {"type": "user", "entrypoint": "t3-code", "isSidechain": False, "timestamp": when, "message": {"role": "user", "content": text}, **fields}


def _tool(name: str, when: str, **arguments: object) -> dict[str, object]:
    use = {"type": "tool_use", "id": "toolu_1", "name": name, "input": arguments}
    return {"type": "assistant", "entrypoint": "t3-code", "timestamp": when, "message": {"role": "assistant", "content": [use]}}


def _transcript(folder: Path, project: str, session: str, records: list[dict[str, object]]) -> None:
    (folder / project).mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(record, ensure_ascii=False, separators=(",", ":")) for record in records]
    (folder / project / f"{session}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _operator_texts(folder: Path, capsys: pytest.CaptureFixture[str]) -> list[str]:
    assert poprawki_operatora.main(["--tydzien", WEEK, "--katalog", str(folder)]) == 0
    *lines, _ = capsys.readouterr().out.splitlines()
    return [line.split(" | ", 2)[2] for line in lines]


@pytest.fixture
def projects(tmp_path: Path) -> Path:
    folder = tmp_path / "projects"
    _transcript(
        folder,
        COORDINATOR,
        SESSION,
        [
            _user(_zdanie(0), "2026-11-08T22:59:59Z"),
            _user(_zdanie(1), "2026-11-08T23:00:00Z", uuid="u1"),
            _user("<command-message>skill-a</command-message>\n<command-name>/skill-a</command-name>\n<command-args>do końca</command-args>", "2026-11-10T10:00:00Z", uuid="c1"),
            _user(
                [{"type": "text", "text": f"{_zdanie(2)}\nzróbmy /skill-a do końca"}, {"type": "text", "text": "Base directory for this skill: /skill-a"}],
                "2026-11-10T10:00:00Z",
                uuid="m1",
                parentUuid="c1",
                isMeta=True,
                commandTextBlocks={"own": 1, "all": 2},
            ),
            _user("<command-message>skill-b</command-message>\n<command-name>/skill-b</command-name>\n<command-args>#1</command-args>", "2026-11-10T11:00:00Z", uuid="c2"),
            _user("Base directory for this skill: /tmp/skills/skill-b", "2026-11-10T11:00:01Z", isMeta=True),
            _user("Update on pull request #1 (https://github.com/o/r/pull/1), which T3 Code is watching for you:", "2026-11-10T12:00:00Z"),
            _user(f"Delegated task node:delegated-task:command%3Amcp (A) [completed]:\n{_zdanie(10)}", "2026-11-10T12:01:00Z"),
            _user("This session is being continued from a previous conversation that ran out of context.", "2026-11-10T12:02:00Z", isCompactSummary=True),
            _user("<task-notification> <task-id>a1</task-id> zakończone", "2026-11-10T12:03:00Z"),
            _user([{"type": "tool_result", "tool_use_id": "toolu_1", "content": _zdanie(11)}], "2026-11-10T12:04:00Z"),
            _user(_zdanie(12), "2026-11-10T12:05:00Z", isSidechain=True),
            _user(PULSE, "2026-11-10T12:06:00Z"),
            _user(RELAY, "2026-11-10T12:07:00Z"),
            _tool("mcp__t3-code__schedule_task", "2026-11-01T08:00:00Z", title="Puls", prompt=f"{PULSE} Odpowiedz jednym zdaniem."),
            _tool("mcp__t3-code__delegate_task", "2026-11-10T12:08:00Z", title="H", task=BRIEF),
            _user("tak", "2026-11-15T22:59:59Z"),
            _user(_zdanie(13), "2026-11-15T23:00:00Z"),
        ],
    )
    _transcript(
        folder,
        CHILD,
        "bbbb0002-sesja-dziecka",
        [
            _user(f"Act as the implementation sub-agent for this task.\n\n{_zdanie(14)}", "2026-11-10T12:09:00Z"),
            _user(f"Kontekst:\n\n{BRIEF}", "2026-11-10T12:10:00Z"),
        ],
    )
    _transcript(folder, OTHER, "cccc0003-sesja-innego", [_tool("mcp__t3-code__t3_thread_send", "2026-11-10T12:06:30Z", threadId="t", message=RELAY)])
    _transcript(folder, f"{COORDINATOR}-proba", "dddd0004", [_user("Run the command.", "2026-11-10T13:00:00Z", entrypoint="sdk-cli")])
    return folder


def test_tydzien_daje_tylko_wiadomosci_operatora_z_tekstem_wpisanym_przy_komendzie(projects: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert poprawki_operatora.main(["--tydzien", "2026-11-12", "--katalog", str(projects)]) == 0

    *lines, last = capsys.readouterr().out.splitlines()
    assert lines == [
        f"2026-11-09 00:00 | koordynator/aaaa0001 | {_zdanie(1)}",
        f"2026-11-10 11:00 | koordynator/aaaa0001 | {_zdanie(2)} / zróbmy /skill-a do końca",
        "2026-11-10 12:00 | koordynator/aaaa0001 | /skill-b #1",
        "2026-11-15 23:59 | koordynator/aaaa0001 | tak",
    ]
    assert last == (
        f"POPRAWKI OPERATORA OK | tydzień {WEEK}: 4 wiadomości operatora w 1 wątkach z 15 rekordów w 3 transkryptach | "
        "sesje bez operatora 1, streszczenia kontekstu 1, harness 2, powiadomienia PR 1, wyniki delegatów 1, "
        "wiadomości agentów 4, kopie komend 1"
    )


def test_tekst_operatora_przekazany_dalej_dopiero_po_nim_zostaje_wiadomoscia_operatora(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _transcript(
        tmp_path,
        COORDINATOR,
        SESSION,
        [
            _user(_zdanie(6), "2026-11-10T10:00:00Z"),
            _tool("mcp__t3-code__delegate_task", "2026-11-10T10:01:00Z", title="X", task=f"{_zdanie(6)}\n\nKontekst"),
        ],
    )

    assert _operator_texts(tmp_path, capsys) == [_zdanie(6)]


def test_tekst_wyslany_poleceniem_bash_t3_thread_send_jest_wiadomoscia_agenta(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    command = f"cd /tmp && ~/.t3/bin/t3 thread send --json watek-a '{_zdanie(7)}'; echo wysłane"
    _transcript(tmp_path, OTHER, "cccc0003", [_tool("Bash", "2026-11-10T09:59:00Z", command=command)])
    _transcript(tmp_path, COORDINATOR, SESSION, [_user(_zdanie(7), "2026-11-10T10:00:00Z")])

    assert _operator_texts(tmp_path, capsys) == []


def test_wiadomosc_zaczeta_wyslanym_tekstem_zostaje_z_czescia_dopisana_przez_operatora(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _transcript(tmp_path, OTHER, "cccc0003", [_tool("mcp__t3-code__t3_thread_send", "2026-11-10T09:00:00Z", threadId="a", message=_zdanie(7))])
    _transcript(tmp_path, COORDINATOR, SESSION, [_user(f"{_zdanie(7)}\n\n{_zdanie(8)}", "2026-11-10T10:00:00Z")])

    assert _operator_texts(tmp_path, capsys) == [_zdanie(8)]


def test_tekst_skrocony_do_limitu_znakow_mowi_ile_mial_znakow(projects: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert poprawki_operatora.main(["--tydzien", WEEK, "--katalog", str(projects), "--znaki", "10"]) == 0

    assert f"| {_zdanie(1)[:10]}… ({len(_zdanie(1))} zn.)" in capsys.readouterr().out.splitlines()[0]


def test_brak_katalogu_konczy_sie_porazka_z_jego_nazwa(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert poprawki_operatora.main(["--tydzien", WEEK, "--katalog", str(tmp_path / "brak")]) == 1

    assert capsys.readouterr().out == f"POPRAWKI OPERATORA FAIL | brak katalogu: {tmp_path / 'brak'}\n"
