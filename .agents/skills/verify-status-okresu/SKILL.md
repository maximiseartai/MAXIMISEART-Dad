---
name: verify-status-okresu
description: Exhaustively check, on the real code and a real temporary folder, that every consumer of the Status okresu reads one Folder okresu the same way, for every state of its files (each period file present or not, readable or not) - Tablica okresów and its steps, the start cards of Przygotowanie, Przebieg rozliczeń and Wycena w efenix, Uzupełnienie (`settled`), Wpisanie raportów (`report_entering._closed`) and the Sprawdzanie of Przygotowanie and Przebieg rozliczeń (`ensure_period_files_absent`, `ensure_worker_settlements_absent`). Use when a change touches `PeriodFolderObservation` or `PeriodFolder.observe` in `src/rozliczenia/period_folder.py`, `_closed` in `report_entering.py`, `_settled` in `centrum/filling.py`, `quantities_to_fill.py`, `_steps` or `read_board` in `centrum/period_board.py`, the choosers in `centrum/period_start.py` or `centrum/processes/`, `check_preparation` or `check_settlement` in `input_checks.py`, the two guards, or when `explore_status_okresu.py` fails.
pilnuje:
  - src/rozliczenia/period_folder.py
  - src/rozliczenia/file_state.py
  - src/rozliczenia/report_entering.py
  - src/rozliczenia/worker_reports/_model.py
  - src/rozliczenia/quantities_to_fill.py
  - src/rozliczenia/preparation_files.py
  - src/rozliczenia/settlement_files.py
  - src/rozliczenia/input_checks.py
  - src/rozliczenia/centrum/app.py
  - src/rozliczenia/centrum/filling.py
  - src/rozliczenia/centrum/period_board.py
  - src/rozliczenia/centrum/period_start.py
  - src/rozliczenia/centrum/process_kind.py
  - src/rozliczenia/centrum/processes/preparation.py
  - src/rozliczenia/centrum/processes/settlement.py
  - src/rozliczenia/centrum/processes/efenix.py
  - tools/lib/atrapy/pliki_taty.py
  - tools/lib/atrapy/preparation.py
  - tools/lib/atrapy/settlement.py
  - tools/lib/atrapy/skrzynka_raportow.py
  - tools/lib/eksplorator.py
  - tools/lib/rozjazd_modelu.py
ci: .agents/skills/verify-status-okresu/scripts/explore_status_okresu.py
---

# Verify Status okresu

## What CI runs and what stays local

CI runs `explore_status_okresu.py` (the `ci:` key) in Mutation checks whenever a change touches a file in `pilnuje:`
or this skill's folder, and `check_status_okresu_mutations.py` in full CI on `main` and nightly on `main`
(`mutacje-nocne.yml`).
Run them locally only to reproduce a red CI step or the night's issue, or while you work on one consumer.
What stays with you: „Does the change touch it?” (a new consumer of the Status okresu that the check does not ask
escapes it), bringing the reference in line when the drift says so, and sorting a red run as „When the check fails”
says.

## The promise

- **OTWARCIE**: for every state of the Folder okresu, each process lets itself act on the period exactly when the
  Status okresu allows it: Przygotowanie pliku zbiorczego and Wpisanie raportów only in „Brak plików okresu”,
  Przebieg rozliczeń and Uzupełnienie only in „Plik zbiorczy przygotowany”. Tablica okresów offers a step only where
  its process will act. A consumer that cannot read the folder says so instead of answering, and says so only when
  something in the folder cannot be read.
  Harm: Dad sees „Okres zamknięty” while Wpisanie raportów writes into that period's days of INTERMAX, or Przygotowanie
  writes a new Plik zbiorczy into a period that already has Rozliczenia pracowników, or the board offers a start that
  stops.
- **TA_SAMA_NAZWA**: every consumer that shows Dad a Status okresu (Tablica okresów, the start cards of Przygotowanie,
  Przebieg rozliczeń and Wycena w efenix, Uzupełnienie through `settled`) shows the same one, also for a state that
  should not happen (Rozliczenia pracowników without a Plik zbiorczy, the Rozliczenie wewnętrzne left by ADR 0005).
  Harm: two screens of Centrum tell Dad two different stages of the same period.

The reference Status okresu is the checker's own (`reference` in `explore_status_okresu.py`), from what it built and
`GLOSSARY.md`: a Folder rozliczeń pracowników makes „Rozliczenia pracowników gotowe” and the period closed, else a Plik
zbiorczy makes „Plik zbiorczy przygotowany”, else „Brak plików okresu”. `GLOSSARY.md` names Rozliczenia pracowników
without a Plik zbiorczy twice in „Status okresu” (no Plik zbiorczy, and a Folder rozliczeń pracowników); „Droga okresu”
settles it („Okres z Rozliczeniami pracowników jest zamknięty”), and `PeriodFolderObservation.status` decides the same.

## Does the change touch it?

The check asks every consumer through its public entry point: `create_app` over HTTP for Tablica okresów
(`/api/periods`), the start cards (`/api/runs/setup`) and Uzupełnienie (`/api/periods/{token}/quantities-to-fill`),
`report_entering.enter_from_mail` for Wpisanie raportów, and `input_checks.check_preparation` and
`input_checks.check_settlement` for the starts.
Run it when a diff changes how any of them reads the Folder okresu or decides from it: `PeriodFolderObservation`,
`PeriodFolder.observe`, `_listing`, `_exists` and `reading` in `period_folder.py`, `path_taken` and `file_state` in
`file_state.py`, `_closed` and `read` in `report_entering.py`, `Window` in `worker_reports/_model.py`, `_settled` and
`read` in `centrum/filling.py`, `_steps`, `_path` and `read_board` in `centrum/period_board.py`, `_recent_choice` and the
`ByStatus` and `RecentWeeks` choosers, `ensure_period_files_absent`, `ensure_worker_settlements_absent`, and the order
of checks in `check_preparation` and `check_settlement`.
A new consumer of the Status okresu (Diagnoza, a new process with a period) is not asked until you add it to
`ask_all` with its line in `ALLOWED` or `NAMING`.

The part modelled by hand is the reference Status okresu, which mirrors `PeriodFolderObservation.status`; its digest
is in `model/definicje.json`.
When `status` changes, the Mutation checks step fails before it starts (line
`ROZJAZD MODELU Z KODEM | verify-status-okresu: …`), `explore_status_okresu.py` run by hand prints the drift as an
`UWAGA:` line above the verdict, and `tools/szybko.py` fails on the same drift before you push (step `rozjazd modelu`).

## Bring the model in line

When `PeriodFolderObservation.status` changes:

1. Read the diff: the drift line names the changed definition.
2. Decide which Status okresu each folder state has now, in the words of `GLOSSARY.md`, and change `reference` in
   `explore_status_okresu.py` to say it.
   If the change is the fix of a known finding, change `GLOSSARY.md` in the same change.
3. Run the check and `--strict`. A new violation is a finding: replay it on the code before you call it a bug.
4. Run `tools/przesun_model.py verify-status-okresu` only after `reference` describes the code, and write in the commit
   message what changed in it and why.

## Run

```powershell
py -3 .agents\skills\verify-status-okresu\scripts\explore_status_okresu.py
```

On macOS or Linux use `.venv/bin/python` instead of `py -3`.
It takes about 2 s on a Mac and needs nothing beyond the repo's `.venv`.
In a worktree the script checks the worktree's own `src`.
`--scope czytelne` or `--scope niedostepne` runs one scope; `--strict` counts known findings and accepted risks as
violations too.

The last line is the verdict:

| Last line | Exit | Meaning |
| --- | --- | --- |
| `STATUS OKRESU OK` | 0 | Both rules hold in every state. |
| `STATUS OKRESU OK, ZNANE USTALENIA: n, ZAAKCEPTOWANE RYZYKA: m` | 0 | Only the known findings and accepted risks below, each printed with its first state and every consumer's answer. A count of zero is left out. |
| `STATUS OKRESU: NOWE NARUSZENIE (n)` | 1 | A rule breaks in a way not listed below, or a consumer crashed (`WYJATEK`) or answered in a way the checker cannot read (`NIEOCZEKIWANA_ODPOWIEDZ`, for example a renamed Komunikat code). |
| `STATUS OKRESU: ZNALEZISKO ZNIKNĘŁO (n)` | 1 | A known finding or accepted risk did not show in a scope of its `after`. If a change fixed it, narrow or delete it in `KNOWN_FINDINGS` or `ACCEPTED_RISKS` and below. |
| `STATUS OKRESU: LUKA MODELU (n)` | 2 | The system does not take access away with `chmod` (Windows, or a run as root), so scope `niedostepne` did not run. No verdict on it. |

## How it works and what it covers

The question is whether, for each state of the Folder okresu on disk, all consumers say the same.
Its inputs are finite and small (presence and readability of each file), so the checker walks every state once, on
the real code and a real temporary folder, instead of a hand model (which would not see a consumer reading the folder
its own way) or Hypothesis (sampling a space it can cover whole).
Each state gets a fresh Centrum (`create_app`, without its lifespan) because Uzupełnienie keeps the last good read of
each Plik zbiorczy.
Wpisanie raportów is deployed on the period's Tuesday and runs the Wednesday after, so its window spans this period
and the next; its Skrzynka raportów refuses the password, so the click stops right after the window is set and the
day it reads from (`Window.first`) says whether the period is open for it.
The starts run the Sprawdzanie of each process on valid synthetic Wzorce, so only the Folder okresu decides.

| Scope | States of Folder okresu `08_14_09_2026` |
| --- | --- |
| `czytelne` (13) | no Folder okresu; a Folder okresu with or without Rozliczenie wewnętrzne, with or without Plik zbiorczy, without, with an empty or with a filled Folder rozliczeń pracowników |
| `niedostepne` (24) | as above, with the Plik zbiorczy or the Folder rozliczeń pracowników unreadable (`chmod 0`), and the Folder okresu itself unreadable |

There is no TLA+ model here, so `/statechart` does not apply: the order of events that leads to a state (Przebieg
rozliczeń, then Dad moves the Plik zbiorczy away) is one step, and the check covers the state whatever led to it.

Not covered: Dad's month layout with the Folder okresu in two months (`PeriodFolderLookupError`), a name taken by the
wrong kind of entry (a folder named like the Plik zbiorczy, a file named like the Folder rozliczeń pracowników), a
Plik zbiorczy open in Excel (a lock, not a Status okresu), unreadability that `chmod` does not model (OneDrive
placeholders, Windows sharing violations), Diagnoza, the start card's own refusals after a choice
(`PeriodStarts.prepare`), and anything after Sprawdzanie: the check does not run a whole process.

## Known findings

A known finding is a real defect in the current code. It is printed on every run until the code is fixed; when a code
change fixes it, the check ends with `ZNALEZISKO ZNIKNĘŁO`: delete its entry from `KNOWN_FINDINGS` and from this list.

1. **Wpisanie raportów w zamkniętym okresie** (OTWARCIE). The Folder okresu has a Folder rozliczeń pracowników and no
   Plik zbiorczy: Dad moved, renamed or deleted the Plik zbiorczy after Przebieg rozliczeń, or OneDrive renamed it in a
   conflict. `PeriodFolderObservation.status` says `worker_settlements_ready`, so Tablica okresów shows „Rozliczenia
   pracowników gotowe” and „Okres zamknięty”. `report_entering._closed` looks only at `collective_file_exists`, so
   `Window.first` is the period's Tuesday and Wpisanie raportów writes `SKUTECZNE` and `CZYNNOŚCI ZREALIZOWANE` into
   INTERMAX orders of the closed period. Replayed on 12 November 2026 with a whole `enter_from_mail` and a Raport
   wykonawcy from 9.09.2026: 2 cells written; with the Plik zbiorczy back, 0.
2. **Przygotowanie w zamkniętym okresie** (OTWARCIE). The Folder okresu has a Folder rozliczeń pracowników (readable or
   not) and neither period file. Tablica okresów offers no „Przygotuj plik zbiorczy”, but
   `ensure_period_files_absent` checks only the Rozliczenie wewnętrzne and the Plik zbiorczy, so the Sprawdzanie of
   Przygotowanie passes, and the karta startu Przygotowania lists the period (`RecentWeeks`). Uzupełnienie for that
   period says „Nie ma Pliku zbiorczego tego okresu. … najpierw przygotuj plik zbiorczy”. Replayed on 12 November 2026
   with `tools/uruchom_proces.py preparation`: the run ends `WYMAGA_SPRAWDZENIA` with a new Plik zbiorczy and
   Rozliczenie wewnętrzne next to the Folder rozliczeń pracowników.

An entry lives in `KNOWN_FINDINGS` of `explore_status_okresu.py` as an `Excuse` of `tools/lib/eksplorator.py` with its
shape (`StateShape`): the folder states exactly (`states`) and the consumers (`consumers`).
Each part has a broken variant just outside it in `BOUNDARIES` of `check_status_okresu_mutations.py`, which must give a
new violation; `tests/test_mutacje_skilli.py` reds an entry with a part without one.

## Accepted risks

1. **Samo Rozliczenie wewnętrzne** ([ADR 0005](../../../docs/adr/0005-przerwana-publikacja-plikow-okresu.md)). A
   publication cut short leaves only the Rozliczenie wewnętrzne. Tablica okresów shows „Brak plików okresu” and offers
   „Przygotuj plik zbiorczy”, and the Sprawdzanie of Przygotowanie stops on `PLIK_OKRESU_ISTNIEJE` naming the file;
   ADR 0005 accepts this stop and Dad's instructions say how to remove the file. Every other consumer treats the period
   as having no period files.

## When the check fails

Read the counterexample as a story: the first line is the Folder okresu, the second the reference Status okresu, and
each further line one consumer's answer in its own words (a step on the board, a Komunikat code, the day Wpisanie
raportów reads from).
Then sort it:

- **Real bug**: the state can happen to Dad, and a consumer acts, refuses or names a Status okresu against the rule.
  Replay it on the code (a whole process, as for the known findings above) and report it with the story. Fix the
  product code only if the user asks. If the user accepts the risk instead, record the decision in an ADR and add an
  entry to `ACCEPTED_RISKS` with its shape, `after`, its `BOUNDARIES` and a line under Accepted risks here.
- **Modelling error**: the reference is wrong for the state (read `GLOSSARY.md` again), the folder the checker built is
  not what the state says, or a Komunikat code in `UNREADABLE_STOPS` or a text the checker reads changed on purpose.
  Fix the checker, then rerun the mutations below.
- **LUKA MODELU**: the scope with unreadable files did not run; run it on macOS or Linux as a normal user.

Never narrow a rule, the reference or a scope to make a real counterexample disappear.

## After changing the checker or an intended change to the consumers

CI proves the check can still fail: the night on `main` runs the script below after a change of this skill's folder.
Run it locally only to reproduce a red Mutation checks step or the night's issue, or after you rewrite a mutation.
It applies the broken variants to a temporary copy of the checkout (`tools/lib/silnik_mutacji.py`), never to the
checkout:

```powershell
py -3 .agents\skills\verify-status-okresu\scripts\check_status_okresu_mutations.py
```

It must end with `MUTACJE OK`: a Status okresu that ignores an empty Folder rozliczeń pracowników, Uzupełnienie
deciding `settled` by the wrong Status okresu, Wpisanie raportów that closes no period, the karta Przebiegu rozliczeń
offering a closed period, an unreadable folder read as a missing one, and the karta Przygotowania naming every period
„Brak plików okresu” all give `NOWE NARUSZENIE`, and so do the `BOUNDARIES` variants: Wpisanie raportów closing a
period by its Rozliczenie wewnętrzne (outside `states` of the first finding, outside `consumers` of ADR 0005),
Sprawdzanie of Przebieg rozliczeń without its guard (outside `consumers` of both findings), and the guard of
Przygotowanie checking only the Rozliczenie wewnętrzne or also the Folder okresu (outside `states` of the second
finding and of ADR 0005).
A mutation reported as `NIEAKTUALNA` no longer matches its file; rewrite its anchor and replacement against the new
code so it breaks the same rule again.
