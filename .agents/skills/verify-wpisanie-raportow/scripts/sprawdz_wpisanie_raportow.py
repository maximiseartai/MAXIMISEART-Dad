"""Sprawdza model TLA+ komórki raportu we Wpisaniu raportów przy każdej kolejności kliknięć, „Zostaw moją”, zmian taty i awarii.

Uruchamia TLC na każdej konfiguracji z ``model/konfiguracje.json``, porównuje wynik z jej znanymi znaleziskami i
opowiada każdy kontrprzykład krokami kodu. Konfiguracje, TLC, werdykt, znane znaleziska, narzędzia TLC i rozjazd modelu
z kodem z ``model/definicje.json`` ma ``tools/lib/model_tlc.py``: rozjazd skrypt tylko
ostrzega linią ``UWAGA:`` nad werdyktem, a w CI krok z rozjazdem nie biegnie (``tools/ci/wykonaj_zadanie.py``).

    .venv/bin/python .agents/skills/verify-wpisanie-raportow/scripts/sprawdz_wpisanie_raportow.py
    py -3 .agents\\skills\\verify-wpisanie-raportow\\scripts\\sprawdz_wpisanie_raportow.py
"""

from __future__ import annotations

from collections.abc import Sequence
import itertools
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))

from model_tlc import Model, Obietnica, Stan, main

# Akcja modelu i krok kodu, który opisuje (tabela w SKILL.md), w słowach kontrprzykładu.
_STEPS = {
    "TataZmienia": "tata (albo jego pracownik przez OneDrive) wpisuje w komórkę INTERMAX {komorka}",
    "NowyMail": "Wykonawca przysyła Raport wykonawcy z Wpisem {wpis} dla tego zlecenia",
    "ZamkniecieOkresu": "Przygotowanie tworzy Plik zbiorczy okresu, okres jest zamknięty (_closed)",
    "OtwarcieOkresu": "tata usuwa Plik zbiorczy okresu, okres znów jest otwarty",
    "PojawiaSieKopia": "OneDrive kładzie obok INTERMAX kopię konfliktu",
    "TataUsuwaKopie": "tata scala kopię konfliktu i ją usuwa",
    "Sprawdzanie": "tata klika „Wpisz raporty z maili”: Sprawdzanie, FileReportState.load (pamięć {mig}, decyzje {migd})",
    "Zapis": "odczyt skrzynki i INTERMAX, _cells.reconcile, write_cells (report_entering.py :340)",
    "ZapiszPamiec": "save_memory zapisuje pamięć własnych wpisów {plan} (report_entering.py :353)",
    "ZapiszWynik": "save_result zapisuje wynik dla widoku Raporty, różnica {roznica} (report_entering.py :354), "
    "potem onedrive_conflicts.beside (:356) i koniec Uruchomienia",
    "Odswiez": "karta odświeża widok Raporty: shown() i kept() ponawiają odłożony zapis",
    "ZostawSprawdz": "tata klika „Zostaw moją” przy różnicy {tresc} na karcie {k}: keep sprawdza shown() poza blokadą",
    "ZostawCzytaj": "FileReportState.keep na karcie {k} pod _deciding czyta dawne decyzje (kept())",
    "ZostawZapisz": "FileReportState.keep na karcie {k} zapisuje decyzje z nową, tata dostaje widok bez różnicy",
    "Zgasniecie": "Centrum gaśnie (brak prądu, zabity proces), tata otwiera je od nowa",
}

_CELL = {"pusta": "pustą wartość", "brak": "nic"}


def _step(action: str, before: dict[str, str], after: dict[str, str]) -> str:
    """Krok kontrprzykładu w słowach kodu; awaria w kroku to zmiana jej licznika."""

    fields = {
        "komorka": _CELL.get(after.get("komorka", "?"), after.get("komorka", "?")),
        "wpis": after.get("wpis", "?"),
        "mig": after.get("migPamiec", "?"),
        "migd": _set(after.get("migDecyzje", "?")),
        "plan": before.get("planPamiec", "?"),
        "roznica": before.get("planRoznica", "?"),
        "tresc": "?",
        "k": "?",
    }
    card = _card(before.get("etap", ""), after.get("etap", ""))
    if card is not None:
        fields["k"] = str(card + 1)
        texts = re.findall(r'"(\w+)"', after.get("tresc", ""))
        fields["tresc"] = texts[card] if card < len(texts) else "?"
    said = _STEPS[action].format(**fields)
    if action == "Sprawdzanie" and after.get("faza") == "wolne":
        said = "tata klika „Wpisz raporty z maili”: obok INTERMAX leży kopia konfliktu, Zatrzymanie przed skrzynką"
    if action == "Zapis":
        said += _wrote(before, after)
    if action == "ZapiszWynik" and before.get("kopia") == "TRUE":
        said += ": kopia konfliktu, Zatrzymanie dla taty"
    failed = [
        what
        for counter, what in (
            ("awarieIntermax", "write_cells odmawia (Refusal), INTERMAX nietknięty, pamięć i wynik bez zapisu"),
            ("awariePamieci", "zapis pamięci rzuca OSError, treść czeka w pamięci (StateFile)"),
            ("awarieWyniku", "zapis wyniku rzuca OSError, treść czeka w pamięci (StateFile)"),
            ("awarieDecyzji", "zapis decyzji rzuca OSError, treść czeka w pamięci (StateFile)"),
        )
        if after.get(counter) != before.get(counter)
    ]
    return said + (f": {', '.join(failed)}" if failed else "")


def _card(before: str, after: str) -> int | None:
    """Karta, której etap „Zostaw moją” zmienił się w kroku."""

    old, new = re.findall(r'"(\w+)"', before), re.findall(r'"(\w+)"', after)
    return next((index for index, (a, b) in enumerate(zip(old, new, strict=False)) if a != b), None)


def _wrote(before: dict[str, str], after: dict[str, str]) -> str:
    if after.get("faza") == "wolne":
        return ""
    if after.get("komorka") != before.get("komorka"):
        return f": Wpis {after.get('komorka')} w komórce z {_CELL.get(before.get('komorka', '?'), before.get('komorka'))}"
    if after.get("planRoznica", "brak") != "brak":
        return f": różnica z ręczną wartością {before.get('komorka')} (ManualDifference), Wpis {after.get('planRoznica')}"
    return ": bez zmian komórki (CellsWritten(0))"


def _set(value: str) -> str:
    return "{" + ", ".join(re.findall(r'"(\w+)"', value)) + "}"


def _tell(states: Sequence[Stan]) -> None:
    for number, (before, state) in enumerate(itertools.pairwise(states), start=1):
        print(f"   {number}. {state.petla or _step(state.akcja, before.zmienne, state.zmienne)}")
    last = states[-1].zmienne if states else {}
    print(
        f"   na koniec: komórka {last.get('komorka', '?')} (wpisał {last.get('autor', '?')}), Wpis {last.get('wpis', '?')}, "
        f"pamięć na dysku {last.get('pamiec', '?')} (odłożona: {last.get('pamiecCzeka', '?')}), "
        f"różnica w wyniku {last.get('wynik', '?')} (odłożona: {last.get('wynikCzeka', '?')}), "
        f"decyzje {_set(last.get('decyzje', ''))} (odłożone: {last.get('decyzjeCzeka', '?')}), "
        f"„Zostaw moją” wróciło przy {_set(last.get('zostawione', ''))}"
    )


MODEL = Model(
    werdykt="WPISANIE RAPORTÓW",
    skill=Path(__file__).resolve().parents[1],
    specyfikacja="WpisanieRaportow.tla",
    # Zmienna historii każdej obietnicy: zbiór przyczyn w chwili każdego zdarzenia, które ją łamie.
    obietnice={
        "NieNadpisuje": Obietnica(
            "Wpis raportu zastąpił w INTERMAX wartość, którą wpisał tata albo jego pracownik.", "nadpisane"
        ),
        "ZostawUcisza": Obietnica(
            "widok Raporty znów pokazuje różnicę, przy której tata kliknął „Zostaw moją” i dostał widok bez niej.",
            "bezDecyzji",
        ),
        "BezFalszywejRoznicy": Obietnica(
            "wynik dla widoku Raporty pokazuje różnicę z ręczną wartością przy wartości, którą wpisało samo narzędzie.",
            "falszywe",
        ),
        "KopiaZatrzymuje": Obietnica(
            "kliknięcie przeczytało skrzynkę przy kopii konfliktu OneDrive obok INTERMAX albo skończyło się "
            "podsumowaniem, choć kopia pojawiła się do końca zapisu.",
            "przeoczonaKopia",
        ),
    },
    opowiedz=_tell,
    akcje=frozenset(_STEPS),
)


if __name__ == "__main__":
    raise SystemExit(main(MODEL, opis=__doc__.splitlines()[0] if __doc__ else None))
