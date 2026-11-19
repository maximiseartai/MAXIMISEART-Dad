"""Show that sprawdz_historie_ustawien.py fails when the TLA+ model of the Ustawienia owner loses a guard the code has.

Each mutation removes from ``model/HistoriaUstawien.tla`` one guard or step whose counterpart in
``src/rozliczenia/centrum/settings/owner.py`` (``CentrumSettings``) the mutation names, runs on its own copy of the
checkout (``tools/lib/silnik_mutacji.py``) and must end the check with ``HISTORIA USTAWIEŃ: NOWE NARUSZENIE``. A
mutation whose anchor text is no longer in the model is reported as NIEAKTUALNA: update it to the new model.
``GRANICE`` holds, for each cause of a known finding, its configuration without that one known finding: its path
must then be a new violation, so no other cause of that configuration forgives it.

The copy of the checkout has no ignored TLC cache, so this script hands Java and ``tla2tools.jar`` of this checkout
to every command through ``TLC_JAVA`` and ``TLC_JAR`` (``model_tlc.narzedzia_dla_kopii``).
"""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
import sys
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))

from model_tlc import narzedzia_dla_kopii
from silnik_mutacji import Edit, Mutation, check_all

ROOT = Path(__file__).resolve().parents[4]
MODEL = Path(".agents/skills/verify-historia-ustawien/model/HistoriaUstawien.tla")
CONFIGS = Path(".agents/skills/verify-historia-ustawien/model/konfiguracje.json")
CHECK = ".agents/skills/verify-historia-ustawien/scripts/sprawdz_historie_ustawien.py"
NEW = "HISTORIA USTAWIEŃ: NOWE NARUSZENIE"


def _check(config: str) -> tuple[str, ...]:
    return (CHECK, "--config", config)


def _without_known(config: str, cause: str, harm: str) -> Mutation:
    """``config`` without the known finding of ``cause``: its path must stay a new violation."""

    text = (ROOT / CONFIGS).read_text(encoding="utf-8")
    loaded = json.loads(text)
    kept = dict(loaded[config])
    kept["znane"] = [finding for finding in kept["znane"] if finding["przyczyna"] != cause]
    if len(kept["znane"]) == len(loaded[config]["znane"]):
        raise ValueError(f"{config} has no known finding {cause}")
    changed = json.dumps({**loaded, config: kept}, ensure_ascii=False, indent=2) + "\n"
    return Mutation(f"{config} bez znanego {cause}", (Edit(CONFIGS, text, changed),), _check(config), harm, NEW)


GRANICE: Final[Mapping[str, tuple[Mutation, ...]]] = {
    "zgasniecie-przed-pamiecia": (
        _without_known(
            "zwykle",
            "zgasniecie-przed-pamiecia",
            "_change: Centrum gaśnie po History.append, a przed _remember, potem zła treść: proces liczy starą wartością",
        ),
    ),
    "bez-zmian-bez-pamieci": (
        _without_known(
            "poczatek-wydania",
            "bez-zmian-bez-pamieci",
            "_apply_pending: wynik „bez-zmian” bez wiersza i bez pamięci zmian z Wydań, a tata potem zmienia wartość",
        ),
    ),
    "wiersz-odczytu-nieudany": (
        _without_known(
            "wiersz",
            "wiersz-odczytu-nieudany",
            "_compared: History.append wiersza spoza Centrum zawodzi, a proces dostaje nową treść",
        ),
    ),
    "wiersz-i-przywrocenie-nieudane": (
        _without_known(
            "wiersz",
            "wiersz-i-przywrocenie-nieudane",
            "_change zmiany z Wydania: wiersz i _put_back zawodzą, tata cofa wiersz spoza Centrum, start stosuje ją znowu",
        ),
    ),
    "przywrocenie-nieudane": (
        _without_known(
            "wiersz",
            "przywrocenie-nieudane",
            "_change taty: wiersz i _put_back zawodzą, a tata czyta „nie zapisano” przy pliku z jego wartością",
        ),
    ),
    "pamiec-niezapisana": (
        _without_known(
            "pamiec",
            "pamiec-niezapisana",
            "_remember po wierszu zawodzi, potem zła treść: proces liczy starą wartością",
        ),
    ),
    "pamiec-bez-odczytu": (
        _without_known(
            "odczyt-pamieci",
            "pamiec-bez-odczytu",
            "_compared przy pamięci bez odczytu: proces liczy zmianą spoza Centrum bez wiersza",
        ),
    ),
    "zly-plik-bez-pamieci": (
        _without_known(
            "odczyt-pamieci",
            "zly-plik-bez-pamieci",
            "_compared przy pamięci bez odczytu i złej treści: proces liczy wartością domyślną z Wydania",
        ),
    ),
    "zgasniecie-przed-wierszem-wydania": (
        _without_known(
            "historia-i-zapis",
            "zgasniecie-przed-wierszem-wydania",
            "zmiana z Wydania zapisana bez wiersza (zgaśnięcie), start bez Historii, tata zmienia: następny start ją nadpisuje",
        ),
    ),
}
"""For each cause of a known finding, its configuration without that one known finding: the same harm must then be a
new violation, because no other cause of that configuration forgives that path (#1341 round 1: a cause too wide
forgave a different path under the name of another)."""

MUTATIONS = (
    Mutation(
        "_compared bez porównania z pamięcią: zmiana spoza Centrum bez wiersza",
        (
            Edit(
                MODEL,
                "           zmieniony == ~(dane = pamiec.widziany /\\ (dane = ZLY \\/ pamiec.dobry = dane))\n",
                "           zmieniony == FALSE\n",
            ),
        ),
        _check("zwykle"),
        "Maks zmienia plik poza Centrum, a proces liczy tą wartością, której Historia nigdy nie dostaje",
        NEW,
    ),
    Mutation(
        "_change bez History.append wiersza zmiany",
        (
            Edit(
                MODEL,
                "!.wiersz = op.cel # op.obs, !.tataPrzed = wartoscTaty]",
                "!.wiersz = FALSE, !.tataPrzed = wartoscTaty]",
            ),
        ),
        _check("zwykle"),
        "zapis taty zmienia plik i pamięć bez wiersza: proces liczy wartością, której Historia nie pokazuje",
        NEW,
    ),
    Mutation(
        "_compared zapamiętuje stan mimo nieudanego wiersza spoza Centrum (bez except OSError: return)",
        (
            Edit(
                MODEL,
                '!.pc = "porownane", !.sciezka = "wiersz-odczytu-nieudany"]',
                '!.pc = "pamiecSpoza", !.sciezka = "wiersz-odczytu-nieudany"]',
            ),
        ),
        _check("wiersz"),
        "pamięć przyjmuje zmianę spoza Centrum bez wiersza, więc następny odczyt już go nie dopisze",
        NEW,
    ),
    Mutation(
        "_change bez _put_back po nieudanym wierszu",
        (
            Edit(
                MODEL,
                "          /\\ op' = [op EXCEPT !.pc = \"przywroc\"]\n",
                "          /\\ op' = [op EXCEPT !.pc = \"niezapisane\"]\n",
            ),
        ),
        _check("wiersz"),
        "wiersz Historii zawodzi, plik zostaje z nową wartością, a tata czyta „nie zapisano”",
        NEW,
    ),
    Mutation(
        "_apply_pending bez _release_rows: zmiana z wierszem Historii, a bez pamięci, wraca",
        (
            Edit(
                MODEL,
                '       \\/ /\\ \\E i \\in DOMAIN historia : historia[i].zrodlo = "wydanie"\n',
                "       \\/ /\\ FALSE\n",
            ),
            Edit(
                MODEL,
                '       \\/ /\\ ~\\E i \\in DOMAIN historia : historia[i].zrodlo = "wydanie"\n',
                "       \\/ /\\ TRUE\n",
            ),
        ),
        _check("pamiec-zmian"),
        "tata cofa zmianę z Wydania, której pamięć zmian z Wydań nie zapisała, a następny start stosuje ją znowu",
        NEW,
    ),
    Mutation(
        "apply_release_changes bez Memory.applied: zmiana bez zmian w pliku wraca przy każdym starcie",
        (
            Edit(
                MODEL,
                '    /\\ faza\' = IF zmianyZWydan THEN "wolny" ELSE "historiaWydan"\n',
                '    /\\ faza\' = "historiaWydan"\n',
            ),
        ),
        _check("poczatek-wydania"),
        "zmiana z Wydania z wynikiem „bez-zmian” stosuje się przy następnym starcie znowu i nadpisuje wartość taty",
        NEW,
    ),
    *dict.fromkeys(mutation for mutations in GRANICE.values() for mutation in mutations),
)


if __name__ == "__main__":
    narzedzia_dla_kopii(ROOT)
    raise SystemExit(check_all(MUTATIONS))
