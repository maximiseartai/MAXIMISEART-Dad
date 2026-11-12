"""Skrzynka raportów (ADR 0028): port czyta maile Wykonawców z Gmaila tylko do odczytu.

Port rozmawia prawdziwym ``imaplib`` i ``smtplib`` z lokalną ``AtrapaImap`` i ``AtrapaSmtp`` (``tools/lib/atrapy/skrzynka_raportow.py``), bez sieci:
test sprawdza polecenia, które dostał serwer, i wynik, który oddał port. Prawdziwego Gmaila sprawdza próba IMAP (#1234).
Maile są syntetyczne, zbudowane w teście bajt po bajcie, żeby było widać każde kodowanie nagłówka i treści.
"""

from __future__ import annotations

import base64
import codecs
import copy
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
from typing import Literal

from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st
import pydantic
import pytest

from rozliczenia.worker_report_inbox import (
    FETCH_BATCH,
    INBOX_ACCESS_FILE,
    ImapInbox,
    InboxOutcome,
    InboxUnreachable,
    MailRefused,
    Mails,
    MailSent,
    PasswordRejected,
    SentReminders,
    WorkerReportInbox,
    mail_of,
)
from rozliczenia.worker_reports import Login, MailId, Reminder, ReportMail, SenderAddress, SentReminder

from atrapy.skrzynka_raportow import AtrapaImap, AtrapaMail, AtrapaSmtp, FakeInbox

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
    """Mail MIME z jedną częścią: treść w ``charset`` zakodowana ``kodowanie`` (quoted-printable albo base64)."""

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


def port(config: Path, atrapa: AtrapaImap) -> ImapInbox:
    return ImapInbox(config, connect=lambda: imaplib.IMAP4("127.0.0.1", atrapa.port))


def polecenia(atrapa: AtrapaImap) -> list[str]:
    """Nazwy poleceń, które dostał serwer (``UID FETCH`` jako jedna nazwa), bez ``CAPABILITY``.

    ``imaplib`` z Pythona 3.14 bierze możliwości serwera z powitania, a 3.11 pyta o nie osobno: to nie decyzja portu.
    """

    names = [" ".join(command.split(" ")[:2 if command.startswith("UID ") else 1]) for command in atrapa.commands]
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


@pytest.mark.parametrize(
    ("temat", "oddane"),
    [
        pytest.param(
            b"=?utf-8?q?Re=3A_Przypomnienie=3A_raport_za_dzie=C5=84_08=2E11=2E2026?=",
            ["Re: Przypomnienie: raport za dzień 08.11.2026"],
            id="re",
        ),
        pytest.param(
            b"=?utf-8?b?T2RwOiBQcnp5cG9tbmllbmllOiByYXBvcnQgemEgZHppZcWEIDA4LjExLjIwMjY=?=",
            ["Odp: Przypomnienie: raport za dzień 08.11.2026"],
            id="odp-z-outlooka",
        ),
        pytest.param(b"Re: Przypomnienie o fakturze", [], id="bez-slowa-raport"),
    ],
)
def test_skrzynka_oddaje_odpowiedz_wykonawcy_na_przypomnienie_o_raporcie(
    tmp_path: Path, temat: bytes, oddane: list[str]
) -> None:
    """Odpowiedź na Przypomnienie o raporcie ma słowo „raport” w temacie, więc port oddaje ją rdzeniowi (ADR 0030)."""

    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=[w_skrzynce(1, surowy(temat=temat))]) as atrapa:
        found = maile(port(dostep(tmp_path), atrapa).mails_since(date(2026, 11, 8)))

    assert [mail.subject for mail in found] == oddane


def test_skrzynka_szuka_od_dnia_przed_wskazanym_bo_gmail_liczy_dzien_przyjecia_w_swojej_strefie(tmp_path: Path) -> None:
    # 23:30 UTC 7 listopada to 00:30 8 listopada u taty: Gmail zalicza taki mail do 7 listopada.
    po_polnocy_u_taty = w_skrzynce(1, surowy(), datetime(2026, 11, 7, 23, 30, tzinfo=timezone.utc))

    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=[po_polnocy_u_taty]) as atrapa:
        found = maile(port(dostep(tmp_path), atrapa).mails_since(date(2026, 11, 8)))

    assert [command for command in atrapa.commands if command.startswith("UID SEARCH")] == ["UID SEARCH SINCE 07-Nov-2026"]
    assert [mail.arrived for mail in found] == [datetime(2026, 11, 8, 0, 30, tzinfo=TATA)]


def test_skrzynka_z_wiecej_maili_niz_paczka_pobierania_oddaje_kazdy_mail(tmp_path: Path) -> None:
    """UID bez przerw idą zakresem ``a:b``, a polecenie ma najwyżej ``FETCH_BATCH`` zakresów: tu same pojedyncze UID z
    przerwami między nimi, więc paczek jest kilka. W przerwach leżą starsze Raporty spoza wyszukanych dni, których
    zakres nie może objąć."""

    uids = [2 * n for n in range(1, 2 * FETCH_BATCH + 2)] + [1001, 1002, 1003]
    starsze = [w_skrzynce(uid, surowy(message_id=b"<starszy@x.invalid>"), datetime(2026, 11, 1, 9, 0, tzinfo=TATA)) for uid in (3, 1000)]
    mails = [w_skrzynce(uid, surowy(message_id=f"<{uid}@x.invalid>".encode())) for uid in uids] + starsze

    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=mails) as atrapa:
        found = maile(port(dostep(tmp_path), atrapa).mails_since(date(2026, 11, 8)))

    assert [mail.id for mail in found] == [MailId.of(f"<{uid}@x.invalid>") for uid in uids]
    fetched = [command.split(" ")[2].split(",") for command in atrapa.commands if command.startswith("UID FETCH")]
    assert fetched and max(len(items) for items in fetched) <= FETCH_BATCH
    assert any("1001:1003" in items for items in fetched)


def z_zalacznikami(*, message_id: bytes | None = b"<z-zalacznikami@x.invalid>") -> bytes:
    """Raport ze zdjęciem, PDF-em i przekazanym mailem, jak z telefonu Wykonawcy: tekst w ``multipart/alternative``."""

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
    """Pełny mail ze zdjęciami to megabajty, a Gmail liczy pobranie treści za każdy mail: port bierze strukturę, nagłówki
    i treść części ``text/plain``, którą wybiera ``mail_of``, a treść HTML i załączników zostaje w skrzynce (pomiar
    12.11.2026: 214 MB i 17–34 s dla 121 maili)."""

    surowe = z_zalacznikami()
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=[w_skrzynce(7, surowe)]) as atrapa:
        found = maile(port(dostep(tmp_path), atrapa).mails_since(date(2026, 11, 8)))

    assert [(mail.id, mail.subject, mail.text) for mail in found] == [(MailId.of("<z-zalacznikami@x.invalid>"), TEMAT, TRESC)]
    fetches = [command for command in atrapa.commands if command.startswith("UID FETCH")]
    asked = {section for command in fetches for section in re.findall(r"BODY\.PEEK\[([^\]]*)\]", command)}
    assert asked == {"HEADER.FIELDS (SUBJECT)", "HEADER", "1.MIME", "1.1.MIME", "1.1", "1.2.MIME"}


def test_mail_od_samej_skrzynki_port_pomija_bez_pobierania_tresci(tmp_path: Path) -> None:
    """Przypomnienia o raporcie, które Centrum wysyła ze skrzynki raportów, leżą w folderze wszystkich maili ze słowem
    „raport” w temacie: port pomija je po nagłówku ``From``, zanim pobierze ich treść."""

    od_skrzynki = z_zalacznikami(message_id=b"<przypomnienie@x.invalid>").replace(
        b"From: Jan Testowy <jan.testowy@przyklad.invalid>", f"From: Tata <{SKRZYNKA}>".encode()
    )
    mails = [w_skrzynce(7, z_zalacznikami()), w_skrzynce(8, od_skrzynki)]
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=mails) as atrapa:
        found = maile(port(dostep(tmp_path), atrapa).mails_since(date(2026, 11, 8)))

    assert [(mail.id, mail.text) for mail in found] == [(MailId.of("<z-zalacznikami@x.invalid>"), TRESC)]
    tresc = [command for command in atrapa.commands if command.startswith("UID FETCH") and re.search(r"PEEK\[(TEXT|\d[\d.]*)?\]", command)]
    assert tresc and all(command.split(" ")[2].split(",") == ["7"] for command in tresc)


def test_zepsuty_naglowek_czesci_jednego_maila_nie_wywraca_odczytu_skrzynki(tmp_path: Path) -> None:
    """Nagłówek części, na którym pakiet ``email`` zgłasza wyjątek (fuzz przeglądu #1416 r1): szkielet tego maila się
    nie składa, port pobiera go w całości, a ``mail_of`` liczy go jako pominięty; dobry mail obok dochodzi."""

    def related(message_id: bytes, typ_drugiej: bytes) -> bytes:
        return (
            b"From: Jan Testowy <jan.testowy@przyklad.invalid>\r\nSubject: Raport 08.11.2026\r\nMessage-ID: " + message_id
            + b'\r\nMIME-Version: 1.0\r\nContent-Type: multipart/related; boundary="B"\r\n\r\n'
            + b"--B\r\nContent-Type: text/plain\r\n\r\n40000001 tak\r\n--B\r\nContent-Type: " + typ_drugiej
            + b"\r\n\r\n40000001 tak\r\n--B--\r\n"
        )

    mails = [
        w_skrzynce(1, related(b"<dobry@x.invalid>", b"text/plain; charset=utf-8")),
        w_skrzynce(2, related(b"<zly@x.invalid>", b"*\r\n :multipart/mixed;attachment *")),
    ]
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=mails) as atrapa:
        outcome = port(dostep(tmp_path), atrapa).mails_since(date(2026, 11, 8))

    assert isinstance(outcome, Mails), outcome
    assert ([(mail.id, mail.text) for mail in outcome.mails], outcome.skipped) == (
        [(MailId.of("<dobry@x.invalid>"), "40000001 tak")],
        1,
    )


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
    """Mail z tekstem, który serwer opisuje jako zdjęcie: szkielet bez treści tej części zgubiłby Raport, więc port
    pobiera wtedy cały mail."""

    struktura = b'("IMAGE" "JPEG" NIL NIL NIL "BASE64" 10 NIL NIL NIL)'
    mail = AtrapaMail(7, datetime(2026, 11, 8, 18, 5, tzinfo=TATA), surowy(), structure=struktura)
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=[mail]) as atrapa:
        found = maile(port(dostep(tmp_path), atrapa).mails_since(date(2026, 11, 8)))

    assert [mail.text for mail in found] == ["40000001 tak wymiana routera"]
    assert any("BODY.PEEK[]" in command for command in atrapa.commands)


def _related_ze_start_na_zdjecie() -> list[Message]:
    """``multipart/related``, którego ``start`` wskazuje zdjęcie, a nie pierwszą część: ``get_body`` szuka treści w
    zdjęciu i jej nie znajduje, więc szkielet musi mieć ``Content-ID`` zdjęcia z jego nagłówka."""

    zdjecie = MIMEImage(b"\xff\xd8\xff", "jpeg")
    zdjecie.add_header("Content-ID", "<zdjecie-1@x.invalid>")
    related = MIMEMultipart("related", _subparts=[MIMEText("40000001 tak", "plain", "utf-8"), zdjecie])
    related.set_param("start", "<zdjecie-1@x.invalid>")
    return [related]


def _html_obok_tekstu_w_zalaczniku() -> list[Message]:
    """Treść w HTML, a ``text/plain`` tylko w załączniku: ``get_body`` wybiera HTML, którego treści port nie wziął w
    pierwszym poleceniu, bo mail ma część ``text/plain``."""

    zalacznik = MIMEText("notatka", "plain", "utf-8")
    zalacznik.add_header("Content-Disposition", "attachment", filename="notatka.txt")
    return [MIMEMultipart("mixed", _subparts=[zalacznik, MIMEText("<p>40000001 tak</p>", "html", "utf-8")])]


def _tekst(draw: st.DrawFn) -> str:
    return draw(st.text(alphabet="40000123 takniewymiaśćżółęńŁŻ,.\n", min_size=1, max_size=40)).strip() or "40000001 tak"


@st.composite
def czesc_maila(draw: st.DrawFn, glebokosc: int = 0) -> Message:
    """Część maila w kształcie, jaki wysyła telefon albo program pocztowy Wykonawcy: tekst, HTML, zdjęcie, PDF, plik
    tekstowy w załączniku, przekazany mail albo ``multipart`` (``mixed``, ``alternative``, ``related`` ze ``start``)."""

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
    """``mail_of`` na mailu ze skrzynki daje to samo co na całym mailu (``mail_skeleton``): nadawca, temat, ``MailId``
    i treść, którą wybiera ``get_body``, dla każdego kształtu maila z ``czesc_maila``."""

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
    "zalacznik-rfc822-z-zla-granica": b"From: a@\rb.invalid\r\n" + TEMAT_RAPORTU
    + b'Content-Type: multipart/mixed; boundary="\xffx"\r\n\r\n--x\r\nContent-yp: mess]age/rfc822\r\n\r\n'
    + b"From: c@d.pFrom: l\r\nSubject: s\r\n\r\nbody\r\n--x--",
}


@pytest.mark.parametrize("zepsuty", ZEPSUTE.values(), ids=ZEPSUTE.keys())
def test_zepsuty_mail_z_raportem_w_temacie_nie_wywraca_odczytu_skrzynki_tylko_liczy_sie_jako_pominiety(
    tmp_path: Path, zepsuty: bytes
) -> None:
    """Maile, na których pakiet ``email`` Pythona 3.11, 3.12 albo 3.14 zgłaszał wyjątek (fuzz recenzenta #1236).

    Który mail parser umie rozebrać, zależy od wersji, więc test żąda tylko, żeby każdy mail był przeczytany albo
    policzony jako pominięty, a poprawne Raporty przed zepsutym mailem i po nim doszły (skrzynka: zepsuty, dobry,
    zepsuty, dobry).
    """

    dobre = [surowy(message_id=b"<dobry-1@x.invalid>"), surowy(message_id=b"<dobry-2@x.invalid>")]
    mails = [w_skrzynce(1, zepsuty), w_skrzynce(2, dobre[0]), w_skrzynce(3, zepsuty), w_skrzynce(4, dobre[1])]

    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=mails) as atrapa:
        outcome = port(dostep(tmp_path), atrapa).mails_since(date(2026, 11, 8))

    assert isinstance(outcome, Mails), outcome
    found = {mail.id: (mail.subject, mail.text) for mail in outcome.mails}
    assert [found.get(MailId.of(f"<dobry-{n}@x.invalid>")) for n in (1, 2)] == [
        ("Raport 08.11.2026", "40000001 tak wymiana routera")
    ] * 2
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

    inbox = ImapInbox(tmp_path, connect=no_connection)

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
    assert ImapInbox(config, connect=no_network).mails_since(date(2026, 11, 8)) == InboxUnreachable("ConnectionRefusedError")


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
        """Połączenie, któremu limit czasu (w porcie ``TIMEOUT_S``) mija od razu po zalogowaniu, a nie wcześniej."""

        def login(self, user: str, password: str) -> tuple[Literal["OK"], list[bytes]]:
            reply = super().login(user, password)
            self.sock.settimeout(0.01)
            return reply

    mails = [w_skrzynce(1, surowy())]
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=mails, cut=zerwanie, refuse=odmowa) as atrapa:
        inbox = ImapInbox(dostep(tmp_path), connect=lambda: LimitCzasuPoZalogowaniu("127.0.0.1", atrapa.port))
        outcome = inbox.mails_since(date(2026, 11, 8))

    assert outcome == InboxUnreachable(przyczyna)
    assert polecenia(atrapa) == do_serwera


def _zlap_wynik(config: Path, scenariusz: str) -> tuple[ImapInbox, InboxOutcome]:
    if scenariusz == "brak-sieci":

        def no_network() -> imaplib.IMAP4:
            raise TimeoutError(f"LOGIN {SKRZYNKA} {HASLO}")

        inbox = ImapInbox(config, connect=no_network)
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
    niepoprawne = ["", "Jan Testowy", "a@b@c.invalid", '"a@b"@przyklad.invalid', '"a b"@przyklad.invalid', "@x.invalid", "jan@"]
    assert [SenderAddress.of(header) for header in niepoprawne] == [None] * len(niepoprawne)


def test_test_bez_atrapy_skrzynki_raportow_pada_zamiast_laczyc_sie_z_gmailem(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="Skrzynką raportów w Gmailu"):
        ImapInbox(dostep(tmp_path)).mails_since(date(2026, 11, 8))


def test_atrapa_skrzynki_raportow_procesu_oddaje_swoj_wynik_i_zapisuje_dzien_kazdego_odczytu() -> None:
    mail = mail_of(surowy(), datetime(2026, 11, 8, 18, 5, tzinfo=TATA))
    assert mail is not None
    with_mails = FakeInbox([mail])
    rejected = FakeInbox(PasswordRejected(), state="unreadable")
    inboxes: list[WorkerReportInbox] = [with_mails, rejected]

    assert [inbox.mails_since(date(2026, 11, 8)) for inbox in inboxes] == [Mails((mail,), skipped=0), PasswordRejected()]
    assert [inbox.access() for inbox in inboxes] == ["ready", "unreadable"]
    assert with_mails.days == rejected.days == [date(2026, 11, 8)]


# --- Przypomnienia o raporcie: „Wysłane” i wysyłka przez SMTP (ADR 0030, #1349) ----------------------------------------

PRZYPOMNIENIE = Reminder(
    worker=Login("jan.testowy"),
    recipients=(SenderAddress(WYKONAWCA), SenderAddress("jan.prywatny@przyklad.invalid")),
    day=date(2026, 11, 9),
    subject="Przypomnienie: raport za dzień 09.11.2026",
    text="Poproszę o wysłanie raportu za dzień 09.11.2026.\n\nPozdrawiam, zażółć gęślą jaźń\n",
)
WYSLANE_O = datetime(2026, 11, 10, 8, 1, tzinfo=TATA)


def wyslany(uid: int, temat: str, do: str = WYKONAWCA, kiedy: datetime = WYSLANE_O, flagi: tuple[str, ...] = ()) -> AtrapaMail:
    """Mail w „Wysłanych” skrzynki raportów: od skrzynki do ``do`` z tematem ``temat``."""

    message = EmailMessage()
    message["From"] = SKRZYNKA
    message["To"] = do
    message["Subject"] = temat
    message["Date"] = format_datetime(kiedy)
    message.set_content("treść")
    return AtrapaMail(uid, kiedy, bytes(message), flags=flagi, in_inbox=False)


def smtp_portu(config: Path, imap: AtrapaImap, smtp: AtrapaSmtp) -> ImapInbox:
    return ImapInbox(
        config,
        connect=lambda: imaplib.IMAP4("127.0.0.1", imap.port),
        smtp=lambda: smtplib.SMTP("127.0.0.1", smtp.port, timeout=10),
    )


def test_przypomnienie_idzie_przez_smtp_ze_skrzynki_raportow_do_kazdego_adresu_wykonawcy_i_trafia_do_wyslanych(
    tmp_path: Path,
) -> None:
    """Wysyłka loguje się adresem i hasłem aplikacji z pliku dostępu, wysyła jeden mail z tematem, treścią w UTF-8 i datą
    na wszystkie adresy Wykonawcy, a Gmail (atrapa) kładzie go w „Wysłanych”, skąd czyta go odczyt przypomnień."""

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
    body = message.get_body()
    assert body is not None and body.get_content().replace("\r\n", "\n") == PRZYPOMNIENIE.text, "SMTP niesie linie z CRLF"
    assert [command.split(" ")[0] for command in smtp.commands] == ["ehlo", "AUTH", "mail", "rcpt", "rcpt", "data", "quit"]
    assert sent == SentReminders(
        (SentReminder(frozenset(PRZYPOMNIENIE.recipients), date(2026, 11, 9), WYSLANE_O.astimezone()),)
    )


def test_wyslane_przypomnienia_czyta_z_folderu_wyslane_tylko_do_odczytu_bez_zmiany_flag(tmp_path: Path) -> None:
    """Odczyt „Wysłanych” otwiera folder ``\\Sent`` przez ``EXAMINE``, pobiera tylko nagłówki ``Subject`` i ``To`` przez
    ``BODY.PEEK`` i oddaje tylko maile z tematem przypomnienia, z adresatami i chwilą przyjęcia; flagi zostają."""

    sent = [
        wyslany(101, "Przypomnienie: raport za dzień 09.11.2026", flagi=("\\Seen",)),
        wyslany(102, "Przypomnienie: raport za dzień 08.11.2026", do=f"Ewa <ewa@przyklad.invalid>, {WYKONAWCA}"),
        wyslany(103, "Re: Raport 09.11.2026"),
        wyslany(104, "Przypomnienie: raport za dzień 01.11.2026", kiedy=datetime(2026, 11, 2, 8, 0, tzinfo=TATA)),
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
        )
    )
    assert 'EXAMINE "[Gmail]/Wys&AUI-ane"' in atrapa.commands
    assert not WRITES & {name.removeprefix("UID ") for name in polecenia(atrapa)}
    fetches = [command for command in atrapa.commands if command.startswith("UID FETCH")]
    assert fetches and all("BODY.PEEK[HEADER.FIELDS (SUBJECT TO)]" in command for command in fetches)
    assert atrapa.flags == {101: {"\\Seen"}, 102: set(), 103: set(), 104: set()}


def test_skrzynka_bez_folderu_wyslane_nie_daje_przypomnien_tylko_wynik_niedostepnej(tmp_path: Path) -> None:
    """Bez folderu ``\\Sent`` nie wiadomo, co już poszło, więc odczyt nie oddaje pustej listy, która wysłałaby wszystko."""

    with AtrapaImap(address=SKRZYNKA, password=HASLO, sent_folder=False) as atrapa:
        outcome = port(dostep(tmp_path), atrapa).sent_reminders(date(2026, 11, 8))

    assert outcome == InboxUnreachable("UnexpectedReply")


def test_odrzucone_haslo_przy_wysylce_i_odczycie_wyslanych_daje_wynik_odrzuconego_hasla(tmp_path: Path) -> None:
    """Gmail odrzuca hasło aplikacji przy SMTP (``535``) i IMAP (``AUTHENTICATIONFAILED``): oba to ``PasswordRejected``,
    z którego praca przypomnień zakłada Zgłoszenie do Maksa (US 47)."""

    with AtrapaImap(address=SKRZYNKA, password="inne-haslo-maksa") as imap, AtrapaSmtp(imap) as smtp:
        inbox = smtp_portu(dostep(tmp_path), imap, smtp)
        outcomes = [inbox.send(PRZYPOMNIENIE, WYSLANE_O), inbox.sent_reminders(date(2026, 11, 8))]

    assert outcomes == [PasswordRejected(), PasswordRejected()]
    assert smtp.received == [] and "mail" not in [command.split(" ")[0] for command in smtp.commands]


def _bez_sieci() -> smtplib.SMTP:
    raise ConnectionRefusedError(f"AUTH {SKRZYNKA} {HASLO}")


def _wynik_wysylki(config: Path, scenariusz: str) -> tuple[ImapInbox, object]:
    if scenariusz == "brak-sieci":
        inbox = ImapInbox(config, smtp=_bez_sieci)
        return inbox, inbox.send(PRZYPOMNIENIE, WYSLANE_O)
    password = "inne-haslo-maksa" if scenariusz == "odrzucone-haslo" else HASLO
    cut: Literal["greeting"] | None = "greeting" if scenariusz == "zerwane" else None
    refuse: Literal["recipients"] | None = "recipients" if scenariusz == "odmowa-adresu" else None
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
        pytest.param("odmowa-adresu", MailRefused("SMTPRecipientsRefused"), id="odmowa-adresu"),
    ],
)
def test_wynik_wysylki_przypomnienia_niesie_sama_nazwe_bledu_bez_hasla(tmp_path: Path, scenariusz: str, wynik: object) -> None:
    """Brak sieci i zerwane połączenie to ``InboxUnreachable`` (ponowienie w tej samej porze), inna odmowa serwera to
    ``MailRefused``, a hasło aplikacji nie wychodzi z portu w żadnym wyniku, ``repr`` ani tekście (US 47)."""

    inbox, outcome = _wynik_wysylki(dostep(tmp_path), scenariusz)

    assert outcome == wynik
    assert not [text for text in (repr(inbox), repr(outcome), str(outcome)) if HASLO in text or "abcd efgh" in text]


def test_test_bez_atrapy_smtp_pada_zamiast_laczyc_sie_z_gmailem(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="Skrzynką raportów w Gmailu"):
        ImapInbox(dostep(tmp_path)).send(PRZYPOMNIENIE, WYSLANE_O)
