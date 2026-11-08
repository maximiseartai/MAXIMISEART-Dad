"""Atrapy świata zewnętrznego, z których korzystają testy, narzędzia i skrypty skilli.

- ``model_efenix``: stan zleceń i sesji efenix i decyzje serwera efenix, bez HTTP i przeglądarki,
- ``atrapa_efenix``: Atrapa efenix, lokalny serwer HTTP w budowie stron efenix nad modelem (ADR 0024).

Pakiet leży poza ``tests/``, bo narzędzia i skille, które zmieniają się rzadko, nie mogą zależeć od plików testów
(``tests/test_granice_importow.py::test_kod_spoza_testow_nie_importuje_testow``), i poza ``src``, bo atrapa to celowa
kopia świata zewnętrznego, z którą testy porównują sprawdzany kod (``docs/agents/skille.md``, „Co wyrocznia bierze z
src”). Importuje się go z ``tools/lib`` na ``sys.path``: ``from atrapy.atrapa_efenix import atrapa_efenix``.
"""
