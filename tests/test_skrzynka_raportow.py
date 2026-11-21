from __future__ import annotations

import base64
import codecs
import copy
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta, timezone
import email
from email.message import EmailMessage, Message
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage
from email.mime.message import MIMEMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import email.policy
from email.utils import format_datetime
import hashlib
import imaplib
import smtplib
from pathlib import Path
import quopri
import re
from typing import Any, Literal

from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st
import pydantic
import pytest

from rozliczenia.centrum.settings.owner import read_snapshot
from rozliczenia.worker_report_inbox import (
    CENTRUM_MARK,
    AttachmentMail,
    FETCH_BATCH,
    INBOX_ACCESS_FILE,
    ImapInbox,
    InboxState,
    InboxOutcome,
    InboxSurvey,
    InboxUnreachable,
    MailRefused,
    Mails,
    MailSent,
    PasswordRejected,
    SentAttachment,
    SentAttachments,
    SentReminders,
    mail_of,
)
from rozliczenia.worker_reports import Login, MailId, Reminder, ReportMail, SenderAddress, SentReminder

from atrapy.skrzynka_raportow import AtrapaImap, AtrapaMail, AtrapaSmtp, FolderInbox

SKRZYNKA = "raporty.taty@przyklad.invalid"
HASLO = "abcdefghijklmnop"
WYKONAWCA = "jan.testowy@przyklad.invalid"
TATA = timezone(timedelta(hours=1))
WRITES = {"SELECT", "STORE", "COPY", "MOVE", "EXPUNGE", "APPEND"}


def surowy(
    *,
    temat: bytes = b"Raport 08.11.2026",
    tresc: str = "40000001 tak wymiana routera",
    od: bytes | None = b"Jan Testowy <jan.testowy@przyklad.invalid>",
    typ: str = "text/plain",
    charset: str = "utf-8",
    kodowanie: str = "quoted-printable",
    message_id: bytes = b"<1@przyklad.invalid>",
) -> bytes:
    encoded = tresc.encode(charset if charset != "x-nieznany" else "utf-8")
    body = quopri.encodestring(encoded) if kodowanie == "quoted-printable" else base64.encodebytes(encoded)
    headers = [
        *([b"From: " + od] if od is not None else []),
        b"To: " + SKRZYNKA.encode(),
        b"Subject: " + temat,
        b"Message-ID: " + message_id,
        b"MIME-Version: 1.0",
        f"Content-Type: {typ}; charset={charset}".encode(),
        f"Content-Transfer-Encoding: {kodowanie}".encode(),
    ]
    return b"\r\n".join(headers) + b"\r\n\r\n" + body.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")


def w_skrzynce(uid: int, raw: bytes, przyszedl: datetime = datetime(2026, 11, 8, 18, 5, tzinfo=TATA)) -> AtrapaMail:
    return AtrapaMail(uid, przyszedl, raw)


def dostep(config: Path, tresc: bytes = f"{SKRZYNKA}\nabcd efgh ijkl mnop\n".encode()) -> Path:
    (config / INBOX_ACCESS_FILE).write_bytes(tresc)
    return config


def z_pliku(config: Path) -> Callable[[], InboxState]:
    return lambda: read_snapshot(config).inbox


def port(config: Path, atrapa: AtrapaImap) -> ImapInbox:
    return ImapInbox(z_pliku(config), connect=lambda: imaplib.IMAP4("127.0.0.1", atrapa.port))


def z_odpowiedzia(
    config: Path, atrapa: AtrapaImap, polecenie: str, odpowiedz: Callable[[tuple[str, list[Any]]], tuple[str, list[Any]]]
) -> ImapInbox:
    class Polaczenie(imaplib.IMAP4):
        def uid(self, command: str, *args: str) -> tuple[str, list[Any]]:
            reply = super().uid(command, *args)
            return odpowiedz(reply) if command == "FETCH" and polecenie in args[-1] else reply

    return ImapInbox(z_pliku(config), connect=lambda: Polaczenie("127.0.0.1", atrapa.port))


def polecenia(atrapa: AtrapaImap) -> list[str]:
    names = [" ".join(command.split(" ")[:2 if command.startswith("UID ") else 1]) for command in atrapa.commands]
    # ZEWNĘTRZNE: imaplib z Pythona 3.14 bierze możliwości serwera z powitania, a z 3.11 pyta o nie poleceniem CAPABILITY (CPython Lib/imaplib.py, IMAP4._get_capabilities)
    return [name for name in names if name != "CAPABILITY"]


def maile(outcome: InboxOutcome) -> tuple[ReportMail, ...]:
    assert isinstance(outcome, Mails), outcome
    return outcome.mails


def test_skrzynka_raportow_otwiera_folder_wszystkich_maili_tylko_do_odczytu_i_pobiera_maile_bez_flagi_przeczytane(
    tmp_path: Path,
) -> None:
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=[w_skrzynce(7, surowy())]) as atrapa:
        outcome = port(dostep(tmp_path), atrapa).mails_since(date(2026, 11, 8))

    assert [(mail.subject, mail.text) for mail in maile(outcome)] == [("Raport 08.11.2026", "40000001 tak wymiana routera")]
    assert 'EXAMINE "[Gmail]/Wszystkie wiadomo&AVs-ci"' in atrapa.commands
    assert not WRITES & {name.removeprefix("UID ") for name in polecenia(atrapa)}
    fetches = [command for command in atrapa.commands if command.startswith("UID FETCH")]
    assert any("BODY.PEEK[TEXT]" in command for command in fetches)
    assert fetches and all("BODY[" not in command.replace("BODY.PEEK[", "") for command in fetches)
    assert polecenia(atrapa)[-1] == "LOGOUT"


def test_skrzynka_bez_folderu_wszystkich_maili_otwiera_odebrane_tylko_do_odczytu(tmp_path: Path) -> None:
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=[w_skrzynce(7, surowy())], all_folder=False) as atrapa:
        outcome = port(dostep(tmp_path), atrapa).mails_since(date(2026, 11, 8))

    assert len(maile(outcome)) == 1
    assert 'EXAMINE "INBOX"' in atrapa.commands


def test_przeglad_skrzynki_bez_folderu_wszystkich_maili_liczy_odebrane_raz_w_obu_miejscach(tmp_path: Path) -> None:
    mails = [w_skrzynce(1, surowy()), w_skrzynce(2, surowy(temat=b"Faktura", message_id=b"<2@x.invalid>"))]
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=mails, all_folder=False) as atrapa:
        survey = port(dostep(tmp_path), atrapa).survey(date(2026, 11, 8))

    assert isinstance(survey, InboxSurvey), survey
    assert (survey.searched, survey.in_folder, survey.in_inbox) == (2, 1, 1)
    assert [command for command in atrapa.commands if command.startswith("EXAMINE")] == ['EXAMINE "INBOX"']


def test_przeglad_skrzynki_z_flagami_maila_spoza_paczki_to_odpowiedz_ktorej_port_nie_zna(tmp_path: Path) -> None:
    def z_obcym_uid(reply: tuple[str, list[Any]]) -> tuple[str, list[Any]]:
        return reply[0], [*reply[1], b"9 (UID 999 FLAGS ())"]

    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=[w_skrzynce(7, surowy())]) as atrapa:
        survey = z_odpowiedzia(dostep(tmp_path), atrapa, "FLAGS", z_obcym_uid).survey(date(2026, 11, 8))

    assert survey == InboxUnreachable("UnexpectedReply")


def test_skrzynka_raportow_oddaje_maile_ze_slowem_raport_w_temacie_od_dnia_bez_maili_samej_skrzynki_i_liczy_maile_bez_nadawcy(
    tmp_path: Path,
) -> None:
    w_dniu = w_skrzynce(1, surowy(message_id=b"<a@x.invalid>"))
    duze_litery = w_skrzynce(
        2, surowy(temat=b"RAPORT 09.11.2026", message_id=b"<b@x.invalid>"), datetime(2026, 11, 9, 7, 0, tzinfo=TATA)
    )
    bez_slowa = w_skrzynce(3, surowy(temat=b"Faktura za listopad", message_id=b"<c@x.invalid>"))
    dwa_dni_wczesniej = w_skrzynce(4, surowy(message_id=b"<d@x.invalid>"), datetime(2026, 11, 6, 23, 30, tzinfo=TATA))
    od_skrzynki = w_skrzynce(5, surowy(od=f"Tata <{SKRZYNKA.upper()}>".encode(), message_id=b"<e@x.invalid>"))
    bez_nadawcy = w_skrzynce(6, surowy(od=None, message_id=b"<f@x.invalid>"))
    mails = [w_dniu, duze_litery, bez_slowa, dwa_dni_wczesniej, od_skrzynki, bez_nadawcy]

    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=mails) as atrapa:
        outcome = port(dostep(tmp_path), atrapa).mails_since(date(2026, 11, 8))

    assert isinstance(outcome, Mails), outcome
    assert outcome.skipped == 1
    found = outcome.mails

    assert [(mail.subject, mail.sender, mail.arrived) for mail in found] == [
        ("Raport 08.11.2026", SenderAddress.of(WYKONAWCA), datetime(2026, 11, 8, 18, 5, tzinfo=TATA)),
        ("RAPORT 09.11.2026", SenderAddress.of(WYKONAWCA), datetime(2026, 11, 9, 7, 0, tzinfo=TATA)),
    ]
    assert [mail.id for mail in found] == [MailId.of("<a@x.invalid>"), MailId.of("<b@x.invalid>")]
    assert all(len(mail.id.digest) == 16 and set(mail.id.digest) <= set("abcdefghijklmnop") for mail in found)
    assert found[0].arrived.utcoffset() == datetime(2026, 11, 8, 18, 5).astimezone().utcoffset()


def test_skrzynka_szuka_od_dnia_przed_wskazanym_bo_gmail_liczy_dzien_przyjecia_w_swojej_strefie(tmp_path: Path) -> None:
    u_taty = datetime(2026, 11, 8, 0, 30, tzinfo=TATA)
    po_polnocy_u_taty = w_skrzynce(1, surowy(), u_taty.astimezone(timezone.utc))

    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=[po_polnocy_u_taty]) as atrapa:
        found = maile(port(dostep(tmp_path), atrapa).mails_since(date(2026, 11, 8)))

    assert (u_taty.date(), u_taty.astimezone(timezone.utc).date()) == (date(2026, 11, 8), date(2026, 11, 7))
    assert [command for command in atrapa.commands if command.startswith("UID SEARCH")] == ["UID SEARCH SINCE 07-Nov-2026"]
    assert [mail.arrived for mail in found] == [u_taty]


def test_skrzynka_z_wiecej_maili_niz_paczka_pobierania_oddaje_kazdy_mail(tmp_path: Path) -> None:
    uids = [2 * n for n in range(1, 2 * FETCH_BATCH + 2)] + [1001, 1002, 1003]
    starsze = [w_skrzynce(uid, surowy(message_id=b"<starszy@x.invalid>"), datetime(2026, 11, 1, 9, 0, tzinfo=TATA)) for uid in (3, 1000)]
    mails = [w_skrzynce(uid, surowy(message_id=f"<{uid}@x.invalid>".encode())) for uid in uids] + starsze

    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=mails) as atrapa:
        found = maile(port(dostep(tmp_path), atrapa).mails_since(date(2026, 11, 8)))

    assert [mail.id for mail in found] == [MailId.of(f"<{uid}@x.invalid>") for uid in uids]
    fetched = [command.split(" ")[2].split(",") for command in atrapa.commands if command.startswith("UID FETCH")]
    assert fetched and max(len(items) for items in fetched) <= FETCH_BATCH
    assert len([command for command in atrapa.commands if "SUBJECT FROM" in command]) > 1
    assert any("1001:1003" in items for items in fetched)
    assert all(min(uids) < mail.uid < max(uids) and mail.uid not in uids for mail in starsze)
    assert _czytane(atrapa) == set(uids)


def z_zalacznikami(*, message_id: bytes | None = b"<z-zalacznikami@x.invalid>") -> bytes:
    tekst = MIMEMultipart("alternative", _subparts=[MIMEText(TRESC, "plain", "utf-8"), MIMEText(f"<p>{TRESC}</p>", "html", "utf-8")])
    zdjecie = MIMEImage(b"\xff\xd8" + bytes(range(256)) * 400, "jpeg")
    zdjecie.add_header("Content-Disposition", "attachment", filename=("utf-8", "", "zdjęcie licznika.jpg"))
    przekazany = MIMEText("40000009 tak", "plain", "utf-8")
    przekazany["Subject"] = "Raport 01.11.2026"
    root = MIMEMultipart(
        "mixed",
        _subparts=[tekst, zdjecie, MIMEApplication(b"%PDF-1.4" * 500, "pdf"), MIMEMessage(przekazany)],
    )
    root["From"] = "Jan Testowy <jan.testowy@przyklad.invalid>"
    root["Subject"] = TEMAT
    if message_id is not None:
        root["Message-ID"] = message_id.decode()
    return root.as_bytes(policy=email.policy.SMTP)


def test_skrzynka_czyta_raport_bez_pobierania_zalacznikow(tmp_path: Path) -> None:
    surowe = z_zalacznikami()
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=[w_skrzynce(7, surowe)]) as atrapa:
        found = maile(port(dostep(tmp_path), atrapa).mails_since(date(2026, 11, 8)))

    assert [(mail.id, mail.subject, mail.text) for mail in found] == [(MailId.of("<z-zalacznikami@x.invalid>"), TEMAT, TRESC)]
    fetches = [command for command in atrapa.commands if command.startswith("UID FETCH")]
    asked = {section for command in fetches for section in re.findall(r"BODY\.PEEK\[([^\]]*)\]", command)}
    assert asked == {"HEADER.FIELDS (SUBJECT FROM)", "HEADER", "1.MIME", "1.1.MIME", "1.1", "1.2.MIME"}


def _uidy(command: str) -> set[int]:
    found: set[int] = set()
    for part in command.split(" ")[2].split(","):
        first, _, last = part.partition(":")
        found.update(range(int(first), int(last or first) + 1))
    return found


def _pobrane(atrapa: AtrapaImap) -> set[int]:
    fetches = [command for command in atrapa.commands if command.startswith("UID FETCH")]
    return {uid for command in fetches if "HEADER.FIELDS (SUBJECT FROM)" not in command for uid in _uidy(command)}


def test_port_wybiera_maile_po_temacie_i_nadawcy_z_naglowkow_a_tresc_pobiera_tylko_wybranych(tmp_path: Path) -> None:
    def mail(uid: int, temat: bytes, od: bytes = b"Jan Testowy <jan.testowy@przyklad.invalid>") -> AtrapaMail:
        return w_skrzynce(uid, surowy(temat=temat, od=od, message_id=f"<{uid}@x.invalid>".encode()))

    mails = [
        mail(1, b"Rapotr 08.11.2026"),
        mail(2, b"Montaze 08.11.2026"),
        mail(3, "Zdjęcia do raportu 08.11.2026".encode()),
        mail(4, b"Faktura za listopad", b"Biuro <biuro@przyklad.invalid>"),
        mail(5, b"Raport 08.11.2026 Kowalski"),
        mail(6, b"Raport 08.11.2026", f"Tata <{SKRZYNKA}>".encode()),
        mail(7, b"Re: Raport 08.11.2026", f"Tata <{SKRZYNKA}>".encode()),
        mail(8, "Re: Raport 16.11.2026 - BŁĘDY PROSZĘ POPRAW".encode()),
        mail(9, b"Fwd: Raport 08.11.2026"),
        mail(10, b"Re: Zmiana w raportach 08.11.2026"),
        mail(11, b"Re: Raport 16.11 - popraw"),
        mail(12, b"Re: Raport popraw"),
    ]
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=mails) as atrapa:
        found = maile(port(dostep(tmp_path), atrapa).mails_since(date(2026, 11, 8)))

    assert [mail.subject for mail in found] == [
        "Rapotr 08.11.2026",
        "Raport 08.11.2026 Kowalski",
        "Re: Raport 16.11.2026 - BŁĘDY PROSZĘ POPRAW",
        "Re: Raport 16.11 - popraw",
    ]
    assert _pobrane(atrapa) == {1, 5, 8, 11}


def _czytane(atrapa: AtrapaImap) -> set[int]:
    return {uid for command in atrapa.commands if command.startswith("UID FETCH") for uid in _uidy(command)}


def test_kolejny_odczyt_skrzynki_pyta_serwer_tylko_o_maile_spoza_poprzedniego_i_oddaje_to_co_odczyt_od_zera(
    tmp_path: Path,
) -> None:
    def mail(uid: int, temat: bytes = b"Raport 08.11.2026", od: bytes | None = b"Jan <jan.testowy@przyklad.invalid>") -> AtrapaMail:
        return w_skrzynce(uid, surowy(temat=temat, od=od, message_id=f"<{uid}@x.invalid>".encode()))

    config = dostep(tmp_path)
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=[mail(1), mail(2, b"Faktura"), mail(3, od=None), mail(4)]) as atrapa:
        inbox = port(config, atrapa)
        first = inbox.mails_since(date(2026, 11, 8))
        atrapa.mails = (*atrapa.mails, mail(5), mail(6, b"Faktura"))
        atrapa.deleted.add(4)
        atrapa.commands.clear()
        again = inbox.mails_since(date(2026, 11, 8))
        asked = _czytane(atrapa)
        fresh = port(config, atrapa).mails_since(date(2026, 11, 8))

    assert [mail.id for mail in maile(first)] == [MailId.of("<1@x.invalid>"), MailId.of("<4@x.invalid>")]
    assert again == fresh
    assert [mail.id for mail in maile(again)] == [MailId.of("<1@x.invalid>"), MailId.of("<5@x.invalid>")]
    assert isinstance(again, Mails) and again.skipped == 1
    assert asked == {5, 6}


@pytest.mark.parametrize(("uidvalidity", "nowe_uidvalidity"), [(1, 2), (None, None)], ids=["zmienione", "bez-uidvalidity"])
def test_skrzynka_ze_zmienionym_albo_bez_uidvalidity_port_czyta_kazdy_mail_od_zera(
    tmp_path: Path, uidvalidity: int | None, nowe_uidvalidity: int | None
) -> None:
    config = dostep(tmp_path)
    przed = w_skrzynce(7, surowy(tresc="40000001 tak", message_id=b"<przed@x.invalid>"))
    po = w_skrzynce(7, surowy(tresc="40000002 nie", message_id=b"<po@x.invalid>"))
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=[przed], validity=uidvalidity) as atrapa:
        inbox = port(config, atrapa)
        first = inbox.mails_since(date(2026, 11, 8))
        atrapa.mails, atrapa.validity = (po,), nowe_uidvalidity
        again = inbox.mails_since(date(2026, 11, 8))

    assert [mail.text for mail in maile(first)] == ["40000001 tak"]
    assert [(mail.id, mail.text) for mail in maile(again)] == [(MailId.of("<po@x.invalid>"), "40000002 nie")]


@pytest.mark.parametrize("bez_odpowiedzi", ["choice", "content"], ids=["naglowki", "tresc"])
def test_mail_bez_odpowiedzi_serwera_port_czyta_przy_nastepnym_odczycie(
    tmp_path: Path, bez_odpowiedzi: Literal["choice", "content"]
) -> None:
    config = dostep(tmp_path)
    mails = [w_skrzynce(uid, surowy(message_id=f"<{uid}@x.invalid>".encode())) for uid in (1, 2)]
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=mails, unanswered={2: bez_odpowiedzi}) as atrapa:
        inbox = port(config, atrapa)
        first = inbox.mails_since(date(2026, 11, 8))
        atrapa.unanswered.clear()
        again = inbox.mails_since(date(2026, 11, 8))

    assert [mail.id for mail in maile(first)] == [MailId.of("<1@x.invalid>")]
    assert [mail.id for mail in maile(again)] == [MailId.of("<1@x.invalid>"), MailId.of("<2@x.invalid>")]


def test_pamiec_odczytu_jednej_skrzynki_nie_oddaje_maili_innej_skrzynce_ani_innemu_folderowi(tmp_path: Path) -> None:
    inna = "inna.skrzynka@przyklad.invalid"
    przed = w_skrzynce(7, surowy(tresc="40000001 tak", message_id=b"<przed@x.invalid>"))
    po = w_skrzynce(7, surowy(tresc="40000002 nie", message_id=b"<po@x.invalid>"))
    config = dostep(tmp_path)
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=[przed]) as atrapa:
        inbox = port(config, atrapa)
        first = inbox.mails_since(date(2026, 11, 8))
        atrapa.mails, atrapa.address = (po,), inna
        dostep(config, f"{inna}\nabcd efgh ijkl mnop\n".encode())
        po_adresie = inbox.mails_since(date(2026, 11, 8))
        atrapa.mails, atrapa.all_folder = (przed,), False
        po_folderze = inbox.mails_since(date(2026, 11, 8))

    assert [mail.text for mail in maile(first)] == ["40000001 tak"]
    assert [mail.text for mail in maile(po_adresie)] == ["40000002 nie"]
    assert [mail.text for mail in maile(po_folderze)] == ["40000001 tak"]


def test_mail_bez_message_id_port_pobiera_w_calosci_bo_jego_mailid_liczy_sie_z_bajtow_maila(tmp_path: Path) -> None:
    surowe = z_zalacznikami(message_id=None)
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=[w_skrzynce(7, surowe)]) as atrapa:
        found = maile(port(dostep(tmp_path), atrapa).mails_since(date(2026, 11, 8)))

    assert [(mail.id, mail.text) for mail in found] == [(MailId.of(hashlib.sha256(surowe).hexdigest()), TRESC)]
    assert any("BODY.PEEK[]" in command for command in atrapa.commands)


def test_gdy_serwer_odmawia_czesci_maila_port_pobiera_mail_w_calosci(tmp_path: Path) -> None:
    surowe = z_zalacznikami()
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=[w_skrzynce(7, surowe)], refuse="sections") as atrapa:
        found = maile(port(dostep(tmp_path), atrapa).mails_since(date(2026, 11, 8)))

    assert [(mail.subject, mail.text) for mail in found] == [(TEMAT, TRESC)]
    assert any("BODY.PEEK[]" in command for command in atrapa.commands)


def test_gdy_serwer_czyta_typ_czesci_inaczej_niz_email_port_pobiera_mail_w_calosci(tmp_path: Path) -> None:
    struktura = b'("IMAGE" "JPEG" NIL NIL NIL "BASE64" 10 NIL NIL NIL)'
    mail = AtrapaMail(7, datetime(2026, 11, 8, 18, 5, tzinfo=TATA), surowy(), structure=struktura)
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=[mail]) as atrapa:
        found = maile(port(dostep(tmp_path), atrapa).mails_since(date(2026, 11, 8)))

    assert [mail.text for mail in found] == ["40000001 tak wymiana routera"]
    assert any("BODY.PEEK[]" in command for command in atrapa.commands)


def test_gdy_serwer_opisuje_maile_w_postaci_spoza_rfc_port_pobiera_je_w_calosci(tmp_path: Path) -> None:
    mails = [w_skrzynce(uid, surowy(message_id=f"<{uid}@x.invalid>".encode())) for uid in (7, 8)]
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=mails) as atrapa:
        inbox = z_odpowiedzia(dostep(tmp_path), atrapa, "BODYSTRUCTURE", lambda reply: ("OK", [b"7 (UID 7"]))
        found = maile(inbox.mails_since(date(2026, 11, 8)))

    assert [mail.id for mail in found] == [MailId.of("<7@x.invalid>"), MailId.of("<8@x.invalid>")]
    assert any("BODY.PEEK[]" in command for command in atrapa.commands)


def test_przyklady_szkieletu_to_maile_z_trescia_poza_pierwsza_czescia_tekstu() -> None:
    def rozebrany(czesc: Message) -> EmailMessage:
        message = email.message_from_bytes(czesc.as_bytes(policy=email.policy.SMTP), policy=email.policy.default)
        assert isinstance(message, EmailMessage)
        return message

    [related] = _related_ze_start_na_zdjecie()
    [mieszany] = _html_obok_tekstu_w_zalaczniku()
    html = rozebrany(mieszany).get_body(preferencelist=("plain", "html"))

    assert rozebrany(related).get_body(preferencelist=("plain", "html")) is None
    assert html is not None and html.get_content_type() == "text/html"
    assert [part.get_content_type() for part in rozebrany(mieszany).iter_attachments()] == ["text/plain"]


def _related_ze_start_na_zdjecie() -> list[Message]:
    zdjecie = MIMEImage(b"\xff\xd8\xff", "jpeg")
    zdjecie.add_header("Content-ID", "<zdjecie-1@x.invalid>")
    related = MIMEMultipart("related", _subparts=[MIMEText("40000001 tak", "plain", "utf-8"), zdjecie])
    related.set_param("start", "<zdjecie-1@x.invalid>")
    return [related]


def _html_obok_tekstu_w_zalaczniku() -> list[Message]:
    zalacznik = MIMEText("notatka", "plain", "utf-8")
    zalacznik.add_header("Content-Disposition", "attachment", filename="notatka.txt")
    return [MIMEMultipart("mixed", _subparts=[zalacznik, MIMEText("<p>40000001 tak</p>", "html", "utf-8")])]


def _tekst(draw: st.DrawFn) -> str:
    return draw(st.text(alphabet="40000123 takniewymiaśćżółęńŁŻ,.\n", min_size=1, max_size=40)).strip() or "40000001 tak"


@st.composite
def czesc_maila(draw: st.DrawFn, glebokosc: int = 0) -> Message:
    rodzaje = ["plain", "html", "zdjecie", "pdf", "plik-tekstowy", "przekazany"]
    rodzaj = draw(st.sampled_from(rodzaje + (["mixed", "alternative", "related"] if glebokosc < 2 else [])))
    if rodzaj in ("plain", "html"):
        tekst = _tekst(draw)
        czesc: Message = MIMEText(tekst if rodzaj == "plain" else f"<div>{tekst}</div>", rodzaj, draw(st.sampled_from(["utf-8", "iso-8859-2"])))
    elif rodzaj == "zdjecie":
        czesc = MIMEImage(draw(st.binary(min_size=1, max_size=64)), "jpeg")
        czesc.add_header("Content-ID", f"<zdjecie-{draw(st.integers(0, 3))}@x.invalid>")
    elif rodzaj == "pdf":
        czesc = MIMEApplication(draw(st.binary(min_size=1, max_size=64)), "pdf")
    elif rodzaj == "plik-tekstowy":
        czesc = MIMEText(_tekst(draw), "plain", "utf-8")
    elif rodzaj == "przekazany":
        wewnetrzny = MIMEText(_tekst(draw), "plain", "utf-8")
        wewnetrzny["Subject"] = "Raport 01.11.2026"
        czesc = MIMEMessage(wewnetrzny)
    else:
        dzieci = draw(st.lists(czesc_maila(glebokosc + 1), min_size=1, max_size=3))
        czesc = MIMEMultipart(rodzaj, _subparts=dzieci)
        if rodzaj == "related" and draw(st.booleans()):
            czesc.set_param("start", f"<zdjecie-{draw(st.integers(0, 3))}@x.invalid>")
    if rodzaj not in ("mixed", "alternative", "related") and draw(st.booleans()):
        nazwa = draw(st.sampled_from(["notatka.txt", "zdjęcie licznika.jpg", 'raport "x".pdf']))
        czesc.add_header("Content-Disposition", draw(st.sampled_from(["attachment", "inline"])), filename=("utf-8", "", nazwa))
    return czesc


@settings(max_examples=60, derandomize=True, database=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.lists(czesc_maila(), min_size=1, max_size=4))
@example(_related_ze_start_na_zdjecie())
@example(_html_obok_tekstu_w_zalaczniku())
def test_skrzynka_bez_tresci_zalacznikow_daje_te_same_maile_co_rozbior_calego_maila(tmp_path: Path, czesci: list[Message]) -> None:
    surowe = []
    for uid, oryginal in enumerate(czesci, start=1):
        czesc = copy.deepcopy(oryginal)
        czesc["From"] = "Jan Testowy <jan.testowy@przyklad.invalid>"
        czesc["Subject"] = TEMAT
        czesc["Message-ID"] = f"<{uid}@x.invalid>"
        surowe.append(czesc.as_bytes(policy=email.policy.SMTP))
    przyszedl = datetime(2026, 11, 8, 18, 5, tzinfo=TATA)

    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=[w_skrzynce(uid, raw, przyszedl) for uid, raw in enumerate(surowe, 1)]) as atrapa:
        found = maile(port(dostep(tmp_path), atrapa).mails_since(date(2026, 11, 8)))

    assert found == tuple(mail for raw in surowe if (mail := mail_of(raw, przyszedl)) is not None)
    assert not any("BODY.PEEK[]" in command for command in atrapa.commands)


TEMAT = "Raport 08.11.2026 żółć"
TRESC = "40000001 tak wymiana złącza, ąęśźń ŻÓŁĆ"


@pytest.mark.parametrize(
    ("temat", "charset", "kodowanie"),
    [
        (b"=?utf-8?q?Raport_08=2E11=2E2026_=C5=BC=C3=B3=C5=82=C4=87?=", "windows-1250", "quoted-printable"),
        (b"=?windows-1250?b?" + base64.b64encode(TEMAT.encode("windows-1250")) + b"?=", "utf-8", "base64"),
        (b"=?windows-1250?q?Raport_08.11.2026_=BF=F3=B3=E6?=", "windows-1250", "base64"),
        (b"=?utf-8?b?" + base64.b64encode(TEMAT.encode()) + b"?=", "utf-8", "quoted-printable"),
        (b"=?utf-8?b?" + base64.b64encode(TEMAT.encode()) + b"?=", "x-nieznany", "quoted-printable"),
    ],
    ids=["temat-q-utf8-tresc-qp-1250", "temat-b-1250-tresc-b64-utf8", "temat-q-1250-tresc-b64-1250", "temat-b-utf8-tresc-qp-utf8", "nieznany-zestaw-znakow-jako-utf8"],
)
def test_skrzynka_raportow_dekoduje_polski_temat_i_tresc_w_kazdym_kodowaniu(
    tmp_path: Path, temat: bytes, charset: str, kodowanie: str
) -> None:
    raw = surowy(temat=temat, tresc=TRESC, charset=charset, kodowanie=kodowanie)

    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=[w_skrzynce(1, raw)]) as atrapa:
        found = maile(port(dostep(tmp_path), atrapa).mails_since(date(2026, 11, 8)))

    assert [(mail.subject, mail.text.strip()) for mail in found] == [(TEMAT, TRESC)]


HTML = (
    "<html><head><style>p { color: red }</style><script>var x = 1;</script></head><body>"
    "<p>40000001 tak wymiana&nbsp;routera</p><div>40000002   nie\nbrak klienta</div>"
    "<table><tr><td>40000003 tak</td></tr></table><ul><li>montaż</li></ul>Pozdrawiam<br>Jan</body></html>"
)


TEMAT_RAPORTU = b"Subject: Raport 08.11.2026\r\n"
ZEPSUTE = {
    "zestaw-znakow-z-bajtem-zerowym": b"From: ola@przyklad.invalid\r\n" + TEMAT_RAPORTU
    + b"Content-Type: text/plain; charset=u\x00f-8\r\n\r\n40000002 nie\r\n",
    "nadawca-jako-grupa": b"From: undiscloFrom: sed-;recipient:;\r\n" + TEMAT_RAPORTU + b"\r\nx\r\n",
    "zestaw-znakow-rfc2231-zawiniety": b"From: ola@przyklad.invalid\r\n" + TEMAT_RAPORTU
    + b"Content-Type: text/plain; charset*\n=''\r\n\r\nabc\r\n",
    "nadawca-z-nawiasem-kwadratowym-i-zla-granica": b"From: a@[b.invalid\r\n" + TEMAT_RAPORTU
    + b'Content-Type: multipart/mixed; boundary="x":\r\n\r\n--x\r\nContent-Type: application/pdf\r\n'
    + b"Content-Disposition: attachment; filename=a.pdf\r\n\r\nAAAA\r\n--x-\r\n -",
    "czesc-multipart-bez-granicy": b"From: ola@przyklad.invalid\r\n" + TEMAT_RAPORTU
    + b'Content-Type: multipart/alternative; boundary="x"\r\n\r\n--x\r\nContent-Type: multipart/related\r\n\r\n-x--',
    "nadawca-z-niezamknietym-cudzyslowem": b'From: "\n' + TEMAT_RAPORTU + b"\r\nx\r\n",
    "nadawca-z-niezamknietym-nawiasem": b"From: <\r\n" + TEMAT_RAPORTU + b"\r\nx\r\n",
    "message-id-z-nawiasami": b"From: ola@przyklad.invalid\r\n" + TEMAT_RAPORTU + b"Message-ID: <<<\r\n\r\nx\r\n",
    "nadawca-z-przecinkiem-i-dwukropkiem": b"From: \t,\t:f\x84\r\n" + TEMAT_RAPORTU + b"Message-ID: <z@x.invalid>\r\n\r\nx\r\n",
    "zalacznik-rfc822-z-zla-granica": b"From: a@\rb.invalid\r\n" + TEMAT_RAPORTU
    + b'Content-Type: multipart/mixed; boundary="\xffx"\r\n\r\n--x\r\nContent-yp: mess]age/rfc822\r\n\r\n'
    + b"From: c@d.pFrom: l\r\nSubject: s\r\n\r\nbody\r\n--x--",
    "naglowek-czesci-z-wyjatkiem-pakietu-email": b"From: Jan Testowy <jan.testowy@przyklad.invalid>\r\n" + TEMAT_RAPORTU
    + b'Message-ID: <zly@x.invalid>\r\nMIME-Version: 1.0\r\nContent-Type: multipart/related; boundary="B"\r\n\r\n'
    + b"--B\r\nContent-Type: text/plain\r\n\r\n40000001 tak\r\n--B\r\nContent-Type: *\r\n :multipart/mixed;attachment *"
    + b"\r\n\r\n40000001 tak\r\n--B--\r\n",
}


@pytest.mark.parametrize("zepsuty", ZEPSUTE.values(), ids=ZEPSUTE.keys())
def test_zepsuty_mail_z_raportem_w_temacie_nie_wywraca_odczytu_skrzynki_tylko_liczy_sie_jako_pominiety(
    tmp_path: Path, zepsuty: bytes
) -> None:
    dobre = [surowy(message_id=b"<dobry-1@x.invalid>"), surowy(message_id=b"<dobry-2@x.invalid>")]
    mails = [w_skrzynce(1, zepsuty), w_skrzynce(2, dobre[0]), w_skrzynce(3, zepsuty), w_skrzynce(4, dobre[1])]

    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=mails) as atrapa:
        outcome = port(dostep(tmp_path), atrapa).mails_since(date(2026, 11, 8))

    assert isinstance(outcome, Mails), outcome
    found = {mail.id: (mail.subject, mail.text) for mail in outcome.mails}
    assert [found.get(MailId.of(f"<dobry-{n}@x.invalid>")) for n in (1, 2)] == [
        ("Raport 08.11.2026", "40000001 tak wymiana routera")
    ] * 2
    # ZEWNĘTRZNE: ten sam zepsuty mail pakiet email jednej wersji Pythona rozbiera, a innej zgłasza wyjątek, np. nadawca-jako-grupa daje AttributeError w 3.11 i 3.12, a w 3.13 i 3.14 się rozbiera (CPython Lib/email/_header_value_parser.py)
    assert len(outcome.mails) + outcome.skipped == len(mails)
    assert polecenia(atrapa)[-1] == "LOGOUT"


def test_mail_z_zestawem_znakow_z_bajtem_zerowym_czyta_tresc_jako_utf8() -> None:
    mail = mail_of(ZEPSUTE["zestaw-znakow-z-bajtem-zerowym"], datetime(2026, 11, 8, 18, 5, tzinfo=TATA))

    assert mail is not None
    assert mail.text.strip() == "40000002 nie"


def test_mail_tylko_z_html_daje_tekst_z_linia_na_akapit_bez_stylow_i_skryptow() -> None:
    mail = mail_of(surowy(tresc=HTML, typ="text/html"), datetime(2026, 11, 8, 18, 5, tzinfo=TATA))

    assert mail is not None
    assert mail.text == "40000001 tak wymiana routera\n40000002 nie brak klienta\n40000003 tak\nmontaż\nPozdrawiam\nJan"


def test_mail_tylko_z_html_bez_znacznika_na_koncu_daje_cala_ostatnia_linie_takze_ze_znakiem_ampersand() -> None:
    raw = surowy(tresc="<p>40000001 tak wymiana routera</p>40000002 tak montaż AT&T", typ="text/html")

    mail = mail_of(raw, datetime(2026, 11, 8, 18, 5, tzinfo=TATA))

    assert mail is not None
    assert mail.text == "40000001 tak wymiana routera\n40000002 tak montaż AT&T"


def test_mail_z_tekstem_i_html_daje_tekst_z_czesci_text_plain() -> None:
    raw = (
        b"From: jan.testowy@przyklad.invalid\r\nSubject: Raport 08.11.2026\r\nMIME-Version: 1.0\r\n"
        b'Content-Type: multipart/alternative; boundary="g"\r\n\r\n'
        b"--g\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<p>z html</p>\r\n"
        b"--g\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n40000001 tak z tekstu\r\n--g--\r\n"
    )

    mail = mail_of(raw, datetime(2026, 11, 8, 18, 5, tzinfo=TATA))

    assert mail is not None
    assert mail.text.strip() == "40000001 tak z tekstu"
    assert mail.id == MailId.of(hashlib.sha256(raw).hexdigest())


@pytest.mark.parametrize(
    "tresc",
    [
        f"{SKRZYNKA}\r\nabcd efgh ijkl mnop\r\n".encode("utf-8-sig"),
        f"{SKRZYNKA}\r\nabcd efgh ijkl mnop\r\n".encode("utf-16"),
        codecs.BOM_UTF16_BE + f"{SKRZYNKA}\nabcdefghijklmnop".encode("utf-16-be"),
        f"  {SKRZYNKA.upper()}  \n  abcd efgh ijkl mnop  \n".encode(),
    ],
    ids=["notatnik-bom-utf8", "powershell-utf16-le", "utf16-be", "spacje-i-wielkie-litery"],
)
def test_plik_dostepu_z_notatnika_albo_powershella_otwiera_skrzynke(tmp_path: Path, tresc: bytes) -> None:
    inbox_config = dostep(tmp_path, tresc)

    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=[w_skrzynce(1, surowy())]) as atrapa:
        inbox = port(inbox_config, atrapa)
        state, outcome = inbox.access(), inbox.mails_since(date(2026, 11, 8))

    assert state == "ready"
    assert len(maile(outcome)) == 1


@pytest.mark.parametrize(
    ("tresc", "stan"),
    [
        (None, "missing"),
        (b"", "missing"),
        (f"{SKRZYNKA}\n".encode(), "missing"),
        (b"\nabcd efgh ijkl mnop\n", "missing"),
        (b"raporty.taty\nabcd efgh ijkl mnop\n", "unreadable"),
        (b"Tata <raporty.taty@przyklad.invalid>\nabcd\n", "unreadable"),
        (f"{SKRZYNKA}\nhas\xb3o\n".encode("latin-1"), "unreadable"),
        (f"{SKRZYNKA}\nhasło\n".encode(), "unreadable"),
    ],
    ids=["brak-pliku", "pusty", "bez-hasla", "bez-adresu", "adres-bez-malpy", "adres-z-nazwa", "nie-utf8", "haslo-spoza-ascii"],
)
def test_plik_dostepu_bez_hasla_albo_z_zla_trescia_nie_laczy_sie_ze_skrzynka(
    tmp_path: Path, tresc: bytes | None, stan: str
) -> None:
    if tresc is not None:
        dostep(tmp_path, tresc)

    def no_connection() -> imaplib.IMAP4:
        raise AssertionError("port łączy się ze skrzynką bez pliku dostępu")

    inbox = ImapInbox(z_pliku(tmp_path), connect=no_connection)

    assert inbox.access() == stan
    assert inbox.mails_since(date(2026, 11, 8)) == InboxUnreachable(stan)


def test_odrzucone_haslo_aplikacji_daje_wynik_odrzuconego_hasla_bez_otwarcia_skrzynki(tmp_path: Path) -> None:
    with AtrapaImap(address=SKRZYNKA, password="inne-haslo-maksa", mails=[w_skrzynce(1, surowy())]) as atrapa:
        outcome = port(dostep(tmp_path), atrapa).mails_since(date(2026, 11, 8))

    assert outcome == PasswordRejected()
    assert polecenia(atrapa) == ["LOGIN", "LOGOUT"]


def test_zerwane_polaczenie_i_brak_sieci_daja_wynik_niedostepnej_skrzynki_z_sama_nazwa_bledu(tmp_path: Path) -> None:
    config = dostep(tmp_path)

    with AtrapaImap(address=SKRZYNKA, password=HASLO, cut="greeting") as atrapa:
        cut = port(config, atrapa).mails_since(date(2026, 11, 8))

    def no_network() -> imaplib.IMAP4:
        raise ConnectionRefusedError(f"brak sieci przy {SKRZYNKA}")

    assert cut == InboxUnreachable("IMAP4.abort")
    assert ImapInbox(z_pliku(config), connect=no_network).mails_since(date(2026, 11, 8)) == InboxUnreachable("ConnectionRefusedError")


def test_polaczenie_zerwane_przy_wylogowaniu_oddaje_przeczytane_maile_i_zamyka_gniazdo(tmp_path: Path) -> None:
    sessions: list[imaplib.IMAP4] = []

    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=[w_skrzynce(7, surowy())], cut="logout") as atrapa:

        def connect() -> imaplib.IMAP4:
            sessions.append(imaplib.IMAP4("127.0.0.1", atrapa.port))
            return sessions[-1]

        outcome = ImapInbox(z_pliku(dostep(tmp_path)), connect=connect).mails_since(date(2026, 11, 8))

    assert [(mail.subject, mail.text) for mail in maile(outcome)] == [("Raport 08.11.2026", "40000001 tak wymiana routera")]
    assert polecenia(atrapa)[-1] == "LOGOUT"
    assert [session.sock.fileno() for session in sessions] == [-1]


@pytest.mark.parametrize(
    ("zerwanie", "odmowa", "przyczyna", "do_serwera"),
    [
        (None, "login", "IMAP4.error", ["LOGIN", "LOGOUT"]),
        ("after_login", None, "TimeoutError", ["LOGIN", "LIST", "LOGOUT"]),
        (None, "examine", "UnexpectedReply", ["LOGIN", "LIST", "EXAMINE", "LOGOUT"]),
    ],
    ids=["chwilowa-odmowa-logowania-bez-zlego-hasla", "gmail-milknie-po-zalogowaniu", "odmowa-otwarcia-folderu"],
)
def test_awaria_gmaila_w_trakcie_sesji_daje_wynik_niedostepnej_skrzynki_a_nie_odrzuconego_hasla(
    tmp_path: Path,
    zerwanie: Literal["after_login"] | None,
    odmowa: Literal["login", "examine"] | None,
    przyczyna: str,
    do_serwera: list[str],
) -> None:
    class LimitCzasuPoZalogowaniu(imaplib.IMAP4):
        def login(self, user: str, password: str) -> tuple[Literal["OK"], list[bytes]]:
            reply = super().login(user, password)
            self.sock.settimeout(0.01)
            return reply

    mails = [w_skrzynce(1, surowy())]
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=mails, cut=zerwanie, refuse=odmowa) as atrapa:
        inbox = ImapInbox(z_pliku(dostep(tmp_path)), connect=lambda: LimitCzasuPoZalogowaniu("127.0.0.1", atrapa.port))
        outcome = inbox.mails_since(date(2026, 11, 8))

    assert outcome == InboxUnreachable(przyczyna)
    assert polecenia(atrapa) == do_serwera


def _zlap_wynik(config: Path, scenariusz: str) -> tuple[ImapInbox, InboxOutcome]:
    if scenariusz == "brak-sieci":

        def no_network() -> imaplib.IMAP4:
            raise TimeoutError(f"LOGIN {SKRZYNKA} {HASLO}")

        inbox = ImapInbox(z_pliku(config), connect=no_network)
        return inbox, inbox.mails_since(date(2026, 11, 8))
    password = HASLO if scenariusz == "maile" else "inne-haslo-maksa"
    with AtrapaImap(address=SKRZYNKA, password=password, mails=[w_skrzynce(1, surowy())]) as atrapa:
        inbox = port(config, atrapa)
        return inbox, inbox.mails_since(date(2026, 11, 8))


@pytest.mark.parametrize("scenariusz", ["maile", "odrzucone-haslo", "brak-sieci"])
def test_haslo_aplikacji_nie_wychodzi_z_portu_w_zadnym_wyniku(tmp_path: Path, scenariusz: str) -> None:
    inbox, outcome = _zlap_wynik(dostep(tmp_path), scenariusz)

    texts = [repr(inbox), repr(outcome), str(outcome)]
    if isinstance(outcome, Mails):
        texts += [repr(mail) for mail in outcome.mails] + [mail.subject + mail.text for mail in outcome.mails]
    assert texts and not [text for text in texts if HASLO in text or "abcd efgh" in text]


def test_adres_nadawcy_nie_jest_tekstem_i_nie_pokazuje_sie_w_repr() -> None:
    address = SenderAddress.of("Jan Testowy <Jan.Testowy@Przyklad.invalid>")

    class Pole(pydantic.BaseModel):
        tekst: str

    assert address is not None
    assert address == SenderAddress.of(WYKONAWCA)
    assert len({address, SenderAddress.of(WYKONAWCA)}) == 1
    assert address.shown() == WYKONAWCA
    assert "jan" not in repr(address).casefold()
    with pytest.raises(TypeError, match="shown"):
        str(address)
    with pytest.raises(TypeError, match="shown"):
        f"{address}"
    with pytest.raises(pydantic.ValidationError):
        Pole(tekst=address)  # type: ignore[arg-type]
    niepoprawne = ["", "Jan Testowy", "a@b@c.invalid", '"a@b"@przyklad.invalid', '"a b"@przyklad.invalid', "@x.invalid", "jan@", '"jan@"']
    assert [SenderAddress.of(header) for header in niepoprawne] == [None] * len(niepoprawne)


def test_test_bez_atrapy_skrzynki_raportow_pada_zamiast_laczyc_sie_z_gmailem(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="Skrzynką raportów w Gmailu"):
        ImapInbox(z_pliku(dostep(tmp_path))).mails_since(date(2026, 11, 8))


def test_skrzynka_z_folderu_eml_oddaje_maile_z_tematem_raportu_jak_port(tmp_path: Path) -> None:
    for name, temat in [("1", b"Rapotr 08.11.2026"), ("2", "Zdjęcia do raportu 08.11.2026".encode()), ("3", b"Faktura")]:
        (tmp_path / f"{name}.eml").write_bytes(b"Date: Sun, 08 Nov 2026 18:05:00 +0100\r\n" + surowy(temat=temat))

    found = maile(FolderInbox(tmp_path).mails_since(date(2026, 11, 8)))

    assert [mail.subject for mail in found] == ["Rapotr 08.11.2026"]


def test_skrzynka_z_folderu_eml_ma_okno_dni_pominiete_maile_i_brak_skrzynki_jak_port(tmp_path: Path) -> None:
    folder = tmp_path / "maile"
    folder.mkdir()
    for name, sent in [("dzien-przed", b"Sat, 07 Nov 2026 18:05:00 +0100"), ("dwa-dni-przed", b"Fri, 06 Nov 2026 18:05:00 +0100")]:
        (folder / f"{name}.eml").write_bytes(b"Date: " + sent + b"\r\n" + surowy(message_id=f"<{name}@x.invalid>".encode()))
    (folder / "bez-daty.eml").write_bytes(surowy(message_id=b"<bez-daty@x.invalid>"))

    outcome = FolderInbox(folder).mails_since(date(2026, 11, 8))

    assert isinstance(outcome, Mails), outcome
    assert ([mail.arrived.date() for mail in outcome.mails], outcome.skipped) == ([date(2026, 11, 7)], 1)
    assert FolderInbox(tmp_path / "brak").mails_since(date(2026, 11, 8)) == InboxUnreachable("missing")


PRZYPOMNIENIE = Reminder(
    worker=Login("jan.testowy"),
    recipients=(SenderAddress(WYKONAWCA), SenderAddress("jan.prywatny@przyklad.invalid")),
    day=date(2026, 11, 9),
    subject="Przypomnienie: raport za dzień 09.11.2026",
    text="Poproszę o wysłanie raportu za dzień 09.11.2026.\n\nPozdrawiam, zażółć gęślą jaźń\n",
)
WYSLANE_O = datetime(2026, 11, 10, 8, 1, tzinfo=TATA)
DZIEN_PRZED = datetime(2026, 11, 7, 18, 0, tzinfo=TATA)
ZEPSUTY_ADRESAT = "To: \t[?, :c.]x\\<"


def wyslany(uid: int, temat: str, do: str = WYKONAWCA, kiedy: datetime = WYSLANE_O, flagi: tuple[str, ...] = ()) -> AtrapaMail:
    message = EmailMessage()
    message["From"] = SKRZYNKA
    message["To"] = do
    message["Subject"] = temat
    message["Date"] = format_datetime(kiedy)
    message.set_content("treść")
    return AtrapaMail(uid, kiedy, bytes(message), flags=flagi, in_inbox=False)


def smtp_portu(config: Path, imap: AtrapaImap, smtp: AtrapaSmtp) -> ImapInbox:
    return ImapInbox(
        z_pliku(config),
        connect=lambda: imaplib.IMAP4("127.0.0.1", imap.port),
        smtp=lambda: smtplib.SMTP("127.0.0.1", smtp.port, timeout=10),
    )


def test_przypomnienie_idzie_przez_smtp_ze_skrzynki_raportow_do_kazdego_adresu_wykonawcy_i_trafia_do_wyslanych(
    tmp_path: Path,
) -> None:
    with AtrapaImap(address=SKRZYNKA, password=HASLO) as imap, AtrapaSmtp(imap) as smtp:
        inbox = smtp_portu(dostep(tmp_path), imap, smtp)
        outcome = inbox.send(PRZYPOMNIENIE, WYSLANE_O)
        sent = inbox.sent_reminders(date(2026, 11, 9))

    assert outcome == MailSent()
    [(raw, recipients)] = smtp.received
    message = email.message_from_bytes(raw, policy=email.policy.default)
    assert recipients == (WYKONAWCA, "jan.prywatny@przyklad.invalid")
    assert (message["From"], message["To"], message["Subject"]) == (
        SKRZYNKA,
        f"{WYKONAWCA}, jan.prywatny@przyklad.invalid",
        "Przypomnienie: raport za dzień 09.11.2026",
    )
    assert message["Date"].datetime == WYSLANE_O
    assert str(message["Message-ID"]).endswith(f"@{SKRZYNKA.partition('@')[2]}>")
    body = message.get_body()
    assert body is not None and body.get_content().replace("\r\n", "\n") == PRZYPOMNIENIE.text, "SMTP niesie linie z CRLF"
    assert [command.split(" ")[0] for command in smtp.commands] == ["ehlo", "AUTH", "mail", "rcpt", "rcpt", "data", "quit"]
    assert sent == SentReminders(
        (SentReminder(frozenset(PRZYPOMNIENIE.recipients), date(2026, 11, 9), WYSLANE_O.astimezone()),)
    )


def test_wyslane_przypomnienia_czyta_z_folderu_wyslane_tylko_do_odczytu_bez_zmiany_flag(tmp_path: Path) -> None:
    sent = [
        wyslany(101, "Przypomnienie: raport za dzień 09.11.2026", flagi=("\\Seen",)),
        wyslany(102, "Przypomnienie: raport za dzień 08.11.2026", do=f"Ewa <ewa@przyklad.invalid>, {WYKONAWCA}"),
        wyslany(103, "Re: Raport 09.11.2026"),
        wyslany(104, "Przypomnienie: raport za dzień 01.11.2026", kiedy=datetime(2026, 11, 2, 8, 0, tzinfo=TATA)),
        wyslany(105, "Przypomnienie: raport za dzień 06.11.2026", kiedy=DZIEN_PRZED),
        wyslany(106, "Przypomnienie: raport za dzień 09.11.2026", do=""),
    ]
    with AtrapaImap(address=SKRZYNKA, password=HASLO, sent=sent) as atrapa:
        outcome = port(dostep(tmp_path), atrapa).sent_reminders(date(2026, 11, 8))

    assert outcome == SentReminders(
        (
            SentReminder(frozenset({SenderAddress(WYKONAWCA)}), date(2026, 11, 9), WYSLANE_O.astimezone()),
            SentReminder(
                frozenset({SenderAddress(WYKONAWCA), SenderAddress("ewa@przyklad.invalid")}),
                date(2026, 11, 8),
                WYSLANE_O.astimezone(),
            ),
            SentReminder(frozenset({SenderAddress(WYKONAWCA)}), date(2026, 11, 6), DZIEN_PRZED.astimezone()),
        )
    )
    assert 'EXAMINE "[Gmail]/Wys&AUI-ane"' in atrapa.commands
    assert not WRITES & {name.removeprefix("UID ") for name in polecenia(atrapa)}
    fetches = [command for command in atrapa.commands if command.startswith("UID FETCH")]
    assert fetches and all("BODY.PEEK[HEADER.FIELDS (SUBJECT TO)]" in command for command in fetches)
    assert atrapa.flags == {101: {"\\Seen"}, 102: set(), 103: set(), 104: set(), 105: set(), 106: set()}


def test_zepsuty_naglowek_adresata_w_wyslanych_to_nie_przypomnienie_a_przypomnienie_obok_zostaje(tmp_path: Path) -> None:
    zepsuty = (
        f"From: {SKRZYNKA}\r\n{ZEPSUTY_ADRESAT}\r\nSubject: Przypomnienie: raport za dzień 08.11.2026\r\n"
        f"Date: {format_datetime(WYSLANE_O)}\r\n\r\ntreść\r\n"
    ).encode()
    with pytest.raises(IndexError):
        str(email.message_from_bytes(zepsuty, policy=email.policy.default)["To"])
    sent = [wyslany(101, "Przypomnienie: raport za dzień 09.11.2026"), AtrapaMail(102, WYSLANE_O, zepsuty, in_inbox=False)]
    with AtrapaImap(address=SKRZYNKA, password=HASLO, sent=sent) as atrapa:
        outcome = port(dostep(tmp_path), atrapa).sent_reminders(date(2026, 11, 8))

    assert outcome == SentReminders(
        (SentReminder(frozenset({SenderAddress(WYKONAWCA)}), date(2026, 11, 9), WYSLANE_O.astimezone()),)
    )


def test_skrzynka_bez_folderu_wyslane_nie_daje_przypomnien_tylko_wynik_niedostepnej(tmp_path: Path) -> None:
    with AtrapaImap(address=SKRZYNKA, password=HASLO, sent_folder=False) as atrapa:
        outcome = port(dostep(tmp_path), atrapa).sent_reminders(date(2026, 11, 8))

    assert outcome == InboxUnreachable("UnexpectedReply")


def test_odrzucone_haslo_przy_wysylce_i_odczycie_wyslanych_daje_wynik_odrzuconego_hasla(tmp_path: Path) -> None:
    with AtrapaImap(address=SKRZYNKA, password="inne-haslo-maksa") as imap, AtrapaSmtp(imap) as smtp:
        inbox = smtp_portu(dostep(tmp_path), imap, smtp)
        outcomes = [inbox.send(PRZYPOMNIENIE, WYSLANE_O), inbox.sent_reminders(date(2026, 11, 8))]

    assert outcomes == [PasswordRejected(), PasswordRejected()]
    assert smtp.received == [] and "mail" not in [command.split(" ")[0] for command in smtp.commands]


def _bez_sieci() -> smtplib.SMTP:
    raise ConnectionRefusedError(f"AUTH {SKRZYNKA} {HASLO}")


def _wynik_wysylki(config: Path, scenariusz: str) -> tuple[ImapInbox, object]:
    if scenariusz == "brak-sieci":
        inbox = ImapInbox(z_pliku(config), smtp=_bez_sieci)
        return inbox, inbox.send(PRZYPOMNIENIE, WYSLANE_O)
    password = "inne-haslo-maksa" if scenariusz == "odrzucone-haslo" else HASLO
    cut: Literal["greeting"] | None = "greeting" if scenariusz == "zerwane" else None
    refusals: dict[str, Literal["greeting", "recipients"]] = {"zajety": "greeting", "odmowa-adresu": "recipients"}
    refuse = refusals.get(scenariusz)
    with AtrapaImap(address=SKRZYNKA, password=password) as imap, AtrapaSmtp(imap, cut=cut, refuse=refuse) as smtp:
        inbox = smtp_portu(config, imap, smtp)
        return inbox, inbox.send(PRZYPOMNIENIE, WYSLANE_O)


@pytest.mark.parametrize(
    ("scenariusz", "wynik"),
    [
        pytest.param("wyslane", MailSent(), id="wyslane"),
        pytest.param("odrzucone-haslo", PasswordRejected(), id="odrzucone-haslo"),
        pytest.param("brak-sieci", InboxUnreachable("ConnectionRefusedError"), id="brak-sieci"),
        pytest.param("zerwane", InboxUnreachable("SMTPServerDisconnected"), id="zerwane-polaczenie"),
        pytest.param("zajety", InboxUnreachable("SMTPConnectError"), id="zajety-serwer"),
        pytest.param("odmowa-adresu", MailRefused("SMTPRecipientsRefused"), id="odmowa-adresu"),
    ],
)
def test_wynik_wysylki_przypomnienia_niesie_sama_nazwe_bledu_bez_hasla(tmp_path: Path, scenariusz: str, wynik: object) -> None:
    inbox, outcome = _wynik_wysylki(dostep(tmp_path), scenariusz)

    assert outcome == wynik
    assert not [text for text in (repr(inbox), repr(outcome), str(outcome)) if HASLO in text or "abcd efgh" in text]


def test_polaczenie_smtp_zerwane_przy_wylogowaniu_daje_wyslany_mail_i_zamyka_gniazdo(tmp_path: Path) -> None:
    sessions: list[smtplib.SMTP] = []

    class ZerwanePrzyQuit(smtplib.SMTP):
        def quit(self) -> tuple[int, bytes]:
            raise smtplib.SMTPServerDisconnected

    with AtrapaImap(address=SKRZYNKA, password=HASLO) as imap, AtrapaSmtp(imap) as smtp:

        def connect() -> smtplib.SMTP:
            sessions.append(ZerwanePrzyQuit("127.0.0.1", smtp.port, timeout=10))
            return sessions[-1]

        outcome = ImapInbox(z_pliku(dostep(tmp_path)), connect=lambda: imaplib.IMAP4("127.0.0.1", imap.port), smtp=connect).send(
            PRZYPOMNIENIE, WYSLANE_O
        )

    assert outcome == MailSent()
    assert len(smtp.received) == 1
    assert [session.sock for session in sessions] == [None]


def test_dostep_do_skrzynki_z_pliku_nie_ma_hasla_w_repr(tmp_path: Path) -> None:
    config = dostep(tmp_path)

    shown = repr(z_pliku(config)())

    assert ImapInbox(z_pliku(config)).access() == "ready"
    assert HASLO not in shown and "abcd efgh" not in shown


def test_test_bez_atrapy_smtp_pada_zamiast_laczyc_sie_z_gmailem(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="Skrzynką raportów w Gmailu"):
        ImapInbox(z_pliku(dostep(tmp_path))).send(PRZYPOMNIENIE, WYSLANE_O)


ROZLICZENIE = "Rozliczenie 03_09_11_2026 - Paweł Łączyński.xlsx"
XLSX = b"PK\x03\x04 syntetyczny skoroszyt"


def z_zalacznikiem(
    uid: int, nazwa: str, do: str = WYKONAWCA, kiedy: datetime = WYSLANE_O, *, centrum: bool = False, kopie: Sequence[tuple[str, str]] = ()
) -> AtrapaMail:
    message = EmailMessage()
    message["From"] = SKRZYNKA
    if do:
        message["To"] = do
    for naglowek, adresaci in kopie:
        message[naglowek] = adresaci
    message["Subject"] = "Rozliczenie za 3–9 listopada 2026"
    message["Date"] = format_datetime(kiedy)
    if centrum:
        message[CENTRUM_MARK[0]] = CENTRUM_MARK[1]
    message.set_content("Dzień dobry")
    message.add_attachment(XLSX, maintype="application", subtype="octet-stream", filename=nazwa)
    return AtrapaMail(uid, kiedy, bytes(message), in_inbox=False)


def test_zalaczniki_z_wyslanych_czyta_tylko_z_naglowkow_bez_tresci_i_bez_zmiany_flag(tmp_path: Path) -> None:
    sent = [
        z_zalacznikiem(101, ROZLICZENIE, centrum=True),
        z_zalacznikiem(102, ROZLICZENIE, do=f"Ewa <ewa@przyklad.invalid>, {WYKONAWCA}"),
        wyslany(103, "Przypomnienie: raport za dzień 09.11.2026"),
        z_zalacznikiem(104, ROZLICZENIE, kiedy=datetime(2026, 11, 2, 8, 0, tzinfo=TATA), centrum=True),
        AtrapaMail(105, WYSLANE_O, z_zalacznikiem(105, ROZLICZENIE).raw.replace(f"To: {WYKONAWCA}".encode(), ZEPSUTY_ADRESAT.encode()), in_inbox=False),
        z_obrazkiem_bez_nazwy(106),
        z_zalacznikiem(107, ROZLICZENIE, kiedy=DZIEN_PRZED),
    ]
    with AtrapaImap(address=SKRZYNKA, password=HASLO, sent=sent) as atrapa:
        outcome = port(dostep(tmp_path), atrapa).sent_attachments(date(2026, 11, 8))

    assert outcome == SentAttachments(
        (
            SentAttachment(ROZLICZENIE, frozenset({SenderAddress(WYKONAWCA)}), WYSLANE_O.astimezone(), by_centrum=True),
            SentAttachment(
                ROZLICZENIE,
                frozenset({SenderAddress(WYKONAWCA), SenderAddress("ewa@przyklad.invalid")}),
                WYSLANE_O.astimezone(),
                by_centrum=False,
            ),
            SentAttachment(ROZLICZENIE, frozenset({SenderAddress(WYKONAWCA)}), DZIEN_PRZED.astimezone(), by_centrum=False),
        )
    )
    assert 'EXAMINE "[Gmail]/Wys&AUI-ane"' in atrapa.commands
    assert not WRITES & {name.removeprefix("UID ") for name in polecenia(atrapa)}
    fetched = " ".join(command for command in atrapa.commands if command.startswith("UID FETCH"))
    assert "BODYSTRUCTURE" in fetched and "BODY.PEEK[2.MIME]" in fetched
    assert not re.search(r"BODY\.PEEK\[(?:\d+|TEXT)?\]", fetched), "treści i bajtów załącznika port nie pobiera"
    naglowki = {uid for command in atrapa.commands if "BODY.PEEK[HEADER]" in command for uid in _uidy(command)}
    assert naglowki == {101, 102, 105, 106, 107}
    assert atrapa.flags == dict.fromkeys(range(101, 108), set())


def z_obrazkiem_bez_nazwy(uid: int) -> AtrapaMail:
    message = EmailMessage()
    message["From"] = SKRZYNKA
    message["To"] = WYKONAWCA
    message["Subject"] = "Zdjęcie"
    message["Date"] = format_datetime(WYSLANE_O)
    message.set_content("Dzień dobry")
    message.add_attachment(b"\xff\xd8\xff", maintype="image", subtype="jpeg")
    return AtrapaMail(uid, WYSLANE_O, bytes(message), in_inbox=False)


@pytest.mark.parametrize(
    ("polecenie", "odpowiedz"),
    [
        pytest.param("BODY.PEEK[HEADER]", lambda reply: ("NO", [b"odmowa"]), id="odmowa-naglowkow"),
        pytest.param("BODY.PEEK[HEADER]", lambda reply: ("OK", [b"101 (UID 101"]), id="naglowki-spoza-rfc"),
        pytest.param("BODYSTRUCTURE", lambda reply: ("OK", [b"101 (UID 101"]), id="struktura-spoza-rfc"),
    ],
)
def test_wyslane_w_odpowiedzi_spoza_rfc_albo_z_odmowa_nie_daja_pustej_listy_zalacznikow(
    tmp_path: Path, polecenie: str, odpowiedz: Callable[[tuple[str, list[Any]]], tuple[str, list[Any]]]
) -> None:
    with AtrapaImap(address=SKRZYNKA, password=HASLO, sent=[z_zalacznikiem(101, ROZLICZENIE)]) as atrapa:
        outcome = z_odpowiedzia(dostep(tmp_path), atrapa, polecenie, odpowiedz).sent_attachments(date(2026, 11, 8))

    assert outcome == InboxUnreachable("UnexpectedReply")


def test_mail_z_wyslanych_ze_struktura_spoza_rfc_nie_ma_zalacznikow_a_reszta_zostaje(tmp_path: Path) -> None:
    nieznany = AtrapaMail(102, WYSLANE_O, z_zalacznikiem(102, ROZLICZENIE).raw, in_inbox=False, structure=b'("X")')
    with AtrapaImap(address=SKRZYNKA, password=HASLO, sent=[z_zalacznikiem(101, ROZLICZENIE), nieznany]) as atrapa:
        outcome = port(dostep(tmp_path), atrapa).sent_attachments(date(2026, 11, 8))

    assert outcome == SentAttachments(
        (SentAttachment(ROZLICZENIE, frozenset({SenderAddress(WYKONAWCA)}), WYSLANE_O.astimezone(), by_centrum=False),)
    )


def test_zalacznik_wyslany_w_kopii_albo_ukrytej_kopii_ma_tez_tych_adresatow(tmp_path: Path) -> None:
    sent = [
        z_zalacznikiem(101, ROZLICZENIE, do="biuro@przyklad.invalid", kopie=[("Cc", f"Paweł <{WYKONAWCA}>")]),
        z_zalacznikiem(102, ROZLICZENIE, do="", kopie=[("Bcc", f"{WYKONAWCA}, ewa@przyklad.invalid")]),
    ]
    with AtrapaImap(address=SKRZYNKA, password=HASLO, sent=sent) as atrapa:
        outcome = port(dostep(tmp_path), atrapa).sent_attachments(date(2026, 11, 8))

    assert isinstance(outcome, SentAttachments)
    assert [attachment.recipients for attachment in outcome.attachments] == [
        frozenset({SenderAddress("biuro@przyklad.invalid"), SenderAddress(WYKONAWCA)}),
        frozenset({SenderAddress(WYKONAWCA), SenderAddress("ewa@przyklad.invalid")}),
    ]


def test_mail_z_rozliczeniem_idzie_przez_smtp_z_plikiem_xlsx_i_znakiem_centrum_i_wraca_z_wyslanych(tmp_path: Path) -> None:
    mail = AttachmentMail(
        (SenderAddress(WYKONAWCA), SenderAddress("jan.prywatny@przyklad.invalid")),
        "Rozliczenie za 3–9 listopada 2026",
        "Dzień dobry,\nzażółć gęślą jaźń\n",
        ROZLICZENIE,
        XLSX,
    )
    with AtrapaImap(address=SKRZYNKA, password=HASLO) as imap, AtrapaSmtp(imap) as smtp:
        inbox = smtp_portu(dostep(tmp_path), imap, smtp)
        outcome = inbox.send_attachment(mail, WYSLANE_O)
        sent = inbox.sent_attachments(date(2026, 11, 9))

    assert outcome == MailSent()
    [(raw, recipients)] = smtp.received
    message = email.message_from_bytes(raw, policy=email.policy.default)
    assert isinstance(message, EmailMessage)
    assert recipients == (WYKONAWCA, "jan.prywatny@przyklad.invalid")
    assert (message["From"], message["Subject"], message[CENTRUM_MARK[0]]) == (SKRZYNKA, mail.subject, CENTRUM_MARK[1])
    assert str(message["Message-ID"]).endswith(f"@{SKRZYNKA.partition('@')[2]}>")
    body = message.get_body(preferencelist=("plain",))
    assert body is not None and body.get_content().replace("\r\n", "\n") == mail.text
    [attachment] = list(message.iter_attachments())
    assert attachment.get_content_type() == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert (attachment.get_filename(), attachment.get_content()) == (ROZLICZENIE, XLSX)
    assert sent == SentAttachments(
        (SentAttachment(ROZLICZENIE, frozenset(mail.recipients), WYSLANE_O.astimezone(), by_centrum=True),)
    )


def test_wyslane_bez_folderu_wyslane_albo_z_odrzuconym_haslem_nie_daja_pustej_listy_zalacznikow(tmp_path: Path) -> None:
    with AtrapaImap(address=SKRZYNKA, password=HASLO, sent_folder=False) as atrapa:
        without_folder = port(dostep(tmp_path), atrapa).sent_attachments(date(2026, 11, 8))
    with AtrapaImap(address=SKRZYNKA, password="inne-haslo-maksa") as atrapa:
        rejected = port(dostep(tmp_path), atrapa).sent_attachments(date(2026, 11, 8))

    assert (without_folder, rejected) == (InboxUnreachable("UnexpectedReply"), PasswordRejected())
