from __future__ import annotations

import pytest

import slowa_powloki

SLOWA = [
    pytest.param("szybko", "szybko", id="bez-cudzyslowu"),
    pytest.param("'a b'", "a b", id="apostrofy"),
    pytest.param("'a\\b'", "a\\b", id="ukosnik-w-apostrofach-zostaje"),
    pytest.param('"a b"', "a b", id="cudzyslow"),
    pytest.param('"a\\"b"', 'a"b', id="cudzyslow-w-cudzyslowie"),
    pytest.param('"a\\\\b"', "a\\b", id="ukosnik-w-cudzyslowie"),
    pytest.param('"a\\nb"', "a\\nb", id="ukosnik-przed-litera-w-cudzyslowie-zostaje"),
    pytest.param('"a\\$b"', "a$b", id="ucieczka-dolara-w-cudzyslowie"),
    pytest.param('"a\\`b"', "a`b", id="ucieczka-grawisu-w-cudzyslowie"),
    pytest.param("'a\\$b'", "a\\$b", id="ukosnik-przed-dolarem-w-apostrofach-zostaje"),
    pytest.param("szybk\\o", "szybko", id="ucieczka-poza-cudzyslowem"),
    pytest.param("a\\ b", "a b", id="ucieczka-spacji"),
    pytest.param("szyb\\\nko", "szybko", id="kontynuacja-linii-poza-cudzyslowem"),
    pytest.param('"szyb\\\nko"', "szybko", id="kontynuacja-linii-w-cudzyslowie"),
    pytest.param('"a\\\\\nb"', "a\\\nb", id="ukosnik-przed-nowa-linia-w-cudzyslowie"),
    pytest.param("'szyb\\\nko'", "szyb\\\nko", id="kontynuacja-linii-w-apostrofach-zostaje"),
    pytest.param("'x'\"y\"\\z", "xyz", id="sklejone-czesci"),
]


@pytest.mark.parametrize(("slowo", "jak_bash"), SLOWA)
def test_slowo_polecenia_bez_cudzyslowow_jest_takie_jak_po_rozwinieciu_basha(slowo: str, jak_bash: str) -> None:
    assert slowa_powloki.unquoted(slowo) == jak_bash
