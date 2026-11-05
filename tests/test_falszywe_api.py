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
import stat
import sys
import threading

import pytest

from tests.fixtures import ustawienia_claude

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "lib"))

import falszywe_api  # noqa: E402

POSIX_ONLY = pytest.mark.skipif(sys.platform == "win32", reason="atrapa claude to skrypt z linią #!")
FAKE_CLAUDE = '''#!{python}
import json, os, sys, time, urllib.request
sys.path.insert(0, {fixtures!r})
import ustawienia_claude
with open(os.environ["ATRAPA_WYWOLANIA"], "a", encoding="utf-8") as calls:
    calls.write(json.dumps(sys.argv[1:]) + "\\n")
if os.environ.get("ATRAPA_BEZ_API"):
    sys.exit(0)
base = ustawienia_claude.base_url(sys.argv[1:], os.getcwd(), os.environ)
urllib.request.urlopen(urllib.request.Request(base + "/v1/messages", data=b"{{}}", method="POST")).read()
time.sleep(float(os.environ.get("ATRAPA_PO_API_S", "0")))
'''


@pytest.fixture
def calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Plik wywołań atrapy ``claude``, która jest jedynym ``claude`` na ``PATH``."""

    programs = tmp_path / "bin"
    programs.mkdir()
    claude = programs / "claude"
    fixtures = str(Path(ustawienia_claude.__file__).parent)
    claude.write_text(FAKE_CLAUDE.format(python=sys.executable, fixtures=fixtures), encoding="utf-8")
    claude.chmod(claude.stat().st_mode | stat.S_IXUSR)
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


@POSIX_ONLY
@pytest.mark.parametrize(
    ("settings", "switch"),
    [(("settings.json", "settings.local.json")[index % 2], name) for index, name in enumerate(ustawienia_claude.PROVIDERS)],
)
def test_claude_pyta_falszywe_api_takze_gdy_ustawienia_checkoutu_wlaczaja_innego_dostawce(
    calls: Path, tmp_path: Path, settings: str, switch: str
) -> None:
    checkout = tmp_path / "checkout"
    (checkout / ".claude").mkdir(parents=True)
    (checkout / ".claude" / settings).write_text(json.dumps({"env": {switch: "1"}}), encoding="utf-8")

    ran = _claude(calls, checkout, threading.Event())

    assert ran == falszywe_api.Ran(0, True)


@POSIX_ONLY
def test_claude_w_sesji_wyroczni_odmawia_i_niczego_nie_uruchamia(
    calls: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Wyrocznia w Claude Code wyroczni uruchamiałaby kolejne sesje (5.11.2026: ok. 100, #956).
    monkeypatch.setenv(falszywe_api.NESTED, "1")

    with pytest.raises(falszywe_api.Nested, match=falszywe_api.NESTED):
        _claude(calls, tmp_path, threading.Event())

    assert not calls.exists()


@POSIX_ONLY
def test_straznik_kontaktu_przypadku_bez_zapytania_nie_konczy_nastepnego_przypadku(calls: Path, tmp_path: Path) -> None:
    # Wyrocznia dzieli jedno ``stop`` między przypadki; ``claude`` pierwszego kończy się samo przed ``contact_s``,
    # a drugie trwa dłużej niż reszta ``contact_s`` pierwszego.
    stop = threading.Event()

    first = _claude(calls, tmp_path, stop, contact_s=1.0, ATRAPA_BEZ_API="1")
    second = _claude(calls, tmp_path, stop, ATRAPA_PO_API_S="2.5")

    assert (first, second) == (falszywe_api.Ran(0, False), falszywe_api.Ran(0, True))
