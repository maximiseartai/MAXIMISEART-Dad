"""Kontrakt pomiaru u taty: pomiar gotowego widoku z przeglądarki i czasy jego zapytań API."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from rozliczenia.centrum.contract.common import Model


PageId = Literal["okresy", "uruchomienia", "metryki", "ustawienia", "powiadomienia", "uzupelnienie", "raporty"]
"""Strony Centrum (``frontend/src/pages.tsx``): z bocznego menu i widok Powiadomienia; identyfikator to adres ``#/<id>``
strony. Okno Ustawień (``#/ustawienia/<sekcja>``) otwiera się nad stroną i mierzy się jak ona, pod identyfikatorem
``ustawienia``."""


ViewKind = Literal["cold_start", "navigation"]
"""Zimny start strony (otwarcie albo odświeżenie karty) albo przejście w menu."""


ApiOperation = Literal[
    "getHealth",
    "getSettings",
    "addWorker",
    "changeWorker",
    "switchWorker",
    "removeWorker",
    "getWorkerSuggestions",
    "assignWorkerAddress",
    "chooseRegister",
    "openRegister",
    "choosePeriodsDirectory",
    "changeTheme",
    "changeInboxPassword",
    "changeFolders",
    "changeAutostart",
    "changeRemindersEnabled",
    "changeReminders",
    "previewReminder",
    "getSettingsHistory",
    "getQuantityDifferences",
    "markQuantityException",
    "getQuantityRules",
    "addQuantityRule",
    "changeQuantityRule",
    "removeQuantityRule",
    "previewQuantityRules",
    "addDevice",
    "changeDevice",
    "removeDevice",
    "getDeviceSuggestions",
    "undoSettingsChange",
    "getPeriodBoard",
    "openPeriodPath",
    "getQuantitiesToFill",
    "getCollectiveFileVersion",
    "getWithoutQuantity",
    "getKindTable",
    "openWorkerSettlement",
    "getRunSetup",
    "startRun",
    "getIntermaxSetup",
    "getIntermaxDays",
    "startIntermax",
    "getIntermaxCopies",
    "restoreIntermaxCopy",
    "getReportEnteringSetup",
    "startReportEntering",
    "getReportsView",
    "keepManualValue",
    "decideRun",
    "diagnoseRun",
    "reportRun",
    "getRunCard",
    "getNotifications",
    "markNotificationsRead",
    "getMetrics",
    "getConfiguration",
    "startToolUpdate",
    "getToolUpdate",
    "reportToolUpdate",
    "getDadNoteRuns",
    "draftDadNote",
    "sendDadNote",
    "closeCentrum",
]
"""Operacje API, które przeglądarka mierzy: nazwy (``operation_id``) zamiast adresu z tokenem okresu. Trasy spoza tej
listy, każda z powodem, wymienia ``OUTSIDE_TIMING`` w ``tests/test_centrum_rozliczen.py``, który wiąże listę z trasami;
że przeglądarka woła każdą przez ``call``, pilnuje reguła 4 w ``frontend/scripts/rules.mjs``."""


Milliseconds = Annotated[int, Field(ge=0, le=600_000)]
"""Do 10 minut: dłuższy czas to uśpiona karta, nie pomiar."""


MAX_TIMED_REQUESTS = 20


class ApiTiming(Model):
    """Jedno zapytanie API widoku: czas w przeglądarce i czas serwera z ``Server-Timing`` (``None``: brak nagłówka)."""

    operation: ApiOperation
    browser_ms: Milliseconds
    server_ms: Milliseconds | None


class ViewTiming(Model):
    """Pomiar gotowego widoku z przeglądarki: same liczby i nazwy z kontraktu, bez adresów i treści.

    ``ready_ms`` to czas do gotowej treści, ``fcp_ms`` pierwsze malowanie treści
    (tylko przy zimnym starcie), ``skeleton_ms`` czas widocznego szkieletu.
    """

    kind: ViewKind
    page: PageId
    ready_ms: Milliseconds
    fcp_ms: Milliseconds | None
    skeleton_ms: Milliseconds
    requests: Annotated[list[ApiTiming], Field(max_length=MAX_TIMED_REQUESTS)]
