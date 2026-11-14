"""Strażnik reguły danych pracy Centrum dla Logów Uruchomienia (ADR 0025) i dowód, że Logi albo tekst go przeszły.

Przed zapisem pliku Logów i przed wysyłką Logi przechodzą przez strażnika (``guard_logs``), a plik (``LogsOnDisk.write``)
i wysyłka (``comment_versions.post_of``) biorą tylko Logi z niego (``GuardedLogs``) i tekst komentarza z niego
(``GuardedText``, ``guard_text``): wartość ``ADRES`` albo numeru Orange z przeczytanych plików, także wpisana w inną
komórkę Kopii wejścia albo zapisana przez Excel jako liczba, staje się maską z uwagą techniczną, a telefony i ulice w
tekście są zamaskowane. Pola, które niosą tylko słowa i chwile narzędzia (``TOOL_FIELDS``), i nazwy pól schematu
zostają bez maski (#936). Pole typowane, które maski nie przyjmuje, traci wartość (``GuardCut``), a uwaga o tym jest
jedynym zapisem cięcia w pliku Logów, z którego odtworzenie czyta cięcia (``guard_cuts``).

Diagnoza Zatrzymania dopisuje się do Logów, które przeszły przez strażnika (``GuardedLogs.with_diagnosis``), i
przechodzi przez niego razem z nimi.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import re
from typing import Final, final

from pydantic import BaseModel, ValidationError
from pydantic.fields import FieldInfo

from rozliczenia.centrum.run_logs import LoggedDiagnosis, RunLog
from rozliczenia.client_data import READ_VALUES, ForbiddenValues, Guarded, LogsText, guarded, guarded_number, logs_text


def _guarded(record: RunLog, forbidden: ForbiddenValues) -> RunLog:
    """Logi po strażniku reguły danych (``guarded``): każdy tekst i klucz bez zakazanych wartości, z
    zamaskowanymi telefonami i ulicami, a każda zamaskowana wartość to uwaga techniczna z kolumną i polem pliku.

    Strażnik widzi każdy tekst pliku: także datę, kwotę i wartość ``Decimal``, które JSON zapisuje jako tekst. Liczbę
    sprawdza w polu z wartościami z komórek pliku taty albo ze strony efenix (``READ_VALUES``: komórki Kopii wejścia i
    ilości przy zleceniu Wyceny w efenix) w tekście, który pokazuje Excel (``guarded_number``), i liczba z
    zakazaną wartością albo telefonem staje się w całości maską. Liczb, które policzyło narzędzie, nie sprawdza.

    Strażnik porównuje słowa, a nie pochodzenie wartości, więc wartość z pliku taty równa słowu albo chwili narzędzia
    trafiłaby też w pole, które niesie tylko to, co dało narzędzie. Takich pól (``TOOL_FIELDS``) nie maskuje i zostawia
    w nich wartość z rekordu, a klucza pola modelu Logów (nazwy pola schematu) też nie: maska w nich gubiła całe Logi
    albo ich okres, Uruchomienie i commit (#936). Klucz słownika (operator, kod pozycji, litera kolumny) to dane, więc go
    maskuje.

    Pole to ścieżka JSON z nazw pól, a klucz z danych (operator, kod pozycji) jest w niej ``[…]``, żeby uwaga nie
    niosła treści. Uwaga o polu Kopii wejścia idzie do ``input_copy_notes``, a każda inna do ``technical_notes``, które
    pokazuje karta Uruchomienia z Logów: Kopii karta nie pokazuje, więc karta po starcie Centrum zostaje taka jak przed
    nim (ADR 0017). Pole typowane, które maski nie przyjmuje, zostaje puste albo odpada z uwagą techniczną
    (``_representable``). Logi bez niczego do zamaskowania wracają te same.
    """

    notes: list[str] = []
    copy_notes: list[str] = []

    def noted(found: Guarded, place: str) -> str:
        (copy_notes if _field_of(place) == _INPUT_COPY else notes).extend(found.notes)
        return found.text

    def text(value: str, place: str) -> str:
        return noted(guarded(forbidden, value, place or "Logi"), place)

    def number(value: int | float, place: str) -> object:
        found = guarded_number(forbidden, value, place)
        return value if found is None else noted(found, place)

    def walk(source: object, value: object, place: str, read: bool) -> object:
        """``value`` z JSON-a Logów i ``source``, z którego powstał (``None``: poza modelem Logów); ``read``: w polu
        ``READ_VALUES``."""

        if place in TOOL_FIELDS:
            return value
        if isinstance(value, str):
            return text(value, place)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return number(value, place) if read else value
        if isinstance(value, list):
            sources = source if isinstance(source, list) else [None] * len(value)
            return [
                walk(item, entry, f"{place}[{index}]", read)
                for index, (item, entry) in enumerate(zip(sources, value, strict=True))
            ]
        if isinstance(value, dict):
            items: dict[str, object] = {}
            for key, entry in value.items():
                child, field = _child(source, key)
                marked = field is not None and READ_VALUES in field.metadata
                items[key if field is not None else text(key, place)] = walk(child, entry, _field(place, key), read or marked)
            return items
        return value

    dumped = record.model_dump(mode="json")
    walked = walk(record, dumped, "", False)
    if walked == dumped:
        return record
    assert isinstance(walked, dict)
    walked["technical_notes"] = [*walked["technical_notes"], *dict.fromkeys(notes)]
    walked["input_copy_notes"] = [*walked["input_copy_notes"], *dict.fromkeys(copy_notes)]
    return _representable(walked)


_INPUT_COPY: Final = "input_copy"
"""Pole Kopii wejścia w Logach; uwagi strażnika o nim idą do ``input_copy_notes``."""

TOOL_FIELDS: Final = frozenset(
    {
        "run_id",
        "process",
        "mode",
        "period",
        "started_at",
        "ended_at",
        "tool",
        "result",
        "ending",
        "stop_kind",
        "phases",
        "trace",
        "dad_actions",
        "environment.system",
        "environment.python",
    }
)
"""Pola Logów (ścieżka JSON jak w uwadze strażnika), które niosą tylko słowa i chwile narzędzia, więc strażnik
(``guard_logs``) zostawia w nich wartość z rekordu (#936). Każde ma wartość z kodu narzędzia, a nie z pliku taty:
``run_id`` to ``uuid4``, ``period`` token okresu z ``parse_period_token`` albo z zegara (INTERMAX), ``process``,
``mode``, ``result``, ``ending`` i ``stop_kind`` to wartości zamkniętych list schematu, ``started_at`` i ``ended_at``
chwile zegara Centrum (w Logach Urwanego Uruchomienia z dziennika Wyceny, który pisze Centrum), ``tool`` Wydanie i
commit z Gita narzędzia, ``phases`` etapy z zamkniętej listy ze stanem, czasem i chwilami projekcji postępu, ``trace``
typy wyjątków i ramki kodu narzędzia bez treści wyjątku (``call_trace``), ``dad_actions`` chwile, wartości zamkniętych
list i operacje API z kontraktu bez treści zapytań, a ``system`` i ``python`` Środowiska moduł ``platform``.

Pole spoza listy może nieść treść pliku taty (tekst Komunikatu, Wykonawca, nazwa pliku, odczyt strony efenix, Kopia
wejścia), więc strażnik maskuje je dalej, także w polu z wartością narzędzia w modelu, który niesie i jedno, i drugie
(kod Komunikatu, wynik zlecenia efenix). Liczby, które policzyło narzędzie (``schema_version``, ``duration_ms``,
``issue_count``, ``interruption``), zostają i bez listy, bo strażnik sprawdza tylko liczby z ``READ_VALUES``. Każde
pole najwyższego poziomu bez ``None`` poza Środowiskiem jest więc na liście, jest liczbą narzędzia albo listą, z której
maska zabiera najwyżej element, a Środowisko (``environment``) ma poza listą tylko pliki procesu (lista albo ``None``),
więc maska nie gubi całych Logów (``UnrepresentableLogs``).

Pole z listy strażnik zostawia z całym poddrzewem, więc test struktury w ``tests/test_komentarz_logow_uruchomienia.py``
przechodzi typ każdego z nich (modele, dataclassy, unie) i czerwienieje, gdy w poddrzewie jest typ, który przyjmuje
dowolny tekst (``str`` spoza jawnych wyjątków z powodem w teście, słownik, ``Any``), liczba ``READ_VALUES`` albo typ,
którego test nie zna."""

_Path = tuple[str | int, ...]


class UnrepresentableLogs(ValueError):
    """Logi, w których maska strażnika trafiła w pole, które nie może stracić wartości: pole najwyższego poziomu bez
    ``None`` spoza listy pól narzędzia (``TOOL_FIELDS``), albo ``stuck``: cięcia (``_representable``) przestały zmieniać
    Logi, czyli błąd w cięciach. ``place``: to pole albo miejsce ostatniego cięcia.

    Schemat Logów nie ma dziś pola najwyższego poziomu bez ``None``, które gubiłoby Logi (#936). Nowe takie pole wywraca
    przemiatanie pełnych Logów w ``tests/test_komentarz_logow_uruchomienia.py``, które każe pełnym Logom mieć wartość w
    każdym polu ``RunLog``: każdy tekst i każda liczba tych Logów (od ``MIN_VALUE`` znaków) po kolei jako wartość z pliku
    taty, także liczba w polu ``READ_VALUES``."""

    def __init__(self, place: str, *, stuck: bool = False) -> None:
        reason = (
            f"cięcia strażnika przestały zmieniać Logi (ostatnie w polu {place})"
            if stuck
            else f"Logi bez miejsca na maskę strażnika w polu {place} (#936)"
        )
        super().__init__(reason)
        self.place = place
        self.stuck = stuck


@dataclass(frozen=True)
class GuardCut:
    """Miejsce Logów, które straciło wartość, bo strażnik zamaskował w nim pole, które maski nie przyjmuje
    (``_representable``): ``removed`` element listy odpadł, inaczej pole jest puste. ``place``: ścieżka JSON jak w
    uwadze strażnika, bez spacji (``_place``)."""

    place: str
    removed: bool

    @property
    def field(self) -> str:
        """Pole Logów najwyższego poziomu, w którym jest miejsce cięcia (``input_copy``, ``efenix_orders``)."""

        return _field_of(self.place)

    @property
    def note(self) -> str:
        """Uwaga techniczna o cięciu. W pliku Logów cięcie ma tylko ją, a ``guard_cuts`` czyta je z niej, więc zdanie
        jest częścią schematu Logów: Logi u taty mają je w tej postaci."""

        what = f"pominięto {self.place}" if self.removed else f"pole {self.place} jest puste"
        return f"Reguła danych: {what}: strażnik zamaskował w nim wartość, której pole nie przyjmuje."


def guard_cuts(record: RunLog) -> tuple[GuardCut, ...]:
    """Cięcia strażnika w Logach ``record`` z ich uwag (``GuardCut.note``) w uwagach technicznych i uwagach Kopii
    wejścia."""

    found = (_CUT_NOTE.fullmatch(note) for note in (*record.technical_notes, *record.input_copy_notes))
    return tuple(
        GuardCut(match["removed"] or match["emptied"], match["removed"] is not None) for match in found if match
    )


_CUT_NOTE: Final = re.compile(
    r"Reguła danych: (?:pominięto (?P<removed>\S+)|pole (?P<emptied>\S+) jest puste): strażnik zamaskował w nim "
    r"wartość, której pole nie przyjmuje\."
)
"""``GuardCut.note`` w drugą stronę."""


def _field_of(place: str) -> str:
    """Pole Logów najwyższego poziomu miejsca ``place`` (ścieżka JSON jak w uwadze strażnika)."""

    return re.split(r"[.\[]", place)[0]


def _representable(walked: dict[str, object]) -> RunLog:
    """Logi z JSON-a po strażniku (``_guarded``), w którym każde pole przyjmuje swoją wartość.

    Pole typowane (kwota ``Decimal``, data, wartość z zamkniętej listy), w którym strażnik zamaskował tekst, maski nie
    przyjmuje, więc takie Logi nie przeszłyby walidacji i przepadły. Pole dostaje ``None``, a gdy i ``None`` nie
    przyjmuje, odpada najbliższy element listy nad nim (zlecenie, krok, plik) albo ``None`` dostaje pole nad nim
    (``_cut``), z uwagą techniczną o tym miejscu (``GuardCut``). Pole Logów najwyższego poziomu bez ``None`` i poza
    listą nie ma czego stracić, więc dałoby ``UnrepresentableLogs``, ale każde takie pole niesie słowa narzędzia, których
    strażnik nie maskuje (``TOOL_FIELDS``, #936).

    Każde cięcie zabiera Logom co najmniej jedną wartość, więc cięć jest najwyżej tyle, ile Logi mają wartości:
    po tylu obrotach bez poprawnych Logów pętla kończy się ``UnrepresentableLogs``, a nie wisi z końcem Uruchomienia.
    """

    # Miejsce w Logach przed cięciami → odpadło z listy (``False``: dostało ``None``). Błędy idą od ostatniego, więc
    # element, który odpada, przesuwa w liście tylko elementy już bez błędów, a miejsca w uwagach są te sprzed cięć.
    cuts: dict[_Path, bool] = {}
    place: _Path = ()
    for _ in range(_values(walked) + 1):
        try:
            record = RunLog.model_validate(walked)
        except ValidationError as failure:
            place, removed = _cut(walked, _existing(walked, failure.errors()[-1]["loc"]))
            if removed:
                cuts = {cut: kind for cut, kind in cuts.items() if cut[: len(place)] != place}
            cuts[place] = removed
            continue
        notes: dict[bool, list[str]] = {True: [], False: []}  # Kopia wejścia → uwagi
        for cut in (GuardCut(_place(path), removed) for path, removed in sorted(cuts.items())):
            notes[cut.field == _INPUT_COPY].append(cut.note)
        return record.model_copy(
            update={
                "technical_notes": [*record.technical_notes, *notes[False]],
                "input_copy_notes": [*record.input_copy_notes, *notes[True]],
            }
        )
    raise UnrepresentableLogs(_place(place), stuck=True)


def _cut(walked: dict[str, object], path: _Path) -> tuple[_Path, bool]:
    """Najgłębsze miejsce ścieżki błędu walidacji ``path``, które może stracić wartość, i czy odpadło z listy.

    Element listy odpada, a pole z wartością dostaje ``None``. Pole, które już ma ``None``, a wciąż ma błąd, ``None``
    nie przyjmuje, więc wartość traci miejsce wyżej; ścieżka bez takiego miejsca to ``UnrepresentableLogs``.
    """

    for depth in range(len(path), 0, -1):
        place = path[:depth]
        container, key = _at(walked, place[:-1]), place[-1]
        if isinstance(container, list) and isinstance(key, int):
            del container[key]
            return place, True
        if isinstance(container, dict) and container[key] is not None:
            container[key] = None
            return place, False
    raise UnrepresentableLogs(_place(path))


def _values(value: object) -> int:
    """Liczba wartości JSON-a (słowników, list i liści) bez ``None``: ile razy najwyżej da się coś z niego zabrać."""

    if isinstance(value, dict):
        return 1 + sum(_values(entry) for entry in value.values())
    if isinstance(value, list):
        return 1 + sum(_values(entry) for entry in value)
    return 0 if value is None else 1


def _existing(walked: object, location: Sequence[str | int]) -> _Path:
    """Najdłuższy początek miejsca błędu walidacji ``location``, który jest w JSON-ie ``walked`` (dalej pydantic dopisuje
    nazwy wariantów typu)."""

    path: list[str | int] = []
    for key in location:
        if isinstance(walked, dict) and key in walked:
            walked = walked[key]
        elif isinstance(walked, list) and isinstance(key, int):
            walked = walked[key]
        else:
            break
        path.append(key)
    return tuple(path)


def _at(walked: object, path: _Path) -> object:
    for key in path:
        if isinstance(walked, dict):
            walked = walked[key]
        elif isinstance(walked, list) and isinstance(key, int):
            walked = walked[key]
    return walked


def _place(path: _Path) -> str:
    place = ""
    for key in path:
        place = f"{place}[{key}]" if isinstance(key, int) else _field(place, key)
    return place


def _child(source: object, key: str) -> tuple[object, FieldInfo | None]:
    """Wartość pod kluczem ``key`` modelu albo słownika ``source``, z którego powstał JSON Logów, i pole modelu z tym
    kluczem (``None``: klucz słownika, czyli dane, albo JSON poza modelem Logów)."""

    if isinstance(source, BaseModel):
        return getattr(source, key, None), type(source).model_fields.get(key)
    if isinstance(source, Mapping):
        return source.get(key), None
    return None, None


def _field(place: str, key: str) -> str:
    name = key if _FIELD_NAME.fullmatch(key) else "[…]"
    return f"{place}.{name}" if place else name


_FIELD_NAME: Final = re.compile(r"[a-z_]+")
"""Nazwa pola schematu Logów; inny klucz (operator, kod pozycji, litera kolumny) to dane."""


_MINTED: Final = object()
"""Dowód, że wartość wyszła ze strażnika reguły danych: ``GuardedLogs`` i ``GuardedText`` daje tylko ``guard_logs`` i
``guard_text``.

Sprawdzenia niżej łapią kod, który zapomniał strażnika albo przerobił wartość, która go przeszła, a ich granice
pokazują próbki ``ZNANE_LUKI_STRAZNIKA`` w ``tests/test_granice_importow.py``, każda za klasą nazwaną w swojej nazwie.

- Konstruktor bez ``_MINTED`` rzuca ``TypeError``, a ``_MINTED`` zna tylko ten moduł.
- ``dataclasses.replace``: to nie są dataclassy, więc mypy odrzuca wywołanie (``type-var``), a Python rzuca ``TypeError``.
- Przypisanie i usunięcie pola albo slotu: mypy odrzuca przypisanie (właściwość tylko do odczytu), a ``__setattr__`` i
  ``__delattr__`` rzucają ``AttributeError``. Dlatego ``copy.copy``, ``copy.deepcopy`` i ``pickle.loads`` też rzucają:
  odtworzenie wartości ustawia sloty przez ``__setattr__``. ``copy.replace`` rzuca ``TypeError``, bo nie ma
  ``__replace__``. Wartość jest niezmienna, więc kopia nie jest potrzebna.
- Podklasa, także zrobiona przez ``type()``: mypy odrzuca ``class`` (``final``), a ``__init_subclass__`` rzuca
  ``TypeError``.
- Wartość innego typu, np. Logi sprzed strażnika podane przez ``Any``, ``cast(Any, …)`` albo ``# type: ignore``: typ jej
  nie widzi, więc wersje komentarza Uruchomienia (``comment_versions``) i plik Logów (``LogsOnDisk.write``), jedyne miejsca,
  które biorą Logi albo tekst po strażniku, sprawdzają ``isinstance`` i rzucają ``TypeError``.
- ``_MINTED`` i nazwa ``GuardedLogs`` albo ``GuardedText`` poza adnotacją, importem i ``isinstance`` (np.
  ``object.__new__(GuardedLogs)``, ``cast(GuardedLogs, …)``, napis ze slotem ``_GuardedLogs__…``): łapie test
  ``tests/test_granice_importow.py``.
- Pydantic tu nie ma: ``record.model_copy`` daje ``RunLog``, a nie Logi po strażniku."""


@final
class GuardedLogs:
    """Logi Uruchomienia po strażniku reguły danych tej pracy Centrum (ADR 0025), z ``guard_logs``.

    Plik Logów (``LogsOnDisk.write``) i wysyłka Logów (``comment_versions.post_of``) biorą tylko takie Logi, więc Logi,
    które ominęły strażnika (Logi Urwanego Uruchomienia przed 2ff78b6b3), to błąd typu (``_MINTED``). ``text``: znaki
    pliku Logów i pliku w Archiwum Logów okresu.
    """

    __slots__ = ("__record", "__source")
    __record: RunLog
    __source: RunLog
    """Logi, które przeszły przez strażnika: Diagnoza dopisuje się do nich, a nie do ich maski."""

    def __init__(self, record: RunLog, source: RunLog, proof: object) -> None:
        if proof is not _MINTED:
            raise TypeError("Logi po strażniku daje tylko guard_logs.")
        object.__setattr__(self, "_GuardedLogs__record", record)
        object.__setattr__(self, "_GuardedLogs__source", source)

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError("Logi po strażniku nie mają podklas: daje je tylko guard_logs.")

    @property
    def record(self) -> RunLog:
        return self.__record

    @property
    def text(self) -> LogsText:
        return logs_text(self.__record.text)

    def with_diagnosis(self, diagnosis: LoggedDiagnosis, forbidden: ForbiddenValues) -> GuardedLogs | None:
        """Te Logi z Diagnozą ``diagnosis``, przepuszczone przez strażnika drugi raz razem z nią, jak Logi z wynikiem;
        ``None``: Logi mają już Diagnozę z tym samym wynikiem (``LoggedDiagnosis.same_result``)."""

        last = self.__source.diagnosis
        if last is not None and diagnosis.same_result(last):
            return None
        return guard_logs(self.__source.model_copy(update={"diagnosis": diagnosis}), forbidden)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("Logi po strażniku są niezmienne: nowe daje guard_logs.")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("Logi po strażniku są niezmienne: nowe daje guard_logs.")


def guard_logs(record: RunLog, forbidden: ForbiddenValues) -> GuardedLogs:
    """Logi ``record`` po strażniku reguły danych ``forbidden`` (``_guarded``) z dowodem strażnika; narzędzia, które nie
    piszą pliku ani nie wysyłają, biorą z nich ``record``."""

    return GuardedLogs(_guarded(record, forbidden), record, _MINTED)


@final
class GuardedText:
    """Tekst komentarza bez pliku Logów (postęp, wynik bez Logów) po strażniku reguły danych, z ``guard_text``
    (``_MINTED``)."""

    __slots__ = ("__text",)
    __text: str

    def __init__(self, text: str, proof: object) -> None:
        if proof is not _MINTED:
            raise TypeError("Tekst po strażniku daje tylko guard_text.")
        object.__setattr__(self, "_GuardedText__text", text)

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError("Tekst po strażniku nie ma podklas: daje go tylko guard_text.")

    @property
    def text(self) -> str:
        return self.__text

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("Tekst po strażniku jest niezmienny: nowy daje guard_text.")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("Tekst po strażniku jest niezmienny: nowy daje guard_text.")


def guard_text(text: str, place: str, forbidden: ForbiddenValues) -> GuardedText:
    """Tekst ``text`` po strażniku reguły danych ``forbidden``: zamaskowana wartość to uwaga techniczna na jego końcu, z
    miejscem ``place``."""

    found = guarded(forbidden, text, place)
    return GuardedText(found.text + "".join(f"\n- Uwaga techniczna: {note}" for note in found.notes), _MINTED)
