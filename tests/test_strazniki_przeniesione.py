from __future__ import annotations

import pytest

import strazniki_przeniesione
from straznik import Guard, Kind

NODE = "pytest tests/test_x.py::test_y[p]"
MUTATION = '[{"nazwa": "błąd wraca", "zmiany": [["kod/a.py", "dobrze()", "zle()"]]}]'

PRZYJETE = [
    pytest.param(f'["2254/W1/r1"]\nstraznik = "{NODE}"\nmutacja = \'\'\'{MUTATION}\'\'\'\n', (2254, "W1 r1", Guard(Kind.PYTEST, ("tests/test_x.py::test_y[p]",)), True), id="test-z-mutacja"),
    pytest.param(f'["2289/W2/r1"]\nstraznik = "{NODE}"\n', (2289, "W2 r1", Guard(Kind.PYTEST, ("tests/test_x.py::test_y[p]",)), False), id="test-z-mutacja-z-werdyktow-pr"),
    pytest.param('["7/W3/r12"]\nstraznik = "ast-grep zakazane-wywolanie"\n', (7, "W3 r12", Guard(Kind.AST_GREP, ("zakazane-wywolanie",)), False), id="regula-bez-mutacji"),
]

ODMOWY = [
    pytest.param(f'["2254/W1"]\nstraznik = "{NODE}"\n', "klucz to Ważne PR/W<n>/r<k>", id="klucz-bez-rundy"),
    pytest.param(f'["#2254 W1 r1"]\nstraznik = "{NODE}"\n', "klucz to Ważne PR/W<n>/r<k>", id="klucz-w-postaci-naglowka"),
    pytest.param('["2254/W1/r1"]\nstraznik = "brak - usunięte"\n', "to wyjątek, a wpis przenosi Ważne do strażnika, który ma dowód", id="wyjatek-usuniete"),
    pytest.param('["2254/W1/r1"]\nstraznik = "brak - proza"\n', "to wyjątek, a wpis przenosi Ważne do strażnika, który ma dowód", id="wyjatek-proza"),
    pytest.param('["2254/W1/r1"]\nstraznik = "npm test"\n', "to nie selektor strażnika z listy", id="selektor-spoza-listy"),
    pytest.param('["2254/W1/r1"]\nmutacja = "[]"\n', "tabela z kluczem straznik", id="bez-selektora"),
    pytest.param(f'["2254/W1/r1"]\nstraznik = "{NODE}"\npowod = "PR 2401"\n', "bez innych kluczy", id="klucz-spoza-listy"),
    pytest.param('"2254/W1/r1" = "ruff"\n', "tabela z kluczem straznik", id="napis-zamiast-tabeli"),
    pytest.param(f'["2254/W1/r1"]\nstraznik = "ruff"\nmutacja = \'\'\'{MUTATION}\'\'\'\n', "mutacja to tekst JSON bloku ### Mutacja i stoi tylko przy strażniku pytest", id="mutacja-przy-ruff"),
    pytest.param(f'["2254/W1/r1"]\nstraznik = "{NODE}"\nmutacja = 1\n', "mutacja to tekst JSON bloku ### Mutacja", id="mutacja-nie-tekst"),
    pytest.param(f'["2254/W1/r1"]\nstraznik = "{NODE}"\nmutacja = "nie json"\n', "to nie JSON", id="mutacja-nie-json"),
    pytest.param(f'["2254/W1/r1"]\nstraznik = "{NODE}"\nmutacja = "[]"\n', "lista bez wpisu", id="mutacja-pusta"),
    pytest.param(
        f'["2254/W1/r1"]\nstraznik = "{NODE}"\nmutacja = \'\'\'{MUTATION.replace("kod/a.py", "tests/test_x.py")}\'\'\'\n', "zmiana w tests/test_x.py", id="mutacja-zmienia-test"
    ),
    pytest.param(f'["2254/W1/r1"\nstraznik = "{NODE}"\n', "to nie TOML", id="nie-toml"),
]


@pytest.mark.parametrize(("text", "expected"), PRZYJETE)
def test_wpis_straznika_przeniesionego_daje_wazne_selektor_i_mutacje(text: str, expected: tuple[int, str, Guard, bool]) -> None:
    [(key, moved)] = strazniki_przeniesione.parse(text).items()

    assert (key, (moved.pull, moved.major, moved.guard, moved.mutation is not None)) == ((expected[0], expected[1]), expected), moved
    if moved.mutation is not None:
        assert (moved.mutation.label, moved.mutation.round, moved.mutation.text.strip()) == ("W1", 1, MUTATION)


@pytest.mark.parametrize(("text", "said"), ODMOWY)
def test_wpis_straznika_przeniesionego_spoza_postaci_to_odmowa_z_przyczyna(text: str, said: str) -> None:
    with pytest.raises(ValueError, match=".") as refused:
        strazniki_przeniesione.parse(text)

    assert said in str(refused.value), refused.value
    assert str(refused.value).startswith(strazniki_przeniesione.PLIK), refused.value
