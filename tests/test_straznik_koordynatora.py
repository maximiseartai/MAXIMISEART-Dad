"""Hook ``tools/hooks/straznik_koordynatora.py``: wątek T3, który zlecił pracę innym wątkom, dostaje strażnika bez prośby.

Koordynator zleca pracę delegatowi i kończy turę; nikt nie stawia strażnika, a delegat staje albo T3 nie budzi
koordynatora po jego końcu. Oczekiwania biorą się z docstringu hooka. Testy procesu uruchamiają hook tak, jak Claude
Code w T3: JSON wejścia ``PostToolUse`` na stdin i środowisko T3 (``T3CODE_THREAD_ID``, ``T3CODE_CLI_PATH``), z atrapą
programu ``t3``, która trzyma stan wątków w pliku obok siebie. Identyfikatory wątków są wymyślone, a kształt odpowiedzi
narzędzia ``delegate_task`` (tekst JSON w liście treści) to kształt z zapisu sesji T3.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest

from tests.fixtures.fake_cli import fake_cli
from tests.fixtures.potomne import held, wait_for

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "tools" / "hooks" / "straznik_koordynatora.py"
SETTINGS = ROOT / ".claude" / "settings.json"
POSIX_ONLY = pytest.mark.skipif(sys.platform == "win32", reason="hook na Windows nic nie robi")

PARENT = "rodzic-wymyslony-1"
CHILD = "thread:delegated-task:dziecko-wymyslone-1"
MIN = 60.0


def _load(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"test_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


straznik = _load(HOOK)
Seen = straznik.Seen


def _delegated(*children: str) -> dict[str, object]:
    body = [{"taskId": f"node:{child}", "childThreadId": child, "status": "running"} for child in children]
    return {"content": [{"type": "text", "text": json.dumps(item)} for item in body]}


def test_dzieci_z_odpowiedzi_delegate_task_w_tekscie_json_listy_tresci() -> None:
    response = _delegated(CHILD, "thread:delegated-task:dziecko-wymyslone-2", CHILD)

    assert straznik.children_in(response) == [CHILD, "thread:delegated-task:dziecko-wymyslone-2"]
    assert straznik.children_in({"threadId": "mcp:watek-wymyslony", "link": "x"}) == ["mcp:watek-wymyslony"]
    assert straznik.children_in("nie JSON") == []


def test_koordynator_po_turze_przy_dziecku_bez_ruchu_dostaje_jedno_budzenie_z_nazwa_dziecka() -> None:
    memory = straznik.Memory()
    parent = Seen("completed", 50 * MIN)
    stuck = {CHILD: Seen("running", 46 * MIN)}

    (reason,) = straznik.decide(parent, stuck, 0.0, memory)
    assert CHILD in reason and "bez ruchu od 46 min" in reason
    # Ten sam powód nie budzi drugi raz, choć minuty rosną.
    assert straznik.decide(parent, {CHILD: Seen("running", 80 * MIN)}, 3600.0, memory) == []


@pytest.mark.parametrize("status", ["failed", "interrupted"])
def test_koordynator_ktory_padl_tez_dostaje_budzenie(status: str) -> None:
    assert straznik.decide(Seen(status, 50 * MIN), {CHILD: Seen("running", 46 * MIN)}, 0.0, straznik.Memory())


@pytest.mark.parametrize(
    ("parent", "child"),
    [
        (("running", 50), ("running", 46)),
        (("waiting", 50), ("running", 46)),
        (("completed", 50), ("running", 44)),
        (("completed", 10), ("completed", 20)),
        (("completed", 60), ("completed", 14)),
    ],
    ids=[
        "koordynator-biegnie",
        "koordynator-czeka-na-odpowiedz",
        "dziecko-rusza-sie",
        "t3-obudzilo-koordynatora",
        "dziecko-skonczylo-sie-niedawno",
    ],
)
def test_bez_budzenia_gdy_koordynator_pracuje_albo_nic_nie_stoi(
    parent: tuple[str, int], child: tuple[str, int]
) -> None:
    seen = {CHILD: Seen(child[0], child[1] * MIN)}

    assert straznik.decide(Seen(parent[0], parent[1] * MIN), seen, 0.0, straznik.Memory()) == []


def test_dziecko_skonczone_bez_budzenia_koordynatora_przez_t3_budzi_go_strażnik() -> None:
    memory = straznik.Memory()
    assert straznik.decide(Seen("completed", 2 * MIN), {CHILD: Seen("running", 1 * MIN)}, 0.0, memory) == []
    # Dziecko skończyło się w 19. minucie, a koordynator nie ruszył od 2. minuty.
    assert straznik.decide(Seen("completed", 22 * MIN), {CHILD: Seen("completed", 1 * MIN)}, 20 * MIN, memory) == []

    (reason,) = straznik.decide(Seen("completed", 37 * MIN), {CHILD: Seen("completed", 1 * MIN)}, 35 * MIN, memory)

    assert CHILD in reason and "16 min temu" in reason and "nie ruszył" in reason


def test_koordynator_obudzony_po_koncu_dziecka_nie_dostaje_budzenia_choc_t3_potem_przesuwa_ruch_dziecka() -> None:
    memory = straznik.Memory()
    straznik.decide(Seen("completed", 2 * MIN), {CHILD: Seen("running", 1 * MIN)}, 0.0, memory)
    # Dziecko skończyło się w 19. minucie, T3 obudziło koordynatora, a jego tura skończyła się w 21. minucie.
    straznik.decide(Seen("completed", 4 * MIN), {CHILD: Seen("completed", 6 * MIN)}, 25 * MIN, memory)
    # Restart T3 w 50. minucie przesuwa ruch skończonego dziecka, ale nie jego koniec.
    later = {CHILD: Seen("completed", 10 * MIN)}

    assert straznik.decide(Seen("completed", 39 * MIN), later, 60 * MIN, memory) == []
    assert straznik.settled(Seen("completed", 39 * MIN), later, 60 * MIN, memory)


def test_strażnik_ze_startu_sesji_budzi_przy_dziecku_skonczonym_po_ostatnim_ruchu_koordynatora() -> None:
    # Restart T3 przerwał dziecko po ostatniej turze koordynatora; strażnik startuje z wznowioną sesją.
    memory = straznik.Memory()
    assert straznik.decide(Seen("completed", 30 * MIN), {CHILD: Seen("interrupted", 5 * MIN)}, 0.0, memory) == []

    assert straznik.decide(Seen("completed", 41 * MIN), {CHILD: Seen("interrupted", 16 * MIN)}, 11 * MIN, memory)


def test_dziecko_wznowione_przez_koordynatora_budzi_po_swoim_drugim_koncu() -> None:
    memory = straznik.Memory()
    straznik.decide(Seen("completed", 2 * MIN), {CHILD: Seen("running", 1 * MIN)}, 0.0, memory)
    # Pierwszy koniec w 9. minucie, T3 budzi koordynatora, a ten w 12. minucie wznawia dziecko i kończy turę.
    straznik.decide(Seen("completed", 1 * MIN), {CHILD: Seen("completed", 1 * MIN)}, 10 * MIN, memory)
    straznik.decide(Seen("completed", 1 * MIN), {CHILD: Seen("preparing", 1 * MIN)}, 13 * MIN, memory)
    # Drugi koniec w 39. minucie, a T3 koordynatora nie budzi.
    straznik.decide(Seen("completed", 28 * MIN), {CHILD: Seen("completed", 1 * MIN)}, 40 * MIN, memory)

    (reason,) = straznik.decide(Seen("completed", 44 * MIN), {CHILD: Seen("completed", 17 * MIN)}, 56 * MIN, memory)

    assert "17 min temu" in reason


def test_dwa_budzenia_dzieli_przerwa_a_nowy_powod_po_niej_budzi() -> None:
    memory = straznik.Memory()
    parent = Seen("completed", 90 * MIN)
    first = {CHILD: Seen("running", 50 * MIN)}
    both = {**first, "dziecko-2": Seen("completed", 20 * MIN)}

    assert straznik.decide(parent, first, 0.0, memory)
    assert straznik.decide(parent, both, straznik.PAUSE_S - 1, memory) == []
    (reason,) = straznik.decide(parent, both, straznik.PAUSE_S + 1, memory)
    assert "dziecko-2" in reason


def test_strażnik_konczy_sie_dopiero_gdy_nic_nie_trwa_i_koordynator_ruszyl_po_koncu_dzieci() -> None:
    def after(parent_min: float, status: str, child_min: float) -> bool:
        memory = straznik.Memory()
        child = {CHILD: Seen(status, child_min * MIN)}
        straznik.decide(Seen("completed", 30 * MIN), {CHILD: Seen("running", 1 * MIN)}, 0.0, memory)
        straznik.decide(Seen("completed", parent_min * MIN), child, 10 * MIN, memory)
        return bool(straznik.settled(Seen("completed", parent_min * MIN), child, 10 * MIN, memory))

    assert after(1, "completed", 2)
    assert not after(3, "completed", 2)
    assert not after(1, "running", 50)
    assert not after(1, "preparing", 0)


def test_ustawienia_wpinaja_hook_po_kazdym_narzedziu_zlecajacym_prace_i_na_starcie_sesji() -> None:
    hooks = json.loads(SETTINGS.read_text(encoding="utf-8"))["hooks"]
    (after,) = hooks["PostToolUse"]
    (start,) = hooks["SessionStart"]

    assert after["matcher"] == "mcp__t3-code__(" + "|".join(name.split("__")[-1] for name in straznik.DELEGATING) + ")"
    for entry in (after, start):
        (command,) = entry["hooks"]
        assert command["command"].endswith('python3 "$CLAUDE_PROJECT_DIR/tools/hooks/straznik_koordynatora.py"')


FAKE_T3 = r"""
import json, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

state_file = Path(__file__).with_name("watki.json")
state = json.loads(state_file.read_text(encoding="utf-8"))
moment = datetime.now(timezone.utc)
now = moment.isoformat().replace("+00:00", "Z")
if sys.argv[1:3] == ["thread", "show"]:
    thread = state[sys.argv[3]]
    print(json.dumps({"thread": {"threadId": sys.argv[3], **thread}, "messages": []}))
elif sys.argv[1:3] == ["thread", "send"]:
    with Path(__file__).with_name("wyslane.txt").open("a", encoding="utf-8") as sent:
        sent.write(sys.argv[3] + " " + sys.argv[4] + "\n")
    # Koordynator odpowiada na budzenie: dziecko kończy się, a sam koordynator rusza po jego końcu.
    for name, thread in state.items():
        moved = moment - timedelta(seconds=1 if name.startswith("thread:") else 0)
        thread.update({"status": "completed", "updatedAt": moved.isoformat().replace("+00:00", "Z")})
    state_file.write_text(json.dumps(state), encoding="utf-8")
"""


def _ago(minutes: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


@pytest.fixture
def t3(tmp_path: Path) -> Iterator[tuple[Path, dict[str, str]]]:
    """Atrapa ``t3`` z koordynatorem po turze i dzieckiem bez ruchu od 50 min oraz środowisko sesji T3 hooka."""

    program = fake_cli(tmp_path / "bin", "t3", FAKE_T3)
    (tmp_path / "bin" / "watki.json").write_text(
        json.dumps(
            {
                PARENT: {"status": "completed", "updatedAt": _ago(55)},
                CHILD: {"status": "running", "updatedAt": _ago(50)},
            }
        ),
        encoding="utf-8",
    )
    home = tmp_path / "dom"
    env = {
        **os.environ,
        "HOME": str(home),
        "T3CODE_THREAD_ID": PARENT,
        "T3CODE_CLI_PATH": str(program),
        straznik.STEP_ENV: "0.1",
    }
    yield tmp_path, env
    # Strażnik żyje po hooku z założenia; kończy go usunięty stan wątku, także takiego, który dopiero startuje.
    folder = home / straznik.STATE
    for kids in folder.glob("*.dzieci"):
        kids.unlink()
    assert wait_for(lambda: not any(held(lock) for lock in folder.glob("*.blokada")), 10)


def _rows(home: Path) -> list[dict[str, object]]:
    folder = home / straznik.STATE
    lines = [line for path in sorted(folder.glob("*.jsonl")) for line in path.read_text(encoding="utf-8").splitlines()]
    return [json.loads(line) for line in lines]


def _hook(env: dict[str, str], event: dict[str, object]) -> subprocess.CompletedProcess[bytes]:
    data = json.dumps(event).encode("utf-8")
    return subprocess.run([sys.executable, str(HOOK)], input=data, capture_output=True, env=env, timeout=10, check=False)


@POSIX_ONLY
def test_koordynator_ktory_zlecil_prace_i_skonczyl_ture_bez_strażnika_dostaje_go_od_hooka(
    t3: tuple[Path, dict[str, str]],
) -> None:
    folder, env = t3
    event = {"hook_event_name": "PostToolUse", "tool_name": straznik.DELEGATING[0], "tool_response": _delegated(CHILD)}

    first, second = _hook(env, event), _hook(env, event)

    assert [(run.returncode, run.stdout) for run in (first, second)] == [(0, b""), (0, b"")]
    home = Path(env["HOME"])
    assert wait_for(lambda: any(row.get("zdarzenie") == "koniec" for row in _rows(home)), 30)
    (sent,) = (folder / "bin" / "wyslane.txt").read_text(encoding="utf-8").splitlines()
    assert sent.startswith(f"{PARENT} {straznik.NUDGE} dziecko {CHILD} (running) bez ruchu od 50 min")
    events = [row["zdarzenie"] for row in _rows(home)]
    assert events.count("start") == 1 and events.count("budzenie") == 1


@POSIX_ONLY
def test_wznowiona_sesja_koordynatora_dostaje_strażnika_z_powrotem(t3: tuple[Path, dict[str, str]]) -> None:
    # Restart T3 zabija strażnika, a T3 wznawia sesję koordynatora; dziecko z tamtej tury znów stoi.
    folder, env = t3
    home = Path(env["HOME"])
    state = (folder / "bin" / "watki.json").read_text(encoding="utf-8")
    event = {"hook_event_name": "PostToolUse", "tool_name": straznik.DELEGATING[1], "tool_response": _delegated(CHILD)}
    assert _hook(env, event).returncode == 0
    assert wait_for(lambda: any(row.get("zdarzenie") == "koniec" for row in _rows(home)), 30)
    (folder / "bin" / "watki.json").write_text(state, encoding="utf-8")

    assert _hook(env, {"hook_event_name": "SessionStart", "source": "resume"}).returncode == 0

    assert wait_for(lambda: [row.get("zdarzenie") for row in _rows(home)].count("koniec") == 2, 30)
    assert len((folder / "bin" / "wyslane.txt").read_text(encoding="utf-8").splitlines()) == 2


@POSIX_ONLY
@pytest.mark.parametrize("missing", ["T3CODE_THREAD_ID", "T3CODE_CLI_PATH"])
def test_poza_t3_hook_nic_nie_zapisuje_i_nie_uruchamia(t3: tuple[Path, dict[str, str]], missing: str) -> None:
    _, env = t3
    env = {name: value for name, value in env.items() if name != missing}
    event = {"hook_event_name": "PostToolUse", "tool_name": straznik.DELEGATING[0], "tool_response": _delegated(CHILD)}

    assert (_hook(env, event).returncode, (Path(env["HOME"]) / straznik.STATE).exists()) == (0, False)


@POSIX_ONLY
def test_sesja_bez_zleconej_pracy_nie_zostawia_sladu(t3: tuple[Path, dict[str, str]]) -> None:
    _, env = t3

    assert _hook(env, {"hook_event_name": "SessionStart", "source": "startup"}).returncode == 0
    assert _rows(Path(env["HOME"])) == []
