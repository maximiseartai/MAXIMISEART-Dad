"""Sprawdzenie modelu TLA+ Dziennika Wyceny w efenix i Logów Urwanego Uruchomienia: rozjazd z kodem w CI i werdykty.

Model opisuje definicje z ``model/definicje.json`` skilla ``verify-urwane-uruchomienie`` w commicie synchronizacji z jego
``SKILL.md``: funkcje, klasy, przypisania i metody (``Klasa.metoda``). Zmiana innej części tych plików (``run_logs.py``,
``app.py`` i ``runs.py`` zmieniają się często) rozjazdem nie jest. Testy rozjazdu biegną na repozytorium z plikami
zbudowanymi z tej tabeli, nie na kodzie ``src/``: sprawdzają skrypt, a kod opisany modelem sprawdza krok ``ci:`` skilla.

Znane znalezisko z ``model/oczekiwane.json`` wybacza tylko w swojej konfiguracji, tylko swoją obietnicę i tylko
zdarzenie z jego przyczyną: kontrprzykład innej obietnicy, bez tej przyczyny albo w konfiguracji, która go nie oczekuje,
to nowe naruszenie, a Zbieganie (żywotność) nie ma znanych znalezisk.
"""

from __future__ import annotations

from collections import defaultdict
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import ModuleType

import pytest

from tests.fixtures.git_repo import commit, git

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "verify-urwane-uruchomienie" / "scripts" / "sprawdz_urwane_uruchomienie.py"
DEFINITIONS = ROOT / ".agents" / "skills" / "verify-urwane-uruchomienie" / "model" / "definicje.json"
TOOLS = ROOT / ".agents" / "skills" / "verify-aktualizacja-narzedzia" / "scripts" / "sprawdz_aktualizacje.py"
DRIFT = "URWANE URUCHOMIENIE: ROZJAZD MODELU Z KODEM"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(SCRIPT.stem, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _definitions() -> dict[str, list[str]]:
    loaded: dict[str, list[str]] = json.loads(DEFINITIONS.read_text(encoding="utf-8"))
    return loaded


def _source(names: list[str]) -> str:
    """Plik z każdą definicją z ``names`` (metoda ``Klasa.metoda`` w swojej klasie), każda z własnym wynikiem, i z
    funkcją oraz metodą każdej klasy, których tabela nie wymienia."""

    classes: dict[str, list[str]] = defaultdict(list)
    lines = []
    for name in names:
        if "." in name:
            owner, member = name.split(".", 1)
            classes[owner].append(member)
        else:
            lines += [f"def {name}() -> str:", f'    return "{name}"', ""]
    for owner, members in classes.items():
        lines.append(f"class {owner}:")
        for member in [*members, "obok"]:
            lines += [f"    def {member}(self) -> str:", f'        return "{owner}.{member}"', ""]
    return "\n".join([*lines, "def obok() -> str:", '    return "obok"', ""])


def _file_of(name: str) -> str:
    """Plik definicji ``name`` z tabeli; ``Klasa.obok`` leży w pliku klasy, a ``obok`` w pliku ``RunLogs``."""

    owner = name.split(".")[0] + "." if name.endswith(".obok") else None
    wanted = "RunLogs.send" if name == "obok" else name
    [path] = [
        path
        for path, names in _definitions().items()
        if wanted in names or (owner is not None and any(listed.startswith(owner) for listed in names))
    ]
    return path


def _repository(root: Path) -> str:
    """Repozytorium ze skryptami skilli, tabelą definicji i plikami, które ją spełniają; zwraca commit synchronizacji."""

    for script in (SCRIPT, DEFINITIONS, TOOLS):
        copy = root / script.relative_to(ROOT)
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(script, copy)
    for path, names in _definitions().items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(_source(names), encoding="utf-8")
    git(root, "init", "--quiet")
    return commit(root, "synchronizacja")


def _change(root: Path, name: str) -> None:
    """Nowy wynik definicji ``name`` (albo funkcji ``obok`` jej pliku), czyli zmiana jej treści."""

    path = root / _file_of(name)
    text = path.read_text(encoding="utf-8")
    anchor = f'return "{name}"'
    assert text.count(anchor) == 1, anchor
    path.write_text(text.replace(anchor, f'return "{name} po zmianie"'), encoding="utf-8")


def _check_in_ci(root: Path, sync: str) -> subprocess.CompletedProcess[str]:
    skill = root / SCRIPT.relative_to(ROOT).parents[1]
    (skill / "SKILL.md").write_text(f"Sync commit: `{sync}` (main).\n", encoding="utf-8")
    (skill / "model" / "oczekiwane.json").write_text("{}", encoding="utf-8")  # bez konfiguracji: bez rozjazdu bez TLC
    return subprocess.run(
        [sys.executable, str(skill / "scripts" / SCRIPT.name)],
        cwd=root,
        env={**os.environ, "GITHUB_ACTIONS": "true", "TLC_JAVA": "java", "TLC_JAR": "tla2tools.jar"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("InterruptedPricings", id="zamykanie-i-wysylka-dziennikow"),
        pytest.param("RunCards._row", id="wiersz-historii"),
        pytest.param("send_interrupted", id="wysylka-przy-zapytaniu"),
        pytest.param("lifespan", id="start-kolejki"),
        pytest.param("run_process", id="zapis-wiersza-historii"),
    ],
)
def test_w_ci_zmieniona_definicja_opisana_modelem_konczy_sprawdzenie_porazka(tmp_path: Path, name: str) -> None:
    sync = _repository(tmp_path)
    _change(tmp_path, name)
    commit(tmp_path, "zmiana kodu opisanego modelem")

    done = _check_in_ci(tmp_path, sync[:9])

    assert done.returncode == 1, done.stdout + done.stderr
    assert done.stdout.splitlines()[-1] == DRIFT
    assert f"kod opisany modelem zmienił się od {sync[:9]}: {_file_of(name)} {name}." in done.stdout


def test_w_ci_metoda_rozjazdu_to_metoda_swojej_klasy_a_nie_metoda_o_tej_nazwie_w_innej_klasie(tmp_path: Path) -> None:
    """``RunLog.interrupted`` (Logi z dziennika) i ``RunLogs.interrupted`` (te Logi z narzędziem i środowiskiem) to dwie
    definicje: zmiana pierwszej jest rozjazdem tylko pierwszej."""

    sync = _repository(tmp_path)
    _change(tmp_path, "RunLog.interrupted")
    commit(tmp_path, "Logi Urwanego Uruchomienia inaczej")

    done = _check_in_ci(tmp_path, sync[:9])

    assert done.stdout.splitlines()[-1] == DRIFT, done.stdout + done.stderr
    assert f"zmienił się od {sync[:9]}: {_file_of('RunLog.interrupted')} RunLog.interrupted." in done.stdout


@pytest.mark.parametrize("name", ["obok", "RunLogs.obok"])
def test_w_ci_zmiana_obok_definicji_opisanych_modelem_nie_jest_rozjazdem(tmp_path: Path, name: str) -> None:
    sync = _repository(tmp_path)
    _change(tmp_path, name)
    commit(tmp_path, "zmiana obok")

    done = _check_in_ci(tmp_path, sync[:9])

    assert (done.returncode, done.stdout.splitlines()[-1]) == (0, "URWANE URUCHOMIENIE OK"), done.stdout + done.stderr


def test_w_ci_definicja_ktorej_nie_ma_jest_rozjazdem(tmp_path: Path) -> None:
    sync = _repository(tmp_path)
    path = tmp_path / _file_of("RunCards.recorded")
    path.write_text(path.read_text(encoding="utf-8").replace("def recorded(", "def recorded_inaczej("), encoding="utf-8")
    commit(tmp_path, "inna nazwa")

    done = _check_in_ci(tmp_path, sync[:9])

    assert done.stdout.splitlines()[-1] == DRIFT, done.stdout + done.stderr
    assert f"{_file_of('RunCards.recorded')} RunCards.recorded." in done.stdout


def test_definicja_to_przypisanie_w_funkcji_albo_metoda_swojej_klasy() -> None:
    """``app`` i ``interrupted`` w ``create_app`` to przypisania w funkcji, a ``RunLog.interrupted`` i
    ``RunLogs.interrupted`` to metody o tej samej nazwie w dwóch klasach."""

    module = _load()
    source = "\n".join(
        [
            "def create_app():",
            "    interrupted = Pricings(1)",
            "    app = FastAPI(dependencies=[interrupted])",
            "    return app",
            "class RunLog:",
            "    def interrupted(self): return 1",
            "class RunLogs:",
            "    def interrupted(self): return 2",
            "",
        ]
    )
    changed = source.replace("Pricings(1)", "Pricings(2)")

    found = {name: module._definition(source, name) for name in ("interrupted", "app", "RunLog.interrupted", "RunLogs.interrupted")}

    assert None not in found.values(), found
    assert found["RunLog.interrupted"] != found["RunLogs.interrupted"]
    assert (module._definition(changed, "interrupted") != found["interrupted"], module._definition(changed, "app") == found["app"]) == (True, True)
    assert (module._definition(source, "RunLogs.obok"), module._definition(source, "Brak.interrupted")) == (None, None)


def test_w_ci_brak_commitu_synchronizacji_konczy_sprawdzenie_porazka(tmp_path: Path) -> None:
    _repository(tmp_path)

    done = _check_in_ci(tmp_path, "0" * 40)

    assert done.returncode == 1, done.stdout + done.stderr
    assert done.stdout.splitlines()[-1] == DRIFT
    assert f"commitu synchronizacji {'0' * 40} nie ma w tej historii" in done.stdout


def _verdicts(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    known: dict[str, list[dict[str, str]]],
    answers: list[object],
) -> list[frozenset[tuple[str, str]]]:
    """Konfiguracje ``known`` (nazwa → jej znane znaleziska); kolejne przebiegi TLC dają ``answers``. Zwraca wybaczone
    znaleziska każdego przebiegu."""

    for name in known:
        (tmp_path / f"{name}.cfg").write_text("\\* konfiguracja testu\n", encoding="utf-8")
    (tmp_path / "oczekiwane.json").write_text(
        json.dumps({name: {"znane": findings} for name, findings in known.items()}), encoding="utf-8"
    )
    monkeypatch.setattr(module, "MODEL", tmp_path)
    monkeypatch.setattr(module, "_drift", lambda tools, root, skill_md: None)
    monkeypatch.setenv("TLC_JAVA", "java")
    monkeypatch.setenv("TLC_JAR", "tla2tools.jar")
    forgiven: list[frozenset[tuple[str, str]]] = []
    pending = iter(answers)

    def run(java: str, jar: Path, name: str, forgiven_now: frozenset[tuple[str, str]]) -> object:
        forgiven.append(forgiven_now)
        return next(pending)

    monkeypatch.setattr(module, "_run", run)
    return forgiven


_KNOWN = [{"obietnica": "DziennikPoKolejce", "przyczyna": "wiersz-pozniejszej-wyceny", "znalezisko": "test"}]


@pytest.mark.parametrize(
    ("own", "rest", "code", "last"),
    [
        pytest.param(("DziennikPoKolejce", {"wiersz-pozniejszej-wyceny"}), None, 0, "URWANE URUCHOMIENIE OK, ZNANE ZNALEZISKA: 1", id="znane"),
        pytest.param(("DziennikPoKolejce", set()), None, 1, "URWANE URUCHOMIENIE: NOWE NARUSZENIE (1)", id="bez-przyczyny"),
        pytest.param(("TeSameZnaki", {"wiersz-pozniejszej-wyceny"}), None, 1, "URWANE URUCHOMIENIE: NOWE NARUSZENIE (1)", id="inna-obietnica"),
        pytest.param(None, None, 1, "URWANE URUCHOMIENIE: ZNALEZISKO ZNIKNĘŁO (1)", id="zniknelo"),
        pytest.param(
            ("DziennikPoKolejce", {"wiersz-pozniejszej-wyceny"}),
            ("Zbieganie", set()),
            1,
            "URWANE URUCHOMIENIE: NOWE NARUSZENIE (1)",
            id="reszta-nie-zbiega",
        ),
    ],
)
def test_znane_znalezisko_wybacza_tylko_swoja_obietnice_po_swojej_przyczynie(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    own: tuple[str, set[str]] | None,
    rest: tuple[str, set[str]] | None,
    code: int,
    last: str,
) -> None:
    module = _load()

    def verdict(found: tuple[str, set[str]] | None) -> object:
        return module.Verdict(None) if found is None else module.Verdict(found[0], frozenset(found[1]))

    forgiven = _verdicts(module, monkeypatch, tmp_path, {"k": _KNOWN}, [verdict(own), verdict(rest)])

    assert module.main([]) == code
    assert capsys.readouterr().out.splitlines()[-1] == last
    assert forgiven == [frozenset(), frozenset({("DziennikPoKolejce", "wiersz-pozniejszej-wyceny")})]


def test_konfiguracja_wybacza_tylko_znane_znaleziska_ktore_oczekiwane_podaja_dla_niej(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Przyczyna znaleziska innej konfiguracji nie jest wybaczona: nowa droga do niej w konfiguracji, która jej nie
    oczekuje, to nowe naruszenie. Każde znalezisko ma swój przebieg bez pozostałych znanych swojej konfiguracji."""

    module = _load()
    later = ("DziennikPoKolejce", "wiersz-pozniejszej-wyceny")
    unread = ("BezUrwanychPoWyniku", "historia-nieczytelna")
    unwritten = ("BezUrwanychPoWyniku", "historia-niezapisana")

    def finding(found: tuple[str, str]) -> dict[str, str]:
        return {"obietnica": found[0], "przyczyna": found[1], "znalezisko": "test"}

    answers = [
        module.Verdict(unread[0], frozenset({unread[1]})),
        module.Verdict(unwritten[0], frozenset({unwritten[1]})),
        module.Verdict(None),
        module.Verdict(later[0], frozenset({later[1]})),
        module.Verdict(None),
    ]
    known = {"historia": [finding(unread), finding(unwritten)], "odczyt": [finding(later)]}
    forgiven = _verdicts(module, monkeypatch, tmp_path, known, answers)

    assert module.main([]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "URWANE URUCHOMIENIE OK, ZNANE ZNALEZISKA: 3"
    assert forgiven == [
        frozenset({unwritten}),
        frozenset({unread}),
        frozenset({unread, unwritten}),
        frozenset(),
        frozenset({later}),
    ]


def _tlc_output(monkeypatch: pytest.MonkeyPatch, module: ModuleType, tmp_path: Path, output: str) -> None:
    monkeypatch.setattr(module, "_tools", lambda: type("T", (), {"_tlc": staticmethod(lambda *arguments: output)}))
    (tmp_path / "k.cfg").write_text("\\* konfiguracja testu\n", encoding="utf-8")
    monkeypatch.setattr(module, "MODEL", tmp_path)


def test_kontrprzyklad_daje_obietnice_i_przyczyny_jej_zdarzen_a_odczyt_ktory_sie_nie_udal_nazywa_po_imieniu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load()
    output = "\n".join(
        [
            "Error: Invariant DziennikPoKolejcePozaZnanymi is violated.",
            "State 1: <Initial predicate>",
            '/\\ dziennik = <<"jest", "brak">>',
            "/\\ kursor = 1",
            "/\\ awarieOdczytu = 0",
            "/\\ zgubiony = {}",
            "State 2: <Czytaj line 193, col 5 to line 231, col 50 of module UrwaneUruchomienie>",
            '/\\ dziennik = <<"jest", "brak">>',
            "/\\ kursor = 2",
            "/\\ awarieOdczytu = 1",
            '/\\ zgubiony = {{"wiersz-pozniejszej-wyceny",',
            '   "historia-nieczytelna"}}',
        ]
    )
    _tlc_output(monkeypatch, module, tmp_path, output)

    found = module._run("java", Path("tla2tools.jar"), "k", frozenset())

    assert found == module.Verdict("DziennikPoKolejce", frozenset({"wiersz-pozniejszej-wyceny", "historia-nieczytelna"}))
    assert "1. close: odczyt dziennika Wyceny 1 rzuca OSError, dziennik zostaje następnemu startowi" in capsys.readouterr().out


def test_przebieg_bez_konca_to_naruszone_zbieganie_bez_znanych_znalezisk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load()
    output = "\n".join(
        [
            "Error: Temporal properties were violated.",
            "State 1: <Initial predicate>",
            '/\\ dziennik = <<"jest">>',
            "State 2: <Start line 172, col 5 to line 178, col 53 of module UrwaneUruchomienie>",
            '/\\ dziennik = <<"jest">>',
            "Back to state 1: <Zamkniecie line 408, col 5 to line 412, col 70 of module UrwaneUruchomienie>",
        ]
    )
    _tlc_output(monkeypatch, module, tmp_path, output)

    found = module._run("java", Path("tla2tools.jar"), "k", frozenset())

    told = capsys.readouterr().out
    assert found == module.Verdict("Zbieganie")
    assert ("naruszone Zbieganie" in told, "(stąd znów krok 0 i tak bez końca)" in told) == (True, True)
