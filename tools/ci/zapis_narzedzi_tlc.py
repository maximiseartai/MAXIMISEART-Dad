"""Mówi krokowi ``actions/cache/save`` zadania CI, czy katalog narzędzi TLC ma jar o przypiętej sumie i można go zapisać.

    python tools/ci/zapis_narzedzi_tlc.py

Pisze do ``GITHUB_OUTPUT`` linię ``zapisz=true`` tylko wtedy, gdy katalog podręczny ``KATALOG`` z
``tools/lib/narzedzia_tlc.py`` ma ``tla2tools.jar`` przypiętej wersji z przypiętą sumą SHA-256, a w każdym innym razie
``zapisz=false``, także gdy katalogu nie ma, bo żadna jednostka zadania nie uruchomiła modelu. Javę skrypty modeli
instalują przed jarem, a gdy instalacja zawiedzie, kończą się przed pobraniem jara, więc jar o przypiętej sumie znaczy
pełny katalog. Klucz cache, raz zapisany z katalogiem bez jara, dawałby trafienie bez jara każdemu runowi aż do zmiany
przypiętych wersji (#940). Skrypt drukuje swoją decyzję i zawsze kończy się kodem 0, bo decyduje tylko o zapisie cache.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/lib"))

from narzedzia_tlc import KATALOG, jar_tla, ma_przypieta_sume

ZAPISZ = "zapisz"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.parse_args(argv)
    jar = jar_tla(KATALOG)
    zapisz = ma_przypieta_sume(jar)
    print(f"NARZĘDZIA TLC: {jar.as_posix()} {'ma' if zapisz else 'nie ma'} przypiętej sumy, {ZAPISZ}={str(zapisz).lower()}")
    if wyjscie := os.environ.get("GITHUB_OUTPUT"):
        with open(wyjscie, "a", encoding="utf-8") as plik:
            plik.write(f"{ZAPISZ}={str(zapisz).lower()}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
