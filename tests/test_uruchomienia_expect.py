"""Uruchomienia procesów jako tekst w ``tests/expected/uruchomienia/``: to, co tata widzi na karcie Uruchomienia.

Każdy scenariusz syntetyczny weryfikacji różnicowej (``tools/rownowaznosc.py``) biegnie raz, tym samym sposobem i z tą
samą maską czasów, chwil i folderów co tam, skryptem dla maszyn ``tools/uruchom_proces.py``. Plik procesu ma na
scenariusz: wynik, etapy postępu w kolejności, liczby postępu i podsumowania, ostrzeżenia, Zatrzymanie z kodem i
trzema częściami Komunikatu, uwagi techniczne oraz pliki, które Uruchomienie utworzyło albo zmieniło (nazwy względne).
Zmiana zachowania procesu zmienia ten plik w tym samym PR, więc diff PR pokazuje ją obok zmiany kodu. Nowe pole wyniku,
także w obiekcie zagnieżdżonym (Zatrzymanie, Komunikat, ``runs_contract.Progress``), daje porażkę, dopóki nie trafi do
``SHOWN`` i pliku albo do ``HIDDEN``. Treść skoroszytów porównuje ``tools/rownowaznosc.py`` i testy zapisu, nie ten
plik.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.fixtures.expect import assert_expected
from tests.fixtures.rownowaznosc import rownowaznosc

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "uruchom_proces.py"
EXPECTED: dict[rownowaznosc.Process, tuple[str, Path]] = {
    "settlement": ("Przebieg rozliczeń", ROOT / "tests" / "expected" / "uruchomienia" / "przebieg-rozliczen.txt"),
    "preparation": ("Przygotowanie pliku zbiorczego", ROOT / "tests" / "expected" / "uruchomienia" / "przygotowanie-pliku-zbiorczego.txt"),
    "intermax": ("Uporządkowanie INTERMAX", ROOT / "tests" / "expected" / "uruchomienia" / "uporzadkowanie-intermax.txt"),
}
# Pola każdego obiektu wyniku skryptu dla maszyn po jego ścieżce (``[]``: element listy), które plik pokazuje.
SHOWN = {
    "": {"result", "summary", "warnings", "stop", "progress", "technical_notes"},
    "progress": {"phases", "template_total", "templates_completed", "current_worker", "figures"},
    "progress.phases[]": {"phase", "state"},
    "progress.figures[]": {"label", "value"},
    "summary": {"figures", "counts", "files", "worker_settlements", "intermax_copy"},
    "summary.figures[]": {"label", "value"},
    "summary.counts": {"title", "counts"},
    "summary.counts.counts[]": {"label", "count"},
    "summary.files[]": {"name", "kind"},
    "summary.worker_settlements[]": {"worker", "file", "orders", "empty"},
    "warnings[]": {"code", "what", "where", "action"},
    "stop": {"kind", "message"},
    "stop.message": {"code", "what", "where", "action"},
}
# Pola, których plik nie pokazuje: czas Uruchomienia widać tylko na stronie Metryki, zapisu metryk nie ma w kontrakcie
# Centrum, czas etapu zmienia się między przebiegami, a jednostką liczby karta tylko formatuje wartość (czas ma w
# pliku maskę <CZAS>). Krok Zapisywania ma tylko Wycena w efenix, która nie ma tu scenariusza (Atrapa efenix potrzebuje
# przeglądarki; jej kroki sprawdza ``tests/test_wycena_efenix.py``), a to, czy zero kafelka ostrzega, jest tylko wyglądem.
HIDDEN = {
    "": {"total_duration_ms", "metrics_saved"},
    "progress": {"step"},
    "summary.counts": {"zero_warns"},
    "progress.phases[]": {"duration_ms"},
    "progress.figures[]": {"unit"},
    "summary.figures[]": {"unit"},
}
PARTS = (("what", "Co się stało"), ("where", "Gdzie"), ("action", "Co zrobić"))


def _objects(value: object, path: str = "") -> Iterator[tuple[str, dict[str, Any]]]:
    """Każdy obiekt wyniku z jego ścieżką (``stop.message``, ``progress.phases[]``), także zagnieżdżony."""

    if isinstance(value, dict):
        yield path, value
        for key, inner in value.items():
            yield from _objects(inner, f"{path}.{key}" if path else key)
    elif isinstance(value, list):
        for inner in value:
            yield from _objects(inner, f"{path}[]")


def _new_fields(result: dict[str, Any]) -> list[str]:
    """Pola obiektów wyniku spoza ``SHOWN`` i ``HIDDEN`` oraz pola ``SHOWN`` i ``HIDDEN``, których obiekt nie ma."""

    return sorted(
        f"{path}.{field}" if path else field
        for path, fields in _objects(result)
        for field in set(fields) ^ (SHOWN.get(path, set()) | HIDDEN.get(path, set()))
    )


def _message(message: dict[str, str], indent: str) -> list[str]:
    return [f"{indent}{label}: {message[part]}" for part, label in PARTS]


def _figures(title: str, figures: list[dict[str, Any]]) -> list[str]:
    return [f"{title}:", *(f"  {figure['label']}: {figure['value']}" for figure in figures)] if figures else [f"{title}: brak"]


def _summary(summary: dict[str, Any] | None) -> list[str]:
    if summary is None:
        return ["Podsumowanie: brak"]
    lines = _figures("Podsumowanie", summary["figures"])
    counts = summary["counts"]
    if counts is not None:
        lines += [f"{counts['title']}:", *(f"  {count['label']}: {count['count']}" for count in counts["counts"])]
    lines += [f"Plik okresu: {file['name']} ({file['kind']})" for file in summary["files"]]
    for settlement in summary["worker_settlements"] or []:
        empty = ", pusty" if settlement["empty"] else ""
        lines.append(f"Rozliczenie pracownika: {settlement['worker']} | {settlement['file']} | zlecenia {settlement['orders']}{empty}")
    if summary["intermax_copy"] is not None:
        lines.append(f"Kopia INTERMAX: {summary['intermax_copy']}")
    return lines


def _files(outcome: rownowaznosc.Outcome, inputs: Path) -> list[str]:
    before = rownowaznosc.files(inputs)
    after = rownowaznosc.files(outcome.folder)
    lines = [
        f"  {'zmieniony' if name in before else 'nowy'}: {name}"
        for name, path in after.items()
        if name not in before or path.read_bytes() != before[name].read_bytes()
    ]
    lines += [f"  usunięty: {name}" for name in before.keys() - after.keys()]
    return ["Pliki wynikowe:", *sorted(lines)] if lines else ["Pliki wynikowe: brak"]


def _card(name: str, outcome: rownowaznosc.Outcome, inputs: Path) -> str:
    """Karta Uruchomienia scenariusza ``name`` jako tekst."""

    result = outcome.result
    assert isinstance(result, dict), f"{name}: skrypt dla maszyn nie dał JSON (kod {outcome.code})"
    assert not (fields := _new_fields(result)), f"{name}: pola wyniku {fields} trafiają do SHOWN i pliku albo do HIDDEN"
    progress = result["progress"]
    lines = [f"=== {name} ===", f"Wynik: {result['result']}", "Etapy:"]
    lines += [f"  {phase['phase']}: {phase['state']}" for phase in progress["phases"]] or ["  brak"]
    if progress["template_total"]:
        current = f", teraz {progress['current_worker']}" if progress["current_worker"] else ""
        lines.append(f"Szablony pracowników: {progress['templates_completed']} z {progress['template_total']}{current}")
    lines += _figures("Liczby postępu", progress["figures"])
    lines += _summary(result["summary"])
    lines += ["Ostrzeżenia:" if result["warnings"] else "Ostrzeżenia: brak"]
    for warning in result["warnings"]:
        lines += [f"  {warning['code']}", *_message(warning, "    ")]
    stop = result["stop"]
    lines += ["Zatrzymanie: brak"] if stop is None else [f"Zatrzymanie ({stop['kind']}): {stop['message']['code']}", *_message(stop["message"], "  ")]
    notes = result["technical_notes"]
    lines += ["Uwagi techniczne:", *(f"  {note}" for note in notes)] if notes else ["Uwagi techniczne: brak"]
    return "\n".join([*lines, *_files(outcome, inputs)]) + "\n"


@pytest.mark.parametrize("process", sorted(EXPECTED))
def test_uruchomienie_kazdego_scenariusza_procesu_pokazuje_na_karcie_to_co_w_pliku_expect(process: rownowaznosc.Process, tmp_path: Path) -> None:
    title, expected = EXPECTED[process]
    cards = [f"# {title}: karta Uruchomienia każdego scenariusza z tools/rownowaznosc.py, bez czasów, chwil i folderów.\n# Plik zapisuje tests/test_uruchomienia_expect.py.\n"]
    for scenario in rownowaznosc.SCENARIOS:
        if scenario.process == process:
            inputs = tmp_path / "wejscia" / scenario.name
            arguments = rownowaznosc.built(scenario, inputs)
            outcome = rownowaznosc.run(SCRIPT.parents[1], scenario, arguments, inputs, tmp_path / "strona")
            cards.append(_card(scenario.name, outcome, inputs))

    assert_expected("\n".join(cards), expected)
