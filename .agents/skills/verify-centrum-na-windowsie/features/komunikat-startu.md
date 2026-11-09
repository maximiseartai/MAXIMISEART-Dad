# Komunikat startu

When Dad double-clicks „Centrum rozliczeń” and another program holds Centrum's port `47811`, Centrum does not start.
Started by the shortcut it has no console, so the three-part Komunikat appears in Windows' own message box titled
`Centrum rozliczeń`; when Dad closes it, the process ends and the Centrum log keeps `blad-startu` with the code.

## Sub-features

- `okienko`: within 60 s a visible `#32770` window titled `Centrum rozliczeń` belongs to the shortcut's `pythonw.exe` (command line with the tool's `run_centrum.py`), its text is exactly the copy of `start_problems.port_taken(47811).text` in `komunikat_startu.py` (Co się stało / Gdzie / Co zrobić), and that process shows no other window (no console). Desktop screenshot `pulpit/NN-komunikat-zajety-port.png`.
- `zamkniecie-okienka`: `WM_CLOSE` closes the window, the process ends within 15 s, the Centrum log has `blad-startu kod=<code> port=47811`, and the other program still holds the port.

## How to get to it (user POV)

- Double-click the desktop shortcut „Centrum rozliczeń” while another program uses port `47811`.

## Driving it with the Windows harness

Preconditions:

- `instalacja` ran; nothing listens on `47811`; Centrum has never started in this run (so the log has no `start`).

- **Other program.** Harness: a socket on `127.0.0.1:47811` that accepts every connection and closes it, so `health` gets no answer like Centrum's.
- **Double click.** `windows_desktop.start_shortcut(<root>\Pulpit\Centrum rozliczeń.lnk)`. Wait for the message box; check its owner process, its longest `Static` text against the copy of `port_taken(47811).text` (`\r\n` read as `\n`), and that the process has no other visible window. Capture the desktop.
- **Close.** `windows_desktop.close(box)`; the window is gone within 10 s, the process within 15 s; the log lines after the click include `blad-startu kod=PORT_ZAJETY port=47811`. Stop the socket; `47811` is free.
- **Proof.** `pulpit/NN-komunikat-zajety-port.png`, `drive.txt` (the window's text is printed as `okienko: …`), `state/centrum-rozliczen.log`.

## Gotchas

- The launcher asks the other program for `health` once, with a 5 s timeout. The harness's socket closes every connection at once, so the window appears without that wait; a program that accepts and stays silent delays it by 5 s.
- The same message box carries Centrum's other start problems from the shortcut (`start_problems.py`: another version already running, an update still finishing, a missing library, an unexpected error) and the restart guardian's `not_started_after_update` when no version starts. Only the taken port is driven here.
- The message box is modal to nothing and topmost; it can sit behind nothing, but a desktop screenshot on a locked or disconnected session is black. GitHub's runner keeps an unlocked session.
- The text compare is exact: a change of the Komunikat's wording in `start_problems.py` is a change of what Dad reads, and this step reports it.
