"""Sprawdza model TLA+ Aktualizacji narzędzia przy każdej kolejności awarii (TLC).

Uruchamia TLC na każdej konfiguracji z ``model/konfiguracje.json``, porównuje wynik z jej znanymi znaleziskami i
opowiada każdy kontrprzykład krokami kodu. Konfiguracje, TLC, werdykt, znane znaleziska, narzędzia TLC (przypięte
``jdk4py`` i ``tla2tools.jar`` w ``.verification/formal-aktualizacja``, ignorowanym przez Gita) i rozjazd modelu z kodem
z ``model/definicje.json`` ma ``tools/lib/model_tlc.py``: w CI (``GITHUB_ACTIONS=true``) rozjazd kończy się od razu
linią ``AKTUALIZACJA: ROZJAZD MODELU Z KODEM`` i kodem 1, bez TLC.

    .venv/bin/python .agents/skills/verify-aktualizacja-narzedzia/scripts/sprawdz_aktualizacje.py
    py -3 .agents\\skills\\verify-aktualizacja-narzedzia\\scripts\\sprawdz_aktualizacje.py
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))

from model_tlc import Model, Obietnica, Stan, main


def _tell(states: Sequence[Stan]) -> None:
    first, last = states[0].zmienne, states[-1].zmienne
    yes = {"TRUE": "tak", "FALSE": "nie"}
    print(
        "   nowa wersja: usuwa plik taty z config/: {}, zmienia requirements.txt: {}, startuje: {}".format(
            yes[first["nowaUsuwaPlikTaty"]], yes[first["nowaZmieniaWymagania"]], yes[first["nowaStartuje"]]
        )
    )
    for number, state in enumerate(states[1:], start=1):
        print(f"   {number}. {state.petla or state.zmienne['krok']}")
    print(
        f"   na koniec: klon na wersji {last['head']}, plik taty: {last['plikTaty']}, "
        f"biblioteki: {last['biblioteki']}, Centrum: {last['centrum']}, dziennik: {last['dziennik']}"
    )


MODEL = Model(
    werdykt="AKTUALIZACJA",
    skill=Path(__file__).resolve().parents[1],
    specyfikacja="AktualizacjaNarzedzia.tla",
    obietnice={
        "TataMaDzialajacaWersje": Obietnica("tata zostaje bez wersji, która startuje, albo bez swojego pliku w config/."),
        "OpiekunCofaTylkoNieudana": Obietnica("opiekun cofa nową wersję, która by wystartowała."),
        "OkienkoTylkoGdyNicNieDziala": Obietnica("opiekun pokazuje okienko „nie wystartowało”, choć Centrum działa."),
        "TataNieZostajeBezOdpowiedzi": Obietnica("nic nie działa, a tata nie dostaje okienka, tylko martwą kartę."),
        "KartaNieKlamie": Obietnica("karta mówi „Narzędzie zaktualizowane”, choć nowa wersja nie działa."),
        "KartaNieStraszy": Obietnica("karta nowej, działającej wersji mówi o porażce aktualizacji."),
        "Postep": Obietnica("dziennik „Aktualizacja w toku” zostaje na zawsze.", czasowa=True),
    },
    opowiedz=_tell,
    zakleszczenie=False,
)


if __name__ == "__main__":
    raise SystemExit(main(MODEL, opis=__doc__.splitlines()[0] if __doc__ else None))
