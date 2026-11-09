"""Test dymny benchmarku Przebiegu rozliczeń przez jego CLI, na małym scenariuszu z syntetycznymi Wzorcami."""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from openpyxl import load_workbook

from rozliczenia.period_folder import collective_file_name_with
from rozliczenia import tool_files
from rozliczenia.worker_config import load_worker_mapping
from tests.fixtures.benchmark import (
    data_row_entries,
    frozen_reference,
    identifying_values,
    measurement_in_progress,
    protected_repository_files,
    run_benchmark,
    start_benchmark,
    WORKER_TEMPLATE,
    write_templates,
)
from tests.fixtures.potomne import wait_for
from atrapy.settlement import write_mapping

RECORD_FIELDS = {
    "started_at",
    "git_sha",
    "dirty",
    "machine",
    "scenario",
    "runs",
    "wall_ms",
    "start_procesu_ms",
    "czas_uruchomienia_ms",
    "zakonczenie_procesu_ms",
    "phase_durations_ms",
    "counters",
    "oracle",
}
PHASES = {"Sprawdzanie", "Odczyt danych", "Planowanie", "Zapisywanie"}
SPREAD = {"mediana", "min", "max"}
COMMENT_SECTIONS = ("Hipoteza", "Zmiana", "Pomiar", "Bramka poprawności", "Decyzja", "Następny krok")
ORACLE_CATEGORIES = (
    "pliki",
    "wartosci",
    "formuly",
    "style",
    "hiperlacza",
    "scalenia",
    "wymiary",
    "nazwy_zdefiniowane",
    "external_links",
    "flagi_przeliczania",
    "liczniki",
    "komunikaty",
    "podsumowanie",
)


@pytest.fixture(autouse=True)
def maszyna_pomiarow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Folder blokad maszyny tego testu: benchmark nie czeka na testy ani pomiary innych agentów na tym komputerze."""

    directory = tmp_path / "maszyna"
    monkeypatch.setenv("QUIET_MACHINE_SCRATCH", str(directory))
    return directory


def test_benchmark_mierzy_przebieg_rozliczen_na_lustrze_i_opisuje_pomiar_bez_danych_wykonawcow(
    tmp_path: Path,
) -> None:
    config = write_mapping(tmp_path / tool_files.WORKER_CONFIG.name)
    journal = tmp_path / "dziennik.jsonl"
    mirror = tmp_path / "lustro"
    arguments = [
        "measure",
        "--scenario",
        "maly-tydzien",
        "--templates-dir",
        str(write_templates(tmp_path / "wzorce")),
        "--config",
        str(config),
        "--mirror-dir",
        str(mirror),
        "--journal",
        str(journal),
        "--machine",
        "test",
    ]
    repository_before = protected_repository_files()

    first = run_benchmark(*arguments)
    (collective_file,) = mirror.rglob(collective_file_name_with("*"))
    built_at = collective_file.stat().st_mtime_ns
    second = run_benchmark(*arguments)

    assert (first.returncode, second.returncode) == (0, 0), first.stderr + second.stderr
    assert collective_file.stat().st_mtime_ns == built_at  # drugi pomiar używa istniejącego lustra
    assert "Załączniki" in collective_file.parts
    assert collective_file.parent.parent.name == "INEA"
    assert protected_repository_files() == repository_before
    entries = data_row_entries(collective_file)
    assert len(entries) == 6
    for quantities_and_charges in entries:  # tata wpisał ilości w N:AP przed Przebiegiem rozliczeń
        assert any(isinstance(value, int) and value > 0 for value in quantities_and_charges[:29])
    assert any(value is not None for row in entries for value in row[29:])

    records = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 2
    for record in records:
        assert set(record) == RECORD_FIELDS
        assert (record["scenario"], record["machine"], record["runs"]) == ("maly-tydzien", "test", 3)
        assert record["oracle"] is None  # bez zamrożonego wyniku referencyjnego bramka nie jest sprawdzana
        assert len(record["git_sha"]) == 40
        assert isinstance(record["dirty"], bool)
        parts = [record[name] for name in ("start_procesu_ms", "czas_uruchomienia_ms", "zakonczenie_procesu_ms")]
        for spread in (record["wall_ms"], *parts, *record["phase_durations_ms"].values()):
            assert set(spread) == SPREAD
            assert spread["min"] <= spread["mediana"] <= spread["max"]
        assert set(record["phase_durations_ms"]) == PHASES
        # Czas ściany każdego uruchomienia to start procesu + Czas uruchomienia + zakończenie procesu
        # (z dokładnością do zaokrągleń), więc sumy skrajnych wartości obejmują skrajne czasy ściany.
        assert sum(part["min"] for part in parts) <= record["wall_ms"]["max"] + 2
        assert sum(part["max"] for part in parts) >= record["wall_ms"]["min"] - 2
        assert record["start_procesu_ms"]["min"] > 0  # interpreter i importy przed silnikiem zawsze coś kosztują
        assert record["counters"] | {"templates_total": 3, "empty": 1, "rows": 6, "issues": 0} == record["counters"]

    comment = run_benchmark("comment", "--journal", str(journal))
    assert comment.returncode == 0, comment.stderr
    headings = [line for line in comment.stdout.splitlines() if line.startswith("## ")]
    assert headings == [f"## {heading}" for heading in COMMENT_SECTIONS]
    assert "### maly-tydzien" in comment.stdout
    for record in records:
        wall, start = record["wall_ms"], record["start_procesu_ms"]
        assert f"{wall['mediana']} ({wall['min']}–{wall['max']})" in comment.stdout
        assert "| Start procesu [ms] |" in comment.stdout
        assert f"{start['mediana']} ({start['min']}–{start['max']}) |" in comment.stdout
        assert record["started_at"] in comment.stdout

    published = "".join(
        [
            *(result.stdout + result.stderr for result in (first, second, comment)),
            journal.read_text(encoding="utf-8"),
        ]
    )
    secrets = identifying_values(collective_file)
    assert len(secrets) == 4 * 6
    secrets |= {*load_worker_mapping(config), *load_worker_mapping(config).values()}
    assert {secret for secret in secrets if secret in published} == set()


def change_rate(worker_template: Path) -> None:
    """Inny, nadal poprawny Wzorzec rozliczenia pracownika: zmieniona stawka w arkuszu ``Rates``."""

    workbook = load_workbook(worker_template)
    try:
        workbook["Rates"]["B1"] = 99.5
        workbook.save(worker_template)
    finally:
        workbook.close()


def spread(median: int, low: int, high: int) -> dict[str, int]:
    return {"mediana": median, "min": low, "max": high}


@pytest.mark.parametrize(
    ("budget_ms", "exit_code", "verdict"),
    [(250_000, 0, "w budżecie"), (240_000, 1, "ponad budżetem o 1000 ms")],
)
def test_straz_czasu_opisuje_ostatni_pomiar_i_pada_tylko_powyzej_budzetu(
    tmp_path: Path, budget_ms: int, exit_code: int, verdict: str
) -> None:
    journal = tmp_path / "dziennik.jsonl"
    older = {"scenario": "typowy-tydzien", "wall_ms": spread(999_999, 999_999, 999_999)}
    latest = {
        "started_at": "2026-10-20T08:00:00+00:00",
        "git_sha": "0123456789abcdef0123456789abcdef01234567",
        "dirty": False,
        "machine": "github-windows-latest",
        "scenario": "typowy-tydzien",
        "runs": 3,
        "wall_ms": spread(241_000, 238_500, 247_250),
        "start_procesu_ms": spread(4_100, 3_900, 6_200),
        "czas_uruchomienia_ms": spread(236_000, 234_000, 240_000),
        "zakonczenie_procesu_ms": spread(900, 850, 1_050),
        "phase_durations_ms": {"Sprawdzanie": spread(5_100, 5_000, 5_300), "Zapisywanie": spread(228_000, 226_000, 233_000)},
        "counters": {"templates_total": 20},
        "oracle": None,
    }
    journal.write_text("\n".join(json.dumps(record) for record in (older, latest)) + "\n", encoding="utf-8")
    summary = tmp_path / "podsumowanie.md"
    summary.write_text("Wcześniejszy krok\n", encoding="utf-8")

    guard = run_benchmark(
        "guard", "--journal", str(journal), "--budget-ms", str(budget_ms), "--summary", str(summary)
    )

    assert guard.returncode == exit_code, guard.stderr
    text = summary.read_text(encoding="utf-8")
    assert text.startswith("Wcześniejszy krok\n")
    for expected in (
        "typowy-tydzien",
        "241000 (238500–247250)",
        "236000 (234000–240000)",
        "| Start procesu | 4100 (3900–6200) |",
        "| Zakończenie procesu | 900 (850–1050) |",
        "| Sprawdzanie | 5100 (5000–5300) |",
        "228000 (226000–233000)",
        "`0123456`",
        "github-windows-latest",
        f"{budget_ms} ms",
        verdict,
    ):
        assert expected in text
    assert "999999" not in text
    assert verdict in guard.stdout + guard.stderr


def test_benchmark_porownuje_pomiar_z_wynikiem_referencyjnym_zamrozonym_z_commita(tmp_path: Path) -> None:
    config = write_mapping(tmp_path / tool_files.WORKER_CONFIG.name)
    journal = tmp_path / "dziennik.jsonl"
    references = tmp_path / "referencje"
    common = [
        "--scenario",
        "maly-tydzien",
        "--templates-dir",
        str(write_templates(tmp_path / "wzorce")),
        "--config",
        str(config),
        "--mirror-dir",
        str(tmp_path / "lustro"),
        "--reference-dir",
        str(references),
    ]
    measure = ["measure", *common, "--journal", str(journal), "--machine", "test"]

    frozen = run_benchmark("freeze", *common, "--commit", "HEAD")
    assert frozen.returncode == 0, frozen.stdout + frozen.stderr
    reference_folder = frozen_reference(references)
    commit = reference_folder.parent.name
    assert len(commit) == 40
    assert len(list(reference_folder.glob("*.xlsx"))) == 3

    consistent = run_benchmark(*measure)
    for removed in sorted(reference_folder.glob("*.xlsx"))[:1]:
        removed.unlink()
    inconsistent = run_benchmark(*measure)
    comment = run_benchmark("comment", "--journal", str(journal))

    assert (consistent.returncode, inconsistent.returncode, comment.returncode) == (0, 0, 0), (
        consistent.stderr + inconsistent.stderr + comment.stderr
    )
    first, second = (json.loads(line)["oracle"] for line in journal.read_text(encoding="utf-8").splitlines())
    assert first == {"wynik": "zgodny", "referencja": commit, "roznice": dict.fromkeys(ORACLE_CATEGORIES, 0)}
    assert second == {
        "wynik": "niezgodny",
        "referencja": commit,
        "roznice": dict.fromkeys(ORACLE_CATEGORIES, 0) | {"pliki": 1},
    }
    gate = comment.stdout.split("## Bramka poprawności", 1)[1].split("## Decyzja", 1)[0]
    assert "**niezgodny**" in gate
    assert f"`{commit[:7]}`" in gate
    assert "| pliki | 1 |" in gate
    assert "| komunikaty | 0 |" in gate

    published = "".join(result.stdout + result.stderr for result in (frozen, consistent, inconsistent, comment))
    secrets = {*load_worker_mapping(config), *load_worker_mapping(config).values()}
    assert {secret for secret in secrets if secret in published} == set()


@pytest.mark.parametrize(
    "command", [["measure", "--machine", "test"], ["freeze", "--commit", "HEAD"]], ids=["measure", "freeze"]
)
def test_pomiar_czeka_az_skonczy_sie_inny_pomiar_z_tymi_samymi_wynikami_referencyjnymi(
    tmp_path: Path, command: list[str]
) -> None:
    config = write_mapping(tmp_path / tool_files.WORKER_CONFIG.name)
    references = tmp_path / "referencje"
    mirror = tmp_path / "lustro"
    arguments = [
        *command,
        "--scenario",
        "maly-tydzien",
        "--templates-dir",
        str(write_templates(tmp_path / "wzorce")),
        "--config",
        str(config),
        "--mirror-dir",
        str(mirror),
        "--reference-dir",
        str(references),
        *(["--journal", str(tmp_path / "dziennik.jsonl")] if command[0] == "measure" else []),
    ]

    with measurement_in_progress(tmp_path / "referencje.lock"):
        waiting = start_benchmark(*arguments)
        assert waiting.stderr is not None
        notice = waiting.stderr.readline()
        still_waiting = waiting.poll() is None
        mirror_during_wait = mirror.exists()
    stdout, stderr = waiting.communicate(timeout=100)

    assert waiting.returncode == 0, stdout + stderr
    assert "czeka" in notice
    assert still_waiting
    assert not mirror_during_wait  # nic ciężkiego nie rusza, dopóki trwa inny pomiar
    assert mirror.is_dir()
    secrets = {*load_worker_mapping(config), *load_worker_mapping(config).values()}
    assert {secret for secret in secrets if secret in notice} == set()


@pytest.mark.parametrize(
    "command", [["measure", "--machine", "test"], ["freeze", "--commit", "HEAD"]], ids=["measure", "freeze"]
)
def test_pomiar_czeka_az_inny_pomiar_zwolni_maszyne(tmp_path: Path, maszyna_pomiarow: Path, command: list[str]) -> None:
    journal = tmp_path / "dziennik.jsonl"
    references = tmp_path / "referencje"
    mirror = tmp_path / "lustro"
    arguments = [
        *command,
        "--scenario",
        "maly-tydzien",
        "--templates-dir",
        str(write_templates(tmp_path / "wzorce")),
        "--config",
        str(write_mapping(tmp_path / tool_files.WORKER_CONFIG.name)),
        "--mirror-dir",
        str(mirror),
        "--reference-dir",
        str(references),
        *(["--journal", str(journal)] if command[0] == "measure" else []),
    ]
    maszyna_pomiarow.mkdir()
    other_measurement = maszyna_pomiarow / "pomiar.lock"
    other_measurement.write_text(str(os.getpid()), encoding="utf-8")

    waiting = start_benchmark(*arguments)
    assert waiting.stdout is not None
    notice = waiting.stdout.readline()
    still_waiting = waiting.poll() is None
    mirror_during_wait = mirror.exists()
    other_measurement.unlink()
    stdout, stderr = waiting.communicate(timeout=100)

    assert waiting.returncode == 0, stdout + stderr
    assert notice.startswith("MASZYNA ZAJĘTA"), notice
    assert still_waiting
    assert not mirror_during_wait  # nic ciężkiego nie rusza, dopóki inny pomiar trzyma maszynę
    if command[0] == "measure":
        assert len(journal.read_text(encoding="utf-8").splitlines()) == 1
    else:
        assert frozen_reference(references).is_dir()


def journal_record(sha: str, machine: str, started_at: str, wall: dict[str, int]) -> dict[str, object]:
    return {
        "started_at": started_at,
        "git_sha": sha * 40,
        "dirty": False,
        "machine": machine,
        "scenario": "typowy-tydzien",
        "runs": 3,
        "wall_ms": wall,
        "czas_uruchomienia_ms": wall,
        "phase_durations_ms": {"Zapisywanie": wall},
        "counters": {"templates_total": 20},
        "oracle": None,
    }


def measurement_sections(comment: str) -> dict[str, str]:
    measurement = comment.split("## Pomiar", 1)[1].split("## Bramka poprawności", 1)[0]
    return {section.splitlines()[0].strip(): section for section in measurement.split("### ")[1:]}


@pytest.mark.parametrize("selection", [[], ["--before", "aaaa", "--after", "bbbb"]])
def test_komentarz_porownuje_pomiary_tego_samego_scenariusza_na_tej_samej_maszynie(
    tmp_path: Path, selection: list[str]
) -> None:
    journal = tmp_path / "dziennik.jsonl"
    records = [
        journal_record("a", "mac-m4max", "2026-10-01T08:00:00+00:00", spread(70_000, 69_000, 71_000)),
        journal_record("a", "tata-i7", "2026-10-02T08:00:00+00:00", spread(236_000, 234_000, 240_000)),
        journal_record("b", "mac-m4max", "2026-10-03T08:00:00+00:00", spread(10_000, 9_000, 11_000)),
    ]
    journal.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")

    comment = run_benchmark("comment", "--journal", str(journal), *selection)

    assert comment.returncode == 0, comment.stderr
    sections = measurement_sections(comment.stdout)
    mac = sections["typowy-tydzien (mac-m4max)"]
    assert "2026-10-01T08:00:00+00:00" in mac
    assert "2026-10-03T08:00:00+00:00" in mac
    assert "2026-10-02T08:00:00+00:00" not in mac
    assert "mediana krótsza o 60000 ms" in mac
    if selection:  # „po” wskazane commitem: pomiar taty z innego commita nie trafia do komentarza
        assert set(sections) == {"typowy-tydzien (mac-m4max)"}
    else:
        assert set(sections) == {"typowy-tydzien (mac-m4max)", "typowy-tydzien (tata-i7)"}
        tata = sections["typowy-tydzien (tata-i7)"]
        assert "2026-10-02T08:00:00+00:00" in tata
        assert "2026-10-01T08:00:00+00:00" not in tata
        assert "Poprawa czasu ściany" not in tata


def test_komentarz_pokazuje_start_procesu_takze_obok_pomiaru_sprzed_jego_mierzenia(tmp_path: Path) -> None:
    journal = tmp_path / "dziennik.jsonl"
    older = journal_record("a", "mac-m4max", "2026-10-01T08:00:00+00:00", spread(2_834, 2_820, 2_839))
    newer = journal_record("b", "mac-m4max", "2026-10-02T08:00:00+00:00", spread(2_800, 2_790, 2_810)) | {
        "start_procesu_ms": spread(70, 68, 75),
        "zakonczenie_procesu_ms": spread(14, 13, 16),
    }
    journal.write_text("".join(json.dumps(record) + "\n" for record in (older, newer)), encoding="utf-8")

    comment = run_benchmark("comment", "--journal", str(journal))

    assert comment.returncode == 0, comment.stderr
    mac = measurement_sections(comment.stdout)["typowy-tydzien (mac-m4max)"]
    assert "| Start procesu [ms] | — | 70 (68–75) |" in mac
    assert "| Zakończenie procesu [ms] | — | 14 (13–16) |" in mac
    rows = [line.split(" |", 1)[0] for line in mac.splitlines() if line.startswith("| ")]
    wall = rows.index("| Czas ściany [ms]")
    assert rows[wall + 1 : wall + 4] == [
        "| Start procesu [ms]",
        "| Czas uruchomienia [ms]",
        "| Zakończenie procesu [ms]",
    ]


def test_pomiar_z_niepoprawna_konfiguracja_wykonawcow_konczy_sie_przyczyna_z_katalogu_przebiegu(tmp_path: Path) -> None:
    config = tmp_path / tool_files.WORKER_CONFIG.name
    config.write_text("schema_version: 2\nworkers:\n  a: A\n", encoding="utf-8")
    journal = tmp_path / "dziennik.jsonl"

    measured = run_benchmark(
        "measure",
        "--scenario",
        "maly-tydzien",
        "--templates-dir",
        str(write_templates(tmp_path / "wzorce")),
        "--config",
        str(config),
        "--mirror-dir",
        str(tmp_path / "lustro"),
        "--reference-dir",
        str(tmp_path / "referencje"),
        "--journal",
        str(journal),
        "--machine",
        "test",
    )

    assert measured.returncode == 1
    reason = "Nie można odczytać konfiguracji wykonawców. Nieobsługiwana wersja konfiguracji."
    assert f"{reason} Plik: {config}" in measured.stderr
    assert not journal.exists()


def test_pomiar_z_innym_wzorcem_rozliczenia_pracownika_nie_ma_pasujacego_wyniku_referencyjnego(tmp_path: Path) -> None:
    config = write_mapping(tmp_path / tool_files.WORKER_CONFIG.name)
    journal = tmp_path / "dziennik.jsonl"
    references = tmp_path / "referencje"
    templates = write_templates(tmp_path / "wzorce")
    other_templates = tmp_path / "inne-wzorce"
    shutil.copytree(templates, other_templates)
    change_rate(other_templates / WORKER_TEMPLATE)
    common = [
        "--scenario",
        "maly-tydzien",
        "--config",
        str(config),
        "--mirror-dir",
        str(tmp_path / "lustro"),
        "--reference-dir",
        str(references),
    ]
    frozen = run_benchmark("freeze", *common, "--templates-dir", str(templates), "--commit", "HEAD")
    assert frozen.returncode == 0, frozen.stdout + frozen.stderr
    commit = frozen_reference(references).parent.name
    measure = ["measure", *common, "--templates-dir", str(other_templates), "--journal", str(journal), "--machine", "test"]

    named = run_benchmark(*measure, "--reference", commit[:7])
    unnamed = run_benchmark(*measure)

    assert named.returncode == 1
    assert "nie ma wyniku referencyjnego" in named.stderr
    assert "Wzorc" in named.stderr
    assert unnamed.returncode == 0, unnamed.stderr
    assert "Brak wyniku referencyjnego" in unnamed.stdout
    (record,) = (json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines())
    assert record["oracle"] is None


def changed_counter(result: dict[str, Any]) -> None:
    result["counters"]["rows"] += 1


def added_warning(result: dict[str, Any]) -> None:
    result["result"]["warnings"].append(
        {"code": "inny_komunikat", "what": "Co się stało.", "where": "Gdzie.", "action": "Co zrobić."}
    )


def changed_summary_figure(result: dict[str, Any]) -> None:
    result["result"]["summary"]["figures"][0]["value"] += 1


@pytest.mark.parametrize(
    ("change", "category"),
    [(changed_counter, "liczniki"), (added_warning, "komunikaty"), (changed_summary_figure, "podsumowanie")],
    ids=["inne-liczniki", "inny-kod-komunikatu", "inne-podsumowanie"],
)
def test_bramka_poprawnosci_jest_niezgodna_przy_innych_licznikach_komunikatach_albo_podsumowaniu(
    tmp_path: Path, change: Callable[[dict[str, Any]], None], category: str
) -> None:
    config = write_mapping(tmp_path / tool_files.WORKER_CONFIG.name)
    journal = tmp_path / "dziennik.jsonl"
    references = tmp_path / "referencje"
    common = [
        "--scenario",
        "maly-tydzien",
        "--templates-dir",
        str(write_templates(tmp_path / "wzorce")),
        "--config",
        str(config),
        "--mirror-dir",
        str(tmp_path / "lustro"),
        "--reference-dir",
        str(references),
    ]
    frozen = run_benchmark("freeze", *common, "--commit", "HEAD")
    assert frozen.returncode == 0, frozen.stdout + frozen.stderr
    result_path = frozen_reference(references).parent / "wynik.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    change(result)
    result_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")

    measured = run_benchmark("measure", *common, "--journal", str(journal), "--machine", "test")

    assert measured.returncode == 0, measured.stderr
    (record,) = (json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines())
    assert record["oracle"]["wynik"] == "niezgodny"
    assert record["oracle"]["roznice"] == dict.fromkeys(ORACLE_CATEGORIES, 0) | {category: 1}
    assert "niezgodny" in measured.stdout


def test_pomiar_z_wynikiem_referencyjnym_w_formacie_terminala_konczy_sie_poleceniem_ponownego_zamrozenia(
    tmp_path: Path,
) -> None:
    config = write_mapping(tmp_path / tool_files.WORKER_CONFIG.name)
    journal = tmp_path / "dziennik.jsonl"
    references = tmp_path / "referencje"
    common = [
        "--scenario",
        "maly-tydzien",
        "--templates-dir",
        str(write_templates(tmp_path / "wzorce")),
        "--config",
        str(config),
        "--mirror-dir",
        str(tmp_path / "lustro"),
        "--reference-dir",
        str(references),
    ]
    frozen = run_benchmark("freeze", *common, "--commit", "HEAD")
    assert frozen.returncode == 0, frozen.stdout + frozen.stderr
    result_path = frozen_reference(references).parent / "wynik.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    terminal_format = {"git_sha": result["git_sha"], "counters": result["counters"], "terminal": ["Wynik: OK"]}
    result_path.write_text(json.dumps(terminal_format, ensure_ascii=False), encoding="utf-8")

    measured = run_benchmark("measure", *common, "--journal", str(journal), "--machine", "test")

    assert measured.returncode == 1
    assert "stary format" in measured.stderr
    assert "freeze --commit" in measured.stderr
    assert str(result_path.parent) in measured.stderr
    assert not journal.exists()


def _settlement_runs(mirror: Path) -> dict[int, str]:
    listed = subprocess.run(["ps", "-A", "-ww", "-o", "pid=,command="], capture_output=True, text=True, check=True).stdout
    processes = (line.strip().split(" ", 1) for line in listed.splitlines() if line.strip())
    return {int(pid): command for pid, command in processes if "uruchom_proces.py settlement" in command and str(mirror) in command}


@pytest.mark.skipif(sys.platform == "win32", reason="ps i SIGSTOP są tylko na POSIX")
def test_zabity_benchmark_nie_zostawia_wstrzymanego_przebiegu_ani_kopii_commitu(tmp_path: Path) -> None:
    mirror = tmp_path / "lustro"
    freeze = start_benchmark(
        "freeze",
        "--commit",
        "HEAD",
        "--scenario",
        "maly-tydzien",
        "--templates-dir",
        str(write_templates(tmp_path / "wzorce")),
        "--config",
        str(write_mapping(tmp_path / tool_files.WORKER_CONFIG.name)),
        "--mirror-dir",
        str(mirror),
        "--reference-dir",
        str(tmp_path / "referencje"),
    )
    try:
        assert wait_for(lambda: bool(_settlement_runs(mirror)), 120), "freeze nie uruchomił Przebiegu rozliczeń"
        [(pid, command)] = _settlement_runs(mirror).items()
        copy = Path(re.findall(r"(\S+)/tools/uruchom_proces\.py", command)[0])
        if sys.platform != "win32":
            os.kill(pid, signal.SIGSTOP)

        freeze.kill()
        freeze.wait(timeout=20)
        wait_for(lambda: not _settlement_runs(mirror) and not copy.exists(), 20)

        assert (_settlement_runs(mirror), copy.exists()) == ({}, False)
    finally:
        freeze.kill()
        freeze.wait()
        for pid in _settlement_runs(mirror):
            if sys.platform != "win32":
                os.kill(pid, signal.SIGKILL)
