"""Rodzaj Zatrzymania jako pole Komunikatu: „do Maksa” tylko przy bezwarunkowym przekazaniu Komunikatu.

Rodzaj ustawia ``Message.to_maintainer``, który pisze też zdanie „przekaż ten komunikat osobie utrzymującej
narzędzie”; ten test przypina zbiór kodów „do Maksa” dla każdej próbki obu katalogów procesów. Komunikat, który
przekazanie uzależnia od powtórki („Jeśli błąd wraca, przekaż…”) albo od innej przyczyny („W innym wypadku
przekaż…”), pisze je przez ``refer_if`` i jest „dla taty”. Drugi test pilnuje, że poza ``message.py`` nikt nie pisze
tego zdania ani nie ustawia rodzaju sam, więc tekst i rodzaj nie mogą się rozjechać.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.fixtures.centrum_processes import preparing_centrum, run_to_end
from tests.fixtures.message_samples import PREPARATION_SAMPLES, SETTLEMENT_SAMPLES, Samples

FOR_MAKS = {
    "przygotowanie-pliku-zbiorczego": {
        "BRAK_WZORCA",
        "USZKODZONY_WZORZEC",
        "NIEDOSTEPNY_WZORZEC",
        "ZLY_WZORZEC",
        "SCALONE_KOMORKI_WZORCA",
        "BLAD_PODSUMOWANIA",
        "BLAD_PLANU",
    },
    "przebieg-rozliczen": {
        "BLAD_PODSUMOWANIA",
        "BLAD_PLANU",
    },
}
SAMPLES: dict[str, Samples] = {
    "przygotowanie-pliku-zbiorczego": PREPARATION_SAMPLES,
    "przebieg-rozliczen": SETTLEMENT_SAMPLES,
}


@pytest.mark.parametrize("catalog", SAMPLES)
def test_do_maksa_sa_tylko_komunikaty_bezwarunkowo_przekazywane_osobie_utrzymujacej_narzedzie(catalog: str) -> None:
    messages = [sample() for samples in SAMPLES[catalog].values() for sample in samples]

    assert {message.code for message in messages if message.reports_to_maintainer} == FOR_MAKS[catalog]


def _docstrings(tree: ast.Module) -> set[int]:
    nodes = [tree, *(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef))]
    return {
        id(node.body[0].value)
        for node in nodes
        if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)
    }


def test_zdanie_o_osobie_utrzymujacej_narzedzie_i_rodzaj_do_maksa_powstaja_tylko_w_module_komunikatu() -> None:
    found = []
    for path in sorted((Path(__file__).resolve().parents[1] / "src").rglob("*.py")):
        if path.name == "message.py" and path.parent.name == "rozliczenia":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = _docstrings(tree)
        for node in ast.walk(tree):
            match node:
                case ast.Constant(value=str(text)) if "utrzymującej narzędzie" in text and id(node) not in docstrings:
                    found.append(f"{path.name}:{node.lineno} zdanie (message.Message.to_maintainer albo refer_if)")
                case ast.keyword(arg="reports_to_maintainer"):
                    found.append(f"{path.name}:{node.lineno} rodzaj (message.Message.to_maintainer)")
                case _:
                    pass

    assert found == []


def test_ten_sam_komunikat_do_maksa_przy_ponownym_uruchomieniu_nie_jest_powtorka(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    centrum.fixture.internal_template_path.unlink()
    first = run_to_end(centrum, dry_run=True)["result"]

    again = run_to_end(centrum, dry_run=True)["result"]

    assert [(result["stop_kind"], result["diagnosis"]) for result in (first, again)] == [("for_maks", "on_request")] * 2
