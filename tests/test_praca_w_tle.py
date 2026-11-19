"""Hook ``tools/hooks/praca_w_tle.py`` i jego wyrocznia: agent nie kończy tury, dopóki w tle biegnie jego Bash albo Monitor.

Wejścia mają kształt wejścia hooka ``Stop`` z Claude Code 2.1.318: ``REAL`` to zapis z próby ``claude -p``, które
uruchomiło ``sleep 60`` z ``run_in_background`` i skończyło turę (5.11.2026), a pozostałe zadania mają pola, które
budowa ``background_tasks`` w binarce 2.1.318 podaje dla ich typu. Wejścia hooka ``PostToolUse`` (``SUBAGENT_BASH``,
``SUBAGENT_MONITOR``, ``REGISTERED``) to zapisy z prób ``claude -p`` 2.1.328 z fałszywym API (19.11.2026) ze ścieżkami
i ID zadania podmienionymi na te z ``REAL``. Każdy test hooka uruchamia go tak jak Claude Code: JSON na stdin, a
odmowa to ``{"decision": "block", "reason": …}`` na stdout z kodem 0. Dziennik i pliki sesji hooka leżą w katalogu
domowym, więc każdy test ma własny. Wyrocznię ``tools/wyrocznia_pracy_w_tle.py`` test uruchamia z atrapą ``claude``,
która woła API pod adresem, jaki wybrałby Claude Code (``tests/fixtures/ustawienia_claude.py``), uruchamia hooki
``Stop`` i ``PostToolUse`` z ``.claude/settings.json``, podagenta narzędzia Agent i narzędzie MCP, a po turze bez
odmowy budzi sesję powiadomieniem o końcu zadania głównej pętli, jak Claude Code 2.1.328.
"""

from __future__ import annotations

from collections.abc import Mapping
import contextlib
from datetime import datetime, timedelta
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import ModuleType

import pytest

from tests.fixtures import ustawienia_claude
from tests.fixtures.fake_cli import fake_cli

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "tools" / "hooks" / "praca_w_tle.py"
ORACLE = ROOT / "tools" / "wyrocznia_pracy_w_tle.py"
WAITING_HOOK = ROOT / "tools" / "hooks" / "czekanie.py"
FAKE_T3 = ROOT / "tools" / "lib" / "falszywy_t3.py"
SETTINGS = ROOT / ".claude" / "settings.json"
POSIX_ONLY = pytest.mark.skipif(sys.platform == "win32", reason="python3 na Windows bywa aliasem Microsoft Store")

REAL = {
    "session_id": "b5d0e779-cb12-469b-9516-93c36c6d73af",
    "transcript_path": "/Users/Max/.claude/projects/-Users-Max--t3-notes-stop-hook-probe/b5d0e779-cb12-469b-9516-93c36c6d73af.jsonl",
    "cwd": "/Users/Max/.t3/notes/stop-hook/probe",
    "prompt_id": "2c818263-64a6-44c3-90a0-fa0641827000",
    "permission_mode": "bypassPermissions",
    "effort": {"level": "medium"},
    "hook_event_name": "Stop",
    "stop_hook_active": False,
    "last_assistant_message": "STARTED",
    "background_tasks": [
        {
            "id": "bi6lxbxlb",
            "type": "shell",
            "status": "running",
            "description": "Run sleep 60 in background",
            "command": "sleep 60",
        }
    ],
    "session_crons": [],
}
SHELL = REAL["background_tasks"][0]  # type: ignore[index]
# Narzędzie Monitor tworzy zadanie local_bash, a hook dostaje je jako shell z poleceniem, jak Bash z run_in_background.
AGENT_MONITOR = {
    "id": "bm1",
    "type": "shell",
    "status": "running",
    "description": "Logi CI",
    "command": "tail -f ci.log | grep --line-buffered FAIL",
}
# Obserwacja artefaktu (monitor_ws), którą Claude Code włącza sam po publikacji: hook nie dostaje pola ambient.
ARTIFACT_WATCH = {"id": "wsx1", "type": "monitor", "status": "running", "description": "Watching artifact comments"}
MCP_MONITOR = {"id": "m1", "type": "monitor", "status": "running", "description": "CI logs", "server": "x", "tool": "y"}
SUBAGENT = {
    "id": "a1",
    "type": "subagent",
    "status": "running",
    "description": "przegląd",
    "agent_type": "general-purpose",
}


POST = {
    "session_id": REAL["session_id"],
    "transcript_path": REAL["transcript_path"],
    "cwd": REAL["cwd"],
    "prompt_id": "654ab1d2-5c8d-4249-8d3a-7ffca27380e6",
    "permission_mode": "bypassPermissions",
    "effort": {"level": "medium"},
    "hook_event_name": "PostToolUse",
}
SUBAGENT_BASH = {
    **POST,
    "agent_id": "a7918e90976a301e0",
    "agent_type": "general-purpose",
    "tool_name": "Bash",
    "tool_input": {"command": "sleep 60", "description": "Run sleep 60 in background", "run_in_background": True},
    "tool_response": {
        "stdout": "",
        "stderr": "",
        "interrupted": False,
        "isImage": False,
        "noOutputExpected": False,
        "backgroundTaskId": "bi6lxbxlb",
    },
    "tool_use_id": "toolu_2",
    "duration_ms": 236,
}
SUBAGENT_MONITOR = {
    **POST,
    "agent_id": "a5b7fa5dc3a07d45d",
    "agent_type": "general-purpose",
    "tool_name": "Monitor",
    "tool_input": {"description": "Monitor podagenta", "timeout_ms": 60000, "command": "sleep 60"},
    "tool_response": {"taskId": "bi6lxbxlb", "timeoutMs": 60000, "persistent": False},
    "tool_use_id": "toolu_2",
    "duration_ms": 282,
}
MAIN_BASH = {key: value for key, value in SUBAGENT_BASH.items() if key not in ("agent_id", "agent_type")}
REGISTERED = {
    **POST,
    "tool_name": "mcp__t3-code__t3_background_wait",
    "tool_input": {"taskIds": ["bi6lxbxlb"]},
    "tool_response": [{"type": "text", "text": '{"matched": ["bi6lxbxlb"], "unmatched": []}'}],
    "tool_use_id": "toolu_2",
    "duration_ms": 9,
    "mcp_server": {"name": "t3-code", "source": "dynamic"},
}
UNREGISTERED = {**REGISTERED, "tool_input": {"taskIds": ["bi6lxbxlb"], "waiting": False}}


def _load(path: Path) -> ModuleType:
    """Hook z pliku jako moduł, zapisany w ``sys.modules``, bo dataclass hooka szuka tam swojego modułu."""

    spec = importlib.util.spec_from_file_location(f"test_praca_w_tle_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _stop(tasks: object, **fields: object) -> str:
    return json.dumps({**REAL, "background_tasks": tasks, **fields})


def _hook(stdin: str | bytes, home: Path) -> subprocess.CompletedProcess[bytes]:
    data = stdin.encode("utf-8") if isinstance(stdin, str) else stdin
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home)}
    return subprocess.run([sys.executable, str(HOOK)], input=data, capture_output=True, env=env, check=False)


def _reason(hooked: subprocess.CompletedProcess[bytes]) -> str:
    assert (hooked.returncode, hooked.stderr) == (0, b"")
    decision = json.loads(hooked.stdout)
    assert decision["decision"] == "block"
    return str(decision["reason"])


def _log(home: Path) -> list[dict[str, object]]:
    path = home / ".cache" / "maximiseart" / "praca_w_tle.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def test_zapis_wejscia_claude_code_z_sleep_w_tle_zatrzymuje_koniec_tury_i_trafia_do_dziennika(tmp_path: Path) -> None:
    """Odmowa podaje jedną drogę czekania na zadanie: ``t3_background_wait`` z ID z odmowy w liście ``taskIds``, bo
    ``taskId`` pada (#2267), i koniec tury."""

    reason = _reason(_hook(json.dumps(REAL), tmp_path))

    assert "shell bi6lxbxlb „sleep 60”" in reason
    assert 't3_background_wait z taskIds: ["bi6lxbxlb"]' in reason
    assert _load(WAITING_HOOK).WAIT_FOR_TASK in reason
    assert "serwer), zatrzymaj jako zadanie i uruchom odłączony (nohup … & w Bashu na pierwszym planie)" in reason
    (row,) = _log(tmp_path)
    assert datetime.fromisoformat(str(row.pop("czas"))).utcoffset() == timedelta(0)
    assert row == {
        "decyzja": "odmowa",
        "szczegoly": ["shell bi6lxbxlb „sleep 60”"],
        "session_id": REAL["session_id"],
        "prompt_id": REAL["prompt_id"],
        "cwd": REAL["cwd"],
        "stop_hook_active": False,
    }


@pytest.mark.parametrize(
    ("tasks", "named"),
    [
        ([AGENT_MONITOR], ["shell bm1 „tail -f ci.log | grep --line-buffered FAIL”"]),
        ([{**SHELL, "status": "pending"}], ["shell bi6lxbxlb"]),
        ([SUBAGENT, SHELL, AGENT_MONITOR, ARTIFACT_WATCH], ["shell bi6lxbxlb", "shell bm1"]),
        ([{"id": "b3", "type": "shell", "status": "running", "description": "Sen w tle"}], ["shell b3 „Sen w tle”"]),
    ],
    ids=["monitor-agenta", "pending", "zywe-bash-i-monitor-obok-podagenta-i-obserwacji-artefaktu", "bez-polecenia"],
)
def test_zywe_zadanie_basha_albo_monitor_agenta_w_tle_zatrzymuje_koniec_tury(
    tmp_path: Path, tasks: list[object], named: list[str]
) -> None:
    reason = _reason(_hook(_stop(tasks), tmp_path))

    assert [name in reason for name in named] == [True] * len(named)
    assert ["a1" in reason, "wsx1" in reason] == [False, False]


def test_odmowa_trwa_takze_przy_stop_hook_active_dopoki_zadanie_zyje(tmp_path: Path) -> None:
    # Claude Code zostawia stop_hook_active do końca tury także po narzędziach; pętlę ucina sam po 8 odmowach z rzędu.
    reason = _reason(_hook(_stop([SHELL], stop_hook_active=True), tmp_path))

    assert "shell bi6lxbxlb" in reason
    assert [row["stop_hook_active"] for row in _log(tmp_path)] == [True]


def _session_file(home: Path, session: str = str(REAL["session_id"])) -> Path:
    return home / ".cache" / "maximiseart" / "praca_w_tle" / f"{session}.jsonl"


def _quietly(hooked: subprocess.CompletedProcess[bytes]) -> None:
    assert (hooked.returncode, hooked.stdout, hooked.stderr) == (0, b"", b"")


@pytest.mark.parametrize(
    ("posts", "reason"),
    [
        ([SUBAGENT_BASH], "zadanie podagenta a7918e90976a301e0"),
        ([SUBAGENT_MONITOR], "zadanie podagenta a5b7fa5dc3a07d45d"),
        ([REGISTERED], "zarejestrowany w t3_background_wait"),
        ([UNREGISTERED, REGISTERED], "zarejestrowany w t3_background_wait"),
    ],
    ids=["bash-podagenta", "monitor-podagenta", "zarejestrowany", "zarejestrowany-po-wypisaniu"],
)
def test_shell_podagenta_i_zadanie_zarejestrowane_przepuszczaja_koniec_tury_z_powodem_w_dzienniku(
    tmp_path: Path, posts: list[dict[str, object]], reason: str
) -> None:
    """Claude Code 2.1.328 podaje hookowi Stop shell podagenta bez pola, które go odróżnia (wyrocznia, przypadek
    shell-podagenta), więc przepuszcza go plik sesji z hooka ``PostToolUse``."""

    for post in posts:
        _quietly(_hook(json.dumps(post), tmp_path))

    _quietly(_hook(json.dumps(REAL), tmp_path))
    assert [(row["decyzja"], row["szczegoly"]) for row in _log(tmp_path)] == [
        ("przepuszczam", [f"shell bi6lxbxlb „sleep 60” przepuszczony: {reason}"])
    ]


@pytest.mark.parametrize(
    "posts",
    [
        [MAIN_BASH],
        [REGISTERED, UNREGISTERED],
        [{**SUBAGENT_BASH, "tool_response": {"stdout": "gotowe", "stderr": "", "interrupted": False}}],
        [{**REGISTERED, "tool_input": {"taskId": "bi6lxbxlb"}}],
        [{**REGISTERED, "tool_input": {"taskIds": ["b2"]}}],
        [{**REGISTERED, "session_id": "inna-sesja"}],
        [{**REGISTERED, "session_id": f"../praca_w_tle/{REAL['session_id']}"}],
        [{**SUBAGENT_BASH, "hook_event_name": "PreToolUse"}],
    ],
    ids=[
        "bash-glownej-petli",
        "wypisany-z-rejestracji",
        "bash-podagenta-na-pierwszym-planie",
        "taskId-zamiast-taskIds",
        "inne-zadanie",
        "inna-sesja",
        "sesja-spoza-wzorca",
        "przed-narzedziem",
    ],
)
def test_wlasny_shell_glownej_petli_bez_rejestracji_zatrzymuje_koniec_tury(
    tmp_path: Path, posts: list[dict[str, object]]
) -> None:
    """Próbka ``sesja-spoza-wzorca`` ma ID sesji, które jako ścieżka wskazałoby plik sesji ``REAL``."""

    for post in posts:
        assert _hook(json.dumps(post), tmp_path).returncode == 0

    assert "shell bi6lxbxlb „sleep 60”" in _reason(_hook(json.dumps(REAL), tmp_path))


def test_rejestracja_w_t3_background_wait_obejmuje_tylko_zadania_z_listy(tmp_path: Path) -> None:
    other = {"id": "b2", "type": "shell", "status": "running", "description": "Drugi sen", "command": "sleep 90"}
    _quietly(_hook(json.dumps(REGISTERED), tmp_path))

    reason = _reason(_hook(_stop([SHELL, other]), tmp_path))

    assert ["shell b2 „sleep 90”" in reason, 't3_background_wait z taskIds: ["b2"]' in reason] == [True, True]
    assert "shell bi6lxbxlb „sleep 60”" not in reason.split(". ")[0]


def test_pliki_sesji_starsze_niz_tydzien_znikaja_przy_dopisaniu(tmp_path: Path) -> None:
    old, young = _session_file(tmp_path, "stara"), _session_file(tmp_path, "mloda")
    old.parent.mkdir(parents=True)
    for path, days in ((old, 8), (young, 6)):
        path.write_text('{"id": "b9", "przepuszczam": true, "powod": "x"}\n', encoding="utf-8")
        moment = time.time() - days * 24 * 3600
        os.utime(path, (moment, moment))

    _quietly(_hook(json.dumps(REGISTERED), tmp_path))

    assert sorted(path.name for path in old.parent.iterdir()) == sorted(["mloda.jsonl", f"{REAL['session_id']}.jsonl"])


@pytest.mark.parametrize(
    ("content", "said"),
    [
        (b"\xff\xfe{", b"plik sesji nieczytelny"),
        (b'nie json\n["bi6lxbxlb"]\n{"id": "bi6lxbxlb", "przepuszczam": "tak"}\n', b""),
    ],
    ids=["nie-utf8", "linie-innej-postaci"],
)
def test_plik_sesji_innej_postaci_nie_przepuszcza_zadania(tmp_path: Path, content: bytes, said: bytes) -> None:
    path = _session_file(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(content)

    hooked = _hook(json.dumps(REAL), tmp_path)

    assert json.loads(hooked.stdout)["decision"] == "block"
    assert (hooked.returncode, said in hooked.stderr) == (0, True)


def test_niedostepny_katalog_plikow_sesji_nie_zatrzymuje_narzedzia(tmp_path: Path) -> None:
    (tmp_path / ".cache" / "maximiseart").mkdir(parents=True)
    (tmp_path / ".cache" / "maximiseart" / "praca_w_tle").write_text("plik zamiast katalogu", encoding="utf-8")

    hooked = _hook(json.dumps(REGISTERED), tmp_path)

    assert (hooked.returncode, hooked.stdout, b"praca_w_tle: plik sesji niedost" in hooked.stderr) == (0, b"", True)


# Typy z budowy background_tasks w binarce 2.1.318, które same raportują wywołującemu (REPORTING hooka).
REPORTING = (
    "subagent",
    "workflow",
    "MCP task",
    "teammate",
    "dream",
    "auto-mode scan",
    "memory import",
    "memory save",
    "cloud session",
)


@pytest.mark.parametrize(
    "tasks",
    [
        [],
        [
            SUBAGENT,
            {"id": "w1", "type": "workflow", "status": "running", "name": "x"},
            {"id": "t1", "type": "MCP task", "status": "running"},
        ],
        *[[{"id": "r1", "type": kind, "status": status}] for kind in REPORTING for status in ("running", "pending")],
    ],
    ids=[
        "pusta-lista",
        "podagent-workflow-zadanie-mcp",
        *[f"{kind}-{status}" for kind in REPORTING for status in ("running", "pending")],
    ],
)
def test_bez_basha_ani_monitora_w_tle_tura_konczy_sie_bez_slowa_i_bez_dziennika(
    tmp_path: Path, tasks: list[object]
) -> None:
    hooked = _hook(_stop(tasks), tmp_path)

    assert (hooked.returncode, hooked.stdout, hooked.stderr) == (0, b"", b"")
    assert _log(tmp_path) == []


@pytest.mark.parametrize(
    ("tasks", "doubt"),
    [
        ([{**SHELL, "status": "completed"}], "shell bi6lxbxlb o nieznanym statusie 'completed'"),
        (
            [{**SHELL, "status": None}],
            "zadanie bi6lxbxlb z type 'shell' i status None, z których nie każde jest tekstem",
        ),
        (
            [{**SHELL, "type": ["shell"]}],
            "zadanie bi6lxbxlb z type ['shell'] i status 'running', z których nie każde jest tekstem",
        ),
        (
            [{**SHELL, "status": ["running"]}],
            "zadanie bi6lxbxlb z type 'shell' i status ['running'], z których nie każde jest tekstem",
        ),
        (["shell"], "wpis listy zadań nie jest obiektem: str"),
        ({"0": SHELL}, "wejście bez listy background_tasks"),
    ],
    ids=["status-skonczony", "bez-statusu", "type-lista", "status-lista", "wpis-nie-obiekt", "lista-nie-lista"],
)
def test_watpliwosc_przepuszcza_koniec_tury_i_trafia_do_dziennika(tmp_path: Path, tasks: object, doubt: str) -> None:
    hooked = _hook(_stop(tasks), tmp_path)

    assert (hooked.returncode, hooked.stdout, hooked.stderr) == (0, b"", b"")
    assert [(row["decyzja"], row["szczegoly"]) for row in _log(tmp_path)] == [("przepuszczam", [doubt])]


WATCHED = "przepuszczony: typ monitor ma też obserwacja artefaktu, której Claude Code nie odróżnia w wejściu hooka"


@pytest.mark.parametrize(
    ("tasks", "doubts"),
    [
        ([ARTIFACT_WATCH], [f"monitor wsx1 „Watching artifact comments” (running) {WATCHED}"]),
        ([{**MCP_MONITOR, "status": "pending"}, SUBAGENT], [f"monitor m1 „CI logs” (pending) {WATCHED}"]),
        (
            [{"id": "n1", "type": "nowy typ", "status": "running"}],
            ["nowy typ n1 (running) przepuszczony: nieznany typ zadania"],
        ),
    ],
    ids=["obserwacja-artefaktu", "monitor-mcp-obok-podagenta", "nieznany-typ"],
)
def test_monitor_i_nieznany_typ_w_tle_przepuszczaja_koniec_tury_z_powodem_w_dzienniku(
    tmp_path: Path, tasks: list[dict[str, object]], doubts: list[str]
) -> None:
    # Po publikacji artefaktu Claude Code 2.1.318 sam obserwuje go do końca sesji jako monitor (recenzja #955, r1).
    hooked = _hook(_stop(tasks), tmp_path)

    assert (hooked.returncode, hooked.stdout, hooked.stderr) == (0, b"", b"")
    assert [(row["decyzja"], row["szczegoly"]) for row in _log(tmp_path)] == [("przepuszczam", doubts)]


def test_watpliwosc_obok_zywego_zadania_nie_znosi_odmowy(tmp_path: Path) -> None:
    _reason(_hook(_stop([{**SHELL, "id": "b2", "status": "dziwny"}, ARTIFACT_WATCH, SHELL]), tmp_path))

    assert [row["szczegoly"] for row in _log(tmp_path)] == [
        [
            "shell bi6lxbxlb „sleep 60”",
            "shell b2 o nieznanym statusie 'dziwny'",
            f"monitor wsx1 „Watching artifact comments” (running) {WATCHED}",
        ]
    ]


@pytest.mark.parametrize(
    ("stdin", "doubt"),
    [
        ("", "nieczytelne wejście: JSONDecodeError"),
        (b"\xff\xfe{", "nieczytelne wejście: UnicodeDecodeError"),
        ("null", "wejście bez listy background_tasks"),
        (json.dumps({"hook_event_name": "Stop", "stop_hook_active": False}), "wejście bez listy background_tasks"),
    ],
    ids=["pusto", "nie-utf8", "null", "bez-background-tasks"],
)
def test_nieczytelne_wejscie_hooka_przechodzi_i_trafia_do_dziennika(
    tmp_path: Path, stdin: str | bytes, doubt: str
) -> None:
    hooked = _hook(stdin, tmp_path)

    assert (hooked.returncode, hooked.stdout) == (0, b"")
    assert [(row["decyzja"], row["szczegoly"]) for row in _log(tmp_path)] == [("przepuszczam", [doubt])]


def test_json_glebszy_niz_stos_pythona_przechodzi_i_trafia_do_dziennika(tmp_path: Path) -> None:
    # Na macOS dekoder rzuca RecursionError, a na Linuksie z Pythonem 3.14 JSONDecodeError (CI #955): oba to wątpliwość.
    hooked = _hook("[" * 100000, tmp_path)

    assert (hooked.returncode, hooked.stdout) == (0, b"")
    (row,) = _log(tmp_path)
    details = row["szczegoly"]
    assert isinstance(details, list)
    assert (row["decyzja"], [str(detail).startswith("nieczytelne wejście: ") for detail in details]) == (
        "przepuszczam",
        [True],
    )


def test_rekursja_dekodera_jak_na_macos_przechodzi_i_trafia_do_dziennika(tmp_path: Path) -> None:
    # Dekoder JSON z macOS rzuca RecursionError na zbyt głębokim wejściu, a Linux z Pythonem 3.14 nie, więc test
    # podaje hookowi dekoder, który rzuca jak na macOS, na każdym systemie.
    broken = (
        f"import json, runpy, sys\n"
        f"def loads(*args, **kwargs): raise RecursionError('maximum recursion depth exceeded')\n"
        f"json.loads = loads\n"
        f"sys.argv = [{str(HOOK)!r}]\n"
        f"runpy.run_path({str(HOOK)!r}, run_name='__main__')\n"
    )
    env = {**os.environ, "HOME": str(tmp_path), "USERPROFILE": str(tmp_path)}

    hooked = subprocess.run(
        [sys.executable, "-c", broken], input=json.dumps(REAL).encode("utf-8"), capture_output=True, env=env, check=False
    )

    assert (hooked.returncode, hooked.stdout) == (0, b"")
    assert [(row["decyzja"], row["szczegoly"]) for row in _log(tmp_path)] == [
        ("przepuszczam", ["nieczytelne wejście: RecursionError"])
    ]


def test_kolejne_konce_tury_dopisuja_sie_do_dziennika_czytelnego_bez_dekodowania(tmp_path: Path) -> None:
    # Dziennik czyta się jako tekst (grep, edytor), więc polskie litery i cudzysłowy stoją w nim wprost, nie jako ``\u201e``.
    for _ in range(2):
        _reason(_hook(json.dumps(REAL), tmp_path))

    text = (tmp_path / ".cache" / "maximiseart" / "praca_w_tle.jsonl").read_text(encoding="utf-8")
    assert [row["decyzja"] for row in _log(tmp_path)] == ["odmowa", "odmowa"]
    assert text.count("shell bi6lxbxlb „sleep 60”") == 2


def test_niedostepny_dziennik_nie_zmienia_odmowy(tmp_path: Path) -> None:
    (tmp_path / ".cache").write_text("plik zamiast katalogu", encoding="utf-8")

    hooked = _hook(json.dumps(REAL), tmp_path)

    assert json.loads(hooked.stdout)["decision"] == "block"
    assert (hooked.returncode, b"praca_w_tle: dziennik ~/.cache/maximiseart/praca_w_tle.jsonl" in hooked.stderr) == (
        0,
        True,
    )


@pytest.mark.parametrize("error", ["KeyError", "RuntimeError"])
def test_katalog_domowy_nie_do_ustalenia_nie_zmienia_odmowy(tmp_path: Path, error: str) -> None:
    # Path.home() bez HOME rzuca KeyError (Python 3.9, użytkownik spoza passwd) albo RuntimeError (Windows, 3.12+).
    broken = (
        f"import pathlib, runpy, sys\n"
        f"def home(cls): raise {error}('HOME')\n"
        f"pathlib.Path.home = classmethod(home)\n"
        f"sys.argv = [{str(HOOK)!r}]\n"
        f"runpy.run_path({str(HOOK)!r}, run_name='__main__')\n"
    )
    env = {name: value for name, value in os.environ.items() if name != "MAXIMISEART_PRACA_W_TLE_DZIENNIK"}

    hooked = subprocess.run(
        [sys.executable, "-c", broken], input=json.dumps(REAL).encode("utf-8"), capture_output=True, env=env, check=False
    )

    assert json.loads(hooked.stdout)["decision"] == "block"
    assert (hooked.returncode, f"niedostępny: {error}('HOME')".encode() in hooked.stderr) == (0, True)


def _configured_hooks() -> list[dict[str, object]]:
    entries = json.loads(SETTINGS.read_text(encoding="utf-8"))["hooks"]["Stop"]
    return [hook for entry in entries for hook in entry["hooks"]]


def test_hook_ocenia_dluga_liste_zadan_przed_limitem_z_ustawien(tmp_path: Path) -> None:
    # Claude Code po limicie kończy hook bez decyzji, a tura kończy się mimo pracy w tle (próba na 2.1.318).
    (timeout,) = [float(str(hook["timeout"])) for hook in _configured_hooks()]
    tasks = [{**SUBAGENT, "id": f"a{n}"} for n in range(100000)] + [SHELL]

    hooked = subprocess.run(
        [sys.executable, str(HOOK)],
        input=_stop(tasks).encode("utf-8"),
        capture_output=True,
        env={**os.environ, "HOME": str(tmp_path), "USERPROFILE": str(tmp_path)},
        timeout=timeout,
        check=False,
    )

    assert 0 < timeout <= 10
    assert "shell bi6lxbxlb" in _reason(hooked)


def _configured(project: Path, home: Path) -> list[subprocess.CompletedProcess[bytes]]:
    return [
        subprocess.run(
            str(hook["command"]),
            shell=True,
            input=json.dumps(REAL).encode("utf-8"),
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(project), "HOME": str(home)},
            capture_output=True,
            check=False,
        )
        for hook in _configured_hooks()
    ]


@POSIX_ONLY
def test_ustawienia_projektu_wpinaja_hook_w_stop_a_nie_w_subagent_stop(tmp_path: Path) -> None:
    hooked = _configured(ROOT, tmp_path)

    assert [json.loads(run.stdout)["decision"] for run in hooked] == ["block"]
    assert "SubagentStop" not in json.loads(SETTINGS.read_text(encoding="utf-8"))["hooks"]


@POSIX_ONLY
def test_checkout_bez_skryptu_hooka_nie_blokuje_konca_tury(tmp_path: Path) -> None:
    # Sesja trzyma ustawienia ze startu, a checkout sprzed hooka nie ma skryptu; python3 bez pliku kończy się kodem 2.
    hooked = _configured(tmp_path, tmp_path)

    assert [(run.returncode, run.stdout, run.stderr) for run in hooked] == [(0, b"", b"")]


FAKE_CLAUDE = '''"""Atrapa claude: zachowuje się jak Claude Code 2.1.328 w ``claude -p`` wobec fałszywego API wyroczni."""
import json, os, re, subprocess, sys, time, urllib.request
sys.path.insert(0, {fixtures!r})
import ustawienia_claude
# Ustawienia atrapy z testu: środowisko wyroczni nie dochodzi do claude (lista dozwolona falszywe_api).
ATRAPA = {atrapa!r}
argv = sys.argv[1:]
if argv == ["--version"]:
    print("9.9.9 (Claude Code)")
    sys.exit(0)
with open(ATRAPA["ATRAPA_WYWOLANIA"], "a", encoding="utf-8") as calls:
    keys = ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "MAXIMISEART_WYROCZNIA_W_SRODKU", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "MAXIMISEART_PRACA_W_TLE_DZIENNIK")
    seen = open(ATRAPA["ATRAPA_WYJSCIE"], encoding="utf-8").read() if ATRAPA.get("ATRAPA_WYJSCIE") else None
    calls.write(json.dumps({{"argv": argv, "cwd": os.getcwd(), "env": {{k: os.environ.get(k) for k in keys}}, "wyjscie": seen}}) + "\\n")
if ATRAPA.get("ATRAPA_CISZA"):
    time.sleep(600)
base = ustawienia_claude.base_url(argv, os.getcwd(), os.environ)
def api(messages):
    with open(ATRAPA["ATRAPA_WYWOLANIA"] + ".api", "a", encoding="utf-8") as asked:
        asked.write(json.dumps(base) + "\\n")
    body = json.dumps({{"model": "m", "stream": True, "messages": messages}}).encode()
    with urllib.request.urlopen(urllib.request.Request(base + "/v1/messages", data=body, method="POST")) as answer:
        events = [json.loads(line[6:]) for line in answer.read().decode().splitlines() if line.startswith("data: ")]
    start = next(e["content_block"] for e in events if e["type"] == "content_block_start")
    delta = next(e["delta"] for e in events if e["type"] == "content_block_delta")
    return start, delta
def user(text):
    return [{{"type": "text", "text": text}}] if ATRAPA.get("ATRAPA_BLOKI") else text
SESSION = f"atrapa-{{os.getpid()}}"
settings = json.load(open(os.path.join(os.getcwd(), ".claude", "settings.json"), encoding="utf-8"))
def hooks(name, event, tool=None):
    if ATRAPA.get("ATRAPA_BEZ_HOOKA") and name == "Stop" or ATRAPA.get("ATRAPA_BEZ_POST") and name == "PostToolUse":
        return []
    commands = [h["command"] for e in settings["hooks"].get(name, []) if tool is None or re.fullmatch(e["matcher"], tool) for h in e["hooks"]]
    payload = json.dumps({{"hook_event_name": name, "session_id": SESSION, **event}})
    env = {{**os.environ, "CLAUDE_PROJECT_DIR": os.getcwd()}}
    return [subprocess.run(c, shell=True, input=payload, capture_output=True, text=True, env=env).stdout for c in commands]
tasks, owners = [], {{}}
def call(name, given, agent):
    if name == "Bash" and given.get("run_in_background"):
        task = f"b{{len(owners) + 1}}"
        owners[task] = agent
        tasks.append({{"id": task, "type": "shell", "status": "running", "description": given["description"], "command": given["command"]}})
        result, response = f"Command running in background with ID: {{task}}", {{"backgroundTaskId": task}}
    elif name == "Bash":
        result = subprocess.run(given["command"], shell=True, capture_output=True, text=True).stdout
        response = {{"stdout": result}}
    elif name == "Agent":
        result, response = turn([{{"role": "user", "content": user(given["prompt"])}}], "a1"), {{"status": "completed"}}
    else:
        result = json.dumps({{"matched": given["taskIds"], "unmatched": []}})
        response = [{{"type": "text", "text": result}}]
    hooks("PostToolUse", {{"tool_name": name, "tool_input": given, "tool_response": response, **({{"agent_id": agent}} if agent else {{}})}}, name)
    return result
def turn(messages, agent=None):
    for _ in range(20):
        start, delta = api(messages)
        if start["type"] != "tool_use":
            messages.append({{"role": "assistant", "content": [{{"type": "text", "text": delta["text"]}}]}})
            return delta["text"]
        if ATRAPA.get("ATRAPA_BEZ_WYNIKU"):
            sys.exit(0)
        given = json.loads(delta["partial_json"])
        result = call(start["name"], given, agent)
        messages += [
            {{"role": "assistant", "content": [{{"type": "tool_use", "id": start["id"], "name": start["name"], "input": given}}]}},
            {{"role": "user", "content": [{{"type": "tool_result", "tool_use_id": start["id"], "content": [{{"type": "text", "text": result}}]}}]}},
        ]
    sys.exit(3)
api([{{"role": "user", "content": "Podaj tytuł sesji."}}])
if ATRAPA.get("ATRAPA_TYLKO_POBOCZNE"):
    sys.exit(0)
messages = [{{"role": "user", "content": user(argv[argv.index("-p") + 1])}}]
active = False
for _ in range(12):
    turn(messages)
    event = {{"stop_hook_active": active, "background_tasks": tasks, "session_crons": []}}
    reasons = [json.loads(a)["reason"] for a in hooks("Stop", event) if a.strip()]
    if ATRAPA.get("ATRAPA_JEDNA_ODMOWA") and not active:
        reasons.append("Odmowa końca tury: w tle sesji biegnie jeszcze nic (fałszywa odmowa).")
    if reasons:
        messages.append({{"role": "user", "content": user("Stop hook feedback:\\n" + reasons[0])}})
        active = True
        continue
    # Claude Code 2.1.328 w claude -p czeka na zadania w tle, a koniec zadania głównej pętli budzi sesję.
    own = [task["id"] for task in tasks if owners[task["id"]] is None]
    tasks.clear()
    if own and not ATRAPA.get("ATRAPA_BEZ_BUDZENIA"):
        note = "".join(f"<task-notification><task-id>{{task}}</task-id><status>completed</status></task-notification>" for task in own)
        messages.append({{"role": "user", "content": user(note)}})
        active = False
        continue
    sys.exit(int(ATRAPA.get("ATRAPA_KOD", "0")))
sys.exit(3)
'''


def _oracle(
    tmp_path: Path,
    *arguments: str,
    env: dict[str, str] | None = None,
    atrapa: dict[str, str] | None = None,
    user_settings: Mapping[str, object] | None = None,
    stdout: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Wyrocznia z atrapą ``claude``; ze ``stdout`` jej wyjście idzie do tego pliku, a atrapa kopiuje go przy każdym starcie."""

    programs = tmp_path / "bin"
    fixtures = str(Path(ustawienia_claude.__file__).parent)
    atrapa = {"ATRAPA_WYWOLANIA": str(tmp_path / "wywolania.jsonl"), **(atrapa or {})}
    if stdout is not None:
        atrapa["ATRAPA_WYJSCIE"] = str(stdout)
    fake_cli(programs, "claude", FAKE_CLAUDE.format(fixtures=fixtures, atrapa=atrapa))
    (tmp_path / "dom" / ".claude").mkdir(parents=True)
    if user_settings is not None:
        (tmp_path / "dom" / ".claude" / "settings.json").write_text(json.dumps(user_settings), encoding="utf-8")
    with contextlib.ExitStack() as files:
        output = files.enter_context(stdout.open("w", encoding="utf-8")) if stdout is not None else subprocess.PIPE
        return subprocess.run(
            [sys.executable, str(ORACLE), *arguments],
            env={
                **os.environ,
                "HOME": str(tmp_path / "dom"),
                "PATH": f"{programs}{os.pathsep}/usr/bin{os.pathsep}/bin",
                "CLAUDECODE": "1",
                "CLAUDE_CODE_ENTRYPOINT": "sdk-ts",
                "ANTHROPIC_AUTH_TOKEN": "token-huba",
                **(env or {}),
            },
            stdout=output,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=60,
        )


def _calls(tmp_path: Path) -> list[dict[str, object]]:
    path = tmp_path / "wywolania.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


@POSIX_ONLY
@pytest.mark.parametrize("atrapa", [{}, {"ATRAPA_BLOKI": "1"}], ids=["tresc-tekstem", "tresc-blokami-tekstu"])
def test_wyrocznia_z_odmowa_hooka_przy_pracy_w_tle_i_bez_niej_konczy_sie_ok(
    tmp_path: Path, atrapa: dict[str, str]
) -> None:
    # Messages API przyjmuje treść wiadomości jako tekst albo listę bloków; wyrocznia rozpoznaje przypadek i odmowy w obu.
    ran = _oracle(tmp_path, atrapa=atrapa)

    assert ran.stdout.splitlines() == [
        "Claude Code 9.9.9 (Claude Code), przypadki 4",
        "ZGODNE praca-w-tle | odmowy hooka: 2",
        "ZGODNE bez-pracy-w-tle | koniec tury bez odmowy (kod 0)",
        "ZGODNE shell-podagenta | koniec tury bez odmowy (kod 0)",
        "ZGODNE zadanie-zarejestrowane | koniec tury bez odmowy (kod 0), sesja obudzona po końcu zadania",
        "WYROCZNIA OK | Claude Code 9.9.9 (Claude Code) | ZGODNE 4",
    ], ran.stderr
    assert ran.returncode == 0
    # Dziennik hooka w biegu wyroczni leży poza katalogiem domowym, żeby nie mieszać prób z prawdziwymi sesjami.
    assert _log(tmp_path / "dom") == []


@POSIX_ONLY
def test_wyrocznia_uruchamia_claude_p_w_checkoucie_tylko_z_ustawieniami_projektu_i_falszywym_api(
    tmp_path: Path,
) -> None:
    """Z serwerów MCP ``claude`` wyroczni dostaje tylko fałszywy ``t3-code``: ani serwery z ``~/.claude.json``, ani
    prawdziwy T3."""

    ran = _oracle(tmp_path, "bez-pracy-w-tle")

    (call,) = _calls(tmp_path)
    argv = call["argv"]
    assert isinstance(argv, list), ran.stdout + ran.stderr
    settings = json.loads(argv[argv.index("--settings") + 1])
    assert argv[:2] == ["-p", "WYROCZNIA-PRACY-W-TLE bez-pracy-w-tle: uruchom polecenie."]
    assert argv[argv.index("--setting-sources") + 1] == "project,local"
    assert argv[argv.index("--permission-mode") + 1] == "bypassPermissions"
    servers = json.loads(argv[argv.index("--mcp-config") + 1])["mcpServers"]
    assert ("--strict-mcp-config" in argv, list(servers), servers["t3-code"]["args"]) == (True, ["t3-code"], [str(FAKE_T3)])
    # Reguła zespołu: Claude Code wyroczni, gdyby jednak zapytał model, pyta Opusa.
    assert argv[argv.index("--model") + 1] == "claude-opus-5-5"
    assert call["cwd"] == str(ROOT)
    env = call["env"]
    assert isinstance(env, dict)
    log = Path(env["MAXIMISEART_PRACA_W_TLE_DZIENNIK"])
    assert env == {
        "ANTHROPIC_BASE_URL": settings["env"]["ANTHROPIC_BASE_URL"],
        "ANTHROPIC_AUTH_TOKEN": None,
        "MAXIMISEART_WYROCZNIA_W_SRODKU": "1",
        "CLAUDECODE": None,
        "CLAUDE_CODE_ENTRYPOINT": None,
        "MAXIMISEART_PRACA_W_TLE_DZIENNIK": str(log),
    }
    assert (log.name, tmp_path / "dom" in log.parents, log.exists()) == ("praca_w_tle.jsonl", False, False)
    assert settings["env"]["ANTHROPIC_BASE_URL"].startswith("http://127.0.0.1:")


@POSIX_ONLY
def test_wyrocznia_pyta_tylko_falszywe_api_takze_gdy_ustawienia_uzytkownika_maja_adres_huba(tmp_path: Path) -> None:
    # 5.11.2026 env.ANTHROPIC_BASE_URL huba z ~/.claude/settings.json wygrał z adresem fałszywego API w środowisku (#956).
    hub = {"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:9", "ANTHROPIC_AUTH_TOKEN": "token-huba"}}

    ran = _oracle(tmp_path, user_settings=hub)

    assert ran.stdout.splitlines()[-1] == "WYROCZNIA OK | Claude Code 9.9.9 (Claude Code) | ZGODNE 4", ran.stderr
    envs = [call["env"] for call in _calls(tmp_path)]
    fake = {str(env["ANTHROPIC_BASE_URL"]) for env in envs if isinstance(env, dict)}
    asked = [json.loads(line) for line in (tmp_path / "wywolania.jsonl.api").read_text(encoding="utf-8").splitlines()]
    assert (bool(asked), set(asked) <= fake) == (True, True)
    assert all(url.startswith("http://127.0.0.1:") and url != "http://127.0.0.1:9" for url in fake)


@POSIX_ONLY
def test_wyrocznia_gdy_hook_nie_odmawia_konczy_sie_zmiana(tmp_path: Path) -> None:
    ran = _oracle(tmp_path, atrapa={"ATRAPA_BEZ_HOOKA": "1"})

    assert ran.stdout.splitlines()[1:3] == [
        "ZMIANA praca-w-tle | koniec tury bez odmowy (kod 0)",
        "ZGODNE bez-pracy-w-tle | koniec tury bez odmowy (kod 0)",
    ], ran.stderr
    assert ran.stdout.splitlines()[-1] == "WYROCZNIA ZMIANA | Claude Code 9.9.9 (Claude Code) | ZGODNE 3, ZMIANA 1"
    assert ran.returncode == 1


@POSIX_ONLY
@pytest.mark.parametrize(
    ("atrapa", "seen"),
    [
        (
            {"ATRAPA_BEZ_POST": "1"},
            ["ZMIANA shell-podagenta | odmowy hooka: 2", "ZMIANA zadanie-zarejestrowane | odmowy hooka: 2"],
        ),
        (
            {"ATRAPA_BEZ_BUDZENIA": "1"},
            [
                "ZGODNE shell-podagenta | koniec tury bez odmowy (kod 0)",
                "ZMIANA zadanie-zarejestrowane | koniec tury bez odmowy (kod 0), ale bez powiadomienia o końcu zadania",
            ],
        ),
    ],
    ids=["bez-hooka-post-tool-use", "bez-budzenia-po-koncu-zadania"],
)
def test_wyrocznia_gdy_shell_podagenta_albo_zadanie_zarejestrowane_nie_konczy_tury_jak_trzeba_konczy_sie_zmiana(
    tmp_path: Path, atrapa: dict[str, str], seen: list[str]
) -> None:
    """Bez hooka ``PostToolUse`` hook Stop odmawia jak przed #2267, a bez budzenia tura z zadaniem zostaje bez wyniku."""

    ran = _oracle(tmp_path, "shell-podagenta", "zadanie-zarejestrowane", atrapa=atrapa)

    assert ran.stdout.splitlines()[1:3] == seen, ran.stderr
    assert ran.returncode == 1


@POSIX_ONLY
def test_wyrocznia_gdy_hook_odmawia_bez_pracy_w_tle_konczy_sie_zmiana(tmp_path: Path) -> None:
    # Jedna fałszywa odmowa, po której Claude Code kończy turę sam, to też zmiana: każda zatrzymuje agenta.
    ran = _oracle(tmp_path, "bez-pracy-w-tle", atrapa={"ATRAPA_JEDNA_ODMOWA": "1"})

    assert ran.stdout.splitlines()[1:] == [
        "ZMIANA bez-pracy-w-tle | odmowy hooka: 1",
        "WYROCZNIA ZMIANA | Claude Code 9.9.9 (Claude Code) | ZMIANA 1",
    ], ran.stderr
    assert ran.returncode == 1


@POSIX_ONLY
@pytest.mark.parametrize(
    ("atrapa", "seen"),
    [
        ({"ATRAPA_TYLKO_POBOCZNE": "1"}, "Claude Code nie zapytał fałszywego API"),
        ({"ATRAPA_BEZ_WYNIKU": "1"}, "Bash nie oddał wyniku"),
    ],
    ids=["tylko-zapytanie-poboczne", "koniec-przed-wynikiem-basha"],
)
def test_wyrocznia_gdy_claude_code_konczy_sie_przed_wynikiem_basha_konczy_sie_zmiana(
    tmp_path: Path, atrapa: dict[str, str], seen: str
) -> None:
    # Zapytanie poboczne (tytuł sesji) nie jest pytaniem przypadku, a bez wyniku Basha hook nie miał czego ocenić.
    ran = _oracle(tmp_path, "praca-w-tle", atrapa=atrapa)

    assert ran.stdout.splitlines()[1:] == [
        f"ZMIANA praca-w-tle | {seen}",
        "WYROCZNIA ZMIANA | Claude Code 9.9.9 (Claude Code) | ZMIANA 1",
    ], ran.stderr
    assert ran.returncode == 1


@POSIX_ONLY
def test_wyrocznia_gdy_claude_code_bez_odmowy_konczy_sie_bledem_konczy_sie_zmiana(tmp_path: Path) -> None:
    ran = _oracle(tmp_path, "bez-pracy-w-tle", atrapa={"ATRAPA_KOD": "5"})

    assert ran.stdout.splitlines()[1:] == [
        "ZMIANA bez-pracy-w-tle | koniec tury bez odmowy (kod 5)",
        "WYROCZNIA ZMIANA | Claude Code 9.9.9 (Claude Code) | ZMIANA 1",
    ], ran.stderr
    assert ran.returncode == 1


@POSIX_ONLY
def test_wyrocznia_z_nazwa_spoza_przypadkow_nie_konczy_sie_ok(tmp_path: Path) -> None:
    # Literówka w nazwie przypadku nie sprawdza niczego, więc nie może dać ``WYROCZNIA OK``.
    ran = _oracle(tmp_path, "praca-w-tel")

    assert (ran.returncode, ran.stdout.splitlines(), _calls(tmp_path)) == (
        1,
        ["Claude Code 9.9.9 (Claude Code), przypadki 0", "WYROCZNIA ZMIANA | Claude Code 9.9.9 (Claude Code) | brak przypadków"],
        [],
    )


@POSIX_ONLY
def test_wynik_przypadku_widac_w_wyjsciu_zanim_zacznie_sie_nastepny(tmp_path: Path) -> None:
    # Wyjście do pliku albo potoku (T3, log) Python buforuje, a następny przypadek trwa do limitu ``--limit-s``.
    output = tmp_path / "wyjscie.txt"

    ran = _oracle(tmp_path, stdout=output)

    assert ran.returncode == 0, output.read_text(encoding="utf-8") + ran.stderr
    seen = [call["wyjscie"] for call in _calls(tmp_path)]
    assert len(seen) == 4 and "ZGODNE praca-w-tle | odmowy hooka: 2\n" in str(seen[1]), seen


@POSIX_ONLY
def test_wyrocznia_konczy_claude_code_ktory_nie_pyta_falszywego_api(tmp_path: Path) -> None:
    # Claude Code, który pyta inny model, uruchomiłby prawdziwego agenta (5.11.2026: agenci uruchamiali wyrocznię).
    ran = _oracle(tmp_path, "praca-w-tle", "--kontakt-s", "1", atrapa={"ATRAPA_CISZA": "1"})

    assert ran.stdout.splitlines()[1:] == [
        "ZMIANA praca-w-tle | Claude Code nie zapytał fałszywego API",
        "WYROCZNIA ZMIANA | Claude Code 9.9.9 (Claude Code) | ZMIANA 1",
    ], ran.stderr
    assert ran.returncode == 1


@POSIX_ONLY
def test_wyrocznia_uruchomiona_w_claude_code_wyroczni_nie_uruchamia_claude(tmp_path: Path) -> None:
    ran = _oracle(tmp_path, env={"MAXIMISEART_WYROCZNIA_W_SRODKU": "1"})

    assert (ran.returncode, ran.stdout.splitlines(), _calls(tmp_path)) == (
        2,
        ["WYROCZNIA BRAK | uruchomiona w Claude Code wyroczni (MAXIMISEART_WYROCZNIA_W_SRODKU)"],
        [],
    )
