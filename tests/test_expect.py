from __future__ import annotations

from itertools import pairwise
import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest

from tests.fixtures.expect import assert_expected, save_command

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _bez_zapisu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ZAPISZ_EXPECT", raising=False)
    monkeypatch.delenv("CI", raising=False)


def test_inny_tekst_pada_z_diffem_i_nie_zmienia_pliku(tmp_path: Path) -> None:
    expected = tmp_path / "wynik.txt"
    expected.write_bytes("Gdzie: plik A\nCo zrobić: zamknij\n".encode())

    with pytest.raises(pytest.fail.Exception) as failure:
        assert_expected("Gdzie: plik B\nCo zrobić: zamknij\n", expected)

    assert "-Gdzie: plik A\n+Gdzie: plik B\n Co zrobić: zamknij\n" in str(failure.value)
    assert expected.read_bytes() == "Gdzie: plik A\nCo zrobić: zamknij\n".encode()


def test_polecenie_zapisu_z_porazki_zapisuje_plik_w_powloce_systemu_a_test_potem_przechodzi(tmp_path: Path) -> None:
    (tmp_path / "test_probka.py").write_text(
        "from pathlib import Path\n\nimport pytest\n\nfrom tests.fixtures.expect import assert_expected\n\n\n"
        "@pytest.mark.parametrize('wariant', [\"a b's\"])\n"
        "def test_probka(wariant: str) -> None:\n"
        "    assert_expected('Co zrobić: zamknij\\n', Path(__file__).parent / 'wynik.txt')\n",
        encoding="utf-8",
    )
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONUTF8": "1"}

    def run(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )

    failed = run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_probka.py"])
    command = next(
        line.strip() for before, line in pairwise(failed.stdout.splitlines()) if before.startswith("Jeśli zmiana jest zamierzona")
    )
    # Powłoka systemu wykonuje wydrukowane polecenie; tylko interpreter .venv katalogu repo zastępuje ten, który biegnie test.
    if sys.platform == "win32":
        shell = ["powershell", "-NoProfile", "-NonInteractive", "-Command"]
        ours = command.replace(".venv\\Scripts\\python.exe", "& '" + sys.executable.replace("'", "''") + "'", 1)
        left = "; Write-Output ('zmienna po poleceniu: [' + $env:ZAPISZ_EXPECT + ']')"
    else:
        shell = ["/bin/sh", "-c"]
        ours = command.replace(".venv/bin/python", shlex.quote(sys.executable), 1)
        left = '; echo "zmienna po poleceniu: [$ZAPISZ_EXPECT]"'
    saved = run([*shell, ours + left])

    printed = save_command("test_probka.py::test_probka[a b's]", windows=sys.platform == "win32")
    assert (failed.returncode, command) == (1, printed)
    assert (tmp_path / "wynik.txt").read_bytes() == "Co zrobić: zamknij\n".encode(), saved.stdout + saved.stderr
    assert "zmienna po poleceniu: []" in saved.stdout
    assert run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_probka.py"]).returncode == 0


def test_brak_pliku_pada_z_calym_tekstem_jako_dodanym(tmp_path: Path) -> None:
    with pytest.raises(pytest.fail.Exception, match=r"\+Co się stało: coś"):
        assert_expected("Co się stało: coś\n", tmp_path / "wynik.txt")


def test_zapis_tworzy_plik_w_utf8_z_koncami_linii_lf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZAPISZ_EXPECT", "1")
    expected = tmp_path / "expected" / "wynik.txt"

    assert_expected("Co się stało: coś\nGdzie: tu\n", expected)

    assert expected.read_bytes() == "Co się stało: coś\nGdzie: tu\n".encode()


def test_w_ci_zapis_pada_i_nie_zmienia_pliku(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZAPISZ_EXPECT", "1")
    monkeypatch.setenv("CI", "true")
    expected = tmp_path / "wynik.txt"
    expected.write_bytes(b"stary\n")

    with pytest.raises(pytest.fail.Exception, match="w CI"):
        assert_expected("nowy\n", expected)

    assert expected.read_bytes() == b"stary\n"


def test_plik_z_koncami_linii_crlf_z_checkoutu_na_windows_porownuje_sie_jak_lf(tmp_path: Path) -> None:
    expected = tmp_path / "wynik.txt"
    expected.write_bytes(b"Gdzie: tu\r\nCo zrobi\xc4\x87: nic\r\n")

    assert_expected("Gdzie: tu\nCo zrobić: nic\n", expected)
    with pytest.raises(pytest.fail.Exception, match=r"-Co zrobić: nic\n\+Co zrobić: coś\n"):
        assert_expected("Gdzie: tu\nCo zrobić: coś\n", expected)
