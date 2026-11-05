"""Komentarz postępu Wyceny w efenix w issue Logów okresu (#846): w trakcie Wyceny Maks widzi, jak idzie.

Wycena w efenix trwa u taty do półtorej godziny, a Logi Uruchomienia powstają dopiero na jej końcu. Przy starcie Wyceny
(``run_started``) Centrum zakłada jej komentarz Uruchomienia w issue Logów okresu, a potem co ``PROGRESS_S`` na zegarze
Centrum, nigdy częściej, odświeża go stanem dziennika Wyceny (``PricingJournal.progress``): zlecenia skończone z
wszystkich, wyniki do tej pory, ostatnie skończone zlecenie, zlecenie w trakcie i czas od startu. Dziennik podaje tylko
wpisy, które już ma na dysku, więc postęp nigdy go nie wyprzedza.

Postęp to starsza wersja tej samej wysyłki co Logi tego Uruchomienia (``run_logs.progress_post``: ten sam ``run_id`` i
etykieta), więc kolejka zmienia ten sam komentarz, a bez sieci najnowszy postęp w kolejce zastępuje starszy (``outbox``).
Koniec Uruchomienia (``run_ended``, działanie po wyniku przed Logami Uruchomienia) kończy odświeżanie, zanim Logi pójdą do
kolejki, więc żaden postęp nie przychodzi po nich, a Logi zamieniają komentarz w podsumowanie z odnośnikiem do Archiwum
Logów okresu. Komentarz Urwanego Uruchomienia zamieniają w podsumowanie jego Logi przy następnym starcie Centrum
(``pricing_journal.InterruptedPricings``).

Postęp jest dla Maksa, a nie warunkiem pracy taty: wysyłkę, której kolejka nie przyjęła, ``Outbox.post`` zapisuje w
dzienniku Centrum, a Wycena biegnie dalej.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import partial
import threading
from typing import Final

from rozliczenia.centrum import contract
from rozliczenia.centrum.clock import Clock
from rozliczenia.centrum.pricing_journal import PricingJournal
from rozliczenia.centrum.run_logs import RunLogs
from rozliczenia.centrum.runs import EndedRun

PROGRESS_S: Final = 300.0
"""Odstęp między postępami jednej Wyceny w efenix na zegarze Centrum (#846: „najwyżej co 5 minut”)."""


@dataclass(frozen=True)
class _Watched:
    """Uruchomienie z komentarzem postępu i jego start na zegarze Centrum."""

    run_id: str
    since: float


class ProgressComment:
    """Komentarz postępu każdego Uruchomienia procesu ``process``, którego dziennik pisze ``journal`` (Wycena w efenix).

    Start, każde odświeżenie i koniec Uruchomienia (``run_ended``) biegną pod jedną blokadą, więc postęp, który zaczął
    się przed końcem, jest w kolejce przed Logami, a po końcu żaden już nie idzie.
    """

    def __init__(self, journal: PricingJournal, run_logs: RunLogs, *, process: contract.ProcessKey, clock: Clock) -> None:
        self._journal = journal
        self._run_logs = run_logs
        self._process = process
        self._clock = clock
        self._lock = threading.Lock()
        self._watched: _Watched | None = None

    def run_started(self, info: contract.RunInfo, started_at: datetime) -> None:
        """Start Uruchomienia z Centrum, po starcie jego dziennika (``PricingJournal.run_started``): komentarz postępu
        bez zleceń i budzik pierwszego odświeżenia."""

        if info.process != self._process:
            return
        with self._lock:
            self._watched = _Watched(info.id, self._clock())
            self._post_locked(self._watched)
        self._clock.after(PROGRESS_S, partial(self._refresh, info.id))

    def run_ended(self, run: EndedRun) -> None:
        """Działanie po wyniku (``runs.AfterRun``) przed Logami Uruchomienia: koniec odświeżania tego Uruchomienia."""

        with self._lock:
            if self._watched is not None and self._watched.run_id == run.info.id:
                self._watched = None

    def _refresh(self, run_id: str) -> None:
        """Budzik ``PROGRESS_S`` po starcie albo poprzednim odświeżeniu: postęp i następny budzik, dopóki Uruchomienie
        ``run_id`` trwa."""

        with self._lock:
            watched = self._watched
            if watched is None or watched.run_id != run_id:
                return
            self._post_locked(watched)
        self._clock.after(PROGRESS_S, partial(self._refresh, run_id))

    def _post_locked(self, watched: _Watched) -> None:
        progress = self._journal.progress(watched.run_id)
        if progress is not None:
            self._run_logs.progress(progress, elapsed_s=self._clock() - watched.since)
