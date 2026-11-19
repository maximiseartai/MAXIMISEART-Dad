"""Uruchamia TLC na każdej konfiguracji z ``model/konfiguracje.json``, porównuje wynik z jej znanymi znaleziskami i
opowiada każdy kontrprzykład krokami kodu ``CentrumSettings``. Konfiguracje, TLC, werdykt, znane znaleziska, narzędzia
TLC i rozjazd modelu z kodem z ``model/definicje.json`` ma ``tools/lib/model_tlc.py``: rozjazd skrypt tylko ostrzega
linią ``UWAGA:`` nad werdyktem, a w CI krok z rozjazdem nie biegnie (``tools/ci/wykonaj_zadanie.py``).

    .venv/bin/python .agents/skills/verify-historia-ustawien/scripts/sprawdz_historie_ustawien.py
    py -3 .agents\\skills\\verify-historia-ustawien\\scripts\\sprawdz_historie_ustawien.py
"""

from __future__ import annotations

from collections.abc import Sequence
import itertools
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))

from model_tlc import Model, Obietnica, Stan, main

OPIS = "Sprawdza model TLA+ Historii Ustawień, pamięci właściciela i zmian z Wydania przy każdej kolejności kroków i awarii."

# Akcja modelu i krok kodu, który opisuje (tabela w SKILL.md), w słowach kontrprzykładu.
_STEPS = {
    "StartPamiecZmian": "start Centrum: apply_release_changes czyta pamięć zmian z Wydań (Memory.applied)",
    "StartHistoria": "_apply_pending: _release_rows czyta Historię Ustawień",
    "Odczyt": "proces bierze migawkę Ustawień (CentrumSettings.snapshot)",
    "ZapisTaty": "tata zapisuje sekcję w oknie Ustawień (change_* -> _by_dad -> _change)",
    "CofnijTaty": "tata klika „Cofnij” w Historii (CentrumSettings.undo)",
    "Porownaj": "_compared: odczyt pliku i jego pamięci (settings_bytes, Memory.read)",
    "WierszSpoza": "_compared: History.append wiersza spoza Centrum (_outside_row)",
    "PamiecSpoza": "_compared: _remember po wierszu spoza Centrum",
    "Uzyj": "proces liczy wartością _value(observed)",
    "Propozycja": "_apply: change.propose na wartości z _observe",
    "Wylicz": "_change: edit(current), różnica kluczy (file.diff)",
    "Zapis": "_change: place.write(new) (replace_atomically)",
    "Wiersz": "_change: History.append wiersza zmiany",
    "Przywroc": "_change: _put_back poprzedniej treści po nieudanym wierszu",
    "NieZapisano": "_change zwraca NotSaved",
    "Pamiec": "_change: _remember(Remembered(new, new))",
    "PamiecZmian": "_apply_pending: Memory.remember_applied",
    "Reczna": "ktoś zapisuje plik Ustawień poza Centrum",
    "Zgasniecie": "Centrum gaśnie, a tata otwiera je znowu (start stosuje zmiany z Wydania przed pierwszym zapytaniem)",
}

# Wartości pliku w słowach czytelnika.
_VALUES = {
    "v0": "wartość sprzed Wydania",
    "r": "wartość zmiany z Wydania",
    "t": "wartość taty",
    "x": "wartość wpisana poza Centrum",
    "d": "wartość domyślna z Wydania",
    "zly": "zła treść",
    "brak": "brak pliku",
}
_KTO = {"proces": "odczyt dla procesu", "tata": "zapis taty", "wydanie": "zmiana z Wydania", "-": ""}

# Zmiana licznika awarii w kroku i jej słowa.
_FAILURES = (
    ("awZapisu", "place.write rzuca OSError"),
    ("awWiersza", "History.append rzuca OSError"),
    ("awPrzywrocenia", "_put_back nie przywraca pliku"),
    ("awPamieci", "Memory.write rzuca OSError"),
    ("awPamieciZmian", "Memory.remember_applied rzuca OSError"),
    ("nieczPamieci", "Memory.read: Unreadable"),
    ("nieczHistorii", "History.read: Unreadable"),
)


def _value(raw: str) -> str:
    return _VALUES.get(raw.strip('"'), raw)


def _field(record: str, name: str) -> str:
    found = re.search(rf'{name} \|-> "?([\w-]+)"?', record)
    return found[1] if found else "?"


def _rows(value: str) -> str:
    found = re.findall(r'zrodlo \|-> "(\w+)",\s*wynik \|-> "(\w+)",\s*przed \|-> "(\w+)",\s*po \|-> "(\w+)"', value)
    return "[" + "; ".join(f"{source} {result}: {_value(before)} → {_value(after)}" for source, result, before, after in found) + "]"


def _step(action: str, before: dict[str, str], after: dict[str, str]) -> str:
    """Krok kontrprzykładu w słowach kodu, z tym, co zmienił w pliku, pamięci i Historii."""

    said = _STEPS[action]
    who = _KTO.get(_field(after.get("op", ""), "kto"), "")
    if action in {"Porownaj", "WierszSpoza", "PamiecSpoza", "Wylicz", "Zapis", "Wiersz", "Przywroc", "Pamiec", "Propozycja"} and who:
        said += f" [{who}]"
    if action == "Uzyj":
        said += f": {_value(_field(before.get('op', ''), 'obs'))}"
    failed = [what for counter, what in _FAILURES if after.get(counter) != before.get(counter)]
    if failed:
        said += f": {', '.join(failed)}"
    if after.get("plik") != before.get("plik"):
        said += f"; plik: {_value(after.get('plik', ''))}"
    if after.get("historia") != before.get("historia"):
        said += f"; Historia: {_rows(after.get('historia', ''))}"
    return said


def _tell(states: Sequence[Stan]) -> None:
    for number, (before, state) in enumerate(itertools.pairwise(states), start=1):
        print(f"   {number}. {state.petla or _step(state.akcja, before.zmienne, state.zmienne)}")
    last = states[-1].zmienne if states else {}
    memory = last.get("pamiec", "")
    print(
        f"   na koniec: plik {_value(last.get('plik', ''))}, pamięć pliku: widziany {_value(_field(memory, 'widziany'))}, "
        f"dobry {_value(_field(memory, 'dobry'))}; Historia {_rows(last.get('historia', ''))}; "
        f"pamięć zmian z Wydań {'ma zmianę' if last.get('zmianyZWydan') == 'TRUE' else 'bez zmiany'}"
    )


MODEL = Model(
    werdykt="HISTORIA USTAWIEŃ",
    skill=Path(__file__).resolve().parents[1],
    specyfikacja="HistoriaUstawien.tla",
    obietnice={
        "LiczyZapisanym": Obietnica(
            "Uruchomienie liczy wartością, której Historia Ustawień nie pokazuje jako bieżącej (ani „po” najnowszego "
            "wiersza „zapisano”, ani wartości sprzed Wydania): Maks nie wytłumaczy wyniku z Historii, a tata cofa nie to.",
            "bezWiersza",
        ),
        "WydanieNieNadpisuje": Obietnica(
            "zmiana z Wydania przy starcie nadpisuje wartość, którą tata zapisał (albo przywrócił „Cofnij”), gdy ta "
            "zmiana już weszła.",
            "nadpisane",
        ),
        "NieZapisanoZnaczyNie": Obietnica(
            "tata czyta „nie zapisano”, a plik ma wartość, którą właśnie wpisał: procesy liczą nią bez jego wiedzy.",
            "klamstwo",
        ),
        "CofnijPrzywracaBajty": Obietnica(
            "„Cofnij” zapisuje inne bajty niż sprzed cofanej zmiany, np. treść z Wydania w miejscu pliku, którego nie "
            "było: następne Wydanie z nowymi wartościami domyślnymi nie dociera do taty (ADR 0032).",
            "zleBajty",
        ),
    },
    opowiedz=_tell,
    akcje=frozenset(_STEPS),
)


if __name__ == "__main__":
    raise SystemExit(main(MODEL, opis=OPIS))
