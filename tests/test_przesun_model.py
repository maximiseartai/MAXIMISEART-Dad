from __future__ import annotations

import json
from pathlib import Path

import pytest

import przesun_model
import rozjazd_modelu

SKILL = "verify-model"
CODE = "src/kod.py"


@pytest.mark.parametrize(
    ("recorded", "reason"),
    [
        pytest.param("[]\n", "to nie jest niepusty obiekt ścieżka → definicje", id="plik definicji w innej postaci"),
        pytest.param(json.dumps({"src/nie_ma.py": {"f": ""}}), "nie ma definicji: src/nie_ma.py f", id="definicja z pliku, którego nie ma"),
    ],
)
def test_przesuniecie_ze_zlym_plikiem_definicji_albo_definicja_bez_kodu_konczy_sie_kodem_1_bez_zapisu(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], recorded: str, reason: str
) -> None:
    (tmp_path / CODE).parent.mkdir(parents=True)
    (tmp_path / CODE).write_text("def f() -> int:\n    return 1\n", encoding="utf-8")
    definitions = tmp_path / ".agents" / "skills" / SKILL / rozjazd_modelu.DEFINICJE
    definitions.parent.mkdir(parents=True)
    definitions.write_text(recorded, encoding="utf-8")

    code = przesun_model.main([SKILL, "--root", str(tmp_path)])

    [line] = capsys.readouterr().out.splitlines()
    assert (code, line.startswith("PRZESUNIĘCIE FAIL | "), reason in line) == (1, True, True), line
    assert definitions.read_text(encoding="utf-8") == recorded
