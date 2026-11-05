"""Komentarz postępu Wyceny w efenix w issue Logów okresu (#846): w trakcie Wyceny Maks widzi, jak idzie.

Wycena w efenix trwa u taty do półtorej godziny, a Logi Uruchomienia powstają dopiero na jej końcu. Przy starcie Wyceny
(``run_started``) Centrum zakłada jej komentarz Uruchomienia w issue Logów okresu, a potem co ``PROGRESS_S`` na zegarze
Centrum, nigdy częściej, odświeża go stanem dziennika Wyceny (``PricingJournal.progress``): zlecenia skończone z
wszystkich, wyniki do tej pory, ostatnie skończone zlecenie, zlecenie w trakcie i czas od startu. Dziennik podaje tylko
wpisy, które już ma na dysku, a bez swojej pierwszej linii na dysku nic, więc postęp nigdy go nie wyprzedza: każdy
komentarz postępu ma dziennik. Na końcu Wyceny komentarz staje się podsumowaniem z jej Logów z wynikiem, a Wycenę, którą
przerwało zgaśnięcie Centrum przed wpisem końca dziennika, następny start Centrum zamyka Logami Urwanego Uruchomienia
(``pricing_journal.InterruptedPricings``), które też zamieniają komentarz w podsumowanie. Wycena, której Logi z wynikiem
nie doszły do kolejki po wpisie końca (Centrum zgasło między wpisem końca a ich przyjęciem, wpis końca się nie zapisał,
Logi nie powstały albo kolejka ich nie przyjęła), zostawia komentarz postępu bez wersji końcowej, bo start Centrum za
Wycenę z wynikiem niczego nie wysyła, żeby nie zastąpić Logów z wynikiem, które kolejka już przyjęła (#871); to okno
zamyka #910. Wycena, której dziennika nie da się zapisać, postępu nie ma, tylko podsumowanie na końcu.

Postęp to starsza wersja tej samej wysyłki co Logi tego Uruchomienia (``run_logs.progress_post``: ten sam ``run_id`` i
etykieta), więc kolejka zmienia ten sam komentarz, a bez sieci najnowszy postęp w kolejce zastępuje starszy (``outbox``).
Koniec postępu wyznacza ``RunLogs``: od działań po wyniku tego Uruchomienia (``RunLogs.run_ended``) nie przyjmuje jego
postępu, więc żaden nie przychodzi po Logach, które zamieniają komentarz w podsumowanie z odnośnikiem do Archiwum Logów
okresu (postęp nowszy od Logów zastąpiłby je w kolejce), a pierwsze odświeżenie po końcu kończy budzik.

Postęp jest dla Maksa, a nie warunkiem pracy taty: wysyłkę, której kolejka nie przyjęła, ``Outbox.post`` zapisuje w
dzienniku Centrum, a Wycena biegnie dalej.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import partial
from typing import Final

from rozliczenia.centrum import contract
from rozliczenia.centrum.clock import Clock
from rozliczenia.centrum.pricing_journal import PricingJournal
from rozliczenia.centrum.run_logs import RunLogs

PROGRESS_S: Final = 300.0
"""Odstęp między postępami jednej Wyceny w efenix na zegarze Centrum (#846: „najwyżej co 5 minut”)."""


@dataclass(frozen=True)
class _Watched:
    """Uruchomienie z komentarzem postępu i jego start na zegarze Centrum."""

    run_id: str
    since: float


class ProgressComment:
    """Komentarz postępu każdego Uruchomienia, którego dziennik pisze ``journal`` (Wycena w efenix)."""

    def __init__(self, journal: PricingJournal, run_logs: RunLogs, *, clock: Clock) -> None:
        self._journal = journal
        self._run_logs = run_logs
        self._clock = clock
        self._watched: _Watched | None = None

    def run_started(self, info: contract.RunInfo, started_at: datetime) -> None:
        """Start Uruchomienia z Centrum, po starcie jego dziennika (``PricingJournal.run_started``): komentarz postępu
        bez zleceń i budzik pierwszego odświeżenia."""

        if info.process != self._journal.process:
            return
        watched = self._watched = _Watched(info.id, self._clock())
        self._post(watched)
        self._clock.after(PROGRESS_S, partial(self._refresh, info.id))

    def _refresh(self, run_id: str) -> None:
        """Budzik ``PROGRESS_S`` po starcie albo poprzednim odświeżeniu: postęp i następny budzik, dopóki Uruchomienie
        ``run_id`` nie doszło do działań po wyniku i nie zaczęło się następne."""

        watched = self._watched
        if watched is None or watched.run_id != run_id or not self._post(watched):
            return
        self._clock.after(PROGRESS_S, partial(self._refresh, run_id))

    def _post(self, watched: _Watched) -> bool:
        """Postęp ``watched`` z dziennika; ``False``: Uruchomienie doszło do działań po wyniku, więc postęp się skończył."""

        progress = self._journal.progress(watched.run_id)
        return self._run_logs.progress(watched.run_id, progress, elapsed_s=self._clock() - watched.since)
