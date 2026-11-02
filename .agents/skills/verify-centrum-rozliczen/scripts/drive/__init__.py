"""One module per verified Centrum feature (``features/<feature>.md``), driven by ``drive_centrum.py``.

The constants here are shared with ``run_centrum_verification.py``, which imports them before it checks that
Playwright is installed, so this module imports nothing.
"""

# aktualizacja moves the run's tool clone right after Konfiguracja shows it. Przygotowanie pliku zbiorczego
# appends to the metrics files that Metryki counts, so it runs after Metryki; blad-odczytu runs between them, before
# the week's first Uruchomienie; uzupelnienie shows what Dad fills in its Plik zbiorczy and restores the file, and
# Przebieg rozliczeń continues Dad's path from that Plik zbiorczy, and kontrola-ilosci sends its Kontrola ilości after two restarts of Centrum; Diagnoza stops Uruchomienia of an empty Folder okresu after Dad's week, and aktualnosc-i-onedrive diagnoses one more such stop with the
# scripted GitHub and OneDrive; zgloszenie sends one such stop to the file skrzynka Zgłoszeń, and
# uwaga-taty needs the skrzynka queue that kontrola-ilosci emptied; logi-uruchomienia matches every Uruchomienie
# of the week with its file of Logi; powiadomienia closes an Uwaga taty and that Zgłoszenie there; pomiar-u-taty
# clicks through the pages with the files
# of Dad's whole week; uporzadkowanie-intermax points the Rejestr zleceń to its INTERMAX files and back, so it runs after
# every feature that reads the Rejestr zleceń, and kopie-intermax after it, because uporzadkowanie-intermax counts the
# Kopie in their folder; wycena-w-efenix puts its own Folder okresu in the folder okresów and removes it again, and adds
# a file of Logi, so it runs after every feature that counts periods or Logi; start-i-zamykanie closes Centrum, so it
# stays last.
# CI drives `all` in consecutive parts of this order (`ci-czesci` in SKILL.md), each part on a fresh fixture and
# Centrum, so a feature also starts right after the fixture or after any earlier feature of the order.
FEATURES = (
    "ustawienia",
    "tablica-okresow",
    "uklad-folderow-taty",
    "konfiguracja",
    "aktualizacja",
    "metryki",
    "blad-odczytu",
    "przygotowanie-pliku-zbiorczego",
    "uzupelnienie",
    "przebieg-rozliczen",
    "kontrola-ilosci",
    "diagnoza",
    "aktualnosc-i-onedrive",
    "zgloszenie",
    "uwaga-taty",
    "logi-uruchomienia",
    "karta-z-logow",
    "powiadomienia",
    "pomiar-u-taty",
    "uporzadkowanie-intermax",
    "kopie-intermax",
    "wycena-w-efenix",
    "start-i-zamykanie",
)
# Run only when named, never in `all`: the measurement takes minutes, needs a quiet CPU, and its own fixture variant.
EXPLICIT_FEATURES = ("wydajnosc",)
# wydajnosc: repetitions of every scenario per CPU profile unless `--powtorzenia` says otherwise; a baseline
# comes only from a run with this many (features/wydajnosc.md).
DEFAULT_REPEATS = 5
