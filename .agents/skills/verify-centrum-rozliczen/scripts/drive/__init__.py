"""One module per verified Centrum feature (``features/<feature>.md``), driven by ``drive_centrum.py``.

``FEATURES`` is the one register of the features: a new one is its entry here, its module and its feature file.
``run_centrum_verification.py`` reads it before it checks that Playwright is installed, so this module imports only
the standard library.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple


class Feature(NamedTuple):
    """A feature that ``drive/<name with _ for ->.py`` drives with ``drive(run, page)``.

    ``screenshots`` are every screenshot it takes (``Run.capture`` refuses another), so a run of the feature misses
    none of them. ``needs`` are the features whose state it finds: ``drive_centrum.py`` drives each one first unless the
    drive already did, and each stands before it in ``FEATURES``. ``evidence`` is more it leaves in the evidence,
    ``fixture`` the variant of the fixture it needs. A ``measurement`` runs only when named, alone on the machine.
    """

    name: str
    screenshots: tuple[str, ...]
    needs: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    fixture: str | None = None
    measurement: bool = False

    @property
    def module(self) -> str:
        return "drive." + self.name.replace("-", "_")


# The order of `all`. CI drives `all` in consecutive parts of it (`ci-czesci` in SKILL.md), each part on a fresh
# fixture and Centrum, so a feature also starts right after the fixture or after any earlier feature of the order.
FEATURES = (
    # Checks the files unset, so it runs before `ustawienia` sets them; it sets nothing itself.
    Feature(
        "okno-ustawien",
        (
            "300-okno-stopka-menu",
            "301-okno-szerokie",
            "302-okno-foldery",
            "303-okno-z-raportow",
            "304-okno-waskie",
            "305-okno-waskie-wybor",
        ),
    ),
    Feature(
        "ustawienia",
        (
            "01-ustawienia-pusty-stan",
            "19-ustawienia-jedno-okno-wyboru",
            "02-ustawienia-folder-okresow",
            "03-ustawienia-rejestr-zlecen",
            "18-ustawienia-braki-do-startu",
            "04-ustawienia-brak-rejestru",
            "275-ustawienia-nieczytelny-plik",
            "276-ustawienia-niedostepna-sciezka",
            "05-ustawienia-motyw-jasny",
            "306-ustawienia-zapisano-cofnij",
            "307-ustawienia-zapisano-waskie",
            "315-ustawienia-blad-w-oknie",
            "341-ustawienia-blad-po-zamknieciu",
            "308-ustawienia-historia",
            "309-ustawienia-historia-waska",
            "340-ustawienia-historia-wydanie",
            "310-ustawienia-odmowa-przy-polu",
            "311-ustawienia-odmowa-waska",
            "312-ustawienia-zle-pole",
            "313-ustawienia-zly-plik",
            "314-ustawienia-historia-bez-cofniecia",
            "330-ustawienia-autostart",
            "331-ustawienia-autostart-waskie",
            "332-ustawienia-autostart-spoza",
            "333-ustawienia-autostart-bez-windows",
            "319-ustawienia-zle-stare-haslo",
            "316-ustawienia-haslo-przyjete",
            "317-ustawienia-historia-hasla",
            "318-ustawienia-haslo-waskie",
        ),
    ),
    Feature(
        "reguly-ilosci",
        (
            "350-reguly-ilosci-szerokie",
            "351-reguly-ilosci-bez-wzorca",
            "352-urzadzenia-szerokie",
            "353-reguly-ilosci-waskie",
            "354-urzadzenia-waskie",
        ),
    ),
    Feature(
        "tablica-okresow",
        (
            "06-tablica-okresow",
            "07-tablica-otwieranie",
            "156-tablica-brakujacy-plik",
            "157-tablica-brakujacy-plik-dotyk",
            "1a-tablica-podwojne-klikniecie",
            "08-tablica-po-zmianie-na-dysku",
            "17-tablica-odczyt-nieudany",
            "09-tablica-podpowiedz",
        ),
    ),
    # Adds period folders around the fixture's "today" and removes them again.
    Feature(
        "tablica-skrocona",
        (
            "297-tablica-skrocona",
            "298-tablica-rozwinieta",
            "299-tablica-piec-zaczetych",
        ),
    ),
    Feature(
        "uklad-folderow-taty",
        (
            "102-uklad-taty-foldery",
            "15-uklad-taty-tablica",
            "16-uklad-taty-otwieranie",
        ),
    ),
    Feature(
        "konfiguracja",
        (
            "10-konfiguracja-gotowa",
            "11-konfiguracja-tylko-do-odczytu",
            "12-konfiguracja-wzorzec-otwarty",
            "12a-konfiguracja-wzorzec-niedostepny",
            "12b-konfiguracja-wzorzec-dostepny",
            "13-konfiguracja-brak-wzorca",
            "14-konfiguracja-nieczytelna-konfiguracja-wykonawcow",
            "14a-konfiguracja-niedostepna-konfiguracja-wykonawcow",
        ),
    ),
    # Moves the run's tool clone right after Konfiguracja shows it.
    Feature(
        "aktualizacja",
        (
            "93-aktualizacja-jest-nowsza",
            "115-aktualizacja-brak-sieci",
            "116-aktualizacja-brak-sieci-zgloszenie",
            "117-aktualizacja-brak-sieci-bez-przycisku",
            "94-aktualizacja-postep",
            "100-aktualizacja-ponowny-start",
            "101-aktualizacja-zaktualizowano",
            "96-aktualizacja-najnowsza",
            "130-aktualizacja-instalowanie",
            "131-aktualizacja-instalacja-nieudana",
            "135-aktualizacja-nie-wystartowala-ponowny-start",
            "136-aktualizacja-nie-wystartowala",
            "137-aktualizacja-nie-wystartowala-konfiguracja",
            "132-aktualizacja-start-ze-skrotu",
            "138-aktualizacja-ok-przy-starej-wersji",
        ),
    ),
    Feature(
        "metryki",
        (
            "20-metryki-karty-okresow",
            "2c-metryki-karty-okresow-bez-odczytu",
            "21-metryki-wykres",
            "2a-metryki-wykres-waski",
            "28-metryki-wykres-szczegoly-ciemny",
            "29-metryki-wykres-szczegoly-jasny",
            "22-metryki-tabela-etapow",
            "23-metryki-za-malo-obserwacji",
            "24-metryki-historia",
            "25-metryki-historia-filtry",
            "2b-metryki-rodzaj-zatrzymania",
            "26-metryki-nowy-rekord-spoza-centrum",
            "27-metryki-pusty-stan",
        ),
    ),
    # Runs before the week's first Uruchomienie.
    Feature(
        "blad-odczytu",
        (
            "139-blad-odczytu-ustawienia",
            "142-blad-odczytu-tablica",
            "153-blad-odczytu-okresy-trzy-odczyty",
            "154-blad-odczytu-okresy-jednym-kliknieciem",
            "143-blad-odczytu-uruchomienia",
            "144-blad-odczytu-historia",
            "145-blad-odczytu-metryki",
            "146-blad-odczytu-konfiguracja",
            "141-blad-odczytu-ponowny-odczyt",
            "148b-blad-odczytu-aktualizacja",
            "147-blad-odczytu-powiadomienia",
            "148-blad-odczytu-uwaga",
            "148c-blad-odczytu-uzupelnienie",
            "148e-blad-odczytu-uzupelnienie-rodzaj",
            "148d-blad-odczytu-strumien",
        ),
    ),
    # Appends to the metrics files that Metryki counts, so it runs after Metryki.
    Feature(
        "przygotowanie-pliku-zbiorczego",
        (
            "30-przygotowanie-nowe-uruchomienie",
            "3c-przygotowanie-rejestr-otwarty-w-excelu",
            "3d-przygotowanie-rejestr-zamkniety",
            "31-przygotowanie-podglad",
            "39-przygotowanie-bez-podgladu",
            "32-przygotowanie-potwierdzenie",
            "33-przygotowanie-decyzja",
            "149-przygotowanie-znak-decyzji",
            "34-przygotowanie-zatrzymanie",
            "3a-przygotowanie-podwojne-klikniecie",
            "35-przygotowanie-zapisane",
            "3b-przygotowanie-otwieranie",
            "36-przygotowanie-status-okresu",
            "37-przygotowanie-nienadpisywanie",
            "38-przygotowanie-historia",
        ),
    ),
    # Shows what Dad fills in the Plik zbiorczy of Przygotowanie and restores the file.
    Feature(
        "uzupelnienie",
        (
            "250-uzupelnienie-wynik",
            "255-uzupelnienie-wynik-na-zywo",
            "256-uzupelnienie-wynik-po-przebiegu",
            "257-uzupelnienie-wynik-bez-odpowiedzi",
            "258-uzupelnienie-wynik-bez-centrum",
            "252-uzupelnienie-wynik-po-starcie",
            "251-uzupelnienie-tablica",
            "220-uzupelnienie-karta",
            "221-uzupelnienie-podsumowanie",
            "222-uzupelnienie-po-wpisie",
            "225-uzupelnienie-bez-reguly-otwarty-opis",
            "225-uzupelnienie-bez-reguly-1280px",
            "225-uzupelnienie-bez-reguly-1536px",
            "225-uzupelnienie-bez-reguly-jasny",
            "225-uzupelnienie-bez-reguly-przewiniete",
            "226-uzupelnienie-z-opisu-otwarty-opis",
            "226-uzupelnienie-z-opisu-1280px",
            "226-uzupelnienie-z-opisu-1536px",
            "226-uzupelnienie-z-opisu-jasny",
            "226-uzupelnienie-z-opisu-przewiniete",
            "227-uzupelnienie-tabela-na-zywo",
            "223-uzupelnienie-blokada-excela",
            "229-uzupelnienie-odczyt-nieudany",
            "215-uzupelnienie-gotowe",
            "216-uzupelnienie-gotowe-potwierdzenie",
            "218-uzupelnienie-gotowe-po-podgladzie",
            "217-uzupelnienie-gotowe-bez-odczytu",
            "253-uzupelnienie-po-przebiegu",
            "253-uzupelnienie-po-przebiegu-bez-reguly",
            "253-uzupelnienie-po-przebiegu-bez-reguly-jasny",
            "224-uzupelnienie-bez-pliku",
            "254-uzupelnienie-gotowe-bez-okresu",
        ),
        needs=("przygotowanie-pliku-zbiorczego",),
    ),
    # Continues Dad's path from that Plik zbiorczy.
    Feature(
        "przebieg-rozliczen",
        (
            "40-przebieg-nowe-uruchomienie",
            "4a-przebieg-plik-zbiorczy-otwarty-w-excelu",
            "4b-przebieg-plik-zbiorczy-zamkniety",
            "4c-przebieg-wzorzec-otwarty-w-excelu",
            "4d-przebieg-nowe-uruchomienie-bez-blokady",
            "4e-przebieg-krok-uzupelnienie",
            "4f-przebieg-krok-wycena",
            "4g-przebieg-krok-rozliczenia",
            "41-przebieg-podglad",
            "42-przebieg-potwierdzenie",
            "43-przebieg-na-zywo",
            "155-przebieg-znak-uruchomienia",
            "44-przebieg-zapisane",
            "49-przebieg-otwieranie",
            "48-przebieg-odczyt-po-uruchomieniu",
            "45-przebieg-status-okresu",
            "46-przebieg-nienadpisywanie",
            "47-przebieg-wymaga-sprawdzenia",
            "47b-przebieg-nieznany-wykonawca",
        ),
        needs=("przygotowanie-pliku-zbiorczego",),
    ),
    # Sends the Kontrola ilości of Przebieg rozliczeń after two restarts of Centrum.
    Feature(
        "kontrola-ilosci",
        (
            "150-kontrola-w-kolejce",
            "151-kontrola-bez-sieci-po-starcie",
            "152-kontrola-start-bez-czekania",
        ),
        needs=("przebieg-rozliczen",),
    ),
    # Stops Uruchomienia of an empty Folder okresu after Dad's week.
    Feature(
        "diagnoza",
        (
            "50-diagnoza-dla-taty",
            "51-diagnoza-powtorka",
            "52-diagnoza-wyjasnienie",
            "53-diagnoza-sprawdzono",
            "54-diagnoza-inny-komunikat",
            "55-diagnoza-do-maksa",
            "56-diagnoza-do-maksa-wyjasnienie",
            "57-diagnoza-bez-przyczyny",
            "58-diagnoza-nieoczekiwany-wyjatek",
            "59-diagnoza-nieoczekiwany-wyjatek-zgloszenie",
            "59b-diagnoza-klucz-odrzucony",
            "59c-diagnoza-lista-wykonawcow",
        ),
    ),
    # Diagnoses one more such stop with the scripted GitHub and OneDrive.
    Feature(
        "aktualnosc-i-onedrive",
        (
            "76-aktualnosc-nowsza-wersja",
            "77-aktualnosc-brak-sieci",
            "78-onedrive-tylko-w-chmurze",
            "81-aktualnosc-propozycja",
            "140-aktualnosc-aktualizacja-w-trakcie",
            "79-aktualnosc-i-onedrive-przeszly",
        ),
    ),
    # Sends one such stop to the file skrzynka Zgłoszeń.
    Feature(
        "zgloszenie",
        (
            "60-zgloszenie-podglad",
            "61-zgloszenie-bez-klucza",
            "61b-zgloszenie-bez-klucza-powiadomienia",
            "62-zgloszenie-konfiguracja-brak-klucza",
            "63-zgloszenie-konfiguracja-gotowe",
            "63b-zgloszenie-konfiguracja-odrzucony",
            "64-zgloszenie-wyslane",
            "65-zgloszenie-po-odswiezeniu",
            "66-zgloszenie-kolejne-uruchomienie",
            "68-zgloszenie-zamkniete-przed-diagnoza",
            "69-zgloszenie-zamkniete-po-diagnozie",
            "70-zgloszenie-nowe-z-odnosnikiem",
            "71-zgloszenie-inny-problem",
            "72-zgloszenie-bez-sieci",
            "73-zgloszenie-bez-sieci-wyslane",
            "74-zgloszenie-odrzucone",
            "74b-zgloszenie-odrzucone-powiadomienia",
            "75-zgloszenie-odrzucone-po-starcie",
        ),
    ),
    # Finds the skrzynka queue as kontrola-ilosci leaves it: empty.
    Feature(
        "uwaga-taty",
        (
            "170-uwaga-ikona-w-naglowku",
            "170b-uwaga-ikona-zblizenie",
            "171-uwaga-puste-okno",
            "172-uwaga-dlugi-tekst",
            "178-uwaga-pelne-okno",
            "177-uwaga-niskie-okno",
            "177b-uwaga-niskie-okno-drugi-motyw",
            "179-uwaga-pelne-okno-lista",
            "173-uwaga-wypelniona",
            "173b-uwaga-bez-wybranego-uruchomienia",
            "174-uwaga-token-nie-dziala",
            "175-uwaga-wysylanie",
            "176-uwaga-wyslana",
            "190-uwaga-przycisk-na-karcie",
            "191-uwaga-z-karty",
            "192-uwaga-przypieta",
            "193-uwaga-ogolna-z-karty",
            "194-uwaga-historia",
            "195-uwaga-z-historii",
            "196-uwaga-z-historii-laptop",
            "197-uwaga-spoza-historii",
            "198-uwaga-logi-odrzucone",
            "174b-uwaga-odrzucona",
            "174c-uwaga-odrzucona-powiadomienia",
            "199-uwaga-logi-dotarly",
            "200-uwaga-logi-nie-powstaly",
        ),
    ),
    # Matches every Uruchomienie of the week with its file of Logi.
    Feature(
        "logi-uruchomienia",
        (
            "160-logi-podglad",
            "161-logi-zatrzymanie",
            "162-logi-w-skrzynce",
        ),
        needs=("przebieg-rozliczen",),
    ),
    Feature(
        "karta-z-logow",
        (
            "210-karta-przed-zamknieciem",
            "211-karta-po-zamknieciu",
            "211b-karta-bez-szczegolow",
            "212-karta-przerwana",
            "213-karta-z-historii",
            "214-karta-bez-logow",
        ),
    ),
    # Closes an Uwaga taty and a Zgłoszenie in the skrzynka.
    Feature(
        "powiadomienia",
        (
            "180-powiadomienia-dzwonek",
            "181-powiadomienia-kropka",
            "181b-powiadomienia-kropka-zblizenie",
            "181c-powiadomienia-oznaczenie-bez-odpowiedzi",
            "182-powiadomienia-widok",
            "183-powiadomienia-widok-drugi-motyw",
            "184-powiadomienia-brak-sieci",
            "185-powiadomienia-nowa-wersja",
            "186-powiadomienia-nowa-wersja-drugi-motyw",
            "187-powiadomienia-aktualizacja",
            "188-powiadomienia-wydanie-aktualne",
            "189-powiadomienia-wydania-brak-sieci",
            "201-powiadomienia-plik-niedostepny",
            "202-powiadomienia-plik-zapisany",
        ),
        needs=("zgloszenie", "uwaga-taty"),
    ),
    # Clicks through the pages with the files of Dad's whole week.
    Feature(
        "pomiar-u-taty",
        ("80-pomiar-bez-sladu",),
    ),
    # Points the Rejestr zleceń to its INTERMAX files and back, after every feature that reads the Rejestr zleceń.
    Feature(
        "uporzadkowanie-intermax",
        (
            "230-intermax-bez-intermax",
            "231-intermax-karta",
            "232-intermax-otwarty",
            "233-intermax-wynik",
            "238-intermax-dni-po-uporzadkowaniu",
            "234-intermax-zatrzymanie-dla-taty",
            "235-intermax-do-maksa",
            "236-intermax-historia",
            "237-intermax-metryki",
        ),
    ),
    # Counts the Kopie INTERMAX that uporzadkowanie-intermax left in their folder.
    Feature(
        "kopie-intermax",
        (
            "240-kopie-intermax-lista",
            "241-kopie-intermax-ostrzezenie",
            "242-kopie-intermax-otwarty",
            "243-kopie-intermax-przywrocona",
        ),
    ),
    # Points the Rejestr zleceń to its own INTERMAX and back, and counts only the Logi of Wpisanie raportów.
    Feature(
        "wpisanie-raportow",
        (
            "280-raporty-przycisk",
            "285-raporty-blokada",
            "281-raporty-dzien-z-problemami",
            "282-raporty-zostaw-moja",
            "283-raporty-dzien-bez-problemow",
            "284-raporty-waski-ekran",
            "287-raporty-w-czasie-innego",
            "293-raporty-mapa-bez-popovera",
            "288-raporty-mapa-jasna",
            "289-raporty-mapa-ciemna",
            "290-raporty-kalendarz",
            "291-raporty-status",
            "292-raporty-mapa-waska",
            "294-raporty-przypomnienia",
            "295-raporty-przypomnienie-i-przeniesienie",
            "296-raporty-dopisane",
            "286-raporty-zatrzymanie",
        ),
    ),
    # Puts its own Folder okresu in the folder okresów and removes it again, and adds a file of Logi, so it runs
    # after every feature that counts periods or Logi.
    Feature(
        "wycena-w-efenix",
        (
            "260-efenix-karta-startu",
            "261-efenix-logowanie",
            "262-efenix-postep",
            "263-efenix-karta",
            "264-efenix-dzwonek",
            "265-efenix-powiadomienie",
            "266-efenix-powiadomienie-karta",
            "267-efenix-z-zapisem-potwierdzenie",
            "268-efenix-z-zapisem-karta",
            "269-efenix-z-zapisem-powiadomienie",
            "270-efenix-uruchom-ponownie",
        ),
    ),
    # Closes Centrum, so it stays last; numbered 9x, so its screenshots are always the last ones.
    Feature(
        "start-i-zamykanie",
        (
            "90-start-i-zamykanie-karty-w-tle",
            "91-start-i-zamykanie-potwierdzenie",
            "92-start-i-zamykanie-zamkniete",
        ),
    ),
    # Only when named, never in `all`: the measurement takes minutes, needs a quiet CPU and its own fixture variant.
    Feature(
        "wydajnosc",
        (
            "84-wydajnosc-okresy",
            "85-wydajnosc-uruchomienia",
            "86-wydajnosc-metryki",
        ),
        evidence=(
            "wydajnosc/raport.json",
            "wydajnosc/raport.txt",
            "wydajnosc/baseline-kandydat.json",
            "wydajnosc/slad-okresy-4x.json",
            "wydajnosc/slad-okresy-6x.json",
            "wydajnosc/slad-metryki-4x.json",
            "wydajnosc/slad-metryki-6x.json",
        ),
        fixture="rok-pracy",
        measurement=True,
    ),
)
ALL = tuple(feature.name for feature in FEATURES if not feature.measurement)
# wydajnosc: repetitions of every scenario per CPU profile unless `--powtorzenia` says otherwise; a baseline
# comes only from a run with this many (features/wydajnosc.md).
DEFAULT_REPEATS = 5


def feature(name: str) -> Feature:
    [found] = [feature for feature in FEATURES if feature.name == name]
    return found


def broken_rules(features: Sequence[Feature]) -> list[str]:
    """Where ``features`` break the rules of the register: one screenshot number belongs to one feature, because
    feature files and PR descriptions name screenshots by number alone, and a feature's needs stand before it."""

    owners: dict[str, set[str]] = {}
    for each in features:
        for shot in each.screenshots:
            owners.setdefault(shot.split("-", 1)[0], set()).add(each.name)
    shared = {number: sorted(names) for number, names in owners.items() if len(names) > 1}
    order = [each.name for each in features]
    late = [f"{each.name} needs {need}" for each in features for need in each.needs if need not in order[: order.index(each.name)]]
    return ([f"screenshot numbers of more than one feature: {shared}"] if shared else []) + (
        [f"a feature needs one that does not stand before it in FEATURES: {late}"] if late else []
    )
