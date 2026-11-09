---
name: verify-kopia-wzorca
description: Check with generated Wiersze danych that every Rozliczenie pracownika written by the template copy (ADR 0008, `template_copy.py`) is the file the old openpyxl path would write, keeps the rest of the Wzorzec byte for byte, and has the shape Excel needs. Use when a change touches `src/rozliczenia/template_copy.py`, `src/rozliczenia/workbook_parts.py`, `src/rozliczenia/highlights.py`, `src/rozliczenia/row_look.py`, `src/rozliczenia/hyperlinks.py`, `src/rozliczenia/template_file.py`, `src/rozliczenia/write_routes.py`, `src/rozliczenia/workbook_save.py`, `src/rozliczenia/workbook_files.py`, `src/rozliczenia/collective_layout.py`, `tools/porownanie_rozliczen.py`, the synthetic Wzorce in `tools/lib/atrapy/` (`wzorce.py`, `settlement.py`, `workbooks.py`, `pliki_taty.py`), or when `tests/test_kopia_wzorca.py` fails.
pilnuje:
  - src/rozliczenia/template_copy.py
  - src/rozliczenia/workbook_parts.py
  - src/rozliczenia/highlights.py
  - src/rozliczenia/row_look.py
  - src/rozliczenia/hyperlinks.py
  - src/rozliczenia/collective_layout.py
  - src/rozliczenia/workbook_files.py
  - src/rozliczenia/template_file.py
  - src/rozliczenia/write_routes.py
  - src/rozliczenia/workbook_save.py
  - tools/porownanie_rozliczen.py
  - tools/lib/atrapy/wzorce.py
  - tools/lib/atrapy/settlement.py
  - tools/lib/atrapy/workbooks.py
  - tools/lib/atrapy/pliki_taty.py
ci: .agents/skills/verify-kopia-wzorca/scripts/check_template_copy.py --no-shrink
---

# Verify kopia Wzorca

## What CI runs and what stays local

CI runs `check_template_copy.py --no-shrink` (the `ci:` key, which is also the baseline of
`check_copy_mutations.py`) and `tests/test_kopia_wzorca.py` whenever a change touches this skill, and
the mutations in full CI on `main` and nightly on `main` (`mutacje-nocne.yml`). Run them locally only to
reproduce a red CI step or the night's issue. What stays with you: the options CI never
runs, fresh seeds after a larger change to `template_copy.py` (`--seed`) and Dad's real Wzorzec
(`--wzorzec`, on Maks's Mac), both in the background with a wait for their end in the same turn; and reading a red run as „When the check
fails” says.

## The promise

Przebieg rozliczeń does not load and save each Rozliczenie pracownika with openpyxl. It copies the
bytes of the Wzorzec rozliczenia pracownika and splices the Wiersze danych into the sheet XML
([ADR 0008](../../../docs/adr/0008-zapis-rozliczenia-pracownika-przez-podmiane-wierszy-danych.md)).
The check holds that copy to five rules, for any Wiersze danych:

- **WIERNA_KOPIA**: the Rozliczenie pracownika from the copy matches the file the old openpyxl path
  writes (`TemplateFile.create` on a twin of the Wzorzec the copy refuses) in everything Dad sees in Excel, as judged by
  the benchmark's correctness gate `tools/porownanie_rozliczen.py`: values, formulas, resolved
  styles (with the Wyróżnienia: fill, font color, bold, italic), Hiperłącza (address and location of every cell's
  hyperlink, not its relationship id), merges, row and column dimensions, defined names, external links,
  recalculation flags.
  Harm: a worker's quantities or amounts are wrong or formatted differently, and nothing stops.
- **WYGLAD_WIERSZA**: every cell A:L of a written Wiersz danych has the Wygląd Wiersza danych (GLOSSARY),
  derived in the checker from the rule and not from the code: font face and size of the Wzorzec's header
  cell in row 17, left and centre alignment, wrapping exactly when the value is text with a line break
  (`\n` or `\r`), a thin border on all four sides in the automatic colour (`indexed=64`) and the number
  format of the Plik zbiorczy cell; a written row stores no height. Both paths share `row_look.py`, so
  WIERNA_KOPIA alone would not see a defect there. Harm: rows twice as high, centred text, no cell borders
  or `#####` in DATA, as before this rule (2026-10-22).
- **TA_SAMA_ODMOWA**: the copy refuses a value (the run stops) exactly when the openpyxl path
  refuses it, and a refusal leaves no file behind. Harm: a stop that the old path would not make,
  or a file written from a value openpyxl rejects.
- **NIETKNIETY_WZORZEC**: what ADR 0008 promises stays byte for byte does stay so: every zip part
  except the sheet, `xl/workbook.xml` (only `calcPr` changes), `xl/styles.xml` (fonts, fills, borders,
  cell styles and number formats are only appended) and the sheet relationships (only whole
  `<Relationship/>` entries of Hiperłącza appended, or a new part at the end of the zip when the
  Wzorzec has none; without Hiperłącza byte for byte), every sheet row outside the written Wiersze
  danych apart from one inserted `<hyperlinks>`, the row attributes apart from the removed height
  (`ht`, `customHeight`) and the cells right of AT (formulas AU:AY) in written rows, and the Wzorzec
  file on disk. Harm: lost shared formulas,
  `calcChain`, external links or the Wzorzec's comments, which openpyxl's view would not show.
- **KSZTALT_EXCELA**: the file has the shape Excel expects, which openpyxl does not check when it
  reads a file: zip CRCs, rows and cells in ascending order with references matching the row,
  `dimension` covering the written rows, `xml:space="preserve"` on text with spaces at either edge,
  the `count` of `numFmts`, `fonts`, `fills`, `borders` and `cellXfs` matching their entries, every
  cell style pointing at an existing font, fill, border and number format, unique `numFmtId`, the children of
  `<worksheet>` in schema order (CT_Worksheet, written down in the checker independently of the
  copy) with at most one `<hyperlinks>`, a content type for every part, unique relationship ids in
  the sheet relationships, every `<hyperlink>` pointing at an external hyperlink relationship and no
  cell twice in `<hyperlinks>`. Harm: Excel offers to repair the file, drops the Hiperłącza or
  silently trims text.

## Does the change touch it?

The check covers this code. Its definitions have digests in `model/definicje.json`: when one of them changes,
`tools/szybko.py` fails before you push (step `rozjazd modelu`), and CI fails this skill's step before it starts
(`tools/ci/wykonaj_zadanie.py`, line `ROZJAZD MODELU Z KODEM`), until you have done „Bring the model in line”.

| Code | What the check covers |
| --- | --- |
| `src/rozliczenia/template_copy.py` (all of it but what only the period files reach, `SheetLayout.period_file`: the Plik zbiorczy and the Rozliczenie wewnętrzne, with their `autoFilter`, `_require_known_styles`, zero rows and target headers; `tests/test_plik_zbiorczy_kopia_wzorca.py` covers them) | the code under verification |
| `src/rozliczenia/workbook_parts.py` (`SheetData`, `SheetRow`, `relationships`, `office_document`, `relationships_part`, `active_sheet`, `style_list`, `appended`, `with_style_attribute`; `UnsupportedShape`; `IrregularSheetData`, `_sheet_rows`, `_raise_irregular`) | row index the copy splices on, the parts it finds by relationship, the sheet it writes (`workbook.active` of openpyxl), the styles it appends, the Wzorce it sends down the old path and the XML comment that makes it refuse the twin |
| `src/rozliczenia/highlights.py` (`Highlights`: `of`, `font_over`, `fill_over`; `LookReader`) | Wyróżnienia both paths lay over the Wzorzec's font and fill |
| `src/rozliczenia/row_look.py` (`RowLook`, `CellLook`, `wraps`) | Wygląd Wiersza danych both paths give A:L; judged by WYGLAD_WIERSZA |
| `src/rozliczenia/hyperlinks.py` (`Hyperlink`) | the Hiperłącze both paths write; its reader `read_sheet_hyperlinks` is covered by pytest (`tests/test_hiperlacza_pliku_zbiorczego.py`), not here |
| `src/rozliczenia/template_file.py`: `TemplateFile` (`worker_settlement`, `check`, `create`, `_read`, `_template_copy`), `_in_columns` (a `DataRow` cell in its own column), `_package_writer`; `src/rozliczenia/write_routes.py`: `Route`; `src/rozliczenia/workbook_files.py`: `DataCell`, `DataRow`, `check_worker_header`, `template_content`; `src/rozliczenia/workbook_save.py`: `write_atomically` | the real entry point; which path it takes (`create` returns it) |
| `src/rozliczenia/template_file.py`: `TemplateFile._create_with_openpyxl`, `_write_rows`, `_ensure_unmerged`, `_request_recalculation`; `src/rozliczenia/workbook_save.py`: `save_from_template`, `_restore_external_link_parts` | the reference (old openpyxl path) |
| `tools/porownanie_rozliczen.py` (`compare_worker_settlements` and its per-cell helpers, `_hyperlink` among them) | the judge for WIERNA_KOPIA |
| `tools/lib/atrapy/wzorce.py` (`write_settlement_template`), `tools/lib/atrapy/settlement.py` (`write_template`), `tools/lib/atrapy/workbooks.py` (`add_external_link_fixture`, `refused_by_copy`) | the Wzorce under test and the twin the copy refuses |

The checker and the synthetic Wzorce take Dad's layout (header row 17, first Wiersz danych 18, A:L, A:AT, F) from
`tools/lib/atrapy/pliki_taty.py`, not from `src/rozliczenia/collective_layout.py`, so a wrong layout constant in `src`
misses the Wzorzec and the check fails, with no digest; two mutations below hold that.
Changes elsewhere (reading the Plik zbiorczy, `engine.py`, publication of the Folder rozliczeń
pracowników) do not matter here.

## Bring the model in line

When `tools/szybko.py` names a changed definition of `model/definicje.json`:

1. Read the diff of that definition and sort it: does it change what a rule above promises (ADR 0008), the shape of
   a Wzorzec in the table under „How it works and what it covers”, the path a Wzorzec or a value takes (copy, old path,
   refusal), or the names in the coverage table?
2. If it does, change this file and `check_template_copy.py` so that they describe the code: the rules, the
   coverage table, the Wzorce, `build_templates`, and `VERIFIED` and the mutations in `check_copy_mutations.py` when
   code moves to another file. A new definition the copy now calls goes into `model/definicje.json`.
3. Run the check, after a larger change to `template_copy.py` also a few `--seed` runs (both under „Run”). A new
   violation is a finding: sort it as „When the check fails” says before you call it a bug.
4. Run `tools/przesun_model.py verify-kopia-wzorca` only after this file describes the code, and write in the commit
   message what changed in the description and why.

## Run

```powershell
py -3 .agents\skills\verify-kopia-wzorca\scripts\check_template_copy.py
```

On macOS or Linux use `.venv/bin/python` instead of `py -3`. It needs the repo's test
dependencies (`hypothesis`, pinned to the same version in `requirements.txt` and the `dev` extra, because the checker
reaches into `hypothesis.internal`; `tests/test_kopia_wzorca.py` holds the pins equal), takes about
85 s on a Mac M4 Max when it passes and runs in CI as `tests/test_kopia_wzorca.py`. Most of that
is the openpyxl reference, which copies the font and fill of every written cell. A failing run
spends up to a minute more shrinking the counterexample (`SHRINK_SECONDS`). In a worktree,
create its own `.venv` first (`tools/setup_worktree.py`); the script refuses to run against another checkout's
`src`.

`tests/test_kopia_wzorca.py` runs the same check in parts that pytest-xdist spreads over workers
(`CZESCI`: one part for `maly`, four for `syntetyczny`). Part i of n compares every n-th example of its
Wzorzec with the openpyxl path (`run_check(part=(i, n))`), but writes every example through the copy,
so its coverage line is that of all examples. A failing part names its share in the `Czas:` line.

The last line is the verdict:

| Last line | Exit | Meaning |
| --- | --- | --- |
| `KOPIA WZORCA OK` | 0 | All five rules hold in every example. |
| `KOPIA WZORCA: NOWE NARUSZENIE (n)` | 1 | A rule breaks. The shrunk counterexample is printed. |
| `KOPIA WZORCA: LUKA SPRAWDZENIA (n)` | 2 | The run did not exercise what it must: the copy was used less often than the openpyxl fallback or than refusals, a reachable compression chunk start was never crossed, no Rozliczenie pracownika with Wyróżnienia or no Rozliczenie pracownika with Hiperłącza went through the copy, Wiersze danych without a rare value were refused (`odmowy Wierszy danych bez rzadkiej wartości`: usually an interface change both paths fail on alike), `rozliczenia` was imported from another checkout, or the checker itself failed (`błąd samego sprawdzenia`). No verdict on the rules. |

Options:

- `--seed N --examples 300` draws fresh random examples instead of the fixed derandomized set.
  Use it after a larger change to `template_copy.py`; one seed takes a few minutes. Run seeds one
  after another, not in parallel.
- `--wzorzec "<path>\Wzorzec rozliczenia pracownika.xlsx"` checks Dad's real Wzorzec instead of the
  synthetic ones (read only, copied to a temp folder; it has no client data). On Maks's Mac it is in
  `~/MAXIMISEART-Dad/config/`. Each example loads 10 thousand rows three times and the
  process needs about 1 GB of memory, so use `--examples 15` (about 4 minutes) and run nothing else beside it.
- `--no-shrink` skips shrinking (used by the mutation check).

## How it works and what it covers

One Hypothesis example is one Przebieg rozliczeń: one `TemplateFile` is loaded and
checked once, then 1 to 3 Rozliczenia pracowników are made from it in a row, as `run_settlements()`
does for its workers. That catches state carried from one copy to the next, such as the
compressed chunks cached at the first copy. Each Wzorzec below gets its own Hypothesis run with the
full number of examples (60 by default), and fixed examples first: the value-type and
Wyróżnienia rows of the owner tests in `tests/test_workbook_files.py` with Hiperłącza in A and I, one
Rozliczenie pracownika with the most Wiersze danych in scope, each with a Hiperłącze in F (it crosses
every reachable chunk start and writes the sheet tail with `<hyperlinks>`), three counterexamples
from CI with `\r` in text (two through the copy, one down the old path), and empty A and B up
to the first row whose A cell the Wzorzec XML lacks (row 139 of `syntetyczny`), which the copy has
to add. Each Rozliczenie
pracownika is written by the real `TemplateFile.create()` and, separately, by the openpyxl path from the Wzorzec's twin (an XML comment in its sheet data makes the copy refuse it; openpyxl skips the comment), then judged.

| Wzorzec | Shape | Wiersze danych per Rozliczenie pracownika |
| --- | --- | --- |
| `syntetyczny` | Dad's Wzorzec in small, from `tools/lib/atrapy/wzorce.py` with 200 Wiersze danych: Excel-written XML, shared formulas every 64 rows, `calcChain`, external link, `sharedStrings`, a comment in H17 with Dad's sheet relationships (`rId1` VML drawing, `rId2` comments, `<legacyDrawing>` after `pageMargins`, so new ids must start at `rId3`), rows of zeros in N:V and X, date formats, the first Wiersz danych without a cell in A in row 139 (Dad: 609) | 0–260, so writes reach past the last formatted row and the trailing row 269; compression chunks start at rows 18, 82, 146, 210 |
| `maly` | openpyxl-written workbook with two formatted Wiersze danych, a second sheet, an external link, namespace prefixes in `workbook.xml`, no sheet relationships (a copy with Hiperłącza adds the part) | 0–80 |
| `wzorzec-taty` (only with `--wzorzec`, then the only one) | Dad's real Wzorzec | 0–700, chunks from rows 18, 82, …, 658 |

Row counts are drawn both at random and from the counts whose last written row falls right
before, on, or right after each chunk start within reach and the end of the sheet. The run reports
`granice kawałków przekroczone: k/n` and is a LUKA SPRAWDZENIA unless every reachable chunk start
was crossed by a Rozliczenie pracownika written through the copy. Each row is a `DataRow` with 46
cells (A:AT), each with its value, Wyróżnienia, number format and Hiperłącze, as `read_data_rows` gives them; the
number formats of A:L vary: most rows carry
`General` with a date format on dates, as from a Plik zbiorczy written by Przygotowanie, the others a mix of
built-in formats, Dad's date format and custom codes with quotes, colours and `<&>`. About half the rows have no
Wyróżnienia; the others mark up to 10 cells, built with `Highlights.of` from fonts and fills as
reading a Plik zbiorczy does: solid, patterned and gradient fills, RGB, theme-with-tint and indexed
colors, bold, italic. About half the rows have Hiperłącza in 1 to 3 cells, mostly in F (`NUMER ZL.`),
and only on cells with a value, as `read_data_rows` gives them (an empty cell drawn for a link gets
a synthetic order number). Addresses: `&`, `#fragment`, quotes, `<`, spaces at the edges, Polish
letters, emoji, tab and line breaks, `mailto:`, `file:///`, 2000 characters, and random text of any
character XML allows. The run reports `z Hiperłączami przez kopię` and is a LUKA SPRAWDZENIA when no
Rozliczenie pracownika with Hiperłącza went through the copy on a Wzorzec. Values cover what reading a Plik
zbiorczy gives and what openpyxl accepts: `None`, text (XML specials, spaces at the edges, line
breaks, `_x000D_`, emoji, 32 767 characters and longer), formulas and `=`, error codes, integers past
2^53, floats (NaN, infinities, subnormals, −0), `Decimal`, booleans, dates, datetimes, times and
durations including dates before 1900-03-01. About one value in 60 is one that sends the file down
the old path or refuses it: control characters, time zones, signalling NaN, rich text, array
formulas, bytes. Only these may be refused: a refused Rozliczenie pracownika without one is a
LUKA SPRAWDZENIA. The default run is derandomized, so it gives the same examples every time and in
every process. The checker turns off Hypothesis's draws from the literals of the modules loaded beside
it; with them, `tests/test_kopia_wzorca.py` checked other examples alone than in the full pytest (#288).

Not covered:

- This is testing with generated inputs, not a proof. Python has no verifier that runs on code
  built from `zlib`, regexes and byte slicing; a bug that needs a value or a row count the
  generator does not reach can pass.
- The reference is the openpyxl path, and the judge reads both files with openpyxl. A defect
  shared by both paths, or a difference openpyxl hides when reading, is invisible, apart from
  what KSZTALT_EXCELA checks. Excel itself is never run.
- The openpyxl path's raw `\r` on Windows. Every XML reader turns `\r\n` and a lone `\r` into `\n`,
  so when the copy writes the file, the reference gets text with line ends already normalized
  (`_xml_line_ends`) and the copy gets the raw text.
  The reason: openpyxl writes the sheet through et_xmlfile, which opens its temporary file in text
  mode, so on Windows a raw `\r\n` comes back from the openpyxl path as two line breaks (first CI
  run of this skill). When the copy itself takes the old path, both files come from openpyxl with the
  raw text, so they share that quirk. The quirk is not checked. A Plik zbiorczy read by openpyxl
  practically never carries a raw `\r` (Excel stores it as `_x000D_`).
- Only the Wzorce above. Wzorce of other shapes go the old way (`UnsupportedShape`), and that
  routing decision is not checked. Neither is the refusal of a Wzorzec whose written Wiersze danych
  are merged (`_ensure_unmerged` on the openpyxl path), which `tests/test_settlement_engine.py` covers.
- Ilości usług (`RegisterRow.quantities`, `SheetLayout.quantity_columns`). Only the Plik zbiorczy gets
  them, so every Rozliczenie pracownika here has none; `tests/test_ilosci_uslug.py` compares the
  copy with the openpyxl path for them.
- Reading the Plik zbiorczy, the engine, the publication of the Folder rozliczeń pracowników, the
  Wzorzec changing on disk between Sprawdzanie and Zapisywanie, and file system failures.

## When the check fails

Read the counterexample as a story: step 1 loads the Wzorzec, each next step is one Rozliczenie
pracownika with its row count, row range and non-empty values (`K82=datetime(...)`), and the
lines with `→` name the rule, the Rozliczenie pracownika and the cells or parts that differ. Then
sort it into one of three cases:

- **Real bug**: a Plik zbiorczy could carry those values (or a Wzorzec of that shape could exist),
  and the copy is the side that differs. Report it with the story in those words. Fix the product
  code only if the user asks. If the user accepts the divergence instead, record the decision
  (ADR 0008 or a new ADR) before teaching the checker to accept exactly that pattern.
- **Modeling error**: the checker is wrong. For example a rule reads XML the copy is allowed to
  write differently (prefixed tags, attribute order the ADR allows), the reference was written
  differently from `run_settlements()`, or the generator made a value that can never reach a
  Wiersz danych and both paths treat differently for an irrelevant reason. Fix the checker, then
  rerun the mutations below.
- **LUKA SPRAWDZENIA**: the run lost coverage, usually because a new refusal or fallback became
  common (look at `Rozliczenia pracowników: kopia …, droga openpyxl …, odmowa …` and the refusal
  types) or the Wzorzec generator changed its row count. Make the rare values rarer or fix the
  Wzorzec setup in `build_templates`.

Never loosen a rule or drop a value or Wzorzec to make a real counterexample disappear.

## After changing the checker or an intended change to the copy

CI proves the check can still fail: the night on `main` runs the script below after a change of this
skill's folder. Run it locally only to reproduce a red Mutation checks step or the night's issue, or after
you rewrite a mutation.
It applies broken variants to a temporary copy of the checkout (`tools/mutacje.py`), never to the checkout:

```powershell
py -3 .agents\skills\verify-kopia-wzorca\scripts\check_copy_mutations.py
```

It must end with `MUTACJE OK`: each of the twenty-two mutations (sheet CRC over the head only, chunks
from one shared compressor without a full flush, so each reaches back into the one before, a dropped chunk, `dimension` not extended, a date without a date format, an
empty value keeping the Wzorzec's zero, Wyróżnienia without the fill, the Wzorzec's border left in
A:L, the Wzorzec's number format left in A:L, the Wzorzec's row height kept, three in `row_look.py`
that change both paths at once (every text wrapped, text with `\r` but no `\n` not wrapped, a font
size not from the header), 15 significant digits, `xml:space` only for leading spaces, `&` not
escaped, `<hyperlinks>` placed after `pageMargins`, a reused Wzorzec `rId`, a Hiperłącze one row off,
`&` not escaped in a Hiperłącze address, and two in `collective_layout.py` that the Wzorce and the checker no longer
follow: the first Wiersz danych one row lower, A:K instead of A:L for the Wygląd Wiersza danych) must give
`KOPIA WZORCA: NOWE NARUSZENIE`.
The mutations run side by side; it takes about 15 s. CI runs it in the `mutations` job. A
mutation reported as `NIEAKTUALNA` no longer finds its `anchor` exactly once in `template_copy.py`,
`row_look.py` or `collective_layout.py`: rewrite its `anchor` and `replacement` in `check_copy_mutations.py` against the new code
so that it breaks the same rule again.

When the copy changes on purpose, follow „Bring the model in line”; if the copy moves to another file, also update
this skill's description.
