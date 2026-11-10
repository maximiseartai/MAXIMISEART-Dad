"""Sprawdza port IMAP na prawdziwej skrzynce raportów taty tylko do odczytu, wynik jedną linią; uruchom przed Wydaniem z Wpisaniem raportów.

Narzędzie dla Maksa, poza CI (Granica 4 speca #1224, ADR 0028). Port IMAP Skrzynki raportów
(``rozliczenia.worker_report_inbox.ImapInbox``) CI sprawdza tylko na ``AtrapaImap``, więc prawdziwego Gmaila sprawdza
ta próba: tym samym portem, z tym samym plikiem dostępu ``config/skrzynka-raportow.txt`` (linia 1 adres skrzynki,
linia 2 hasło aplikacji Google) i plikiem adresów Wykonawców ``config/adresy-wykonawcow.yaml``, co Wpisanie raportów.
Po kolei:

1. czyta plik adresów z Konfiguracją wykonawców (``config/worker_mapping.yaml``), jak Wpisanie raportów;
2. czyta flagi IMAP każdego maila z dni od dnia przed ``--od`` w folderze, który czyta port (``\\All``, a bez niego
   ``INBOX``), i liczy maile ze słowem ``raport`` w temacie w tym folderze i w ``INBOX`` (``ImapInbox.survey``);
3. czyta Raporty wykonawców od ``--od`` portem (``mails_since``) i przepuszcza je przez rdzeń raportów
   (``enter_reports``) bez zleceń INTERMAX, więc każdy Wpis raportu z rozpoznanego Raportu to problem nieznanego numeru;
4. czyta flagi jeszcze raz i porównuje je z pierwszym odczytem: mail, którego flagi są inne albo którego nie ma w
   drugim odczycie, to mail ze zmienionymi flagami. Port oddaje flagi każdego wyszukanego maila albo błąd
   ``UnexpectedReply``, a próba sprawdza jeszcze, że w każdym odczycie liczba maili z flagami równa się liczbie
   wyszukanych. Port oddaje UID tylko w odczycie flag, więc mail, który przyszedł po pierwszym odczycie flag, próba
   poznaje po liczbie: przeczytanych i pominiętych maili jest więcej niż maili ze słowem ``raport`` w temacie w
   pierwszym odczycie, a flag takiego maila nikt nie porównał.

Skrzynki nie zmienia: port otwiera folder przez ``EXAMINE`` i pobiera tematy, treści i flagi przez ``BODY.PEEK`` i
``FETCH (FLAGS)``, bez ``SELECT`` i ``STORE``.

Wynik (stdout) to same liczby, bez treści maili, tematów, adresów, loginów i numerów zleceń, i same znaki ASCII (polskie
słowa bez polskich liter), bo konsola Windows przy przekierowaniu wyjścia koduje w cp1252, który nie ma ``ł`` ani ``ż``:

    SKRZYNKA | folder_wszystkich=<n> | odebrane=<n> | poza_odebranymi=<n>
    MAILE | przeczytane=<n> | pominiete=<n> | raporty=<n> | wpisy=<n> | polskie_znaki=<n> | zepsute_znaki=<n>
    PROBLEMY | <rodzaj problemu>=<n> | …      (albo PROBLEMY | brak)
    FLAGI | sprawdzone=<n> | zmienione=<n>
    PROBA IMAP OK | maile=<n> | flagi bez zmian

``SKRZYNKA`` liczy maile ze słowem ``raport`` w temacie: ``poza_odebranymi`` to ile ich więcej jest w folderze, który
czyta port, niż w ``INBOX``. ``MAILE``: ``przeczytane`` to maile, które oddał port, ``pominiete`` te, których nie umiał
rozebrać, ``raporty`` maile z tematem ``Raport dd.mm.rrrr`` z dniem od ``--od``, ``wpisy`` ich Wpisy raportu,
``polskie_znaki`` maile z polską literą w temacie albo treści, a ``zepsute_znaki`` maile ze znakiem zastępczym U+FFFD
albo literą ``Ã``, ``Ä``, ``Å``, ``Ă``, ``Ĺ``, którą daje polska litera z UTF-8 przeczytana w zestawie jednobajtowym.
``PROBLEMY`` liczy problemy rdzenia według rodzaju (nazwa typu z ``rozliczenia.worker_reports``).

Ostatnia linia to ``PROBA IMAP OK | …`` (kod 0) tylko wtedy, gdy rdzeń rozpoznał co najmniej jeden Raport wykonawcy od
adresu z pliku adresów z Wpisem raportu z ``tak`` albo ``nie``, a inaczej ``PROBA IMAP FAIL | <powód>`` (kod 1): brak
albo zła treść pliku dostępu, pliku adresów albo Konfiguracji wykonawców, odrzucone hasło, skrzynka niedostępna (nazwa
typu błędu), brak rozpoznanego Raportu wykonawcy, zepsute znaki, flagi nieodczytane dla części wyszukanych maili, mail,
który przyszedł w trakcie próby, albo flagi, które zmieniły się między odczytami. Powód ``brak rozpoznanego Raportu wykonawcy`` niesie liczby: maile ze
słowem ``raport`` w temacie (``maile_z_raport``), Raporty od adresów spoza pliku adresów (``nieznani_nadawcy``), maile,
których temat nie jest ``Raport dd.mm.rrrr`` z dniem od ``--od`` (``nierozpoznane_tematy``), Raporty od Wykonawców bez
Wpisu (``raporty_bez_wpisow``) i Wpisy bez ``tak`` ani ``nie`` (``wpisy_bez_tak_nie``). Zepsute znaki daje też
zagraniczne nazwisko z ``Å`` albo ``Ä`` w mailu ze słowem ``raport``: wtedy Maks sprawdza te maile ręcznie. Hasła nie ma
w wyniku, wyjątkach ani żadnym pliku: zna je tylko port.

Uruchomienie u taty, w klonie narzędzia z plikami w ``config/`` (Windows: ``py -3``), a ostatnią linię Maks wpisuje w
komentarzu #1234:

    .venv/bin/python tools/proba_skrzynki_raportow.py [--od RRRR-MM-DD] [--config <folder config>]
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta
import imaplib
from pathlib import Path
import re
import sys
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rozliczenia import tool_files
from rozliczenia.worker_addresses import WORKER_ADDRESSES_FILE, AddressesError
from rozliczenia.worker_addresses import load as load_addresses
from rozliczenia.worker_config import WorkerConfigError, load_worker_mapping
from rozliczenia.worker_report_inbox import (
    INBOX_ACCESS_FILE,
    ImapInbox,
    InboxSurvey,
    InboxUnreachable,
    PasswordRejected,
)
from rozliczenia.worker_reports import (
    OwnEntries,
    ReadReport,
    ReadStranger,
    ReportInputs,
    ReportMail,
    ReportsOutcome,
    Window,
    enter_reports,
)

DAYS_BACK: Final = 14
"""Domyślne ``--od``: tyle dni przed dziś, żeby w skrzynce były Raporty z kilku dni roboczych."""
OK: Final = "PROBA IMAP OK"
FAIL: Final = "PROBA IMAP FAIL"
_POLISH: Final = re.compile("[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]")
_BROKEN: Final = re.compile("[\ufffdÃÄÅĂĹ]")


class ProbeFailed(Exception):
    """Próba nie przeszła; ``reason`` to powód z ostatniej linii, bez hasła, adresu i treści maila."""

    def __init__(self, reason: str) -> None:
        self.reason = reason


def probe(inbox: ImapInbox, config: Path, since: date, today: date) -> list[str]:
    """Linie wyniku próby z ostatnią ``PROBA IMAP OK`` albo ``PROBA IMAP FAIL``; ``ProbeFailed``, gdy próba nie doszła
    do liczb."""

    match inbox.access():
        case "missing":
            raise ProbeFailed(f"brak pliku dostepu config/{INBOX_ACCESS_FILE} albo jego adresu lub hasla")
        case "unreadable":
            raise ProbeFailed(f"nieczytelny plik dostepu config/{INBOX_ACCESS_FILE}")
        case "ready":
            pass
    try:
        workers = load_worker_mapping(config / tool_files.WORKER_CONFIG.name)
    except WorkerConfigError as error:
        raise ProbeFailed(f"Konfiguracja wykonawcow: {_problem(error.reason)}") from None
    try:
        addresses = load_addresses(config / WORKER_ADDRESSES_FILE, workers=workers)
    except AddressesError as error:
        raise ProbeFailed(f"plik adresow Wykonawcow: {_problem(error.problem)}") from None

    before = _survey(inbox, since, "pierwszym odczycie flag")
    read = inbox.mails_since(since)
    if isinstance(read, (PasswordRejected, InboxUnreachable)):
        raise ProbeFailed(_unreachable(read, "odczycie maili"))
    mails = read.mails
    outcome = enter_reports(
        ReportInputs(mails, addresses, (), Window.of(today, since), OwnEntries.EMPTY, frozenset())
    )
    after = _survey(inbox, since, "drugim odczycie flag")
    changed = sum(1 for uid, flags in before.flags.items() if after.flags.get(uid) != flags)
    unread = sum(1 for survey in (before, after) if len(survey.flags) != survey.searched)
    arrived = len(mails) + read.skipped - before.in_folder

    lines = [
        f"SKRZYNKA | folder_wszystkich={before.in_folder} | odebrane={before.in_inbox}"
        f" | poza_odebranymi={before.in_folder - before.in_inbox}",
        _mail_line(mails, read.skipped, outcome),
        _problem_line(outcome),
        f"FLAGI | sprawdzone={len(before.flags)} | zmienione={changed}",
    ]
    reasons = [
        *([] if _recognised(outcome) else [_no_report(mails, outcome, since)]),
        *([f"zepsute polskie znaki w {broken} mailach"] if (broken := _count(mails, _BROKEN)) else []),
        *([f"flagi nie kazdego wyszukanego maila w {unread} z 2 odczytow"] if unread else []),
        *(
            [f"{arrived} maili przyszlo w trakcie proby bez pierwszego odczytu flag, uruchom ponownie"]
            if arrived > 0
            else []
        ),
        *([f"flagi zmienione w {changed} mailach"] if changed else []),
    ]
    last = f"{FAIL} | {'; '.join(reasons)}" if reasons else f"{OK} | maile={len(mails)} | flagi bez zmian"
    return [*lines, last]


def _recognised(outcome: ReportsOutcome) -> bool:
    """Rdzeń rozpoznał Raport wykonawcy od adresu z pliku adresów z Wpisem raportu, który ma ``tak`` albo ``nie``."""

    return any(entry.verdict is not None for report in _reports(outcome) for entry in report.entries)


def _no_report(mails: Sequence[ReportMail], outcome: ReportsOutcome, since: date) -> str:
    strangers = len(_strangers(outcome))
    reports = _reports(outcome)
    return (
        f"brak rozpoznanego Raportu wykonawcy od {since.isoformat()} (maile_z_raport={len(mails)}"
        f", nieznani_nadawcy={strangers}, nierozpoznane_tematy={len(mails) - len(reports) - strangers}"
        f", raporty_bez_wpisow={sum(1 for report in reports if not report.entries)}"
        f", wpisy_bez_tak_nie={sum(1 for report in reports for entry in report.entries if entry.verdict is None)})"
    )


def _reports(outcome: ReportsOutcome) -> list[ReadReport]:
    return [read for read in outcome.mails if isinstance(read, ReadReport)]


def _strangers(outcome: ReportsOutcome) -> list[ReadStranger]:
    return [read for read in outcome.mails if isinstance(read, ReadStranger)]


def _survey(inbox: ImapInbox, since: date, when: str) -> InboxSurvey:
    found = inbox.survey(since)
    if isinstance(found, (PasswordRejected, InboxUnreachable)):
        raise ProbeFailed(_unreachable(found, when))
    return found


def _unreachable(found: PasswordRejected | InboxUnreachable, when: str) -> str:
    match found:
        case PasswordRejected():
            return f"Gmail odrzucil haslo aplikacji przy {when}"
        case InboxUnreachable(cause):
            return f"skrzynka niedostepna przy {when}: {cause}"


def _problem(problem: object) -> str:
    """Rodzaj problemu pliku: sam napis albo nazwa typu, bez pól, w których bywa login."""

    return problem if isinstance(problem, str) else type(problem).__name__


def _count(mails: Sequence[ReportMail], pattern: re.Pattern[str]) -> int:
    return sum(1 for mail in mails if pattern.search(mail.subject) or pattern.search(mail.text))


def _mail_line(mails: Sequence[ReportMail], skipped: int, outcome: ReportsOutcome) -> str:
    return (
        f"MAILE | przeczytane={len(mails)} | pominiete={skipped} | raporty={len(_reports(outcome)) + len(_strangers(outcome))}"
        f" | wpisy={sum(len(report.entries) for report in _reports(outcome))}"
        f" | polskie_znaki={_count(mails, _POLISH)} | zepsute_znaki={_count(mails, _BROKEN)}"
    )


def _problem_line(outcome: ReportsOutcome) -> str:
    kinds = Counter(type(problem).__name__ for problem in outcome.problems)
    return "PROBLEMY | " + (" | ".join(f"{kind}={kinds[kind]}" for kind in sorted(kinds)) or "brak")


def main(argv: Sequence[str] | None = None, *, connect: Callable[[], imaplib.IMAP4] | None = None) -> int:
    """``connect`` podaje test, żeby port rozmawiał z ``AtrapaImap``; bez niego port łączy się z Gmailem."""

    today = datetime.now().astimezone().date()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--od",
        type=date.fromisoformat,
        default=today - timedelta(days=DAYS_BACK),
        help=f"Pierwszy dzień Raportów, RRRR-MM-DD (domyślnie {DAYS_BACK} dni przed dziś).",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=tool_files.CONFIG_DIR,
        help="Folder config z plikiem dostępu i plikiem adresów (domyślnie config klonu narzędzia, jak w Centrum).",
    )
    args = parser.parse_args(argv)
    inbox = ImapInbox(args.config) if connect is None else ImapInbox(args.config, connect=connect)
    try:
        lines = probe(inbox, args.config, args.od, today)
    except ProbeFailed as error:
        lines = [f"{FAIL} | {error.reason}"]
    print("\n".join(lines))
    return 0 if lines[-1].startswith(OK) else 1


if __name__ == "__main__":
    sys.exit(main())
