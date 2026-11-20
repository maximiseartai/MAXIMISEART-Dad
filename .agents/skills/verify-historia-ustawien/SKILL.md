---
name: verify-historia-ustawien
description: Model-check with TLA+ (TLC) the owner of the Ustawienia Centrum (`CentrumSettings`, ADR 0032) on one settings file with its memory in `config/ustawienia-pamiec`, the Historia Ustawień and one Zmiana z Wydania, under every order of Dad's saves and „Cofnij”, process snapshots, a hand edit of the file outside Centrum, a Centrum that switches off at any step and a failure of each write and read. It checks that an Uruchomienie computes with the value the Historia shows as current, that a Zmiana z Wydania never overwrites a value Dad saved after it took effect, that „nie zapisano” means the file did not change, and that „Cofnij” restores the bytes from before the change, including no file. Use when `tools/skille_dla_zmiany.py` names it, when a change adds a writer of a settings file, of the memory or of the Historia, a step to `CentrumSettings._change`, `_compared` or `_apply_pending`, or a new entry in `RELEASE_CHANGES`, or when `sprawdz_historie_ustawien.py` fails.
pilnuje:
  - src/rozliczenia/centrum/settings/owner.py
  - src/rozliczenia/centrum/settings/memory.py
  - src/rozliczenia/centrum/settings/history.py
  - src/rozliczenia/centrum/settings/release_changes.py
  - src/rozliczenia/centrum/settings/proposal.py
  - src/rozliczenia/centrum/atomic_file.py
  - tools/lib/model_tlc.py
  - tools/lib/rozjazd_modelu.py
  - tools/lib/narzedzia_tlc.py
ci: .agents/skills/verify-historia-ustawien/scripts/sprawdz_historie_ustawien.py
---

# Verify Historia Ustawień (TLA+)

## What CI runs and what stays local

CI runs `sprawdz_historie_ustawien.py` (the `ci:` key) in Mutation checks whenever a change touches this skill's
`pilnuje:` or folder, so run it locally only while you bring the model in line or to reproduce a red Mutation checks
step. CI and `tools/szybko.py` catch drift: covered code that differs from its digests in `model/definicje.json`
(`ROZJAZD MODELU Z KODEM | <skill>: …`); they cannot tell whether your change to the model is right.
`check_model_historii_mutations.py` runs on a pull request that changes a file in `model/`, the script itself,
`sprawdz_historie_ustawien.py` or a module that check imports (`tools/lib/model_tlc.py` and its imports), and in full
CI and nightly on `main` after a change of this skill's folder.
What stays with you on every change to the covered code is „Bring the model in line”.
A change whose model nobody brought in line is not verified, whatever CI says.

## The promises

`CentrumSettings` is the only reader and writer of the settings files in `config/`, their Historia Ustawień
(`config/historia-ustawien.jsonl`) and its memory (`config/ustawienia-pamiec/`: `seen` and `good` per file, and
`zmiany-z-wydan.json`). Every read and write runs under one lock and starts by comparing the file with the memory; a
different state is a change from outside Centrum with one Historia row. A Zmiana z Wydania runs at the start of
Centrum, before the first request, through the same `_change` as Dad's save. ADR 0032 and the tests named below
promise, and the model checks over every order of steps:

- **LiczyZapisanym**: an Uruchomienie computes with the value the Historia shows as current: the „po” of the newest row
  „zapisano” of the file, or, before any such row, the content from before the Wydanie. Source: ADR 0032 („Historia
  Ustawień”, „Furtka Maksa”), `test_reczna_zmiana_pliku_ustawien_ma_jeden_wiersz_spoza_centrum_z_wartoscia_przed_i_po`,
  `test_zmiana_ktorej_wiersza_historii_nie_da_sie_dopisac_zostawia_plik_ustawien_bez_zmiany` and
  `test_zla_tresc_pliku_po_dobrej_to_zle_ustawienie_z_ostatnia_dobra_wartoscia_i_jednym_wierszem_bez_cofniecia`. Harm: a settlement computed with Reguły ilości, a
  Lista Wykonawców or Foldery that the Historia does not show; Maks cannot explain it, and Dad's „Cofnij” restores
  something else.
- **WydanieNieNadpisuje**: a Zmiana z Wydania never writes its value over a value Dad saved (with the form or
  „Cofnij”) after that change took effect: it got a result, or a Historia row showed its value in the file. Source:
  `test_zmiana_ustawien_z_wydania_bez_niczego_do_zmiany_nie_wraca_i_nie_ma_wiersza`,
  `test_zmiana_z_wydania_z_wierszem_historii_bez_pamieci_nie_wraca_po_cofnieciu_przez_tate`,
  `test_zmiana_ustawien_z_wydania_ktorej_nie_da_sie_zapisac_wraca_przy_nastepnym_starcie` and the declarative edit
  that `release_changes.py` requires. Harm: Dad undoes or corrects a Wydanie's change, and the next start
  of Centrum quietly puts it back.
- **NieZapisanoZnaczyNie**: when Dad reads „nie zapisano” (`NotSaved`), the file does not hold the value he just typed.
  Source: `test_zmiana_ktorej_wiersza_historii_nie_da_sie_dopisac_zostawia_plik_ustawien_bez_zmiany`. Harm: processes compute with a value Dad believes
  was refused.
- **CofnijPrzywracaBajty**: „Cofnij” of a row writes the bytes from before that change: no file when the change created
  it (`HistoryRow.created`), otherwise the value from before. Source: ADR 0032 („Historia Ustawień”, Maks's decision
  in #2237) and `test_cofniecie_zmiany_ktora_utworzyla_plik_ustawien_usuwa_plik`. Harm: Dad undoes his first change of a file he did not have, the file stays with the Wydanie's
  content, and the next Wydanie's new defaults never reach him, because an Aktualizacja does not overwrite Ustawienia
  (ADR 0032).

## The model

`model/HistoriaUstawien.tla` has one settings file without a secret and outside the pair of Reguły ilości and Lista
Urządzeń, with abstract values: `v0` (the content before the Wydanie), `r` (the value the Zmiana z Wydania sets), `t`
(Dad's value), `x` (a value typed outside Centrum), `zly` (content `parse` refuses) and `d` (`file.default`). The file
holds a content: one of these values, `brak` (no file, whose value is `d`) or `d` itself (`file.dump(file.default)`, the
Wydanie's content written to Dad's file); `Wartosc` gives a content's value. The Zmiana
z Wydania is declarative, as `tests/test_centrum_rozliczen.py::test_zmiana_z_wydania_po_utracie_pamieci_wlasciciela_biegnie_drugi_raz_bez_roznicy_i_bez_wiersza` requires of each entry of `RELEASE_CHANGES`: it proposes „set `r`” on a good value and `Later` on bad
content, like `periods_directory_from_layout_root`. Because the owner works under one lock, its steps never interleave
with each other; they interleave only with a hand edit of the file and with a switch-off. Each action is one read or
write on disk; an action without disk (`Uzyj`, `Propozycja`, `Wylicz`, `NieZapisano`) changes nothing a hand edit or a
switch-off could see.

## Does the change touch it?

The check runs a hand-written TLA+ model, not the code. It describes the code only while you keep the two in step.
Each model action is one indivisible step of this code (`src/rozliczenia/centrum/settings/`):

| Model action | Code |
| --- | --- |
| `StartPamiecZmian` | `CentrumSettings.apply_release_changes`: `Memory.applied`; a change it has is not applied again |
| `StartHistoria` | `CentrumSettings._apply_pending`: `CentrumSettings._release_rows` (`History.read`); Historia without a read holds the change until the next start („bez-historii”), a row with the change's id gives it a result without applying it, otherwise `CentrumSettings._apply`, which starts with `_observe` of the file |
| `Odczyt` | `CentrumSettings.snapshot` for an Uruchomienie: `CentrumSettings._observe` of the file |
| `ZapisTaty` | Dad's save of a section: `CentrumSettings.change_*` → `CentrumSettings._by_dad` → `CentrumSettings._dad_change` → `CentrumSettings._change` with „set `v`” |
| `CofnijTaty` | `CentrumSettings.undo`: `History.read` (without a read: `NotSaved`), a row „zapisano” with `undoable`, then `_by_dad` with the value from before that row (`file.restore(current, changes)`) and the row itself as `undoes` (its `created`) |
| `Porownaj` | `CentrumSettings._bytes_for_change` or `_observe` (`settings_bytes`), then `CentrumSettings._compared`: `Memory.read`; the same state as the memory gives no row; `Unreadable` memory (only in a read for a process) gives `_read(parsed, None)` without comparing, so bad content has no last good value and `_value` gives `file.default` |
| `WierszSpoza` | `CentrumSettings._compared`: `History.append` of `CentrumSettings._outside_row` (`created` when the memory saw no file); on `OSError` it returns `_read(parsed, good)` and keeps the memory |
| `PamiecSpoza` | `CentrumSettings._compared`: `CentrumSettings._remember` of the new state (bad content keeps the old `good`) |
| `Uzyj` | the process takes `_value` of the observed value |
| `Propozycja` | `CentrumSettings._apply`: `change.propose` on the observed value: `Edit` („set `r`”) on a good value, after which `_change` reads the file again, or `Later` on bad content (`periods_directory_from_layout_root`), without a result, so the change comes back at the next start |
| `Wylicz` | `CentrumSettings._change`: `edit(current)`; no difference on a good file is `Saved(change=None)` (result „bez-zmian”); a row only with a difference of keys; `new` is no file when `CentrumSettings._restores_absence` holds („Cofnij” of a row with `created` after which the later rows of the file leave nothing: each key back to its value before the first row since that touched it gives the same value and `file.restore` of those keys is not a `FieldProblem`; with one value, always), else `file.dump` |
| `Zapis` | `CentrumSettings._change`: `place.write(new)` (`_ConfigFile`, `replace_atomically`); `OSError` is `NotSaved` |
| `Wiersz` | `CentrumSettings._change`: `History.append` of `CentrumSettings._row` (`created` when there was no file before, `removed` when the change writes none); `OSError` goes to `CentrumSettings._put_back` |
| `Przywroc` | `CentrumSettings._put_back(place, data)`, the content from before; its `OSError` is only logged and leaves the new content without a row; then `NotSaved` |
| `NieZapisano` | `CentrumSettings._change` returns `NotSaved`: Dad reads „nie zapisano”, and a Zmiana z Wydania has no result and comes back at the next start |
| `Pamiec` | `CentrumSettings._remember(file, Remembered(seen=new, good=new))` after the row (`Memory.write`, its `OSError` only logged), then `Saved`, which gives a Zmiana z Wydania its result |
| `PamiecZmian` | `CentrumSettings._apply_pending`: `applied[change.id]` and `Memory.remember_applied` of the result; its `OSError` only logged („bez-pamieci”) |
| `Reczna` | none: Maks or Dad writes the file outside Centrum, also during a step of the owner and while Centrum is off |
| `Zgasniecie` | none: Centrum switches off at any step and Dad opens it again; the next start runs `apply_release_changes` before the first request; a Historia line cut by the switch-off is skipped by `History.read`, so it is a row that does not exist |

Definitions and values the actions share:

| Model definition | Code |
| --- | --- |
| `BRAK`, `Wartosc(tresc)` | no file (`settings_bytes` gives `None`), whose value is `DOMYSLNA` (`file.parse(None)`); any other content is its own value |
| `DOMYSLNA` | `file.default`: the Wydanie's value, which `_value` gives to no file and to bad content without a last good value; as a content, `file.dump(file.default)` written to Dad's file |
| `ZLY` | content that `parse` refuses (`FieldProblem`): a bad setting |
| `CEL_WYDANIA` | the value the Zmiana z Wydania sets (an `Edit`, declarative) |
| `WartosciTaty`, `Reczne` | the values Dad types into the form of a section; the contents someone writes outside Centrum |
| `Zrodla`, `Wiersze` | `RowSource` (`ByDad`, `FromRelease`, `Outside`) and a Historia row, whose `utworzono` is `HistoryRow.created`: there was no file before the change |
| `Zapisane` | the value the Historia explains: the „po” of the newest row „zapisano”, or without one the content from before the Wydanie |
| `WierszSpozaCentrum(dane, dobry, utworzono)` | `CentrumSettings._outside_row`: bad content is „odrzucono” without „Cofnij”, good content a difference from the last good value; `created` when the memory saw no file |

Each constant is the start state or a bound of a configuration (`stale` in `model/konfiguracje.json`):

| Constant | Meaning |
| --- | --- |
| `Poczatek` | the file before the first start with the Wydanie: `v0`, `r` (Dad already has the change's value) or `brak` (no file, Centrum computes with the Wydanie's value) |
| `MaxZmian` | Dad's saves in the Ustawienia window (the form of a section: `CentrumSettings._by_dad`, `_change`) |
| `MaxCofniec` | Dad's clicks of „Cofnij” (`CentrumSettings.undo`) |
| `MaxRecznych` | edits of the file outside Centrum (Maks, or Dad in Notepad) |
| `MaxZgasniec` | switch-offs of Centrum at any step, after which Dad opens it again |
| `MaxAwariiZapisuPliku` | `_ConfigFile.write` (`replace_atomically`) raises `OSError` |
| `MaxAwariiWiersza` | `History.append` raises `OSError` after its retries (`RETRY_PAUSES_S`) |
| `MaxAwariiPrzywrocenia` | `_put_back` does not restore the file (`place.write` raises `OSError`) |
| `MaxAwariiPamieci` | `Memory.write` raises `OSError` (`_remember` only logs it) |
| `MaxAwariiPamieciZmian` | `Memory.remember_applied` raises `OSError` (`_apply_pending` only logs it) |
| `MaxNieczytelnejPamieci` | `Memory.read` in a read for a process gives `Unreadable` (an antivirus holds the file) |
| `MaxNieczytelnejHistorii` | `History.read` gives `Unreadable` (at start or at „Cofnij”) |
| `Wybaczone…` | the causes of known findings that the `…PozaZnanymi` variant of each promise skips; the script sets them |

| Variable | Meaning |
| --- | --- |
| `plik`, `pamiec`, `historia`, `zmianyZWydan` | Dad's disk, which outlives a switch-off: the content of the settings file in `config/`; its `Remembered` (`seen` and `good`); the Historia rows from the oldest (a line cut by a switch-off is a row that does not exist); whether the memory of Zmiany z Wydań has the change |
| `faza`, `op` | the work of Centrum, gone with a switch-off: `start` (`apply_release_changes` before the first request), `historiaWydan`, `wolny` or `praca`; the one operation of the owner under its lock (a read for a process, Dad's save, the Zmiana z Wydania) |
| `weszla` | the Zmiana z Wydania took effect: it has a result, or a Historia row (also one from outside Centrum) showed its value in the file |
| `wydanieWPliku`, `wartoscTaty` | the file still has the value the Zmiana z Wydania wrote (nobody overwrote it); the file has a value Dad saved after the change took effect |
| `bezZmianNiezapamietane`, `przywrocenieWydaniaNieudane`, `zgasniecieWydania` | the causes of known findings: a result „bez-zmian” without a row whose `remember_applied` failed; a write of the Zmiana z Wydania without a row that `_put_back` did not undo; a switch-off after that write and before its Historia row (`History.append` after `place.write`) |
| `pamiecZaWierszem` | the Historia has a row the file's memory did not take: after a switch-off between `History.append` and `_remember` (`zgasniecie`) or a failed `_remember` (`awaria`); bad content keeps the last good value in the memory, so its cause stays |
| `zmiany`, `cofniecia`, `reczne`, `zgasniecia`, `awZapisu`, `awWiersza`, `awPrzywrocenia`, `awPamieci`, `awPamieciZmian`, `nieczPamieci`, `nieczHistorii` | the counters of the `Max…` constants |
| `bezWiersza`, `nadpisane`, `klamstwo`, `zleBajty` | the history variable of each promise: the set of causes at the moment of each event that breaks it |

`model/definicje.json` holds the digests of the definitions the table names, plus `History._write` (the leading newline
that keeps a cut line apart), `replace_atomically` (old or new file, never a torn one), `settings_bytes`, `_seen` and `_good_value` (what
`_compared` compares and which last good value it gives), `_value`,
`_or_unreadable`, `_or_release` (which callers get `file.default`), `RELEASE_CHANGES` and all of `proposal.py` (the
shapes of a Zmiana z Wydania). `_restores_absence` keeps a file whose Zmiana z Wydania gives no file a meaning
(`refused_absent`, `waiting`: Lista Wykonawców); the model has no such change, so that branch is not checked. Left out
on purpose: the pair check of Reguły ilości and Lista Urządzeń (`_paired`,
`_checked`), the secret of the inbox file (`_with_secret_value`, the hash in `_seen`), the autostart place, a settings file
outside the Zakres of the Stanowisko (`_OutsideScope`: `_observed` gives `file.default` without the file, the memory or
the Historia, and the constructor drops its Zmiany z Wydania), the periods check of
removed logins (`_by_dad` before the lock), `keep_rejected`, the first read after the Wydanie that introduced the owner
(no memory at all) and `_absent`. Two changes move the model without changing a definition, so look for them in the
diff: a new caller that writes a settings file, the memory or the Historia outside `_change`, `_compared` and
`_apply_pending`, and a new entry in `RELEASE_CHANGES` whose `propose` is not „set on a good value, `Later` on bad
content” (a migration that reads old files and returns `Nothing` once its file exists is safer than the model's
change; one that edits a value Dad can change again is what the model checks). Add such code to the table and to
`model/definicje.json`.

The digests in `model/definicje.json` were taken when every row of the table was last checked against the code
(`tools/przesun_model.py`); what that check found is in the message of the commit that changed the digests. To see what
changed since: `git diff $(git log -1 --format=%h -- .agents/skills/verify-historia-ustawien/model/definicje.json) --
<files of model/definicje.json>`.

## Run

```sh
.venv/bin/python .agents/skills/verify-historia-ustawien/scripts/sprawdz_historie_ustawien.py
py -3 .agents\skills\verify-historia-ustawien\scripts\sprawdz_historie_ustawien.py
```

The run of TLC, the verdict and the known findings are `tools/lib/model_tlc.py`; Java and `tla2tools.jar` come from
`tools/lib/narzedzia_tlc.py`. The whole check took 32 s on Maks's busy Mac (load 30) on 2026-11-19 (19 known findings in 28
TLC runs).

The last line is the verdict:

- `HISTORIA USTAWIEŃ OK` or `HISTORIA USTAWIEŃ OK, ZNANE ZNALEZISKA: n`: every configuration ends as
  `model/konfiguracje.json` says (n counts each known finding in each configuration). Exit 0 (1 with `--strict` and
  known findings).
- `HISTORIA USTAWIEŃ: NOWE NARUSZENIE (n)`: a promise breaks on a path that is not a known finding. Exit 1.
- `HISTORIA USTAWIEŃ: ZNALEZISKO ZNIKNĘŁO (n)`: a known finding no longer happens. Describe the change below and remove
  it from `znane` of its configuration in `model/konfiguracje.json`. Exit 1.
- `HISTORIA USTAWIEŃ: BŁĄD MODELU (n)`: TLC gave no verdict, `TypeOK` broke, `model/konfiguracje.json` has another
  shape, or the script's story does not know every action of `Next`. Exit 2.
- `UWAGA: kod opisany modelem zmienił się: …` above the verdict: a definition in `model/definicje.json` differs from its
  digest there, and the verdict means nothing until you bring the model in line.

Each counterexample is told as numbered steps in the code's words, with every change of the file and the Historia, and
ends with the file, the memory of the file, the Historia and the memory of Zmiany z Wydań.

## Read a result

Read every result with the pstack `/statechart` skill: give it `model/HistoriaUstawien.tla` and one configuration with
the `Wybaczone…` constants as they are (empty), and a view whose regions are the file (with the value the Historia
shows), the memory's last good value and Centrum (start, idle, a step of the owner). It shows each broken promise as
its shortest path in plain words. Every configuration here has more states than its chart budget (one save, one hand
edit and one switch-off already give 1,679), so it draws only the paths to the promises that break.

Then tell a real bug from a modeling error: replay the path on the code, one step per action, on a temporary `config`
folder with a `CentrumSettings` of its own (as `tests/test_centrum_rozliczen.py` does through the app). The file
`centrum-ustawienia.yaml` with the theme (`ChangeTheme`) is the simplest file: `dark` and `light` play `v0` and `t`, and
a Zmiana z Wydania of your own (`ReleaseChange` setting the theme) plays `r`. A switch-off inside a step is a child
process that ends with `os._exit` in that step (for `_remember`: `Memory.write` of the file's name; for the row:
`History.append`), and the next start is a new `CentrumSettings` on the same folder. A failed `Memory.write` or
`place.write` is a folder in place of its `.tmp` file; a failed `History.append` is a directory in place of
`historia-ustawien.jsonl` (that also makes `History.read` fail) or a replaced `History.append`; a memory or Historia
without a read is `chmod 0` (not on Windows). A path that does not happen on the code means the model is wrong until
you show it is not.

## Configurations

| Configuration | What can happen | Expected |
| --- | --- | --- |
| `zwykle` | two saves, one „Cofnij”, one hand edit, one switch-off, no failure of a write | known `zgasniecie-przed-pamiecia` |
| `poczatek-wydania` | the file already holds the Wydanie's value, one failed `Memory.remember_applied` | known `zgasniecie-przed-pamiecia`, `bez-zmian-bez-pamieci` |
| `pamiec-zmian` | one save, one „Cofnij”, one switch-off, one failed `Memory.remember_applied` after the change entered with its row | passes |
| `wiersz` | one save, one „Cofnij”, one hand edit, one switch-off, one failed `History.append`, one failed `_put_back` | known `zgasniecie-przed-pamiecia`, `wiersz-odczytu-nieudany`, `wiersz-i-przywrocenie-nieudane`, `przywrocenie-nieudane` |
| `pamiec` | two saves, one „Cofnij”, one hand edit, one switch-off, one failed `Memory.write` | known `zgasniecie-przed-pamiecia`, `pamiec-niezapisana` |
| `odczyt-pamieci` | one save, one „Cofnij”, two hand edits, one switch-off, the memory once without a read in a snapshot | known `zgasniecie-przed-pamiecia`, `pamiec-bez-odczytu`, `zly-plik-bez-pamieci` |
| `historia-i-zapis` | two saves, one „Cofnij”, one hand edit, two switch-offs, one failed `place.write`, the Historia once without a read | known `zgasniecie-przed-pamiecia`, `zgasniecie-przed-wierszem-wydania` |
| `wydanie-jako-spoza` | no save, one „Cofnij”, one hand edit, two switch-offs, one failed `History.append`, one failed `Memory.write` | known `zgasniecie-przed-pamiecia`, `wiersz-odczytu-nieudany`, `pamiec-niezapisana`, `zgasniecie-przed-wierszem-wydania` |
| `brak-pliku` | no file before the first start, one save, two „Cofnij” (an undo of an undo too), one hand edit, one switch-off | known `zgasniecie-przed-pamiecia` |

## Known findings

A configuration forgives only the findings `model/konfiguracje.json` lists for it (`znane`), each only for its promise
and only for an event that happened with its cause. The causes are path flags the model records as the code runs, never
„the memory differs from the file”: `pamiecZaWierszem` (a row the memory did not take, by a switch-off or a failed
`Memory.write`), the branch of the read (`sciezka`), `bezZmianNiezapamietane`, `przywrocenieWydaniaNieudane` and
`zgasniecieWydania`. Findings 1, 2, 5, 7 and 8 were replayed on the code on 2026-11-19 (main at b3323122fb) with a
scratch script outside the repository, as „Read a result” says, on `centrum-ustawienia.yaml` and its theme.

1. **`zgasniecie-przed-pamiecia`, LiczyZapisanym (open).** `_change` writes the file and appends the row, and Centrum
   switches off before `_remember`; the memory keeps the old `seen` and `good` (the same after the row of
   `_compared`). The owner counts on the next read to see the new file and add a repeated row „spoza”. But when the
   file meanwhile has bad content, `_compared` adds a row „odrzucono” and the last good value it takes from memory is
   the one from before the change; and when the file was meanwhile set back by hand to exactly the old content, there is
   no row at all. Processes compute with the old value while the Historia's newest row shows the new one. The window
   is one `Memory.write`; the bad content is a hand edit or a broken copy. Replayed: Dad saves `light`, `os._exit` in
   `Memory.write`, bad content, a new start: the snapshot has `dark`, the Historia `[tata dark→light, spoza odrzucono]`.
2. **`pamiec-niezapisana`, LiczyZapisanym (open).** The same with a `Memory.write` that raises `OSError`: `_remember`
   only logs, Dad reads `Saved`. Replayed with a folder in place of the memory's `.tmp`: the snapshot after bad content
   has `dark`.
3. **`wiersz-odczytu-nieudany`, LiczyZapisanym (by design).** `History.append` of the row „spoza” fails and `_compared`
   returns the new content: the process computes with a change whose row comes only at the next read, and never when
   the file goes back before it. `test_reczna_zmiana_przy_historii_ktorej_nie_da_sie_dopisac_dostaje_wiersz_przy_nastepnym_odczycie`
   asserts that the change works at once.
4. **`pamiec-bez-odczytu`, LiczyZapisanym (by design).** `Memory.read` gives `Unreadable`, so `_compared` does not
   compare and the process computes with a change from outside Centrum without a row;
   `test_reczna_zmiana_przy_nieczytelnej_pamieci_ustawien_dostaje_wiersz_gdy_pamiec_wroci` asserts it.
5. **`zly-plik-bez-pamieci`, LiczyZapisanym (open).** Bad content while `Memory.read` gives `Unreadable`:
   `_compared` returns `_read(parsed, None)`, so `_value` gives `file.default` instead of Dad's last good value. For
   Reguły ilości (`_or_release` in `_quantity_rules`) and Legenda czynności (`_activity_legend`) the Uruchomienie
   computes with the Wydanie's rules and legend without a refusal; Lista Wykonawców, Foldery and the theme and text of
   the Mail z rozliczeniem refuse or show defaults. Replayed on the theme: Dad saves `light`, bad content, `chmod 0` on
   the memory: the snapshot has `dark` (the default); with the memory readable again, `light`.
6. **`bez-zmian-bez-pamieci`, WydanieNieNadpisuje (by design).** A Zmiana z Wydania with the result „bez-zmian” (no row)
   and a failed `Memory.remember_applied` comes back at the next start and sets its value over what Dad saved since,
   because only the memory of the Zmiany z Wydań records a result without a row.
7. **`wiersz-i-przywrocenie-nieudane`, WydanieNieNadpisuje (open).** The write of a Zmiana z Wydania stays in the file
   without its row because `History.append` and `_put_back` both fail; the next read shows it as a change from outside
   Centrum, Dad undoes it, and the next start applies the change again: a readable Historia without the change's row
   lets the change in again, and Dad's „Cofnij” is lost with it. Replayed by replacing
   `History.append` and the second `replace_atomically` of the file: after Dad's „Cofnij” the snapshot has `dark`, after
   the next start `light`.
8. **`zgasniecie-przed-wierszem-wydania`, WydanieNieNadpisuje (open).** Centrum switches off after the write of a Zmiana
   z Wydania and before its row. The next start gives the change no result (here the Historia cannot be read for that
   one `_release_rows`; a failed `_change` does the same), Dad changes the value the Historia shows as a change from
   outside Centrum, and the start after that sets the Wydanie's value again. A declarative edit repeated after a break
   before its row gives no second difference only when the value did not change in between. Replayed: `os._exit` in
   `History.append` of the change, `chmod 0` on the Historia for the next start, Dad saves `dark`, the start after that
   gives `light` and a row „wydanie dark→light”.
9. **`przywrocenie-nieudane`, NieZapisanoZnaczyNie (by design).** `History.append` and `_put_back` both fail on Dad's
   save: Dad reads „nie zapisano” and the file has his value; the owner leaves it to the next read, which shows it as a
   change from outside Centrum.

Decide 1, 2, 5, 7 and 8 with Maks; when the code changes, the finding disappears and the check says
`ZNALEZISKO ZNIKNĘŁO`.

## Bring the model in line

When a definition from `model/definicje.json` changes:

1. Read the diff against the table above. Find each action whose code changed, or the new step that has none.
2. Change the model so each action is again one indivisible step of the code, and write the code's names in its row of
   the table above, not in a comment: the model has none, and a new action of `Next`, constant or variable gets its own
   row, and a new definition gets one when it models code. TLA+ strings must be ASCII. Never weaken a promise or narrow
   a configuration to make the check pass.
3. A new way to fail gets a constant with its row, a branch guarded by it, and a value in `stale` of every configuration in
   `model/konfiguracje.json`. A new path of a known harm gets its own flag and cause, never a cause as wide as „the
   memory differs from the file”. A new action of `Next` gets its words in `_STEPS` of the script.
4. Break the new path in the model on purpose (remove the guard you just added) and see the check fail; add that break
   to `scripts/check_model_historii_mutations.py` with the code counterpart in its name.
5. Run the check. A new violation is a finding: replay it on the code (Read a result) before you call it a bug, report
   it with the path, and do not change product code unless asked.
6. Run `tools/przesun_model.py verify-historia-ustawien` only after every row of the table describes the code, and write
   in the commit message, in one sentence, what changed in the model and why.

## After changing the model

`.venv/bin/python .agents/skills/verify-historia-ustawien/scripts/check_model_historii_mutations.py` applies each broken
variant of the model to a copy of the checkout (`tools/lib/silnik_mutacji.py`) and must end with `MUTACJE OK`; run it
only to reproduce a red Mutation checks step or while you change the model. Each mutation removes a guard the code has,
and each gives `HISTORIA USTAWIEŃ: NOWE NARUSZENIE`:

- LiczyZapisanym: `_compared` without comparing with the memory (`zwykle`); `_change` without the row (`zwykle`);
  `_compared` that remembers the state although its row failed (`wiersz`).
- NieZapisanoZnaczyNie: `_change` without `_put_back` (`wiersz`).
- CofnijPrzywracaBajty: `_change` without `_restores_absence`, so „Cofnij” writes `file.dump(file.default)` (`brak-pliku`).
- WydanieNieNadpisuje: `_apply_pending` without `_release_rows` (`pamiec-zmian`); `apply_release_changes` without
  `Memory.applied` (`poczatek-wydania`).

`GRANICE` in the script holds, for each cause, its configuration without that one known finding: it must give
`NOWE NARUSZENIE`, so no other cause of that configuration forgives its path.

## Scope

Verified: the four promises over every order of the actions above within the bounds of each configuration (one
settings file, one Zmiana z Wydania, at most two saves, one „Cofnij”, two hand edits, two switch-offs and one failure of
each kind; two „Cofnij” only in `brak-pliku` and in a wider run outside CI, see PR #2174). Assumed, each a reason the check can pass while the code is wrong:

- **One Centrum at a time** on `config/`: the owner's lock is per process; two Centrum on one folder are not checked.
- **`replace_atomically` is atomic** and `History.append` either adds a whole line or a line `History.read` skips.
- **The file is one value.** A file with several keys (a Lista Wykonawców with several Wykonawcy) behaves like one value
  per key; a „Cofnij” of one key while another changed is not checked.
- **A Zmiana z Wydania is declarative**, as `tests/test_centrum_rozliczen.py::test_zmiana_z_wydania_po_utracie_pamieci_wlasciciela_biegnie_drugi_raz_bez_roznicy_i_bez_wiersza` requires, and waits on bad content.
- **`file.default` is one value** (`DOMYSLNA`): an Aktualizacja that changes the Wydanie's defaults between a change and
  its „Cofnij” is not modeled. `_restores_absence` does not compare with `file.default`, and the tests
  `test_cofniecie_zmiany_ktora_utworzyla_plik_po_aktualizacji_zmieniajacej_wartosci_z_wydania_usuwa_plik` and
  `test_cofniecie_zmiany_ktora_utworzyla_plik_po_cofnieciu_pozniejszej_i_aktualizacji_usuwa_plik` check that path;
  a later change of another key that stays after „Cofnij” keeps the file
  (`test_cofniecie_zmiany_ktora_utworzyla_plik_zostawia_plik_z_pozniejsza_zmiana_innego_klucza`).

Left out: the pair of Reguły ilości and Lista Urządzeń (a file that stops fitting the other, `_paired`), secrets,
autostart, removed logins and the periods check, a „Cofnij” whose `file.restore` breaks a rule of the file (a
`FieldProblem`, so `_change` gives `Refused` before any write or row; only the Lista Wykonawców, a file of several keys,
refuses one, and
`test_cofniecie_usuniecia_wykonawcy_po_ktorym_lista_lamalaby_regule_to_odmowa_ze_zdaniem_a_lista_i_historia_bez_zmian`
checks it), the first start without any memory, `_absent`, a file the system
cannot read (`Unreadable` file: processes refuse), a hand edit that lands between the owner's read and its write (the
owner overwrites it without a row, as any file without a lock would), and the Historia or the memory deleted by hand.
