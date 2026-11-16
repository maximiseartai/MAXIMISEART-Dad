# Aktualność narzędzia i OneDrive

The Diagnoza has two checks that look beyond Dad's files. `Aktualność
narzędzia` compares the tool's commit with the newest Wydanie on the public
GitHub (ADR 0014). A newer Wydanie is the cause only when no other check found one (Dad clicks
`Zaktualizuj narzędzie` in the explanation and runs again); next to another
cause it is only a quiet proposal under the explanation, with the same button
second after `Uruchom ponownie` (ADR 0009). While the update runs, the button
cannot be clicked again. No network leaves it `not_checked`, never a cause, and with no button (so do a tool without a Git commit and a GitHub with no Wydanie yet); an up-to-date tool has none either (only a newer Wydanie offers the update, ADR 0014). `Pliki w OneDrive` finds a Rejestr
zleceń, Wzorzec, or period file that OneDrive keeps only in the cloud and tells
Dad to choose „Zawsze zachowuj na tym urządzeniu”. The server computes both;
the browser shows the explanation and the list `Sprawdzono`.

## Sub-features

Printed by `scripts/sub_features.py --feature aktualnosc-i-onedrive` from the drive's steps and checks; refresh the section with it.

- `aktualnosc-nowsza-wersja`: the stop without its Wzorzec is „do Maksa”; updating the tool is the explanation's main action; with no other cause a newer Wydanie on `main` explains the stop, and Dad updates the tool with the button.
- `aktualnosc-brak-sieci`: without network the freshness is not checked, is no cause, and the Diagnoza offers no update.
- `onedrive-tylko-w-chmurze`: a Rejestr zleceń only in the cloud explains the stop with „Zawsze zachowuj na tym urządzeniu”; the Diagnoza left the Rejestr zleceń as it was.
- `aktualnosc-propozycja`: `Zaktualizuj narzędzie` in the proposal comes second, after the explanation's `Uruchom ponownie`; a newer Wydanie does not cover the Rejestr zleceń only in the cloud: it is only proposed under the explanation.
- `aktualnosc-aktualizacja-w-trakcie`: the click on the disabled button during the update sends nothing; the server reports the update running; the click on the disabled button during the update started no second Aktualizacja narzędzia.
- `aktualnosc-i-onedrive-przeszly`: an up-to-date tool and files kept on the computer pass both checks, and the Diagnoza offers no update; the Centrum log records both causes by code only.

## How to get to it (user POV)

When an Uruchomienie procesu on Uruchomienia stops „do Maksa”, or the same stop comes back, Dad clicks `Diagnoza` on
the `Zatrzymanie` banner. The explanation, the note `Propozycja aktualizacji` when there is one, and the collapsed list
`Sprawdzono (11)` appear in region `Diagnoza`.

## Driving it with Playwright for Python

Run `.venv/bin/python .agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py --feature aktualnosc-i-onedrive`; the shared proof and the Windows form are in point 3 of [`README.md`](README.md).
Its proof adds `api/aktualnosc-*.json` and `api/onedrive-*.json`.

## Gotchas

- Remove `<root>/github/main-commit.txt` before `aktualnosc-i-onedrive-przeszly`: with no other cause the newer
  Wydanie stays `failed` and becomes the explanation.
- Restore the Wzorzec by renaming it back, never by copying: `diagnoza` compares modification times.
- Opening `Sprawdzono (11)` twice collapses it again; open it once per Diagnoza.
- The primary and outline checks of `Zaktualizuj narzędzie` hold because no earlier feature of `all` leaves a failed
  Aktualizacja narzędzia behind: after one, the button follows that failure.
- The result `Masz najnowszą wersję.` of the update is about the newest Wydanie Centrum knew then, the scripted
  GitHub's stand-in in `main-commit.txt`, so the explanation can still say there is a newer version; the result stays
  only until Centrum knows another newest Wydanie (issue #373).
