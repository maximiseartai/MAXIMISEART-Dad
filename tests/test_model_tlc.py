"""Jedna droga sprawdzenia modelu TLA+ skilla (``tools/lib/model_tlc.py``) i jego narzędzia TLC (``narzedzia_tlc.py``).

Znane znalezisko z ``model/konfiguracje.json`` wybacza tylko w swojej konfiguracji, tylko swoją obietnicę i tylko
przebieg, w którym zdarzyła się jego przyczyna: kontrprzykład innej obietnicy, bez tej przyczyny albo w konfiguracji,
która go nie podaje, to nowe naruszenie (werdykt FAIL #638). ``.cfg`` powstaje z konfiguracji i obietnic modelu, więc
żadna konfiguracja nie pomija obietnicy. Rozjazd modelu z kodem kończy sprawdzenie w CI przed TLC.

Narzędzia TLC (``tla2tools.jar``) pobiera się z GitHub Releases: chwilowy 5xx się ponawia, a gdy pobieranie zawiedzie do
końca, linia mówi, że zawiodło narzędzie, nie model (#930). Jar z katalogu podręcznego liczy się tylko z przypiętą sumą,
a CI zapisuje ten katalog w cache tylko z takim jarem (#940).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
import email.message
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
from types import ModuleType
import urllib.error

import pytest
import yaml

from tests.fixtures.model_tlc import model_tlc, narzedzia_tlc, rozjazd_modelu, skrypt_modelu, wyjscie_tlc
from tests.fixtures.potomne import potomne

ROOT = Path(__file__).resolve().parents[1]
ZAPIS = ROOT / "tools" / "ci" / "zapis_narzedzi_tlc.py"
WORKFLOWS = {"ci.yml": ROOT / ".github" / "workflows" / "ci.yml", "mutacje-nocne.yml": ROOT / ".github" / "workflows" / "mutacje-nocne.yml"}
SKRYPTY_MODELI = (
    ROOT / ".agents" / "skills" / "verify-kolejka-skrzynki" / "scripts" / "sprawdz_model_kolejki.py",
    ROOT / ".agents" / "skills" / "verify-urwane-uruchomienie" / "scripts" / "sprawdz_urwane_uruchomienie.py",
    ROOT / ".agents" / "skills" / "verify-wznowienie-wyceny-efenix" / "scripts" / "sprawdz_wznowienie_wyceny.py",
    ROOT / ".agents" / "skills" / "verify-aktualizacja-narzedzia" / "scripts" / "sprawdz_aktualizacje.py",
)
SPEC = """---- MODULE M ----
Next ==
    \\/ Pisz \\/ Czytaj
    \\/ \\E x \\in 1..2 : Tata(x)

Spec == Init /\\ [][Next]_vars
====
"""
PASSED = "Model checking completed. No error has been found.\n"
FINDING = {"obietnica": "Jedno", "przyczyna": "a", "znalezisko": "opis"}


def _model(tmp_path: Path, configs: object) -> model_tlc.Model:
    """Model testu: obietnice ``Jedno`` (przyczyny w ``slady``), ``Rowno`` (przyczyny w ``rozne``) i czasowa ``Zbieganie``
    bez znanych znalezisk, z konfiguracjami ``configs``."""

    skill = tmp_path / ".agents" / "skills" / "verify-m"
    (skill / "model").mkdir(parents=True, exist_ok=True)
    (skill / "model" / "M.tla").write_text(SPEC, encoding="utf-8")
    (skill / model_tlc.KONFIGURACJE).write_text(json.dumps(configs), encoding="utf-8")
    return model_tlc.Model(
        werdykt="MODEL M",
        skill=skill,
        specyfikacja="M.tla",
        obietnice={
            "Jedno": model_tlc.Obietnica("drugie issue."),
            "Rowno": model_tlc.Obietnica("część dwa razy.", "rozne"),
            "Zbieganie": model_tlc.Obietnica("kolejka nie zbiega.", None, czasowa=True),
        },
        opowiedz=lambda states: None,
        zakleszczenie=False,
    )


def _config(**extra: object) -> dict[str, object]:
    return {"opis": "Opis.", "stale": {"Czesci": 2, "Cel": "okres", "Siec": True}, **extra}


def _violation(invariant: str | None, causes: str = "{}", variable: str = "slady") -> str:
    return wyjscie_tlc(invariant, ("Init", {"krok": '"start"', variable: "{}"}), ("Pisz", {"krok": '"pisze"', variable: causes}))


def _checked(
    model: model_tlc.Model, answer: Callable[[str], str], capsys: pytest.CaptureFixture[str]
) -> tuple[int, list[str], list[str]]:
    """Sprawdzenie modelu z atrapą TLC ``answer(treść .cfg)``: kod wyjścia, linie wyjścia i treści ``.cfg`` przebiegów."""

    configs: list[str] = []

    def run_tlc(name: str, text: str) -> str:
        configs.append(text)
        return answer(text)

    code = model_tlc.sprawdz(model, model_tlc.konfiguracje(model), run_tlc)
    return code, capsys.readouterr().out.splitlines(), configs


@pytest.mark.parametrize(
    ("own", "rest", "last", "returncode"),
    [
        (_violation("Jedno", '{"a"}'), PASSED, "MODEL M OK, ZNANE ZNALEZISKA: 1", 0),
        (PASSED, PASSED, "MODEL M: ZNALEZISKO ZNIKNĘŁO (1)", 1),
        (_violation("Jedno", '{"a"}'), _violation("RownoPozaZnanymi", '{"a"}', "rozne"), "MODEL M: NOWE NARUSZENIE (1)", 1),
        (_violation("Rowno", '{"a"}', "rozne"), PASSED, "MODEL M: NOWE NARUSZENIE (1)", 1),
        (_violation("Jedno", '{"b"}'), PASSED, "MODEL M: NOWE NARUSZENIE (1)", 1),
        (_violation("TypeOK", '{"a"}'), PASSED, "MODEL M: BŁĄD MODELU (1)", 2),
        (_violation("Pomocniczy", '{"a"}'), PASSED, "MODEL M: BŁĄD MODELU (1)", 2),
        ("Error: TLC threw an unexpected exception.\n", PASSED, "MODEL M: BŁĄD MODELU (1)", 2),
        (_violation("Jedno", '{"a"}'), wyjscie_tlc(None, ("Init", {"slady": "{}"}), ("Stuttering", {})), "MODEL M: NOWE NARUSZENIE (1)", 1),
    ],
    ids=["znane", "zniknelo", "inna-obietnica-w-reszcie", "inna-obietnica", "bez-przyczyny", "typeok", "spoza-obietnic", "bez-werdyktu", "reszta-nie-zbiega"],
)
def test_znane_znalezisko_wybacza_tylko_swoja_obietnice_po_swojej_przyczynie(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], own: str, rest: str, last: str, returncode: int
) -> None:
    model = _model(tmp_path, {"f": _config(znane=[FINDING])})

    code, lines, configs = _checked(model, lambda text: rest if "PozaZnanymi" in text else own, capsys)

    assert (code, lines[-1]) == (returncode, last)
    assert len(configs) == 2
    assert "WybaczoneJedno = {}" in configs[0] and "PozaZnanymi" not in configs[0]
    assert all(part in configs[1] for part in ("JednoPozaZnanymi", "RownoPozaZnanymi", 'WybaczoneJedno = {"a"}', "WybaczoneRowno = {}"))


def test_konfiguracja_wybacza_tylko_znane_znaleziska_ktore_podaje_dla_niej(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Przyczyna znaleziska innej konfiguracji nie jest wybaczona: nowa droga do niej w konfiguracji, która jej nie
    podaje, to nowe naruszenie. Każde znalezisko ma swój przebieg bez pozostałych znanych swojej konfiguracji."""

    first, second, later = (
        {"obietnica": "Jedno", "przyczyna": "a", "znalezisko": "x"},
        {"obietnica": "Rowno", "przyczyna": "b", "znalezisko": "y"},
        {"obietnica": "Jedno", "przyczyna": "c", "znalezisko": "z"},
    )
    model = _model(tmp_path, {"koniec": _config(znane=[first, second]), "wpisy": _config(znane=[later]), "zwykle": _config()})
    answers = iter(
        [_violation("JednoPozaZnanymi", '{"a"}'), _violation("RownoPozaZnanymi", '{"b"}', "rozne"), PASSED, _violation("Jedno", '{"c"}'), PASSED, PASSED]
    )

    code, lines, configs = _checked(model, lambda text: next(answers), capsys)

    assert (code, lines[-1]) == (0, "MODEL M OK, ZNANE ZNALEZISKA: 3")
    forgiven = [tuple(line.strip() for line in text.splitlines() if line.strip().startswith("Wybaczone")) for text in configs]
    assert forgiven == [
        ("WybaczoneJedno = {}", 'WybaczoneRowno = {"b"}'),
        ('WybaczoneJedno = {"a"}', "WybaczoneRowno = {}"),
        ('WybaczoneJedno = {"a"}', 'WybaczoneRowno = {"b"}'),
        ("WybaczoneJedno = {}", "WybaczoneRowno = {}"),
        ('WybaczoneJedno = {"c"}', "WybaczoneRowno = {}"),
        ("WybaczoneJedno = {}", "WybaczoneRowno = {}"),
    ]


def test_konfiguracja_bez_znalezisk_z_kontrprzykladem_to_nowe_naruszenie(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    model = _model(tmp_path, {"f": _config()})

    code, lines, _ = _checked(model, lambda text: _violation("Rowno", "{}", "rozne"), capsys)

    assert (code, lines[-1]) == (1, "MODEL M: NOWE NARUSZENIE (1)")


def test_cfg_sprawdza_typeok_i_kazda_obietnice_a_wybaczony_przebieg_ich_warianty_poza_znanymi(tmp_path: Path) -> None:
    model = _model(tmp_path, {"f": _config(znane=[FINDING])})
    [config] = model_tlc.konfiguracje(model)

    plain = model_tlc.cfg(model, config, frozenset())
    forgiven = model_tlc.cfg(model, config, frozenset({("Jedno", "b"), ("Jedno", "a"), ("Rowno", "c")}))

    assert plain == (
        "\\* Opis.\nSPECIFICATION Spec\nINVARIANTS TypeOK Jedno Rowno\nPROPERTIES Zbieganie\nCHECK_DEADLOCK FALSE\nCONSTANTS\n"
        '    Czesci = 2\n    Cel = "okres"\n    Siec = TRUE\n    WybaczoneJedno = {}\n    WybaczoneRowno = {}\n'
    )
    assert forgiven.splitlines()[2:4] == ["INVARIANTS TypeOK JednoPozaZnanymi RownoPozaZnanymi", "PROPERTIES Zbieganie"]
    assert forgiven.splitlines()[-2:] == ['    WybaczoneJedno = {"a", "b"}', '    WybaczoneRowno = {"c"}']


def test_kontrprzyklad_skleja_wartosc_z_kilku_linii_i_konczy_przebieg_bez_konca_slowami_petli() -> None:
    output = wyjscie_tlc(
        "Jedno",
        ("Init", {"krok": '"start"', "issues": "<<>>"}),
        ("Zaloz", {"krok": '"open_issue: Sent"', "issues": '<< [klucz |-> "L"],\n   [klucz |-> "L"] >>', "plik": '<<"czeka">>'}),
        ("Stuttering", {}),
        ("Back to state 2", {}),
    )

    states = model_tlc.slad(output)

    assert [(state.akcja, state.petla) for state in states] == [
        ("Init", None),
        ("Zaloz", None),
        ("Stuttering", "(dalej nic się nie dzieje)"),
        ("Koniec", "(stąd znów krok 1 i tak bez końca)"),
    ]
    assert states[1].zmienne == {"krok": "open_issue: Sent", "issues": '<< [klucz |-> "L"], [klucz |-> "L"] >>', "plik": '<<"czeka">>'}
    assert states[3].zmienne == states[1].zmienne


@pytest.mark.parametrize(
    ("obietnica", "causes"),
    [(model_tlc.Obietnica("x", czasowa=True), {"a", "b-c"}), (model_tlc.Obietnica("x", None, czasowa=True), set())],
    ids=["ze-zdarzeniami", "bez-znanych"],
)
def test_przebieg_bez_konca_lamie_obietnice_czasowa_z_przyczynami_ostatniego_stanu(
    tmp_path: Path, obietnica: model_tlc.Obietnica, causes: set[str]
) -> None:
    told: list[Sequence[model_tlc.Stan]] = []
    model = model_tlc.Model("MODEL M", tmp_path, "M.tla", {"Jedno": model_tlc.Obietnica("y"), "Zbieganie": obietnica}, told.append)
    output = wyjscie_tlc(None, ("Init", {"slady": "{}"}), ("Pisz", {"slady": '{"a",\n   "b-c"}'}), ("Back to state 1", {}))

    found = model_tlc.werdykt(model, output)

    assert found == model_tlc.Werdykt("Zbieganie", frozenset(causes))
    assert [state.petla for state in told[0]] == [None, None, "(stąd znów krok 0 i tak bez końca)"]


@pytest.mark.parametrize(
    "configs",
    [
        {},
        [],
        {"f": {"opis": "Opis."}},
        {"f": _config(inne=1)},
        {"f": _config(opis="")},
        {"f": {"opis": "Opis.", "stale": {}}},
        {"f": {"opis": "Opis.", "stale": {"X": [1]}}},
        {"f": {"opis": "Opis.", "stale": {"X": 'a"b'}}},
        {"f": _config(znane={"obietnica": "Jedno"})},
        {"f": _config(znane=[{"obietnica": "Jedno", "przyczyna": "a"}])},
        {"f": _config(znane=[{**FINDING, "obietnica": "Zbieganie"}])},
        {"f": _config(znane=[{**FINDING, "obietnica": "Nieznana"}])},
    ],
    ids=["pusty", "lista", "bez-stalych", "obcy-klucz", "pusty-opis", "puste-stale", "stala-lista", "stala-z-cudzyslowem", "znane-nie-lista", "znalezisko-bez-opisu", "znalezisko-bez-wybaczenia", "znalezisko-nieznanej-obietnicy"],
)
def test_konfiguracje_w_innej_postaci_to_blad_modelu_przed_tlc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], configs: object
) -> None:
    model = _model(tmp_path, {})
    (model.skill / model_tlc.KONFIGURACJE).write_text(json.dumps(configs), encoding="utf-8")
    _without_drift_or_tools(monkeypatch)

    assert model_tlc.main(model, []) == 2
    assert capsys.readouterr().out.splitlines()[-1] == "MODEL M: BŁĄD MODELU (1)"


def test_konfiguracja_spoza_pliku_konfiguracji_to_blad_modelu(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    model = _model(tmp_path, {"f": _config()})
    _without_drift_or_tools(monkeypatch)

    assert model_tlc.main(model, ["--config", "f", "--config", "usunieta"]) == 2
    assert capsys.readouterr().out.splitlines()[0] == f"BŁĄD MODELU: {model_tlc.KONFIGURACJE} nie ma konfiguracji usunieta"


@pytest.mark.parametrize(
    ("akcje", "said"),
    [
        (frozenset({"Pisz", "Czytaj"}), "nie zna akcji Next: Tata, a zna akcje spoza Next: -"),
        (frozenset({"Pisz", "Czytaj", "Tata", "Start"}), "nie zna akcji Next: -, a zna akcje spoza Next: Start"),
    ],
    ids=["brak-akcji", "akcja-spoza-next"],
)
def test_opowiesc_ktora_nie_zna_kazdej_akcji_next_to_blad_modelu_przed_tlc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], akcje: frozenset[str], said: str
) -> None:
    base = _model(tmp_path, {"f": _config()})
    model = model_tlc.Model(base.werdykt, base.skill, base.specyfikacja, base.obietnice, base.opowiedz, akcje=akcje)
    _without_drift_or_tools(monkeypatch)

    assert model_tlc.main(model, []) == 2
    assert said in capsys.readouterr().out


def test_kazdy_skill_z_modelem_ma_konfiguracje_a_jego_opowiesc_zna_kazda_akcje_next() -> None:
    """To samo, co skrypt modelu sprawdza przed TLC, bez TLC: konfiguracje się wczytują, a opowieść, która nazywa akcje
    (``akcje``), zna każdą akcję ``Next`` swojej specyfikacji i żadnej innej."""

    models = [skrypt_modelu(script).MODEL for script in SKRYPTY_MODELI]
    checked = {}
    for model in models:
        spec = (model.skill / "model" / model.specyfikacja).read_text(encoding="utf-8")
        checked[model.skill.name] = (bool(model_tlc.konfiguracje(model)), model.akcje is None or model.akcje == model_tlc.akcje_next(spec))

    assert sorted(model.skill for model in models) == rozjazd_modelu.skille(ROOT)
    assert checked == {name: (True, True) for name in checked}
    assert {model.skill.name for model in models if model.akcje is not None} == {"verify-urwane-uruchomienie", "verify-wznowienie-wyceny-efenix"}


@pytest.mark.parametrize(
    ("value", "written"),
    [(True, "TRUE"), (False, "FALSE"), (0, "0"), (12, "12"), ("12", '"12"'), ("okres", '"okres"')],
    ids=["prawda", "falsz", "zero", "liczba", "napis-z-cyframi", "napis"],
)
def test_stala_konfiguracji_trafia_do_cfg_jako_wartosc_tla(tmp_path: Path, value: bool | int | str, written: str) -> None:
    """``TRUE``/``FALSE`` z wartości logicznej, liczba bez cudzysłowu, napis w cudzysłowie, także napis z samych cyfr."""

    model = _model(tmp_path, {"f": {"opis": "Opis.", "stale": {"Stala": value}}})
    [config] = model_tlc.konfiguracje(model)

    assert f"    Stala = {written}" in model_tlc.cfg(model, config, frozenset()).splitlines()


def _without_drift_or_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(katalog: Path) -> str:
        raise AssertionError("błąd modelu przed TLC nie pobiera narzędzi")

    monkeypatch.setattr(rozjazd_modelu, "rozjazd", lambda skill, root: None)
    monkeypatch.setattr(narzedzia_tlc, "java", unavailable)
    monkeypatch.setattr(narzedzia_tlc, "jar", unavailable)


def test_w_ci_rozjazd_konczy_sprawdzenie_porazka_przed_tlc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    model = _model(tmp_path, {"f": _config()})
    moved = "kod opisany modelem zmienił się od abcdef1: src/rozliczenia/centrum/app.py lifespan."
    asked: list[tuple[Path, Path]] = []

    def drift(skill: Path, root: Path) -> str:
        asked.append((skill, root))
        return moved

    _without_drift_or_tools(monkeypatch)
    monkeypatch.setattr(rozjazd_modelu, "rozjazd", drift)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    assert model_tlc.main(model, []) == 1
    assert capsys.readouterr().out.splitlines() == [f"UWAGA: {moved}", "", "MODEL M: ROZJAZD MODELU Z KODEM"]
    assert asked == [(model.skill, tmp_path)]


def test_poza_ci_rozjazd_tylko_ostrzega_a_java_i_jar_ze_zmiennych_zastepuja_narzedzia(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Kopia checkoutu mutacji nie ma katalogu podręcznego z Javą i jarem, więc bierze je z ``TLC_JAVA`` i ``TLC_JAR``."""

    model = _model(tmp_path, {"f": _config()})
    _without_drift_or_tools(monkeypatch)
    monkeypatch.setattr(rozjazd_modelu, "rozjazd", lambda skill, root: "pokryty kod zmienił się")
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv(model_tlc.JAVA, "java-z-kopii")
    monkeypatch.setenv(model_tlc.JAR, str(tmp_path / "tla2tools.jar"))
    calls: list[tuple[str, Path, Path, str]] = []

    def tlc(java: str, jar: Path, spec: Path, name: str, text: str) -> str:
        calls.append((java, jar, spec, name))
        return PASSED

    monkeypatch.setattr(model_tlc, "tlc", tlc)

    assert model_tlc.main(model, []) == 0
    assert calls == [("java-z-kopii", tmp_path / "tla2tools.jar", model.skill / "model" / "M.tla", "f")]
    assert capsys.readouterr().out.splitlines()[-3:] == ["UWAGA: pokryty kod zmienił się", "", "MODEL M OK"]


@pytest.mark.parametrize(("argv", "returncode"), [([], 0), (["--strict"], 1)], ids=["bez-strict", "strict"])
def test_znane_znaleziska_koncza_sie_kodem_1_tylko_ze_strict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], argv: list[str], returncode: int
) -> None:
    model = _model(tmp_path, {"f": _config(znane=[FINDING])})
    _without_drift_or_tools(monkeypatch)
    monkeypatch.setenv(model_tlc.JAVA, "java")
    monkeypatch.setenv(model_tlc.JAR, str(tmp_path / "tla2tools.jar"))
    monkeypatch.setattr(model_tlc, "tlc", lambda java, jar, spec, name, text: PASSED if "PozaZnanymi" in text else _violation("Jedno", '{"a"}'))

    assert model_tlc.main(model, argv) == returncode
    assert capsys.readouterr().out.splitlines()[-1] == "MODEL M OK, ZNANE ZNALEZISKA: 1"


def test_narzedzia_dla_kopii_ustawiaja_jave_i_jar_checkoutu_a_ustawionych_zmiennych_nie_zmieniaja(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(narzedzia_tlc, "java", lambda katalog: f"java z {katalog.name}")
    monkeypatch.setattr(narzedzia_tlc, "jar", lambda katalog: katalog / "tla2tools.jar")
    monkeypatch.setenv(model_tlc.JAVA, "java-ustawiona")
    monkeypatch.delenv(model_tlc.JAR, raising=False)

    model_tlc.narzedzia_dla_kopii(tmp_path)

    assert (os.environ[model_tlc.JAVA], os.environ[model_tlc.JAR]) == (
        "java-ustawiona",
        str(tmp_path / narzedzia_tlc.KATALOG / "tla2tools.jar"),
    )


JAR = b"tla2tools z atrapy"


def _download_answers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, answers: list[int | OSError]) -> list[str]:
    """Atrapa ``urlopen`` odpowiada kolejno z ``answers``: kod HTTP (200 daje jar) albo błąd sieci; zwraca adresy prób."""

    calls: list[str] = []

    def urlopen(url: str, timeout: float) -> io.BytesIO:
        calls.append(url)
        code = answers[len(calls) - 1]
        if isinstance(code, OSError):
            raise code
        if code != 200:
            raise urllib.error.HTTPError(url, code, "Gateway Time-out", email.message.Message(), None)
        return io.BytesIO(JAR)

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    monkeypatch.setattr(narzedzia_tlc, "PRZERWY_S", (0.0, 0.0))
    monkeypatch.setattr(narzedzia_tlc, "TLA_SHA256", hashlib.sha256(JAR).hexdigest())
    return calls


@pytest.mark.parametrize("awaria", [504, 500, 429, urllib.error.URLError("Connection reset by peer")], ids=["504", "500", "429", "siec"])
def test_chwilowa_awaria_github_releases_nie_przerywa_pobrania_tla2tools_bo_pobieranie_ponawia(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, awaria: int | OSError
) -> None:
    calls = _download_answers(tmp_path, monkeypatch, [awaria, 200])

    jar = narzedzia_tlc.jar(tmp_path)

    assert jar.read_bytes() == JAR
    assert calls == [narzedzia_tlc.TLA_URL, narzedzia_tlc.TLA_URL]


def test_pobranie_tla2tools_ktore_zawodzi_do_konca_konczy_sie_bledem_pobierania_a_nie_modelu(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _download_answers(tmp_path, monkeypatch, [504, 502, 503])

    with pytest.raises(SystemExit) as stopped:
        narzedzia_tlc.jar(tmp_path)

    assert str(stopped.value).startswith(f"BŁĄD POBIERANIA NARZĘDZIA TLC: {narzedzia_tlc.TLA_URL} po 3 próbach (HTTP 503 ")
    assert len(calls) == 3
    assert not list(tmp_path.glob("*.jar"))


def test_adres_tla2tools_ktorego_nie_ma_konczy_sie_bledem_pobierania_bez_ponawiania(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _download_answers(tmp_path, monkeypatch, [404, 200])

    with pytest.raises(SystemExit) as stopped:
        narzedzia_tlc.jar(tmp_path)

    assert str(stopped.value).startswith(f"BŁĄD POBIERANIA NARZĘDZIA TLC: {narzedzia_tlc.TLA_URL} odpowiada HTTP 404 ")
    assert len(calls) == 1


def test_jar_z_inna_suma_w_katalogu_podrecznym_pobiera_sie_ponownie(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _download_answers(tmp_path, monkeypatch, [200])
    narzedzia_tlc.jar_tla(tmp_path).write_bytes(b"jar innej wersji z cache")

    jar = narzedzia_tlc.jar(tmp_path)

    assert jar.read_bytes() == JAR
    assert calls == [narzedzia_tlc.TLA_URL]


def test_pobrany_jar_z_inna_suma_konczy_sie_bledem_pobierania_i_nie_zostaje_w_katalogu_podrecznym(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _download_answers(tmp_path, monkeypatch, [200])
    monkeypatch.setattr(narzedzia_tlc, "TLA_SHA256", hashlib.sha256(b"inny jar").hexdigest())

    with pytest.raises(SystemExit) as stopped:
        narzedzia_tlc.jar(tmp_path)

    assert str(stopped.value) == f"BŁĄD POBIERANIA NARZĘDZIA TLC: {narzedzia_tlc.TLA_URL} ma inną sumę SHA-256 niż przypięta; to nie wynik modelu."
    assert list(tmp_path.iterdir()) == []


def _pip_answers(monkeypatch: pytest.MonkeyPatch, codes: list[int]) -> list[list[str]]:
    """Atrapa ``potomne.run``: instalacja ``jdk4py`` kończy się kolejno kodami z ``codes`` (0 instaluje pakiet); zwraca próby."""

    installs: list[list[str]] = []

    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "--version" in args:
            return subprocess.CompletedProcess(args, 0)
        if "--target" in args:
            installs.append(args)
            code = codes[len(installs) - 1]
            if code == 0:
                (Path(args[args.index("--target") + 1]) / "jdk4py").mkdir(parents=True)
            return subprocess.CompletedProcess(args, code)
        assert "import jdk4py" in args[-1], args
        return subprocess.CompletedProcess(args, 0, stdout="/atrapa/java\n")

    monkeypatch.setattr(potomne, "run", run)
    monkeypatch.setattr(narzedzia_tlc, "PRZERWY_S", (0.0, 0.0))
    return installs


def test_instalacja_javy_ktora_zawiodla_raz_ponawia_sie_i_daje_jave_z_drugiej_proby(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    installs = _pip_answers(monkeypatch, [1, 0])

    java = narzedzia_tlc.java(tmp_path)

    assert java == "/atrapa/java"
    assert [args[-1] for args in installs] == [narzedzia_tlc.JDK4PY, narzedzia_tlc.JDK4PY]
    assert (tmp_path / "jdk" / "jdk4py").is_dir()


def test_instalacja_javy_ktora_zawodzi_do_konca_konczy_sie_bledem_pobierania_a_nie_modelu(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    installs = _pip_answers(monkeypatch, [1, 1, 1])

    with pytest.raises(SystemExit) as stopped:
        narzedzia_tlc.java(tmp_path)

    assert str(stopped.value).startswith(f"BŁĄD POBIERANIA NARZĘDZIA TLC: {narzedzia_tlc.JDK4PY} po 3 próbach (instalacja skończyła się kodem 1)")
    assert len(installs) == 3


def _zapis() -> ModuleType:
    return skrypt_modelu(ZAPIS)


@pytest.mark.parametrize(("jar", "zapisz"), [(None, "false"), (b"jar innej wersji", "false"), (JAR, "true")], ids=["bez-katalogu", "inna-suma", "przypiety"])
def test_ci_zapisuje_cache_narzedzi_tlc_tylko_z_jarem_o_przypietej_sumie(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, jar: bytes | None, zapisz: str) -> None:
    module = _zapis()
    monkeypatch.setattr(narzedzia_tlc, "TLA_SHA256", hashlib.sha256(JAR).hexdigest())
    monkeypatch.chdir(tmp_path)
    if jar is not None:
        katalog = tmp_path / narzedzia_tlc.KATALOG
        katalog.mkdir(parents=True)
        narzedzia_tlc.jar_tla(katalog).write_bytes(jar)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))

    assert module.main([]) == 0
    assert (tmp_path / "output").read_text(encoding="utf-8") == f"zapisz={zapisz}\n"


def test_kazde_zadanie_z_cache_narzedzi_tlc_zapisuje_go_dopiero_po_sprawdzeniu_jara() -> None:
    """Klucz cache zapisuje się raz i się nie nadpisuje, więc zapis przed sprawdzeniem jara mógłby utrwalić katalog bez niego."""

    katalog = _zapis().KATALOG.as_posix()
    shapes = {}
    for name, path in WORKFLOWS.items():
        for job_name, job in yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"].items():
            steps = job.get("steps", [])
            cache = [step for step in steps if step.get("with", {}).get("path") == katalog]
            if not cache:
                continue
            restore, save = cache
            [check] = [step for step in steps if step.get("run") == "python tools/ci/zapis_narzedzi_tlc.py"]
            units = next(step for step in steps if "tools/plan_ci.py wykonaj" in step.get("run", ""))
            shapes[f"{name}:{job_name}"] = (
                [step["uses"].split("@")[0] for step in cache],
                steps.index(restore) < steps.index(units) < steps.index(check) < steps.index(save),
                check["if"],
                save["if"],
                save["with"]["key"],
            )

    expected = (
        ["actions/cache/restore", "actions/cache/save"],
        True,
        "${{ !cancelled() && steps.tlc-cache.outputs.cache-hit != 'true' }}",
        "${{ !cancelled() && steps.tlc-check.outputs.zapisz == 'true' }}",
        "${{ steps.tlc-cache.outputs.cache-primary-key }}",
    )
    assert shapes == {"ci.yml:mutations": expected, "mutacje-nocne.yml:skill-mutations": expected}
