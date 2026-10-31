"""Sprawdzenie modelu TLA+ Kolejki Skrzynki nie przechodzi w CI, gdy pokryty kod rozjechał się z modelem.

Podstawa skilla w CI (``sprawdz_kolejke.py``) uruchamia model i sprawdzenie prawdziwego kodu, każde do końca, i pada,
gdy padło którekolwiek; w częściach ``MUTACJE_CZESC=k/n`` każda jednostka biegnie w jednej części.

Znane znalezisko z ``model/oczekiwane.json`` wybacza tylko swoją obietnicę i tylko przebieg, który przeszedł przez jego
przyczynę: kontrprzykład innej obietnicy albo bez tej przyczyny to nowe naruszenie (werdykt FAIL #638).

Model opisuje kod z commitu synchronizacji w ``SKILL.md`` skilla ``verify-kolejka-skrzynki``. Javę, ``tla2tools.jar``
i porównanie z commitem bierze ze skryptu skilla ``verify-aktualizacja-narzedzia``, a zmienne ``TLC_JAVA`` i
``TLC_JAR`` (kopia checkoutu mutacji) zastępują jego Javę i jar.
"""

from __future__ import annotations

from collections.abc import Callable
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import ModuleType, SimpleNamespace

import pytest

from tests.fixtures.git_repo import commit, git

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "ci"))

import mutacje  # noqa: E402
import mutacje_skilli  # noqa: E402

SCRIPT = ROOT / ".agents" / "skills" / "verify-kolejka-skrzynki" / "scripts" / "sprawdz_model_kolejki.py"
BASELINE = ROOT / ".agents" / "skills" / "verify-kolejka-skrzynki" / "scripts" / "sprawdz_kolejke.py"
EXPLORER = ROOT / ".agents" / "skills" / "verify-kolejka-skrzynki" / "scripts" / "explore_outbox.py"
SKILL_MD = ROOT / ".agents" / "skills" / "verify-kolejka-skrzynki" / "SKILL.md"
TOOLS = ROOT / ".agents" / "skills" / "verify-aktualizacja-narzedzia" / "scripts" / "sprawdz_aktualizacje.py"
COVERED = "src/rozliczenia/centrum/outbox.py"
DRIFT = "MODEL KOLEJKI: ROZJAZD MODELU Z KODEM"
APP = ROOT / "src" / "rozliczenia" / "centrum" / "app.py"
LAUNCHER = ROOT / "src" / "rozliczenia" / "centrum" / "launcher.py"
SERVER = ROOT / "src" / "rozliczenia" / "centrum" / "server.py"
PASSED = "Model checking completed. No error has been found.\n"


def _load(path: Path = SCRIPT) -> ModuleType:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _violation(invariant: str, causes: str) -> str:
    """Wyjście TLC z kontrprzykładem ``invariant``, którego ostatni stan ma ``slady`` równe ``causes``."""

    return "\n".join(
        [
            f"Error: Invariant {invariant} is violated.",
            "State 1: <Initial predicate>",
            '/\\ krok = "start"',
            '/\\ plik = <<"czeka">>',
            "/\\ issues = <<>>",
            "/\\ slady = {}",
            "State 2: <Komentuj line 324, col 5 to line 352, col 63 of module KolejkaSkrzynki>",
            '/\\ krok = "comment: Rejected"',
            '/\\ plik = <<"usuniety">>',
            "/\\ issues = <<>>",
            f"/\\ slady = {causes}",
        ]
    )


def test_w_ci_pokryty_kod_zmieniony_od_synchronizacji_konczy_sprawdzenie_modelu_kolejki_porazka(tmp_path: Path) -> None:
    (tmp_path / COVERED).parent.mkdir(parents=True)
    (tmp_path / COVERED).write_text("X = 1\n", encoding="utf-8")
    for script in (SCRIPT, TOOLS):
        copy = tmp_path / script.relative_to(ROOT)
        copy.parent.mkdir(parents=True)
        shutil.copy(script, copy)
    git(tmp_path, "init", "--quiet")
    sync = commit(tmp_path, "synchronizacja")
    (tmp_path / COVERED).write_text("X = 2\n", encoding="utf-8")
    commit(tmp_path, "zmiana pokrytego kodu")
    skill = tmp_path / SCRIPT.relative_to(ROOT).parents[1]
    (skill / "SKILL.md").write_text(f"Covered: `{COVERED}`.\n\n**Sync commit: `{sync[:8]}`** (main).\n", encoding="utf-8")

    done = subprocess.run(
        [sys.executable, str(skill / "scripts" / SCRIPT.name)],
        cwd=tmp_path,
        env={**os.environ, "GITHUB_ACTIONS": "true"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )

    assert done.returncode == 1, done.stdout + done.stderr
    assert done.stdout.splitlines()[-1] == DRIFT
    assert f"pokryty kod zmienił się od {sync[:8]}: {COVERED}" in done.stdout


def test_java_i_jar_ze_zmiennych_srodowiska_zastepuja_narzedzia_aktualizacji(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load()

    def unavailable() -> str:
        raise AssertionError("kopia checkoutu mutacji nie ma katalogu podręcznego z Javą i jarem")

    tools = SimpleNamespace(_drift=lambda root, skill_md: None, _java=unavailable, _tla_tools=unavailable)
    monkeypatch.setattr(module, "_tools", lambda: tools)
    monkeypatch.setattr(module, "_moved_definitions", lambda tools, root, skill_md: None)
    (tmp_path / "oczekiwane.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(module, "MODEL", tmp_path)  # model bez konfiguracji: sprawdzenie biegnie do końca bez TLC
    monkeypatch.setenv("TLC_JAVA", "java")
    monkeypatch.setenv("TLC_JAR", str(tmp_path / "tla2tools.jar"))

    assert module.main([]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "MODEL KOLEJKI OK"


def test_kontrprzyklad_skleja_wartosc_zmiennej_z_kilku_linii_tlc() -> None:
    output = "\n".join(
        [
            "Error: Invariant JednoIssue is violated.",
            "State 1: <Initial predicate>",
            '/\\ krok = "start"',
            "/\\ issues = <<>>",
            "State 2: <Zaloz line 296, col 5 to line 322, col 63 of module KolejkaSkrzynki>",
            '/\\ krok = "open_issue: Sent"',
            '/\\ issues = << [klucz |-> "L", tresc |-> <<<<1, 1>>>>],',
            '   [klucz |-> "L", tresc |-> <<<<1, 1>>>>] >>',
            '/\\ plik = <<"czeka">>',
            "State 3: Stuttering",
        ]
    )

    trace = _load()._trace(output)

    assert trace[1]["issues"] == '<< [klucz |-> "L", tresc |-> <<<<1, 1>>>>], [klucz |-> "L", tresc |-> <<<<1, 1>>>>] >>'
    assert trace[1]["plik"] == '<<"czeka">>'
    assert trace[2]["krok"] == "(dalej nic sie nie dzieje)"


# Jedno znane znalezisko „a” obietnicy JednoIssue i odpowiedzi TLC: bez wybaczenia (przebieg znaleziska) i z nim (reszta).
FINDING = {"wynik": "narusza", "obietnica": "JednoIssue", "przyczyna": "a", "znalezisko": "opis"}
FORGIVEN = ("JednoIssuePozaZnanymi", 'WybaczoneJednoIssue = {"a"}', "WybaczoneWszystkieCzesci = {}", "WybaczoneZbieganie = {}")


@pytest.mark.parametrize(
    ("own", "rest", "last", "returncode"),
    [
        (_violation("JednoIssue", '{"a"}'), PASSED, "MODEL KOLEJKI OK, ZNANE ZNALEZISKA: 1", 0),
        (PASSED, PASSED, "MODEL KOLEJKI: ZNALEZISKO ZNIKNĘŁO (1)", 1),
        (_violation("JednoIssue", '{"a"}'), _violation("WszystkieCzesciPozaZnanymi", '{"a"}'), "MODEL KOLEJKI: NOWE NARUSZENIE (1)", 1),
        (_violation("WszystkieCzesci", '{"a"}'), PASSED, "MODEL KOLEJKI: NOWE NARUSZENIE (1)", 1),
        (_violation("JednoIssue", '{"zerwane_po_zalozeniu"}'), PASSED, "MODEL KOLEJKI: NOWE NARUSZENIE (1)", 1),
        (_violation("TypeOK", '{"a"}'), PASSED, "MODEL KOLEJKI: BŁĄD MODELU (1)", 2),
    ],
    ids=["znane", "zniknelo", "inna-obietnica-w-reszcie", "inna-obietnica", "bez-przyczyny", "typeok"],
)
def test_znane_znalezisko_wybacza_tylko_swoja_obietnice_po_swojej_przyczynie(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], own: str, rest: str, last: str, returncode: int
) -> None:
    module = _load()
    (tmp_path / "oczekiwane.json").write_text(json.dumps({"f": FINDING}), encoding="utf-8")
    (tmp_path / "f.cfg").write_text(
        "\\* Opis.\nINVARIANTS TypeOK JednoIssue WszystkieCzesci CzesciWKolejnosci\nPROPERTIES Zbieganie\nCONSTANTS\n"
        + "".join(f"    Wybaczone{promise} = {{}}\n" for promise in ("JednoIssue", "WszystkieCzesci", "CzesciWKolejnosci", "Zbieganie")),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "MODEL", tmp_path)
    monkeypatch.setattr(module, "_tools", lambda: SimpleNamespace(_drift=lambda root, skill_md: None))
    monkeypatch.setattr(module, "_moved_definitions", lambda tools, root, skill_md: None)
    monkeypatch.setenv("TLC_JAVA", "java")
    monkeypatch.setenv("TLC_JAR", str(tmp_path / "tla2tools.jar"))
    # Reszta przebiegów dostaje wybaczenie tylko w stałej obietnicy znaleziska; każda inna konfiguracja to błąd testu.
    answers: dict[bool, str] = {False: own, True: rest}

    def tlc(java: str, jar: Path, name: str, config: str) -> str:
        forgiven = all(line in config for line in FORGIVEN)
        assert forgiven or "PozaZnanymi" not in config, config
        return answers[forgiven]

    monkeypatch.setattr(module, "_tlc", tlc)

    assert module.main([]) == returncode
    assert capsys.readouterr().out.splitlines()[-1] == last


def test_konfiguracja_bez_znaleziska_z_kontrprzykladem_to_nowe_naruszenie(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load()
    (tmp_path / "oczekiwane.json").write_text(json.dumps({"f": {"wynik": "przechodzi"}}), encoding="utf-8")
    (tmp_path / "f.cfg").write_text("\\* Opis.\nINVARIANTS TypeOK JednoIssue\n", encoding="utf-8")
    monkeypatch.setattr(module, "MODEL", tmp_path)
    monkeypatch.setattr(module, "_tools", lambda: SimpleNamespace(_drift=lambda root, skill_md: None))
    monkeypatch.setattr(module, "_moved_definitions", lambda tools, root, skill_md: None)
    monkeypatch.setenv("TLC_JAVA", "java")
    monkeypatch.setenv("TLC_JAR", str(tmp_path / "tla2tools.jar"))
    monkeypatch.setattr(module, "_tlc", lambda java, jar, name, config: _violation("WszystkieCzesci", "{}"))

    assert module.main([]) == 1
    assert capsys.readouterr().out.splitlines()[-1] == "MODEL KOLEJKI: NOWE NARUSZENIE (1)"


def test_w_ci_zmieniona_definicja_procesow_centrum_konczy_sprawdzenie_rozjazdem(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load()
    moved = "kod procesów Centrum zmienił się od abcdef1: src/rozliczenia/centrum/app.py lifespan."
    monkeypatch.setattr(module, "_tools", lambda: SimpleNamespace(_drift=lambda root, skill_md: None))
    monkeypatch.setattr(module, "_moved_definitions", lambda tools, root, skill_md: moved)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    assert module.main([]) == 1
    assert capsys.readouterr().out.splitlines() == [f"UWAGA: {moved}", "", DRIFT]


def _no_change(text: str) -> str:
    return text


@pytest.mark.parametrize(
    ("path", "edit", "moved"),
    [
        (APP, lambda text: text.replace("        outbox.resume()\n", "        pass\n"), "src/rozliczenia/centrum/app.py lifespan"),
        (LAUNCHER, lambda text: text.replace("def _listen_when_released(", "def _listen_later("), "src/rozliczenia/centrum/launcher.py _listen_when_released"),
        (SERVER, lambda text: text.replace("_GRACEFUL_SHUTDOWN_S = 5", "_GRACEFUL_SHUTDOWN_S = 0"), "src/rozliczenia/centrum/server.py _GRACEFUL_SHUTDOWN_S"),
        (LAUNCHER, lambda text: text.replace("def listen_locally(port: int) -> socket.socket:\n", "def listen_locally(port: int) -> socket.socket:\n    _ = 0\n"), "src/rozliczenia/centrum/launcher.py listen_locally"),
        (SERVER, lambda text: text.replace("def serve(", "def serve_later("), "src/rozliczenia/centrum/server.py serve"),
        (SERVER, lambda text: text.replace("class _Server(uvicorn.Server):\n", "class _Server(uvicorn.Server):\n    DODANE = 1\n"), "src/rozliczenia/centrum/server.py _Server"),
        (APP, lambda text: "POZA = 1\n" + text, None),
        (APP, lambda text: text.replace("        outbox.resume()\n", "        outbox.resume()  # komentarz\n"), None),
        (SERVER, _no_change, None),
    ],
    ids=["lifespan", "listen-when-released", "graceful-shutdown", "listen-locally", "serve", "server", "poza-definicjami", "komentarz", "bez-zmian"],
)
def test_rozjazd_liczy_w_plikach_procesu_centrum_tylko_definicje_procesow_centrum(
    tmp_path: Path, path: Path, edit: Callable[[str], str], moved: str | None
) -> None:
    module = _load()
    for source in (APP, LAUNCHER, SERVER):
        copy = tmp_path / source.relative_to(ROOT)
        copy.parent.mkdir(parents=True, exist_ok=True)
        copy.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    git(tmp_path, "init", "--quiet")
    sync = commit(tmp_path, "synchronizacja")
    copy = tmp_path / path.relative_to(ROOT)
    changed = edit(copy.read_text(encoding="utf-8"))
    assert edit is _no_change or changed != copy.read_text(encoding="utf-8"), "kotwica zmiany nie pasuje do kodu"
    copy.write_text(changed, encoding="utf-8")

    found = module._moved_definitions(module._tools(), tmp_path, f"**Sync commit: `{sync[:8]}`**")

    if moved is None:
        assert found is None
    else:
        assert found == f"kod procesów Centrum zmienił się od {sync[:8]}: {moved}. Sprawdź Start, Zamknij i KoniecProcesu."


@pytest.mark.parametrize(
    ("part", "failing", "ran", "last", "returncode"),
    [
        ("", "", ["explore_outbox.py --scope watek-okresu", "explore_outbox.py --scope zgloszenie", "sprawdz_model_kolejki.py"], "KOLEJKA SKRZYNKI OK", 0),
        ("", "sprawdz_model_kolejki.py", ["explore_outbox.py --scope watek-okresu", "explore_outbox.py --scope zgloszenie", "sprawdz_model_kolejki.py"], "KOLEJKA SKRZYNKI: PADŁO sprawdz_model_kolejki.py", 1),
        ("", "explore_outbox.py --scope watek-okresu", ["explore_outbox.py --scope watek-okresu", "explore_outbox.py --scope zgloszenie", "sprawdz_model_kolejki.py"], "KOLEJKA SKRZYNKI: PADŁO explore_outbox.py --scope watek-okresu", 1),
        ("2/2", "", ["explore_outbox.py --scope zgloszenie", "sprawdz_model_kolejki.py"], "KOLEJKA SKRZYNKI OK", 0),
        ("1/2", "", ["explore_outbox.py --scope watek-okresu"], "KOLEJKA SKRZYNKI OK", 0),
        ("4/4", "", [], "KOLEJKA SKRZYNKI: PADŁO (MUTACJE_CZESC to K/N z 1 <= K <= N <= 3, nie '4/4')", 1),
    ],
    ids=["calosc", "model-pada", "zakres-pada", "czesc-2-z-2", "czesc-1-z-2", "zla-czesc"],
)
def test_podstawa_ci_uruchamia_jednostki_swojej_czesci_do_konca_i_pada_gdy_padla_ktoras(
    tmp_path: Path, part: str, failing: str, ran: list[str], last: str, returncode: int
) -> None:
    shutil.copy(BASELINE, tmp_path / BASELINE.name)
    for name in ("sprawdz_model_kolejki.py", "explore_outbox.py"):
        (tmp_path / name).write_text(
            "import os, sys\n"
            f"said = ' '.join([{name!r}, *sys.argv[1:3]])\n"
            "print(said)\n"
            f"raise SystemExit(os.environ['PADA'] == ' '.join([{name!r}, *sys.argv[1:]]) or os.environ['PADA'] == said)\n",
            encoding="utf-8",
        )

    done = subprocess.run(
        [sys.executable, str(tmp_path / BASELINE.name)],
        env={**os.environ, "PYTHONPATH": str(ROOT / "tools" / "lib"), "MUTACJE_CZESC": part, "PADA": failing},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )

    lines = done.stdout.splitlines()
    assert (done.returncode, lines[-1]) == (returncode, last), done.stdout + done.stderr
    assert [line for line in lines if line.startswith((EXPLORER.name, SCRIPT.name))] == ran


def test_czesci_podstawy_kazdej_liczby_do_ci_czesci_skladaja_sie_na_kazdy_zakres_i_model_raz(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(EXPLORER.parent))
    baseline = _load(BASELINE)
    count = mutacje_skilli.ci_parts(SKILL_MD)

    assert 1 < count <= len(baseline.UNITS)
    for parts in range(1, count + 1):
        chosen = [baseline.units({mutacje.PART: f"{number}/{parts}"}) for number in range(1, parts + 1)]
        assert sum(chosen, ()) == baseline.UNITS, parts
        assert all(chosen), parts
    scopes = [argument for name, arguments in baseline.UNITS if name == EXPLORER.name for argument in arguments if argument != "--scope"]
    listed = subprocess.run(
        [sys.executable, "-c", "import explore_outbox; print(*explore_outbox.SCOPES, sep='\\n')"],
        cwd=EXPLORER.parent,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=True,
    )
    assert sorted(scopes) == sorted(listed.stdout.splitlines())
    assert [arguments for name, arguments in baseline.UNITS if name == SCRIPT.name] == [()]
