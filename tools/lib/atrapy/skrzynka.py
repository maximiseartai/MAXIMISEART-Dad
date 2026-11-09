"""Stan Skrzynki Zgłoszeń atrap z regułami GitHuba: issue z komentarzami i Archiwa okresów (GitHub Releases) z plikami.

Każda atrapa ``ReportBox`` poza eksploratorem kolejki pyta ten model o skutek kroku: ``FakeReportBox`` testów trzyma go
w pamięci, a ``FileReportBox`` weryfikacji Centrum (``serve_centrum.py``) w plikach, które czyta i zmienia napęd. Reguła
GitHuba ma więc jedno miejsce w atrapach:

- issue dostaje kolejny numer od ``first_number``;
- komentarz, lista komentarzy i poprawka komentarza issue albo komentarza, którego nie ma, to ``Refused`` (404 GitHuba,
  ADR 0007);
- lista issue z etykietą pokazuje tylko issue tej etykiety, zamknięte tylko na prośbę;
- drugie Archiwum jednego tagu i drugi plik jednej nazwy w Archiwum to ``Rejected`` (422) i niczego nie zmieniają, a
  krok na Archiwum albo pliku, którego nie ma, to ``Refused``;
- plik dostaje identyfikator, którego nie miał żaden plik, także usunięty, bo ``KeyedBox`` odróżnia po nim usunięty plik
  od jego nowej wersji;
- z ``lag`` lista issue i lista Archiwów nie widzą nowego issue ani Archiwum, dopóki atrapa nie powie, że nadążyły
  (``caught_up``), jak listy GitHuba, które nadążają po kilku sekundach (#879, #887).

Identyfikator komentarza jest częścią adresu, który każda atrapa buduje po swojemu: bez ``comment_base`` kolejny
w całej skrzynce, jak na GitHubie, a z nim ``numer issue * comment_base + miejsce komentarza``. Wierność tych reguł
GitHubowi sprawdza ``verify-github-skrzynki`` na atrapach HTTP.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import gzip

from rozliczenia.centrum.report_box import (
    Archive,
    Asset,
    Closure,
    Issue,
    Label,
    Refused,
    Rejected,
    Removed,
)

from atrapy.widok_skrzynki import shown


@dataclass
class BoxIssue:
    """Issue Skrzynki: etykieta, tytuł, treść i komentarze tak, jak je zapisało Centrum (``text``, ``comment_texts``
    z identyfikatorami ``comment_ids``), ``body`` i ``comments`` tak, jak Maks je widzi (``shown``), i zamknięcie przez
    Maksa (``closure``)."""

    number: int
    label: Label
    title: str
    text: str
    comment_texts: list[str] = field(default_factory=list)
    comment_ids: list[int] = field(default_factory=list)
    closure: Closure | None = None

    @property
    def body(self) -> str:
        return shown(self.text)

    @property
    def comments(self) -> list[str]:
        return [shown(text) for text in self.comment_texts]

    def position(self, comment_id: int) -> int:
        """Miejsce komentarza ``comment_id`` w issue, od 1."""

        return self.comment_ids.index(comment_id) + 1


@dataclass
class Issues:
    """Issue Skrzynki z regułami GitHuba (opis modułu)."""

    issues: list[BoxIssue] = field(default_factory=list)
    first_number: int = 1
    comment_base: int | None = None
    lag: bool = False
    unlisted: set[int] = field(default_factory=set)

    def open(self, label: Label, title: str, text: str, number: int | None = None) -> BoxIssue:
        """Nowe issue z kolejnym numerem albo z numerem ``number``, który dała odpowiedź GitHuba."""

        opened = BoxIssue(self.first_number + len(self.issues) if number is None else number, label, title, text)
        self.issues.append(opened)
        if self.lag:
            self.unlisted.add(opened.number)
        return opened

    def find(self, number: int) -> BoxIssue | None:
        return next((issue for issue in self.issues if issue.number == number), None)

    def comment(self, number: int, text: str) -> tuple[BoxIssue, int] | Refused:
        """Nowy komentarz issue ``number``: issue i identyfikator komentarza."""

        issue = self.find(number)
        if issue is None:
            return Refused()
        position = len(issue.comment_texts) + 1
        if self.comment_base is None:
            comment_id = sum(len(each.comment_texts) for each in self.issues) + 1
        else:
            comment_id = number * self.comment_base + position
        issue.comment_texts.append(text)
        issue.comment_ids.append(comment_id)
        return issue, comment_id

    def comments(self, number: int) -> BoxIssue | Refused:
        issue = self.find(number)
        return Refused() if issue is None else issue

    def edit_comment(self, comment_id: int, text: str) -> BoxIssue | Refused:
        """Nowy tekst komentarza ``comment_id``: issue, w którym stoi."""

        for issue in self.issues:
            if comment_id in issue.comment_ids:
                issue.comment_texts[issue.comment_ids.index(comment_id)] = text
                return issue
        return Refused()

    def listed(self, label: Label, *, include_closed: bool) -> tuple[Issue, ...]:
        return tuple(
            Issue(issue.number, issue.text, issue.closure)
            for issue in self.issues
            if issue.label == label
            and (include_closed or issue.closure is None)
            and issue.number not in self.unlisted
        )

    def caught_up(self) -> None:
        """Lista issue nadąża: widzi każde założone issue."""

        self.unlisted.clear()


@dataclass
class ArchivedFile:
    """Plik w Archiwum okresu: identyfikator, nazwa, etykieta i bajty, jak je wysłało Centrum (gzip)."""

    id: int
    name: str
    label: str
    data: bytes

    @property
    def unpacked(self) -> bytes:
        """Plik rozpakowany gzipem, bajt w bajt, jak go dostaje Maks po ``gh release download`` i ``gunzip``."""

        return gzip.decompress(self.data)

    @property
    def text(self) -> str:
        """Plik rozpakowany (``unpacked``) jako tekst UTF-8."""

        return self.unpacked.decode("utf-8")


@dataclass
class BoxArchive:
    """Archiwum okresu (GitHub Release): identyfikator, tag, tytuł, opis i pliki po kolei."""

    id: int
    tag: str
    title: str
    description: str
    assets: list[ArchivedFile] = field(default_factory=list)


@dataclass
class Archives:
    """Archiwa okresów Skrzynki z regułami GitHuba (opis modułu); ``last_file_id`` to identyfikator ostatniego pliku."""

    archives: list[BoxArchive] = field(default_factory=list)
    last_file_id: int = 0
    lag: bool = False
    unlisted: set[int] = field(default_factory=set)

    def archive(self, tag: str) -> Archive | None:
        found = next((each for each in self.archives if each.tag == tag and each.id not in self.unlisted), None)
        if found is None:
            return None
        return Archive(found.id, tuple(Asset(asset.id, asset.name, asset.label, True) for asset in found.assets))

    def open_archive(self, tag: str, title: str, description: str) -> Archive | Rejected:
        if any(each.tag == tag for each in self.archives):
            return Rejected()
        opened = BoxArchive(len(self.archives) + 1, tag, title, description)
        self.archives.append(opened)
        if self.lag:
            self.unlisted.add(opened.id)
        return Archive(opened.id, ())

    def upload(self, archive_id: int, name: str, label: str, data: bytes) -> Asset | Refused | Rejected:
        found = next((each for each in self.archives if each.id == archive_id), None)
        if found is None:
            return Refused()
        if any(asset.name == name for asset in found.assets):
            return Rejected()
        self.last_file_id += 1
        found.assets.append(ArchivedFile(self.last_file_id, name, label, data))
        return Asset(self.last_file_id, name, label, True)

    def file(self, file_id: int) -> tuple[BoxArchive, ArchivedFile] | None:
        """Archiwum i plik o identyfikatorze ``file_id``."""

        return next(
            ((each, asset) for each in self.archives for asset in each.assets if asset.id == file_id),
            None,
        )

    def remove(self, file_id: int) -> Removed | Refused:
        found = self.file(file_id)
        if found is None:
            return Refused()
        archive, asset = found
        archive.assets.remove(asset)
        return Removed()

    def caught_up(self) -> None:
        """Lista Archiwów nadąża: widzi każde założone Archiwum."""

        self.unlisted.clear()
