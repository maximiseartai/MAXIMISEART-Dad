"""Sprawdza model TLA+ wznowienia Wyceny w efenix przy każdej kolejności Zatrzymań, zgaśnięć i zmian taty w efenix.

Uruchamia TLC na każdej konfiguracji z ``model/konfiguracje.json``, porównuje wynik z jej znanymi znaleziskami i
opowiada każdy kontrprzykład krokami kodu. Konfiguracje, TLC, werdykt, znane znaleziska, narzędzia TLC i rozjazd modelu
z kodem z ``model/definicje.json`` ma ``tools/lib/model_tlc.py``: rozjazd skrypt tylko
ostrzega linią ``UWAGA:`` nad werdyktem, a w CI krok z rozjazdem nie biegnie (``tools/ci/wykonaj_zadanie.py``).

    .venv/bin/python .agents/skills/verify-wznowienie-wyceny-efenix/scripts/sprawdz_wznowienie_wyceny.py
    py -3 .agents\\skills\\verify-wznowienie-wyceny-efenix\\scripts\\sprawdz_wznowienie_wyceny.py
"""

from __future__ import annotations

from collections.abc import Sequence
import itertools
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))

from model_tlc import Model, Obietnica, Stan, main

# Akcja modelu i krok kodu, który opisuje (tabela w SKILL.md), w słowach kontrprzykładu.
_STEPS = {
    "Start": "tata uruchamia Wycenę w efenix (tryb: bez albo z Przekazaniem)",
    "Otworz": "okno szuka zlecenia {z}, a gdy nie jest „Do akceptacji”, otwiera je i decyduje (_outcome, completion)",
    "ZaladujEmmetta": "okno klika „Załaduj do zlecenia” w zleceniu {z}: efenix ma Wycenę Emmetta (load_emmett, _emmett)",
    "OdczytPoEmmetcie": "okno czyta stronę zlecenia {z} po Emmetcie i liczy, co dopisać (_completed, completion)",
    "BrakPozycji": "strona zlecenia {z} po Emmetcie nie ma pozycji z ilością w pliku: błąd zlecenia",
    "Wpisz": "okno wpisuje ilość z pliku w zleceniu {z}, efenix ją zapisuje (enter_quantity)",
    "Potwierdz": "efenix odpowiada kwotą w zleceniu {z}",
    "Przekaz": "okno przekazuje zlecenie {z} do akceptacji, efenix zmienia status (forward_to_accept)",
    "OdmowaPrzekazania": "efenix odmawia Przekazania zlecenia {z} oknem informacji: błąd zlecenia (forward_to_accept, _refusal)",
    "Szukaj": "okno szuka zlecenia {z} ponownie i czyta jego status (_forwarded, listing)",
    "KoniecZlecenia": "zlecenie {z} ma wynik",
    "Zatrzymanie": "okno efenix się nie dokończyło działania: Zatrzymanie (StopError) w zleceniu {z}",
    "Znaczniki": "Znaczniki efenix przy gotowych i Znaczniki przekazania przy przekazanych zleceniach (_mark), koniec Uruchomienia",
    "Zgasniecie": "Centrum gaśnie w zleceniu {z} (brak prądu, zabity proces)",
    "Tata": "tata sam zmienia ilość w efenix",
    "Koniec": "ostatnie Uruchomienie się skończyło, nic więcej się nie dzieje",
}


# Zmienne stanu modelu, które opowieść kontrprzykładu pokazuje po każdym kroku, i ich nazwy.
_SHOWN = (("efenix", "efenix"), ("status", "status"), ("wynik", "wynik"), ("znacznik", "Znaczniki"))


def _tell(states: Sequence[Stan]) -> None:
    for number, (before, state) in enumerate(itertools.pairwise(states), start=1):
        step = state.petla or _STEPS[state.akcja].format(z=before.zmienne.get("zlecenie", "?"))
        seen = ", ".join(f"{name} {_brief(state.zmienne[variable])}" for variable, name in _SHOWN if variable in state.zmienne)
        print(f"   {number}. {step}: {seen}")


def _brief(value: str) -> str:
    return " ".join(value.split())


MODEL = Model(
    werdykt="WZNOWIENIE WYCENY",
    skill=Path(__file__).resolve().parents[1],
    specyfikacja="WznowienieWyceny.tla",
    # Zmienna historii każdej obietnicy: zbiór z jednym zbiorem śladów w chwili zdarzenia, które ją łamie.
    obietnice={
        "NieCzysciWycenyTaty": Obietnica(
            "narzędzie ładuje Wycenę Emmetta do zlecenia, które ma już ilości, i czyści je.", "czysciTate"
        ),
        "NieObnizaIlosci": Obietnica("narzędzie obniża albo czyści ilość w efenix.", "obniza"),
        "ZmianaTatyZostaje": Obietnica(
            "zlecenie, które tata zmienił, nie kończy się Ostrzeżeniem Emmetta przy ilości większej niż plik albo nie jest"
            " gotowe bez niej.",
            "zlyWynikPoTacie",
        ),
        "ZnacznikTylkoNaWycenionym": Obietnica(
            "Znacznik efenix albo Znacznik przekazania staje przy zleceniu, którego nie opisuje (wycena różna od pliku,"
            " zlecenie nie „Do akceptacji”), albo Znacznik efenix zastępuje Znacznik przekazania.",
            "zlyZnacznik",
        ),
        "BladTylkoPoZmianieTaty": Obietnica(
            "tata dostaje błąd albo Ostrzeżenie Emmetta przy zleceniu, którego sam nie zmieniał.", "bladBezPowodu"
        ),
        "PrzekazujeTylkoGotowe": Obietnica(
            "narzędzie przekazuje do akceptacji zlecenie, które nie jest gotowe, albo w trybie bez Przekazania.", "zlePrzekazanie"
        ),
        "NieZmieniaPrzekazanego": Obietnica("narzędzie zmienia coś w zleceniu „Do akceptacji”.", "zmianaPrzekazanego"),
    },
    opowiedz=_tell,
    akcje=frozenset(_STEPS),
)


if __name__ == "__main__":
    raise SystemExit(main(MODEL, opis=__doc__.splitlines()[0] if __doc__ else None))
