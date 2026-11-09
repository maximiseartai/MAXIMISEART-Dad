"""Atrapy świata zewnętrznego, z których korzystają testy, narzędzia i skrypty skilli.

- ``model_efenix``: stan zleceń i sesji efenix i decyzje serwera efenix, bez HTTP i przeglądarki,
- ``atrapa_efenix``: Atrapa efenix, lokalny serwer HTTP w budowie stron efenix nad modelem (ADR 0024),
- syntetyczne pliki taty w kształcie jego plików, z uszkodzeniami i odczytem bajtów skoroszytu: ``settlement`` (Plik
  zbiorczy, Wzorzec rozliczenia pracownika, Konfiguracja wykonawców), ``preparation`` (Rejestr zleceń i Wzorce
  Przygotowania), ``wzorce`` (Wzorce taty w pełnym rozmiarze), ``intermax`` (INTERMAX), ``efenix`` (Plik zbiorczy
  Wyceny w efenix i zgodne z nim zlecenia Atrapy), ``workbooks`` (części skoroszytu),
- fakty scenariuszy skilli: ``scenariusz_rozliczen``, ``scenariusz_centrum``,
- reszta świata wokół Centrum: ``widok_skrzynki`` (issue Skrzynki Zgłoszeń, jak Maks je widzi na GitHubie),
  ``dziennik_wyceny`` (dziennik Wyceny w efenix w formacie dysku taty), ``interlocutor`` (Tata jako rozmówca),
  ``sluchacz_kolejki`` (słuchacz kolejki Skrzynki bez Spraw taty).

Pakiet leży poza ``tests/``, bo narzędzia i skille, które zmieniają się rzadko, nie mogą zależeć od plików testów
(``tests/test_granice_importow.py::test_kod_spoza_testow_nie_importuje_testow``), i poza ``src``, bo atrapa to celowa
kopia świata zewnętrznego, z którą testy porównują sprawdzany kod (``docs/agents/skille.md``, „Co wyrocznia bierze z
src”). Pomocniki, które w teście uruchamiają proces na tych plikach, zostają w ``tests/fixtures/operacje.py``.
Importuje się go z ``tools/lib`` na ``sys.path``: ``from atrapy.atrapa_efenix import atrapa_efenix``.
"""
