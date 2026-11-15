# Pomiar u taty

Centrum measures its own speed on Dad's computer without Dad seeing anything:
every API answer carries `Server-Timing` with the handling time only, and after
every ready view (the cold start of a page, a menu click, a click on the header bell) the browser sends one
measurement that the server appends to the Centrum log as a `pomiar` entry. The
entry holds the page id (`PageId`, the five pages of the menu, Powiadomienia and the Uzupełnienie page `#/uzupelnienie/<okres>`, which this feature does not drive:
`tests/test_centrum_uzupelnienie_tabela.py::test_po_odczycie_strony_rodzaju_teksty_wierszy_nie_wychodza_z_komputera`
sends its measurement and checks that the request reaches the Centrum log while no row text reaches the log, a
Zgłoszenie or the Logi), the times in milliseconds, and for each
API request the operation name from the contract with the browser and server
time, so Maks can tell slow OneDrive reads from a slow browser. No address,
path, period token or content reaches the log.

## Sub-features

Printed by `scripts/sub_features.py --feature pomiar-u-taty` from the drive's steps and checks; refresh the section with it.

- `pomiar-zimny-start`: a cold start on #/ustawienia/wzorce logs the window, not the start page it hides; …: every API request has its operation, browser time and server time (…); the window's entry holds its read of the configuration; the entry names the cold start of …; …: ready content, FCP and skeleton time in milliseconds.
- `pomiar-server-timing`: the browser read API answers during the cold starts; every API answer the browser got has Server-Timing with only the handling time.
- `pomiar-przejscia-w-menu`: one menu-click entry per page, in the order of the clicks; menu clicks carry no FCP; the bell, outside the sidebar, logs a menu click to Powiadomienia without FCP; …: every API request has its operation, browser time and server time (…); back on metryki, the last data shows at once: no skeleton and no request before the content (the read in the background ends later; gotowe_ms=…).
- `pomiar-szkielet-widoczny`: the window measured itself (…); a read held … ms (harness) shows the skeleton only after about … ms: szkielet_ms=… of gotowe_ms=….
- `pomiar-wiele-zapytan`: Ustawienia measured themselves while their read of Aktualizacja narzędzia was held (… reads, harness); a view with more API requests than the contract's … is logged with its newest …, ending with the read that made it ready (…; the page's last read before it sent the measurement: …).
- `pomiar-bez-sladu`: the measurement entries hold no path, address or period token.
- `pomiar-obcy-origin`: a measurement from a foreign Origin is refused; the refused measurement adds no entry.

## How to get to it (user POV)

- None: Dad opens and clicks through Centrum as always. Maks reads the `pomiar` entries in `logs/centrum-rozliczen.log` on Dad's computer.

## Driving it with Playwright for Python

Run `.venv/bin/python .agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py --feature pomiar-u-taty`
from the repository root (Windows: `py -3`). The proof is in the evidence folder that `VERIFY OK` names: the lines under
`STEP pomiar-u-taty` in `drive.txt`, the screenshots of its `Feature` in `scripts/drive/__init__.py`,
`api/pomiar-*.{json,txt}` and `state/centrum-rozliczen.log`.

## Gotchas

- The browser sends the measurement after the next frame, so wait for the log entry before leaving the page; a
  navigation right after the heading appears can drop it.
- The measurement counts only requests finished before the content was ready; a refresh in the background that ends
  later is not in `zapytania`. A page already visited in the same tab shows its last data at once, so its menu-click
  entry usually has no `zapytania`; only a new document (`about:blank` first, or a reload) forgets them.
- This feature proves the measurement, not the speed: its times come from a busy verification run and are not
  compared with anything.
