"""Notka Wydania: to, co napisze narzędzie Wydań, Powiadomienie o nowej wersji odczyta bez straty."""

from __future__ import annotations

import pytest

from rozliczenia.centrum.release_notes import CASES_HEADING, DadCase, ReleaseNotes, WhatsNew, parse, render, whats_new

SUMMARY = "Przygotowanie pliku zbiorczego samo wpisuje ilości usług.\nCentrum pokazuje, co nowego."


@pytest.mark.parametrize(
    "cases",
    [
        (),
        (DadCase(3, "Zatrzymanie przy pustym ADRES", "zgloszenie"), DadCase(12, "Brakuje ilości: montaż #2", "uwaga-taty")),
    ],
)
def test_notka_wraca_z_tekstu_z_co_nowego_i_sprawami_taty(cases: tuple[DadCase, ...]) -> None:
    notes = ReleaseNotes(SUMMARY, cases)

    assert parse(render(notes)) == notes


def test_tytul_sprawy_w_notce_jest_jedna_linia() -> None:
    text = render(ReleaseNotes(SUMMARY, (DadCase(7, "Dwie\nlinie  tytułu", "uwaga-taty"),)))

    assert parse(text).cases == (DadCase(7, "Dwie linie tytułu", "uwaga-taty"),)


def test_notka_bez_spraw_nie_ma_naglowka_spraw() -> None:
    assert CASES_HEADING not in render(ReleaseNotes(SUMMARY, ()))


@pytest.mark.parametrize("summary", ["", "  \n", f"Co nowego.\n\n{CASES_HEADING}\n"])
def test_notka_wymaga_co_nowego_bez_naglowka_spraw(summary: str) -> None:
    with pytest.raises(ValueError, match="Co nowego"):
        render(ReleaseNotes(summary, ()))


CASES = (DadCase(3, "Zatrzymanie przy pustym ADRES", "zgloszenie"), DadCase(12, "Brakuje ilości", "uwaga-taty"))
LISTED = "- Zgłoszenie #3: Zatrzymanie przy pustym ADRES\n- Uwaga taty #12: Brakuje ilości\n"


@pytest.mark.parametrize(
    "text",
    [
        f"{SUMMARY}\n\n## Rozwiązane sprawy taty \n\n{LISTED}",
        f"{SUMMARY}\n\n### Rozwiązane sprawy taty\n\n{LISTED}",
        f"{SUMMARY}\n## Rozwiązane sprawy taty\n{LISTED}",
        f"{SUMMARY}\n\n## Rozwiązane sprawy taty\n\n{LISTED}".replace("\n", "\r\n"),
    ],
    ids=["spacja-na-koncu-naglowka", "naglowek-###", "bez-pustej-linii-przed-naglowkiem", "crlf"],
)
def test_notka_poprawiona_recznie_na_githubie_ma_co_nowego_bez_listy_i_sprawy(text: str) -> None:
    assert parse(text) == ReleaseNotes(SUMMARY, CASES)


@pytest.mark.parametrize("heading", ["# Rozwiązane sprawy taty", "##\tRozwiązane sprawy taty"], ids=["naglowek-#", "tabulator"])
def test_co_nowego_z_naglowkiem_spraw_innego_zapisu_jest_odrzucone(heading: str) -> None:
    with pytest.raises(ValueError, match="Co nowego"):
        render(ReleaseNotes(f"Co nowego.\n{heading}\nDalej o tym, co tata zobaczy.", ()))


POINTS = ("Plik zbiorczy ma kolumnę z kilometrami.", "Rozliczenia pracowników są dwa razy szybsze.")


@pytest.mark.parametrize(
    ("summary", "shown"),
    [
        (f"Ta wersja przyspiesza pracę.\n\n- {POINTS[0]}\n- {POINTS[1]}", WhatsNew("Ta wersja przyspiesza pracę.", POINTS)),
        (f"- {POINTS[0]}\n- {POINTS[1]}", WhatsNew("", POINTS)),
        (
            "Dzień wygląda teraz tak:\n\n- kolumna A ma ramkę,\n- kolumna J jest pogrubiona.",
            WhatsNew("Dzień wygląda teraz tak:", ("kolumna A ma ramkę,", "kolumna J jest pogrubiona.")),
        ),
        (f"Wstęp.\n*   {POINTS[0]}\n\n  - {POINTS[1]}", WhatsNew("Wstęp.", POINTS)),
        ("- Plik zbiorczy ma kolumnę\nz kilometrami.\n- Rozliczenia pracowników\n  są dwa razy szybsze.", WhatsNew("", POINTS)),
    ],
    ids=["wstep-i-punkty", "same-punkty", "notka-v0.3.1", "poprawiona-recznie", "punkt-zlamany-w-linii"],
)
def test_co_nowego_z_punktami_to_wstep_i_punkty_po_drodze_przez_notke(summary: str, shown: WhatsNew) -> None:
    assert whats_new(parse(render(ReleaseNotes(summary, CASES))).summary) == shown


@pytest.mark.parametrize(
    "summary",
    [
        SUMMARY,
        "Koszt - 5 zł za montaż.\nCentrum pokazuje, co nowego.",
        f"Wstęp.\n\n- {POINTS[0]}\n\nAkapit pod punktami.",
    ],
    ids=["zdania-bez-punktow", "myslnik-w-zdaniu", "akapit-pod-punktami"],
)
def test_co_nowego_bez_samych_punktow_pod_wstepem_jest_calym_wstepem(summary: str) -> None:
    """Stare Wydania i notka, której punktów nie da się pokazać bez straty zdania, wyglądają jak tekst notki."""

    assert whats_new(parse(render(ReleaseNotes(summary, ()))).summary) == WhatsNew(summary, ())
