# Research: rozmiar i koszt serwera Centrum na Hetznerze

Data researchu: 2026-11-08 (ceny czytane tego dnia ze stron Hetznera).
Ticket: #1146, mapa: #1145 „Centrum w chmurze”.

Wszystkie ceny Hetznera są cenami netto w EUR („excl. VAT”), tak jak podaje je Hetzner.
Cena brutto w tabelach to netto × 1,23 (polski VAT 23%, który Hetzner nalicza klientowi z Polski bez ważnego numeru VAT UE).
Firma z ważnym numerem VAT UE dostaje fakturę w odwrotnym obciążeniu („Reverse-Charge”), bez niemieckiego VAT, i rozlicza VAT sama ([Value added tax](https://docs.hetzner.com/general/billing-and-account-management/billing-at-hetzner/value-added-tax/)).

## Wniosek

- Serwer: jeden serwer x86 w Norymberdze (NBG1) z aplikacją i Postgresem na tej samej maszynie.
  Dziś da się zamówić **CPX22** (2 vCPU AMD, 4 GB RAM, 80 GB NVMe, 20 TB ruchu, IPv4 w cenie) za **19,99 € netto/mies.**
  Tańsze plany Cost-Optimized (CX23 za 5,99 €, CX33 za 8,99 €) mają na stronie Hetznera status „not available”.
  Gdy CX33 wróci, ma te same 80 GB dysku co CPX22, więc da się na niego zejść zmianą typu bez migracji.
- Kopie zapasowe: Backupy Hetznera (20% ceny serwera, 7 dziennych kopii dysku) plus nocny zrzut Postgresa i archiwum WAL na Storage Box BX11 (1 TB, 3,20 €) w Helsinkach, czyli w innym kraju niż serwer.
- Zdjęcia techników: Object Storage (S3) w NBG1, 6,49 € miesięcznie z 1 TB miejsca i 1 TB ruchu wychodzącego w cenie, co starczy na kilka lat zdjęć. Kopia zdjęć idzie nocą na ten sam Storage Box.
- Bez osobnego serwera bazy i bez zarządzanego Postgresa: Hetzner Cloud go nie ma, a obciążenie jest za małe, żeby płacić za drugą maszynę albo drugiego dostawcę.

| Wariant | Skład | Netto/mies. | Brutto (23%)/mies. |
|---|---|---|---|
| Biuro dziś (zalecany) | CPX22 19,99 + Backupy 4,00 + BX11 3,20 | **27,19 €** | **33,44 €** |
| Biuro dziś, gdy CX33 jest dostępny | CX33 8,99 + Backupy 1,80 + BX11 3,20 | 13,99 € | 17,21 € |
| Biuro + technicy po roku (zalecany) | CPX22 19,99 + Backupy 4,00 + Object Storage 6,49 + BX11 3,20 | **33,68 €** | **41,43 €** |
| Biuro + technicy, gdy zabraknie RAM | CPX32 35,99 + Backupy 7,20 + Object Storage 6,49 + BX11 3,20 | 52,88 € | 65,04 € |
| Biuro + technicy na CX33 | CX33 8,99 + Backupy 1,80 + Object Storage 6,49 + BX11 3,20 | 20,48 € | 25,19 € |

Ruch wychodzący w żadnym wariancie nic nie kosztuje: szacunek poniżej to dziesiątki GB miesięcznie, a w cenie jest 20 TB na serwer i 1 TB na Object Storage.

## Szacunek obciążenia: co się zgadza, a co poprawiam

Policzyłem tylko sumy z kopii Rejestru zleceń taty na Macu Maksa (wersja z 20.10.2026), bez żadnych danych zleceń.

- **Zlecenia: ok. 74 dziennie, nie 20–35.**
  Arkusz zleceń tej wersji Rejestru zaczyna się 2.06.2025 i kończy 21.10.2026.
  Ma 42 783 wiersze, z czego 31 779 niepustych (puste wiersze rozdzielają dni, zob. `GLOSSARY.md`, Rejestr zleceń).
  To ok. 1 850 zleceń miesięcznie (od 1 463 do 2 563), średnio 74 w dniu ze zleceniami, mediana 83, 90. percentyl 105, maksimum 133, a zlecenia są w 430 dniach z ok. 505.
  „42 tys. wierszy od listopada 2021” jest więc błędne dwa razy: 42 tys. to wiersze razem z pustymi, a pochodzą z ok. 17 miesięcy od czerwca 2025.
  Gdzie leży historia z lat 2021–05.2025, trzeba ustalić z tatą (to temat przeniesienia historii z mapy).
  Rocznie daje to ok. 23 tys. zleceń.
- **Wykonawcy: ok. 18–20 różnych wartości w kolumnie `WYKONAWCA` miesięcznie w 2026 r., nie 10.**
  Część z nich może być aliasem tej samej osoby. Jedno Uporządkowanie INTERMAX dnia z 84 zleceniami pokazało 16 Wykonawców.
- **Zapisy: kilkaset do ok. 1 500 zmian dziennie**, czyli przy 8 godzinach pracy 0,02–0,05 zmiany na sekundę.
  To nadal ruch zerowy dla Postgresa i żadna przesłanka do wyboru serwera.
- **Baza: setki MB, nie dziesiątki, po 5 latach, licząc historię zmian.**
  Ok. 115 tys. zleceń w 5 lat to przy ~1 KB na wiersz z indeksami ok. 100–150 MB.
  Pełny dziennik zmian (kryterium 4, pełne logi) to przy ok. 1 000 zmian dziennie i ~1 KB na zmianę ok. 0,3 GB rocznie.
  Razem mniej niż kilka GB w 5 lat, a dysk ma 80 GB.
- **Szczyt pamięci daje silnik na plikach Excel, nie ruch www.**
  Uporządkowanie INTERMAX na kopii prawdziwego Rejestru (6 MB) zajęło 0,42 s i miało szczytowo 450 MB pamięci (`/usr/bin/time -l`, `tools/uruchom_proces.py intermax`, 8.11.2026, Mac).
  Dopóki Excel zostaje zabezpieczeniem, dwa takie Uruchomienia naraz to ok. 1 GB.
  Z Postgresem (256–512 MB buforów), serwerem aplikacji i systemem 4 GB jest minimum, a 2 GB (CPX12) jest za mało.
- **Zdjęcia: 160–350 GB rocznie bez zmniejszania, 30–60 GB ze zmniejszaniem.**
  Szacunek z ticketu (35 raportów × 5 zdjęć × 3 MB ≈ 0,5 GB dziennie) liczył ok. 240 dni roboczych.
  Zlecenia są w ok. 310 dniach rocznie, więc dla 35 raportów dziennie wychodzi ok. 160 GB rocznie.
  Gdyby raport miało każde zlecenie (74 dziennie), byłoby ok. 340 GB rocznie.
  Zdjęcie zmniejszone w telefonie przed wysłaniem (np. dłuższy bok 2048 px, ~0,5 MB) daje 30–60 GB rocznie.
  Liczba zdjęć na raport i rozmiar zdjęcia to założenia z rozmowy, nie pomiar.

## Serwery w chmurze (EU, ceny netto)

Plany Cost-Optimized (CX, CAX) działają na starszej generacji sprzętu ze współdzielonym CPU, Regular Performance (CPX) na najnowszej ze współdzielonym CPU, a General Purpose (CCX) ma dedykowane vCPU ([Servers overview](https://docs.hetzner.com/cloud/servers/overview/)).
Każdy plan w UE ma 20 TB ruchu w cenie, a każdy dodatkowy TB kosztuje 1,00 € (strona pisze „per hour”, co wygląda na błąd zamiast „per TB”).
Strony planów podają „Price incl. IPv4”. Starsze strony dokumentacji (Servers overview, IP pricing z 2023 r.) liczą Primary IPv4 osobno po 0,50 €, więc w najgorszym razie dolicz 0,50 € netto.

Cost-Optimized ([cennik](https://www.hetzner.com/cloud/cost-optimized/)), lokalizacje NBG1 i HEL1, wszystkie z klasą „not-available” na stronie 8.11.2026:

| Plan | Arch. | vCPU | RAM | NVMe | €/mies. | €/h |
|---|---|---|---|---|---|---|
| CX23 | x86 Intel/AMD | 2 | 4 GB | 40 GB | 5,99 | 0,0096 |
| CAX11 | Arm64 Ampere | 2 | 4 GB | 40 GB | 6,49 | 0,0104 |
| CX33 | x86 | 4 | 8 GB | 80 GB | 8,99 | 0,0144 |
| CAX21 | Arm64 | 4 | 8 GB | 80 GB | 10,99 | 0,0176 |
| CX43 | x86 | 8 | 16 GB | 160 GB | 16,49 | 0,0264 |
| CAX31 | Arm64 | 8 | 16 GB | 160 GB | 21,49 | 0,0344 |

Regular Performance ([cennik](https://www.hetzner.com/cloud/regular-performance/)), AMD, do zamówienia 8.11.2026, CPX22 i wyższe tylko w NBG1 i HEL1:

| Plan | vCPU | RAM | NVMe | €/mies. | €/h |
|---|---|---|---|---|---|
| CPX02 | 1 | 1 GB | 20 GB | 6,49 | 0,0104 |
| CPX12 | 1 | 2 GB | 40 GB | 11,99 | 0,0192 |
| CPX22 | 2 | 4 GB | 80 GB | 19,99 | 0,0320 |
| CPX32 | 4 | 8 GB | 160 GB | 35,99 | 0,0577 |
| CPX42 | 8 | 16 GB | 320 GB | 69,99 | 0,1122 |

General Purpose ([cennik](https://www.hetzner.com/cloud/general-purpose/)) zaczyna się od CCX13 (2 dedykowane vCPU, 8 GB, 80 GB) za 43,49 €; przy tym obciążeniu to przepłata.

- **Dostępność:** dostępność planów zmienia się na bieżąco i Hetzner sprawdza ją co ok. 15 minut ([Cloud servers FAQ](https://docs.hetzner.com/cloud/servers/faq/)); strona Cost-Optimized pisze, że „the number of available servers is limited”.
  CX33 trzeba więc sprawdzić w Konsoli w chwili zamawiania.
- **x86 zamiast ARM:** zmiana typu działa tylko w obrębie tej samej architektury ([Cloud servers FAQ](https://docs.hetzner.com/cloud/servers/faq/)).
  ARM (CAX) zamyka drogę do CPX i CCX, a CAX też jest dziś niedostępny.
  Python i Postgres działają na Arm64, ale x86 zostawia otwarte wszystkie plany i zgadza się ze sprzętem taty i CI.
- **Rozliczenie:** godzinowe z miesięcznym limitem, a serwer kosztuje także wyłączony, aż do usunięcia.
- **Podwyżki w 2026:** Hetzner podniósł ceny 1.04.2026 (także istniejących produktów) i 15.06.2026 ([komunikat z 27.05.2026](https://www.hetzner.com/pressroom/standardization-and-price-adjustment-of-our-server-products/)).
  Podwyżka z czerwca dotyczy nowych zamówień i zmian typu serwera, a nie istniejących umów; IP, Volumes, Snapshots i Object Storage zostały bez zmian.
  Ceny powyżej to ceny po czerwcu.

## Dodatki: backupy, snapshoty, wolumeny, Storage Box, Object Storage

- **Backupy serwera:** 20% ceny serwera miesięcznie za 7 dziennych slotów; po siódmej kopii najstarsza znika ([Billing FAQ](https://docs.hetzner.com/cloud/billing/faq/), [Backups/Snapshots](https://docs.hetzner.com/cloud/servers/backups-snapshots/overview/)).
  To kopia całego dysku, bez dołączonych Volumes.
  Dla Postgresa sama kopia dysku nie wystarczy (nie ma spójności transakcji ani odtworzenia do chwili), stąd zrzut i WAL na Storage Box.
- **Snapshoty:** 0,0143 € za GB miesięcznie, liczone od skompresowanego rozmiaru; zostają, aż je usuniesz (strony planów, [Billing FAQ](https://docs.hetzner.com/cloud/billing/faq/)).
  Przydają się przed aktualizacją systemu, nie jako stały backup.
- **Volumes:** 0,044 € za GB miesięcznie, od 10 GB do 10 TB, każdy blok na trzech serwerach, tylko powiększanie ([Block Storage](https://www.hetzner.com/cloud/block-storage/), [Volumes](https://docs.hetzner.com/cloud/volumes/overview/)).
  Kalkulator na tej stronie ma w atrybucie 0,0572, czego nie umiem wyjaśnić; tekst strony mówi 0,044 € netto.
  Backupy i snapshoty serwera nie obejmują Volumes. W zaleceniu Volumes nie są potrzebne: baza i logi mieszczą się na dysku serwera, a 200 GB zdjęć na Volume (8,80 € i rośnie) kosztowałoby więcej niż Object Storage.
- **Storage Box:** BX11 1 TB 3,20 €, BX21 5 TB 10,90 €, ruch bez limitu, SFTP, rsync, BorgBackup, Restic, rclone, automatyczne snapshoty, lokalizacje FSN1 i HEL1 ([Storage Box](https://www.hetzner.com/storage/storage-box/)).
  Opłaty instalacyjnej nie udało się odczytać ze statycznej strony (cena ładuje się skryptem); sprawdź ją przy zamówieniu.
- **Object Storage:** 6,49 € miesięcznie za konto (0,0104 €/h), w tym 1 TB miejsca (744 TB-godzin) i 1 TB ruchu wychodzącego.
  Powyżej: 0,0087 € za TB-godzinę (ok. 6,47 € za TB miesięcznie) i 1,00 € za TB ruchu.
  Ruch przychodzący, ruch wewnątrz strefy eu-central i zapytania S3 są bezpłatne; minimalny rozliczany obiekt to 64 KB ([Object Storage](https://www.hetzner.com/storage/object-storage/)).
  Dane bucketu leżą w jednym centrum danych, z erasure coding odpornym na awarię do trzech serwerów, na dyskach HDD i bez wbudowanej replikacji do innej lokalizacji ([Object Storage FAQ](https://docs.hetzner.com/storage/object-storage/faq/general/)).
  Hetzner poleca go do kopii zapasowych i do zdjęć czytanych przez aplikację „on a moderate basis”, a nie do bazy danych; przy dużej liczbie odbiorców radzi CDN.
  Endpointy są w FSN1, NBG1 i HEL1 ([Object Storage overview](https://docs.hetzner.com/storage/object-storage/overview/)); Hetzner ma instrukcje Object Lock i Versioning.

## Osobny serwer na Postgres i zarządzany Postgres

- Hetzner Cloud nie ma zarządzanej bazy danych.
  PostgreSQL w zarządzanej formie Hetzner daje tylko na Managed Server i webhostingu (konsoleH), bez dostępu root i z jedną wersją Postgresa dla wszystkich ([Managed databases FAQ](https://docs.hetzner.com/managed/databases/faq/)), więc to nie pasuje do aplikacji Centrum.
- Zarządzanego Postgresa poza Hetznerem nie wyceniłem (cennik Scaleway odmówił dostępu).
  Niezależnie od ceny oznacza on drugiego dostawcę, drugą umowę powierzenia, bazę w innym centrum danych niż aplikacja i opóźnienie sieci przy każdym zapytaniu.
- Przy tym obciążeniu (zob. wyżej) jeden serwer z Postgresem obok aplikacji wystarczy z dużym zapasem.
  Osobny serwer bazy ma sens dopiero wtedy, gdy pomiar pokaże, że silnik albo aplikacja zabiera bazie CPU lub RAM.

## Skalowanie bez migracji

- **Większy serwer:** zmiana typu (Rescale) w Konsoli albo przez API wymaga wyłączenia serwera, kopiuje jego dysk i włącza go z powrotem ([Cloud API, change_type](https://docs.hetzner.cloud/reference/cloud)).
  Adres IP i dane zostają; przerwa trwa tyle, ile kopiowanie dysku (nie mierzyłem).
  Przy powiększaniu zostaw obecny dysk (`upgrade_disk: false`, w Konsoli „keep current disk size”): po powiększeniu dysku nie da się już zejść na mniejszy plan ([Cloud servers FAQ](https://docs.hetzner.com/cloud/servers/faq/)).
  Ścieżka: CPX22 (80 GB) → CPX32 z dyskiem 80 GB → z powrotem CPX22 albo CX33, gdy będzie dostępny.
  Na CX23 (40 GB) z CPX22 zejść się nie da.
- **Zdjęcia:** Object Storage jest niezależny od serwera, więc zmiana serwera, a nawet jego wymiana, nie rusza zdjęć.
  Rośnie samo zużycie (1 TB w cenie, potem ok. 6,47 € za TB).
  Aplikacja powinna od początku zapisywać zdjęcia przez API S3, nie na dysk serwera, wtedy żadnego przenoszenia nie będzie.
- **Baza:** gdy kiedyś trzeba będzie, Postgres przechodzi na drugi serwer w sieci prywatnej Hetznera przez odtworzenie z kopii na Storage Box.

## Bezpieczeństwo danych (kryterium 4)

- Umowę powierzenia przetwarzania (Art. 28 RODO) zawiera się samodzielnie w koncie klienta Hetznera, zaznaczając zgodę; nie zawiera się sama, a Hetzner nie podpisuje indywidualnych umów ([Data Protection at Hetzner](https://docs.hetzner.com/general/company-and-policy/data-protection-at-hetzner/)).
  Trzeba to zrobić przed wgraniem danych zleceń.
- Wszystkie zalecane usługi leżą w UE: serwer i bucket w Niemczech (NBG1), Storage Box w Finlandii (HEL1).

## Źródła (czytane 2026-11-08)

- [Cost-Optimized](https://www.hetzner.com/cloud/cost-optimized/), [Regular Performance](https://www.hetzner.com/cloud/regular-performance/), [General Purpose](https://www.hetzner.com/cloud/general-purpose/)
- [Block Storage](https://www.hetzner.com/cloud/block-storage/), [Object Storage](https://www.hetzner.com/storage/object-storage/), [Storage Box](https://www.hetzner.com/storage/storage-box/)
- [Standardization and price adjustment, 15.06.2026](https://www.hetzner.com/pressroom/standardization-and-price-adjustment-of-our-server-products/)
- [Cloud billing FAQ](https://docs.hetzner.com/cloud/billing/faq/), [Cloud servers FAQ](https://docs.hetzner.com/cloud/servers/faq/), [Servers overview](https://docs.hetzner.com/cloud/servers/overview/)
- [Backups/Snapshots](https://docs.hetzner.com/cloud/servers/backups-snapshots/overview/) (zmiana 2026-09-03), [Volumes](https://docs.hetzner.com/cloud/volumes/overview/)
- [Object Storage overview](https://docs.hetzner.com/storage/object-storage/overview/), [Object Storage FAQ](https://docs.hetzner.com/storage/object-storage/faq/general/)
- [IP pricing](https://docs.hetzner.com/general/infrastructure-and-availability/ipv4-pricing/) (zmiana 2023-04-13)
- [Value added tax](https://docs.hetzner.com/general/billing-and-account-management/billing-at-hetzner/value-added-tax/) (zmiana 2026-09-15)
- [Hetzner Cloud API reference](https://docs.hetzner.cloud/reference/cloud) (`POST /servers/{id}/actions/change_type`)
- [Managed databases FAQ](https://docs.hetzner.com/managed/databases/faq/), [Data Protection at Hetzner](https://docs.hetzner.com/general/company-and-policy/data-protection-at-hetzner/)
- Pomiar własny: sumy z kopii Rejestru zleceń i pamięć Uporządkowania INTERMAX na Macu Maksa, 8.11.2026 (bez danych zleceń w repozytorium).
