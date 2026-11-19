"""Slot Maca ciężkiego procesu: na Macu Maksa ciężki proces bierze przy starcie slot ``boatbox`` i bez wolnego czeka.

Sloty to te same pliki co sloty ``boatbox auto`` i ``boatbox run --here`` (skill ``boat``, sekcja „Budżet”): ``flock``
na jednym z ``BOATBOX_MAC_SLOTS`` plików w ``BOATBOX_SLOT_DIR``, a ich liczba to ta sama reguła co w ``boatbox``.
``take`` nic nie robi, gdy ``boatbox`` nie ma w ``PATH`` (CI, box boat, komputer taty), gdy proces biegnie już
w slocie (``SLOT``, które ustawia ``boatbox`` i samo ``take`` dla potomków) albo w teście pytest
(``PYTEST_CURRENT_TEST``). Inaczej bierze pierwszy wolny slot i trzyma go do końca procesu, a jądro zwalnia go także po
zabiciu; bez wolnego slotu czeka w kolejce jak ``boatbox`` i co ``LINE_S`` s pisze linię ``CIĘŻKIE`` z gotowym
poleceniem ``boatbox``, które pośle polecenie na box bez czekania. Kodu wyjścia bramka nie zmienia, więc narzędzie,
które czyta wynik pytest (``tools/mutacje.py``, test scalenia ``tools/scal_pr.py``), nie weźmie jej za wynik testu,
a na Macu nigdy nie biegnie naraz więcej ciężkich procesów niż slotów. Bramki nie omija składnia powłoki, bo stawia ją
sam proces, a nie odczyt jego polecenia.
"""

from __future__ import annotations

import os
from pathlib import Path
import shlex
import shutil
import sys
import time
from typing import IO

SLOT = "BOATBOX_MAC_SLOT"
LINE_S = 30
TRY_S = 2
_HELD: list[IO[str]] = []


def _slots() -> int:
    given = os.environ.get("BOATBOX_MAC_SLOTS", "")
    return max(1, int(given) if given.isdigit() else (os.cpu_count() or 1) // 4 - 1)


def _command() -> str:
    words = list(sys.orig_argv)
    if os.path.isabs(words[0]) and Path(words[0]).is_relative_to(Path.cwd()):
        words[0] = os.path.relpath(words[0])
    return shlex.join(words)


def take(name: str, route: str) -> None:
    if sys.platform == "win32" or os.environ.get(SLOT) or os.environ.get("PYTEST_CURRENT_TEST") or shutil.which("boatbox") is None:
        return
    import fcntl

    folder = Path(os.environ.get("BOATBOX_SLOT_DIR") or Path.home() / ".cache" / "boatbox" / "mac-slots")
    folder.mkdir(parents=True, exist_ok=True)
    count, command = _slots(), _command()
    start = next_line = time.monotonic()
    while True:
        for number in range(1, count + 1):
            slot = (folder / str(number)).open("a", encoding="utf-8")
            try:
                fcntl.flock(slot, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                slot.close()
                continue
            _HELD.append(slot)
            os.environ[SLOT] = str(number)
            who = f"pid={os.getpid()}\nsince={int(time.time())}\ndir={Path.cwd()}\ncmd={command[:120]}\n"
            (folder / f"{number}.who").write_text(who, encoding="utf-8")
            return
        if time.monotonic() >= next_line:
            waited = int(time.monotonic() - start)
            print(
                f"CIĘŻKIE {name} | Mac zajęty ({count}/{count} sloty), czekam {waited} s na slot; "
                f"bez czekania: boatbox {route} {shlex.quote(command)}",
                file=sys.stderr,
                flush=True,
            )
            next_line += LINE_S
        time.sleep(TRY_S)
