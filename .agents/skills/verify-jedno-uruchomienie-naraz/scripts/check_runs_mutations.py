"""Show that explore_runs.py fails on broken variants of RunHost, Shutdown and PreparedRun.conduct.

Each mutation runs on its own copy of the checkout (``tools/mutacje.py``) and must
end the checker's report with the expected line. A mutation whose anchor text is no
longer in its file is reported as NIEAKTUALNA: update it to the new code.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))

from mutacje import Edit, Mutation, check_all

RUNS = Path("src/rozliczenia/centrum/runs.py")
SHUTDOWN = Path("src/rozliczenia/centrum/shutdown.py")
PROCESS_KIND = Path("src/rozliczenia/centrum/process_kind.py")
EXPLORER = ".agents/skills/verify-jedno-uruchomienie-naraz/scripts/explore_runs.py"
NEW = "URUCHOMIENIA: NOWE NARUSZENIE"

# Each mutation runs only the explorer scope that catches it: every scope for every mutation costs minutes in CI.
MUTATIONS = (
    Mutation(
        "sprawdzenie i zajęcie w RunHost.start pod dwiema blokadami",
        (Edit(RUNS, "            run = Run(self, prepared, self._stops, self._threads)\n", "        with self._lock:\n            run = Run(self, prepared, self._stops, self._threads)\n"),),
        (EXPLORER, "--scope", "dwie-karty"),
        "dwie karty „Uruchom” prowadzą dwa Uruchomienia naraz na tym samym Folderze okresu",
        NEW,
    ),
    Mutation(
        "odmowa zamknięcia pomija Uruchomienie czekające na Decyzję",
        (Edit(RUNS, "        if run is None or run.ended:\n", "        if run is None or run.ended or run.awaiting_decision:\n"),),
        (EXPLORER, "--scope", "zamknij-w-trakcie"),
        "Centrum zamyka się, gdy tata jeszcze nie odpowiedział na Decyzję",
        NEW,
    ),
    Mutation(
        "ended ustawione na początku Run.work",
        (Edit(RUNS, "        prepared = self._prepared\n        core: Outcome[Shown[Any]] | None = None\n", "        prepared = self._prepared\n        self.ended = True\n        core: Outcome[Shown[Any]] | None = None\n"),),
        (EXPLORER, "--scope", "zamknij-w-trakcie"),
        "Centrum zamyka się w trakcie silnika i kolejne „Uruchom” startuje drugie Uruchomienie",
        NEW,
    ),
    Mutation(
        "działania po wyniku po końcu Uruchomienia",
        (
            Edit(
                RUNS,
                "        self._host.after(ended)\n        self._host.finished(ended)\n",
                "        self._host.finished(ended)\n",
            ),
            Edit(RUNS, "        )\n\n    def _ended(", "        )\n        self._host.after(ended)\n\n    def _ended("),
        ),
        (EXPLORER, "--scope", "zamknij-w-trakcie"),
        "Centrum zamyka się po wyniku, zanim Kontrola ilości trafi do pliku kolejki",
        NEW,
    ),
    Mutation(
        "koniec Uruchomienia przed wynikiem na karcie",
        (
            Edit(
                RUNS,
                "        with self._lock:\n            self._publish_locked(result)\n            run.ended = True\n",
                "        with self._lock:\n            run.ended = True\n        self.publish(run, result)\n",
            ),
        ),
        (EXPLORER, "--scope", "dwie-karty"),
        "druga karta startuje między końcem a wynikiem pierwszego Uruchomienia i jego wynik nie trafia na kartę",
        NEW,
    ),
    Mutation(
        "start czyści wynik poprzedniego Uruchomienia",
        (Edit(RUNS, "            self._events = self._events[-1:]\n", "            self._events = []\n"),),
        (EXPLORER, "--scope", "dwie-karty"),
        "druga karta startuje, zanim karta odczyta wynik pierwszego Uruchomienia, i wynik znika ze strumienia",
        NEW,
    ),
    Mutation(
        "Shutdown.request bez odmowy",
        (Edit(SHUTDOWN, "        message = self._blocker()\n", "        message = None\n"),),
        (EXPLORER, "--scope", "zamknij-w-trakcie"),
        "„Zamknij” zamyka Centrum w trakcie każdego Uruchomienia",
        NEW,
    ),
    Mutation(
        "zamknięcie przyjęte bez odcięcia nowych startów",
        (Edit(RUNS, "                self._closing = True\n", "                pass\n"),),
        (EXPLORER, "--scope", "zamknij-w-trakcie"),
        "„Uruchom” albo „Zaktualizuj narzędzie” tuż po „Zamknij” startuje wątek, który koniec serwera zabija",
        NEW,
    ),
    Mutation(
        "begin_update bez odmowy po przyjętym zamknięciu",
        (Edit(RUNS, "            if self._closing:\n                raise contract.Refusal(409, _CLOSING.format(then=\"zaktualizuj narzędzie\"))\n", ""),),
        (EXPLORER, "--scope", "aktualizacja"),
        "aktualizacja startuje po „Zamknij” i ginie w trakcie Gita albo pip",
        NEW,
    ),
    Mutation(
        "begin_update bez sprawdzenia trwającego Uruchomienia",
        (Edit(RUNS, "            busy = self._busy_locked(\"zaktualizuj narzędzie\")\n", "            busy = None\n"),),
        (EXPLORER, "--scope", "aktualizacja"),
        "aktualizacja przesuwa klon narzędzia pod pracującym silnikiem",
        NEW,
    ),
    Mutation(
        "RunHost.start bez odmowy w trakcie aktualizacji",
        (Edit(RUNS, "            if self._updating:\n                raise contract.Refusal(409, _UPDATING.format(then=\"uruchom proces\"))\n", ""),),
        (EXPLORER, "--scope", "aktualizacja"),
        "Uruchomienie startuje, gdy aktualizacja zmienia kod i biblioteki narzędzia",
        NEW,
    ),
    Mutation(
        "begin_restore bez sprawdzenia trwającego Uruchomienia",
        (Edit(RUNS, "            busy = self._busy_locked(_RESTORE)\n", "            busy = None\n"),),
        (EXPLORER, "--scope", "przywracanie"),
        "przywrócenie Kopii podmienia INTERMAX pod pracującym Uporządkowaniem INTERMAX",
        NEW,
    ),
    Mutation(
        "RunHost.start bez odmowy w trakcie przywracania",
        (Edit(RUNS, "            if self._restoring:\n                raise contract.Refusal(409, _RESTORING.format(then=\"uruchom proces\"))\n", ""),),
        (EXPLORER, "--scope", "przywracanie"),
        "Uporządkowanie INTERMAX startuje, gdy przywrócenie podmienia INTERMAX",
        NEW,
    ),
    Mutation(
        "zajęte miejsce nie widzi przywracania",
        (Edit(RUNS, "        if self._restoring:\n            return _RESTORING.format(then=then)\n", ""),),
        (EXPLORER, "--scope", "przywracanie"),
        "dwie karty „Przywróć tę kopię” podmieniają INTERMAX naraz",
        NEW,
    ),
    Mutation(
        "RLock zamiast Lock w RunHost",
        (Edit(RUNS, "        self._lock = threads.Lock()\n", "        self._lock = threads.RLock()\n"),),
        (EXPLORER, "--scope", "zamknij-w-trakcie"),
        "model nie zna tej blokady, więc nie może nic orzec",
        "URUCHOMIENIA: LUKA MODELU",
    ),
    Mutation(
        "blokada RunHost z threading obok szwu threads",
        (Edit(RUNS, "        self._lock = threads.Lock()\n", "        self._lock = threading.Lock()\n"),),
        (EXPLORER, "--scope", "zamknij-w-trakcie"),
        "model nie widzi blokady, której RunHost nie wziął ze szwu, więc nie może nic orzec",
        "URUCHOMIENIA: LUKA MODELU",
    ),
    Mutation(
        "wątek Uruchomienia z threading obok szwu threads",
        (Edit(RUNS, "        self._threads.Thread(target=run.work,", "        threading.Thread(target=run.work,"),),
        (EXPLORER, "--scope", "zamknij-w-trakcie"),
        "Uruchomienie biegnie w wątku, którego model nie prowadzi, więc nie może nic orzec",
        "URUCHOMIENIA: LUKA MODELU",
    ),
    Mutation(
        "PreparedRun.conduct czeka na prawdziwy Event przed silnikiem",
        (
            Edit(
                PROCESS_KIND,
                "        return self.engine(\n",
                "        __import__('threading').Event().wait()\n        return self.engine(\n",
            ),
        ),
        (EXPLORER, "--scope", "zamknij-w-trakcie"),
        "Uruchomienie wisi na zawsze, a Centrum nie da się zamknąć: eksplorator prowadzi prawdziwe conduct (przegląd #1127)",
        "URUCHOMIENIA: LUKA MODELU",
    ),
    Mutation(
        "Event zamknięcia użyty już w Shutdown.__init__, w wątku sprawdzającego",
        (Edit(SHUTDOWN, "        self._requested = threads.Event()\n", "        self._requested = threads.Event()\n        self._requested.clear()\n"),),
        (EXPLORER, "--scope", "zamknij-w-trakcie"),
        "eksplorator kończył się kodem 0 bez werdyktu, nie sprawdziwszy żadnego harmonogramu (przegląd #1127)",
        "URUCHOMIENIA: LUKA MODELU",
    ),
    Mutation(
        "prawdziwa blokada spoza threading w RunHost.start",
        (
            Edit(RUNS, "import uuid\n", "import uuid\n\n_REAL = __import__('_thread').allocate_lock()\n"),
            Edit(
                RUNS,
                "    def start(self, prepared: PreparedRun[Any, Any]) -> contract.RunView:\n        with self._lock:\n",
                "    def start(self, prepared: PreparedRun[Any, Any]) -> contract.RunView:\n        with _REAL, self._lock:\n",
            ),
        ),
        (EXPLORER, "--scope", "dwie-karty"),
        "druga karta „Uruchom” czeka na blokadę, której model nie widzi, więc sprawdzenie wisiałoby do limitu pytest",
        "URUCHOMIENIA: LUKA MODELU",
    ),
)


if __name__ == "__main__":
    raise SystemExit(check_all(MUTATIONS))
