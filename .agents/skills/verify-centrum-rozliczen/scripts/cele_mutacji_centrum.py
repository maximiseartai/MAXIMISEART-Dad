"""Pliki Centrum i polecenia funkcji, których używają skrypty mutacji ``check_centrum_<funkcja>_mutations.py``.

Nazwa bez ``mutation``: ``Katalog.skanuj`` (``tools/lib/kroki_skilli.py``) daje FAIL plikowi skilla z ``mutation`` w nazwie spoza wzorca
``check_*_mutations.py``.

Stałe trzymaj w kolejności alfabetycznej: dopiski dwóch PR-ów trafiają wtedy w różne miejsca pliku.
"""

from __future__ import annotations

from pathlib import Path

APP = Path("src/rozliczenia/centrum/app.py")
# The committed frontend build: a change of the frontend source needs its anchor here after `npm run regen`.
BUILD = Path("src/rozliczenia/centrum/static/assets/index.js")
CASE_DELIVERY = Path("src/rozliczenia/centrum/case_delivery.py")
DAD_CASES = Path("src/rozliczenia/centrum/dad_cases.py")
DIAGNOSIS = Path("src/rozliczenia/centrum/diagnosis.py")
EFENIX_BROWSER = Path("src/rozliczenia/efenix_browser.py")
EFENIX_CHECKS = Path("src/rozliczenia/efenix_checks.py")
EFENIX_KIND = Path("src/rozliczenia/centrum/processes/efenix.py")
FILLING = Path("src/rozliczenia/centrum/filling.py")
INTERMAX_COPIES = Path("src/rozliczenia/intermax_copies.py")
INTERMAX_KIND = Path("src/rozliczenia/centrum/processes/intermax.py")
INTERMAX_ORDERING = Path("src/rozliczenia/intermax_ordering.py")
INTERMAX_RUN = Path("src/rozliczenia/centrum/intermax_run.py")
KEYED_BOX = Path("src/rozliczenia/centrum/keyed_box.py")
LIVE_FILE = Path("src/rozliczenia/centrum/live_file.py")
NOTIFICATIONS = Path("src/rozliczenia/centrum/notifications.py")
OUTBOX = Path("src/rozliczenia/centrum/outbox.py")
QUANTITIES_TO_FILL = Path("src/rozliczenia/quantities_to_fill.py")
REPORTS = Path("src/rozliczenia/centrum/reports.py")
RUN_CARDS = Path("src/rozliczenia/centrum/run_cards.py")
RUN_LOGS = Path("src/rozliczenia/centrum/run_logs.py")
RUN_VIEW = Path("src/rozliczenia/centrum/run_view.py")
SETTINGS_ROUTER = Path("src/rozliczenia/centrum/settings_router.py")
SETTLEMENT_KIND = Path("src/rozliczenia/centrum/processes/settlement.py")
SETTLEMENT_MESSAGES = Path("src/rozliczenia/settlement_messages.py")
STOPS = Path("src/rozliczenia/centrum/stops.py")
TOOL_UPDATES = Path("src/rozliczenia/centrum/tool_updates.py")
WORKBOOK_FILES = Path("src/rozliczenia/workbook_files.py")
WORKER_CONFIG = Path("src/rozliczenia/worker_config.py")
RUNNER = ".agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py"
AKTUALIZACJA = (RUNNER, "--feature", "aktualizacja")
DIAGNOZA = (RUNNER, "--feature", "diagnoza")
KARTA = (RUNNER, "--feature", "karta-z-logow")
KOPIE = (RUNNER, "--feature", "kopie-intermax")
PRZEBIEG = (RUNNER, "--feature", "przebieg-rozliczen")
PRZYGOTOWANIE = (RUNNER, "--feature", "przygotowanie-pliku-zbiorczego")
UPORZADKOWANIE = (RUNNER, "--feature", "uporzadkowanie-intermax")
UWAGA = (RUNNER, "--feature", "uwaga-taty")
UZUPELNIENIE = (RUNNER, "--feature", "uzupelnienie")
WYCENA = (RUNNER, "--feature", "wycena-w-efenix")
ZGLOSZENIE = (RUNNER, "--feature", "zgloszenie")
