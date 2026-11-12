---
name: verify-karta-uruchomienia
description: Model-check with TLA+ (TLC) how one browser tab of Centrum rozliczeń follows an Uruchomienie procesu and an Aktualizacja narzędzia, under every order of stream events, HTTP answers, Dad's clicks in this tab and in a second tab, an unreadable view, a broken stream and Centrum restarting - that a start or a Decyzja sent from this tab ends (its buttons come back) once the server's last view can be read, that the card shows the result of a finished Uruchomienie instead of the start card unless Dad chose a new Uruchomienie in this tab after that result, and that the Aktualizacja card does not return to „Zaktualizuj narzędzie” while the update it showed is still running. Use when a change touches `RunsProvider`, `streamShows`, `starting` or `deciding` in `frontend/src/lib/runs.tsx`, `useAction` in `frontend/src/lib/action.ts`, `RunOrSetup` in `frontend/src/pages/runs/runs-page.tsx`, a `setDraft` or a start button gated by `starting`, `watchRunEvents` in `frontend/src/api/centrum.ts`, `ToolUpdateProvider` in `frontend/src/lib/tool-update.tsx` or `ToolUpdateButton`/`ToolUpdateStatus` in `frontend/src/components/tool-update.tsx`, or `RunHost.start`, `RunHost.decide`, `_event_stream`, `ToolUpdates.start` or `ToolUpdates.current` on the server.
pilnuje:
  - frontend/src/lib/runs.tsx
  - frontend/src/lib/action.ts
  - frontend/src/lib/tool-update.tsx
  - frontend/src/components/tool-update.tsx
  - frontend/src/api/centrum.ts
  - frontend/src/pages/runs/runs-page.tsx
  - frontend/src/pages/runs/run-card.tsx
  - frontend/src/pages/runs/run-dialogs.tsx
  - frontend/src/pages/runs/run-setup-card.tsx
  - frontend/src/pages/runs/outside-period-card.tsx
  - frontend/src/pages/periods/prepare-actions.tsx
  - frontend/src/pages/filling/ready-for-settlement.tsx
  - frontend/src/pages/worker-reports/report-entering.tsx
  - src/rozliczenia/centrum/runs.py
  - src/rozliczenia/centrum/tool_updates.py
  - tools/lib/model_tlc.py
  - tools/lib/rozjazd_modelu.py
  - tools/lib/narzedzia_tlc.py
ci: .agents/skills/verify-karta-uruchomienia/scripts/sprawdz_karte_uruchomienia.py
---

# Verify karta Uruchomienia (TLA+)

## What CI runs and what stays local

CI runs `sprawdz_karte_uruchomienia.py` (the `ci:` key) in Mutation checks whenever a change touches this skill's
`pilnuje:` or folder, so run it locally only while you bring the model in line or to reproduce a red Mutation checks
step. In CI the Mutation checks step does not start while covered code differs from its digests in `model/definicje.json`: it fails with a `ROZJAZD MODELU Z KODEM | <skill>: …` line, but it cannot tell whether your change to the model is right.
`tools/szybko.py` fails on the same drift before you push (step `rozjazd modelu`, without TLC) whenever the change would run this check on a pull request; one module, `tools/lib/rozjazd_modelu.py`, decides what drift is for both.
`check_model_karty_mutations.py` runs on a pull request that changes a file in `model/`, the script itself or
`sprawdz_karte_uruchomienia.py`, and in full CI and nightly on `main` after a change of this skill's folder.
What stays with you on every change to the covered code is „Bring the model in line, then run”: read the diff against
the table, change the model, break the new path in it, and run the check while you do. A change whose model nobody
brought in line is not verified, whatever CI says.

The frontend has no unit-test runner (`frontend/package.json`: typecheck, oxlint, knip, jscpd, `rules`), and
`CODING_STANDARDS.md` proves UI behaviour in the browser with `verify-centrum-rozliczen`. That skill drives one order of
events per feature; this one checks every order of the events below on a model of the same code.

## The promises

Centrum rozliczeń shows one Uruchomienie procesu at a time on every tab (`RunsProvider`, one event stream per visible
tab). A start or a Decyzja sent from a tab keeps its buttons disabled until the stream shows the change (the comment
above `starting` in `runs.tsx`: „Przycisk startu i okno decyzji znikają dopiero, gdy strumień pokaże zmianę, więc start
i decyzja trwają do tej chwili”). The panel (`RunOrSetup`) shows the start card, the live view or the last result, and
`draft` means both „Okres i proces wybrane w innym miejscu … do formularza nowego Uruchomienia” and „show the start
card instead of the result”. The model checks three promises over every order of steps:

- **PrzyciskWraca** (temporal): a start or a Decyzja sent from this tab ends (`starting`/`deciding` return to `null`,
  so every start button and the Decyzja buttons are enabled again) whenever the server's last view can be read: the
  stream came back to readable, or Centrum started again with a readable `idle` (the comment in `starting`: „`idle`
  znaczy wtedy, że serwer zgubił Uruchomienie (Centrum uruchomione ponownie …)”).
- **WynikNaKarcie**: when the tab reads the `finished` view of an Uruchomienie, the panel shows that result, not the
  start card, unless Dad in this tab chose a new Uruchomienie after that result reached it (`newRun` on the result
  card, or a `setDraft` while the result was the tab's view). The moment between a start from this tab and its answer
  (`setDraft(null)` has not run yet) is left out.
- **AktualizacjaNieWraca**: once the page has shown an Aktualizacja narzędzia as running, the card does not return to
  an enabled „Zaktualizuj narzędzie” (`busy` false) while that update is still running on the server or Centrum is
  closed for its restart (`ToolUpdateProvider`: „Start wysłany albo aktualizacja trwa: każdy przycisk aktualizacji jest
  wtedy wyłączony”).

Harm: for the first, Dad cannot start anything or answer a Decyzja until he refreshes the page, and nothing on the
start card tells him why. For the second, Dad never sees the result (its Komunikaty, „Otwórz plik zbiorczy”, the
Zatrzymanie and „Wyślij do Maksa”) and finds it only in Historia. For the third, Dad sees „Zaktualizuj narzędzie” in
the middle of an update, clicks it and gets a refusal; worse, the card stops polling and never reloads into the new
version.

## Does the change touch it?

The check runs a hand-written TLA+ model, `model/KartaUruchomienia.tla`, not the code. It describes the code only
while you keep the two in step. Each model action is one indivisible step: one task of the browser's event loop (a
stream message, the continuation after an HTTP answer, a click) or one request the server handles under its lock.

| Model action | Code |
| --- | --- |
| `KlikStart` | a start button whose `start` reaches `useAction` `starting` (`runs.tsx`): the start card's „Podgląd bez zapisu”, „Uruchom” and Wycena modes (`run-setup-card.tsx`, disabled by `starting`), `IntermaxCard` (`outside-period-card.tsx`, disabled by `starting`), „Wpisz raporty z maili” (`report-entering.tsx`, disabled by `starting` and `isActive(view)`), the preview of the next step on the Tablica okresów (`prepare-actions.tsx` `PreviewAction`, only when `!isActive(view)`) and „Uruchom ponownie” (`rerun`). `useAction.run` ignores the click while `inFlight` (`action.ts`); otherwise `before = shownRun(latest.current)` and `fetch` `startRun` |
| `KlikDecyzja` | `DecisionDialog` (`run-dialogs.tsx`) in `RunOrSetup` on an `awaiting_decision` view, disabled while `deciding` is this Uruchomienie; `useAction` `deciding`, `fetch` `decideRun` |
| `NoweUruchomienie` | `NewRunButton` on the result (`RunCard` on `finished`, `run-card.tsx`; `PastRunCard` on `idle` with `previous`): `newRun` = `setDismissed(run.id)` |
| `WyborNaKarcieStartu` | `RunSetupCard` (`run-setup-card.tsx`): `onValueChange` of the process tiles and of the period: `setDraft` |
| `WyborSpozaKarty` | `setDraft` outside the start card, at any time: `DraftButton` in the Tablica okresów (`prepare-actions.tsx`), `ReadyForSettlement` („Gotowe, rozlicz pracowników”, `ready-for-settlement.tsx`), `rerun` of a Wycena w efenix |
| `OdpowiedzStartu` | `starting` after `await startRun(...)`: a refusal or a network error ends the action (toast, `draft` stays); an accepted start runs `setDraft(null)`, returns when `shownRun(latest.current) === accepted`, and otherwise awaits `streamShows((next) => shownRun(next) !== before \|\| next.state === "idle")` |
| `OdpowiedzDecyzji` | `deciding` after `await decideRun(...)`: an error ends it; otherwise it awaits `streamShows((next) => !awaitsDecision(next, runId))` only while `awaitsDecision(latest.current, runId)` |
| `Odbierz` | `watchRunEvents` `message` (`centrum.ts`): `zRunEvent.safeParse`; a readable event is `onEvent` (`announce`, `latest.current`, `setView`, `setUnreadable(false)`, every `awaited` whose `shows` passes is resolved), an unreadable one only `onUnreadable` (`setUnreadable(true)`). The server sends the next view after the connection's `seen` (`_event_stream`, `RunHost.events_after`; after a start trimmed `_events`, the first one left) |
| `Zerwij` | `EventSource` `error` (`onConnection(false)`) or the tab hidden (`followVisibility` closes the stream) |
| `Polacz` | `EventSource` reconnects (`retry`) or the tab is visible again: `open`, and `_event_stream` sends the current view first |
| `ObslugaStartu` | `RunHost.start` under its lock: `run_in_progress` refusal while an Uruchomienie runs; otherwise a new `Run`, `_events` trimmed to its last view and the start view published before the answer |
| `ObslugaDecyzji` | `RunHost.decide` under its lock: `unknown_run`/`not_awaiting_decision` refusal, or `Run.answer` and the `running` view published before the answer |
| `InnaKartaStart`, `InnaKartaDecyzja` | the same server steps for a request from a second tab or window; its own refused requests change nothing and are left out |
| `PytanieODecyzje` | `Run.confirm`: the `awaiting_decision` view; today only Przygotowanie pliku zbiorczego asks, once per Uruchomienie (`collective_preparation`) |
| `KoniecUruchomienia` | `RunHost.end`: the `finished` view (result or Zatrzymanie) and the end under one lock |
| `Restart` | Centrum killed and started again: a new `RunHost` with `idle` (`previous` from the Logi), the tab's stream gets `error`, a request the old server did not handle fails |
| `KlikAktualizuj` | `ToolUpdateButton` (`components/tool-update.tsx`, disabled only by `busy`, so also before the first read answers): `useAction` `starting`, `setClicked(true)`, `getHealth` |
| `ZdrowieStartu` | `.then(health => { instance.current = health.instance; return startToolUpdate() })`; no answer ends the action with a toast |
| `ObslugaStartuAkt` | `ToolUpdates.start`: `begin_update` (refused while an update runs) and the first step `running` as the answer |
| `KoniecStartuAkt` | `.then(show)` of the start; a refusal is a toast and the card keeps its state |
| `Wejscie` | a page with the update button mounts: the provider's first read and `ToolUpdateStatus` (`React.useEffect(read, [read])`) send `getToolUpdate` with no request number |
| `ObslugaOdczytu`, `ObslugaPetli` | `GET /api/tool-update`: `ToolUpdates.current` at the moment the server handles it; a closed Centrum does not answer |
| `OdbierzOdczyt` | `read`: `getToolUpdate().then(show, failRead)`; answers arrive in any order, and `failRead` leaves `update` as it is |
| `Tik` | the effect on `update?.state === "running"`: after `POLL_MS` `getHealth`; the cleanup clears the timer, never a request already sent |
| `ZdrowiePetli` | `getHealth().then`: `instance.current ??= health.instance`; another instance is `sessionStorage` and `window.location.reload()` (the new page reads again), the same one is `getToolUpdate()`; no answer is `.catch(() => show({state: "running", step: "restarting"}))` |
| `OdbierzPetli` | `getToolUpdate().then(show)` in the poll, with no request number either; its failure goes to the same `.catch` |
| `AktPorazka` | `ToolUpdates._update`: a failure before the restart (`failed`, same Centrum) |
| `AktZamkniecie`, `AktPonownyStart` | `ToolUpdates._restart`: Centrum closes, the restart guardian starts the new one (another `instance`), which reads the result once (`_after_restart`: `updated` or `failed`) |

The script compares these definitions with their digests (`model/definicje.json`, a name is a path from the module):
the whole files `frontend/src/lib/runs.tsx`, `frontend/src/lib/action.ts`, `frontend/src/pages/runs/runs-page.tsx`,
`frontend/src/lib/tool-update.tsx` and `frontend/src/components/tool-update.tsx` (a TypeScript file has no digest per
function, so any change in them moves the model); `RunHost.start`, `RunHost.decide`, `RunHost.events_after`,
`RunHost.end`, `RunHost._publish_locked`, `Run.confirm` and `_event_stream` in `src/rozliczenia/centrum/runs.py`;
`ToolUpdates.current`, `ToolUpdates.start`, `ToolUpdates._restart` and `ToolUpdates._after_restart` in
`src/rozliczenia/centrum/tool_updates.py`.
The other files in `pilnuje:` are not in `model/definicje.json`, but they hold the guards of `KlikStart`, `KlikDecyzja`,
`NoweUruchomienie`, both `Wybor…` actions and `Odbierz`: a change of when a button there is enabled, a new `setDraft`
or `start`, or a change of `watchRunEvents` in `frontend/src/api/centrum.ts` moves the model though no digest changes.
A new place that calls `start`, `setDraft`, `decide` or `useToolUpdate().start` does too: add it to the table.

The digests in `model/definicje.json` were taken when every row of the table was last checked against the code
(`tools/przesun_model.py`); what that check found is in the message of the commit that changed the digests. Check what
changed since: `git diff $(git log -1 --format=%h -- .agents/skills/verify-karta-uruchomienia/model/definicje.json)
-- frontend/src/lib frontend/src/components/tool-update.tsx frontend/src/pages frontend/src/api/centrum.ts
src/rozliczenia/centrum/runs.py src/rozliczenia/centrum/tool_updates.py`.

## Run

```sh
.venv/bin/python .agents/skills/verify-karta-uruchomienia/scripts/sprawdz_karte_uruchomienia.py
py -3 .agents\skills\verify-karta-uruchomienia\scripts\sprawdz_karte_uruchomienia.py
```

`--config NAME` runs one configuration, `--strict` fails also on known findings. The run of TLC, the verdict and the
known findings are `tools/lib/model_tlc.py`, which every skill with a TLA+ model shares; Java and `tla2tools.jar` come
from `tools/lib/narzedzia_tlc.py` (pinned `jdk4py` and the jar in `.verification/` on first use; `TLC_JAVA` and
`TLC_JAR` override them). The whole check took 41 s on Maks's Mac (2026-11-12): `druga-karta` 10 s, `restart` 20 s, `aktualizacja` 9 s.

The last line is the verdict:

- `KARTA URUCHOMIENIA OK` or `KARTA URUCHOMIENIA OK, ZNANE ZNALEZISKA: n`: every configuration ends as
  `model/konfiguracje.json` says. Exit 0 (1 with `--strict` and known findings).
- `KARTA URUCHOMIENIA: NOWE NARUSZENIE (n)`: a promise breaks on a path that is not a known finding. Exit 1.
- `KARTA URUCHOMIENIA: ZNALEZISKO ZNIKNĘŁO (n)`: a known finding no longer happens. Describe the change below and
  remove it from `znane` of its configuration in `model/konfiguracje.json`. Exit 1.
- `KARTA URUCHOMIENIA: BŁĄD MODELU (n)`: TLC gave no verdict, an invariant outside the promises such as `TypeOK` broke,
  `model/konfiguracje.json` has another shape, or the counterexample's story in the script does not know every action
  of `Next`. Exit 2.
- `UWAGA: kod opisany modelem zmienił się: …` above the verdict: a definition in `model/definicje.json` differs from its
  digest there, and the verdict means nothing until you bring the model in line. CI does not run the check then.

Each counterexample is told as numbered steps in the code's words, with every shown variable that the step changed
(the server's Uruchomienie and its state, the tab's view, `draft`, the start and the Decyzja in flight, and both sides
of the Aktualizacja).

## Read a result

Read every result with the pstack `/statechart` skill: give it `model/KartaUruchomienia.tla` and one configuration with
the `Wybaczone…` constants as they are (empty), and it shows each broken promise as its shortest path in plain words;
on a passing configuration it draws how the tab moves between the start card, the live view, the Decyzja and the
result.

Then tell a real bug from a modeling error: replay the path on the real build. Serve Centrum on the synthetic fixture
of `verify-centrum-rozliczen` (`create_centrum_fixture.py`, `serve_centrum.py`), open it in Playwright with
`EventSource` replaced by an init script that hands the page the views you push, hold the answer of `POST /api/runs`,
`POST /api/runs/{id}/decision` or `GET /api/tool-update` until the step of the path, and look at the buttons.
To hold a read that more requests follow, wrap `fetch` in an init script that keeps the response from the page until you release it: a `page.route` handler that returns without answering and is fulfilled later stopped Playwright from routing the page's next requests (2026-11-12), so the poll looked stopped also where it was not.
A path that does not happen on the build means the model is wrong until you show it is not.

## Configurations

| Configuration | What can happen | Expected |
| --- | --- | --- |
| `jedna-karta` | one tab, two starts, a Decyzja, one unreadable view, one broken stream | known `wybor-przed-wynikiem` |
| `druga-karta` | a second tab starts and answers the Decyzja, two starts in all | known `wybor-przed-wynikiem`, `druga-karta`, `cudze-uruchomienie-przed-odpowiedzia` |
| `restart` | Centrum starts again once at any moment, two starts, a Decyzja, one unreadable view | known `wybor-przed-wynikiem`, `restart-przed-odpowiedzia` |
| `aktualizacja` | two page entries with a read, two updates, a failure or a restart, one reload, a click before the first read | known `stary-odczyt`, `stary-odczyt-petli` |

`Czesc` picks the part of the tab the configuration runs; the other part's actions stay disabled. Every
configuration lets an Uruchomienie end with a result only (`MozeZatrzymac = FALSE`): a Zatrzymanie is the same
`finished` view to the tab, and the statechart for Dad turns it on.

## Known findings

Each finding is forgiven only for its promise and only when its cause happened before the event that breaks it (the
variable `slady`, and for WynikNaKarcie the history of the Uruchomienie whose result is hidden); any other path is a
new violation. Each was replayed on the real build of 12.11.2026 (Centrum on the synthetic fixture, the page as built,
`EventSource` replaced, answers held with `page.route`, findings 5 and 6 with a wrapped `fetch`).

1. **`wybor-przed-wynikiem`, WynikNaKarcie.** Dad sets `draft` before this tab has read the result of an Uruchomienie
   the server already runs: a step in the Tablica okresów (`DraftButton`), „Gotowe, rozlicz pracowników”, or a tile on
   the start card while the tab still shows the start card (the start view was unreadable or not delivered yet). Only
   an accepted start from this tab clears `draft`, so when the result arrives `RunOrSetup` sees `ended && draft !==
   null` and shows the start card. Replayed: a running view, „Wyceń w efenix” in the Tablica okresów, the finished
   view: the start card, no result.
2. **`druga-karta`, WynikNaKarcie.** An Uruchomienie started in a second tab does not clear `draft` of this tab, so a
   tile Dad picked on the start card before it started, or a start of this tab the server refused because it ran,
   hides its result behind the start card. Replayed: tile „Przebieg rozliczeń”, then running and finished views of
   another Uruchomienie: the start card; the same after a 409 to this tab's „Podgląd bez zapisu”.
3. **`cudze-uruchomienie-przed-odpowiedzia`, PrzyciskWraca.** The answer to a start reaches the tab after the stream
   has shown the end of that Uruchomienie and a whole Uruchomienie from a second tab. `starting` returns only when
   `latest.current` shows the accepted Uruchomienie, so it awaits one more view, and none comes: every start button
   stays disabled until the page is refreshed. Replayed: answer held while the stream showed running and finished of
   `y` and of `z`; after „Nowe Uruchomienie procesu” „Podgląd bez zapisu” was still disabled 3 s later.
4. **`restart-przed-odpowiedzia`, PrzyciskWraca.** The same when the answer arrives after the stream already shows
   the `idle` of a restarted Centrum: the comment says `idle` before the answer is „zwykły stan świeżo uruchomionego
   Centrum”, but this `idle` comes from the new Centrum, and nothing follows it. Replayed: answer held while the stream
   showed `idle`; „Podgląd bez zapisu” disabled 3 s later, the start card with no explanation.
5. **`stary-odczyt`, AktualizacjaNieWraca.** `read()` (the provider's first read and `ToolUpdateStatus` on mount)
   sends `getToolUpdate` with no request number. A read sent when the page mounted (state `idle`) whose answer arrives
   after the start answered `running` replaces `running` with `idle`: „Zaktualizuj narzędzie” is enabled again,
   „Pobieranie nowej wersji…” disappears, the poll stops (the effect runs only on `running`), and the tab will not
   reload into the new version. The model counts only answers of `read()` here (`OdbierzOdczyt`). Replayed on
   Konfiguracja: the first read's answer kept from the page until after the click; button enabled, no status, 0 reads
   in the next 2 s (without the held answer: disabled, status shown, 3–4 reads).
6. **`stary-odczyt-petli`, AktualizacjaNieWraca.** The poll's `getToolUpdate` has no request number either, and the
   effect's cleanup clears only the timer, never a chain already past `setTimeout`. Update 1 runs; the poll sends
   `getHealth`, then `getToolUpdate`; update 1 fails and the server answers that read `failed`, but the answer is late.
   Meanwhile a page entry's `read()` shows `failed` (the effect stops on a state that is not `running`), Dad clicks
   „Zaktualizuj narzędzie” again and the start answers `running` (a new timer of `POLL_MS`). The late poll answer
   arrives before that timer fires: `show(failed)` puts back update 1's Komunikat porażki, enables the button during
   update 2, clears the new timer, and the tab neither polls nor reloads into the new version. A request number on
   `read()` alone does not fix it, and the mutation script proves each fix removes only its own finding. Replayed on
   Konfiguracja: the poll's answer `failed` kept from the page while Dad went to Tablica okresów and back (`failed`
   shown) and clicked again, then released; button enabled, update 1's Komunikat shown, no „Pobieranie…”, 0 reads in
   the next 2 s (released before leaving the page: disabled, „Pobieranie…”, 4 reads).

Findings 3 and 4 need an answer that reaches the tab later than whole Uruchomienia or a restart, and findings 5 and 6
an answer that reaches it later than a newer one; on Dad's computer the answer usually comes in milliseconds, so they
are rare, but nothing in the code rules them out.

## Bring the model in line

When a definition from `model/definicje.json` or a guard in another file of `pilnuje:` changes:

1. Read the diff against the table above. Find each action whose code changed, or the new step that has none.
2. Change the model so each action is again one indivisible step of the code, with the code's names in its comment.
   Never weaken a promise or narrow a configuration to make the check pass. A new action of `Next` gets its words in
   `_STEPS` of the script, or the check ends with `BŁĄD MODELU` before TLC.
3. Break the new path in the model on purpose (remove the guard you just added) and see the check fail; add that break
   to `scripts/check_model_karty_mutations.py` with the code counterpart in its name.
4. Run the check. A new violation is a finding: replay it on the build (see Read a result) before you call it a bug,
   report it with the path, and do not change product code unless asked.
5. Run `tools/przesun_model.py verify-karta-uruchomienia` only after every row of the table describes the code, and
   write in the commit message, in one sentence, what changed in the model and why.

## Scope

Verified: the three promises over every order of the actions above for the bounds of each configuration (two starts,
one Decyzja per Uruchomienie, one unreadable view, one broken stream, one restart, two updates, two reads, one poll
chain, one reload).
The server is only the source of views and answers; its slot „jedno naraz” and the rule that the result of every
Uruchomienie stays among the views a tab reads (`WYNIK_NA_KARCIE`) belong to `verify-jedno-uruchomienie-naraz`.

Left out, each a reason the check can pass while the code is wrong:

- **Progress views** (`running` → `running` with new progress, `show_report` on a result). They are more views of the
  same Uruchomienie: they can only end a start or a Decyzja earlier and do not change the panel.
- **An unreadable view is unreadable on every delivery.** A view's readability is fixed when it is published (a page of
  an older version reads the same shape the same way). A view that is unreadable once and readable on a reconnect only
  adds paths that end earlier.
- **A second Decyzja in one Uruchomienie.** Today only Przygotowanie pliku zbiorczego asks, once (`srvPytal`). With
  `PytanieODecyzje` allowed twice TLC breaks PrzyciskWraca in `jedna-karta` (2026-11-12): the answer to the first
  Decyzja reaches the tab after the stream showed `running` and the second Decyzja, so `deciding` awaits a view without
  a Decyzja that never comes, the second Decyzja's buttons stay disabled and the Uruchomienie waits for Dad forever.
  Lift the bound in the model before a process asks twice.
- **The previous view of `idle`** (`PastRunCard`, the result of the last Uruchomienie before Centrum started). The model
  keeps `previous` and the panel shows it, but WynikNaKarcie covers only `finished` views of this Centrum.
- **A tab that never showed the update running.** A start refused because another tab updates (`update_in_progress`)
  leaves „Zaktualizuj narzędzie” enabled during that update; AktualizacjaNieWraca promises only what this page showed.
  The state `up_to_date` („Masz najnowszą wersję”) is left out as one more state that is not running.
- **Two poll chains at once.** The poll in the model has one chain in flight, so its next `Tik` waits for the answer.
  The code starts a new timer on every new `update` while running (each step, each poll answer) and the cleanup does
  not cancel a chain already sent, so two chains can be in flight. An old chain's answer that replaces a newer state is
  checked (finding 6: its answer is from an update that has ended); two chains of the same update only add answers
  of that update, which are `running` or its result.
- **Dad's choices in the form other than `draft`** (which process and period), the Komunikaty, the toasts and timing:
  `POLL_MS`, the stream's poll every 50 ms and `retry` are left out, so every order counts, however unlikely.

## Files

- `model/KartaUruchomienia.tla`: the model, with the code each action describes.
- `model/konfiguracje.json`: the configurations (description, constants and known findings; the script writes each
  `.cfg` with `TypeOK`, every promise and the temporal property `PrzyciskWraca`).
- `model/definicje.json`: the definitions of the code the model describes.
- `scripts/sprawdz_karte_uruchomienia.py`: runs TLC on every configuration and tells each counterexample.
- `scripts/check_model_karty_mutations.py`: proves the check fails when the model loses a guard the code has; run it
  through `.venv/bin/python .agents/skills/verify-karta-uruchomienia/scripts/check_model_karty_mutations.py` only to
  reproduce a red Mutation checks step or while you change the model.
