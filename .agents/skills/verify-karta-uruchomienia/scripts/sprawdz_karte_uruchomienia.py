"""Sprawdza model TLA+ karty przeglądarki, która śledzi Uruchomienie procesu i Aktualizację narzędzia.

Uruchamia TLC na każdej konfiguracji z ``model/konfiguracje.json``: każda kolejność zdarzeń strumienia Uruchomień,
odpowiedzi HTTP, kliknięć taty w tej karcie i w drugiej karcie, ponownych startów Centrum i odczytów stanu
Aktualizacji. Porównuje wynik ze znanymi znaleziskami i opowiada każdy kontrprzykład krokami kodu. Konfiguracje,
TLC, werdykt, znane znaleziska, narzędzia TLC i rozjazd modelu z kodem z ``model/definicje.json`` ma
``tools/lib/model_tlc.py``: rozjazd skrypt tylko ostrzega linią ``UWAGA:`` nad werdyktem, a w CI krok z rozjazdem nie
biegnie (``tools/ci/wykonaj_zadanie.py``).

    .venv/bin/python .agents/skills/verify-karta-uruchomienia/scripts/sprawdz_karte_uruchomienia.py
    py -3 .agents\\skills\\verify-karta-uruchomienia\\scripts\\sprawdz_karte_uruchomienia.py
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
    "KlikStart": "tata klika start w tej karcie (useAction starting: before = shownRun(latest), fetch startRun)",
    "KlikDecyzja": "tata odpowiada na Decyzję w tej karcie (useAction deciding, fetch decideRun)",
    "NoweUruchomienie": "tata klika „Nowe Uruchomienie procesu” na karcie wyniku (newRun = setDismissed)",
    "WyborNaKarcieStartu": "tata wybiera proces albo okres na karcie startu (setDraft)",
    "WyborSpozaKarty": "tata klika krok w Tablicy okresów albo „Gotowe, rozlicz pracowników” (DraftButton: setDraft)",
    "OdpowiedzStartu": "karta dostaje odpowiedź startu (setDraft(null); bez przyjętego w latest czeka na strumień)",
    "OdpowiedzDecyzji": "karta dostaje odpowiedź Decyzji (czeka, aż strumień przestanie pokazywać Decyzję)",
    "Odbierz": "strumień dostarcza następny widok (onEvent albo onUnreadable)",
    "Zerwij": "strumień się zrywa albo karta znika z wierzchu (EventSource error, followVisibility)",
    "Polacz": "strumień łączy się ponownie i dostaje najpierw bieżący widok (_event_stream: current)",
    "ObslugaStartu": "serwer obsługuje start tej karty (RunHost.start: odmowa albo widok startu przed odpowiedzią)",
    "ObslugaDecyzji": "serwer obsługuje Decyzję tej karty (RunHost.decide)",
    "InnaKartaStart": "druga karta uruchamia (RunHost.start)",
    "InnaKartaDecyzja": "druga karta odpowiada na Decyzję (RunHost.decide)",
    "PytanieODecyzje": "Uruchomienie pyta o Decyzję taty (Run.confirm)",
    "KoniecUruchomienia": "Uruchomienie się kończy: wynik na karcie (RunHost.end)",
    "Restart": "Centrum gaśnie i startuje od nowa z idle (nowy RunHost)",
    "KlikAktualizuj": "tata klika „Zaktualizuj narzędzie” (getHealth przed startem)",
    "ZdrowieStartu": "karta zapamiętuje instance i wysyła startToolUpdate",
    "ObslugaStartuAkt": "serwer zaczyna Aktualizację narzędzia (ToolUpdates.start) albo odmawia",
    "KoniecStartuAkt": "karta dostaje odpowiedź startu aktualizacji (show)",
    "Wejscie": "tata wchodzi na stronę z przyciskiem aktualizacji: read() wysyła getToolUpdate",
    "ObslugaOdczytu": "serwer odpowiada na odczyt stanu aktualizacji (GET /api/tool-update)",
    "OdbierzOdczyt": "karta dostaje odpowiedź odczytu (read: show)",
    "Tik": "mija POLL_MS przy trwającej aktualizacji: getHealth",
    "ZdrowiePetli": "karta dostaje health w pętli (inny instance: przeładowanie; ten sam: getToolUpdate)",
    "ObslugaPetli": "serwer odpowiada na odczyt pętli",
    "OdbierzPetli": "karta dostaje odpowiedź pętli (show)",
    "AktPorazka": "aktualizacja zawodzi przed ponownym startem (ToolUpdates._update)",
    "AktZamkniecie": "Centrum zamyka się do ponownego startu po aktualizacji (_restart)",
    "AktPonownyStart": "nowe Centrum startuje i czyta wynik aktualizacji (_after_restart)",
}


# Zmienne stanu modelu, które opowieść kontrprzykładu pokazuje po każdym kroku, i ich nazwy.
_SHOWN = (
    ("srvRun", "serwer: Uruchomienie"),
    ("srvStan", "jego stan"),
    ("widok", "karta: widok"),
    ("draft", "draft"),
    ("startuje", "start"),
    ("decyduje", "Decyzja"),
    ("aSrv", "serwer: aktualizacja"),
    ("upd", "karta: aktualizacja"),
    ("startA", "start aktualizacji"),
)


def _tell(states: Sequence[Stan]) -> None:
    for number, (before, state) in enumerate(itertools.pairwise(states), start=1):
        step = state.petla or _STEPS[state.akcja]
        changed = [
            f"{name} {_brief(state.zmienne[variable])}"
            for variable, name in _SHOWN
            if variable in state.zmienne and state.zmienne[variable] != before.zmienne.get(variable)
        ]
        print(f"   {number}. {step}" + (f": {', '.join(changed)}" if changed else ""))


def _brief(value: str) -> str:
    return " ".join(value.split())


MODEL = Model(
    werdykt="KARTA URUCHOMIENIA",
    skill=Path(__file__).resolve().parents[1],
    specyfikacja="KartaUruchomienia.tla",
    # Zmienna historii każdej obietnicy: zbiór z jednym zbiorem śladów w chwili zdarzenia, które ją łamie.
    obietnice={
        "WynikNaKarcie": Obietnica(
            "karta pokazuje kartę startu zamiast wyniku Uruchomienia, choć tata w tej karcie po tym wyniku nie wybrał"
            " nowego Uruchomienia.",
            "zaslonietyWynik",
        ),
        "AktualizacjaNieWraca": Obietnica(
            "karta wraca do „Zaktualizuj narzędzie” w trakcie aktualizacji, którą pokazała jako trwającą.",
            "wrocilPrzycisk",
        ),
        "PrzyciskWraca": Obietnica(
            "start albo Decyzja z tej karty trwa bez końca (przyciski zostają wyłączone), choć ostatni widok serwera"
            " da się odczytać.",
            "slady",
            czasowa=True,
        ),
    },
    opowiedz=_tell,
    akcje=frozenset(_STEPS),
    zakleszczenie=False,
)


if __name__ == "__main__":
    raise SystemExit(main(MODEL, opis=__doc__.splitlines()[0] if __doc__ else None))
