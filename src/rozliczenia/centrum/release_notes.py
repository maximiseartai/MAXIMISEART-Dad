from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re
from typing import Final

from rozliczenia.centrum.dad_cases import KINDS

CASE_KINDS: Final[Mapping[str, str]] = {kind.label: kind.name for kind in KINDS}
CASES_HEADING: Final = "## Rozwiązane sprawy taty"
_CASES_HEADING_LINE: Final = re.compile(rf"^#+[ \t]+{re.escape(CASES_HEADING.lstrip('# '))}[ \t]*$", re.MULTILINE)
_CASE_LINE: Final = re.compile(r"- (?P<kind>.+?) #(?P<number>[1-9][0-9]*): (?P<title>.+)")
_POINT_LINE: Final = re.compile(r"[-*][ \t]+(?P<text>.+)")


@dataclass(frozen=True)
class DadCase:
    number: int
    title: str
    label: str


@dataclass(frozen=True)
class ReleaseNotes:
    summary: str
    cases: tuple[DadCase, ...]


@dataclass(frozen=True)
class WhatsNew:
    intro: str
    points: tuple[str, ...]


def whats_new(summary: str) -> WhatsNew:
    lines = summary.strip().splitlines()
    first = next((index for index, line in enumerate(lines) if _POINT_LINE.fullmatch(line.strip())), None)
    if first is None:
        return WhatsNew(summary.strip(), ())
    points: list[str] = []
    after_blank = False
    for line in map(str.strip, lines[first:]):
        if (point := _POINT_LINE.fullmatch(line)) is not None:
            points.append(point["text"].strip())
        elif after_blank:
            return WhatsNew(summary.strip(), ())
        elif line:
            points[-1] = f"{points[-1]} {line}"
        after_blank = not line
    return WhatsNew("\n".join(lines[:first]).strip(), tuple(points))


def render(notes: ReleaseNotes) -> str:
    summary = notes.summary.strip()
    if not summary:
        raise ValueError("notka nie ma „Co nowego”")
    if _CASES_HEADING_LINE.search(summary):
        raise ValueError(f"„Co nowego” nie może zawierać nagłówka {CASES_HEADING!r}")
    if not notes.cases:
        return summary + "\n"
    lines = [f"- {CASE_KINDS[case.label]} #{case.number}: {' '.join(case.title.split())}" for case in notes.cases]
    return "\n".join([summary, "", CASES_HEADING, "", *lines]) + "\n"


def parse(text: str) -> ReleaseNotes:
    summary, *listed = _CASES_HEADING_LINE.split(text.replace("\r\n", "\n"), maxsplit=1)
    labels = {kind: label for label, kind in CASE_KINDS.items()}
    cases = tuple(
        DadCase(int(found["number"]), found["title"].strip(), labels[found["kind"]])
        for line in "".join(listed).splitlines()
        if (found := _CASE_LINE.fullmatch(line.strip())) is not None and found["kind"] in labels
    )
    return ReleaseNotes(summary.strip(), cases)
