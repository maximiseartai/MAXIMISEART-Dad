# Powiadomienia

The bell in the header, right of `Napisz do Maksa`, opens the view Powiadomienia
(`#/powiadomienia`), which has no sidebar entry. The view lists Dad's sent Uwagi
taty and Zgłoszenia, newest first, each with its colored tag (`Uwaga`,
`Zgłoszenie`) and state: `Wysłana do Maksa.`, `Wyślę do Maksa, gdy będzie
internet.`, `Token do Zgłoszeń nie działa. Skontaktuj się z Maksem.` with the error icon (no token, or one the skrzynka
refuses), `Tej Uwagi nie da się wysłać. Skontaktuj się z Maksem.` with the
error icon (the skrzynka rejected its content; a Zgłoszenie: `Tego Zgłoszenia`), `Rozwiązana. Będzie w następnej wersji.` (Maks closed the issue as
`completed` or without a reason) or `Maks przeczytał.` (`not_planned` or
`duplicate`); a Zgłoszenie takes the neuter forms `Wysłane do Maksa.` and
`Rozwiązane. Będzie w następnej wersji.`. A Zgłoszenie is named by its
„Co się stało”, without the code; one recorded before Powiadomienia, without a
„Co się stało”, has no row. A Zgłoszenie that waits in the queue of the
skrzynka reads what it waits for like an Uwaga, and features/zgloszenie.md
checks those rows (`zgloszenie-bez-klucza`, `zgloszenie-odrzucone`), features/uwaga-taty.md
the rejected Uwaga (`uwaga-odrzucona`). Only Maks's states are new: they light a red
dot on the bell. Entering the view marks them read at once (the dot goes out),
and the rows that were new keep a small dot and a light background until Dad
leaves. Centrum asks the skrzynka Zgłoszeń about Dad's open cases at start and
at most once per 10 minutes of its clock, one question per kind of case (label);
no network passes silently with the last known state.

Every Wydanie among the last 30 published (GitHub Releases, no drafts or
pre-releases) up to the newest one on `main` is a
Powiadomienie o nowej wersji `Nowa wersja 0.x.y` with the green tag `Nowa
wersja`: its note under the heading `Co nowego`, with the intro sentence and each `- ` line of the note as a point of a
bulleted list (a note without points stays one paragraph), and the list `Rozwiązane sprawy` with the cases
sent from this computer that it solves (`Uwaga: <tytuł>`, `Zgłoszenie: <Co się
stało>`). The one Centrum offers the update to (`update_offered`, the same rule
as Konfiguracja) stands in its own card above the list with `Zaktualizuj
narzędzie`; once Dad is on it, it goes back to the list as history, read and
without the button. Only that card is new and lights the dot; older Wydania
are history. A higher Wydanie from outside `main` is no Powiadomienie.
Centrum asks GitHub for the Wydania with the same rhythm as the skrzynka, one
question for the list of Releases per 10 minutes.

## Sub-features

- `powiadomienia-dzwonek`: on all four pages the bell sits right of `Napisz do Maksa`; `GET /api/notifications` has the sent Uwaga as `uwaga`, `wyslana`, not new, and the open Zgłoszenie of `zgloszenie` as `zgloszenie` named by its „Co się stało”; `unread` counts the new ones.
- `powiadomienia-zamkniete`: after Maks closes the Uwaga as `completed` and the Zgłoszenie as `not_planned`, 10 minutes later the bell is `Powiadomienia, są nowe`; Centrum asked at most once per label, and a second page within 10 minutes asks nothing.
- `powiadomienia-oznaczenie-bez-odpowiedzi`: entering the view while marking read gets no answer (`/api/notifications/read` aborted, harness) shows one error notification with `Centrum rozliczeń nie odpowiada.`; the server's `unread` stays above 0 and, after a reload of Okresy, the bell is `Powiadomienia, są nowe`.
- `powiadomienia-widok`: the bell opens the view in the same tab with no sidebar item current; the Uwaga row says `Rozwiązana. Będzie w następnej wersji.`, the Zgłoszenie row `Maks przeczytał.`, both with the mark `nowe` and `data-fresh="true"`; the bell is plain `Powiadomienia` at once, the server's `unread` is 0 and `config/powiadomienia.json` keeps the read ids; no alert, no error toast; both themes.
- `powiadomienia-po-wyjsciu`: after Okresy and back, no row has the mark `nowe`.
- `powiadomienia-brak-sieci`: without network, Maks closing another Uwaga changes nothing 10 minutes later: Centrum asks, the row still says `Wysłana do Maksa.`, the bell has no dot, and there is no alert.
- `powiadomienia-nowa-wersja`: GitHub names v0.2.0 the newest Wydanie on `main`, newer than the tool, with v0.1.0 before it and v0.3.0 published from outside `main`; 10 minutes later the bell is `Powiadomienia, są nowe` after one question for the Releases; the view has the card `Nowa wersja 0.2.0` above the list with `Co nowego`: the intro and its three points as a list, exactly the Uwaga and the Zgłoszenie sent from here (not the case from another computer) and an enabled `Zaktualizuj narzędzie` without `Masz najnowszą wersję.` (in `all` earlier features get that result for an older Wydanie); `Nowa wersja 0.1.0` is a row without a button whose note without points is one paragraph; no v0.3.0; both themes.
- `powiadomienia-aktualizacja`: the card's button starts the Aktualizacja narzędzia; v0.2.0 never was the tip of `main` in the local origin, so the card says `Masz najnowszą wersję.` and the clone stays on its commit.
- `powiadomienia-wydanie-aktualne`: with v0.2.0 on the tool's own commit, there is no card above the list; the row `Nowa wersja 0.2.0` has the intro and the three points, no button and no mark `nowe`, and `update_offered` is `false`.
- `powiadomienia-wydania-brak-sieci`: without network, 10 minutes later Centrum asks GitHub and both rows `Nowa wersja` stay as they were, with no alert and no dot.
- `powiadomienia-plik-niedostepny`: while another program holds `config/sprawy-taty.json` and `config/powiadomienia.json`, Maks closing an Uwaga shows the row `Rozwiązana. Będzie w następnej wersji.` and above the list the Komunikat that names both files as niedostępne, never uszkodzone; both files stay as they were. Once the program lets them go, the next read of Powiadomienia saves both and the Komunikat is gone.

## How to get to it (user POV)

- The bell icon `Powiadomienia` in the header of every page, right of `Napisz do Maksa`.

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run with `DOCTOR OK` by `serve_centrum.py`, with the file skrzynka `<root>/skrzynka-zgloszen/`, its question log `<root>/skrzynka-zgloszen-zapytania.jsonl` (one line with the `label` per question that includes closed issues; the drive counts only `zgloszenie` and `uwaga-taty`, since Logi Uruchomienia ask too), and the clock shift `<root>/zegar/przesuniecie-min.txt`. The drive needs the Zgłoszenia of `zgloszenie` and the two Uwagi of `uwaga-taty` in the skrzynka; run alone, it drives those first. It writes the synthetic key to `config/zgloszenia-klucz.txt` and empties it at the end.

- **Bell.** Shift the clock by 10 minutes. For each page `#/<id>`: reload, wait for its heading and network idle; button `Powiadomienia` (prefix) in `header` is visible right of button `Napisz do Maksa`. `GET /api/notifications` (`api/powiadomienia-wyslane.json`): the newest Uwaga is `{"kind": "uwaga", "state": "wyslana", "unread": false}`, the open Zgłoszenie has `what` equal to its issue title after `KOD: `; `unread` is the sum of `unread`. Screenshot `180`.
- **Closed.** Harness: in `<root>/skrzynka-zgloszen/<n>.json` set `state` `closed`, `state_reason` `completed` and `closed_at` for the newest Uwaga, and `not_planned` for the open Zgłoszenie, and shift the clock by 10 minutes. Enter Okresy: the bell's name is `Powiadomienia, są nowe`; the question log grew by at most two lines. Enter Uruchomienia: no new line. Screenshot `181` and the header close-up `181b`.
- **Marking without an answer.** Route `**/api/notifications/read` to abort and click the bell: the view's heading appears and the error notification (`region` `Notifications` → `dialog` `Nie udało się`) holds `Centrum rozliczeń nie odpowiada.`; capture `181c`. Remove the route; `GET /api/notifications` still has `unread` above 0. `page.goto(<url>#/okresy)` and `page.reload()` (which drops the notification): the bell's name is `Powiadomienia, są nowe`.
- **View.** Click the bell: heading `Powiadomienia`, URL ends with `#/powiadomienia`, the menu `Sekcje Centrum rozliczeń` has no `Powiadomienia` link and no `aria-current`. In list `Powiadomienia`, listitem `Uwaga: <title>` contains `Rozwiązana. Będzie w następnej wersji.` and listitem `Zgłoszenie: <Co się stało>` contains `Maks przeczytał.`; each has the label `nowe` and `data-fresh="true"`. The bell's name is `Powiadomienia`. `GET /api/notifications` (`api/powiadomienia-przeczytane.json`) reaches `unread` 0; `config/powiadomienia.json` has `schema_version` 1 and at least two ids. No `alert`, no error toast. Screenshot `182`; toggle the theme, the mark stays, screenshot `183`; toggle back.
- **After leaving.** Sidebar `Okresy`, then the bell: no label `nowe` in the list, the bell is plain `Powiadomienia`.
- **No network.** Create `<root>/skrzynka-zgloszen/brak-sieci`, close the older Uwaga (`completed`), shift the clock by 10 minutes, open `#/powiadomienia` afresh: the question log grew, the older Uwaga still says `Wysłana do Maksa.`, no `alert`, no error toast, the bell has no dot. Screenshot `184`. Remove `brak-sieci` (also in `finally`).
- **New version.** Harness: write to `<root>/github/` the tag `v0.2.0` (`wydanie.txt`), 40 × `e` (`main-commit.txt`, a commit the clone does not contain) and `wydania.json` in GitHub's shape: v0.3.0 (`Wydanie spoza main.`), v0.2.0 with the note `SUMMARY` (the intro `INTRO`, then one `- ` line per item of `POINTS`) and its list `## Rozwiązane sprawy taty` naming the newest Uwaga, the closed Zgłoszenie and `Uwaga taty #999`, and v0.1.0 (`FIRST_SUMMARY`). Shift the clock by 10 minutes. Enter Okresy: the bell is `Powiadomienia, są nowe`; enter Uruchomienia: `<root>/github/zapytania-wydan.jsonl` grew by exactly one line. Click the bell: region `Nowa wersja 0.2.0` (exact) has region `Co nowego` with heading `Co nowego`, the paragraph `INTRO` and listitems exactly `POINTS` (no `- `), its list `Rozwiązane sprawy` has exactly `Uwaga: <title>` and `Zgłoszenie: <Co się stało>`, its button `Zaktualizuj narzędzie` is enabled, `GET /api/tool-update` (`api/powiadomienia-nowa-wersja-aktualizacja.json`) is not `up_to_date` and the card has no status `Masz najnowszą wersję.`, and it has the label `nowe`; it stands above list `Powiadomienia`. In the list, listitem `Nowa wersja 0.1.0` has in region `Co nowego` the paragraph `FIRST_SUMMARY`, no listitem and no button. Neither `Nowa wersja 0.3.0` nor `Uwaga z innego komputera` is on the page. `GET /api/notifications` (`api/powiadomienia-nowa-wersja.json`) reaches `unread` 0 and has `0.2.0` with `update_offered` `true` and `0.1.0` with `false`. No alert. Screenshot `185`; toggle the theme, screenshot `186`; toggle back.
- **Update.** Harness: the local origin's only Wydanie is the clone's `HEAD` (`release_only`; in `all` it already is). Click the card's button: the Centrum log gets one more `aktualizacja-koniec`, with `wynik=AKTUALNA`, the card shows status `Masz najnowszą wersję.` and the clone stays on `HEAD`. Screenshot `187`.
- **Current.** Harness: remove `main-commit.txt` (GitHub's newest Wydanie is the tool's own commit), shift the clock by 10 minutes, open `#/powiadomienia` afresh: no region `Nowa wersja 0.2.0`; listitem `Nowa wersja 0.2.0` has `INTRO` and `POINTS` as on the card, no button and no label `nowe`; the bell is plain `Powiadomienia`; `api/powiadomienia-wydanie-aktualne.json` has both Wydania without `update_offered` and read. Screenshot `188`.
- **No network for Wydania.** Create `<root>/github/brak-sieci`, shift the clock by 10 minutes, open `#/powiadomienia` afresh: the question log grew by one, both rows `Nowa wersja` are there, no alert, no error toast, the bell is plain; `api/powiadomienia-wydania-brak-sieci.json` is unchanged. Screenshot `189`. Remove the four files of `<root>/github/` (also in `finally`).
- **State file unavailable.** Harness: close the oldest open Uwaga (`completed`) in the skrzynka, shift the clock by 10 minutes, and hold both state files (Windows: the drive keeps them open, so `os.replace` onto them fails; macOS: `chflags uchg`; Linux: the `config` folder read-only, so Centrum's temporary file fails; always undone in `finally`). Open `#/powiadomienia` afresh: `GET /api/notifications` (`api/powiadomienia-plik-niedostepny.json`) reaches a `message` whose `where` names both files; after a reload label `Komunikat` contains its three parts, both file names and `niedostępn`, but not `uszkodzon`; the Uwaga row says `Rozwiązana. Będzie w następnej wersji.`; both files on disk are unchanged. Screenshot `201`. Let the files go and open `#/powiadomienia` afresh: no label `Komunikat`, `api/powiadomienia-plik-zapisany.json` has no `message`, `config/powiadomienia.json` has the Uwaga's read id and `config/sprawy-taty.json` its closing. Screenshot `202`.
- **Proof.** Screenshots `180`–`189`, `201`, `202`, `api/powiadomienia-*.json`, the checks in `drive.txt`; the key is neither in the Centrum log nor in the page.

## Gotchas

- Every `GET /api/notifications`, from the tab or from `run.api`, may ask the skrzynka; count questions in the log, not requests.
- The tab reads Powiadomienia on start, on every page change and on focus; the 10-minute limit keeps these from asking again.
- The Zgłoszenie that `zgloszenie` closed has no `state_reason`; Centrum reads it as `completed`, so it may already be new when this feature starts.
- Never point the app at the real GitHub skrzynka; the key is synthetic.
- Only the first failed save of a held state file waits for its retries (under a second); later reads try once. Poll the API with a timeout instead of expecting the Komunikat on the first answer: the Komunikat names `powiadomienia.json` only after the tab has marked the closed Uwaga read.
- The Linux lock was never driven: CI drives Centrum on Windows, and root ignores a read-only folder, so there the Komunikat never shows and the step fails.
- Run alone, the clone stands one commit behind the local origin; the Update step first makes the clone's `HEAD` the origin's only Wydanie, so the click never moves the clone.
