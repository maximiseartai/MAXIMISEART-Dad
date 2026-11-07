"""Dziennik Wyceny w efenix (#845) po wyniku Uruchomienia.

Dziennik pisze i czyta ``logs_disk`` (``Journal``, ``LogsOnDisk.left_behind``); ten moduł decyduje, kiedy dziennik dostaje
wpis końca i kiedy znika po wyniku, a jaką wersję zastępczą komentarza Uruchomienia start Centrum z niego wysyła, decyduje
``run_comments`` (``comment_versions.close``).

Uruchomienie, które doszło do wyniku (``run_process`` wrócił, z wierszem Historii albo bez niego), dopisuje „koniec
Uruchomienia” z wynikiem (``JournalAtResult`` → ``Journal.end``): to pierwsze działanie po wyniku, więc wpis jest na
dysku, zanim powstaną Logi z wynikiem i zanim pójdą do Skrzynki. Dziennik sam mówi więc startowi Centrum, czy jego
Uruchomienie doszło do wyniku i do jakiego, a start nie zgaduje tego z Historii, którą pisze kto inny i którą start może
źle odczytać (#870, #871). Uruchomienie, którego pierwsza linia nie trafiła na dysk w żadnym zapisie, usuwa zamiast
wpisu końca dziennik, który mógł po nim zostać (``Journal.end``). Zgaśnięcie Centrum między rekordem metryk a wpisem
końca (milisekundy) zostawia dziennik bez wpisu końca, a start zamyka go jako Logi Urwanego Uruchomienia; Logi z wynikiem
jeszcze wtedy nie istnieją, więc niczego w Skrzynce nie zastępują.

Dziennik z pierwszą linią na dysku to też ślad komentarza postępu Wyceny w issue okresu (``pricing_progress``, #846),
który mówi, że Uruchomienie trwa, więc znika dopiero wtedy, gdy Kolejka wysyłki przyjęła wersję końcową tego komentarza
(#910). Na końcu Wyceny to Logi z wynikiem: działanie po wyniku za Logami Uruchomienia (``JournalAfterLogs``) usuwa
dziennik, gdy kolejka je przyjęła (``RunLogs.queued``). Dziennik, którego Logów kolejka nie przyjęła (Centrum zgasło po
wyniku, a przed nimi, Logi nie powstały albo kolejka odmówiła), zostaje do następnego startu, także gdy nie zapisał się
wpis końca, a ten start wysyła z niego wersję zastępczą (``run_comments.RunComments``). Wersja zastępcza ma stopień
wyższy od każdego postępu i niższy od Logów z wynikiem (``outbox.Rank``), więc zamienia postęp w podsumowanie także po
cofnięciu zegara komputera, a Logów z wynikiem, które kolejka mogła już przyjąć, nie zastępuje ani w kolejce, ani w
Skrzynce. Wpis końca, który się nie zapisał, zostawia dziennik bez niego: gdy kolejka nie przyjęła też Logów z wynikiem,
a pliku Logów nie ma, start zamknie go jako Logi Urwanego Uruchomienia.
"""

from __future__ import annotations

from dataclasses import dataclass

from rozliczenia.centrum.logs_disk import Journal
from rozliczenia.centrum.run_logs import RunLogs
from rozliczenia.centrum.runs import EndedRun


@dataclass(frozen=True)
class JournalAtResult:
    """Pierwsze działanie po wyniku (``runs.AfterRun``), przed Logami Uruchomienia: wpis końca z wynikiem ``run`` w
    dzienniku ``journal`` (``Journal.end``). Wpis końca, który się nie zapisał, zostawia dziennik ``JournalAfterLogs``:
    komentarz postępu nie zostaje bez wersji końcowej, gdy Centrum zgaśnie przed Logami."""

    journal: Journal

    def run_ended(self, run: EndedRun) -> None:
        self.journal.end(run.info.id, run.result)


@dataclass(frozen=True)
class JournalAfterLogs:
    """Działanie po wyniku za Logami Uruchomienia (``runs.AfterRun`` po ``RunLogs``): dziennik ``journal`` znika, gdy
    Kolejka wysyłki przyjęła Logi jego Uruchomienia (``RunLogs.queued``); inaczej zostaje, a następny start Centrum wyśle
    z niego wersję zastępczą (``run_comments.RunComments``)."""

    journal: Journal
    run_logs: RunLogs

    def run_ended(self, run: EndedRun) -> None:
        if self.run_logs.queued(run.info.id):
            self.journal.remove(run.info.id)
