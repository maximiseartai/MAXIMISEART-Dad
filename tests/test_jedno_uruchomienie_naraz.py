"""Jedno Uruchomienie procesu naraz i brak zamknięcia Centrum rozliczeń w trakcie pracy, w każdym przeplocie w zakresie.

Kolejność kroków dwóch kart, Decyzji taty, wątku Uruchomienia i zamknięcia serwera
jest poza zasięgiem testów przez API, więc sprawdza ją wyczerpująco skrypt skilla
``verify-jedno-uruchomienie-naraz`` na prawdziwych ``RunHost`` i ``Shutdown``.
Zakres, znane ustalenia i postępowanie przy porażce opisuje
``.agents/skills/verify-jedno-uruchomienie-naraz/SKILL.md``.

Każde sprawdzenie prawdziwego kodu biegnie we własnym procesie z limitem, jak w CI, także w testach, które same
zwalniają to, na co czeka wątek modelu. Wątek modelu, który czeka na prawdziwą blokadę spoza modelu, staje na zawsze
i trzyma swoje blokady do końca procesu, a kod z defektem może stanąć na swojej blokadzie w każdym harmonogramie,
zanim zadziała podróbka testu. W workerze pytest taki wątek zatrzymywał każdy następny test Centrum, który brał tę
blokadę, a sesja pytest wisiała bez linii LUKA (#651).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

EXPLORER = (
    Path(__file__).resolve().parents[1]
    / ".agents"
    / "skills"
    / "verify-jedno-uruchomienie-naraz"
    / "scripts"
    / "explore_runs.py"
)
# Poniżej limitu 120 s pytest, żeby sprawdzenie, które się nie kończy, padło z tym, co zdążyło wypisać.
OWN_PROCESS_LIMIT_S = 100

# Skrypt, który na końcu wypisuje nazwy wątków systemu uruchomionych w trakcie sprawdzenia.
COUNTED = """
import sys
import threading

sys.path.insert(0, sys.argv[1])
import explore_runs

started = []
start = threading.Thread.start


def counted(thread):
    started.append(thread.name)
    start(thread)


threading.Thread.start = counted
code = explore_runs.main(sys.argv[2:])
print("wątki systemu:", ", ".join(started))
raise SystemExit(code)
"""

# Skrypt, w którym wątek modelu czeka na zawsze na prawdziwy Event w miejscu z parametru testu.
WAITS_FOR_GOOD = """
import sys
from dataclasses import replace
from threading import Event

sys.path.insert(0, sys.argv[1])
import explore_runs

never = Event()
explore_runs.STALL_SECONDS = 1.0
{waits}
raise SystemExit(explore_runs.main(["--scope", "zamknij-w-trakcie"]))
"""

# Skrypt, w którym wątek modelu czeka na blokadę trzymaną przez skrypt dopiero od 7. wywołania RunHost.start, po sześciu
# krótkich czekaniach, które razem trwają dłużej niż limit. Po raporcie skrypt zwalnia blokadę i patrzy na porzucony
# wątek. Biegnie z pliku, żeby LUKA mogła pokazać linię, na której wątek stoi.
HELD_AFTER_SHORT_WAITS = """
import sys
import threading
import time

sys.path.insert(0, sys.argv[1])
import explore_runs

explore_runs.STALL_SECONDS = 1.0
held = threading.Lock()
held.acquire()
start = explore_runs.runs.RunHost.start
calls = []


def waiting(host, prepared):
    calls.append(prepared)
    if len(calls) <= 6:
        time.sleep(0.25)
        return start(host, prepared)
    with held:
        return start(host, prepared)


explore_runs.runs.RunHost.start = waiting
report = explore_runs.explore(explore_runs.SCOPES["zamknij-w-trakcie"])
for gap in report.gaps:
    print("LUKA:", gap)
print(explore_runs.summarize([report]).lines[-1])
print("prawdziwe threading w runs.py:", explore_runs.runs.threading is threading)
schedules = report.schedules
checker = next(thread for thread in threading.enumerate() if thread.name == "sprawdzenie przeplotów")
held.release()
checker.join(timeout=30)
print("po zwolnieniu blokady:", "żyje" if checker.is_alive() else "skończony", report.schedules - schedules)
"""

# Skrypt, w którym kod pod sprawdzeniem rzuca nieoczekiwany wyjątek w pierwszym wywołaniu RunHost.start.
BROKEN_START = """
import sys

sys.path.insert(0, sys.argv[1])
import explore_runs


def broken(host, prepared):
    raise LookupError("start zepsuty w teście")


explore_runs.runs.RunHost.start = broken
explore_runs.explore(explore_runs.SCOPES["zamknij-w-trakcie"])
print("sprawdzenie skończone bez błędu")
"""


# Skrypt, w którym część modelowana ręcznie rozjechała się z kodem; w CI sprawdzenie przeplotów nie może ruszyć, a poza
# CI biegnie bez zakresów.
DRIFTED = """
import os
import sys

sys.path.insert(0, sys.argv[1])
import explore_runs

os.environ["GITHUB_ACTIONS"] = sys.argv[2]
explore_runs.rozjazd_modelu.rozjazd = lambda skill, root: f"kod opisany modelem zmienił się: {skill.name}."


def explored(scope):
    raise AssertionError("sprawdzenie przeplotów ruszyło mimo rozjazdu w CI")


explore_runs.explore = explored
if sys.argv[2] != "true":
    explore_runs.SCOPES = {}
raise SystemExit(explore_runs.main([]))
"""

def _in_own_process(*arguments: str) -> tuple[int | None, list[str]]:
    """Kod wyjścia Pythona z ``arguments`` we własnym procesie (``None``, gdy nie skończył się w limicie) i jego linie.

    ``-u`` wypisuje każdą linię od razu, więc proces zabity po limicie oddaje wszystko, co zdążył wypisać.
    """

    try:
        done = subprocess.run(
            [sys.executable, "-X", "utf8", "-u", *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=OWN_PROCESS_LIMIT_S,
            check=False,
        )
    except subprocess.TimeoutExpired as hung:
        return None, (hung.stdout or b"").decode("utf-8", "replace").splitlines()
    return done.returncode, done.stdout.decode("utf-8", "replace").splitlines()


def test_centrum_prowadzi_jedno_uruchomienie_naraz_i_nie_zamyka_sie_w_trakcie_w_kazdym_przeplocie() -> None:
    code, lines = _in_own_process(str(EXPLORER))

    assert code == 0 and lines[-1].startswith("URUCHOMIENIA OK"), "\n".join(lines)


@pytest.mark.parametrize(
    ("ci", "code", "last"),
    [("true", 1, ["URUCHOMIENIA: ROZJAZD MODELU Z KODEM"]), ("", 0, ["", "URUCHOMIENIA OK"])],
    ids=["w-ci", "poza-ci"],
)
def test_rozjazd_czesci_modelowanej_recznie_konczy_sprawdzenie_przeplotow_porazka_w_ci_przed_sprawdzeniem(
    ci: str, code: int, last: list[str]
) -> None:
    """Części modelowanej ręcznie (``model/definicje.json``) sprawdzenie nie wykonuje, więc jej zmiana nie wywraca go sama."""

    exited, lines = _in_own_process("-c", DRIFTED, str(EXPLORER.parent), ci)

    assert (exited, lines[0], lines[-len(last) :]) == (code, "UWAGA: kod opisany modelem zmienił się: verify-jedno-uruchomienie-naraz.", last), "\n".join(lines)

def test_sprawdzenie_przeplotow_prowadzi_watki_modelu_bez_watkow_systemu() -> None:
    """Czas sprawdzenia nie zależy od tego, jak zajęte są procesory runnera (#565).

    Wątek systemu na każdy wątek modelu oddawał sterowanie przez jądro przy każdym kroku, a na runnerze CI zajętym
    innymi workerami xdist sprawdzenie dochodziło do limitu 120 s pytest.
    """

    code, lines = _in_own_process("-c", COUNTED, str(EXPLORER.parent), "--scope", "zamknij-w-trakcie")

    # Jeden wątek systemu na całe sprawdzenie: biegną na nim wątki modelu, a wywołujący patrzy z zewnątrz, czy robią kroki.
    assert (code, lines[-2:]) == (0, ["URUCHOMIENIA OK", "wątki systemu: sprawdzenie przeplotów"]), "\n".join(lines)


def test_watek_modelu_czekajacy_poza_modelem_konczy_sprawdzenie_luka_modelu_z_nazwa_i_krokiem(tmp_path: Path) -> None:
    """Prawdziwa blokada poza modelem zatrzymuje jedyny wątek systemu sprawdzenia (#651).

    Bez straży sprawdzenie wisiało do limitu 120 s pytest, z tym samym objawem co flaky test z #565. Krótkie czekania,
    razem dłuższe niż limit, nie są zawieszeniem: limit liczy się od ostatniego kroku, nie od startu sprawdzenia.
    """

    script = tmp_path / "czeka_na_blokade.py"
    script.write_text(HELD_AFTER_SHORT_WAITS, encoding="utf-8")

    code, lines = _in_own_process(str(script), str(EXPLORER.parent))

    output = "\n".join(lines)
    assert code == 0, output
    [gap] = [line.removeprefix("LUKA: ") for line in lines if line.startswith("LUKA: ")]
    assert gap.startswith("karta Uruchom 1: po kroku „żądanie POST /api/runs dociera do serwera” wątek modelu"), output
    assert "(with held:)" in gap, output
    assert lines[-3].startswith("URUCHOMIENIA: LUKA MODELU"), output
    # To, co biegnie w procesie po raporcie, używa Centrum z prawdziwym threading, a wątek, który doczekał się po
    # porzuceniu, kończy się na następnym kroku i nie zmienia już raportu.
    assert lines[-2:] == ["prawdziwe threading w runs.py: True", "po zwolnieniu blokady: skończony 0"], output


@pytest.mark.parametrize(
    ("waits", "stalled", "last"),
    [
        pytest.param(
            "explore_runs.PREPARED = replace(\n"
            "    explore_runs.PREPARED, process=replace(explore_runs.PREPARED.process, metrics_path=never.wait)\n"
            ")",
            "wątek modelu przez 1 s nie doszedł do pierwszego kroku",
            "karta Uruchom 1: odpowiedź 200: running",
            id="przed_pierwszym_krokiem",
        ),
        pytest.param(
            "explore_runs.runs.RunHost.remember = lambda *_: never.wait()",
            "po kroku „silnik kończy i dopisuje rekord metryk” wątek modelu przez 1 s nie doszedł do kolejnego",
            "wątek Uruchomienie 1: silnik kończy i dopisuje rekord metryk [",
            id="po_dwoch_krokach",
        ),
    ],
)
def test_watek_modelu_czekajacy_na_zawsze_konczy_proces_sprawdzenia_luka_z_miejscem_czekania_i_harmonogramem(
    waits: str, stalled: str, last: str
) -> None:
    """Porzucony wątek sprawdzenia czeka do końca procesu, więc proces kończy się po LUCE sam, z LUKĄ w wyjściu (#651).

    Wątek modelu czeka w bibliotece (``Event.wait``), więc LUKA podaje też linię sprawdzanego pliku, z której tam
    doszedł, a harmonogram pod nią kończy się na tym, co zdarzyło się przed czekaniem.
    """

    code, lines = _in_own_process("-c", WAITS_FOR_GOOD.format(waits=waits), str(EXPLORER.parent))

    output = "\n".join(lines)
    assert code == 2 and lines[-1].startswith("URUCHOMIENIA: LUKA MODELU (1)"), output
    [gap] = [line for line in lines if line.startswith("  LUKA MODELU: ")]
    assert re.fullmatch(
        rf"  LUKA MODELU: wątek Uruchomienie 1: {re.escape(stalled)} i stoi w threading\.py:\d+ .+, "
        r"dokąd doszedł z runs\.py:\d+ work, czyli czeka na coś spoza modelu .+",
        gap,
    ), gap
    schedule = lines[lines.index(gap) + 1 : lines.index("", lines.index(gap))]
    assert schedule and schedule[-1].split(". ", 1)[1].startswith(last), output


def test_nieoczekiwany_blad_kodu_pod_sprawdzeniem_przerywa_sprawdzenie() -> None:
    code, lines = _in_own_process("-c", BROKEN_START, str(EXPLORER.parent))

    assert (code, lines[-1]) == (1, "LookupError: start zepsuty w teście"), "\n".join(lines)
