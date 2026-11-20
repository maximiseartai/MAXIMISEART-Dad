from __future__ import annotations

from pathlib import Path

import pytest

import chroniony_wlasciciel
from tests.fixtures.git_repo import commit, git, repository

OWNER = "src/pakiet/modul.py"
RUFF = '[lint.per-file-ignores]\n"{pattern}" = ["{code}"]\n'
OWNERS = 'OWNERS: dict[str, frozenset[str]] = {{"{path}": frozenset({{"os.name"}})}}\n'
CONTRACT = "[importlinter]\nroot_package = pakiet\n\n[importlinter:contract:jedno-wejscie]\nname = x\ntype = protected\nprotected_modules =\n    os\n{field} =\n    {module}\n"
SGCONFIG = "ruleDirs:\n  - reguly\n"
RULE = "id: regula\nlanguage: python\nmessage: użyj właściciela\nfiles:\n  - '**/*.py'\nignores:\n  - {pattern}\nrule:\n  pattern: zle()\n"


def _ban(pattern: str = OWNER, code: str = "TID251", row: str = OWNER) -> dict[str, str]:
    return {"ruff.toml": RUFF.format(pattern=pattern, code=code), "tests/test_zakazy_ruff.py": OWNERS.format(path=row)}


def _rule(pattern: str, directory: str = "reguly") -> dict[str, str]:
    return {"sgconfig.yml": SGCONFIG, f"{directory}/regula.yml": RULE.format(pattern=pattern)}


@pytest.mark.parametrize(
    ("config", "owned"),
    [
        pytest.param(_ban(), True, id="zakaz-tid251-z-wierszem-owners"),
        pytest.param(_ban(pattern="src/pakiet/{modul,inny}.py"), True, id="zakaz-tid251-z-plikiem-w-nawiasie"),
        pytest.param({"ruff.toml": RUFF.format(pattern=OWNER, code="TID251")}, False, id="zakaz-tid251-bez-wiersza-owners"),
        pytest.param(_ban(row="src/pakiet/inny.py"), False, id="wiersz-owners-innego-pliku"),
        pytest.param(_ban(code="BLE001"), False, id="wiersz-owners-bez-zwolnienia-z-tid251"),
        pytest.param(_ban(pattern="src/pakiet/*.py"), False, id="zwolnienie-tid251-na-wzorcu-zasiegu"),
        pytest.param({**_ban(), "ruff.toml": "[lint.per-file-ignores\n"}, False, id="ruff-toml-ktorego-toml-nie-wczyta"),
        pytest.param({".importlinter": CONTRACT.format(field="allowed_importers", module="pakiet.modul")}, True, id="allowed-importers-kontraktu-importow"),
        pytest.param({".importlinter": CONTRACT.format(field="allowed_importers", module="pakiet.*")}, False, id="allowed-importers-ze-wzorcem"),
        pytest.param({".importlinter": CONTRACT.format(field="ignore_imports", module="pakiet.modul")}, False, id="modul-w-innym-polu-kontraktu"),
        pytest.param(_rule(OWNER), True, id="ignores-reguly-ast-grep"),
        pytest.param(_rule(OWNER, directory="poza"), False, id="ignores-reguly-spoza-rule-dirs"),
        pytest.param(_rule("src/**"), False, id="ignores-ze-wzorcem-zasiegu"),
        pytest.param(_rule("src/pakiet"), False, id="ignores-katalogu-wlasciciela"),
        pytest.param(_rule("src/pakiet/modul"), False, id="ignores-z-przedrostkiem-sciezki-wlasciciela"),
        pytest.param({}, False, id="plik-spoza-konfiguracji-regul"),
    ],
)
def test_chroniony_wlasciciel_to_plik_wskazany_wprost_przez_konfiguracje_regul_drzewa(tmp_path: Path, config: dict[str, str], owned: bool) -> None:
    root = repository(tmp_path / "repo", {OWNER: "WARTOSC = 1\n", "src/pakiet/__init__.py": "", **config}, tools=())
    commit(root, "drzewo")

    protected = chroniony_wlasciciel.owners(root, git(root, "rev-parse", "HEAD^{tree}"))

    assert (OWNER in protected) is owned, sorted(protected)
    assert (chroniony_wlasciciel.refusal([OWNER], protected) is None) is owned
