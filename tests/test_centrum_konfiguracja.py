"""Konfiguracja w Centrum rozliczeń przez HTTP API: Wzorce, Wykonawcy i wersja narzędzia, tylko do odczytu."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, NoReturn

import pytest

from rozliczenia import tool_files
from rozliczenia.centrum import tool_freshness

from rozliczenia.centrum.configuration import ConfigurationFiles
from rozliczenia.centrum.tool_freshness import AnswerSource, KeySource
from rozliczenia.run_context import TemplateCheck, check_on_disk
from rozliczenia.template_file import TemplateFile
from rozliczenia.workbook_files import Problem, WorkbookError
from rozliczenia.centrum.report_box import Unreachable

from tests.fixtures.centrum import (
    TOOL_COMMIT,
    CentrumClient,
    FakeGitHub,
    FakeReportBox,
    ToolDirectory,
    centrum_app,
    write_report_key,
)
from tests.fixtures.github_api import github_api, newest_on_main
from tests.fixtures.centrum_processes import write_configuration
from atrapy.settlement import WORKERS, worker_list, write_template, write_worker_list

INTERNAL = tool_files.INTERNAL_TEMPLATE.name
COLLECTIVE = tool_files.COLLECTIVE_TEMPLATE.name
WORKER = tool_files.WORKER_TEMPLATE.name
REPORT_TO_MAINTAINER = "Przekaż ten komunikat osobie utrzymującej narzędzie."


@dataclass
class Configured:
    client: CentrumClient
    files: ConfigurationFiles


def configured(
    tmp_path: Path, github: FakeGitHub | None = None, template_check: TemplateCheck = check_on_disk
) -> Configured:
    tool = ToolDirectory(tmp_path)
    files = write_configuration(tool)
    app = centrum_app(tool, tool_freshness=(github or FakeGitHub()).freshness(), template_check=template_check)
    return Configured(CentrumClient(app), files)


def read_configuration(app: Configured) -> dict[str, Any]:
    response = app.client.get("/api/configuration")
    assert response.status_code == 200
    configuration = response.json()
    assert isinstance(configuration, dict)
    return configuration


def templates_by_file(configuration: dict[str, Any]) -> dict[str, dict[str, Any]]:
    templates = configuration["templates"]
    assert isinstance(templates, list)
    return {template["file_name"]: template for template in templates}


def test_wzorce_sprawdza_czytnik_wzorcow_procesu(tmp_path: Path) -> None:
    def open_in_excel(template: TemplateFile) -> NoReturn:
        raise WorkbookError(template.path, Problem.OPEN_IN_EXCEL)

    app = configured(tmp_path, template_check=open_in_excel)

    templates = templates_by_file(read_configuration(app))
    assert {name: (template["problem"], template["level"]) for name, template in templates.items()} == {
        INTERNAL: ("open_in_excel", "warning"),
        COLLECTIVE: ("open_in_excel", "warning"),
        WORKER: ("open_in_excel", "warning"),
    }


def test_niezmieniony_wzorzec_jest_sprawdzany_raz_a_brakujacy_przy_kazdym_odczycie(tmp_path: Path) -> None:
    checked: list[str] = []

    def counting(template: TemplateFile) -> None:
        checked.append(template.path.name)
        template.check()

    app = configured(tmp_path, template_check=counting)
    app.files.worker_template.unlink()

    read_configuration(app)
    read_configuration(app)

    assert sorted(checked) == sorted([INTERNAL, COLLECTIVE, WORKER, WORKER])


@pytest.mark.parametrize("problem", [Problem.UNREADABLE, Problem.LAYOUT, Problem.HAS_DATA])
def test_niezmieniony_wzorzec_z_problemem_tresci_jest_sprawdzany_raz(tmp_path: Path, problem: Problem) -> None:
    checked: list[str] = []

    def damaged(template: TemplateFile) -> NoReturn:
        checked.append(template.path.name)
        raise WorkbookError(template.path, problem)

    app = configured(tmp_path, template_check=damaged)

    first = read_configuration(app)
    second = read_configuration(app)

    assert sorted(checked) == sorted([INTERNAL, COLLECTIVE, WORKER])
    assert second["templates"] == first["templates"]


INACCESSIBLE_TEMPLATE = (
    "Nie można teraz odczytać wzorca. Plik może być zajęty przez inny program. Nie utworzono żadnego pliku."
)


def test_wzorzec_niedostepny_jest_gotowy_bez_restartu_gdy_dostep_wraca(tmp_path: Path) -> None:
    file_name = INTERNAL
    blocked = {file_name}

    def blocking(template: TemplateFile) -> None:
        if template.path.name in blocked:
            raise WorkbookError(template.path, Problem.INACCESSIBLE)
        template.check()

    app = configured(tmp_path, template_check=blocking)
    path = tmp_path / "config" / file_name
    signature = (path.stat().st_mtime_ns, path.stat().st_size)
    while_blocked = templates_by_file(read_configuration(app))[file_name]
    blocked.clear()

    after = templates_by_file(read_configuration(app))[file_name]

    assert (while_blocked["state"], while_blocked["message"]["what"]) == ("problem", INACCESSIBLE_TEMPLATE)
    assert "uszkodzony" not in while_blocked["message"]["what"]
    assert (path.stat().st_mtime_ns, path.stat().st_size) == signature
    assert after["state"] == "ready"


def test_wszystkie_trzy_wzorce_sa_na_miejscu_i_czytelne(tmp_path: Path) -> None:
    configuration = read_configuration(configured(tmp_path))

    assert configuration["templates"] == [
        {"state": "ready", "label": "Wzorzec rozliczenia wewnętrznego", "file_name": INTERNAL},
        {"state": "ready", "label": "Wzorzec pliku zbiorczego", "file_name": COLLECTIVE},
        {"state": "ready", "label": "Wzorzec rozliczenia pracownika", "file_name": WORKER},
    ]


def test_brak_wzorca_jest_komunikatem_w_trzech_czesciach(tmp_path: Path) -> None:
    file_name = INTERNAL
    app = configured(tmp_path)
    (tmp_path / "config" / file_name).unlink()

    templates = templates_by_file(read_configuration(app))

    assert templates[file_name]["state"] == "problem"
    assert (templates[file_name]["problem"], templates[file_name]["level"]) == ("missing", "stop")
    assert templates[file_name]["message"] == {
        "what": "Nie znaleziono wzorca, z którego powstają pliki okresu. Nie utworzono żadnego pliku.",
        "where": f"plik {file_name}, folder config",
        "action": REPORT_TO_MAINTAINER,
    }
    assert [template["state"] for name, template in templates.items() if name != file_name] == ["ready", "ready"]


UNREADABLE_TEMPLATE = (
    "Nie można odczytać wzorca. Plik jest uszkodzony albo nie jest skoroszytem .xlsx. Nie utworzono żadnego pliku."
)


def test_nieczytelny_wzorzec_trzeba_przekazac_osobie_utrzymujacej_narzedzie(tmp_path: Path) -> None:
    app = configured(tmp_path)
    (tmp_path / "config" / INTERNAL).write_bytes(b"to nie jest skoroszyt")

    template = templates_by_file(read_configuration(app))[INTERNAL]

    assert (template["problem"], template["level"]) == ("unreadable", "stop")
    assert template["message"] == {
        "what": UNREADABLE_TEMPLATE,
        "where": f"plik {INTERNAL}, folder config",
        "action": REPORT_TO_MAINTAINER,
    }


def test_naprawiony_albo_zamkniety_wzorzec_jest_gotowy_przy_nastepnym_odczycie(tmp_path: Path) -> None:
    app = configured(tmp_path)
    config = tmp_path / "config"
    (config / WORKER).write_bytes(b"to nie jest skoroszyt")
    lock_file = config / f"~${INTERNAL}"
    lock_file.touch()
    broken = templates_by_file(read_configuration(app))
    write_template(config / WORKER)
    lock_file.unlink()

    repaired = templates_by_file(read_configuration(app))

    assert [broken[WORKER]["state"], broken[INTERNAL]["state"]] == ["problem", "problem"]
    assert [repaired[WORKER]["state"], repaired[INTERNAL]["state"]] == ["ready", "ready"]


def config_directory_snapshot(config: Path) -> dict[str, tuple[bytes, int]]:
    return {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in sorted(config.iterdir()) if path.is_file()}


def test_centrum_nie_zmienia_zadnego_pliku_konfiguracji_ani_wzorca(tmp_path: Path) -> None:
    app = configured(tmp_path)
    config = tmp_path / "config"
    (config / f"~${INTERNAL}").write_bytes(b"blokada Excela")
    before = config_directory_snapshot(config)

    read_configuration(app)
    change = app.client.put("/api/configuration", json={})

    assert change.status_code == 405
    assert config_directory_snapshot(config) == before


def read_workers(app: Configured) -> dict[str, Any]:
    response = app.client.get("/api/settings")
    assert response.status_code == 200, response.json()
    return dict(response.json()["workers"])


def test_nowy_wykonawca_dopisany_do_listy_jest_widoczny_bez_restartu(tmp_path: Path) -> None:
    app = configured(tmp_path)
    read_workers(app)
    write_worker_list(ToolDirectory(tmp_path).worker_list, worker_list({**WORKERS, "nowy.wykonawca": "Nowy Wykonawca"}))

    workers = read_workers(app)

    assert workers["workers"][-1]["name"] == "Nowy Wykonawca"


def test_wersja_narzedzia_to_skrot_commitu_i_dzien_przejscia_na_niego(tmp_path: Path) -> None:
    configuration = read_configuration(configured(tmp_path, FakeGitHub(since=date(2026, 10, 20))))

    assert configuration["version"] == {"commit": TOOL_COMMIT[:7], "since": "2026-10-20"}


def test_narzedzie_poza_klonem_gita_ma_nieznana_wersje(tmp_path: Path) -> None:
    configuration = read_configuration(configured(tmp_path, FakeGitHub(tool_commit=None)))

    assert (configuration["version"], configuration["freshness"]) == (None, "not_checked")


NEWER_RELEASE = "2222222222222222222222222222222222222222"


@pytest.mark.parametrize(
    ("key", "refused_token", "authorizations"),
    [
        (None, None, {None}),
        ("token-wymyslony-w-tescie", None, {"Bearer token-wymyslony-w-tescie"}),
        ("token-wymyslony-w-tescie", 401, {"Bearer token-wymyslony-w-tescie", None}),
        # Takiego klucza nie da się wysłać w nagłówku, a pytanie bez tokenu i tak dostaje odpowiedź.
        ("token-wymyślony-w-teście", None, {None}),
        ("token-wymyslony-1\ntoken-wymyslony-2", None, {None}),
    ],
    ids=["bez-pliku-klucza", "z-tokenem", "odrzucony-token", "klucz-z-polska-litera", "klucz-w-dwoch-liniach"],
)
def test_konfiguracja_pyta_github_o_wydania_z_tokenem_do_zgloszen_tylko_gdy_jest_plik_klucza(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prawdziwe_wydania_githuba: Callable[[KeySource, str], AnswerSource],
    key: str | None,
    refused_token: int | None,
    authorizations: set[str | None],
) -> None:
    monkeypatch.setattr(tool_freshness, "github_releases", prawdziwe_wydania_githuba)
    tool = ToolDirectory(tmp_path)
    write_configuration(tool)
    if key is not None:
        write_report_key(tool, key)
    with github_api(newest_on_main("/repos/tata/narzedzie", "v9.0.0", NEWER_RELEASE), refused_token=refused_token) as api:
        monkeypatch.setattr(tool_freshness, "TOOL_API", f"{api.url}/repos/tata/narzedzie")
        client = CentrumClient(centrum_app(tool, tool_freshness=None))
        configuration = client.get("/api/configuration").json()
        client.stop()

    assert {asked.authorization for asked in api.asked} == authorizations
    # Odmowa tokenu przez GitHub nie zabiera propozycji aktualizacji ani nie odrzuca klucza Skrzynki.
    assert (configuration["update_offered"], configuration["reports"]) == (True, "missing_key" if key is None else "ready")


@pytest.mark.parametrize("search_failure", [None, Unreachable()], ids=["token-przyjety", "skrzynka-bez-odpowiedzi"])
def test_konfiguracja_mowi_zgloszenia_gotowe_takze_o_tokenie_ktorego_skrzynka_jeszcze_nie_sprawdzila(
    tmp_path: Path, search_failure: Unreachable | None
) -> None:
    tool = ToolDirectory(tmp_path)
    write_configuration(tool)
    write_report_key(tool, "github_pat_SYNTETYCZNY_TOKEN_DO_ZGLOSZEN")
    box = FakeReportBox(search_failure=search_failure)
    client = CentrumClient(centrum_app(tool, tool_freshness=FakeGitHub().freshness(), report_box=box))

    reports = client.get("/api/configuration").json()["reports"]
    client.stop()

    assert reports == "ready"
