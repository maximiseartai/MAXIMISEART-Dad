// Reguły frontendu z CODING_STANDARDS, których Oxlint nie wyraża (brak no-restricted-syntax w Oxlint 1.88):
// 1. Każda właściwość schematów kontraktu (src/api/openapi.json) jest użyta w src poza generated/ (field-use.mjs):
//    kod wartości sięga do jej symbolu z typu Schema (types.gen.ts) albo kształtu zSchema (zod.gen.ts), co
//    rozstrzyga checker TypeScriptu, nie nazwa. Użycie to odczyt (`.pole`, `["pole"]`, `x[klucz]` z kluczem typu
//    literału, destrukturyzacja, `"pole" in x`) albo zapis (klucz literału obiektu, np. wysyłane ciało, atrybut JSX),
//    także przez typ, do którego wartość płynie (zmienna, `Pick<…>`, typ propsów, ograniczenie parametru typu, wynik
//    funkcji, parametr funkcji podanej jako callback, przeciążenia, parametr reszty): odczyt pola celu czyta źródło,
//    a zapisane pole źródła trafia do celu. Wzmianka w typie (`RunInfo["process"]`) nie jest użyciem.
//    Gdzie typy są pewne, reguła jest dokładna: wariant unii płynie tylko w warianty, do których da się go przypisać,
//    a literał w unii zapisuje tylko warianty, które przyjmują jego typ (bez sprawdzania nadmiaru kluczy).
//    Gdzie przepływu nie umie prześledzić, wraca do nazwy pola, żeby nie dać fałszywego „nieużyte” na kodzie, który
//    przyjmuje `tsc -b`:
//    - odczyt pola bez symbolu (wartość `any`, sygnatura indeksu, `"pole" in x` w strażniku typu na `unknown`) i odczyt
//      pola typu, w który płynie wartość `any`/`unknown` (`x as unknown as T`, `JSON.parse(…) as T`), czyta każde pole
//      kontraktu tej nazwy;
//    - pole zapisane w wartość, która wpływa w `any`/`unknown` (też parametr typu bez ograniczenia), trafia do pola tej
//      nazwy w każdym typie, w który `any`/`unknown` płynie (`{ … } as unknown as IntermaxRestoreRequest`);
//    - wariant, którego nie da się przypisać do żadnego wariantu celu (`as` do typu węższego), i literał, którego nie
//      przyjmuje żaden wariant unii, łączą się z każdym wariantem celu po nazwie pola.
//    Granice, które łapie tylko przegląd: pole czytane tylko w kodzie ogólnym, do którego wartość wpływa jako
//    `any`/`unknown` albo `object` (`Object.entries`, `JSON.stringify`), reguła uznaje za nieużyte, więc potrzebuje
//    ono wpisu w FIELDS_OUTSIDE_UI; literał typu odpowiedzi serwera (atrapa, optymistyczna aktualizacja), typ, w który
//    płyną wartości kilku typów (odczyt `T.title` czyta `title` każdego z nich), i powrót do nazwy liczą pole jako
//    użyte, choć UI go nie czyta.
// 2. Przeglądarka nie porównuje nazwy procesu: żadnego `=== "settlement"` ani `case "preparation":`.
// 3. Sieć (fetch, EventSource, WebSocket, XMLHttpRequest, sendBeacon) i JSON.parse tylko w plikach z NETWORK_FILES,
//    które parsują każdą odpowiedź serwera schematem z kontraktu. Wpis w NETWORK_FILES ma powód, a zbędny wpis
//    wywraca regułę. Granica: destrukturyzację (`const { parse } = JSON`), `JSON["parse"]`, `Reflect.get`,
//    `Response.json()` i to, czy plik z NETWORK_FILES parsuje odpowiedź schematem, łapie tylko przegląd.
import { readFileSync } from "node:fs"
import { join, relative } from "node:path"
import ts from "typescript"
import { compilerConfig, fieldUse, isHandWritten, isInType, root, source } from "./field-use.mjs"

// Schematy kontraktu spoza UI; każdy z uzasadnieniem.
const SCHEMAS_OUTSIDE_UI = new Map([
  ["HTTPValidationError", "domyślny błąd walidacji FastAPI; przeglądarka pokazuje własny Komunikat błędu"],
  ["ValidationError", "domyślny błąd walidacji FastAPI, część HTTPValidationError"],
])

// Pola kontraktu, których UI nie pokazuje; każde z uzasadnieniem. Pole użyte w src trzeba stąd usunąć.
// Wpisy z „do usunięcia z kontraktu” znalazła reguła 1 na typach (N11c, 8.11.2026): UI ich nie czyta, a usunięcie
// zmienia contract.py, czyli inną naprawę rozplątania.
const FIELDS_OUTSIDE_UI = new Map([
  ["Health.service", "czyta je launcher Centrum (launcher.py), nie przeglądarka"],
  ["RunEvent.sequence", "numer zdarzenia strumienia SSE, nie treść dla taty"],
  ["Closing.state", "potwierdzenie zamknięcia; przeglądarce wystarcza odpowiedź bez odmowy"],
  ["Decision.title", "okno Decyzji taty pokazuje `question`; do usunięcia z kontraktu"],
  ["IntermaxRestored.previous", "wynik przywrócenia pokazuje przywróconą Kopię, a stan sprzed niej jest na liście Kopii; do usunięcia z kontraktu"],
  ["KindTableReady.kind", "strona rodzaju zna go z adresu; do usunięcia z kontraktu"],
  ["LoggedOutcome.ending", "UI czyta `ending` tylko w wyniku bieżącego Uruchomienia (RunOutcome dziedziczy pole w contract.py), nie w karcie z Logów"],
  ["WithoutQuantityRead.rows", "okno „Uruchomić z zapisem?” pokazuje gotowe zdanie `sentence` z numerami wierszy; do usunięcia z kontraktu"],
])

// Pliki, które wolno rozgałęziać po nazwie procesu; każdy z uzasadnieniem.
const PROCESS_COMPARISON_FILES = new Map([
  ["src/pages/runs/run-setup-card.tsx", "wybór wejścia w karcie ustawień: Plik zbiorczy albo Rejestr zleceń"],
  ["src/lib/runs.tsx", "ponowne Uruchomienie: Uporządkowanie INTERMAX startuje bez okresu własną operacją kontraktu"],
])

// Pliki, które wolno łączyć z serwerem; każdy z uzasadnieniem. Plik bez połączenia trzeba stąd usunąć.
const NETWORK_FILES = new Map([
  ["src/api/client.ts", "`call`: droga każdego zapytania, odpowiedź parsowana schematem z kontraktu"],
  ["src/api/centrum.ts", "strumień Uruchomień (każde zdarzenie parsowane zRunEvent) i pomiar widoku (204 bez treści)"],
])

// Droga naprawy dla każdego rodzaju połączenia: komunikat porażki prowadzi do wzorca z src/api/centrum.ts.
const REPAIRS = {
  request:
    "Dodaj w src/api/centrum.ts funkcję, która woła serwer przez `call` z src/api/client.ts " +
    "ze schematem odpowiedzi z kontraktu, i użyj jej tutaj.",
  stream:
    "Dodaj w src/api/centrum.ts funkcję na wzór `watchRunEvents`, która otwiera strumień " +
    "i parsuje każde zdarzenie schematem z kontraktu, i użyj jej tutaj.",
  beacon:
    "Dodaj w src/api/centrum.ts funkcję na wzór `recordViewTiming` (fetch z keepalive, odpowiedź bez treści) " +
    "i użyj jej tutaj.",
  parse:
    "Odpowiedź serwera parsuj schematem z kontraktu w funkcji z src/api/centrum.ts (przez `call`); " +
    "dane spoza serwera (np. localStorage) wymagają wpisu tego pliku w NETWORK_FILES z powodem.",
}

const NETWORK_GLOBALS = new Map([
  ["fetch", "request"],
  ["XMLHttpRequest", "request"],
  ["EventSource", "stream"],
  ["WebSocket", "stream"],
])

const NETWORK_MEMBERS = new Map([
  ["JSON.parse", "parse"],
  ["navigator.sendBeacon", "beacon"],
])

const GLOBAL_OBJECTS = new Set(["window", "globalThis", "self"])

function createProgram() {
  const config = compilerConfig()

  return ts.createProgram({ rootNames: config.fileNames, options: config.options })
}

function contractFields(contract) {
  return Object.entries(contract.components.schemas)
    .filter(([schema]) => !SCHEMAS_OUTSIDE_UI.has(schema))
    .flatMap(([schema, definition]) => Object.keys(definition.properties ?? {}).map((field) => `${schema}.${field}`))
}

function processNames(contract) {
  return new Set(contract.components.schemas.RunInfo.properties.process.enum)
}

function isProcessName(node, names) {
  return ts.isStringLiteralLike(node) && names.has(node.text)
}

const COMPARISONS = new Set([
  ts.SyntaxKind.EqualsEqualsEqualsToken,
  ts.SyntaxKind.ExclamationEqualsEqualsToken,
  ts.SyntaxKind.EqualsEqualsToken,
  ts.SyntaxKind.ExclamationEqualsToken,
])

function isProcessComparison(node, names) {
  if (ts.isBinaryExpression(node) && COMPARISONS.has(node.operatorToken.kind)) {
    return isProcessName(node.left, names) || isProcessName(node.right, names)
  }

  return ts.isCaseClause(node) && isProcessName(node.expression, names)
}

function unwrap(node) {
  return ts.isParenthesizedExpression(node) ? unwrap(node.expression) : node
}

function isGlobalObject(node) {
  const expression = unwrap(node)

  return ts.isIdentifier(expression) && GLOBAL_OBJECTS.has(expression.text)
}

// `JSON`, `window.JSON`, `(window).JSON`: nazwa globalna wprost albo przez obiekt globalny.
function globalName(node) {
  const expression = unwrap(node)

  if (ts.isIdentifier(expression)) {
    return expression.text
  }

  return ts.isPropertyAccessExpression(expression) && isGlobalObject(expression.expression)
    ? expression.name.text
    : undefined
}

// `x.fetch` i `{ fetch: … }` to nazwy właściwości, nie globalny fetch; `window.fetch` i `{ fetch }` już tak.
function networkGlobal(node) {
  const kind = NETWORK_GLOBALS.get(node.text)

  if (kind === undefined || isInType(node)) {
    return undefined
  }

  const parent = node.parent

  if (ts.isPropertyAccessExpression(parent) && parent.name === node) {
    return isGlobalObject(parent.expression) ? kind : undefined
  }

  return ts.isShorthandPropertyAssignment(parent) || parent.name !== node ? kind : undefined
}

function networkMember(node) {
  return ts.isPropertyAccessExpression(node)
    ? NETWORK_MEMBERS.get(`${globalName(node.expression)}.${node.name.text}`)
    : undefined
}

function networkKind(node) {
  return ts.isIdentifier(node) ? networkGlobal(node) : networkMember(node)
}

function location(file, node) {
  const { line } = file.getLineAndCharacterOfPosition(node.getStart(file))

  return `${relative(root, file.fileName).replaceAll("\\", "/")}:${line + 1}: ${node.getText(file)}`
}

// Porównania nazwy procesu i połączenia w kodzie pliku.
function inspect(file, names, comparisons, network) {
  function visit(node) {
    if (isProcessComparison(node, names)) {
      comparisons.push(location(file, node))
    }

    const kind = networkKind(node)

    if (kind !== undefined) {
      network.push({ place: location(file, node), kind })
    }

    ts.forEachChild(node, visit)
  }

  visit(file)
}

const contract = JSON.parse(readFileSync(join(source, "api", "openapi.json"), "utf8"))

const program = createProgram()

const { declared, used } = fieldUse(program, contract)

const names = processNames(contract)

const comparisons = []

const network = []

const connectedFiles = new Set()

for (const file of program.getSourceFiles().filter(isHandWritten)) {
  const key = relative(root, file.fileName).replaceAll("\\", "/")
  const calls = []
  inspect(file, names, PROCESS_COMPARISON_FILES.has(key) ? [] : comparisons, calls)

  if (calls.length > 0) {
    connectedFiles.add(key)
  }

  if (!NETWORK_FILES.has(key)) {
    network.push(...calls)
  }
}

const fields = contractFields(contract)

const undeclared = fields.filter((key) => !declared.has(key))

const unused = fields.filter((key) => declared.has(key) && !FIELDS_OUTSIDE_UI.has(key) && !used.has(key))

const staleExceptions = [...FIELDS_OUTSIDE_UI.keys()].filter((key) => used.has(key))

const staleNetworkFiles = [...NETWORK_FILES.keys()].filter((key) => !connectedFiles.has(key))

const problems = [
  ...undeclared.map(
    (key) => `Pole kontraktu ${key} nie ma typu w src/api/generated: uruchom npm run contract we frontend/.`
  ),
  ...unused.map((key) => `Pole kontraktu ${key} nie jest użyte w src: pokaż je w UI albo usuń z kontraktu.`),
  ...staleExceptions.map((key) => `Wyjątek ${key} jest zbędny: pole jest już użyte w src.`),
  ...comparisons.map((place) => `Porównanie nazwy procesu w przeglądarce: ${place}`),
  ...network.map(({ place, kind }) => `Sieć albo JSON.parse poza NETWORK_FILES: ${place}. ${REPAIRS[kind]}`),
  ...staleNetworkFiles.map((key) => `Wyjątek ${key} w NETWORK_FILES jest zbędny: plik nie łączy się z serwerem.`),
]

for (const problem of problems) {
  console.error(problem)
}

if (problems.length > 0) {
  process.exit(1)
}

console.log("Reguły frontendu: OK")
