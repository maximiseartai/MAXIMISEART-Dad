"""Publikacja plików okresu w Przygotowaniu pliku zbiorczego we wszystkich harmonogramach w zakresie.

Przerwanie procesu, błąd systemu plików, drugie Uruchomienie procesu i działanie
taty między krokami publikacji są poza zasięgiem testów przez
``prepare_collective_file()``, więc sprawdza je wyczerpująco skrypt skilla
``verify-publikacja-plikow-okresu`` na prawdziwym ``preparation_files.py``.
Zakres, znane ustalenia i postępowanie przy porażce opisuje
``.agents/skills/verify-publikacja-plikow-okresu/SKILL.md``.
"""

from __future__ import annotations

import importlib.util
import os
import stat
import sys
import threading
from pathlib import Path
from types import ModuleType

import pytest

# Harmonogramy i różne stany każdego zakresu zmierzone na c5d8bb3d, a `dwa-uruchomienia` ponownie po Nienadpisywaniu
# jednym krokiem ``os.lstat`` (``file_state.path_taken``), te same na Pythonie 3.11, 3.12 i 3.14. Drzewo
# mniejsze niż to gubi wybory kroków, a sprawdzenie dalej kończy się OK: sprzątanie po Zatrzymaniu bez wyboru kroku
# daje w ``dwa-uruchomienia`` 4718 harmonogramów i przestaje łapać wycofanie, które usuwa plik taty. Granica schodzi
# tylko ze zmianą modelu, która naprawdę zmniejsza drzewo.
SMALLEST_TREE = {"jedno-uruchomienie": (377, 231), "dwa-uruchomienia": (8278, 5818)}

EXPLORER = (
    Path(__file__).resolve().parents[1]
    / ".agents"
    / "skills"
    / "verify-publikacja-plikow-okresu"
    / "scripts"
    / "explore_publication.py"
)


def _load_explorer() -> ModuleType:
    spec = importlib.util.spec_from_file_location("explore_publication", EXPLORER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.dlugi
def test_publikacja_plikow_okresu_zachowuje_nienadpisywanie_i_razem_albo_zaden_w_kazdym_harmonogramie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    explorer = _load_explorer()
    write_period_files = explorer.preparation_files.write_period_files
    writing = 0
    interleaved = False

    def counted(*args: object, **options: object) -> object:
        nonlocal writing, interleaved
        interleaved |= writing > 0
        writing += 1
        try:
            return write_period_files(*args, **options)
        finally:
            writing -= 1

    monkeypatch.setattr(explorer.preparation_files, "write_period_files", counted)

    assert explorer.probe_interception() == []
    reports = [explorer.explore(scope) for scope in explorer.SCOPES.values()]
    outcome = explorer.summarize(reports)

    assert outcome.exit_code == 0, "\n".join(outcome.lines)
    smaller = {
        report.scope.name: (report.schedules, report.states)
        for report in reports
        if report.schedules < SMALLEST_TREE[report.scope.name][0] or report.states < SMALLEST_TREE[report.scope.name][1]
    }
    assert smaller == {}, (
        f"drzewo harmonogramów mniejsze niż {SMALLEST_TREE} na Pythonie {sys.version.split()[0]}: zgubiony wybór kroku"
        " albo świadoma zmiana modelu, która zmniejsza drzewo; wtedy obniż SMALLEST_TREE"
        " w tests/test_publikacja_plikow_okresu.py"
    )
    # Drugie Uruchomienie procesu musi wejść między kroki pierwszego, inaczej zakres dwóch Uruchomień sprawdza tylko
    # jedno po drugim i OK niczego nie mówi o wyścigu.
    assert interleaved, "w żadnym harmonogramie drugie Uruchomienie procesu nie ruszyło przed końcem pierwszego"


def test_sprawdzenie_publikacji_prowadzi_uruchomienia_bez_watkow_systemu(monkeypatch: pytest.MonkeyPatch) -> None:
    """Czas sprawdzenia nie zależy od tego, jak zajęte są procesory runnera.

    Wątek systemu na każde Uruchomienie procesu w każdym harmonogramie oddawał sterowanie przez jądro przy każdym
    kroku, a na runnerze Windows z Pythonem 3.11 zajętym innymi workerami xdist sprawdzenie dochodziło do limitu
    120 s pytest i worker ginął (`main` od 6f94edb8).
    """

    explorer = _load_explorer()
    started: list[str] = []
    start = threading.Thread.start
    checking = threading.current_thread()

    def counted(thread: threading.Thread) -> None:
        # Wątki tła zostawione przez wcześniejsze testy w tym workerze startują swoje wątki same; liczy się tylko to,
        # co uruchomiło sprawdzenie.
        if threading.current_thread() is checking:
            started.append(thread.name)
        start(thread)

    monkeypatch.setattr(threading.Thread, "start", counted)

    report = explorer.explore(explorer.SCOPES["jedno-uruchomienie"])

    assert report.undisturbed_successes
    assert started == []


class _LimitCzasu(BaseException):
    """Jak `Failed: Timeout` pytest-timeout: wyjątek spoza `Exception`, który sygnał rzuca w kodzie publikacji."""


@pytest.mark.parametrize("zatrzymanie", range(1, 21))
def test_limit_czasu_w_kodzie_publikacji_konczy_sprawdzenie_tym_limitem(
    monkeypatch: pytest.MonkeyPatch, zatrzymanie: int
) -> None:
    """Limit pytest, który przychodzi w Uruchomieniu procesu, kończy sprawdzenie, a nie jedno Uruchomienie.

    Na Linuksie i macOS pytest-timeout rzuca `Failed: Timeout` w bieżącej ramce, a ta należy często do kodu
    publikacji w greenlecie Uruchomienia. Połknięty jako Zatrzymanie albo przerwany jak harmonogram w znanym stanie,
    zmieniał drzewo harmonogramów: sprawdzenie kończyło się `IndexError`, fałszywym naruszeniem albo przechodziło,
    a pętla bez końca w kodzie publikacji nie kończyła się wcale. Limit przychodzi tu w chwili N-tego Zatrzymania
    w `ensure_period_files_absent`, bo sprzątanie po nim trafia też w stany sprawdzone wcześniej.
    """

    explorer = _load_explorer()
    ensure_absent = explorer.preparation_files.ensure_period_files_absent
    stops = 0

    def ensure_absent_until_limit(files: object) -> None:
        nonlocal stops
        try:
            ensure_absent(files)
        except Exception:
            stops += 1
            if stops == zatrzymanie:
                raise _LimitCzasu from None
            raise

    monkeypatch.setattr(explorer.preparation_files, "ensure_period_files_absent", ensure_absent_until_limit)

    with pytest.raises(_LimitCzasu):
        explorer.explore(explorer.SCOPES["dwa-uruchomienia"])


def _istnieje_przez_os_stat(path: Path) -> bool:
    try:
        path.stat()
    except OSError:
        return False
    return True


def _dowiazanie_przez_os_lstat(path: Path) -> bool:
    try:
        return stat.S_ISLNK(path.lstat().st_mode)
    except OSError:
        return False


def test_drzewo_harmonogramow_nie_zalezy_od_tego_czym_pathlib_pyta_o_plik(monkeypatch: pytest.MonkeyPatch) -> None:
    """Na każdej wersji Pythona sprawdzenie przechodzi te same harmonogramy.

    Na Pythonie 3.11 i 3.12 `Path.exists` i `Path.is_symlink` pytają `Path.stat` i `Path.lstat`, a na 3.14
    `os.path.exists` i `os.path.islink`, których odpowiedzi mówią mniej. Stan zapamiętywał odpowiedź, więc na 3.14
    łączył stany, które 3.12 rozróżnia, i przechodził 6640 harmonogramów `dwa-uruchomienia` zamiast 9798.
    """

    explorer = _load_explorer()
    trees = {}
    for version, exists, is_symlink in (
        ("3.11 i 3.12", _istnieje_przez_os_stat, _dowiazanie_przez_os_lstat),
        # Przechwytywanie podmienia os.path.exists i os.path.islink, więc szukamy ich w chwili wywołania.
        ("3.14", lambda path: os.path.exists(path), lambda path: os.path.islink(path)),
    ):
        monkeypatch.setattr(Path, "exists", lambda path, exists=exists, **_: exists(path))
        monkeypatch.setattr(Path, "is_symlink", lambda path, is_symlink=is_symlink: is_symlink(path))
        report = explorer.explore(explorer.SCOPES["jedno-uruchomienie"])
        trees[version] = (report.schedules, report.states)

    assert trees["3.11 i 3.12"] == trees["3.14"], trees


def test_rozjazd_kroku_zapisu_skoroszytu_sprawdzenie_tylko_ostrzega_takze_w_ci(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Kroki dysku Zapisywania (domyślne ``preparation_files.Disk``) sprawdzenie zastępuje własnymi, więc ich zmiana
    nie wywraca go sama: rozjazd z ``model/definicje.json`` skrypt tylko ostrzega, a w CI krok z rozjazdem zatrzymuje
    wykonanie zadania (``tools/ci/wykonaj_zadanie.py``), zanim skrypt ruszy."""

    explorer = _load_explorer()
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(explorer.rozjazd_modelu, "rozjazd", lambda skill, root: f"kod opisany modelem zmienił się: {skill.name}.")
    monkeypatch.setattr(explorer, "SCOPES", {"jedno-uruchomienie": explorer.SCOPES["jedno-uruchomienie"]})

    exited = explorer.main([])

    lines = capsys.readouterr().out.splitlines()
    assert (exited, lines[0], lines[-1]) == (0, "UWAGA: kod opisany modelem zmienił się: verify-publikacja-plikow-okresu.", "PUBLIKACJA OK, ZAAKCEPTOWANE RYZYKA: 2")


def test_przyjete_ryzyko_ktorego_nie_pokazal_zakres_z_jego_after_wywraca_werdykt() -> None:
    """Przyjęte ryzyko ADR 0005 występuje zawsze po obu zakresach (``after``): zakres, który przeszedł do końca bez niego,
    daje ``ZNALEZISKO ZNIKNĘŁO`` i kod 1, bo wpis przestał opisywać kod (docs/agents/skille.md, wpisy eksploratorów)."""

    explorer = _load_explorer()
    report = explorer.ScopeReport(explorer.SCOPES["jedno-uruchomienie"], schedules=1, undisturbed_successes=1)

    outcome = explorer.summarize([report])

    assert (outcome.exit_code, outcome.lines[-1]) == (1, "PUBLIKACJA: ZNALEZISKO ZNIKNĘŁO (1)"), "\n".join(outcome.lines)
    assert outcome.lines[-2].startswith("ZNALEZISKO ZNIKNĘŁO ADR 0005 (RAZEM_ALBO_ZADEN) po jedno-uruchomienie:")
