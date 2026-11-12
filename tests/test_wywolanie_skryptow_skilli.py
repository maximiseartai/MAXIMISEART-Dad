"""Skrypty skilli ``verify-*`` mają jeden kontrakt wywołania: katalog runu, warianty i dowolny bieżący katalog.

Kontrakt trzyma ``tools/lib/skrypt_skilla.py``. Test struktury pada, gdy skrypt skilla parsuje te argumenty po swojemu.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

import skrypt_skilla

REPO = Path(__file__).resolve().parents[1]
SKILLS = REPO / ".agents" / "skills"
CLEANUPS = (
    SKILLS / "verify-rozliczenia" / "scripts" / "cleanup.py",
    SKILLS / "verify-centrum-rozliczen" / "scripts" / "centrum_cleanup.py",
)
CONTRACT_NAMES = {"root", "run_dir", "variant", "wariant", "katalog_runu"}
CWD_CALLS = {"chdir", "getcwd", "cwd"}

OUTSIDE_CONTRACT = {
    ("verify-centrum-rozliczen/scripts/create_centrum_fixture.py", "add_argument(--wariant)"): (
        "dane fixture, które runner wybiera dla funkcji wydajnosc; jedna wartość, nie lista wariantów weryfikacji"
    ),
}


def _script(script: Path, *arguments: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *arguments],
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _contract_argument(call: ast.Call) -> str | None:
    options = [str(argument.value) for argument in call.args if isinstance(argument, ast.Constant)]
    dests = [str(keyword.value.value) for keyword in call.keywords if keyword.arg == "dest" and isinstance(keyword.value, ast.Constant)]
    names = {option.lstrip("-").replace("-", "_") for option in options} | set(dests)
    if not names & CONTRACT_NAMES:
        return None
    return f"add_argument({', '.join([*options, *(f'dest={dest}' for dest in dests)])})"


def _own_contract(path: Path) -> list[tuple[int, str]]:
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument":
            if argument := _contract_argument(node):
                found.append((node.lineno, argument))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value == ".verification" or node.value.startswith((".verification/", ".verification\\")):
                found.append((node.lineno, repr(node.value)))
        elif isinstance(node, ast.Attribute) and node.attr in CWD_CALLS:
            found.append((node.lineno, f".{node.attr}"))
        elif isinstance(node, ast.alias) and node.name == "VERIFICATION":
            found.append((node.lineno, "VERIFICATION poza add_run_dir"))
    return found


def test_skrypty_skilli_biora_katalog_runu_warianty_i_sciezki_tylko_z_parsera() -> None:
    found = {
        (path.relative_to(SKILLS).as_posix(), what): line
        for path in sorted(SKILLS.glob("*/scripts/**/*.py"))
        for line, what in _own_contract(path)
    }
    assert sorted(f"{path}:{line}: {what}" for (path, what), line in found.items() if (path, what) not in OUTSIDE_CONTRACT) == [], (
        "--root, --run-dir i --variant dodają metody skrypt_skilla.Parser, katalog przebiegu przychodzi z add_run_dir, "
        "a skrypt nie zależy od bieżącego katalogu"
    )
    assert sorted(set(OUTSIDE_CONTRACT) - set(found)) == [], "wyjątek bez znaleziska: usuń go"


@pytest.mark.parametrize("cleanup", CLEANUPS, ids=lambda path: path.name)
def test_sprzatanie_nie_usuwa_katalogu_ktorego_nie_utworzyla_fixture(tmp_path: Path, cleanup: Path) -> None:
    foreign = tmp_path / "dane-kogos"
    foreign.mkdir()
    (foreign / "wazne.txt").write_text("zostaje\n", encoding="utf-8")

    done = _script(cleanup, "--root", str(foreign), cwd=tmp_path)

    assert done.returncode == 1, done.stdout + done.stderr
    assert (foreign / "wazne.txt").read_text(encoding="utf-8") == "zostaje\n"


class _NtfsOrder:
    """NTFS listuje katalog w kolejności nazw, więc ``.katalog-runu`` przed resztą."""

    def __init__(self, entries: Iterator[os.DirEntry[str]]) -> None:
        self._entries = sorted(entries, key=lambda entry: entry.name)
        close = getattr(entries, "close", None)
        if close is not None:
            close()

    def __enter__(self) -> _NtfsOrder:
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def __iter__(self) -> Iterator[os.DirEntry[str]]:
        return iter(self._entries)

    def close(self) -> None:
        pass


def test_przerwane_sprzatanie_zostawia_znacznik_a_ponowne_konczy_prace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = skrypt_skilla.create_run_root(tmp_path / "run")
    (root / "dane").mkdir()
    (root / "dane" / "zablokowany.txt").write_text("otwarty w innym procesie\n", encoding="utf-8")
    (root / "wynik.json").write_text("{}\n", encoding="utf-8")
    scandir, unlink = os.scandir, os.unlink

    def locked(path: Any, *arguments: Any, **options: Any) -> None:
        if os.fsdecode(path).endswith("zablokowany.txt"):
            raise PermissionError(13, "plik otwarty w innym procesie", os.fsdecode(path))
        unlink(path, *arguments, **options)

    monkeypatch.setattr(os, "scandir", lambda *arguments: _NtfsOrder(scandir(*arguments)))
    monkeypatch.setattr(os, "unlink", locked)
    with pytest.raises(OSError, match=r"run[/\\]+dane"):
        skrypt_skilla.remove_run_root(root)
    monkeypatch.undo()

    assert (root / skrypt_skilla.MARKER).is_file()
    done = _script(CLEANUPS[0], "--root", str(root), cwd=tmp_path)
    assert done.returncode == 0, done.stdout + done.stderr
    assert not root.exists()


def test_sprzatanie_usuwa_pusty_katalog_po_usunietym_znaczniku(tmp_path: Path) -> None:
    left = tmp_path / "run"
    left.mkdir()

    done = _script(CLEANUPS[0], "--root", str(left), cwd=tmp_path)

    assert done.returncode == 0, done.stdout + done.stderr
    assert not left.exists()


def test_self_test_pisze_probe_sprzatania_do_podanego_katalogu_przebiegu(tmp_path: Path) -> None:
    evidence = tmp_path / "dowody"
    evidence.mkdir()
    (evidence / "wynik.txt").write_text("VERIFY OK\n", encoding="utf-8")
    run_dir = tmp_path / "przebieg"

    done = _script(
        SKILLS / "verify-rozliczenia" / "scripts" / "self_test.py",
        *("--evidence-root", str(evidence), "--run-dir", str(run_dir)),
        cwd=tmp_path,
    )

    assert done.returncode == 0, done.stdout + done.stderr
    assert sorted(path.name for path in run_dir.iterdir()) == ["evidence", "runs"]


ROW_VALUE_EVIDENCE = {
    "przebieg.txt": "SYNTHETIC-3",
    "przygotowanie.txt": "PREP-SYN-ADRES-4",
    "intermax-numer-zl.txt": "ZL-78201",
    "intermax-numer-umowy.txt": "UM-78205",
    "intermax-adres.txt": "Ulica 78203",
}


# Jeden plik osobno: kod wyjścia przy dokładnie jednym błędzie, którego przebieg z pięcioma błędami nie widzi (#1435 r1).
@pytest.mark.parametrize("names", [tuple(ROW_VALUE_EVIDENCE), ("przebieg.txt",)], ids=["kazdy-fixture", "jeden-plik"])
def test_self_test_odrzuca_dowod_z_wartoscia_wiersza_kazdego_fixture_skilla(tmp_path: Path, names: tuple[str, ...]) -> None:
    evidence = tmp_path / "dowody"
    evidence.mkdir()
    for name in names:
        (evidence / name).write_text(f"VERIFY OK | wiersz={ROW_VALUE_EVIDENCE[name]}\n", encoding="utf-8")

    done = _script(
        SKILLS / "verify-rozliczenia" / "scripts" / "self_test.py",
        *("--evidence-root", str(evidence), "--run-dir", str(tmp_path / "przebieg")),
        cwd=tmp_path,
    )

    # One run for all files proves each value only if every file is named on its own line.
    found = "SELF-TEST FAIL: source row content found in evidence: "
    flagged = {line.removeprefix(found) for line in done.stderr.splitlines() if line.startswith(found)}
    assert done.returncode == 1, done.stdout + done.stderr
    assert flagged == set(names), done.stderr


@pytest.mark.parametrize(
    ("variants", "summary"),
    [
        (
            ("preparation-real-templates", "chain-real-templates"),
            "VERIFY SKIP | ok=- | skipped=preparation-real-templates, chain-real-templates",
        ),
        (("default", "chain-real-templates"), "VERIFY SKIP | ok=default | skipped=chain-real-templates"),
    ],
    ids=["same-pominiete", "przeszly-i-pominiety"],
)
def test_lista_z_pominietym_wariantem_nie_konczy_sie_verify_ok(
    tmp_path: Path, variants: tuple[str, ...], summary: str
) -> None:
    done = _verification_without_templates(tmp_path, variants)

    assert done.returncode == 3, done.stdout + done.stderr
    assert done.stdout.splitlines()[-1] == summary


def test_lista_z_jednym_pominietym_wariantem_konczy_sie_kodem_pominiecia(tmp_path: Path) -> None:
    done = _verification_without_templates(tmp_path, ("chain-real-templates",))

    assert done.returncode == 3, done.stdout + done.stderr
    templates = (tmp_path / "bez-wzorcow").resolve()
    summary = f"VERIFY SKIP | variant=chain-real-templates | templates_dir={templates} | missing="
    assert done.stdout.splitlines()[-1].startswith(summary), done.stdout


def _verification_without_templates(tmp_path: Path, variants: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    empty_templates = tmp_path / "bez-wzorcow"
    empty_templates.mkdir()
    return _script(
        SKILLS / "verify-rozliczenia" / "scripts" / "run_verification.py",
        *("--variant", *variants),
        *("--templates-dir", str(empty_templates), "--run-dir", str(tmp_path / "przebieg")),
        cwd=tmp_path,
    )


def test_fixture_nie_pisze_do_niepustego_katalogu(tmp_path: Path) -> None:
    occupied = tmp_path / "zajety"
    occupied.mkdir()
    (occupied / "wazne.txt").write_text("zostaje\n", encoding="utf-8")

    done = _script(SKILLS / "verify-rozliczenia" / "scripts" / "create_fixture.py", "--root", str(occupied), cwd=tmp_path)

    assert done.returncode == 1, done.stdout + done.stderr
    assert sorted(path.name for path in occupied.iterdir()) == ["wazne.txt"]


def test_katalog_runu_poza_repozytorium_wzgledny_wobec_biezacego_katalogu(tmp_path: Path) -> None:
    scripts = SKILLS / "verify-rozliczenia" / "scripts"
    (tmp_path / "tu").mkdir()
    (tmp_path / "gdzie-indziej").mkdir()
    root = (tmp_path / "tu" / "run" / "fx").resolve()

    created = _script(scripts / "create_fixture.py", "--root", "run/fx", cwd=tmp_path / "tu")
    removed = _script(scripts / "cleanup.py", "--root", str(root), cwd=tmp_path / "gdzie-indziej")

    assert created.returncode == 0 and f"root={root} " in created.stdout, created.stdout + created.stderr
    assert removed.returncode == 0 and f"removed={root}" in removed.stdout, removed.stdout + removed.stderr
    assert not root.exists()


VARIANTS = ("default", "existing", "locked", "chain-real-templates")
EVERY = ("default", "existing", "locked")


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ([], ("default",)),
        (["--variant", "existing", "locked"], ("existing", "locked")),
        (["--variant", "existing locked"], ("existing", "locked")),
        (["--variant existing"], ("existing",)),
        (["--variant existing locked"], ("existing", "locked")),
        (["--variant", "existing,locked"], ("existing", "locked")),
        (["--variant", "locked", "--variant", "existing"], ("locked", "existing")),
        (["--variant", "locked", "all", "chain-real-templates"], ("locked", "default", "existing", "chain-real-templates")),
    ],
)
def test_wariant_to_lista_takze_w_jednym_argumencie(argv: list[str], expected: tuple[str, ...]) -> None:
    parser = skrypt_skilla.Parser()
    parser.add_variants(VARIANTS, default="default", every=EVERY)

    assert parser.parse_args(argv).variant == expected


def test_nieznany_wariant_konczy_sie_lista_znanych(capsys: pytest.CaptureFixture[str]) -> None:
    parser = skrypt_skilla.Parser()
    parser.add_variants(VARIANTS, default="default", every=EVERY)

    with pytest.raises(SystemExit) as stopped:
        parser.parse_args(["--variant", "existing", "zablokowany"])

    error = capsys.readouterr().err
    assert stopped.value.code == 2
    assert "zablokowany" in error and "existing, locked, chain-real-templates, all" in error


def test_katalog_przebiegu_domyslnie_w_checkoucie_a_podany_bezwzgledny(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parser = skrypt_skilla.Parser()
    parser.add_run_dir()
    monkeypatch.chdir(tmp_path)

    assert parser.parse_args([]).run_dir == REPO / ".verification"
    assert parser.parse_args(["--run-dir", "notatki/run"]).run_dir == tmp_path.resolve() / "notatki" / "run"
