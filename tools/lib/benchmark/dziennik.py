"""Dziennik pomiarów (JSONL), komentarz Markdown do issue-dziennika wspinaczki i straż czasu w CI."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from benchmark import BenchmarkError
from benchmark.lustro import SCENARIOS


# Cele wspinaczki na Macu (spec #141): mediana czasu ściany typowego tygodnia.
HARD_GOAL_MS = 18_000


AMBITIOUS_GOAL_MS = 6_000


TO_FILL = "_Do uzupełnienia._"


# Czas ściany i jego części w kolejności; rekordy sprzed podziału nie mają startu ani zakończenia procesu.
WALL_PARTS = (
    ("Czas ściany", "wall_ms"),
    ("Start procesu", "start_procesu_ms"),
    ("Czas uruchomienia", "czas_uruchomienia_ms"),
    ("Zakończenie procesu", "zakonczenie_procesu_ms"),
)


def append_record(journal: Path, record: Mapping[str, Any]) -> None:
    journal.parent.mkdir(parents=True, exist_ok=True)
    with journal.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_journal(journal: Path) -> list[dict[str, Any]]:
    if not journal.is_file():
        raise BenchmarkError(f"Brak dziennika {journal}; najpierw uruchom measure.")
    return [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines() if line.strip()]


def _matches(record: Mapping[str, Any], reference: str | None) -> bool:
    return reference is None or str(record.get("git_sha") or "").startswith(reference)


def _pairs(
    records: Sequence[Mapping[str, Any]], before: str | None, after: str | None
) -> list[tuple[Mapping[str, Any] | None, Mapping[str, Any]]]:
    """Dla każdego scenariusza na każdej maszynie: ostatni rekord ``after`` i rekord przed nim (albo ostatni ``before``).

    Czasy z różnych maszyn nie są porównywalne, więc „przed” pochodzi zawsze z tej samej maszyny co „po”.
    """

    order = {name: index for index, name in enumerate(dict.fromkeys([*SCENARIOS, *(r["scenario"] for r in records)]))}
    groups = sorted(
        dict.fromkeys((record["scenario"], record.get("machine")) for record in records),
        key=lambda group: order[group[0]],
    )
    pairs: list[tuple[Mapping[str, Any] | None, Mapping[str, Any]]] = []
    for scenario, machine in groups:
        history = [record for record in records if (record["scenario"], record.get("machine")) == (scenario, machine)]
        after_indices = [index for index, record in enumerate(history) if _matches(record, after)]
        if not after_indices:
            continue
        after_index = after_indices[-1]
        if before is None:
            earlier = history[after_index - 1] if after_index > 0 else None
        else:
            candidates = [
                record for index, record in enumerate(history) if index != after_index and _matches(record, before)
            ]
            earlier = candidates[-1] if candidates else None
        pairs.append((earlier, history[after_index]))
    return pairs


def _heading(record: Mapping[str, Any]) -> str:
    return f"{record['scenario']} ({record.get('machine')})"


def spread_text(spread: Mapping[str, int] | None) -> str:
    return "—" if spread is None else f"{spread['mediana']} ({spread['min']}–{spread['max']})"


def _commit_text(record: Mapping[str, Any] | None) -> str:
    if record is None:
        return "brak pomiaru"
    sha = str(record.get("git_sha") or "nieznany")[:7]
    return f"`{sha}`" + (" + niezacommitowane zmiany" if record.get("dirty") else "")


def oracle_text(oracle: object) -> str:
    if not isinstance(oracle, Mapping):
        return "nie sprawdzono"
    total = sum(oracle["roznice"].values())
    return f"{oracle['wynik']} ({total} różnic)" if total else str(oracle["wynik"])


def _oracle_section(record: Mapping[str, Any]) -> list[str]:
    oracle = record.get("oracle")
    if not isinstance(oracle, Mapping):
        return [f"### {_heading(record)}", "", "Nie sprawdzono: brak zamrożonego wyniku referencyjnego.", ""]
    return [
        f"### {_heading(record)}",
        "",
        f"**{oracle['wynik']}** z wynikiem referencyjnym `{str(oracle['referencja'])[:7]}`.",
        "",
        "| Kategoria | Różnice |",
        "|---|---:|",
        *(f"| {category} | {count} |" for category, count in oracle["roznice"].items()),
        "",
    ]


def _improvement(before: Mapping[str, Any], after: Mapping[str, Any]) -> str:
    """Poprawa liczy się tylko wtedy, gdy mediana jest szybsza o więcej niż rozrzut min–max (spec #141)."""

    gain = before["wall_ms"]["mediana"] - after["wall_ms"]["mediana"]
    noise = max(spread["max"] - spread["min"] for spread in (before["wall_ms"], after["wall_ms"]))
    direction = f"krótsza o {gain} ms" if gain >= 0 else f"dłuższa o {-gain} ms"
    verdict = "tak" if gain > noise else "nie"
    return f"Poprawa czasu ściany: **{verdict}** (mediana {direction}, największy rozrzut min–max {noise} ms)."


def _measurement_table(before: Mapping[str, Any] | None, after: Mapping[str, Any]) -> list[str]:
    def row(label: str, value: Any) -> str:
        return f"| {label} | {value(before) if before is not None else '—'} | {value(after)} |"

    def text(key: str) -> Any:
        return lambda record: record.get(key)

    lines = [
        "| | Przed | Po |",
        "|---|---:|---:|",
        row("Rozpoczęto", text("started_at")),
        row("Commit", lambda record: f"`{record.get('git_sha') or 'nieznany'}`"),
        row("Niezacommitowane zmiany", lambda record: {True: "tak", False: "nie"}.get(record.get("dirty"), "?")),
        row("Maszyna", text("machine")),
        row("Uruchomienia", text("runs")),
        *(
            row(f"{label} [ms]", lambda record, key=key: spread_text(record.get(key)))
            for label, key in WALL_PARTS
        ),
    ]
    phases = dict.fromkeys([*(before or {}).get("phase_durations_ms", {}), *after["phase_durations_ms"]])
    for phase in phases:
        lines.append(
            row(f"{phase} [ms]", lambda record, phase=phase: spread_text(record["phase_durations_ms"].get(phase)))
        )
    counters = dict.fromkeys([*(before or {}).get("counters", {}), *after["counters"]])
    for counter in counters:
        lines.append(row(f"`{counter}`", lambda record, counter=counter: record["counters"].get(counter, "—")))
    lines.append(row("Bramka poprawności", lambda record: oracle_text(record.get("oracle"))))
    return lines


def _next_step(pairs: Sequence[tuple[Mapping[str, Any] | None, Mapping[str, Any]]]) -> str:
    typical = next((after for _, after in pairs if after["scenario"] == "typowy-tydzien"), None)
    goals = (
        f"Cel twardy: mediana czasu ściany typowego tygodnia ≤ {HARD_GOAL_MS} ms na Macu; "
        f"cel ambitny ≤ {AMBITIOUS_GOAL_MS} ms."
    )
    if typical is None:
        return f"{goals} Brak pomiaru typowego tygodnia."
    median = typical["wall_ms"]["mediana"]
    if median <= AMBITIOUS_GOAL_MS:
        status = "cel ambitny osiągnięty"
    elif median <= HARD_GOAL_MS:
        status = f"cel twardy osiągnięty, do ambitnego brakuje {median - AMBITIOUS_GOAL_MS} ms"
    else:
        status = f"do celu twardego brakuje {median - HARD_GOAL_MS} ms"
    return f"{goals} Teraz {median} ms na maszynie `{typical['machine']}`: {status}."


def render_comment(records: Sequence[Mapping[str, Any]], before: str | None = None, after: str | None = None) -> str:
    """Komentarz do issue-dziennika w stałym układzie; Hipotezę i Decyzję dopisuje człowiek albo agent."""

    pairs = _pairs(records, before, after)
    if not pairs:
        raise BenchmarkError("W dzienniku nie ma rekordu pasującego do --after.")
    lines = ["## Hipoteza", "", TO_FILL, "", "## Zmiana", ""]
    lines += [f"- {_heading(after)}: {_commit_text(before)} → {_commit_text(after)}" for before, after in pairs]
    lines += ["", "## Pomiar", ""]
    for earlier, later in pairs:
        lines += [f"### {_heading(later)}", "", *_measurement_table(earlier, later), ""]
        if earlier is not None:
            lines += [_improvement(earlier, later), ""]
    lines += ["## Bramka poprawności", ""]
    for _, later in pairs:
        lines += _oracle_section(later)
    lines += ["## Decyzja", "", TO_FILL, "", "## Następny krok", "", _next_step(pairs), ""]
    return "\n".join(lines)


def guard_summary(record: Mapping[str, Any], budget_ms: int) -> tuple[str, bool]:
    """Podsumowanie ostatniego pomiaru do joba CI i to, czy mediana czasu ściany mieści się w budżecie."""

    median = record["wall_ms"]["mediana"]
    within = median <= budget_ms
    verdict = "w budżecie" if within else f"ponad budżetem o {median - budget_ms} ms"
    lines = [
        f"### Czas Przebiegu rozliczeń: {record['scenario']}",
        "",
        "| | mediana (min–max) [ms] |",
        "|---|---:|",
        *(f"| {label} | {spread_text(record[key])} |" for label, key in WALL_PARTS if key in record),
        *(f"| {phase} | {spread_text(spread)} |" for phase, spread in record["phase_durations_ms"].items()),
        "",
        f"{_commit_text(record)}, maszyna `{record['machine']}`, uruchomienia: {record['runs']}.",
        "",
        f"Budżet mediany czasu ściany: {budget_ms} ms. Wynik: **{verdict}**.",
        "",
    ]
    return "\n".join(lines), within
