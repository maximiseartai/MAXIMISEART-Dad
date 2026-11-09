"""``falszywe_api.claude``: Claude Code wyroczni hooka pyta tylko fałszywe API, także gdy ustawienia checkoutu albo sesja
wokół niego kierują gdzie indziej.

Wyrocznie (``tests/test_zgoda.py``, ``tests/test_praca_w_tle.py``) sprawdzają to przez swoje przypadki; tu są
zabezpieczenia, których żaden przypadek wyroczni nie dosięga, bo wyrocznia sama pyta ``nested`` na starcie, nie
zapisuje ustawień w checkoucie i nie zaczyna przypadku, zanim poprzednie ``claude`` skończy. Atrapa ``claude`` pyta adres,
który wybrałby Claude Code 2.1.318 (``tests/fixtures/ustawienia_claude.py``).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import threading
import time

import pytest

from tests.fixtures import ustawienia_claude
from tests.fixtures.fake_cli import ONLY_FOUND_BY_NAME_ON_POSIX, fake_cli

import falszywe_api

ROOT = Path(__file__).resolve().parents[1]

FAKE_CLAUDE = '''import json, os, sys, time, urllib.request
sys.path.insert(0, {fixtures!r})
import ustawienia_claude
with open(os.environ["ATRAPA_WYWOLANIA"], "a", encoding="utf-8") as calls:
    calls.write(json.dumps({{"argv": sys.argv[1:], "env": dict(os.environ)}}) + "\\n")
if os.environ.get("ATRAPA_BEZ_API"):
    sys.exit(0)
base = ustawienia_claude.base_url(sys.argv[1:], os.getcwd(), os.environ)
urllib.request.urlopen(urllib.request.Request(base + "/v1/messages", data=b"{{}}", method="POST")).read()
time.sleep(max(0.0, float(os.environ.get("ATRAPA_DO", "0")) - time.time()))
'''


@pytest.fixture
def calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Plik wywołań atrapy ``claude``, która jest jedynym ``claude`` na ``PATH``."""

    programs = tmp_path / "bin"
    fake_cli(programs, "claude", FAKE_CLAUDE.format(fixtures=str(Path(ustawienia_claude.__file__).parent)))
    monkeypatch.setenv("PATH", f"{programs}{os.pathsep}/usr/bin{os.pathsep}/bin")
    monkeypatch.delenv(falszywe_api.NESTED, raising=False)
    return tmp_path / "wywolania.jsonl"


def _claude(
    calls: Path, cwd: Path, stop: threading.Event, contact_s: float = falszywe_api.CONTACT_S, **env: str
) -> falszywe_api.Ran:
    return falszywe_api.claude(
        ["-p", "x"],
        answer=lambda body: falszywe_api.stream({"type": "text", "text": "ok"}),
        cwd=cwd,
        env={"ATRAPA_WYWOLANIA": str(calls), **env},
        timeout=60,
        stop=stop,
        contact_s=contact_s,
    )


# Przełącznik każdego dostawcy i gniazdo API, które Claude Code 2.1.318 wybiera zamiast ``ANTHROPIC_BASE_URL``.
REDIRECTS = {**dict.fromkeys(ustawienia_claude.PROVIDERS, "1"), ustawienia_claude.SOCKET: "/tmp/gniazdo-huba"}


@ONLY_FOUND_BY_NAME_ON_POSIX
@pytest.mark.parametrize(
    ("settings", "switch"),
    [(("settings.json", "settings.local.json")[index % 2], name) for index, name in enumerate(REDIRECTS)],
)
def test_claude_pyta_falszywe_api_takze_gdy_ustawienia_checkoutu_wlaczaja_innego_dostawce(
    calls: Path, tmp_path: Path, settings: str, switch: str
) -> None:
    checkout = tmp_path / "checkout"
    (checkout / ".claude").mkdir(parents=True)
    (checkout / ".claude" / settings).write_text(json.dumps({"env": {switch: REDIRECTS[switch]}}), encoding="utf-8")

    ran = _claude(calls, checkout, threading.Event())

    assert ran == falszywe_api.Ran(0, True)


@ONLY_FOUND_BY_NAME_ON_POSIX
def test_claude_dostaje_ze_srodowiska_wyroczni_tylko_liste_dozwolona(
    calls: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 5.11.2026 adres huba doszedł do claude wyroczni, a każda zmienna spoza listy (adres, gniazdo, pośrednik,
    # przełącznik dostawcy, token, sesja Claude Code) może skierować je do prawdziwego modelu (#956).
    allowed = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path / "dom"),
        "TMPDIR": str(tmp_path),
        "USER": "maks",
        "LOGNAME": "maks",
        "SHELL": "/bin/zsh",
        "LANG": "pl_PL.UTF-8",
        "LC_ALL": "pl_PL.UTF-8",
        "LC_CTYPE": "pl_PL.UTF-8",
    }
    for name, value in allowed.items():
        monkeypatch.setenv(name, value)
    for name in ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "HTTPS_PROXY", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    if sys.platform != "win32":  # ``os.environb`` jest tylko na POSIX, a test i tak biegnie tylko tam
        monkeypatch.setitem(os.environb, b"ANTHROPIC_UNIX_SOCKET", b"/tmp/gniazdo-huba")
        monkeypatch.setitem(os.environb, b"ALL_PROXY", b"http://127.0.0.1:9")

    ran = _claude(calls, tmp_path, threading.Event())

    (call,) = [json.loads(line) for line in calls.read_text(encoding="utf-8").splitlines()]
    oracle = {"ATRAPA_WYWOLANIA": str(calls), falszywe_api.NESTED: "1", "ANTHROPIC_API_KEY": "sk-ant-wyrocznia"}
    fake = call["env"].pop("ANTHROPIC_BASE_URL")
    # macOS dopisuje kodowanie tekstu Core Foundation każdemu procesowi, który go nie ma.
    call["env"].pop("__CF_USER_TEXT_ENCODING", None)
    assert (ran, call["env"]) == (falszywe_api.Ran(0, True), {**allowed, **oracle})
    assert fake.startswith("http://127.0.0.1:") and fake != "http://127.0.0.1:9"


@ONLY_FOUND_BY_NAME_ON_POSIX
def test_claude_w_sesji_wyroczni_odmawia_i_niczego_nie_uruchamia(
    calls: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Wyrocznia w Claude Code wyroczni uruchamiałaby kolejne sesje (5.11.2026: ok. 100, #956).
    monkeypatch.setenv(falszywe_api.NESTED, "1")

    with pytest.raises(falszywe_api.Nested, match=falszywe_api.NESTED):
        _claude(calls, tmp_path, threading.Event())

    assert not calls.exists()


@ONLY_FOUND_BY_NAME_ON_POSIX
def test_straznik_kontaktu_przypadku_bez_zapytania_nie_konczy_nastepnego_przypadku(calls: Path, tmp_path: Path) -> None:
    # Wyrocznia dzieli jedno ``stop`` między przypadki; ``claude`` pierwszego kończy się samo przed ``contact_s``,
    # a drugie trwa, aż ``contact_s`` pierwszego minie. Atrapa (Python z ``json`` i ``urllib``) startuje na Macu
    # w 0,02 s (``/usr/bin/time``, 5.11.2026), więc 3 s to zapas na obciążone CI.
    stop = threading.Event()
    contact_s = 3.0
    first_deadline = time.time() + contact_s

    first = _claude(calls, tmp_path, stop, contact_s=contact_s, ATRAPA_BEZ_API="1")
    second = _claude(calls, tmp_path, stop, ATRAPA_DO=str(first_deadline + 0.5))

    assert (first, second) == (falszywe_api.Ran(0, False), falszywe_api.Ran(0, True))
