"""Mierzy czas Przebiegu rozliczeń (measure) na lustrze folderów taty, bez danych klientów; użyj przed i po zmianie wydajności silnika.

Użycie (z katalogu repozytorium):

    python tools/benchmark_przebiegu.py freeze --scenario typowy-tydzien --commit SHA
    python tools/benchmark_przebiegu.py measure --scenario typowy-tydzien --machine mac-m4max [--reference SHA]
    python tools/benchmark_przebiegu.py comment [--before SHA] [--after SHA]
    python tools/benchmark_przebiegu.py guard --budget-ms MS [--summary PLIK]

Z syntetycznymi Wzorcami (bez Wzorców taty, jak w CI):

    python tools/syntetyczne_wzorce.py .benchmark/syntetyczne-wzorce
    python tools/benchmark_przebiegu.py measure --templates-dir .benchmark/syntetyczne-wzorce \\
        --config .benchmark/syntetyczne-wzorce/worker_mapping.yaml --machine mac-m4max-syntetyczne

``measure`` buduje lustro folderów taty (albo używa istniejącego), uruchamia na nim
Przebieg rozliczeń 3 razy jako osobny proces Pythona przez skrypt dla maszyn
(``tools/uruchom_proces.py settlement``), sprawdza bramkę poprawności i dopisuje rekord
pomiaru do dziennika JSONL w ``.benchmark/`` (poza gitem). ``comment`` drukuje z dziennika komentarz Markdown do issue-dziennika
wspinaczki (spec #141); „przed” i „po” to zawsze ten sam scenariusz na tej samej maszynie.
``guard`` to straż czasu w CI: opisuje ostatni pomiar dziennika w Markdown i kończy się
kodem 1 tylko wtedy, gdy mediana czasu ściany przekracza budżet.

``measure`` trzyma maszynę jak pomiar ``wydajnosc`` weryfikacji Centrum
(``tools/quiet_machine.py``): czeka najwyżej 3 minuty na cichy procesor i mierzy sam, a
inne weryfikacje Centrum i ``freeze`` czekają, dopóki mierzy, najwyżej 15 minut. ``freeze``
obciąża procesor, więc zajmuje maszynę jak każdy inny przebieg. Wewnątrz obie komendy trzymają wyłączną
blokadę pliku obok folderu wyników referencyjnych (``--reference-dir`` ``reference`` →
``reference.lock``): pomiary ze wspólnym folderem, np. oficjalne pomiary z kilku worktree,
nigdy nie biegną naraz. Czekanie na maszynę opisują linie ``MASZYNA ZAJĘTA | …``, na
blokadę pliku linia na stderr.

``freeze`` zamraża wynik referencyjny scenariusza z commita, który ma skrypt dla maszyn:
buduje ten commit w tymczasowym worktree gita poza repozytorium, uruchamia jego Przebieg
rozliczeń raz na tym samym lustrze i zapisuje Folder rozliczeń pracowników, liczniki i
wynik JSON skryptu w ``.benchmark/reference/<lustro>-wzorzec-<odcisk>/<commit>/``, gdzie
odcisk to skrót Wzorca rozliczenia pracownika: lustro od niego nie zależy, a wynik
zamrożony z jednym Wzorcem nie może być porównany z pomiarem na innym (pomiar z
``--reference`` bez pasującego wyniku kończy się błędem). Bramka poprawności w
``measure`` porównuje z nim Folder rozliczeń pracowników ostatniego uruchomienia
(``tools/porownanie_rozliczen.py``), liczniki, kody Komunikatów (ostrzeżenia i
Zatrzymanie) i podsumowanie z karty Uruchomienia z wyniku JSON. Rekord i komentarz mają
tylko liczbę różnic w kategorii. Wyniki referencyjne sprzed przejścia benchmarku na
skrypt mają linie terminala zamiast wyniku JSON: trzeba je zamrozić od nowa, a pomiar z
takim wynikiem kończy się błędem z poleceniem ponownego zamrożenia.

Lustro to ``Załączniki/Rozliczenia 2026/10_Październik_2026/INEA/06_12_10_2026`` z
Plikiem zbiorczym, który Przygotowanie pliku zbiorczego (``tools/uruchom_proces.py
preparation``) tworzy z deterministycznego, syntetycznego Rejestru zleceń. Wykonawcy
pochodzą z Konfiguracji wykonawców; adresy i numery są fikcyjne. Potem benchmark wpisuje w każdy
Wiersz danych Pliku zbiorczego syntetyczne ilości w ``N:AP``, a w część z nich
obciążenia i uwagi w ``AQ:AT``, tak jak tata przed Przebiegiem. Plik zbiorczy lustra to
więc wynik Przygotowania pliku zbiorczego (dane wejściowe ``A:K``) plus syntetyczne wpisy
w ``N:AT``, które tata uzupełnia w Excelu między oboma procesami. Wzorce są brane z folderu
``--templates-dir`` pod nazwami, pod którymi leżą w ``config``; domyślnie z ``config``
tego checkoutu, a gdy ich tam nie ma (świeży worktree), z ``config`` głównego checkoutu.
Tak samo domyślna Konfiguracja wykonawców (``--config``): prawdziwy
``config/worker_mapping.yaml`` jest poza gitem (w repozytorium jest tylko
``worker_mapping.example.yaml``), więc benchmark szuka go w tym checkoucie, a potem w
głównym.

Czas ściany każdego uruchomienia dzieli się na trzy części: start procesu (od uruchomienia
procesu Pythona do startu silnika: interpreter, importy, argumenty, wejście procesu;
koniec to ``started_at`` rekordu metryk procesu), ``Czas uruchomienia`` (silnik, z rekordu
metryk) i zakończenie procesu (reszta: rekord metryk, wynik JSON, wyjście z interpretera).
Proces nie mierzy niczego dodatkowo.
Rekordy dziennika sprzed tego podziału nie mają pól startu i zakończenia; komentarz
pokazuje dla nich „—”.

Benchmark nie czyta ani nie zmienia Ustawień taty i nie dopisuje rekordów do historii
metryk w repozytorium. Na wyjście, do dziennika i do komentarza trafiają tylko liczby,
nazwy scenariuszy, commit i maszyna: nigdy Wykonawcy, adresy, numery zleceń ani wiersze.
"""

from __future__ import annotations

import argparse
import os
import platform
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

from benchmark import DEFAULT_DIRECTORY, BenchmarkError
from benchmark.dziennik import (
    WALL_PARTS,
    append_record,
    guard_summary,
    oracle_text,
    read_journal,
    render_comment,
    spread_text,
)
from benchmark.lustro import SCENARIOS, default_templates_directory, default_worker_config, ensure_mirror, template_paths
from benchmark.pomiar import RUNS, exclusive_measurement, measure, measurement_lock
from benchmark.referencja import find_reference, freeze_reference, reference_folder
from quiet_machine import MachineBusy, QuietMachine
from syntetyczne_wzorce import WORKER_TEMPLATE


def _default_machine() -> str:
    return f"{platform.system()}-{platform.machine()}".lower()


def _machine() -> QuietMachine:
    """Maszyna tego komputera; testy podają w ``QUIET_MACHINE_SCRATCH`` własny folder blokad bez ``ps``."""

    scratch = os.environ.get("QUIET_MACHINE_SCRATCH")
    return QuietMachine() if scratch is None else QuietMachine(Path(scratch), busy_processes=lambda: [])


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    measure_parser = commands.add_parser("measure", help="Zbuduj lustro (jeśli go brak) i zmierz scenariusz.")
    freeze_parser = commands.add_parser("freeze", help="Zamroź wynik referencyjny scenariusza z commita.")
    for mirror_parser in (measure_parser, freeze_parser):
        mirror_parser.add_argument("--scenario", choices=list(SCENARIOS), default="typowy-tydzien")
        mirror_parser.add_argument("--templates-dir", type=Path, help="Folder z trzema Wzorcami (nazwy jak w config).")
        mirror_parser.add_argument(
            "--config", type=Path, help="Konfiguracja wykonawców; domyślnie config/worker_mapping.yaml jak Wzorce."
        )
        mirror_parser.add_argument("--mirror-dir", type=Path, default=DEFAULT_DIRECTORY / "lustro")
        mirror_parser.add_argument("--reference-dir", type=Path, default=DEFAULT_DIRECTORY / "reference")
    freeze_parser.add_argument("--commit", required=True, help="Commit, z którego powstaje wynik referencyjny.")
    measure_parser.add_argument("--journal", type=Path, default=DEFAULT_DIRECTORY / "przebieg.jsonl")
    measure_parser.add_argument("--machine", default=_default_machine(), help="Np. mac-m4max albo tata-i7.")
    measure_parser.add_argument(
        "--reference", help="Commit (prefiks) wyniku referencyjnego; domyślnie jedyny zamrożony dla lustra."
    )
    comment_parser = commands.add_parser("comment", help="Wydrukuj komentarz Markdown z dziennika.")
    comment_parser.add_argument("--journal", type=Path, default=DEFAULT_DIRECTORY / "przebieg.jsonl")
    comment_parser.add_argument("--before", help="Commit (prefiks) pomiaru „przed”; domyślnie poprzedni rekord.")
    comment_parser.add_argument("--after", help="Commit (prefiks) pomiaru „po”; domyślnie ostatni rekord.")
    guard_parser = commands.add_parser(
        "guard", help="Opisz ostatni pomiar dziennika i zakończ kodem 1, gdy mediana czasu ściany przekracza budżet."
    )
    guard_parser.add_argument("--journal", type=Path, default=DEFAULT_DIRECTORY / "przebieg.jsonl")
    guard_parser.add_argument("--budget-ms", type=int, required=True)
    guard_parser.add_argument("--summary", type=Path, help="Plik, do którego dopisać podsumowanie (np. job CI).")
    return parser


def _guard(journal: Path, budget_ms: int, summary_path: Path | None) -> int:
    records = read_journal(journal)
    if not records:
        raise BenchmarkError(f"Dziennik {journal} jest pusty; najpierw uruchom measure.")
    summary, within = guard_summary(records[-1], budget_ms)
    print(summary, end="")
    if summary_path is not None:
        with summary_path.open("a", encoding="utf-8") as stream:
            stream.write(summary)
    return 0 if within else 1


def _measure_or_freeze(args: argparse.Namespace, references: Path) -> dict[str, Any] | None:
    templates = template_paths((args.templates_dir or default_templates_directory()).expanduser().resolve())
    config = (args.config or default_worker_config()).expanduser().resolve()
    mirror, built = ensure_mirror(args.mirror_dir.expanduser().resolve(), args.scenario, config, templates)
    print(f"Lustro {'zbudowane' if built else 'istniejące'}: {mirror}", flush=True)
    if args.command == "freeze":
        frozen = freeze_reference(references, mirror, args.commit, config, templates[WORKER_TEMPLATE])
        print(f"Wynik referencyjny {args.scenario} z commita {frozen.name[:7]}: {frozen}")
        return None
    reference = find_reference(references, mirror, templates[WORKER_TEMPLATE], args.reference)
    if reference is None:
        folder = reference_folder(references, mirror, templates[WORKER_TEMPLATE])
        print(
            f"Brak wyniku referencyjnego dla tego lustra i Wzorca rozliczenia pracownika w {folder}; "
            "bramka poprawności nie sprawdzona."
        )
    record = measure(mirror, args.scenario, config, templates[WORKER_TEMPLATE], args.machine, reference)
    append_record(args.journal, record)
    return record


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "comment":
            print(render_comment(read_journal(args.journal), args.before, args.after), end="")
            return 0
        if args.command == "guard":
            return _guard(args.journal, args.budget_ms, args.summary)
        references = args.reference_dir.expanduser().resolve()
        machine = _machine()
        hold = machine.measurement() if args.command == "measure" else machine.run()
        with hold as waited:
            if waited >= 1:
                print(f"MASZYNA WOLNA | czekano {waited:.0f} s", flush=True)
            with exclusive_measurement(measurement_lock(references)):
                record = _measure_or_freeze(args, references)
    except (BenchmarkError, MachineBusy) as error:
        print(f"Benchmark przerwany: {error}", file=sys.stderr)
        return 1
    if record is None:
        return 0
    parts = ", ".join(f"{label} {spread_text(record[key])} ms" for label, key in WALL_PARTS)
    print(
        f"{args.scenario}: {parts} (mediana (min–max) z {RUNS} uruchomień), "
        f"bramka poprawności: {oracle_text(record['oracle'])}. Rekord w {args.journal}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
