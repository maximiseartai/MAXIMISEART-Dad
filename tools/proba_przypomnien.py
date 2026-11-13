"""Liczy Przypomnienia o raporcie, które poszłyby teraz ze skrzynki taty, i wysyła jedno tylko na podany adres; uruchom przed Wydaniem.

Narzędzie dla Maksa, poza CI (spec #1344, US 57–58, ADR 0030). Pracę Przypomnień o raporcie CI sprawdza tylko na
``AtrapaImap`` i ``AtrapaSmtp``, więc prawdziwy Gmail, INTERMAX taty, treść i stopkę sprawdza ta próba. Czyta to samo
i tą samą drogą co praca przypomnień Centrum (``rozliczenia.centrum.report_reminders.due_reminders``): z folderu
``--config`` dzień wdrożenia przypomnień (``przypomnienia-od.txt``), Ustawienia taty (``centrum-ustawienia.yaml``:
INTERMAX i folder okresów), plik dostępu do skrzynki raportów (``skrzynka-raportow.txt``), Konfigurację wykonawców,
plik adresów Wykonawców i stopkę taty (``stopka-przypomnien.txt``), potem Pliki zbiorcze okresów, INTERMAX tylko do
odczytu (także otwarty w Excelu), skrzynkę i jej „Wysłane” tylko do odczytu, i pyta rdzeń raportów, które
przypomnienia należą się w tej chwili.

Potem wysyła przez SMTP Gmaila **jedno** przypomnienie, a jedynym adresatem jest adres z ``--do`` (adres Maksa):
pierwsze należne przypomnienie (najstarszy dzień) z adresatami zamienionymi na ten adres, a gdy nic się nie należy
(np. w nocy albo od 17:00 do 18:00), przypomnienie za wczoraj. Temat, treść ze wzorem Raportu wykonawcy i stopkę ma takie, jakie dostałby
Wykonawca. Na adres z listy adresów Wykonawców narzędzie nie wysyła nigdy: taki adres w ``--do`` to odmowa bez
wysyłki. Odmowa porównuje cały adres bez względu na wielkość liter, więc inny adres tej samej skrzynki
Wykonawcy (w Gmailu z ``+…`` albo z kropkami w części przed ``@``) przechodzi i mail do niego dojdzie: ``--do`` to
zawsze własny adres Maksa. Bez pliku stopki narzędzie też nie wysyła, bo przypomnienie Wykonawcy poszłoby bez stopki.

Wynik (stdout) to jedna linia z samymi liczbami, bez adresów, loginów, nazw Wykonawców i numerów zleceń, i same znaki
ASCII (polskie słowa bez polskich liter, jak próba IMAP ``tools/proba_skrzynki_raportow.py``):

    PROBA PRZYPOMNIEN OK | pora=<p> | przypomnienia=<n> | wykonawcy=<n> | dni=<n> | wyslano 1 na podany adres

``pora`` to ``poranna`` (8:00–17:00), ``wieczorna`` (18:00–22:00) albo ``brak`` (17:00–18:00 i noc 22:00–8:00: wtedy
przypomnienia nie idą i liczby to zera), ``przypomnienia`` to liczba przypomnień, które praca Centrum wysłałaby teraz, ``wykonawcy`` liczba ich
Wykonawców, a ``dni`` liczba dni, za które są. Porażka to ``PROBA PRZYPOMNIEN FAIL | <powód>`` (kod 1), każda z
własnym powodem: brak pliku dnia wdrożenia, Ustawień taty, pliku dostępu albo adresów, nieczytelny folder okresów albo
INTERMAX (nazwa typu błędu), odrzucone hasło aplikacji albo niedostępna skrzynka przy odczycie skrzynki. Porażka po
policzeniu przypomnień ma przed powodem te same liczby: brak stopki, adres Wykonawcy w ``--do``, odrzucone hasło
aplikacji, sieć (nazwa typu błędu) albo inna odmowa Gmaila przy wysyłce. Hasła nie ma w wyniku ani wyjątkach: zna je
tylko port skrzynki.

Uruchomienie w klonie narzędzia z plikami w ``config/`` (Windows: ``py -3``); mail sprawdza Maks w swojej skrzynce:

    .venv/bin/python tools/proba_przypomnien.py --do <adres Maksa> [--config <folder config>]
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime, timedelta
import imaplib
from pathlib import Path
import smtplib
import sys
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rozliczenia import tool_files
from rozliczenia.centrum.configuration import ConfigurationFiles
from rozliczenia.centrum.report_reminders import DueReminders, NotRead, due_reminders
from rozliczenia.centrum.settings.owner import read_snapshot
from rozliczenia.dad_files import DadFiles
from rozliczenia.worker_report_inbox import (
    INBOX_ACCESS_FILE,
    ImapInbox,
    InboxUnreachable,
    MailRefused,
    MailSent,
    PasswordRejected,
)
from rozliczenia.worker_reports import (
    Login,
    Reminder,
    SenderAddress,
    reminder_pora,
    reminder_subject,
    reminder_text,
)

OK: Final = "PROBA PRZYPOMNIEN OK"
FAIL: Final = "PROBA PRZYPOMNIEN FAIL"
_NOT_SENT: Final = "mail nie poszedl"


def probe(now: datetime, config: Path, inbox: ImapInbox, target: SenderAddress) -> str:
    """Jedna linia wyniku próby; wysyła najwyżej jeden mail, tylko do ``target``."""

    settings = read_snapshot(config).folders
    read = due_reminders(now, settings, config, ConfigurationFiles.in_folder(config), inbox, DadFiles())
    match read:
        case NotRead():
            return f"{FAIL} | {_not_read(read)}"
        case PasswordRejected() | InboxUnreachable():
            return f"{FAIL} | {_unreachable(read, 'odczycie skrzynki')}"
        case DueReminders():
            pass
    pora = reminder_pora(now)
    counts = (
        f"pora={'brak' if pora is None else pora.value} | przypomnienia={len(read.due)}"
        f" | wykonawcy={len({reminder.worker for reminder in read.due})} | dni={len({reminder.day for reminder in read.due})}"
    )
    if target in read.addresses.logins:
        return f"{FAIL} | {counts} | podany adres jest na liscie adresow Wykonawcow, {_NOT_SENT}"
    if read.footer is None:
        return f"{FAIL} | {counts} | brak stopki config/{tool_files.REMINDERS_FOOTER}, {_NOT_SENT}"
    sent = inbox.send(_sample(read, now, target), now)
    match sent:
        case MailSent():
            return f"{OK} | {counts} | wyslano 1 na podany adres"
        case MailRefused(cause=cause):
            return f"{FAIL} | {counts} | Gmail odmowil wysylki: {cause}"
        case PasswordRejected() | InboxUnreachable():
            return f"{FAIL} | {counts} | {_unreachable(sent, 'wysylce')}"


def _sample(read: DueReminders, now: datetime, target: SenderAddress) -> Reminder:
    """Pierwsze należne przypomnienie z jedynym adresatem ``target``, a bez należnych przypomnienie za wczoraj."""

    if read.due:
        return replace(read.due[0], recipients=(target,))
    yesterday = now.date() - timedelta(days=1)
    return Reminder(Login("proba"), (target,), yesterday, reminder_subject(yesterday), reminder_text(yesterday, read.footer))


def _not_read(read: NotRead) -> str:
    match read.cause:
        case "bez-wdrozenia":
            return f"brak dnia wdrozenia przypomnien w config/{tool_files.REMINDERS_ROLLOUT}"
        case "bez-ustawien":
            return "brak INTERMAX albo folderu okresow w Ustawieniach taty"
        case "bez-dostepu":
            return f"brak albo zly plik dostepu config/{INBOX_ACCESS_FILE}"
        case "bez-adresow":
            return "brak albo zly plik adresow Wykonawcow albo Konfiguracja wykonawcow"
        case "okresy":
            return "nieczytelny folder okresow"
        case "intermax":
            return f"nieczytelny INTERMAX: {read.failure}"


def _unreachable(found: PasswordRejected | InboxUnreachable, when: str) -> str:
    match found:
        case PasswordRejected():
            return f"Gmail odrzucil haslo aplikacji przy {when}"
        case InboxUnreachable(cause):
            return f"skrzynka niedostepna przy {when}: {cause}"


def main(
    argv: Sequence[str] | None = None,
    *,
    connect: Callable[[], imaplib.IMAP4] | None = None,
    smtp: Callable[[], smtplib.SMTP] | None = None,
    now: Callable[[], datetime] = lambda: datetime.now().astimezone(),
) -> int:
    """``connect`` i ``smtp`` podaje test, żeby port rozmawiał z ``AtrapaImap`` i ``AtrapaSmtp``, a ``now`` daje chwilę
    ze strefą; bez nich port łączy się z Gmailem w chwili uruchomienia."""

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--do",
        required=True,
        help=(
            "Jedyny adres, na który idzie przypomnienie próby (własny adres Maksa); adres z listy adresów Wykonawców "
            "narzędzie odmawia, ale innego adresu tej samej skrzynki (w Gmailu z +… albo z kropkami) nie rozpozna."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=tool_files.CONFIG_DIR,
        help="Folder config z plikami przypomnień i Ustawieniami taty (domyślnie config klonu narzędzia, jak w Centrum).",
    )
    args = parser.parse_args(argv)
    target = SenderAddress.of(args.do)
    if target is None:
        parser.error("--do to jeden adres lokalna@domena")
    inbox = (
        ImapInbox(args.config)
        if connect is None or smtp is None
        else ImapInbox(args.config, connect=connect, smtp=smtp)
    )
    line = probe(now(), args.config, inbox, target)
    print(line)
    return 0 if line.startswith(OK) else 1


if __name__ == "__main__":
    sys.exit(main())
