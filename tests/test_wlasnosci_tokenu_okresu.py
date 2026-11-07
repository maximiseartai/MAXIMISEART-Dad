"""Token okresu rozliczeniowego (GLOSSARY.md: Okres rozliczeniowy) jako własności Hypothesis.

Okres trwa od wtorku do poniedziałku, a token ma dzień wtorku oraz dzień, miesiąc i rok poniedziałku, więc na
przełomie miesięcy i lat liczy się nowszy miesiąc. Każdy okres ma jeden token. Przykłady są deterministyczne
(``derandomize=True``, bez bazy przykładów), więc każdy przebieg i CI sprawdzają te same.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from rozliczenia.settlement_period import SettlementPeriod, parse_period_token, period_of

PROPERTY = settings(derandomize=True, database=None, deadline=None, max_examples=100)
TUESDAY = 1
DAYS = st.dates(min_value=date(1900, 1, 1), max_value=date(2199, 12, 20))
TUESDAYS = DAYS.map(lambda day: day - timedelta(days=(day.weekday() - TUESDAY) % 7))


def _written(start: date) -> str:
    """Token w zapisie z GLOSSARY.md dla okresu od ``start`` do ``start`` + 6 dni."""

    end = start + timedelta(days=6)
    return f"{start.day:02d}_{end.day:02d}_{end.month:02d}_{end.year:04d}"


@PROPERTY
@example(date(2026, 10, 27)).via("GLOSSARY.md: 27_02_11_2026")
@example(date(2026, 12, 29)).via("GLOSSARY.md: 29_04_01_2027")
@given(TUESDAYS)
def test_token_okresu_od_wtorku_do_poniedzialku_wraca_ten_sam_okres_przez_granice_miesiecy_i_lat(tuesday: date) -> None:
    period = SettlementPeriod(tuesday)

    assert period.token == _written(tuesday)
    assert parse_period_token(period.token) == period
    assert {period_of(tuesday + timedelta(days=day)) for day in range(7)} == {period}


def _parsed(token: str) -> SettlementPeriod | str:
    try:
        return parse_period_token(token)
    except ValueError as error:
        return str(error)


@st.composite
def _changed_tokens(draw: st.DrawFn) -> str:
    """Token okresu z jedną częścią przesuniętą o 1, czyli zwykle token innego dnia albo żadnego okresu."""

    parts = [int(part) for part in _written(draw(TUESDAYS)).split("_")]
    changed = draw(st.integers(0, 3))
    parts[changed] += draw(st.sampled_from((-1, 1)))
    return "_".join(f"{part:0{4 if index == 3 else 2}d}" for index, part in enumerate(parts))


@PROPERTY
@given(
    st.one_of(
        _changed_tokens(),
        st.tuples(st.integers(0, 99), st.integers(0, 99), st.integers(0, 99), st.integers(0, 9999)).map(
            lambda parts: "{:02d}_{:02d}_{:02d}_{:04d}".format(*parts)
        ),
    )
)
def test_token_przyjety_jako_okres_jest_jedynym_tokenem_tego_okresu(token: str) -> None:
    parsed = _parsed(token)

    if isinstance(parsed, SettlementPeriod):
        assert parsed.token == token
        assert parsed.tuesday.weekday() == TUESDAY
    else:
        assert parsed == "Token okresu nie opisuje okresu od wtorku do poniedziałku.", token


@PROPERTY
@given(DAYS.filter(lambda day: day.weekday() != TUESDAY))
def test_okres_nie_zaczyna_sie_w_dniu_innym_niz_wtorek(start: date) -> None:
    with pytest.raises(ValueError, match="zaczyna się we wtorek"):
        SettlementPeriod(start)

    assert _parsed(_written(start)) == "Token okresu nie opisuje okresu od wtorku do poniedziałku."


@PROPERTY
@example(date(2026, 10, 27), 0).via("GLOSSARY.md: wtorek 00:00 to pierwsza chwila okresu")
@example(date(2026, 10, 27), 7 * 24 * 3600 - 1).via("poniedziałek 23:59:59 to ostatnia chwila okresu")
@example(date(2026, 10, 27), 7 * 24 * 3600).via("następny wtorek 00:00 należy do kolejnego okresu")
@example(date(2026, 10, 27), -1).via("poniedziałek przed okresem 23:59:59")
@given(TUESDAYS, st.integers(min_value=-2 * 24 * 3600, max_value=9 * 24 * 3600))
def test_okres_zawiera_kazda_chwile_i_dzien_od_wtorku_do_poniedzialku_i_zadnej_poza_nim(tuesday: date, seconds: int) -> None:
    moment = datetime(tuesday.year, tuesday.month, tuesday.day) + timedelta(seconds=seconds)
    inside = 0 <= seconds < 7 * 24 * 3600

    assert (SettlementPeriod(tuesday).contains(moment), SettlementPeriod(tuesday).contains(moment.date())) == (inside, inside)
