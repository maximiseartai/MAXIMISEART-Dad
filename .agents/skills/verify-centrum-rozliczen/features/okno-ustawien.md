# Okno Ustawień

Dad opens Ustawienia with the gear in the menu's footer, right above `Zamknij Centrum rozliczeń`. The window opens
over the blurred Centrum, like the settings of T3 Code (ADR 0032): sections in groups on the left, the path
`Ustawienia / <sekcja>` and ✕ on top. Esc, ✕ and a click on the backdrop close it, and the page under it stays. The
address `#/ustawienia/<sekcja>` opens the window on that section over the current page, and the old address of
Konfiguracja, `#/konfiguracja`, opens Ustawienia. On a narrow browser window it fills the screen and the sections
are a combobox. Okresy, Uruchomienia and Raporty choose no file any more: an unset one is the link
`Ustaw w Ustawieniach` to the section Foldery.

## Sub-features

- `okno-stopka-menu`: the link `Ustawienia` stands in the menu's footer right above `Zamknij Centrum rozliczeń`; the menu has no `Konfiguracja`.
- `okno-nad-strona`: on Metryki the gear opens the window at `#/ustawienia` on Foldery; the heading of Metryki stays in the document; the groups shown are Praca, Pliki, Połączenia, Narzędzie, Historia in that order (Ilości has no section yet and does not show), with the sections Foldery, Wykonawcy, Wzorce, Kopie INTERMAX, Skrzynka raportów, Zgłoszenia, Narzędzie, Wygląd, Historia.
- `okno-zamykanie`: Esc, ✕ (`Zamknij Ustawienia`) and a click on the backdrop each close the window back to `#/metryki` with Metryki shown, and opening and closing never reads `/api/metrics` again; Back in the browser then goes to `#/okresy`, where Dad was before Metryki.
- `okno-adres-sekcji`: `#/ustawienia/wzorce` set on Uruchomienia opens Wzorce over Uruchomienia (its link is `aria-current`); another section changes the address in place, so Back in the browser closes the window; a new tab on `#/ustawienia/kopie-intermax` opens that section over the start page Okresy; an unknown section opens Foldery.
- `okno-stara-konfiguracja`: a bookmark of `#/konfiguracja` (a new load) and a link to it (a change of the address) both open Ustawienia at `#/ustawienia`.
- `okno-foldery`: on the empty Okresy, `Ustaw w Ustawieniach` opens `#/ustawienia/foldery`, where `Rejestr zleceń` and `Folder okresów` read `Nie wskazano` with `Wskaż …` enabled.
- `okno-linki-do-folderow`: Okresy, Uruchomienia (groups `Rejestr zleceń`, `Folder okresów`, `INTERMAX`) and Raporty (group `INTERMAX`) have no `Wskaż …`/`Zmień …` button; each unset file links to `#/ustawienia/foldery`, and the link on Raporty opens Foldery over Raporty, which stays after Esc; a chosen INTERMAX on Raporty shows its name without the link.
- `okno-waskie`: at 420×860 the window covers the whole viewport, the list of sections is hidden, the combobox `Sekcja Ustawień` names the section and lists the groups, and choosing `Wzorce` goes to `#/ustawienia/wzorce`.

## How to get to it (user POV)

- The link `Ustawienia` (gear) in the menu's footer, above `Zamknij Centrum rozliczeń`.
- `Ustaw w Ustawieniach` next to an unset file on Okresy, Uruchomienia and Raporty.
- The address `#/ustawienia/<sekcja>`, or the old `#/konfiguracja`.

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run with `DOCTOR OK` and nothing is set yet: `okno-foldery` and `okno-linki-do-folderow`
  check the unset files, so `all` drives this feature first, before `ustawienia` sets them. It sets nothing itself: the
  chosen INTERMAX on Raporty is the server's answer from `page.route`.

- **Footer.** `#/okresy`; the bounding box of link `Ustawienia` ends above the button `Zamknij Centrum rozliczeń`; no link `Konfiguracja`. Screenshot `300`.
- **Over the page.** Link `Metryki`, then link `Ustawienia`: dialog `Ustawienia` with heading `Ustawienia/Foldery` (the `/` is hidden from screen readers), address `#/ustawienia`, `h1[data-page="metryki"]` still in the document. The labels `[data-slot=sidebar-group-label]` read Praca, Pliki, Połączenia, Narzędzie, Historia; no text `Ilości` in the dialog; the links of the list are the eight sections in order. Screenshot `301`.
- **Closing.** In turn Esc, button `Zamknij Ustawienia`, and a click at (40, 500) on the backdrop, reopening with the gear before each: the dialog is gone, heading `Metryki` visible, address `#/metryki`. `page.on("request")` sees no `/api/metrics` from the gear to the last close. `page.go_back()`: heading `Okresy`, address `#/okresy` (a close that replaces the address instead of going Back would leave Metryki).
- **Section address.** Link `Uruchomienia`; `location.hash = '#/ustawienia/wzorce'`: heading `Ustawienia/Wzorce`, link `Wzorce` `aria-current="page"`, `h1[data-page="uruchomienia"]` in the document. Link `Narzędzie` in the dialog: address `#/ustawienia/narzedzie`. `page.go_back()`: the dialog is gone and Uruchomienia shows. `goto` `#/ustawienia/kopie-intermax` and reload (a new tab): heading `Ustawienia/Kopie INTERMAX` over `h1[data-page="okresy"]`; Esc shows Okresy. `goto` `#/ustawienia/nie-ma-takiej`: heading `Ustawienia/Foldery`; Esc.
- **Old address.** `goto` `#/konfiguracja` and reload, then `goto` `#/konfiguracja` without reload: each time heading `Ustawienia/Foldery` and address `#/ustawienia`; Esc.
- **Foldery.** Link `Ustaw w Ustawieniach` on the empty Okresy: address `#/ustawienia/foldery`; list items `Rejestr zleceń` and `Folder okresów` contain `Nie wskazano` with enabled `Wskaż Rejestr zleceń` and `Wskaż Folder okresów`. Screenshot `302`. Esc.
- **Links from the pages.** On Okresy, Uruchomienia and Raporty (menu links), `main` has no button named `Wskaż …` or `Zmień …`, and the link `Ustaw w Ustawieniach` of each group above has `href` `#/ustawienia/foldery`. On Raporty click it: heading `Ustawienia/Foldery` over `h1[data-page="raporty"]`; screenshot `303`; Esc shows Raporty. Then `page.route("**/api/settings")` answers with `order_register` `ready` (the fixture's Rejestr zleceń) and the page reloads: group `INTERMAX` contains the file's name and no link `Ustaw w Ustawieniach`; after `unroute` and a reload the link is back.
- **Narrow window.** Viewport 420×860, `goto` `#/ustawienia/foldery`; after the entrance animations end, the dialog's bounding box is exactly the viewport; link `Wzorce` is hidden; combobox `Sekcja Ustawień` contains `Foldery`. Screenshot `304`. Open it: the listbox has a group per shown group. Screenshot `305`. Option `Wzorce`: heading `Ustawienia/Wzorce`, address `#/ustawienia/wzorce`. Esc, and the viewport goes back to 1440×1000 (also in `finally`).
- **Proof.** Screenshots `300`–`305` and the checks in `drive.txt`.

## Gotchas

- The window is a modal: the page under it is inert, so role queries do not see it; the drive checks the page under
  by its `h1[data-page]`.
- `goto` to another fragment of the same page only changes the address (a `hashchange`); a new tab is `goto` plus
  `reload`.
- The window grows from 95 % as it opens; measure its box after `document.getAnimations()` are done.
- The section `Narzędzie` and its group `Narzędzie` share a name: find the group in the listbox by role `group`.
