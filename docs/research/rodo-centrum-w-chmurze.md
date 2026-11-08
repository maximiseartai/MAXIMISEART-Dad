# Research: RODO, gdy dane klientów INEA przechodzą na serwer w chmurze

Data researchu: 2026-11-08.
Ticket: #1150 (mapa #1145 „Centrum w chmurze”), wejście do ticketu #1152 „Umowa z INEA o danych klientów”.

To nie jest porada prawna.
Niżej są fakty z pierwotnych źródeł (tekst RODO, wytyczne EROD, materiały UODO, umowy powierzenia dostawców) z odnośnikiem przy każdym twierdzeniu, a na końcu pytania do taty o jego umowę z INEA.
Decyzję podejmuje tata, a jeśli trzeba, z prawnikiem.
Gdzie piszę „wskazuje”, to odczyt źródła, nie rozstrzygnięcie.

## Wniosek w skrócie

- INEA w swojej klauzuli informacyjnej dla klientów wymienia „monterom sprzętu i technikom rozprowadzającym łącza” wśród podmiotów, które przetwarzają dane „w naszym imieniu” [INEA-KI pkt 5.1.3].
  Firma taty jest więc najpewniej **podmiotem przetwarzającym** INEA (art. 4 pkt 8 RODO), a nie administratorem tych danych.
  Pewność da dopiero umowa: tata może mieć umowę z firmą pośrednią, a przy zleceniach hurt administratorem może być inny operator (sekcja 1).
- Serwer w Hetznerze, Microsoft 365 (OneDrive) i Gmail, przez które płyną dane klientów, to **dalsze podmioty przetwarzające**.
  Art. 28 ust. 2 RODO zabrania tacie korzystać z nich bez **uprzedniej pisemnej zgody** administratora, szczegółowej albo ogólnej.
  Która to zgoda i jaka procedura, mówi tylko umowa powierzenia taty [RODO art. 28 ust. 2; EROD 07/2020 pkt 152–158].
- Wobec INEA tata odpowiada **w pełni** za to, czy Hetzner, Microsoft i Google wypełniają swoje obowiązki [RODO art. 28 ust. 4 zd. 2].
- Hetzner ma standardową umowę powierzenia (AVV/DPA), ale **nie zawiera się ona sama**: zawiera ją klient zaznaczeniem pola w panelu konta [Hetzner-Docs].
  Przy lokalizacji w UE dane i wsparcie zostają w UE [Hetzner-DPA §3, zał. 3].
  Szyfrowanie danych i kopii w spoczynku, aktualizacje, zapora, kopie i monitoring serwera chmurowego to według Hetznera **obowiązek klienta**, czyli Maksa [Hetzner-TOM pkt 7, 9].
- RODO nie podaje listy minimalnych zabezpieczeń.
  Art. 32 wymaga środków „odpowiednich” do ryzyka i wymienia przykłady: szyfrowanie, poufność i odporność, szybkie odtworzenie, regularne testy [RODO art. 32 ust. 1].
  Konkretne minimum może narzucać dopiero umowa z INEA.
- Gmail prywatny i Gmail w Google Workspace to dwa różne reżimy.
  Dla zwykłego konta w EOG administratorem jest Google Ireland [Google-PP], a umowa powierzenia (Cloud Data Processing Addendum) obejmuje dane z konta Workspace [Google-CDPA, Workspace pkt 1].
- Rejestr kategorii czynności przetwarzania (art. 30 ust. 2) najpewniej obowiązuje firmę taty mimo mniej niż 250 osób: zdaniem GR Art. 29 wyjątek z art. 30 ust. 5 nie obejmuje przetwarzania, które „nie ma charakteru sporadycznego” [WP29-30(5)].

## Pojęcia

- **Administrator** ustala cele i sposoby przetwarzania [RODO art. 4 pkt 7].
- **Podmiot przetwarzający** „przetwarza dane osobowe w imieniu administratora” [RODO art. 4 pkt 8].
  EROD wskazuje dwa warunki: osobny podmiot i przetwarzanie w imieniu administratora [EROD 07/2020 pkt 76].
- **Dalszy podmiot przetwarzający** (w RODO „inny podmiot przetwarzający”, w umowach „podprocesor”, „Subunternehmer”, „Subprocessor”) to podmiot, któremu podmiot przetwarzający powierza część przetwarzania [RODO art. 28 ust. 2 i 4; EROD 07/2020 pkt 151].
- **Dane osobowe** obejmują też osobę, którą można zidentyfikować „pośrednio”, np. przez numer identyfikacyjny [RODO art. 4 pkt 1].
  Liczą się sposoby identyfikacji, których użycie jest „rozsądnie prawdopodobne” [RODO motyw 26].
  Numer umowy albo zlecenia, który INEA wiąże z klientem, jest więc daną osobową przynajmniej dla INEA i dla taty.
  TSUE uznał, że dla odbiorcy, który nie może rozsądnie przypisać danych osobie, dane spseudonimizowane mogą nie być osobowe, ale ocenia się to w okolicznościach sprawy [TSUE C-413/23 P].

## 1. Rola taty wobec INEA

- Rolę wyznaczają faktyczne działania, nie nazwa w umowie.
  Ten sam podmiot może być administratorem jednych operacji i podmiotem przetwarzającym innych [EROD 07/2020 pkt 82].
- INEA w klauzuli dla klientów, w punkcie „Komu możemy udostępniać Państwa dane osobowe”, w części „Podmiotom przetwarzającym dane osobowe w naszym imieniu” wymienia m.in. „podwykonawcom w procesie obsługi klienta” i „monterom sprzętu i technikom rozprowadzającym łącza” [INEA-KI pkt 5.1.1, 5.1.3].
  Sama INEA opisuje więc instalatorów jako swoich podmiotów przetwarzających.
- Przetwarzanie przez podmiot przetwarzający odbywa się na podstawie umowy, która wymienia przedmiot, czas, charakter i cel przetwarzania, rodzaj danych i kategorie osób oraz obowiązki z lit. a–h (polecenia, poufność, art. 32, dalsze podmioty, pomoc administratorowi, usunięcie albo zwrot danych, audyty) [RODO art. 28 ust. 3].
  Umowa ma formę pisemną, także elektroniczną [RODO art. 28 ust. 9].
- **Uwaga 1: łańcuch może być dłuższy.**
  Rejestr zleceń zawiera zlecenia `Instalacja Hurt` dla innych operatorów, np. Orange, T-Mobile i Netii (`GLOSSARY.md`: „Wpis urządzenia i czynności INTERMAX”, „Kolor operatora”).
  Dla klientów tych operatorów administratorem może być operator detaliczny, a INEA jego podmiotem przetwarzającym, i wtedy tata jest już dalszym podmiotem.
  Tak samo, gdy tata ma umowę nie z INEA, tylko z firmą pośrednią (np. tą, z którą rozlicza się w efenix).
  Z publicznych źródeł tego nie ustalimy, to pytanie do taty (pytania A1–A3).
- **Uwaga 2: cel spoza poleceń robi z podmiotu administratora.**
  Podmiot przetwarzający, który sam ustala cele i sposoby przetwarzania, staje się dla tego przetwarzania administratorem [RODO art. 28 ust. 10; EROD 07/2020 pkt 81].
  Narzędzie używa danych zleceń także do Rozliczeń pracowników (płatności tata–Wykonawca).
  Czy umowa z INEA obejmuje taki cel, sprawdzi pytanie A4.
- Dane własne firmy taty, czyli dane jego pracowników i Wykonawców, w tym adresy, z których przychodzą Raporty wykonawców, tata przetwarza jako administrator.
  Do nich stosuje się art. 30 ust. 1, a nie umowa z INEA.

## 2. Co RODO i wytyczne mówią o dalszym podmiocie

### Tekst RODO

> „Podmiot przetwarzający nie korzysta z usług innego podmiotu przetwarzającego bez uprzedniej szczegółowej lub ogólnej pisemnej zgody administratora. W przypadku ogólnej pisemnej zgody podmiot przetwarzający informuje administratora o wszelkich zamierzonych zmianach dotyczących dodania lub zastąpienia innych podmiotów przetwarzających, dając tym samym administratorowi możliwość wyrażenia sprzeciwu wobec takich zmian.” [RODO art. 28 ust. 2]

- Na dalszy podmiot trzeba nałożyć umową „te same obowiązki ochrony danych” co w umowie administrator–podmiot przetwarzający, a jeśli dalszy podmiot ich nie wypełni, „pełna odpowiedzialność wobec administratora (…) spoczywa na pierwotnym podmiocie przetwarzającym” [RODO art. 28 ust. 4].
- Gwarancje dalszego podmiotu można wykazać m.in. zatwierdzonym kodeksem postępowania albo certyfikacją z art. 42 [RODO art. 28 ust. 5].

### Zgoda szczegółowa a ogólna (EROD 07/2020)

- Umowa musi określić, czy zgoda jest szczegółowa, czy ogólna [EROD 07/2020 pkt 128, 153].
- Zgoda **szczegółowa** wskazuje na piśmie konkretny dalszy podmiot i czynność.
  Każda późniejsza zmiana wymaga nowej zgody, a brak odpowiedzi w terminie oznacza **odmowę** [EROD 07/2020 pkt 155].
- Zgoda **ogólna** powinna mieć kryteria wyboru.
  Podmiot przetwarzający informuje „w odpowiednim czasie” o dodaniu albo zastąpieniu dalszego podmiotu, a brak sprzeciwu w terminie można uznać za zgodę [EROD 07/2020 pkt 156–157].
- W obu przypadkach umowa powinna podać termin na zgodę albo sprzeciw i sposób komunikacji [EROD 07/2020 pkt 158].
- Przed powierzeniem trzeba dać administratorowi listę zamierzonych dalszych podmiotów: każdy z lokalizacją, zakresem działań i dowodem zabezpieczeń [EROD 07/2020 pkt 152].
- Obowiązek informowania jest **aktywny**.
  Nie wystarczy dać administratorowi dostęp do listy podprocesorów aktualizowanej co jakiś czas, trzeba wskazać każdy nowy podmiot [EROD 07/2020 przyp. 54].
  UODO powtarza to w odpowiedzi na pytanie o wykazy podprocesorów i dodaje, że administrator ma mieć „realny wpływ” i możliwość sprzeciwu „zanim nastąpi podpowierzenie” [UODO-Q&A].
- Obowiązki w umowie z dalszym podmiotem mają być „te same” funkcjonalnie, nie słowo w słowo [EROD 07/2020 pkt 160].

### Wzór Komisji (klauzule z art. 28 ust. 7)

Standardowe klauzule umowne Komisji 2021/915 dają dwa warianty klauzuli 7.7 [SCC-915 klauzula 7.7]:

- **Opcja 1, uprzednia szczegółowa zgoda:** wniosek co najmniej [TERMIN] przed skorzystaniem z dalszego podmiotu, lista w załączniku IV.
- **Opcja 2, ogólna pisemna zgoda:** zgoda na podmioty z uzgodnionego wykazu i informacja na piśmie o zmianach z wyprzedzeniem co najmniej [TERMIN], żeby administrator zdążył się sprzeciwić.

Jeśli umowa powierzenia taty opiera się na tym wzorze, te dwa terminy i załącznik IV powiedzą, co tata musi zrobić przed przeniesieniem danych.

### Opinia EROD 22/2024

- Administrator powinien mieć „w każdej chwili” pod ręką tożsamość (nazwę, adres, osobę kontaktową) **wszystkich** podmiotów przetwarzających i dalszych podmiotów, niezależnie od ryzyka.
  Podmiot przetwarzający powinien je przekazywać z własnej inicjatywy i na bieżąco [EROD-Op22/2024, streszczenie].
- Ostateczna decyzja o dalszym podmiocie i weryfikacja jego gwarancji należą do administratora, który może oprzeć się na informacjach od podmiotu przetwarzającego [EROD-Op22/2024, streszczenie].

## 3. Hetzner jako dalszy podmiot

### Umowa powierzenia (AVV / DPA)

- Zawarcie: Hetzner nie podpisuje indywidualnych umów.
  Klient zawiera umowę w panelu konta, zaznaczając zgodę, i wcześniej wpisuje rodzaje danych i kategorie osób (załącznik 1) [Hetzner-Docs].
  Bez tego kroku umowy powierzenia z Hetznerem nie ma.
- Wersja: DPA 1.1 z 10.02.2025, załącznik 2 (TOM) 1.2 z 17.02.2026, załącznik 3 (podwykonawcy) 1.0 z 08.2024 [Hetzner-DPA].
- **Lokalizacja:** świadczenie odbywa się „wyłącznie” w państwie członkowskim UE albo EOG.
  Przekazanie do państwa trzeciego wymaga uprzedniej zgody klienta i warunków z art. 44 i nast. [Hetzner-DPA §3 ust. 1–2].
  Przy lokalizacji serwera w UE dane serwera są przetwarzane wyłącznie w UE, a wsparcie dla wszystkich lokalizacji świadczy się z UE [Hetzner-DPA zał. 3; Hetzner-Sub].
  Kopie zapasowe zostają w UE, jeśli wybrano lokalizację w UE [Hetzner-Docs].
- **Podwykonawcy Hetznera:** klient zgadza się z góry na dalszych podwykonawców.
  Hetzner informuje przed zmianą, klient ma **14 dni** na sprzeciw, a przy braku porozumienia przysługuje mu szczególne prawo wypowiedzenia [Hetzner-DPA §7 ust. 3–4].
  Usługi pomocnicze (telekomunikacja, poczta i transport, konserwacja) nie są podpowierzeniem [Hetzner-DPA §7 ust. 1].
  Na liście z załącznika 3 dla UE jest tylko Hetzner Finland Oy (lokalizacja w Finlandii).
  Pozostałe podmioty dotyczą lokalizacji w USA i Singapurze [Hetzner-Sub].
- **Naruszenia:** Hetzner informuje klienta „immediately” (niezwłocznie) i podaje minimalną treść zgłoszenia [Hetzner-DPA §5 pkt 8].
- **Kontrole:** Hetzner co najmniej raz w roku zleca przegląd TOM niezależnemu podmiotowi i udostępnia wynik w panelu bez opłat.
  Klient może kontrolować dodatkowo, na miejscu najwyżej raz w roku kalendarzowym, w godzinach pracy i po zapowiedzi [Hetzner-DPA §8 ust. 3–4].
- **Koniec umowy:** dane zwraca się albo usuwa na żądanie, a nośnik, którego nie da się wyczyścić, niszczy się [Hetzner-DPA §11].
- **Prawo i sąd:** prawo niemieckie, sąd w siedzibie Hetznera [Hetzner-DPA §13.1].
- **Rozbieżność do sprawdzenia:** DPA Hetznera z góry nazywa klienta administratorem [Hetzner-DPA §1 ust. 3] i nie ma postanowień dla klienta, który sam jest podmiotem przetwarzającym.
  Google i Microsoft mają takie postanowienia (sekcja 5).
  Art. 28 ust. 4 wymaga „tych samych” obowiązków co w umowie taty z INEA, ocenianych funkcjonalnie [EROD 07/2020 pkt 160].
  Jeśli umowa z INEA daje INEA np. prawo audytu dalszych podmiotów albo krótszy termin zgłoszenia naruszenia niż standard Hetznera, standardowa umowa Hetznera może tego nie pokryć (pytania B4, C3).

### Certyfikaty

- ISO/IEC 27001:2022 dla Hetzner Online GmbH i Hetzner Finland Oy, obejmujący infrastrukturę, eksploatację i obsługę klienta w parkach centrów danych w Norymberdze, Falkenstein i Helsinkach, wydany przez SOCOTEC Certification [Hetzner-Cert].
- BSI C5 Type 2 dla usług chmurowych, §8a BSIG (KRITIS), coroczny przegląd TOM przez zewnętrzny podmiot (obecnie TÜV Rheinland) [Hetzner-Certs; Hetzner-TOM pkt 10].
- Hetzner nie ma SOC 2 [Hetzner-Certs].
- Art. 28 ust. 5 RODO mówi o mechanizmach certyfikacji zatwierdzonych na podstawie art. 42, a ISO 27001 do nich nie należy.
  Hetzner wymienia go w DPA jako jeden z dowodów zgodności [Hetzner-DPA §8 ust. 2].

### Co Hetzner zostawia klientowi (serwer chmurowy albo dedykowany)

Według załącznika TOM dla serwerów chmurowych i dedykowanych [Hetzner-TOM]:

| Obszar | Hetzner | Klient (Maks) |
|---|---|---|
| Fizyczny dostęp, zasilanie, ppoż., sieć, ochrona DDoS | ✓ | – |
| Konto klienta: osobne konta, logi dostępu i zmian w panelu, wymagania haseł, opcja 2FA | ✓ | włączyć 2FA |
| Dostęp do maszyny wirtualnej, uprawnienia, aktualizacje systemu | – | ✓ |
| Szyfrowanie danych w spoczynku | – | ✓ („Client’s responsibility”) |
| Szyfrowanie kopii zapasowych | – | ✓ („Client’s responsibility”) |
| Kopie zapasowe i plan odtworzenia | odpłatne kopie i migawki | ✓ |
| Zapora i porty | zapora konfigurowana przez klienta | ✓ |
| Monitoring maszyny | host | ✓ maszyna |
| Logowanie zmian danych, skan wirusów | – | ✓ |

## 4. Minimalne środki techniczne i organizacyjne

RODO nie ma zamkniętej listy.
Administrator i podmiot przetwarzający wdrażają środki „odpowiednie” do ryzyka, „w tym między innymi w stosownym przypadku” [RODO art. 32 ust. 1]:

> a) pseudonimizację i szyfrowanie danych osobowych;
> b) zdolność do ciągłego zapewnienia poufności, integralności, dostępności i odporności systemów i usług przetwarzania;
> c) zdolność do szybkiego przywrócenia dostępności danych osobowych i dostępu do nich w razie incydentu fizycznego lub technicznego;
> d) regularne testowanie, mierzenie i ocenianie skuteczności środków technicznych i organizacyjnych mających zapewnić bezpieczeństwo przetwarzania.

Przy ocenie liczy się ryzyko „przypadkowego lub niezgodnego z prawem zniszczenia, utraty, modyfikacji, nieuprawnionego ujawnienia lub nieuprawnionego dostępu” do danych „przesyłanych, przechowywanych lub w inny sposób przetwarzanych” [RODO art. 32 ust. 2].
Załącznik III do klauzul Komisji 2021/915 wymienia przykładowe środki, które w umowie trzeba opisać „szczegółowo, a nie w sposób ogólny” [SCC-915 zał. III].

| Temat z ticketu | Źródło w prawie | Uwaga |
|---|---|---|
| Szyfrowanie w tranzycie | art. 32 ust. 1 lit. a i ust. 2 („przesyłanych”); zał. III „ochrona danych w czasie ich przekazywania” | Hetzner daje tylko „opcje szyfrowania transferu” zależne od produktu; TLS do aplikacji, IMAP i OneDrive to strona Maksa [Hetzner-TOM pkt 7]. |
| Szyfrowanie w spoczynku | art. 32 ust. 1 lit. a; zał. III „ochrona danych w czasie ich przechowywania” | Na serwerze chmurowym obowiązek klienta [Hetzner-TOM pkt 7]. Microsoft szyfruje dane w spoczynku w usługach online [MS-DPA „Data Encryption”]. |
| Kopie zapasowe | art. 32 ust. 1 lit. b–c | Obowiązek klienta; kopie zostają w UE przy lokalizacji w UE [Hetzner-TOM pkt 9; Hetzner-Docs]. Kopie też są „kopiami”, które przy końcu umowy trzeba usunąć albo zwrócić [RODO art. 28 ust. 3 lit. g]. |
| Dostęp | art. 29, art. 32 ust. 4, art. 28 ust. 3 lit. b; zał. III „identyfikacja i autoryzacja użytkowników” | Każda osoba z dostępem (tata, Andrzej, Maks jako admin, w przyszłości technicy) przetwarza dane tylko na polecenie administratora i jest zobowiązana do tajemnicy. Role z mapy #1145 trzeba zapisać tak, żeby dało się to wykazać. |
| Logi dostępu | zał. III „rejestrowanie zdarzeń”, „rozliczalność”; art. 33 ust. 2 | Podmiot przetwarzający musi naruszenie stwierdzić i „bez zbędnej zwłoki” zgłosić administratorowi [RODO art. 33 ust. 2], a bez logów trudno je stwierdzić. Hetzner loguje tylko panel konta, logi maszyny są po stronie klienta [Hetzner-TOM pkt 2, 8]. |
| Retencja | art. 5 ust. 1 lit. e; art. 28 ust. 3 lit. g; zał. III „ograniczone zatrzymywanie danych” | Historia Rejestru sięga 11.2021. Ile wolno trzymać, określa administrator, więc to pytanie D1. |
| Testy zabezpieczeń | art. 32 ust. 1 lit. d | Regularne testowanie i ocena, np. odtworzenie kopii na próbę. |
| Rejestr czynności | art. 30 ust. 2 i 5 | Podmiot przetwarzający prowadzi rejestr kategorii czynności (dane podmiotu i każdego administratora, kategorie przetwarzań, przekazania poza EOG, ogólny opis środków) [RODO art. 30 ust. 2; UODO-Rejestr]. Wyjątek dla mniej niż 250 osób nie działa, gdy przetwarzanie „nie ma charakteru sporadycznego”. Każdy z warunków wystarcza sam, a „sporadyczne” jest tylko to, co nie dzieje się systematycznie i odbywa się poza regularną działalnością [RODO art. 30 ust. 5; WP29-30(5)]. Codzienna praca na zleceniach INEA wygląda na regularną działalność. UODO udostępnia wzór rejestru kategorii czynności [UODO-Poradniki]. |
| Naruszenia | art. 33 ust. 2; SCC-915 klauzula 9.2 | Terminy dostawców wobec taty: Hetzner „immediately” [Hetzner-DPA §5 pkt 8], Google „promptly and without undue delay” [Google-CDPA 7.2.1], Microsoft bez zbędnej zwłoki i w każdym razie w 72 godziny [MS-DPA]. Administrator ma 72 godziny na zgłoszenie do organu [RODO art. 33 ust. 1], więc umowa z INEA może dać tacie krótszy termin (pytanie C3). |

## 5. Gmail i Microsoft 365 jako kolejne podmioty

### Gmail: konto prywatne a Google Workspace

- **Konto prywatne (w domenie gmail.com):** zgodnie z polityką prywatności Google, jeśli informacja dla danej usługi nie stanowi inaczej, administratorem danych użytkowników w EOG jest Google Ireland Limited [Google-PP].
  Cloud Data Processing Addendum dotyczy „Customer Data” przesyłanych przez Google Workspace w ramach konta Workspace [Google-CDPA, sekcja Workspace pkt 1].
  W dokumentach, które przeczytałem, nie ma umowy powierzenia z art. 28 dla prywatnego konta Gmail.
- **Google Workspace:** Google jest podmiotem przetwarzającym, a klient administratorem albo podmiotem przetwarzającym [Google-CDPA 4.1].
  Gdy klient jest podmiotem przetwarzającym, zapewnia, że administrator zgodził się na polecenia, na Google jako dalszy podmiot i na podprocesorów Google.
  Klient przekazuje też administratorowi zawiadomienia o incydentach i nowych podprocesorach [Google-CDPA 5.1].
  - Podprocesorzy: zgoda ogólna, zawiadomienie co najmniej 30 dni przed nowym podprocesorem, sprzeciw przez wypowiedzenie umowy w 90 dni [Google-CDPA 11.1, 11.4].
  - Lista podprocesorów Workspace obejmuje firmy wsparcia technicznego m.in. w USA, Indiach i na Filipinach.
    Według Google nie mają one dostępu do danych klienta, chyba że klient sam włączy go w zgłoszeniu do wsparcia [Google-Sub].
  - Dane mogą być przetwarzane w każdym kraju, w którym Google albo podprocesorzy mają zaplecze, z zastrzeżeniem zobowiązań co do lokalizacji danych [Google-CDPA 10.1].
  - Przekazania do USA: Google LLC jest certyfikowany w EU-U.S. Data Privacy Framework, a klientom usług biznesowych Google może też włączać do umów standardowe klauzule umowne [Google-DPF].
- Skrzynka z Raportami wykonawców już dziś zawiera numery zleceń od Wykonawców.
  Chmura dodaje serwer, który czyta ją przez IMAP, i hasło aplikacji zapisane na serwerze (ticket #1161).
  Typ konta (prywatne czy Workspace) sprawdzi Maks.

### Microsoft 365 (OneDrive)

- DPA Microsoftu (wydanie z 1.11.2026) jest dodatkiem do Product Terms, czyli warunków licencji komercyjnych [MS-DPA-strona].
- Klient jest administratorem, a Microsoft podmiotem przetwarzającym.
  Gdy klient sam jest podmiotem przetwarzającym, Microsoft jest dalszym podmiotem, a klient zapewnia, że jego polecenia, w tym wyznaczenie Microsoftu, zatwierdził administrator [MS-DPA „Processor and Controller Roles”].
- Do „operacji biznesowych” związanych z usługą Microsoft działa jako niezależny administrator [MS-DPA].
- Nowy podprocesor: zawiadomienie co najmniej 6 miesięcy wcześniej (30 dni dla podprocesorów funkcji AI).
  Brak akceptacji: wypowiedzenie subskrypcji bez kary przed końcem okresu zawiadomienia [MS-DPA „Notice and Controls on use of Subprocessors”].
- Lokalizacja: dla usług EU Data Boundary Microsoft przechowuje i przetwarza dane w UE i EFTA zgodnie z Product Terms.
  Microsoft nie ogranicza, skąd klient i użytkownicy sięgają po dane [MS-DPA „Location of Customer Data”].
- Microsoft jest certyfikowany w EU-U.S. Data Privacy Framework [MS-DPA].
  Szyfruje dane w tranzycie przez sieci publiczne domyślnie i dane w spoczynku w usługach online [MS-DPA „Data Encryption”].
- OneDrive już dziś trzyma pliki taty z danymi klientów, więc pytanie o zgodę INEA dotyczy też stanu obecnego, nie tylko chmury (pytanie B2).

### Przekazywanie poza EOG (art. 44 i nast.)

- Przekazanie do państwa trzeciego wolno tylko na warunkach rozdziału V, także przy dalszych przekazaniach [RODO art. 44].
  Wystarcza decyzja Komisji o odpowiednim stopniu ochrony [RODO art. 45 ust. 1] albo odpowiednie zabezpieczenia, np. standardowe klauzule ochrony danych Komisji [RODO art. 46 ust. 2 lit. c].
- Dla USA decyzja 2023/1795 (Data Privacy Framework) obejmuje organizacje certyfikowane.
  Sąd UE oddalił skargę na nią 3.09.2025 (T-553/23 Latombe) [TSUE-T-553/23], a odwołanie do Trybunału (C-703/25 P) czeka na wyrok [TSUE-C-703/25].
- Z art. 30 ust. 2 lit. c przekazania poza EOG wpisuje się do rejestru kategorii czynności.
- Hetzner przy lokalizacji w UE nie przekazuje danych poza UE [Hetzner-Sub].
  Przekazania mogą się pojawić tylko po stronie Google i Microsoftu.

### Na marginesie: narzędzia Maksa

Mapa #1145 zakłada pełne logi i alerty.
Każda usługa, do której z serwera trafiają dane klientów (np. zewnętrzny monitoring, poczta z alertami, Skrzynka Zgłoszeń na GitHubie, asystent AI przy debugowaniu), jest kolejnym dalszym podmiotem albo odbiorcą.
Reguła danych (ADR 0025) już zatrzymuje `ADRES` i `NUMER UMOWY/ZLECENIA ORANGE`, ale przepuszcza `NUMER ZL.`.
Czy numer zlecenia jest daną osobową dla odbiorcy, który nie może go przypisać osobie, zależy od okoliczności [TSUE C-413/23 P].
To pytanie dla ticketu „Logowanie, role i bezpieczeństwo danych” (#1157), nie dla taty.

## 6. Pytania do taty o umowę z INEA

Wejście do ticketu #1152.
Zapisujemy tam tylko odpowiedzi i wnioski, bez treści umowy.

**A. Strony i zakres**

1. Z kim tata ma umowę o zlecenia: bezpośrednio z INEA czy z firmą pośrednią (np. tą, z którą rozlicza się w efenix)?
   Kto jest w umowie powierzenia administratorem, a kto podmiotem przetwarzającym?
2. Czy jest osobna umowa powierzenia przetwarzania danych osobowych albo rozdział o danych w umowie głównej?
   Z jakiej daty jest ta wersja i czy przyszły do niej aneksy?
3. Jakie dane i kategorie osób umowa wymienia (adresy, numery umów i zleceń, telefony, zdjęcia)?
   Czy obejmuje zlecenia hurt dla innych operatorów (Orange, T-Mobile, Netia i in.) i czy ci operatorzy mają osobne umowy z tatą?
4. Do jakich celów tata może używać danych zleceń?
   Czy umowa obejmuje rozliczenie z INEA (Plik zbiorczy, efenix) i z Wykonawcami (Rozliczenia pracowników)?

**B. Dalsze podmioty przetwarzające**

1. Czy umowa pozwala tacie korzystać z dalszych podmiotów?
   Zgoda szczegółowa (każdy podmiot osobno, na piśmie, przed startem) czy ogólna (informacja i czas na sprzeciw)?
   Jaki termin, jaka forma (pismo, mail) i do kogo po stronie INEA?
2. Czy załącznik albo lista wymienia już jakiś dalszy podmiot (Microsoft OneDrive, Google Gmail, efenix, księgowość)?
   Czy INEA wie, że pliki ze zleceniami leżą dziś w OneDrive i że Raporty wykonawców przychodzą na Gmaila?
3. Czy umowa wymaga przetwarzania tylko w Polsce, tylko w UE/EOG, czy zabrania przekazywania poza EOG?
   Czy wymaga wcześniejszej zgody na każde przekazanie?
4. Czy umowa daje INEA prawo audytu albo kontroli u taty i u jego dalszych podmiotów?
   Na jakich warunkach (zapowiedź, częstotliwość, na miejscu)?
   Hetzner pozwala na kontrolę na miejscu raz w roku w godzinach pracy.
5. Czy umowa każe nałożyć na dalszy podmiot konkretne zapisy (np. wzór INEA)?
   Czy INEA przyjmie standardową umowę dostawcy (Hetzner: prawo niemieckie, sąd w Niemczech)?

**C. Bezpieczeństwo**

1. Czy umowa ma załącznik ze środkami bezpieczeństwa: szyfrowanie, hasła, uwierzytelnianie dwuskładnikowe, VPN, antywirus, blokada ekranu, logi?
   Czy wymaga certyfikatu (np. ISO 27001) od taty albo od dostawców?
2. Czy wymaga imiennych upoważnień i oświadczeń o poufności dla każdej osoby z dostępem (tata, Andrzej, Maks, Wykonawcy)?
3. W jakim terminie (w godzinach?) i jakim kanałem tata musi zgłosić INEA naruszenie ochrony danych?
4. Czy umowa coś mówi o danych na telefonach i prywatnych urządzeniach techników oraz o zdjęciach (dziś w efenix)?
5. Czy oprócz RODO umowa nakłada tajemnicę telekomunikacyjną (komunikacji elektronicznej) albo szerszą klauzulę poufności?

**D. Retencja i koniec umowy**

1. Jak długo po wykonaniu i rozliczeniu zlecenia tata może trzymać jego dane?
   Czy wolno trzymać historię od 11.2021?
2. Co po zakończeniu umowy: zwrot czy usunięcie danych, także kopii zapasowych, i w jakim terminie?
3. Czy INEA kiedyś prosiła o rejestr kategorii czynności, ankietę bezpieczeństwa albo audyt?

**E. Odpowiedzialność**

1. Czy umowa przewiduje kary umowne albo odszkodowanie za naruszenie danych i czy wymaga ubezpieczenia OC?
2. Kto po stronie INEA odpowiada za sprawy powierzenia (inspektor ochrony danych albo opiekun umowy), do kogo tata ma napisać po zgodę?
   Kontakt zostaje u taty, nie trafia do repo.

**Do sprawdzenia przez Maksa (nie przez tatę)**

- Typ konta Gmail ze skrzynką raportów: prywatne czy Workspace.
- Licencja tenanta Microsoft 365 i lokalizacja danych w centrum administracyjnym.
- Zawarcie DPA w panelu Hetznera przed pierwszymi danymi, lokalizacja w UE, 2FA na koncie, szyfrowanie dysku i kopii.

## Źródła

Wszystkie dostępne 2026-11-08.

- [RODO] Rozporządzenie (UE) 2016/679, tekst polski, EUR-Lex: art. 4, 5, 28–30, 32, 33, 44–46, motyw 26.
  https://eur-lex.europa.eu/legal-content/PL/TXT/HTML/?uri=CELEX:32016R0679
- [EROD 07/2020] EDPB, Guidelines 07/2020 on the concepts of controller and processor in the GDPR, wersja 2.1 (przyjęte 7.07.2021, poprawki 20.09.2022).
  https://www.edpb.europa.eu/system/files/documents/2023-10/EDPB_guidelines_202007_controllerprocessor_final_en.pdf
  (wersja polska 2.0, nieskorygowana językowo: https://www.edpb.europa.eu/system/files/documents/2023-10/edpb_guidelines_202007_controllerprocessor_final_pl.pdf)
- [EROD-Op22/2024] EDPB, Opinion 22/2024 on certain obligations following from the reliance on processor(s) and sub-processor(s), przyjęta 7.10.2024.
  https://www.edpb.europa.eu/system/files/2024-10/edpb_opinion_202422_relianceonprocessors-sub-processors_en.pdf
- [SCC-915] Decyzja wykonawcza Komisji (UE) 2021/915 (standardowe klauzule umowne między administratorami a podmiotami przetwarzającymi), klauzule 7.7 i 9, załącznik III.
  https://eur-lex.europa.eu/legal-content/PL/TXT/HTML/?uri=CELEX:32021D0915
- [UODO-Q&A] UODO, „Jakie rozwiązania są wystarczające w przypadku wykazu podmiotów podpowierzających?”.
  https://uodo.gov.pl/pl/676/4259
- [UODO-Rejestr] UODO, „Wskazówki i wyjaśnienia dotyczące obowiązku rejestrowania czynności i kategorii czynności przetwarzania określonego w art. 30 ust. 1 i 2 RODO”.
  https://uodo.gov.pl/pl/file/708
- [UODO-Poradniki] UODO, Poradniki i wskazówki (2018–2020), wzór rejestru kategorii czynności.
  https://uodo.gov.pl/pl/383/214
- [WP29-30(5)] Stanowisko Grupy Roboczej Art. 29 w sprawie wyjątków od obowiązku prowadzenia rejestru (art. 30 ust. 5 RODO), w serwisie UODO.
  https://uodo.gov.pl/data/filemanager_pl/690.pdf
- [INEA-KI] INEA, Klauzula informacyjna dla klientów (2024), pkt 5.
  https://www.inea.pl/sites/default/files/2024-10/Klauzula_informacyjna_klienci_INEA_2024_01_FL.pdf
- [Hetzner-DPA] Hetzner, Data Processing Agreement in Accordance with Article 28 of the GDPR, wersja 1.1 z 10.02.2025, z załącznikami 1–3.
  https://www.hetzner.com/AV/DPA_en.pdf (wersja niemiecka: https://www.hetzner.com/AV/DPA_de.pdf)
- [Hetzner-TOM] Załącznik 2 do DPA, Technical and Organizational Measures, wersja 1.2 z 17.02.2026 (w tym samym PDF).
- [Hetzner-Sub] Anlage 3 zum AV-Vertrag, Genehmigte Subunternehmer, wersja 1.0 z 06.08.2024.
  https://www.hetzner.com/AV/subunternehmer.pdf
- [Hetzner-Docs] Hetzner Docs, Datenschutz bei Hetzner / Data protection at Hetzner.
  https://docs.hetzner.com/general/company-and-policy/data-protection-at-hetzner/
- [Hetzner-Cert] Hetzner, Zertifizierung (ISO/IEC 27001).
  https://www.hetzner.com/unternehmen/zertifizierung
- [Hetzner-Certs] Hetzner Docs, Certificates.
  https://docs.hetzner.com/general/others/certificates
- [Google-CDPA] Google, Cloud Data Processing Addendum (Customers), ostatnia zmiana 30.10.2026 (obejmuje Google Workspace).
  https://cloud.google.com/terms/data-processing-addendum/
- [Google-Sub] Google Workspace Subprocessors, ostatnia zmiana 19.10.2026.
  https://workspace.google.com/intl/en/terms/subprocessors.html
- [Google-PP] Google, Polityka prywatności, obowiązuje od 16.10.2026 (sekcja o administratorze danych).
  https://policies.google.com/privacy?hl=en-GB&gl=pl
- [Google-DPF] Google, Data transfer frameworks, obowiązuje od 23.08.2025.
  https://policies.google.com/privacy/frameworks?hl=en
- [MS-DPA] Microsoft Products and Services Data Protection Addendum (WW), wydanie z listopada 2026.
  https://www.microsoft.com/licensing/docs/documents/download/MicrosoftProductandServicesDPA(WW)(English)(November_2026)(CR).docx
- [MS-DPA-strona] Microsoft, strona DPA w Licensing Documents.
  https://www.microsoft.com/licensing/docs/view/Microsoft-Products-and-Services-Data-Protection-Addendum-DPA
- [TSUE-T-553/23] Sąd UE, komunikat prasowy 106/25 z 3.09.2025, Latombe przeciwko Komisji.
  https://curia.europa.eu/site/upload/docs/application/pdf/2025-09/cp250106en.pdf
- [TSUE-C-703/25] TSUE, sprawa C-703/25 P Latombe przeciwko Komisji (odwołanie, w toku).
  https://infocuria.curia.europa.eu/tabs/affair?lang=EN&searchTerm=%22C-703%2F25%22&publishedId=C-703%2F25+P
- [TSUE C-413/23 P] TSUE, wyrok z 4.09.2025, EDPS przeciwko SRB (pojęcie danych osobowych), komunikat prasowy 107/25.
  https://curia.europa.eu/site/upload/docs/application/pdf/2025-09/cp250107en.pdf
