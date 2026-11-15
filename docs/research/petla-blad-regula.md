# Pętla błąd → reguła: kto to zbudował i co przejąć

Badanie z 15.11.2026. Rozwija badanie z 14.11.2026 (34 źródła, notatka lokalna poza repo) i nie powtarza go: Tricorder, Meta 0% list wobec 70% w diffie, mutacje Google, zapadki i OpenAI harness są tam. Tu cytuję je tylko numerem „R14.11”.
Każde twierdzenie ma numer źródła [Sn] z listy na końcu. „Niepotwierdzone” znaczy: nie znalazłem źródła pierwotnego.

## Werdykt

1. Nikt publicznie nie zamyka pętli „błąd → egzekwowana reguła → dowód, że reguła łapie ten błąd” automatycznie. Najbliżej są Factory (LLM pisze regułę ESLint z testami, bez żadnej liczby) [S10] i Revisar (grupuje poprawki z historii we wzorce, człowiek robi z nich quick fixy) [S7].
2. Wielcy gracze uczą się z poprawek, ale wynikiem jest poprawka dla istniejącego detektora (Getafix, SapFix) [S1, S3] albo komentarz modelu z linkiem do reguły (Google AutoCommenter) [S6], a nie nowy deterministyczny strażnik.
3. Recenzenci AI (CodeRabbit, Cursor Bugbot, Greptile, Semgrep Memories) i Anthropic zapisują lekcje prozą dla modelu [S11, S12, S15, S16, S18]. Skuteczność mierzy publicznie tylko Greptile, i to jako filtr szumu (19% → 55% komentarzy zaadresowanych) [S17].
4. Mistake hunt po transkryptach istnieje jako narzędzie (Claude Code `/insights`, pstack `/reflect`, Docent) [S20, S23, S26], ale każde kończy się prozą (CLAUDE.md, skill) albo raportem, a nie regułą z dowodem.
5. Dla nas najcenniejsze są trzy rzeczy: miara użyteczności każdej reguły w czasie z wyłączaniem złych (AutoCommenter, Bugbot) [S6, S15], test kontraktu po rejestrze dla klasy „brak testu gałęzi” [S29, S30] i droga Google dla CRLF: reguła z poprawką, sprzątnięcie całego repo, dopiero potem błąd (R14.11, [S5]).

## Kto to zbudował

| System | Wejście | Wyjście | Kto zatwierdza | Dowód skuteczności i liczby | Źródło |
|---|---|---|---|---|---|
| Meta Getafix | Ludzkie poprawki zgłoszeń Infer (np. 2 288 poprawek null) | Wzorce poprawek z „dziurami”, łatka w review i kandydaci dla SapFix | Inżynier w review | Łatka musi się kompilować, a Infer zamilknąć. Pierwsza łatka równa ludzkiej w ~25% z 200 małych edycji. Instagram: 1 077 z ~2 000 błędów (53%). Fix rate z 56% na 62% i z 51% na 59% przy pokazaniu propozycji | [S1, S2] |
| Meta SapFix | Crash z Sapienz i Infer przed produkcją | Łatka: revert, szablon z Getafix albo mutacja AST | Recenzent, „engineers are always in the loop” | Kompilacja, crash znika, brak nowych crashy, testy. Odsetka przyjętych łatek wpis nie podaje (niepotwierdzone) | [S3] |
| Google Error Prone i Tricorder | Wzorzec znany ekspertowi domeny | Check w kompilatorze albo analizator w review, z poprawką | Autor checka według kryteriów, sprzątnięcie repo przed włączeniem | Test pozytywny i negatywny (`CompilationTestHelper`). 733 checki od 162 autorów (01.2018), 146 analizatorów, 125 spoza zespołu. Próg wyłączenia: >10% „Not useful” | [S4, S5], R14.11 |
| Google AutoCommenter | ~800 tys. komentarzy recenzentów z URL do dokumentu dobrej praktyki | Komentarz modelu w review i IDE z tym URL | Brak zatwierdzania reguły. Zespół tłumi URL po ocenie | 330 URL. Użyteczność z 54% na 80% po wyłączeniu 22 URL, progach per URL i ręcznie poprawionych streszczeniach najczęstszych URL. ~40% komentarzy rozwiązanych. 33 z 50 najczęstszych praktyk (66%) są poza zasięgiem analizy statycznej | [S6] |
| Google ML resolution | Komentarz recenzenta | Propozycja edycji | Autor zmiany | 52% komentarzy przy precyzji 50% (offline). 40 do 50% podejrzanych edycji zastosowanych | [S19] |
| Revisar (badanie) | Commity 9 projektów Java | Grupy podobnych edycji jako wzorce, potem quick fix analizatora | Twórca analizatora | 89 wzorców, 64% nieobecnych w narzędziach, 6 z 16 PR-ów przyjętych | [S7] |
| Uber Piranha | Flagi bez zmian dłużej niż próg (np. 8 tygodni) | Diff usuwający kod flagi | Autor flagi jako recenzent | 1 381 flag, 65% diffów scalonych bez zmian, ponad 85% kompiluje się i przechodzi testy. To sprzątanie, nie reguła | [S8, S9] |
| Factory | Dryf z review, testów, incydentów | Reguła ESLint napisana przez LLM (severity, autofix, testy, docs), agenci sprzątają | Człowiek pisze standard w AGENTS.md | Brak liczb. „dozens of rules”. Reguła wchodzi jako ostrzeżenie, potem błąd | [S10] |
| OpenAI harness | Odstępstwa od „golden principles” | Własne linty z instrukcją naprawy, PR-y sprzątające, doc-gardening | Agent-to-agent, automerge | Brak pomiaru reguł, tylko skala (~1 500 PR-ów) | R14.11 |
| Anthropic (secure SDLC) | Odkryta klasa błędu, dawne incydenty | Aktualizacja CLAUDE.md i skilli, RAG z incydentów dla agentów review, SAST na PR | Twarda bramka review w CI. Hook PreToolUse jako opcja | ~1/3 błędów z dawnych incydentów claude.ai złapałaby obecna automatyzacja. PR-y z istotnym komentarzem z 16% na 54% | [S11] |
| Semgrep Memories | Triage „ignore” z powodem, „Customize fix”, wpis admina | Proza dla LLM: wskazówki naprawy i ukrywanie podobnych wyników. Nie reguła Semgrep | Admin aktywuje sugerowane | Dla Memories brak liczb. Ogólnie „over 95% accurate” w klasyfikacji fałszywych alarmów. Osobno beta 2024: reguła z przykładu złego i dobrego kodu | [S12, S13] |
| Cursor Bugbot | Aktywność na PR po merge'u albo zamknięciu, `@cursor remember` | „Learned rules” prozą, same się włączają i wyłączają | Nikt, tylko przełącznik organizacji | Panel: acceptance rate per reguła. Publicznych liczb brak | [S15] |
| CodeRabbit | Odpowiedź do bota w PR | Zdanie prozą z embeddingiem | `approval_delay` 0 do 30 dni, domyślnie 0 | Tylko użycie: „Usage”, „Never Used”. Brak miary skuteczności | [S16] |
| Greptile | 👍/👎 i odpowiedzi | Filtr: komentarz podobny do ≥3 odrzuconych jest blokowany | Nikt | Address rate (z diffów kolejnych commitów) z 19% na 55+% w dwa tygodnie | [S17, S18] |

Co z tego wynika:
- Deterministyczną regułę dostaje się tam, gdzie człowiek ją pisze i testuje na pozytywnych i negatywnych przypadkach (Error Prone, Semgrep `ruleid:`/`ok:`) [S4, S14]. Semgrep ma też `todoruleid:` na znaną lukę, która nie psuje testu [S14]. To dokładnie nasze `ZNANE_LUKI`.
- Uczenie bez człowieka daje prozę albo filtr. Jedyne liczby skuteczności mierzą to, czy autor zareagował (Greptile, AutoCommenter), a nie to, czy klasa błędu wróciła.
- Zarządzanie regułą w czasie to standard: progi i tłumienie per URL (AutoCommenter), acceptance rate per reguła (Bugbot), „Not useful” (Tricorder) [S6, S15].

## Klasy niesyntaktyczne

### Brak testu dla nowej gałęzi

- **Pokrycie zmiany w review (Google).** Pokrycie liczy się automatycznie dla każdej zmiany i pokazuje w Critique. 45% autorów korzysta z niego „Often” albo „Very Often”, 10% nigdy (512 odpowiedzi z 3 000) [S21]. Google nie wymusza progu globalnie. Dobrowolne poziomy mają pokrycie zmiany 70%, 80% i 90% [S21].
- **Koszt.** Najczęstsza przyczyna nieudanego pomiaru to wydajność: instrumentacja wydłuża testy (timeouty, brak pamięci). Druga to flaky testy. Pokrycie zmiany liczy się tylko wtedy, gdy wszystkie testy przeszły [S21].
- **diff-cover.** Porównuje raport XML z `git diff` i `--fail-under=N` kończy się błędem poniżej progu, tylko dla nowych i zmienionych linii [S22]. README mówi o liniach. Czy liczy też gałęzie, nie sprawdziłem.
- **Pokrycie nie dowodzi asercji.** Dlatego Google dokłada mutacje w diffie (R14.11). Programiści, którzy widzieli mutanty, piszą więcej testów, a mutanty są sprzężone z prawdziwymi błędami (~15 mln mutantów) [S24].
- **Test kontraktu.** JUnit pokazuje kontrakt jako interfejs testów, który klasa testowa implementuje (`EqualsContract`, `ComparableContract`) [S29]. To wymaga decyzji autora. Wersja „po rejestrze” (`pytest_generate_tests` parametryzuje test po liście implementacji) daje test każdej nowej implementacji bez decyzji autora [S30]. Liczb skuteczności tego wzorca w źródłach pierwotnych nie znalazłem (niepotwierdzone).

### Zasób zostawiony otwarty

- **Python.** Domyślnie niezamknięty plik nie daje ostrzeżenia. Tryb `-X dev` pokazuje `ResourceWarning`, `-W error` robi z niego błąd, a `-X tracemalloc` podaje miejsce otwarcia [S25].
- **pytest.** Od 6.2 wykrywa wyjątki niemożliwe do zgłoszenia (np. z `__del__`) i nieobsłużone w wątkach [S27]. 8.4 dodało ślad `tracemalloc` [S28]. 9.1 naprawiło lukę: wyciek wykryty późno przechodził po cichu mimo filtra `error` [S28]. Na `origin/main` 15.11.2026 repo ma pytest 8.3.3 i żadnego `filterwarnings` w `pyproject.toml`.
- **Playwright.** `context` i `page` mają zasięg funkcji i są niszczone na końcu testu, `browser` ma zasięg sesji [S31]. Zasób należy do fixture, a nie do testu.
- **Lint.** Ruff `SIM115` zgłasza `open()` bez menedżera kontekstu, także `Path.open` i `tempfile` [S32]. W repo nie jest włączony (stan 15.11.2026).
- **RAII.** Czas życia zasobu wiąże się z czasem życia obiektu, a zwolnienie dzieje się w destruktorze [S33]. W Pythonie odpowiednikiem jest menedżer kontekstu.
- **Granica.** `ResourceWarning` widzi tylko obiekty Pythona. Okno w innym procesie (Excel, przeglądarka efenix) go nie da. Liczb skuteczności wykrywania wycieków w źródłach nie znalazłem (niepotwierdzone).

## Mistake hunt

**Claude Code `/insights`.** Dokumentacja: raport HTML z ostatnich sesji na tej maszynie, w tym „where things go wrong” [S20]. Prompty w binarce 2.1.325 pokazują mechanizm [S34]. Każdą sesję model streszcza do JSON z polem `friction_counts` w zamkniętej liście: `misunderstood_request`, `wrong_approach`, `buggy_code`, `user_rejected_action`, `excessive_changes`. Agregat daje 3 kategorie tarcia z przykładami i pole `claude_md_additions` z regułą: „PRIORITIZE instructions that appear MULTIPLE TIMES … in 2+ sessions”. Wynik to proza do CLAUDE.md. Ta sama dokumentacja mówi, że CLAUDE.md i auto memory to „context, not enforced configuration”, a do blokowania służy hook PreToolUse [S35].

**pstack `/correct`, `/reflect`, `/recall`** (lokalnie, 0.15.42) [S23]:
- `/correct`: wejście to commity, reverty, komentarze review, pliki instrukcji i komentarze o obejściach. Klasa liczy się po dwóch wystąpieniach. Drabina: architektura, typy, lint z nazwą poprawki, test, a docs na końcu. Każdy nowy check musi paść na prawdziwym dawnym błędzie, wyjątek w linii z datą i zgodą człowieka.
- `/reflect`: trzech recenzentów (osąd, narzędzia, rozbieżny) czyta bieżący transkrypt, a syntetyzator daje Accepted, Rejected i Backlog. Punkt, który lepiej wymusi lint albo skrypt, idzie do Backlogu. Edycje dopiero po zgodzie użytkownika.
- `/recall`: równoległe podagenty po transkryptach, każdy zwraca m.in. „struggles and corrections”.
- Wszystkie trzy uruchamia człowiek (`disable-model-invocation: true`), żaden nie jest cykliczny.

**Cursor Bugbot** uczy się po każdym scalonym albo zamkniętym PR i potrafi przejść historię wstecz [S15]. To najbliższe cyklicznemu przeszukaniu historii review, ale wynik to proza.

**Anthropic** zamyka pętlę w CLAUDE.md: „Once an agent discovers a bug class, the relevant file is updated”. Agenci review mają RAG z dawnych incydentów [S11].

**Badania.**
- MAST (Cemri i in.): grounded theory na 150 trajektoriach, 6 ekspertów, ponad 20 h każdy, 3 rundy zgodności, κ = 0,88. Wynik: 14 trybów porażki w 3 kategoriach. Sędzia LLM (o1, few-shot) ma trafność 0,94 i κ = 0,77 wobec ludzi, zero-shot κ = 0,58. Interwencje z taksonomii dały +9,4% i +15,6% sukcesu [S26].
- Docent (Transluce): model wyciąga krótkie opisy dopasowania z każdego transkryptu, duży model proponuje centroidy, mały przypisuje, potem heurystyka szuka rozłącznych i wyczerpujących klastrów. Autorzy piszą „summaries often contain false positives” i nie podają trafności [S36].
- ACE (Zhang i in.): kontekst jako „playbook” zmieniany przyrostowymi deltami po informacji z wykonania, +10,6% na benchmarkach agentów [S37]. Wynik to proza w kontekście.

**OpenAI i Cursor.** Wpisu inżynierskiego o cyklicznym przeszukiwaniu transkryptów agentów nie znalazłem (niepotwierdzone).

Wzór we wszystkich: wejściem są transkrypty, komentarze PR albo reverty. Grupuje model albo człowiek (MAST: człowiek do nasycenia, potem sędzia LLM). Z klasy powstaje proza, a decyzję o zmianie struktury zawsze podejmuje człowiek. ADR 0036 grupuje inaczej: jawnym polem `Idiom:` od recenzenta, bo zgodności grupowania modelem nikt nie zmierzył. MAST pokazuje, że da się ją zmierzyć: κ 0,58 bez przykładów, 0,77 z przykładami [S26].

## Co przejąć u nas

### Ogólnie

1. **Użyteczność każdej reguły w czasie.** ADR 0036 mierzy fałszywe alarmy reguły tylko przy przyjęciu (≤10% na 20 PR-ach). AutoCommenter, Bugbot i Tricorder mierzą stale i wyłączają złe reguły [S6, S15], R14.11. Propozycja: rejestr korzeni co tydzień liczy dla każdej reguły ast-grep, `banned-api` i kontraktu import-linter liczbę odpaleń na dodanych liniach i to, czym się skończyły (poprawka albo zmiana reguły). Reguła z powtarzaną zmianą bez poprawki to kandydat do przeglądu.
2. **Cykliczny mistake hunt, który kończy się propozycją reguły, a nie prozą.** Wejście: Ważne z werdyktów (`Gdzie`, `Idiom`), diffy poprawek po `FAIL` i korekty Maksa w transkryptach. Każdy przypadek dostaje JSON jak w `/insights` [S34], ale z naszą zamkniętą listą kodów i polem „trigger”. Grupowanie modelem (jak Docent) tylko proponuje kandydatów. Model może naszkicować regułę z próbkami jak u Factory [S10] albo grupę edycji jak Revisar [S7]. Przyjęcie zostaje przy ADR 0036: drugie wystąpienie i dowód `tools/na_scalonych_pr.py`. Nigdy nie wypisywać `claude_md_additions`.
3. **Zgodność grupowania mierzyć jak MAST** [S26], jeśli kiedyś model ma zastąpić pole `Idiom:`: kilka trajektorii oceniają niezależnie dwie osoby, potem sędzia, i liczymy κ.
4. **Nie przejmować pamięci prozą** (CodeRabbit, Bugbot, Semgrep Memories). Żadne z nich nie publikuje, że błąd przestał wracać.

### (a) Gałąź „plik nieczytelny” w kodzie Ustawień bez testu, 4 razy (#1529, #1532, #1572, #1577)

Najlepszy znaleziony system to Google: pokrycie zmiany w review plus mutant na linii w diffie [S21, S24]. To jednak wykrycie po fakcie. Wyżej na drabinie stoi test kontraktu po rejestrze [S30]:
- Każda sekcja Ustawień rejestruje się w jednym rejestrze. Test struktury sprawdza, że każda klasa sekcji w pakiecie jest w rejestrze.
- Jeden test parametryzowany po rejestrze podaje każdej sekcji plik nieczytelny i sprawdza wynik właściciela. Nowa sekcja dostaje ten test bez decyzji autora.
- Zapasowo: `diff-cover --fail-under=100` tylko dla pakietu Ustawień [S22]. To zamienia `Idiom: bez reguły brak-testu` w strukturę dla tej jednej klasy.

### (b) Funkcja napędu GUI zostawia otwarte okno

- Okno otwiera tylko właściciel jako menedżer kontekstu (RAII [S33]). Reguła ast-grep odmawia wywołania otwarcia poza `with` i poza właścicielem, na wzór `SIM115` [S32].
- Fixture autouse w testach napędu robi zdjęcie okien i procesów przed testem i po nim, a różnica kończy test błędem. Tak Playwright wiąże `context` z testem [S31].
- Dla zasobów Pythona: `filterwarnings = ["error::ResourceWarning", "error::pytest.PytestUnraisableExceptionWarning"]` i pytest co najmniej 9.1, bo 8.3.3 nie ma śladu `tracemalloc` ani poprawki późnego wycieku [S25, S28].
- Niepotwierdzone: czy obiekty napędu w repo trzymają uchwyt, który Python w ogóle uzna za zasób.

### (c) Logika domeny w trasie HTTP zamiast u właściciela

- Szczebel (a): kontrakt import-linter, w którym moduły tras importują z domeny tylko fasadę właściciela. To warstwy OpenAI (R14.11) i „architectural boundaries” Factory [S10].
- Reguła `regula-w-trasie` z `reguly-ast-grep/` łapie 15.11.2026 tylko odmowę obok zapisu Ustawień, więc ogólna klasa jest szersza niż ona.
- Resztę z osądem zostawia się recenzentowi. AutoCommenter pokazuje, że 66% praktyk z review nie da się wyrazić analizą statyczną [S6]. Komentarz powinien wtedy nieść link do dokumentu reguły, a reguła mieć swoją miarę użyteczności (punkt 1).

### (d) Stary zapis pliku bez ustalonego końca linii plus nowe porównanie bajt w bajt

Najlepszy znaleziony system to droga Clang i Error Prone: check z poprawką, automatyczne sprzątnięcie wszystkich wystąpień, dopiero potem twardy błąd (R14.11, [S5]).
- Reguła ast-grep z `fix:` dla zapisu tekstowego bez `newline=` (`open` w trybie `w` i `a`, `Path.write_text`) w `src/` i `tools/`. `write_text` ma `newline` od Pythona 3.10, a domyślne `None` zamienia `\n` na `os.linesep` [S38].
- Ruff `PLW1514` sprawdza tylko `encoding`, jest w preview, a jego poprawka jest „unsafe” [S39]. Gotowej reguły na `newline=` nie znalazłem (niepotwierdzone).
- Sprzątnięcie starych zapisów w tym samym PR, żeby reguła nie miała wyjątków.
- Istniejąca 15.11.2026 `kotwica-konca-linii` pilnuje tylko `$` w regexach w `tools/`, więc to inna forma tej samej klasy CRLF.

## Źródła

- [S1] Meta, „Getafix: How Facebook tools learn to fix bugs automatically”, 2018. https://engineering.fb.com/2018/11/06/developer-tools/getafix-how-facebook-tools-learn-to-fix-bugs-automatically/
- [S2] Bader i in., „Getafix: Learning to Fix Bugs Automatically”, OOPSLA 2019. https://arxiv.org/abs/1902.06111
- [S3] Meta, „Finding and fixing software bugs automatically with SapFix and Sapienz”, 2018. https://engineering.fb.com/2018/09/13/developer-tools/finding-and-fixing-software-bugs-automatically-with-sapfix-and-sapienz/
- [S4] Error Prone, „Writing a check”. https://github.com/google/error-prone/wiki/Writing-a-check
- [S5] Sadowski i in., „Lessons from Building Static Analysis Tools at Google”, CACM 2018. https://cacm.acm.org/research/lessons-from-building-static-analysis-tools-at-google/ (DOI https://doi.org/10.1145/3188720)
- [S6] Vijayvergiya i in., „AI-Assisted Assessment of Coding Practices in Modern Code Review”, AIware 2024. https://arxiv.org/html/2405.13565v1
- [S7] Rolim i in., „Learning Quick Fixes from Code Repositories”, 2018. https://arxiv.org/abs/1803.03806
- [S8] Uber, „Introducing Piranha: An Open Source Tool to Automatically Delete Stale Code”, 17.03.2020. https://www.uber.com/blog/piranha/
- [S9] Ramanathan i in., „Piranha: Reducing Feature Flag Debt at Uber”, ICSE-SEIP 2020. https://github.com/uber/piranha/blob/master/report.pdf
- [S10] Factory, A. Sng, „Using Linters to Direct Agents”, 5.09.2025. https://factory.com/news/using-linters-to-direct-agents
- [S11] Anthropic, J. Clinton, „How Anthropic secures its AI-native software development lifecycle”, 21.07.2026. https://claude.com/blog/how-anthropic-secures-its-ai-native-software-development-lifecycle
- [S12] Semgrep, „Customize” (Memories). https://docs.semgrep.dev/semgrep-assistant/customize
- [S13] Semgrep, C. Li, „10x your AppSec program with Semgrep Assistant”, 20.03.2024. https://semgrep.dev/blog/2024/assistant-ga-launch/
- [S14] Semgrep, „Testing rules”. https://docs.semgrep.dev/writing-rules/testing-rules
- [S15] Cursor, „Bugbot”. https://cursor.com/docs/bugbot
- [S16] CodeRabbit, „Learnings”. https://docs.coderabbit.ai/knowledge-base/learnings
- [S17] Greptile, D. Gupta, „How to Make LLMs Shut Up”, 18.12.2024. https://www.greptile.com/blog/make-llms-shut-up
- [S18] Greptile, „Training the Learning System”. https://www.greptile.com/docs/code-review/training-the-learning-system
- [S19] Google Research, „Resolving code review comments with ML”, 23.05.2023. https://research.google/blog/resolving-code-review-comments-with-ml/
- [S20] Claude Code, „Commands” (`/insights`). https://code.claude.com/docs/en/commands
- [S21] Ivanković, Petrović, Just, Fraser, „Code Coverage at Google”, ESEC/FSE 2019. https://storage.googleapis.com/gweb-research2023-media/pubtools/5172.pdf
- [S22] diff-cover, README. https://github.com/Bachmann1234/diff_cover
- [S23] pstack 0.15.42, skille `correct`, `reflect`, `recall`, lokalnie `~/.claude/plugins/cache/cursor-plugins/pstack/0.15.42/skills/`.
- [S24] Petrović, Ivanković, Fraser, Just, „Does mutation testing improve testing practices?”, ICSE 2021. https://arxiv.org/abs/2103.07189
- [S25] Python, „Python Development Mode”. https://docs.python.org/3/library/devmode.html
- [S26] Cemri i in., „Why Do Multi-Agent LLM Systems Fail?”, 2025. https://arxiv.org/html/2503.13657
- [S27] pytest, „Unraisable and unhandled thread exceptions”. https://docs.pytest.org/en/stable/how-to/failures.html
- [S28] pytest, changelog (#12958 w 8.4.0, #14263 w 9.1.0). https://raw.githubusercontent.com/pytest-dev/pytest/main/doc/en/changelog.rst
- [S29] JUnit, „Test Interfaces and Default Methods”. https://docs.junit.org/current/writing-tests/test-interfaces-and-default-methods.html
- [S30] pytest, „How to parametrize” (`pytest_generate_tests`). https://docs.pytest.org/en/stable/how-to/parametrize.html
- [S31] Playwright, „Pytest plugin reference”. https://playwright.dev/python/docs/test-runners
- [S32] Ruff, `SIM115`. https://docs.astral.sh/ruff/rules/open-file-with-context-handler/
- [S33] cppreference, „RAII”. https://en.cppreference.com/w/cpp/language/raii
- [S34] Claude Code 2.1.325, prompty `/insights` w binarce (`strings ~/.local/share/claude/versions/2.1.325`, 15.11.2026).
- [S35] Claude Code, „How Claude remembers your project”. https://code.claude.com/docs/en/memory
- [S36] Transluce, „Introducing Docent”, 24.03.2025. https://transluce.org/docent/blog/introducing-docent
- [S37] Zhang i in., „Agentic Context Engineering”, ICLR 2026. https://arxiv.org/abs/2510.04618
- [S38] Python, `pathlib.Path.write_text`. https://docs.python.org/3/library/pathlib.html
- [S39] Ruff, `PLW1514`. https://docs.astral.sh/ruff/rules/unspecified-encoding/
