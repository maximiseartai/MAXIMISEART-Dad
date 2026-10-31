"""Wypisuje skille verify-*, które obowiązują dla zmiany od bazy, każdy z powodem; użyj przed pushem i przed oceną gotowości PR.

Wypisuje skille ``verify-*``, które obowiązują dla zmiany od bazy (domyślnie ``origin/main``), każdy z powodem.

Zmiana to ``changed_since`` z ``tools/lib/wplyw_zmiany.py``: pliki z ``git diff`` od rozgałęzienia z bazą oraz pliki niezacommitowane i
nieśledzone. Skill deklaruje we frontmatterze ``SKILL.md`` klucz ``pilnuje:``, listę globów ścieżek względem korzenia
repozytorium (``*`` obejmuje też ``/``). Skill obowiązuje, gdy zmieniony plik pasuje do jego globu albo leży w jego
folderze (``hits`` z ``tools/lib/kroki_skilli.py``): ten sam klucz, przy trafieniu w który na pull request biegnie w CI
podstawa skilla. Skill bez klucza albo z kluczem, którego nie da się odczytać, obowiązuje zawsze.

Każdy skill, który obowiązuje, dostaje linię ``<skill>: <plik> (<glob>), …``. Ostatnia linia to
``SKILLE VERIFY: <skille po przecinku>`` albo ``SKILLE VERIFY: brak``: każdy skill, który obowiązuje, także taki,
którego polecenia liczy CI, bo jego workflow ma kroki, których CI nie zrobi (osąd, prawdziwe Wzorce, Excel na Macu).
Linie ``LICZY CI`` i ``LICZY NOC`` przed nią drukuje z zakresu runu (``tools/lib/zakres_runu.py``) tej zmiany, tego
samego, który wycenia plan CI. ``LICZY CI: <skill> (<polecenie>, …); …`` wymienia polecenia skilla, które liczy CI na
tym SHA: zakres pull requestu, czyli wybrane kroki skilla (podstawa ``ci:``, skrypt mutacji modelu przy zmianie modelu)
i wywołania jego skryptów w krokach CI (E2E przy zmianie ``src/``). ``LICZY NOC: <skill> (<skrypt>, …); …`` wymienia
skrypty mutacji skilla, które po merge'u liczy noc na ``main`` (zakres nocy, ADR 0021), a pull request nie: skrypt z
``LICZY CI`` w niej nie stoi. Agent nie uruchamia ich lokalnie poza odtworzeniem czerwonego kroku CI albo issue nocy.
Gdy git nie wyznaczy zmiany (np. nie ma bazy), ostatnia linia to ``SKILLE VERIFY: nieznane (<powód>)``, a kod wyjścia 1.

    .venv/bin/python tools/skille_dla_zmiany.py            # macOS i Linux
    py -3 tools/skille_dla_zmiany.py origin/main           # Windows
"""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

from kroki_skilli import ROOT, SKILLS, hits
from wplyw_zmiany import changed_since
from zakres_runu import Zdarzenie, zakres

VERDICT = "SKILLE VERIFY"
IN_CI = "LICZY CI"
AT_NIGHT = "LICZY NOC"
SHOWN = 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("baza", nargs="?", default="origin/main", help="Commit albo gałąź, od której liczy się zmiana.")
    args = parser.parse_args(argv)
    try:
        files = changed_since(ROOT, args.baza)
    except subprocess.CalledProcessError as error:
        detail = (error.stderr.strip().splitlines() or [f"kod {error.returncode}"])[0]
        print(f"{VERDICT}: nieznane (git {error.cmd[1]}: {detail})")
        return 1
    pull_request, night = zakres(Zdarzenie.PULL_REQUEST, files, ROOT), zakres(Zdarzenie.NOC, files, ROOT)
    chosen: list[str] = []
    in_ci: list[str] = []
    at_night: list[str] = []
    for skill_md in sorted(SKILLS.glob("verify-*/SKILL.md")):
        found = hits(skill_md.parent, files)
        reasons = [found.always] if found.always else [name if glob == name else f"{name} ({glob})" for name, glob in found.files.items()]
        if not reasons:
            continue
        chosen.append(skill_md.parent.name)
        if runs := pull_request.polecenia(skill_md.parent):
            in_ci.append(f"{skill_md.parent.name} ({', '.join(' '.join(run) for run in runs)})")
        in_pull_request = pull_request.kroki_skilla(skill_md.parent)
        if scripts := [Path(step.command[0]).name for step in night.kroki_skilla(skill_md.parent) if step not in in_pull_request]:
            at_night.append(f"{skill_md.parent.name} ({', '.join(scripts)})")
        more = f" i {len(reasons) - SHOWN} innych" if len(reasons) > SHOWN else ""
        print(f"{skill_md.parent.name}: {', '.join(reasons[:SHOWN])}{more}")
    if in_ci:
        print(f"{IN_CI}: {'; '.join(in_ci)}")
    if at_night:
        print(f"{AT_NIGHT}: {'; '.join(at_night)}")
    print(f"{VERDICT}: {', '.join(chosen) or 'brak'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
