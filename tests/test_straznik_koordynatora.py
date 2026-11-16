"""Hook ``tools/hooks/straznik_koordynatora.py``: wątek T3, który zlecił pracę delegatowi, dostaje strażnika bez prośby.

Koordynator zleca pracę delegatowi i kończy turę; nikt nie stawia strażnika, a delegat staje albo T3 nie budzi
koordynatora po jego końcu. Oczekiwania biorą się z docstringu hooka. Testy procesu uruchamiają hook tak, jak Claude
Code w T3: JSON wejścia ``PostToolUse`` na stdin i środowisko T3 (``T3CODE_THREAD_ID``, ``T3CODE_CLI_PATH``), z atrapą
programu ``t3``, która trzyma stan wątków w pliku obok siebie i jak prawdziwe ``t3`` kończy się kodem 1 na wątku, którego
nie zna (usunięty albo z innego środowiska). Identyfikatory wątków są wymyślone, a kształt odpowiedzi ``delegate_task``
(tekst JSON w liście treści, ``childThreadId`` null i ``remoteChild`` przy dziecku na innym środowisku) to kształt z
zapisu sesji T3.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import ModuleType
from typing import NamedTuple

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


class Seen(NamedTuple):
    """Stan wątku w scenariuszu testu: status i wiek ruchu w chwili pytania; ``_at`` robi z niego ``updatedAt``."""

    status: str
    age_s: float


def _at(now: float, state: Seen | None) -> object:
    return None if state is None else straznik.Seen(state.status, now - state.age_s)


def decide(parent: Seen, children: Mapping[str, Seen | None], now: float, memory: object) -> list[str]:
    shown = {name: _at(now, state) for name, state in children.items()}
    return list(straznik.decide(_at(now, parent), shown, now, memory))


def pending(parent: Seen, children: Mapping[str, Seen | None], now: float, memory: object) -> bool:
    shown = {name: _at(now, state) for name, state in children.items()}
    return bool(straznik.pending(_at(now, parent), shown, now, memory))


def _delegated(*children: str) -> dict[str, object]:
    body = [{"taskId": f"node:{child}", "childThreadId": child, "status": "running"} for child in children]
    return {"content": [{"type": "text", "text": json.dumps(item)} for item in body]}


REMOTE = {
    "content": [
        {
            "type": "text",
            "text": json.dumps(
                {
                    "taskId": "node:zdalne",
                    "childThreadId": None,
                    "remoteChild": {"environmentId": "srodowisko-wymyslone", "threadId": "mcp:launch:zdalne"},
                    "status": "running",
                }
            ),
        }
    ]
}
# Odpowiedź z polem childThreadId, żeby test sprawdzał samo pominięcie narzędzia, nie kształt jego odpowiedzi.
LAUNCHED = {"content": [{"type": "text", "text": json.dumps({"threadId": "mcp:przekazany", "childThreadId": "mcp:przekazany"})}]}


def test_dzieci_z_odpowiedzi_delegate_task_w_tekscie_json_listy_tresci() -> None:
    response = _delegated(CHILD, "thread:delegated-task:dziecko-wymyslone-2", CHILD)

    assert straznik.children_in(response) == [CHILD, "thread:delegated-task:dziecko-wymyslone-2"]
    assert straznik.children_in(REMOTE) == []
    assert straznik.children_in("nie JSON") == []


def test_koordynator_po_turze_przy_dziecku_bez_ruchu_dostaje_jedno_budzenie_z_nazwa_dziecka() -> None:
    memory = straznik.Memory()
    parent = Seen("completed", 50 * MIN)
    stuck = {CHILD: Seen("running", 46 * MIN)}

    (reason,) = decide(parent, stuck, 0.0, memory)
    assert CHILD in reason and "bez ruchu od 46 min" in reason
    # Ten sam powód nie budzi drugi raz, choć minuty rosną.
    assert decide(parent, {CHILD: Seen("running", 80 * MIN)}, 3600.0, memory) == []


@pytest.mark.parametrize("status", ["failed", "interrupted"])
def test_koordynator_ktory_padl_tez_dostaje_budzenie(status: str) -> None:
    assert decide(Seen(status, 50 * MIN), {CHILD: Seen("running", 46 * MIN)}, 0.0, straznik.Memory())


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

    assert decide(Seen(parent[0], parent[1] * MIN), seen, 0.0, straznik.Memory()) == []


def test_dziecko_skonczone_bez_budzenia_koordynatora_przez_t3_budzi_go_strażnik() -> None:
    memory = straznik.Memory()
    assert decide(Seen("completed", 2 * MIN), {CHILD: Seen("running", 1 * MIN)}, 0.0, memory) == []
    # Dziecko skończyło się w 19. minucie, a koordynator nie ruszył od 2. minuty.
    assert decide(Seen("completed", 22 * MIN), {CHILD: Seen("completed", 1 * MIN)}, 20 * MIN, memory) == []

    (reason,) = decide(Seen("completed", 37 * MIN), {CHILD: Seen("completed", 1 * MIN)}, 35 * MIN, memory)

    assert CHILD in reason and "16 min temu" in reason and "nie ruszył" in reason


def test_koordynator_obudzony_po_koncu_dziecka_nie_dostaje_budzenia_choc_t3_potem_przesuwa_ruch_dziecka() -> None:
    memory = straznik.Memory()
    decide(Seen("completed", 2 * MIN), {CHILD: Seen("running", 1 * MIN)}, 0.0, memory)
    # Dziecko skończyło się w 19. minucie, T3 obudziło koordynatora, a jego tura skończyła się w 21. minucie.
    decide(Seen("completed", 4 * MIN), {CHILD: Seen("completed", 6 * MIN)}, 25 * MIN, memory)
    # Restart T3 w 50. minucie przesuwa ruch skończonego dziecka, ale nie jego koniec.
    later = {CHILD: Seen("completed", 10 * MIN)}

    assert decide(Seen("completed", 39 * MIN), later, 60 * MIN, memory) == []
    assert not pending(Seen("completed", 39 * MIN), later, 60 * MIN, memory)


def test_strażnik_ze_startu_sesji_budzi_przy_dziecku_skonczonym_po_ostatnim_ruchu_koordynatora() -> None:
    # Restart T3 przerwał dziecko po ostatniej turze koordynatora; strażnik startuje z wznowioną sesją.
    memory = straznik.Memory()
    assert decide(Seen("completed", 30 * MIN), {CHILD: Seen("interrupted", 5 * MIN)}, 0.0, memory) == []

    assert decide(Seen("completed", 41 * MIN), {CHILD: Seen("interrupted", 16 * MIN)}, 11 * MIN, memory)


def test_dziecko_wznowione_przez_koordynatora_budzi_po_swoim_drugim_koncu() -> None:
    memory = straznik.Memory()
    decide(Seen("completed", 2 * MIN), {CHILD: Seen("running", 1 * MIN)}, 0.0, memory)
    # Pierwszy koniec w 9. minucie, T3 budzi koordynatora, a ten w 12. minucie wznawia dziecko i kończy turę.
    decide(Seen("completed", 1 * MIN), {CHILD: Seen("completed", 1 * MIN)}, 10 * MIN, memory)
    decide(Seen("completed", 1 * MIN), {CHILD: Seen("preparing", 1 * MIN)}, 13 * MIN, memory)
    # Drugi koniec w 39. minucie, a T3 koordynatora nie budzi.
    decide(Seen("completed", 28 * MIN), {CHILD: Seen("completed", 1 * MIN)}, 40 * MIN, memory)

    (reason,) = decide(Seen("completed", 44 * MIN), {CHILD: Seen("completed", 17 * MIN)}, 56 * MIN, memory)

    assert "17 min temu" in reason


def test_dwa_budzenia_dzieli_przerwa_a_nowy_powod_po_niej_budzi() -> None:
    memory = straznik.Memory()
    parent = Seen("completed", 90 * MIN)
    first = {CHILD: Seen("running", 50 * MIN)}
    both = {**first, "dziecko-2": Seen("completed", 20 * MIN)}

    assert decide(parent, first, 0.0, memory)
    assert decide(parent, both, straznik.PAUSE_S - 1, memory) == []
    (reason,) = decide(parent, both, straznik.PAUSE_S + 1, memory)
    assert "dziecko-2" in reason


def test_strażnik_konczy_sie_dopiero_gdy_nic_nie_trwa_i_koordynator_ruszyl_po_koncu_dzieci() -> None:
    def after(parent_min: float, status: str, child_min: float) -> bool:
        memory = straznik.Memory()
        child = {CHILD: Seen(status, child_min * MIN)}
        decide(Seen("completed", 30 * MIN), {CHILD: Seen("running", 1 * MIN)}, 0.0, memory)
        decide(Seen("completed", parent_min * MIN), child, 10 * MIN, memory)
        return not pending(Seen("completed", parent_min * MIN), child, 10 * MIN, memory)

    assert after(1, "completed", 2)
    assert not after(3, "completed", 2)
    assert not after(1, "running", 50)
    assert not after(1, "preparing", 0)


def test_po_budzeniu_bez_odpowiedzi_strażnik_nie_ma_juz_czego_pilnowac() -> None:
    memory = straznik.Memory()
    decide(Seen("completed", 2 * MIN), {CHILD: Seen("running", 1 * MIN)}, 0.0, memory)
    decide(Seen("completed", 22 * MIN), {CHILD: Seen("completed", 1 * MIN)}, 20 * MIN, memory)
    done = {CHILD: Seen("completed", 16 * MIN)}
    assert pending(Seen("completed", 37 * MIN), done, 35 * MIN, memory)

    assert decide(Seen("completed", 37 * MIN), done, 35 * MIN, memory)
    assert not pending(Seen("completed", 37 * MIN), done, 35 * MIN, memory)


def test_dziecko_ktorego_t3_nie_pokazuje_przestaje_sie_liczyc_po_limicie() -> None:
    # Dziecko usunięte w trakcie albo środowisko odłączone: t3 thread show kończy się kodem 1.
    memory = straznik.Memory()
    parent = Seen("completed", 5 * MIN)
    decide(parent, {CHILD: Seen("running", 1 * MIN)}, 0.0, memory)
    decide(parent, {CHILD: None}, 10 * MIN, memory)

    assert pending(parent, {CHILD: None}, 10 * MIN + straznik.LOST_S, memory)
    assert not pending(parent, {CHILD: None}, 10 * MIN + straznik.LOST_S + 1, memory)


def test_dziecko_chwilowo_niewidoczne_ktore_wraca_dalej_jest_pilnowane() -> None:
    memory = straznik.Memory()
    decide(Seen("completed", 2 * MIN), {CHILD: Seen("running", 1 * MIN)}, 0.0, memory)
    assert decide(Seen("completed", 12 * MIN), {CHILD: None}, 10 * MIN, memory) == []

    (reason,) = decide(Seen("completed", 52 * MIN), {CHILD: Seen("running", 46 * MIN)}, 50 * MIN, memory)

    assert "bez ruchu od 46 min" in reason


def test_dwa_hooki_dopisuja_obu_dzieci_do_stanu(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    files = straznik._files(PARENT)

    straznik.record(files, [CHILD], 10.0)
    straznik.record(files, ["dziecko-2"], 20.0)

    assert straznik.entries(files.kids.read_text(encoding="utf-8"), 30.0, 60) == ([CHILD, "dziecko-2"], 20.0)


def test_limit_zycia_liczy_sie_od_najmlodszego_zlecenia() -> None:
    assert straznik.alive(100.0, 100.0 + 60, 60)
    assert not straznik.alive(100.0, 100.0 + 61, 60)
    assert not straznik.alive(None, 0.0, 60)


def test_wpis_dzieci_traci_znaczenie_po_limicie_a_linia_innej_postaci_nic_nie_znaczy() -> None:
    text = f"10.0 {CHILD}\n50.0 dziecko-2\nzepsuta linia\n70.0 {CHILD}\n80.0\n"

    assert straznik.entries(text, 100.0, 60) == (["dziecko-2", CHILD], 70.0)
    assert straznik.entries(text, 115.0, 60) == ([CHILD], 70.0)
    assert straznik.entries(text, 131.0, 60) == ([], None)


def test_ustawienia_wpinaja_hook_po_delegate_task_i_na_starcie_sesji() -> None:
    hooks = json.loads(SETTINGS.read_text(encoding="utf-8"))["hooks"]
    (after,) = hooks["PostToolUse"]
    (start,) = hooks["SessionStart"]

    assert after["matcher"] == straznik.DELEGATE
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
if sys.argv[1:3] == ["thread", "show"] and sys.argv[3] not in state:
    sys.exit(f"Thread {sys.argv[3]} is no longer available. Thread ids belong to one environment.")
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
        straznik.LIFE_ENV: "5",
    }
    yield tmp_path, env
    # Strażnik żyje po hooku z założenia; ten, którego test nie zakończył, kończy krótki limit życia.
    folder = home / straznik.STATE
    assert wait_for(lambda: not any(held(lock) for lock in folder.glob("*.zycie")), 15)


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
    event = {"hook_event_name": "PostToolUse", "tool_name": straznik.DELEGATE, "tool_response": _delegated(CHILD)}

    first, second = _hook(env, event), _hook(env, event)

    assert [(run.returncode, run.stdout) for run in (first, second)] == [(0, b""), (0, b"")]
    home = Path(env["HOME"])
    assert wait_for(lambda: any(row.get("zdarzenie") == "koniec" for row in _rows(home)), 30)
    (sent,) = (folder / "bin" / "wyslane.txt").read_text(encoding="utf-8").splitlines()
    assert sent.startswith(f"{PARENT} {straznik.NUDGE} dziecko {CHILD} (running) bez ruchu od 50 min")
    events = [row["zdarzenie"] for row in _rows(home)]
    # Drugi hook uruchamia drugi proces, który zostaje czekającym i nie budzi drugi raz.
    assert events.count("budzenie") == 1
    # Wznowiona sesja stawia strażnika na te same dzieci, ale nie ma już czego pilnować.
    assert _hook(env, {"hook_event_name": "SessionStart", "source": "resume"}).returncode == 0
    assert wait_for(lambda: [row.get("zdarzenie") for row in _rows(home)].count("koniec") == 2, 30)
    assert len((folder / "bin" / "wyslane.txt").read_text(encoding="utf-8").splitlines()) == 1


@POSIX_ONLY
def test_wznowiona_sesja_koordynatora_dostaje_strażnika_z_powrotem(
    t3: tuple[Path, dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Restart Maca zabił strażnika, zanim skończył; zostawił stan wątku, a T3 wznawia sesję koordynatora.
    folder, env = t3
    monkeypatch.setenv("HOME", env["HOME"])
    files = straznik._files(PARENT)
    straznik.record(files, [CHILD], time.time())

    assert _hook(env, {"hook_event_name": "SessionStart", "source": "resume"}).returncode == 0

    assert wait_for(lambda: any(row.get("zdarzenie") == "koniec" for row in _rows(Path(env["HOME"]))), 30)
    assert len((folder / "bin" / "wyslane.txt").read_text(encoding="utf-8").splitlines()) == 1


@POSIX_ONLY
@pytest.mark.parametrize(
    ("tool", "response"),
    [
        ("mcp__t3-code__t3_thread_launch", LAUNCHED),
        ("mcp__t3-code__create_threads", LAUNCHED),
        ("mcp__t3-code__delegate_task", REMOTE),
    ],
    ids=["watek-najwyzszego-poziomu", "watki-najwyzszego-poziomu", "dziecko-na-innym-srodowisku"],
)
def test_przekazanie_bez_budzenia_przez_t3_i_dziecko_spoza_srodowiska_nie_stawiaja_strażnika(
    t3: tuple[Path, dict[str, str]], tool: str, response: dict[str, object]
) -> None:
    _, env = t3

    assert _hook(env, {"hook_event_name": "PostToolUse", "tool_name": tool, "tool_response": response}).returncode == 0
    assert _rows(Path(env["HOME"])) == []
    assert list((Path(env["HOME"]) / straznik.STATE).glob("*.dzieci")) == []


@POSIX_ONLY
@pytest.mark.parametrize("missing", ["T3CODE_THREAD_ID", "T3CODE_CLI_PATH"])
def test_poza_t3_hook_nic_nie_zapisuje_i_nie_uruchamia(t3: tuple[Path, dict[str, str]], missing: str) -> None:
    _, env = t3
    env = {name: value for name, value in env.items() if name != missing}
    event = {"hook_event_name": "PostToolUse", "tool_name": straznik.DELEGATE, "tool_response": _delegated(CHILD)}

    assert (_hook(env, event).returncode, (Path(env["HOME"]) / straznik.STATE).exists()) == (0, False)


@POSIX_ONLY
def test_sesja_bez_zleconej_pracy_nie_zostawia_sladu(t3: tuple[Path, dict[str, str]]) -> None:
    _, env = t3

    assert _hook(env, {"hook_event_name": "SessionStart", "source": "startup"}).returncode == 0
    assert _rows(Path(env["HOME"])) == []


SLOW_T3 = r"""
import json, sys, time
from pathlib import Path

here = Path(__file__).parent
state = json.loads((here / "watki.json").read_text(encoding="utf-8"))
if sys.argv[1:3] == ["thread", "show"]:
    # Czas odpytania zmienia się z pytania na pytanie, jak na Macu pod obciążeniem.
    tick = here / "takt"
    slow = tick.exists()
    tick.unlink() if slow else tick.touch()
    time.sleep(0.15 if slow else 0.0)
    if sys.argv[3] not in state:
        sys.exit("Thread is no longer available. Thread ids belong to one environment.")
    print(json.dumps({"thread": {"threadId": sys.argv[3], **state[sys.argv[3]]}, "messages": []}))
elif sys.argv[1:3] == ["thread", "send"]:
    with (here / "wyslane.txt").open("a", encoding="utf-8") as sent:
        sent.write(sys.argv[4] + "\n")
"""


@POSIX_ONLY
@pytest.mark.parametrize(
    ("parent", "child"),
    [
        ({"status": "completed", "updatedAt": 55}, {"status": "running", "updatedAt": 50}),
        ({"status": "completed", "updatedAt": 55}, {"status": "running", "updatedAt": 0}),
        ({"status": "completed", "updatedAt": 55}, {"status": "waiting", "updatedAt": 50}),
        ({"status": "completed", "updatedAt": 55}, None),
        ({"status": "completed", "updatedAt": 55}, {"status": "completed", "updatedAt": 20}),
        ({"status": "running", "updatedAt": 0}, {"status": "running", "updatedAt": 50}),
        (None, {"status": "running", "updatedAt": 50}),
    ],
    ids=[
        "dziecko-stoi-po-budzeniu",
        "dziecko-pracuje",
        "dziecko-czeka-na-odpowiedz",
        "dziecka-nie-widac",
        "dziecko-skonczone-bez-odpowiedzi-koordynatora",
        "koordynator-pracuje",
        "koordynatora-nie-widac",
    ],
)
def test_strażnik_konczy_sie_w_limicie_zycia_w_kazdym_stanie_dziecka_i_przy_zmiennym_czasie_odpytania(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, parent: dict[str, object] | None, child: dict[str, object] | None
) -> None:
    # Nic w T3 się nie rusza, a koordynator nie odpowiada na budzenie; zostaje tylko granica życia.
    def ago(state: dict[str, object]) -> dict[str, object]:
        return {**state, "updatedAt": _ago(float(str(state["updatedAt"])))}

    program = fake_cli(tmp_path / "bin", "t3", SLOW_T3)
    threads = {name: ago(state) for name, state in ((PARENT, parent), (CHILD, child)) if state is not None}
    (tmp_path / "bin" / "watki.json").write_text(json.dumps(threads), encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path / "dom"))
    monkeypatch.setenv(straznik.STEP_ENV, "0.1")
    monkeypatch.setenv(straznik.LIFE_ENV, "2")
    monkeypatch.setattr(straznik, "LOST_S", 3600.0)
    files = straznik._files(PARENT)
    straznik.record(files, [CHILD], time.time())

    assert straznik.serve(PARENT, str(program)) == 0

    rows = map(json.loads, files.log.read_text(encoding="utf-8").splitlines())
    (end,) = [row for row in rows if row["zdarzenie"] == "koniec"]
    assert str(end["powod"]).startswith(("limit życia", "nie ma czego pilnować"))


NEW = "thread:delegated-task:dziecko-wymyslone-2"


class _T3InProcess:
    """T3 w pamięci dla przeplotów: koordynator ruszył po końcu pierwszego dziecka, nowe dziecko stoi od 50 min, a
    budzenie kończy nowe dziecko i rusza koordynatora; ``inject`` robi krok hooka w wybranym miejscu pętli strażnika."""

    def __init__(self, now: float) -> None:
        self.lock = threading.Lock()
        self.threads = {
            PARENT: straznik.Seen("completed", now - 10 * MIN),
            CHILD: straznik.Seen("completed", now - 30 * MIN),
            NEW: straznik.Seen("running", now - 50 * MIN),
        }
        self.sent: list[str] = []
        self.inject: tuple[str, Callable[[], None]] | None = None
        self.gate = threading.Event()

    def show(self, cli: str, thread: str) -> object:
        assert self.gate.wait(10)
        self._fire("show")
        with self.lock:
            return self.threads[thread]

    def send(self, cli: str, thread: str, text: str) -> int:
        with self.lock:
            self.sent.append(text)
            moved = time.time()
            self.threads = {**self.threads, NEW: straznik.Seen("completed", moved - 1), PARENT: straznik.Seen("completed", moved)}
        return 0

    def _fire(self, point: str) -> None:
        action, self.inject = (self.inject, None) if self.inject and self.inject[0] == point else (None, self.inject)
        if action:
            action[1]()


@POSIX_ONLY
@pytest.mark.parametrize(
    ("point", "waiting"),
    [
        ("show", False),
        ("koniec", False),
        ("po", False),
        ("show", True),
        ("koniec", True),
    ],
    ids=[
        "w-trakcie-odpytania",
        "po-decyzji-przed-oddaniem-zycia",
        "po-koncu-strażnika",
        "w-trakcie-odpytania-przy-czekajacym",
        "po-decyzji-przy-czekajacym",
    ],
)
def test_dziecko_zlecone_w_kazdej_chwili_konca_strażnika_ma_strażnika(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, point: str, waiting: bool
) -> None:
    # Koordynator zleca nowe dziecko w chwili, gdy strażnik pierwszego dziecka się kończy (krok hooka: dopisanie, potem
    # uruchomienie procesu), a nowe dziecko staje.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(straznik.STEP_ENV, "0.01")
    monkeypatch.setenv(straznik.LIFE_ENV, "10")
    t3 = _T3InProcess(time.time())
    monkeypatch.setattr(straznik, "_show", t3.show)
    monkeypatch.setattr(straznik, "_send", t3.send)
    files = straznik._files(PARENT)
    straznik.record(files, [CHILD], time.time())
    started: list[threading.Thread] = []

    def hook() -> None:
        straznik.record(files, [NEW], time.time())
        started.append(threading.Thread(target=straznik.serve, args=(PARENT, "t3")))
        started[-1].start()

    log = straznik._log

    def log_then_inject(path: Path, **row: object) -> None:
        log(path, **row)
        if row.get("zdarzenie") == "koniec":
            t3._fire("koniec")

    monkeypatch.setattr(straznik, "_log", log_then_inject)
    t3.inject = (point, hook)
    # Strażnik pierwszego dziecka bierze życie i czeka na T3; czekający (gdy jest) staje w kolejce.
    first = threading.Thread(target=straznik.serve, args=(PARENT, "t3"))
    first.start()
    assert wait_for(lambda: held(files.life), 5)
    if waiting:
        started.append(threading.Thread(target=straznik.serve, args=(PARENT, "t3")))
        started[-1].start()
        assert wait_for(lambda: held(files.queue), 5)
    t3.gate.set()
    first.join(15)
    assert not first.is_alive()
    if point == "po":
        hook()

    for thread in started:
        thread.join(15)
    assert [thread.is_alive() for thread in started] == [False] * len(started)
    assert [NEW in text for text in t3.sent] == [True]


@POSIX_ONLY
def test_dziecko_zlecone_w_trakcie_pilnowania_dostaje_budzenie_od_pilnujacego(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Pierwsze dziecko dalej pracuje, więc strażnik się nie kończy; nowe dziecko zlecone w trakcie staje.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(straznik.STEP_ENV, "0.01")
    monkeypatch.setenv(straznik.LIFE_ENV, "5")
    t3 = _T3InProcess(time.time())
    t3.threads[CHILD] = straznik.Seen("running", time.time())
    monkeypatch.setattr(straznik, "_show", t3.show)
    monkeypatch.setattr(straznik, "_send", t3.send)
    files = straznik._files(PARENT)
    straznik.record(files, [CHILD], time.time())
    first = threading.Thread(target=straznik.serve, args=(PARENT, "t3"))
    first.start()
    assert wait_for(lambda: held(files.life), 5)
    t3.gate.set()

    straznik.record(files, [NEW], time.time())

    # Pilnujący czyta plik w każdym przebiegu, więc budzi, zanim minie jego limit życia.
    assert wait_for(lambda: bool(t3.sent), 2)
    assert NEW in t3.sent[0]
    first.join(15)
    assert not first.is_alive()
