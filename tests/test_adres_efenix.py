"""Reguła adresu Wyceny w efenix jako własność Hypothesis: ``ADRES`` z Pliku zbiorczego i ``Dane adresowe`` z efenix.

Oczekiwanie pochodzi ze specyfikacji #741 („Porównanie adresu”): bez wielkości liter, zbędnych spacji i interpunkcji,
ten sam rodzaj (``ul.``, ``os.``), ten sam zbiór słów nazwy ulicy w dowolnej kolejności, ten sam numer i lokal (``/24``
w pliku to ``Lokal 24`` w efenix), a miejscowość z dzielnicą przed rodzajem w efenix się pomija. Numer budynku z ``/``
ma lokal (decyzja #829): ``13/14 Lokal 16`` w efenix to ``13/14/16`` w pliku. Generator pisze jeden adres w obu
zapisach, także z nazwą ulicy ze słowem reguły (``ul.Lokal 1``); zmiana numeru, lokalu, rodzaju albo jednego słowa
(także słowo dłuższe o literę) daje inny adres.
Hypothesis losuje z ``derandomize=True`` i bez bazy przykładów, ale bierze też napisy ze stałych modułów załadowanych
w procesie, więc słowa reguły generator podaje sam (#759).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from hypothesis import given, settings
from hypothesis import strategies as st
import pytest

from rozliczenia.efenix_address import same_address

PROPERTY = settings(derandomize=True, database=None, deadline=None, max_examples=150)
LETTERS = "abcdefghijklmnoprstuwyząćęłńóśźżABCDEFGHIJKLMNOPRSTUWYZĄĆĘŁŃÓŚŹŻ"


@dataclass(frozen=True)
class Address:
    kind: str
    words: tuple[str, ...]
    number: str
    flat: str | None


# Słowa samej reguły (rodzaje i ``Lokal``) bywają nazwą ulicy; Hypothesis losuje je zawsze, a nie tylko wtedy, gdy
# wcześniejszy test tego procesu xdist załadował moduł z takim napisem (stałe z ``sys.modules``, #759).
words = st.text(LETTERS, min_size=2, max_size=9) | st.sampled_from(["Lokal", "LOKAL", "ul", "Os", "AL", "pl"])
# Numer budynku bywa z ``/`` (``13/14``, ``15/19D``); w Pliku zbiorczym taki numer pisze się tylko z lokalem, bo
# ``13/14`` bez lokalu to budynek ``13`` i lokal ``14``.
numbers = st.from_regex(r"[1-9][0-9]{0,2}[A-Za-z]?(/[1-9][0-9]{0,2}[A-Za-z]?)?", fullmatch=True)
addresses = st.builds(
    Address,
    kind=st.sampled_from(["ul", "os"]),
    words=st.lists(words, min_size=1, max_size=3, unique_by=str.casefold).map(tuple),
    number=numbers,
    flat=st.none() | st.from_regex(r"[1-9][0-9]{0,2}|LU[1-9]", fullmatch=True),
).filter(lambda address: address.flat is not None or "/" not in address.number)


@st.composite
def _cased(draw: st.DrawFn, text: str) -> str:
    return "".join(letter.upper() if draw(st.booleans()) else letter.lower() for letter in text)


@st.composite
def _collective(draw: st.DrawFn, address: Address) -> str:
    """Zapis ``ADRES`` z Pliku zbiorczego: ``UL. SŁOWA 12A/24``, z kropką i spacjami w różnych miejscach."""

    kind = address.kind + draw(st.sampled_from([".", ". ", " . ", " "]))
    number = address.number + ("" if address.flat is None else draw(st.sampled_from(["/", " / ", "/ "])) + address.flat)
    tail = draw(st.sampled_from(["", ",", "."]))
    return draw(_cased(f"{kind}{' '.join(address.words)} {number}{tail}"))


@st.composite
def _efenix(draw: st.DrawFn, address: Address) -> str:
    """Zapis ``Dane adresowe`` z efenix: ``Miasto-Dzielnica ul.Słowa w innej kolejności 12A Lokal 24``."""

    town = draw(st.sampled_from(["Poznań-Wilda ", "Poznań-Nowe Miasto ", "Luboń ", ""]))
    order = draw(st.permutations(address.words))
    flat = "" if address.flat is None else f" Lokal {address.flat}"
    return town + draw(_cased(f"{address.kind}.{' '.join(order)} {address.number}{flat}"))


@PROPERTY
@given(st.data(), addresses)
def test_ten_sam_adres_w_zapisie_pliku_i_efenix_jest_rowny_przy_kazdej_kolejnosci_slow_i_wielkosci_liter(
    data: st.DataObject, address: Address
) -> None:
    assert same_address(data.draw(_collective(address)), data.draw(_efenix(address)))


def _changes(address: Address) -> st.SearchStrategy[Address]:
    other_number = numbers.filter(lambda n: n.casefold() != address.number.casefold())
    other_flat = (st.none() | st.from_regex(r"[1-9][0-9]{0,2}", fullmatch=True)).filter(
        lambda f: (f or "").casefold() != (address.flat or "").casefold()
    )
    longer = replace(address, words=(address.words[0] + "a", *address.words[1:]))
    other_word = words.filter(lambda w: w.casefold() not in {word.casefold() for word in address.words}).map(
        lambda w: replace(address, words=(w, *address.words[1:]))
    )
    return st.one_of(
        other_number.map(lambda number: replace(address, number=number)),
        other_flat.map(lambda flat: replace(address, flat=flat)),
        st.just(replace(address, kind="os" if address.kind == "ul" else "ul")),
        st.just(longer),
        other_word,
        st.just(replace(address, words=(*address.words, "Dodatkowe"))),
    )


@PROPERTY
@given(st.data(), addresses)
def test_inny_numer_lokal_rodzaj_albo_slowo_ulicy_to_inny_adres(data: st.DataObject, address: Address) -> None:
    changed = data.draw(_changes(address))

    assert not same_address(data.draw(_collective(address)), data.draw(_efenix(changed)))


@pytest.mark.parametrize(
    ("collective", "efenix"),
    [
        pytest.param("", "Poznań ul.Testowa 1", id="pusty-adres"),
        pytest.param("TESTOWA 1/2", "Poznań ul.Testowa 1 Lokal 2", id="bez-rodzaju"),
        pytest.param("UL. TESTOWA", "Poznań ul.Testowa", id="bez-numeru"),
        pytest.param("UL. TESTOWA 1/2", "Poznań ul.Testowa 1 Lokal 2 kod", id="cos-po-lokalu"),
        pytest.param("UL. 12 LOKAL 3", "Poznań ul. 12 Lokal 3", id="lokal-bez-nazwy-ulicy"),
    ],
)
def test_adres_bez_rodzaju_numeru_albo_z_czyms_po_lokalu_nie_jest_rowny_zadnemu(collective: str, efenix: str) -> None:
    assert not same_address(collective, efenix)


@pytest.mark.parametrize(
    ("collective", "efenix"),
    [
        pytest.param("UL. NAZWA ULICY 13/14/16", "Poznań-Wilda ul.Nazwa Ulicy 13/14 Lokal 16", id="13/14-lokal-16"),
        pytest.param("ul. Nazwa 15/19D/9", "Poznań ul.Nazwa 15/19D Lokal 9", id="15/19D-lokal-9"),
        pytest.param("Poznań ul.Nazwa Ulicy 13/14 Lokal 16", "Poznań ul.Nazwa Ulicy 13/14 Lokal 16", id="sam-sobie"),
        pytest.param("ul. Nazwa 15/19D/9", "ul. Nazwa 15/19D/9", id="sam-sobie-w-pliku"),
    ],
)
def test_numer_budynku_z_ukosnikiem_i_lokal_w_efenix_to_numer_z_dwoma_ukosnikami_w_pliku(collective: str, efenix: str) -> None:
    assert same_address(collective, efenix)


@pytest.mark.parametrize(
    ("collective", "efenix"),
    [
        pytest.param("UL. NAZWA 13/14/17", "Poznań ul.Nazwa 13/14 Lokal 16", id="inny-lokal"),
        pytest.param("UL. NAZWA 13 LOKAL 16", "Poznań ul.Nazwa 13/14 Lokal 16", id="numer-bez-ukosnika"),
        pytest.param("UL. NAZWA 13/15/16", "Poznań ul.Nazwa 13/14 Lokal 16", id="inna-druga-czesc-numeru"),
        pytest.param("UL. NAZWA 13/14", "Poznań ul.Nazwa 13/14 Lokal 16", id="jeden-ukosnik-to-lokal"),
        pytest.param("UL. TESTOWA 1/2/3", "Poznań ul.Testowa 1 Lokal 2", id="dwa-ukosniki"),
        pytest.param("UL. TESTOWA 1/2", "Poznań ul.Testowa 1/2 Lokal 2", id="ukosnik-i-lokal"),
    ],
)
def test_numer_budynku_z_ukosnikiem_rozni_sie_od_numeru_bez_niego_i_od_innej_czesci(collective: str, efenix: str) -> None:
    assert not same_address(collective, efenix)


@pytest.mark.parametrize(
    "address",
    [
        pytest.param("UL. TESTOWA 1/2/3/4", id="trzy-ukosniki"),
        pytest.param("Poznań ul.Testowa 1/2/3 Lokal 4", id="dwa-ukosniki-i-lokal"),
        pytest.param("UL. TESTOWA 1//3", id="pusta-czesc-numeru"),
        pytest.param("UL. TESTOWA 1/2/", id="pusty-lokal"),
        pytest.param("Poznań ul.Testowa 13/A Lokal 4", id="druga-czesc-numeru-bez-cyfry"),
    ],
)
def test_numer_budynku_z_wiecej_niz_dwiema_czesciami_albo_pusta_czescia_nie_jest_rowny_nawet_sobie(address: str) -> None:
    assert not same_address(address, address)
