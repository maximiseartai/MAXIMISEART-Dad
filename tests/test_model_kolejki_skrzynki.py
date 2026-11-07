"""Model TLA+ Kolejki Skrzynki i podstawa skilla ``verify-kolejka-skrzynki``.

Podstawa skilla w CI (``sprawdz_kolejke.py``) uruchamia model i sprawdzenie prawdziwego kodu, każde do końca, i pada,
gdy padło którekolwiek; w częściach ``MUTACJE_CZESC=k/n`` każda jednostka biegnie w jednej części.

Model opisuje kod z ``model/definicje.json`` skilla w chwili jego skrótów, a w plikach procesu Centrum
(``app.py``, ``launcher.py``, ``server.py``) tylko definicje procesów Centrum. Werdykt, znane znaleziska i rozjazd w CI
sprawdza ``tests/test_model_tlc.py`` na drodze wspólnej dla modeli skilli.
"""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from tests.fixtures.model_tlc import model_tlc, rozjazd_modelu, skrypt_modelu, wyjscie_tlc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from jednostka import ZMIENNA_CZESCI  # noqa: E402
import kroki_skilli  # noqa: E402

SCRIPT = ROOT / ".agents" / "skills" / "verify-kolejka-skrzynki" / "scripts" / "sprawdz_model_kolejki.py"
BASELINE = ROOT / ".agents" / "skills" / "verify-kolejka-skrzynki" / "scripts" / "sprawdz_kolejke.py"
EXPLORER = ROOT / ".agents" / "skills" / "verify-kolejka-skrzynki" / "scripts" / "explore_outbox.py"
SKILL_MD = ROOT / ".agents" / "skills" / "verify-kolejka-skrzynki" / "SKILL.md"
DEFINITIONS = ROOT / ".agents" / "skills" / "verify-kolejka-skrzynki" / "model" / "definicje.json"
APP = ROOT / "src" / "rozliczenia" / "centrum" / "app.py"
LAUNCHER = ROOT / "src" / "rozliczenia" / "centrum" / "launcher.py"
SERVER = ROOT / "src" / "rozliczenia" / "centrum" / "server.py"
TOOL_FILES = ROOT / "src" / "rozliczenia" / "tool_files.py"
# Pliki opisane modelem w całości.
WHOLE = (
    ROOT / "src" / "rozliczenia" / "centrum" / "outbox.py",
    ROOT / "src" / "rozliczenia" / "centrum" / "keyed_box.py",
    ROOT / "src" / "rozliczenia" / "centrum" / "report_box.py",
    ROOT / "src" / "rozliczenia" / "centrum" / "atomic_file.py",
)


def test_kontrprzyklad_kolejki_opowiada_kroki_kodu_i_stan_kolejki_i_skrzynki_na_koncu(capsys: pytest.CaptureFixture[str]) -> None:
    output = wyjscie_tlc(
        "JednoIssuePozaZnanymi",
        ("Init", {"krok": '"start"', "plik": '<<"czeka">>', "issues": "<<>>", "slady": "{}"}),
        ("Zaloz", {"krok": '"open_issue: Sent"', "plik": '<<"czeka">>', "issues": '<< [klucz |-> "L"],\n   [klucz |-> "L"] >>', "slady": '{"a"}'}),
        ("Stuttering", {}),
    )

    found = model_tlc.werdykt(skrypt_modelu(SCRIPT).MODEL, output)

    assert found == model_tlc.Werdykt("JednoIssue", frozenset({"a"}))
    assert capsys.readouterr().out.splitlines() == [
        "   naruszone JednoIssue: okres, problem Zgłoszenia albo Uwaga taty ma drugie issue.",
        "   1. open_issue: Sent",
        "   2. (dalej nic się nie dzieje)",
        '   na koniec: pliki kolejki <<"czeka">>, Skrzynka << [klucz |-> "L"], [klucz |-> "L"] >>',
    ]


def _no_change(text: str) -> str:
    return text


@pytest.mark.parametrize(
    ("path", "edit", "moved"),
    [
        (APP, lambda text: text.replace("        outbox.resume()\n", "        pass\n"), "src/rozliczenia/centrum/app.py create_app.lifespan"),
        (LAUNCHER, lambda text: text.replace("def _listen_when_released(", "def _listen_later("), "src/rozliczenia/centrum/launcher.py _listen_when_released"),
        (SERVER, lambda text: text.replace("_GRACEFUL_SHUTDOWN_S = 5", "_GRACEFUL_SHUTDOWN_S = 0"), "src/rozliczenia/centrum/server.py _GRACEFUL_SHUTDOWN_S"),
        (TOOL_FILES, lambda text: text.replace("def listen_locally(port: int) -> socket.socket:\n", "def listen_locally(port: int) -> socket.socket:\n    _ = 0\n"), "src/rozliczenia/tool_files.py listen_locally"),
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
    for source in (APP, LAUNCHER, SERVER, TOOL_FILES, *WHOLE, DEFINITIONS):
        copy = tmp_path / source.relative_to(ROOT)
        copy.parent.mkdir(parents=True, exist_ok=True)
        copy.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    skill = tmp_path / DEFINITIONS.relative_to(ROOT).parents[1]
    rozjazd_modelu.przesun(skill, tmp_path)
    copy = tmp_path / path.relative_to(ROOT)
    changed = edit(copy.read_text(encoding="utf-8"))
    assert edit is _no_change or changed != copy.read_text(encoding="utf-8"), "kotwica zmiany nie pasuje do kodu"
    copy.write_text(changed, encoding="utf-8")

    found = rozjazd_modelu.rozjazd(skill, tmp_path)

    if moved is None:
        assert found is None
    else:
        assert found is not None and found.startswith(f"kod opisany modelem zmienił się: {moved}. "), found


# Jednostki sprawdzenia kodu i modelu w kolejności ``UNITS``; atrapa sprawdzenia wypisuje pierwszy zakres jednostki.
ALL = [
    "explore_outbox.py --scope archiwum",
    "explore_outbox.py --scope watek-okresu",
    "explore_outbox.py --scope diagnoza",
    "explore_outbox.py --scope zgloszenie",
    "sprawdz_model_kolejki.py",
]


@pytest.mark.parametrize(
    ("part", "failing", "ran", "last", "returncode"),
    [
        ("", "", ALL, "KOLEJKA SKRZYNKI OK", 0),
        ("", "sprawdz_model_kolejki.py", ALL, "KOLEJKA SKRZYNKI: PADŁO sprawdz_model_kolejki.py", 1),
        (
            "",
            "explore_outbox.py --scope watek-okresu",
            ALL,
            "KOLEJKA SKRZYNKI: PADŁO explore_outbox.py --scope watek-okresu --scope watek-okresu-lista",
            1,
        ),
        ("3/3", "", ALL[3:], "KOLEJKA SKRZYNKI OK", 0),
        ("1/3", "", ALL[:1], "KOLEJKA SKRZYNKI OK", 0),
        ("6/6", "", [], "KOLEJKA SKRZYNKI: PADŁO (MUTACJE_CZESC to K/N z 1 <= K <= N <= 5, nie '6/6')", 1),
    ],
    ids=["calosc", "model-pada", "zakres-pada", "czesc-3-z-3", "czesc-1-z-3", "zla-czesc"],
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
    baseline = skrypt_modelu(BASELINE)
    count = kroki_skilli.ci_parts(SKILL_MD)

    assert 1 < count <= len(baseline.UNITS)
    for parts in range(1, count + 1):
        chosen = [baseline.units({ZMIENNA_CZESCI: f"{number}/{parts}"}) for number in range(1, parts + 1)]
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


# Kod bez wątku kolejki (mutacja „send_in_background nie uruchamia wątku”): nowe naruszenie w pierwszym harmonogramie
# każdego zakresu. Biegnie we własnym interpreterze (reguła ``IN_PROCESS_EXPLORERS``).
WITHOUT_QUEUE_THREAD = """
import sys

sys.path.insert(0, sys.argv[1])
import explore_outbox

explore_outbox.outbox_module.Outbox.send_in_background = lambda self: None
raise SystemExit(explore_outbox.main(sys.argv[2:]))
"""


def _explored_without_queue_thread(*arguments: str) -> tuple[int, list[str]]:
    done = subprocess.run(
        [sys.executable, "-c", WITHOUT_QUEUE_THREAD, str(EXPLORER.parent), "--scope", "zgloszenie", "--scope", "nowe-issue", *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    lines = done.stdout.splitlines()
    assert lines, done.stderr
    return done.returncode, [line for line in lines if line.startswith("== ")] + lines[-1:]


def test_przebieg_mutacji_konczy_sie_na_pierwszym_harmonogramie_z_nowym_naruszeniem() -> None:
    """``--stop-at-new`` (#963, #967): mutacji wystarczy werdykt, więc eksplorator kończy na pierwszym harmonogramie z
    nowym naruszeniem i nie zaczyna następnego zakresu. Bez flagi ten sam zepsuty kod przechodzi każdy harmonogram
    każdego zakresu, a pełny przebieg mutacji przekroczył w CI limit 600 s ``tools/mutacje.py``."""

    full_code, full = _explored_without_queue_thread()
    stopped_code, stopped = _explored_without_queue_thread("--stop-at-new")

    assert (full_code, len(full), "Harmonogramy: 1." in full[0]) == (1, 3, False), full
    assert full[-1].startswith("KOLEJKA: NOWE NARUSZENIE"), full
    assert (stopped_code, len(stopped)) == (1, 2), stopped
    assert stopped[0].startswith("== zgloszenie: "), stopped
    assert stopped[0].endswith(" Harmonogramy: 1. Koniec na pierwszym nowym naruszeniu (--stop-at-new)."), stopped
    assert stopped[-1].startswith("KOLEJKA: NOWE NARUSZENIE"), stopped


def test_przebieg_mutacji_bez_nowego_naruszenia_przechodzi_kazdy_harmonogram_jak_bez_flagi() -> None:
    """Podstawa skryptu mutacji to to samo polecenie z ``--stop-at-new`` na kodzie bez mutacji: musi przejść każdy
    harmonogram, bo mutacja, której naruszenie leży w dalszym harmonogramie, inaczej przeszłaby niewykryta."""

    def explored(*arguments: str) -> str:
        done = subprocess.run(
            [sys.executable, str(EXPLORER), "--scope", "zgloszenie", *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )
        assert done.returncode == 0, done.stdout + done.stderr
        return done.stdout

    stopped = explored("--stop-at-new")

    assert stopped == explored()
    assert "Harmonogramy: 1." not in stopped
