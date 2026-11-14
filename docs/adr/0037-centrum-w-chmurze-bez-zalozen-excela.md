# ADR 0037: Centrum w chmurze robi pracę samo, bez założeń Excela

## Status

Zaakceptowana (decyzja Maksa z 9.11.2026 w grillach [#1154](https://github.com/maximiseartai/MAXIMISEART-Dad/issues/1154),
[#1156](https://github.com/maximiseartai/MAXIMISEART-Dad/issues/1156) i
[#1172](https://github.com/maximiseartai/MAXIMISEART-Dad/issues/1172) mapy
[Centrum w chmurze](https://github.com/maximiseartai/MAXIMISEART-Dad/issues/1145)).
Dotyczy projektu Centrum w chmurze; Centrum na laptopie taty ten ADR nie zmienia.

## Decyzja

- **Praca sama.** To, co w Centrum istnieje tylko z powodu Excela albo jednego laptopa, w chmurze znika: aplikacja
  sama robi, co może, a tatę i pracownika taty pyta tylko wtedy, gdy potrzebny jest ich osąd albo decyzja (#1172).
  Uruchomienie bierze na starcie klucze dnia albo okresu, które zmienia albo czyta, i biegnie naraz z tym, co się z
  nim nie styka, a składanie pliku Excela ma limit wspólny dla wszystkich Uruchomień: najwyżej 2 naraz (#1156).
  Z plików Excela na stałe zostają Rozliczenia pracowników; Rejestr INTERMAX i Pliki zbiorcze w dzisiejszym kształcie
  zostają tylko do usunięcia starego Centrum z laptopa, a zamiast reszty jest tabela z ekranu w `.xlsx` bez Wzorca
  (#1154).
  Powód: dzisiejsze pliki i kroki taty (Uporządkowanie jako układ, Plik zbiorczy, Rozliczenie wewnętrzne) mają taką
  postać, bo tata musiał pracować w Excelu, a celem jest zdjąć z niego tę pracę, a nie przenieść ją na serwer.
