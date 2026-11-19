"""Slot Maca ciężkiego procesu: na Macu Maksa ciężki proces bierze przy starcie slot ``boatbox`` albo się nie zaczyna.

Sloty to te same pliki co sloty ``boatbox auto`` i ``boatbox run --here`` (skill ``boat``, sekcja „Budżet”): ``flock``
na jednym z ``BOATBOX_MAC_SLOTS`` plików w ``BOATBOX_SLOT_DIR``. ``take`` nic nie robi, gdy ``boatbox`` nie ma w
``PATH`` (CI, box boat, komputer taty), gdy proces biegnie już w slocie (``SLOT``, które ustawia ``boatbox`` i samo
``take`` dla potomków), gdy uruchomiło go narzędzie z ``tools/`` (``potomne.CHILD``: o jego miejscu zdecydowało to
narzędzie, a jego wynik czyta ono jako wynik polecenia) albo w teście pytest (``PYTEST_CURRENT_TEST``). Inaczej bierze pierwszy wolny slot i trzyma
go do końca procesu, a jądro zwalnia go także po zabiciu; bez wolnego slotu zwraca linię ``CIĘŻKIE``, z którą
wołający kończy się kodem ``CODE`` (EX_UNAVAILABLE, inny niż ``box_boat.KOD_WYJSCIA``) i gotowym poleceniem
``boatbox``. Bramki nie omija więc żadna składnia powłoki,
bo stawia ją sam proces, a nie odczyt jego polecenia.
"""

from __future__ import annotations

import os
from pathlib import Path
import shlex
import shutil
import sys
import time
from typing import IO, Optional

import potomne

SLOT = "BOATBOX_MAC_SLOT"
CODE = 69
_HELD: list[IO[str]] = []


def _slots() -> int:
    given = os.environ.get("BOATBOX_MAC_SLOTS", "")
    return max(1, int(given) if given.isdigit() else (os.cpu_count() or 1) // 4 - 1)


def _command() -> str:
    words = list(sys.orig_argv)
    if os.path.isabs(words[0]) and Path(words[0]).is_relative_to(Path.cwd()):
        words[0] = os.path.relpath(words[0])
    return shlex.join(words)


def take(name: str, route: str) -> Optional[str]:
    outside = (SLOT, potomne.CHILD, "PYTEST_CURRENT_TEST")
    if sys.platform == "win32" or any(os.environ.get(name) for name in outside) or shutil.which("boatbox") is None:
        return None
    import fcntl

    folder = Path(os.environ.get("BOATBOX_SLOT_DIR") or Path.home() / ".cache" / "boatbox" / "mac-slots")
    folder.mkdir(parents=True, exist_ok=True)
    count, command = _slots(), _command()
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
        return None
    return f"CIĘŻKIE {name} | Mac zajęty ({count}/{count} sloty): uruchom przez boatbox {route} {shlex.quote(command)}"
