"""Hook ``tools/hooks/zgoda.py`` i jego wyrocznia: w trybie bypass pytanie o zgodę na Basha dostaje odmowę od razu.

Hook uruchamia Claude Code przy pytaniu o zgodę (zdarzenie ``PermissionRequest``), więc test podaje mu to zdarzenie
tak jak Claude Code: JSON na stdin, a decyzja to JSON na stdout. Wyrocznię ``tools/wyrocznia_zgody.py`` test uruchamia
z atrapą ``claude``, która woła API pod adresem, jaki wybrałby Claude Code (``tests/fixtures/ustawienia_claude.py``),
i uruchamia hook z ``.claude/settings.json`` przez prefiks powłoki wyroczni, tak jak robi to Claude Code 2.1.310.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from types import ModuleType
from typing import Any

import pytest

from tests.fixtures import ustawienia_claude

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "tools" / "hooks" / "zgoda.py"
ORACLE = ROOT / "tools" / "wyrocznia_zgody.py"
PREFIX = ROOT / "tools" / "wyrocznia_zgody_prefiks.sh"
CASES = ROOT / "tools" / "wyrocznia_zgody.jsonl"
SETTINGS = ROOT / ".claude" / "settings.json"
POSIX_ONLY = pytest.mark.skipif(sys.platform == "win32", reason="atrapa claude i prefiks to skrypty z linią #!")


@pytest.fixture(scope="module")
def hook() -> ModuleType:
    spec = importlib.util.spec_from_file_location("zgoda", HOOK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _request(mode: str) -> dict[str, Any]:
    tool_input = {"command": "cd /srv/x && rm -f logi/*", "description": "x"}
    return {
        "hook_event_name": "PermissionRequest",
        "permission_mode": mode,
        "tool_name": "Bash",
        "tool_input": tool_input,
    }


# Pytanie z reguły ``permissions.ask`` (``Bash(echo PYTAJ-MAKSA:*)``) w trybie bypass, jak je zapisał hook w rundzie 4 #496:
# od pytania o ``rm`` różni się tylko brakiem ``permission_suggestions``.
ASK_RULE = {
    "hook_event_name": "PermissionRequest",
    "permission_mode": "bypassPermissions",
    "tool_name": "Bash",
    "tool_input": {"command": "echo PYTAJ-MAKSA push", "description": "x"},
}
RM_CHECK = _request("bypassPermissions") | {
    "permission_suggestions": [{"type": "addRules", "rules": [{"toolName": "Bash", "ruleContent": "rm -f logi/*"}]}]
}
# Komunikat odmowy, który agent dostaje zamiast pytania, cały: wiersz reguły w AGENTS.md odsyła do niego, więc każde
# jego zdanie jest obietnicą, a sprawdzenie samych fragmentów przepuszczało zdania o odwrotnym sensie.
EXPECTED_MESSAGE = (
    "Claude Code zatrzymałby to polecenie Basha na zgodzie człowieka, a agent w trybie bypass nie czeka na zgodę, "
    "więc polecenie nie ruszyło. Gdy to rm, którego celu Claude Code nie ustali z tekstu polecenia, uruchom rm "
    "osobnym wywołaniem Basha z dosłowną ścieżką bezwzględną (rm -rf /abs/katalog/logi) albo ze zmienną w postaci "
    "${VAR:?}, a resztę polecenia w następnym wywołaniu. Kod i dane z rm zapisz do pliku narzędziem Write albo Edit, "
    "a nie w heredocu ani w napisie w poleceniu. Gdy polecenie pasuje do reguły permissions.ask z ustawień, potrzebuje "
    "zgody człowieka: nie obchodź jej innym zapisem, tylko napisz w odpowiedzi, o co prosisz."
)


def _permission_hooks() -> list[dict[str, Any]]:
    entries = json.loads(SETTINGS.read_text(encoding="utf-8"))["hooks"]["PermissionRequest"]
    return [hook for entry in entries if entry["matcher"] == "Bash" for hook in entry["hooks"]]


def _hook(stdin: bytes) -> subprocess.CompletedProcess[bytes]:
    (configured,) = _permission_hooks()
    # Claude Code po limicie z ustawień pomija hook, a wtedy pytanie idzie do człowieka.
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=stdin,
        capture_output=True,
        check=False,
        timeout=configured["timeout"],
    )


@pytest.mark.parametrize("event", [RM_CHECK, ASK_RULE], ids=["kontrola-rm", "regula-ask"])
def test_pytanie_o_zgode_w_trybie_bypass_dostaje_odmowe_z_kazda_poprawka(event: dict[str, Any]) -> None:
    hooked = _hook(json.dumps(event).encode())

    decision = json.loads(hooked.stdout)["hookSpecificOutput"]
    assert (
        hooked.returncode,
        decision["hookEventName"],
        decision["decision"]["behavior"],
    ) == (0, "PermissionRequest", "deny")
    assert decision["decision"]["message"] == EXPECTED_MESSAGE


@pytest.mark.parametrize("mode", ["default", "acceptEdits", "plan", "dontAsk", "auto", None])
def test_pytanie_o_zgode_poza_trybem_bypass_idzie_do_czlowieka(
    mode: str | None,
) -> None:
    hooked = _hook(json.dumps(_request(mode) if mode else {"tool_name": "Bash"}).encode())

    assert (hooked.returncode, hooked.stdout, hooked.stderr) == (0, b"", b"")


@pytest.mark.parametrize(
    "stdin",
    [b"", b"nie json", b"[]", b"null", b'"bypassPermissions"', b"\xff\xfe{", b"[" * 100000],
    ids=["pusto", "nie-json", "lista", "null", "napis", "nie-utf8", "gleboki-json"],
)
def test_nieczytelne_wejscie_hooka_idzie_do_czlowieka(stdin: bytes) -> None:
    hooked = _hook(stdin)

    assert (hooked.returncode, hooked.stdout, hooked.stderr) == (0, b"", b"")


def test_odmowa_dochodzi_przez_konsole_bez_polskich_liter(hook: ModuleType) -> None:
    # Claude Code wysyła UTF-8, a konsola Windows ma inne kodowanie: hook czyta bajty i wypisuje same znaki ASCII.
    event = _request("bypassPermissions") | {"tool_input": {"command": "rm -f /srv/zażółć/*"}}
    (configured,) = _permission_hooks()

    hooked = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(event, ensure_ascii=False).encode("utf-8"),
        env={**os.environ, "PYTHONIOENCODING": "ascii"},
        capture_output=True,
        check=False,
        timeout=configured["timeout"],
    )

    assert hooked.returncode == 0, hooked.stderr
    assert json.loads(hooked.stdout)["hookSpecificOutput"]["decision"]["message"] == hook.MESSAGE


def _configured(project: Path, mode: str) -> list[subprocess.CompletedProcess[str]]:
    return [
        subprocess.run(
            configured["command"],
            shell=True,
            input=json.dumps(_request(mode)),
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(project)},
            capture_output=True,
            text=True,
            check=False,
        )
        for configured in _permission_hooks()
    ]


@pytest.mark.skipif(sys.platform == "win32", reason="python3 na Windows bywa aliasem Microsoft Store")
def test_ustawienia_projektu_wpinaja_hook_zgody_dla_basha() -> None:
    hooked = _configured(ROOT, "bypassPermissions")

    assert [
        (
            run.returncode,
            json.loads(run.stdout)["hookSpecificOutput"]["decision"]["behavior"],
        )
        for run in hooked
    ] == [(0, "deny")]
    assert 0 < _permission_hooks()[0]["timeout"] <= 10


@pytest.mark.skipif(sys.platform == "win32", reason="python3 na Windows bywa aliasem Microsoft Store")
def test_checkout_bez_skryptu_hooka_zgody_zostawia_pytanie_czlowiekowi(
    tmp_path: Path,
) -> None:
    # Sesja trzyma ustawienia ze startu, a checkout sprzed hooka nie ma skryptu; python3 bez pliku kończy się kodem 2.
    hooked = _configured(tmp_path, "bypassPermissions")

    assert [(run.returncode, run.stdout, run.stderr) for run in hooked] == [(0, "", "")]


def test_przed_poleceniem_basha_biegnie_tylko_hook_czekania() -> None:
    # Odmowę rm daje teraz kontrola Claude Code przez hook zgody, a nie własny matcher przed poleceniem.
    entries = json.loads(SETTINGS.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]

    assert [hook["command"].rsplit("/", 1)[-1] for entry in entries for hook in entry["hooks"]] == ['czekanie.py"']


def test_przypadki_wyroczni_maja_dziesiec_przestojow_i_polecenia_ktore_claude_code_puszcza() -> None:
    rows = _rows(CASES)
    stalls = [row for row in rows if row["nazwa"].startswith("real-")]

    assert len(stalls) == 10
    assert all(row["pyta_o_zgode"] for row in stalls)
    assert any(not row["pyta_o_zgode"] for row in rows)


FAKE_CLAUDE = '''#!{python}
"""Atrapa claude: zachowuje się jak Claude Code 2.1.310 w trybie T3 wobec fałszywego API wyroczni."""
import json, os, select, subprocess, sys, time, urllib.request
sys.path.insert(0, {fixtures!r})
import ustawienia_claude
if sys.argv[1:] == ["--version"]:
    print("9.9.9 (Claude Code)")
    sys.exit(0)
with open(os.environ["ATRAPA_WYWOLANIA"], "a", encoding="utf-8") as calls:
    keys = ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_SHELL_PREFIX", "WYROCZNIA_ZGODY_HOOK",
            "MAXIMISEART_WYROCZNIA_W_SRODKU", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")
    calls.write(json.dumps({{"argv": sys.argv[1:], "cwd": os.getcwd(), "env": {{k: os.environ.get(k) for k in keys}}}}) + "\\n")
if os.environ.get("ATRAPA_CISZA"):
    time.sleep(600)
lines = [json.loads(sys.stdin.readline()) for _ in range(2)]
assert [line["type"] for line in lines] == ["control_request", "user"], lines
base = ustawienia_claude.base_url(sys.argv[1:], os.getcwd(), os.environ)
def api(body):
    with open(os.environ["ATRAPA_WYWOLANIA"] + ".api", "a", encoding="utf-8") as asked:
        asked.write(json.dumps(base) + "\\n")
    request = urllib.request.Request(base + "/v1/messages", data=json.dumps(body).encode(), method="POST")
    with urllib.request.urlopen(request) as answer:
        return answer.read().decode()
stream = api({{"model": "m", "stream": True, "tools": [{{"name": "Bash"}}], "messages": [{{"role": "user", "content": "x"}}]}})
deltas = [json.loads(line[6:]) for line in stream.splitlines() if line.startswith("data: ")]
command = json.loads(next(e["delta"]["partial_json"] for e in deltas if e["type"] == "content_block_delta"))["command"]
def emit(event):
    print(json.dumps(event), flush=True)
emit({{"type": "assistant", "message": {{"content": [{{"type": "tool_use", "name": "Bash", "input": {{"command": command}}}}]}}}})
with open(os.environ["ATRAPA_WYWOLANIA"] + ".polecenia", "a", encoding="utf-8") as sent:
    sent.write(json.dumps(command) + "\\n")
prefix = os.environ["CLAUDE_CODE_SHELL_PREFIX"]
if "PYTA" in command:
    emit({{"type": "control_request", "request_id": "r1", "request": {{"subtype": "can_use_tool", "tool_name": "Bash"}}}})
    settings = json.load(open(os.path.join(os.getcwd(), ".claude", "settings.json"), encoding="utf-8"))
    hooks = [h["command"] for e in settings["hooks"].get("PermissionRequest", []) for h in e["hooks"]]
    event = {{"hook_event_name": "PermissionRequest", "permission_mode": "bypassPermissions", "tool_name": "Bash"}}
    answers = [
        subprocess.run([prefix, h], input=json.dumps(event), capture_output=True, text=True,
                       env={{**os.environ, "CLAUDE_PROJECT_DIR": os.getcwd()}}).stdout
        for h in hooks
    ] if "HOOK" in command else []
    denials = [json.loads(a)["hookSpecificOutput"]["decision"]["message"] for a in answers if a.strip()]
    # Claude Code przerywa pytanie, gdy host zamknął wejście, zanim hook odpowiedział (claude -p bez stdin).
    closed = select.select([sys.stdin], [], [], 0)[0] and sys.stdin.read() == ""
    if closed:
        result = "Tool permission request failed: AbortError: Stream closed"
    elif denials:
        emit({{"type": "control_cancel_request", "request_id": "r1"}})
        result = denials[0]
    else:
        sys.stdin.read()
        result = "Tool permission request failed: AbortError: Stream closed"
else:
    shell = subprocess.run([prefix, "eval " + command + " && pwd -P >| /dev/null"], capture_output=True, text=True).stdout
    # Wynik powłoki Claude Code oddaje też jako listę bloków tekstu.
    result = [{{"type": "text", "text": shell}}]
emit({{"type": "user", "message": {{"content": [{{"type": "tool_result", "content": result}}]}}}})
answered = {{"role": "user", "content": [{{"type": "tool_result", "content": result}}]}}
api({{"model": "m", "stream": True, "tools": [{{"name": "Bash"}}], "messages": [answered]}})
# Claude Code w trybie stream-json nie kończy się sam po turze.
while True:
    time.sleep(60)
'''


def _oracle(
    tmp_path: Path,
    cases: list[dict[str, Any]],
    *arguments: str,
    timeout: float = 60,
    env: dict[str, str] | None = None,
    user_settings: dict[str, Any] | None = None,
) -> subprocess.CompletedProcess[str]:
    programs = tmp_path / "bin"
    programs.mkdir()
    claude = programs / "claude"
    fixtures = str(Path(ustawienia_claude.__file__).parent)
    claude.write_text(FAKE_CLAUDE.format(python=sys.executable, fixtures=fixtures), encoding="utf-8")
    claude.chmod(claude.stat().st_mode | stat.S_IXUSR)
    listed = tmp_path / "przypadki.jsonl"
    listed.write_text("".join(json.dumps(case) + "\n" for case in cases), encoding="utf-8")
    # Piaskownica wyroczni powstaje w ``~/.cache``, więc każdy test ma własny katalog domowy.
    (tmp_path / "dom" / ".claude").mkdir(parents=True)
    if user_settings is not None:
        (tmp_path / "dom" / ".claude" / "settings.json").write_text(json.dumps(user_settings), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(ORACLE), "--przypadki", str(listed), *arguments],
        env={
            **os.environ,
            "HOME": str(tmp_path / "dom"),
            "PATH": f"{programs}{os.pathsep}/usr/bin{os.pathsep}/bin",
            "ATRAPA_WYWOLANIA": str(tmp_path / "wywolania.jsonl"),
            "CLAUDECODE": "1",
            "CLAUDE_CODE_ENTRYPOINT": "sdk-ts",
            "ANTHROPIC_AUTH_TOKEN": "token-huba",
            **(env or {}),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


@POSIX_ONLY
def test_wyrocznia_z_odmowa_hooka_i_poleceniem_w_powloce_konczy_sie_ok_przed_limitem_hosta(
    tmp_path: Path,
) -> None:
    # Host czeka 600 s, a test najwyżej 60 s: wyrocznia zamyka wejście, gdy tura się skończyła.
    ran = _oracle(
        tmp_path,
        [
            {
                "nazwa": "przestoj",
                "polecenie": "cd @TFAR@ && rm -f logi/* # PYTA HOOK",
                "pyta_o_zgode": True,
            },
            {"nazwa": "kontrola", "polecenie": "rm -f @FAR@/x", "pyta_o_zgode": False},
        ],
        "--host-s",
        "600",
    )

    assert ran.stdout.splitlines() == [
        "Claude Code 9.9.9 (Claude Code), przypadki 2",
        "ZGODNE przestoj | odmowa hooka",
        "ZGODNE kontrola | powłoka",
        "WYROCZNIA OK | Claude Code 9.9.9 (Claude Code) | ZGODNE 2",
    ], ran.stderr
    assert ran.returncode == 0


@POSIX_ONLY
def test_wyrocznia_gdy_claude_code_czeka_na_hosta_konczy_sie_przestojem(
    tmp_path: Path,
) -> None:
    ran = _oracle(
        tmp_path,
        [
            {
                "nazwa": "bez-hooka",
                "polecenie": "rm -f $X/y # PYTA",
                "pyta_o_zgode": True,
            },
            {
                "nazwa": "z-hookiem",
                "polecenie": "rm -f $X/z # PYTA HOOK",
                "pyta_o_zgode": True,
            },
        ],
        "--host-s",
        "1",
    )

    assert ran.stdout.splitlines()[1:] == [
        "PRZESTÓJ bez-hooka | czekał na hosta",
        "ZGODNE z-hookiem | odmowa hooka",
        "WYROCZNIA PRZESTÓJ | Claude Code 9.9.9 (Claude Code) | PRZESTÓJ 1, ZGODNE 1",
    ], ran.stderr
    assert ran.returncode == 1


@POSIX_ONLY
def test_wyrocznia_gdy_claude_code_rozstrzyga_inaczej_niz_plik_konczy_sie_zmiana(
    tmp_path: Path,
) -> None:
    ran = _oracle(
        tmp_path,
        [
            {
                "nazwa": "juz-nie-pyta",
                "polecenie": "rm -f @FAR@/a",
                "pyta_o_zgode": True,
            },
            {
                "nazwa": "teraz-pyta",
                "polecenie": "rm -f @FAR@/b # PYTA HOOK",
                "pyta_o_zgode": False,
            },
        ],
    )

    assert ran.stdout.splitlines()[1:] == [
        "ZMIANA juz-nie-pyta | powłoka",
        "ZMIANA teraz-pyta | odmowa hooka",
        "WYROCZNIA ZMIANA | Claude Code 9.9.9 (Claude Code) | ZMIANA 2",
    ], ran.stderr
    assert ran.returncode == 1


@POSIX_ONLY
def test_wyrocznia_bez_ani_jednej_odmowy_hooka_nie_konczy_sie_ok(
    tmp_path: Path,
) -> None:
    # Same polecenia, które Claude Code puszcza, nie sprawdzają hooka, więc OK niczego by nie znaczyło.
    ran = _oracle(
        tmp_path,
        [{"nazwa": "kontrola", "polecenie": "rm -f @FAR@/x", "pyta_o_zgode": False}],
    )

    assert ran.stdout.splitlines()[1:] == [
        "ZGODNE kontrola | powłoka",
        "WYROCZNIA ZMIANA | Claude Code 9.9.9 (Claude Code) | ZGODNE 1, hook nie odmówił ani razu",
    ], ran.stderr
    assert ran.returncode == 1


@POSIX_ONLY
@pytest.mark.parametrize(
    "tail",
    ["", "; echo tools/hooks/zgoda.py", f"; {_permission_hooks()[0]['command']}"],
    ids=["samo", "ze-sciezka-hooka", "z-poleceniem-hooka"],
)
def test_wyrocznia_nie_wykonuje_polecen_przypadkow(tmp_path: Path, tail: str) -> None:
    # Przestój przy edycji hooka zgody będzie miał jego ścieżkę w treści, a wyrocznia biegnie w checkoucie.
    done = tmp_path / "wykonane"

    ran = _oracle(
        tmp_path,
        [{"nazwa": "touch", "polecenie": f"touch {done}{tail}", "pyta_o_zgode": False}],
    )

    assert ran.stdout.splitlines()[1] == "ZGODNE touch | powłoka", ran.stderr
    assert not done.exists()


@POSIX_ONLY
def test_wyrocznia_uruchamia_claude_code_jak_t3_w_katalogu_checkoutu_z_falszywym_api(tmp_path: Path) -> None:
    ran = _oracle(tmp_path, [{"nazwa": "tylda", "polecenie": "rm -f @TFAR@/x # PYTA HOOK", "pyta_o_zgode": True}])

    (call,) = _rows(tmp_path / "wywolania.jsonl")
    argv = call["argv"]
    flags = ("--input-format", "--output-format", "--permission-prompt-tool", "--permission-mode", "--tools")
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert [argv[argv.index(flag) + 1] for flag in flags] == [
        "stream-json",
        "stream-json",
        "stdio",
        "bypassPermissions",
        "default",
    ]
    assert {"--verbose", "--allow-dangerously-skip-permissions"} <= set(argv)
    # Reguła zespołu: Claude Code wyroczni, gdyby jednak zapytał model, pyta Opusa.
    assert (argv[argv.index("--model") + 1], argv[argv.index("--setting-sources") + 1]) == (
        "claude-opus-5-5",
        "project,local",
    )
    assert call["cwd"] == str(ROOT)
    assert call["env"]["ANTHROPIC_BASE_URL"].startswith("http://127.0.0.1:")
    assert json.loads(argv[argv.index("--settings") + 1])["env"]["ANTHROPIC_BASE_URL"] == call["env"]["ANTHROPIC_BASE_URL"]
    env = (call["env"]["CLAUDE_CODE_SHELL_PREFIX"], call["env"]["CLAUDECODE"], call["env"]["CLAUDE_CODE_ENTRYPOINT"])
    assert env == (str(PREFIX), None, None)
    assert (call["env"]["ANTHROPIC_AUTH_TOKEN"], call["env"]["MAXIMISEART_WYROCZNIA_W_SRODKU"]) == (None, "1")
    assert call["env"]["WYROCZNIA_ZGODY_HOOK"] == _permission_hooks()[0]["command"]
    (command,) = [json.loads(line) for line in (tmp_path / "wywolania.jsonl.polecenia").read_text().splitlines()]
    assert re.fullmatch(r"rm -f ~/\.cache/wyrocznia-zgody-\w+/far/x # PYTA HOOK", command), command


@POSIX_ONLY
def test_wyrocznia_pyta_tylko_falszywe_api_takze_gdy_ustawienia_uzytkownika_maja_adres_huba(tmp_path: Path) -> None:
    # 5.11.2026 env.ANTHROPIC_BASE_URL huba z ~/.claude/settings.json wygrał z adresem fałszywego API w środowisku (#956).
    hub = {"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:9", "ANTHROPIC_AUTH_TOKEN": "token-huba"}}

    ran = _oracle(
        tmp_path,
        [
            {"nazwa": "odmowa", "polecenie": "rm -f @FAR@/x # PYTA HOOK", "pyta_o_zgode": True},
            {"nazwa": "kontrola", "polecenie": "rm -f @FAR@/y", "pyta_o_zgode": False},
        ],
        user_settings=hub,
    )

    assert ran.stdout.splitlines()[-1] == "WYROCZNIA OK | Claude Code 9.9.9 (Claude Code) | ZGODNE 2", ran.stderr
    fake = {call["env"]["ANTHROPIC_BASE_URL"] for call in _rows(tmp_path / "wywolania.jsonl")}
    asked = [json.loads(line) for line in (tmp_path / "wywolania.jsonl.api").read_text(encoding="utf-8").splitlines()]
    # Każda atrapa pyta dwa razy (polecenie, potem wynik narzędzia), zawsze adres z wywołania wyroczni.
    assert (len(asked), set(asked) <= fake) == (4, True)
    assert all(url.startswith("http://127.0.0.1:") and url != "http://127.0.0.1:9" for url in fake)


@POSIX_ONLY
def test_wyrocznia_konczy_claude_code_ktory_nie_pyta_falszywego_api(tmp_path: Path) -> None:
    # Host czeka 600 s: przypadek kończy brak kontaktu, bo taki Claude Code pyta inny model.
    ran = _oracle(
        tmp_path,
        [{"nazwa": "cisza", "polecenie": "rm -f @FAR@/x # PYTA HOOK", "pyta_o_zgode": True}],
        "--host-s",
        "600",
        "--kontakt-s",
        "1",
        env={"ATRAPA_CISZA": "1"},
    )

    assert ran.stdout.splitlines()[1:] == [
        "ZMIANA cisza | Claude Code nie zapytał fałszywego API",
        "WYROCZNIA ZMIANA | Claude Code 9.9.9 (Claude Code) | ZMIANA 1",
    ], ran.stderr
    assert ran.returncode == 1


@POSIX_ONLY
def test_wyrocznia_uruchomiona_w_claude_code_wyroczni_nie_uruchamia_claude(tmp_path: Path) -> None:
    ran = _oracle(
        tmp_path,
        [{"nazwa": "odmowa", "polecenie": "rm -f @FAR@/x # PYTA HOOK", "pyta_o_zgode": True}],
        env={"MAXIMISEART_WYROCZNIA_W_SRODKU": "1"},
    )

    assert (ran.returncode, ran.stdout.splitlines(), (tmp_path / "wywolania.jsonl").exists()) == (
        2,
        ["WYROCZNIA BRAK | uruchomiona w Claude Code wyroczni (MAXIMISEART_WYROCZNIA_W_SRODKU)"],
        False,
    )


@POSIX_ONLY
def test_wyrocznia_wybiera_przypadki_z_nazwy_i_usuwa_piaskownice(
    tmp_path: Path,
) -> None:
    ran = _oracle(
        tmp_path,
        [
            {
                "nazwa": "wybrany",
                "polecenie": "rm -f @FAR@/logi/a # PYTA HOOK",
                "pyta_o_zgode": True,
            },
            {
                "nazwa": "pominiety",
                "polecenie": "rm -f @FAR@/logi/b # PYTA",
                "pyta_o_zgode": True,
            },
        ],
        "wybrany",
    )

    assert ran.stdout.splitlines()[-1] == "WYROCZNIA OK | Claude Code 9.9.9 (Claude Code) | ZGODNE 1", ran.stderr
    assert list((tmp_path / "dom" / ".cache").iterdir()) == []


@POSIX_ONLY
def test_wyrocznia_bez_claude_na_path_konczy_sie_kodem_2(tmp_path: Path) -> None:
    (tmp_path / "dom").mkdir()

    ran = subprocess.run(
        [sys.executable, str(ORACLE), "--przypadki", str(CASES)],
        env={**os.environ, "HOME": str(tmp_path / "dom"), "PATH": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )

    assert (ran.returncode, ran.stdout) == (
        2,
        "WYROCZNIA BRAK | potrzebny claude na PATH na macOS albo Linuksie\n",
    )


@POSIX_ONLY
@pytest.mark.parametrize(
    ("command", "printed"),
    [
        ("echo hook zgody", "hook zgody\n"),
        ("echo hook zgody; echo przypadek", "WYROCZNIA-ZGODY-NIE-WYKONANO\n"),
        ("eval 'echo hook zgody' && pwd -P >| /dev/null", "WYROCZNIA-ZGODY-NIE-WYKONANO\n"),
        ("echo inny hook", "WYROCZNIA-ZGODY-NIE-WYKONANO\n"),
    ],
    ids=["hook-zgody", "polecenie-z-hookiem-zgody", "polecenie-basha", "inny-hook"],
)
def test_prefiks_wyroczni_wykonuje_tylko_polecenie_rowne_hookowi_zgody(command: str, printed: str) -> None:
    ran = subprocess.run(
        [str(PREFIX), command],
        env={**os.environ, "WYROCZNIA_ZGODY_HOOK": "echo hook zgody"},
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert (ran.returncode, ran.stdout) == (0, printed)
