"""Reguła adresu Wyceny w efenix jako własność Hypothesis: ``ADRES`` z Pliku zbiorczego i ``Dane adresowe`` z efenix.

Oczekiwanie pochodzi ze specyfikacji #741 („Porównanie adresu”): bez wielkości liter, zbędnych spacji i interpunkcji,
ten sam rodzaj (``ul.``, ``os.``), ten sam zbiór słów nazwy ulicy w dowolnej kolejności, ten sam numer i lokal (``/24``
w pliku to ``Lokal 24`` w efenix), a miejscowość z dzielnicą przed rodzajem w efenix się pomija. Generator pisze jeden
adres w obu zapisach; zmiana numeru, lokalu, rodzaju albo jednego słowa (także słowo dłuższe o literę) daje inny adres.
Przykłady są deterministyczne (``derandomize=True``, bez bazy przykładów).
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


words = st.text(LETTERS, min_size=2, max_size=9)
addresses = st.builds(
    Address,
    kind=st.sampled_from(["ul", "os"]),
    words=st.lists(words, min_size=1, max_size=3, unique_by=str.casefold).map(tuple),
    number=st.from_regex(r"[1-9][0-9]{0,2}[A-Za-z]?", fullmatch=True),
    flat=st.none() | st.from_regex(r"[1-9][0-9]{0,2}|LU[1-9]", fullmatch=True),
)


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
    other_number = st.from_regex(r"[1-9][0-9]{0,2}[A-Za-z]?", fullmatch=True).filter(lambda n: n.casefold() != address.number.casefold())
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
        pytest.param("UL. TESTOWA 1/2/3", "Poznań ul.Testowa 1 Lokal 2", id="dwa-ukosniki"),
        pytest.param("UL. TESTOWA 1/2", "Poznań ul.Testowa 1/2 Lokal 2", id="lokal-dwa-razy"),
        pytest.param("UL. TESTOWA 1/2", "Poznań ul.Testowa 1 Lokal 2 kod", id="cos-po-lokalu"),
    ],
)
def test_adres_bez_rodzaju_numeru_albo_z_czyms_po_lokalu_nie_jest_rowny_zadnemu(collective: str, efenix: str) -> None:
    assert not same_address(collective, efenix)
