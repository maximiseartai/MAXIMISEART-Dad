from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import re
from typing import Final, final

from pydantic import BaseModel, ValidationError
from pydantic.fields import FieldInfo

from rozliczenia.centrum.run_logs import LoggedDiagnosis, RunLog
from rozliczenia.settlement_period import PERIOD_TOKEN_PATTERN, UNKNOWN_PERIOD
from rozliczenia.client_data import READ_VALUES, ForbiddenValues, Guarded, LogsText, WithoutSubclasses, guarded, guarded_number, logs_text


def _guarded(record: RunLog, forbidden: ForbiddenValues) -> RunLog:
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
                if _field(place, key) in TOOL_FIELDS:
                    items[key] = _kept(child, entry, f"{type(source).__name__}.{key}", _field(place, key), text)
                    continue
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

TOOL_TEXT_GRAMMAR: Final = {
    "RunLog.run_id": re.compile(r"[0-9a-f]{32}", re.ASCII),
    "RunLog.period": re.compile(rf"{PERIOD_TOKEN_PATTERN}|{UNKNOWN_PERIOD}", re.ASCII),
    "Tool.wydanie": re.compile(r"\d+\.\d+\.\d+", re.ASCII),
    "Tool.commit": re.compile(r"[0-9a-f]{7,40}", re.ASCII),
    "CallTrace.exception_type": re.compile(r"[A-Za-z_][\w.]*", re.ASCII),
    "CallCause.exception_type": re.compile(r"[A-Za-z_][\w.]*", re.ASCII),
    "CallFrame.file": re.compile(r"[\w.\-]+(?:/[\w.\-]+)*\.py", re.ASCII),
    "CallFrame.function": re.compile(r"[A-Za-z_]\w*|<\w+>", re.ASCII),
    "Environment.system": re.compile(r"[\w.\-]+", re.ASCII),
    "Environment.python": re.compile(r"\d+\.\d+\.\d+\w*", re.ASCII),
}

_OUTSIDE_TOOL: Final = "[poza-narzędziem]"


def _kept(source: object, value: object, owner: str, place: str, text: Callable[[str, str], str]) -> object:
    if isinstance(value, str):
        grammar = TOOL_TEXT_GRAMMAR.get(owner)
        return value if grammar is None or grammar.fullmatch(value) else text(value, place)
    if isinstance(value, list):
        sources = list(source) if isinstance(source, (list, tuple)) else [None] * len(value)
        return [_kept(item, entry, owner, f"{place}[{index}]", text) for index, (item, entry) in enumerate(zip(sources, value, strict=True))]
    if isinstance(value, dict):
        return {key: _kept(getattr(source, key, None), entry, f"{type(source).__name__}.{key}", _field(place, key), text) for key, entry in value.items()}
    return value


def tool_text(owner: str, value: str) -> str:
    return value if TOOL_TEXT_GRAMMAR[owner].fullmatch(value) else _OUTSIDE_TOOL


_Path = tuple[str | int, ...]


class UnrepresentableLogs(ValueError):
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
    place: str
    removed: bool

    @property
    def field(self) -> str:
        return _field_of(self.place)

    @property
    def note(self) -> str:
        what = f"pominięto {self.place}" if self.removed else f"pole {self.place} jest puste"
        return f"Reguła danych: {what}: strażnik zamaskował w nim wartość, której pole nie przyjmuje."


def guard_cuts(record: RunLog) -> tuple[GuardCut, ...]:
    found = (_CUT_NOTE.fullmatch(note) for note in (*record.technical_notes, *record.input_copy_notes))
    return tuple(
        GuardCut(match["removed"] or match["emptied"], match["removed"] is not None) for match in found if match
    )


_CUT_NOTE: Final = re.compile(
    r"Reguła danych: (?:pominięto (?P<removed>\S+)|pole (?P<emptied>\S+) jest puste): strażnik zamaskował w nim "
    r"wartość, której pole nie przyjmuje\."
)


def _field_of(place: str) -> str:
    return re.split(r"[.\[]", place)[0]


def _representable(walked: dict[str, object]) -> RunLog:
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
        notes: dict[bool, list[str]] = {True: [], False: []}
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
    if isinstance(value, dict):
        return 1 + sum(_values(entry) for entry in value.values())
    if isinstance(value, list):
        return 1 + sum(_values(entry) for entry in value)
    return 0 if value is None else 1


def _existing(walked: object, location: Sequence[str | int]) -> _Path:
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
    if isinstance(source, BaseModel):
        return getattr(source, key, None), type(source).model_fields.get(key)
    if isinstance(source, Mapping):
        return source.get(key), None
    return None, None


def _field(place: str, key: str) -> str:
    name = key if _FIELD_NAME.fullmatch(key) else "[…]"
    return f"{place}.{name}" if place else name


_FIELD_NAME: Final = re.compile(r"[a-z_]+")


_MINTED: Final = object()


_NO_LOGS_SUBCLASSES: Final = "Logi po strażniku nie mają podklas: daje je tylko guard_logs."
_NO_TEXT_SUBCLASSES: Final = "Tekst po strażniku nie ma podklas: daje go tylko guard_text."


@final
class GuardedLogs(metaclass=WithoutSubclasses, refusal=_NO_LOGS_SUBCLASSES):
    __slots__ = ("__record", "__source")
    __record: RunLog
    __source: RunLog

    def __init__(self, record: RunLog, source: RunLog, proof: object) -> None:
        if proof is not _MINTED:
            raise TypeError("Logi po strażniku daje tylko guard_logs.")
        object.__setattr__(self, "_GuardedLogs__record", record)
        object.__setattr__(self, "_GuardedLogs__source", source)

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError(_NO_LOGS_SUBCLASSES)

    @property
    def record(self) -> RunLog:
        return self.__record

    @property
    def text(self) -> LogsText:
        return logs_text(self.__record.text)

    def with_diagnosis(self, diagnosis: LoggedDiagnosis, forbidden: ForbiddenValues) -> GuardedLogs | None:
        last = self.__source.diagnosis
        if last is not None and diagnosis.same_result(last):
            return None
        return guard_logs(self.__source.model_copy(update={"diagnosis": diagnosis}), forbidden)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("Logi po strażniku są niezmienne: nowe daje guard_logs.")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("Logi po strażniku są niezmienne: nowe daje guard_logs.")


def guard_logs(record: RunLog, forbidden: ForbiddenValues) -> GuardedLogs:
    return GuardedLogs(_guarded(record, forbidden), record, _MINTED)


def exact_logs(logs: object) -> GuardedLogs:
    if type(logs) is not GuardedLogs:
        raise TypeError(f"Logi po strażniku daje tylko guard_logs, nie {type(logs).__name__}.")
    return logs


@final
class GuardedText(metaclass=WithoutSubclasses, refusal=_NO_TEXT_SUBCLASSES):
    __slots__ = ("__text",)
    __text: str

    def __init__(self, text: str, proof: object) -> None:
        if proof is not _MINTED:
            raise TypeError("Tekst po strażniku daje tylko guard_text.")
        object.__setattr__(self, "_GuardedText__text", text)

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError(_NO_TEXT_SUBCLASSES)

    @property
    def text(self) -> str:
        return self.__text

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("Tekst po strażniku jest niezmienny: nowy daje guard_text.")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("Tekst po strażniku jest niezmienny: nowy daje guard_text.")


def exact_text(text: object) -> GuardedText:
    if type(text) is not GuardedText:
        raise TypeError(f"Tekst po strażniku daje tylko guard_text, nie {type(text).__name__}.")
    return text


def guard_text(text: str, place: str, forbidden: ForbiddenValues) -> GuardedText:
    found = guarded(forbidden, text, place)
    return GuardedText(found.text + "".join(f"\n- Uwaga techniczna: {note}" for note in found.notes), _MINTED)
