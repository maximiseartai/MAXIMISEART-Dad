"""Model TLA+ Dziennika Wyceny w efenix i Logów Urwanego Uruchomienia: kod opisany modelem i opowieść kontrprzykładu.

Model opisuje definicje z ``model/definicje.json`` skilla ``verify-urwane-uruchomienie`` w chwili ich skrótów: funkcje,
klasy, przypisania i metody po ścieżce od modułu (``Klasa.metoda``, ``create_app.runs``); rozjazd rozstrzyga ``tools/lib/rozjazd_modelu.py``
(``tests/test_rozjazd_modelu.py``). Zmiana innej części tych plików (``run_logs.py``, ``app.py`` i ``runs.py`` zmieniają
się często) rozjazdem nie jest. Testy rozjazdu biegną na repozytorium z plikami zbudowanymi z tej tabeli, nie na kodzie
``src/``: sprawdzają tabelę, a kod opisany modelem sprawdza krok ``ci:`` skilla. Werdykt i znane znaleziska sprawdza
``tests/test_model_tlc.py`` na drodze wspólnej dla modeli skilli.
"""

from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import shutil

import pytest

from tests.fixtures.model_tlc import model_tlc, rozjazd_modelu, skrypt_modelu, wyjscie_tlc

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "verify-urwane-uruchomienie" / "scripts" / "sprawdz_urwane_uruchomienie.py"
DEFINITIONS = ROOT / ".agents" / "skills" / "verify-urwane-uruchomienie" / "model" / "definicje.json"


def _definitions() -> dict[str, list[str]]:
    return {path: list(names) for path, names in json.loads(DEFINITIONS.read_text(encoding="utf-8")).items()}


def _source(names: list[str]) -> str:
    """Plik z każdą definicją z ``names`` (``Klasa.metoda`` jako metoda w swojej klasie, tak samo ``create_app.runs``),
    każda z własnym wynikiem, i z funkcją oraz metodą każdej klasy, których tabela nie wymienia."""

    classes: dict[str, list[str]] = defaultdict(list)
    lines = []
    for name in names:
        if "." in name:
            owner, member = name.split(".", 1)
            classes[owner].append(member)
        else:
            lines += [f"def {name}() -> str:", f'    return "{name}"', ""]
    for owner, members in classes.items():
        lines.append(f"class {owner}:")
        for member in [*members, "obok"]:
            lines += [f"    def {member}(self) -> str:", f'        return "{owner}.{member}"', ""]
    return "\n".join([*lines, "def obok() -> str:", '    return "obok"', ""])


def _file_of(name: str) -> str:
    """Plik definicji ``name`` z tabeli; ``Klasa.obok`` leży w pliku klasy, a ``obok`` w pliku ``guard_logs``."""

    owner = name.split(".")[0] + "." if name.endswith(".obok") else None
    wanted = "guard_logs" if name == "obok" else name
    [path] = [
        path
        for path, names in _definitions().items()
        if wanted in names or (owner is not None and any(listed.startswith(owner) for listed in names))
    ]
    return path


def _repository(root: Path) -> Path:
    """Tabela definicji skilla i pliki, które ją spełniają, ze skrótami przeliczonymi na nich; zwraca folder skilla."""

    copy = root / DEFINITIONS.relative_to(ROOT)
    copy.parent.mkdir(parents=True)
    shutil.copy(DEFINITIONS, copy)
    for path, names in _definitions().items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(_source(names), encoding="utf-8")
    skill = copy.parents[1]
    rozjazd_modelu.przesun(skill, root)
    return skill


def _change(root: Path, name: str) -> None:
    """Nowy wynik definicji ``name`` (albo funkcji ``obok`` jej pliku), czyli zmiana jej treści."""

    path = root / _file_of(name)
    text = path.read_text(encoding="utf-8")
    anchor = f'return "{name}"'
    assert text.count(anchor) == 1, anchor
    path.write_text(text.replace(anchor, f'return "{name} po zmianie"'), encoding="utf-8")


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("RunComments.close_left_behind", id="zamykanie-dziennikow"),
        pytest.param("RunComments.send_left_behind", id="wysylka-wersji-zastepczych"),
        pytest.param("close", id="macierz-startu"),
        pytest.param("create_app.runs", id="kolejnosc-dzialan-po-wyniku"),
        pytest.param("create_app.send_interrupted", id="wysylka-przy-zapytaniu"),
        pytest.param("create_app.lifespan", id="start-kolejki"),
        pytest.param("run_process", id="wynik-uruchomienia"),
        pytest.param("_remove", id="usuniecie-dziennika"),
    ],
)
def test_zmieniona_definicja_opisana_modelem_jest_rozjazdem(tmp_path: Path, name: str) -> None:
    skill = _repository(tmp_path)
    _change(tmp_path, name)

    found = rozjazd_modelu.rozjazd(skill, tmp_path)

    assert found is not None and f"kod opisany modelem zmienił się: {_file_of(name)} {name}." in found, found


def test_metoda_rozjazdu_to_metoda_swojej_klasy_a_nie_metoda_o_tej_nazwie_w_innej_klasie(tmp_path: Path) -> None:
    """``RunLog.interrupted`` (Logi z dziennika) i ``RecordMaker.interrupted`` (te Logi z narzędziem i środowiskiem) to
    dwie definicje: zmiana pierwszej jest rozjazdem tylko pierwszej."""

    skill = _repository(tmp_path)
    _change(tmp_path, "RunLog.interrupted")

    found = rozjazd_modelu.rozjazd(skill, tmp_path)

    assert found is not None and f"zmienił się: {_file_of('RunLog.interrupted')} RunLog.interrupted. " in found, found


@pytest.mark.parametrize("name", ["obok", "RunComments.obok"])
def test_zmiana_obok_definicji_opisanych_modelem_nie_jest_rozjazdem(tmp_path: Path, name: str) -> None:
    skill = _repository(tmp_path)
    _change(tmp_path, name)

    assert rozjazd_modelu.rozjazd(skill, tmp_path) is None


def test_kontrprzyklad_daje_obietnice_i_przyczyny_jej_zdarzen_a_odczyt_ktory_sie_nie_udal_nazywa_po_imieniu(
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = wyjscie_tlc(
        "BezUrwanychPoWynikuPozaZnanymi",
        ("Init", {"dziennik": '<<"jest", "brak">>', "kursor": "1", "awarieOdczytu": "0", "poWyniku": "{}"}),
        (
            "Czytaj",
            {"dziennik": '<<"jest", "brak">>', "kursor": "2", "awarieOdczytu": "1", "poWyniku": '{{"przed-wpisem-konca",\n   "wpis-konca-nieudany"}}'},
        ),
    )

    found = model_tlc.werdykt(skrypt_modelu(SCRIPT).MODEL, output)

    assert found == model_tlc.Werdykt("BezUrwanychPoWyniku", frozenset({"przed-wpisem-konca", "wpis-konca-nieudany"}))
    assert "1. close: odczyt dziennika Wyceny 1 rzuca OSError, dziennik zostaje następnemu startowi" in capsys.readouterr().out


def test_przebieg_bez_konca_to_naruszone_zbieganie_bez_znanych_znalezisk(capsys: pytest.CaptureFixture[str]) -> None:
    output = wyjscie_tlc(None, ("Init", {"dziennik": '<<"jest">>'}), ("Start", {"dziennik": '<<"jest">>'}), ("Back to state 1", {}))

    found = model_tlc.werdykt(skrypt_modelu(SCRIPT).MODEL, output)

    told = capsys.readouterr().out
    assert found == model_tlc.Werdykt("Zbieganie")
    assert ("naruszone Zbieganie" in told, "(stąd znów krok 0 i tak bez końca)" in told) == (True, True)
