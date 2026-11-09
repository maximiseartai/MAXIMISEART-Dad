// Reguły frontendu z CODING_STANDARDS, których Oxlint nie wyraża (brak no-restricted-syntax w Oxlint 1.88):
// 1. Każda właściwość schematów kontraktu (src/api/openapi.json) jest użyta w src poza generated/:
//    jej nazwa występuje jako identyfikator (dostęp, destrukturyzacja, klucz obiektu) albo tekst literału.
// 2. Przeglądarka nie porównuje nazwy procesu: żadnego `=== "settlement"` ani `case "preparation":`.
// 3. Sieć (fetch, EventSource, WebSocket, XMLHttpRequest, sendBeacon) i JSON.parse tylko w plikach z NETWORK_FILES,
//    które parsują każdą odpowiedź serwera schematem z kontraktu. Wpis w NETWORK_FILES ma powód, a zbędny wpis
//    wywraca regułę. Granica: destrukturyzację (`const { parse } = JSON`), `JSON["parse"]`, `Reflect.get`,
//    `Response.json()` i to, czy plik z NETWORK_FILES parsuje odpowiedź schematem, łapie tylko przegląd.
// 4. Przeglądarka woła przez `call` (src/api/client.ts) dokładnie operacje pomiaru widoku (`ApiTiming.operation`
//    kontraktu): każdą z nich i żadnej innej, a nazwa operacji to literał drugiego argumentu `call`. Granica: `call`
//    pod inną nazwą (alias importu, `const f = call`) reguła pomija; to łapie tylko przegląd.
import { readdirSync, readFileSync } from "node:fs"
import { join, relative, resolve } from "node:path"
import ts from "typescript"

const root = resolve(import.meta.dirname, "..")

const source = join(root, "src")

const generated = join(source, "api", "generated")

// Schematy kontraktu spoza UI; każdy z uzasadnieniem.
const SCHEMAS_OUTSIDE_UI = new Map([
  ["HTTPValidationError", "domyślny błąd walidacji FastAPI; przeglądarka pokazuje własny Komunikat błędu"],
  ["ValidationError", "domyślny błąd walidacji FastAPI, część HTTPValidationError"],
])

// Pola kontraktu, których UI nie pokazuje; każde z uzasadnieniem. Pole użyte w src trzeba stąd usunąć.
const FIELDS_OUTSIDE_UI = new Map([
  ["Health.service", "czyta je launcher Centrum (launcher.py), nie przeglądarka"],
  ["RunEvent.sequence", "numer zdarzenia strumienia SSE, nie treść dla taty"],
])

// Pliki, które wolno rozgałęziać po nazwie procesu; każdy z uzasadnieniem.
const PROCESS_COMPARISON_FILES = new Map([
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

function sourceFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name)

    if (entry.isDirectory()) {
      return path === generated ? [] : sourceFiles(path)
    }

    return /\.tsx?$/.test(entry.name) ? [path] : []
  })
}

function contractFields(contract) {
  return Object.entries(contract.components.schemas)
    .filter(([schema]) => !SCHEMAS_OUTSIDE_UI.has(schema))
    .flatMap(([schema, definition]) => Object.keys(definition.properties ?? {}).map((field) => `${schema}.${field}`))
}

function fieldName(key) {
  return key.split(".")[1]
}

function timedOperations(contract) {
  return new Set(contract.components.schemas.ApiTiming.properties.operation.enum)
}

// `call(schemat, "operacja", …)`: nazwa operacji albo `null`, gdy drugi argument nie jest literałem.
function calledOperation(node) {
  if (!ts.isCallExpression(node) || !ts.isIdentifier(node.expression) || node.expression.text !== "call") {
    return undefined
  }

  const operation = node.arguments[1]

  return operation !== undefined && ts.isStringLiteralLike(operation) ? operation.text : null
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

// `class X extends EventSource` dziedziczy wartość, choć TypeScript nazywa ten węzeł typem.
function isClassExtends(node) {
  return (
    ts.isExpressionWithTypeArguments(node) &&
    node.parent.token === ts.SyntaxKind.ExtendsKeyword &&
    ts.isClassLike(node.parent.parent)
  )
}

function isInType(node) {
  for (let ancestor = node.parent; ancestor !== undefined; ancestor = ancestor.parent) {
    if (isClassExtends(ancestor)) {
      return false
    }

    if (ts.isTypeNode(ancestor)) {
      return true
    }
  }

  return false
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

function location(file, path, node) {
  const { line } = file.getLineAndCharacterOfPosition(node.getStart(file))

  return `${relative(root, path).replaceAll("\\", "/")}:${line + 1}: ${node.getText(file)}`
}

// Nazwy użyte w kodzie: identyfikatory (także dostęp do właściwości i destrukturyzacja) i teksty literałów.
function inspect(path, names, used, comparisons, network, calls) {
  const file = ts.createSourceFile(path, readFileSync(path, "utf8"), ts.ScriptTarget.Latest, true)

  function visit(node) {
    if (ts.isIdentifier(node) || ts.isStringLiteralLike(node)) {
      used.add(node.text)
    }

    if (isProcessComparison(node, names)) {
      comparisons.push(location(file, path, node))
    }

    const operation = calledOperation(node)

    if (operation !== undefined) {
      calls.push({ place: location(file, path, node.expression), operation })
    }

    const kind = networkKind(node)

    if (kind !== undefined) {
      network.push({ place: location(file, path, node), kind })
    }

    ts.forEachChild(node, visit)
  }

  visit(file)
}

const contract = JSON.parse(readFileSync(join(source, "api", "openapi.json"), "utf8"))

const names = processNames(contract)

const used = new Set()

const comparisons = []

const network = []

const connectedFiles = new Set()

const operationCalls = []

for (const path of sourceFiles(source)) {
  const key = relative(root, path).replaceAll("\\", "/")
  const calls = []
  inspect(path, names, used, PROCESS_COMPARISON_FILES.has(key) ? [] : comparisons, calls, operationCalls)

  if (calls.length > 0) {
    connectedFiles.add(key)
  }

  if (!NETWORK_FILES.has(key)) {
    network.push(...calls)
  }
}

const unused = contractFields(contract).filter((key) => !FIELDS_OUTSIDE_UI.has(key) && !used.has(fieldName(key)))

const staleExceptions = [...FIELDS_OUTSIDE_UI.keys()].filter((key) => used.has(fieldName(key)))

const staleNetworkFiles = [...NETWORK_FILES.keys()].filter((key) => !connectedFiles.has(key))

const timed = timedOperations(contract)

const called = new Set(operationCalls.map(({ operation }) => operation))

const problems = [
  ...unused.map((key) => `Pole kontraktu ${key} nie jest użyte w src: pokaż je w UI albo usuń z kontraktu.`),
  ...staleExceptions.map((key) => `Wyjątek ${key} jest zbędny: pole jest już użyte w src.`),
  ...comparisons.map((place) => `Porównanie nazwy procesu w przeglądarce: ${place}`),
  ...network.map(({ place, kind }) => `Sieć albo JSON.parse poza NETWORK_FILES: ${place}. ${REPAIRS[kind]}`),
  ...staleNetworkFiles.map((key) => `Wyjątek ${key} w NETWORK_FILES jest zbędny: plik nie łączy się z serwerem.`),
  ...[...timed].flatMap((operation) =>
    called.has(operation) ? [] : [`Operacji ${operation} z ApiTiming.operation przeglądarka nie woła przez \`call\`.`],
  ),
  ...operationCalls.flatMap(({ place, operation }) =>
    operation !== null && !timed.has(operation)
      ? [`\`call\` z operacją ${operation} spoza ApiTiming.operation: ${place}`]
      : [],
  ),
  ...operationCalls.flatMap(({ place, operation }) =>
    operation === null ? [`\`call\` bez literału nazwy operacji w drugim argumencie: ${place}`] : [],
  ),
]

for (const problem of problems) {
  console.error(problem)
}

if (problems.length > 0) {
  process.exit(1)
}

console.log("Reguły frontendu: OK")
