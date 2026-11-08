// Reguły frontendu z CODING_STANDARDS, których Oxlint nie wyraża (brak no-restricted-syntax w Oxlint 1.88):
// 1. Każda właściwość schematów kontraktu (src/api/openapi.json) jest użyta w src poza generated/: kod wartości
//    sięga do jej symbolu z typu Schema (types.gen.ts) albo kształtu zSchema (zod.gen.ts), co rozstrzyga checker
//    TypeScriptu, nie nazwa. Użycie to odczyt (`.pole`, `["pole"]`, `x[klucz]` z kluczem typu literału,
//    destrukturyzacja, `"pole" in x`) albo zapis (klucz literału obiektu typu schematu, np. wysyłane ciało, atrybut
//    JSX; w miejscu unii tylko w wariantach, do których literał da się przypisać), także przez typ, do którego
//    wartość płynie (`Pick<…>`, typ propsów, ograniczenie parametru typu, wynik funkcji, parametr funkcji podanej
//    jako callback): odczyt pola celu czyta źródło, a zapisane pole źródła trafia do celu. Wzmianka w typie
//    (`RunInfo["process"]`) nie jest użyciem. Granice: pole czytane tylko w kodzie ogólnym (`Object.entries`,
//    `JSON.stringify`) reguła uznaje za nieużyte, więc takie pole potrzebuje wpisu w FIELDS_OUTSIDE_UI. Literał typu
//    odpowiedzi serwera (atrapa, optymistyczna aktualizacja) liczy się jako użycie pola, choć UI go nie czyta; to
//    łapie tylko przegląd.
// 2. Przeglądarka nie porównuje nazwy procesu: żadnego `=== "settlement"` ani `case "preparation":`.
// 3. Sieć (fetch, EventSource, WebSocket, XMLHttpRequest, sendBeacon) i JSON.parse tylko w plikach z NETWORK_FILES,
//    które parsują każdą odpowiedź serwera schematem z kontraktu. Wpis w NETWORK_FILES ma powód, a zbędny wpis
//    wywraca regułę. Granica: destrukturyzację (`const { parse } = JSON`), `JSON["parse"]`, `Reflect.get`,
//    `Response.json()` i to, czy plik z NETWORK_FILES parsuje odpowiedź schematem, łapie tylko przegląd.
import { readFileSync } from "node:fs"
import { join, relative, resolve, sep } from "node:path"
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

// Te same pliki i opcje, które sprawdza `tsc -b` (tsconfig.app.json), z checkerem typów.
function createProgram() {
  const config = ts.getParsedCommandLineOfConfigFile(
    join(root, "tsconfig.app.json"),
    {},
    {
      ...ts.sys,
      onUnRecoverableConfigFileDiagnostic(diagnostic) {
        throw new Error(ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n"))
      },
    }
  )

  return ts.createProgram({ rootNames: config.fileNames, options: config.options })
}

// TypeScript podaje ścieżki plików z ukośnikiem `/` także na Windows.
function under(directory) {
  return directory.split(sep).join("/") + "/"
}

// Pola typów z src (kontraktu i UI), nie z bibliotek: przepływ do propsów DOM i Reacta nie czyta pól kontraktu.
function isDeclaredInSource(property) {
  return property.declarations?.some((declaration) => declaration.getSourceFile().fileName.startsWith(under(source)))
}

function isHandWritten(file) {
  return file.fileName.startsWith(under(source)) && !file.fileName.startsWith(under(generated))
}

function contractSchemas(contract) {
  return Object.entries(contract.components.schemas).filter(([schema]) => !SCHEMAS_OUTSIDE_UI.has(schema))
}

function contractFields(contract) {
  return contractSchemas(contract).flatMap(([schema, definition]) =>
    Object.keys(definition.properties ?? {}).map((field) => `${schema}.${field}`)
  )
}

function exportsOf(program, checker, name) {
  const file = program.getSourceFile(join(generated, name))

  if (file === undefined) {
    throw new Error(`Brak src/api/generated/${name}: uruchom npm run contract.`)
  }

  return new Map(checker.getExportsOfModule(checker.getSymbolAtLocation(file)).map((symbol) => [symbol.name, symbol]))
}

// Typy, w których leżą pola schematu: `Schema` z types.gen.ts i kształt `zSchema.shape` z zod.gen.ts, bo odpowiedź
// z `call` ma typ wywiedziony ze schematu zod, a reszta UI typy z types.gen.ts.
function schemaTypes(checker, types, schemas, schema) {
  const found = []
  const type = types.get(schema)
  const zod = schemas.get(`z${schema}`)

  if (type !== undefined) {
    found.push(checker.getDeclaredTypeOfSymbol(type))
  }

  const parsed = zod === undefined ? undefined : checker.getTypeOfSymbol(zod).getProperty("shape")

  if (parsed !== undefined) {
    found.push(checker.getTypeOfSymbol(parsed))
  }

  return found
}

// Deklaracja pola w wygenerowanym pliku → pola kontraktu, które ją mają.
function contractDeclarations(program, checker, contract) {
  const types = exportsOf(program, checker, "types.gen.ts")
  const schemas = exportsOf(program, checker, "zod.gen.ts")
  const declarations = new Map()
  const declared = new Set()

  for (const [schema, definition] of contractSchemas(contract)) {
    for (const type of schemaTypes(checker, types, schemas, schema)) {
      for (const field of Object.keys(definition.properties ?? {})) {
        for (const declaration of type.getProperty(field)?.declarations ?? []) {
          const key = `${schema}.${field}`
          declarations.set(declaration, [...(declarations.get(declaration) ?? []), key])
          declared.add(key)
        }
      }
    }
  }

  return { declarations, declared }
}

function link(edges, from, to) {
  edges.set(from, (edges.get(from) ?? new Set()).add(to))
}

function members(type) {
  return type.isUnion() ? type.types : [type]
}

function propertiesNamed(type, name) {
  if (type === undefined) {
    return []
  }

  return members(type).flatMap((member) => member.getProperty(name) ?? [])
}

function propertyName(name) {
  return ts.isIdentifier(name) || ts.isStringLiteralLike(name) ? name.text : undefined
}

// Właściwości, które węzeł kodu wartości czyta; każda niesie deklaracje z typów, z których pochodzi.
function readProperties(checker, node) {
  if (ts.isPropertyAccessExpression(node)) {
    return [checker.getSymbolAtLocation(node.name)]
  }

  // `range[key]` z `key: "p50_ms" | "p95_ms"` czyta oba pola.
  if (ts.isElementAccessExpression(node)) {
    const object = checker.getTypeAtLocation(node.expression)

    return members(checker.getTypeAtLocation(node.argumentExpression))
      .filter((key) => key.isStringLiteral())
      .flatMap((key) => propertiesNamed(object, key.value))
  }

  if (ts.isBindingElement(node) && ts.isObjectBindingPattern(node.parent)) {
    const name = propertyName(node.propertyName ?? node.name)

    return name === undefined ? [] : propertiesNamed(checker.getTypeAtLocation(node.parent), name)
  }

  if (
    ts.isBinaryExpression(node) &&
    node.operatorToken.kind === ts.SyntaxKind.InKeyword &&
    ts.isStringLiteralLike(node.left)
  ) {
    return propertiesNamed(checker.getTypeAtLocation(node.right), node.left.text)
  }

  return []
}

// Właściwości, które węzeł zapisuje: klucz literału obiektu (np. wysyłane ciało) i atrybut JSX. Literał w miejscu
// unii zapisuje tylko warianty, do których da się go przypisać: `{ title, body }` jako `Note | Decision` to `Note`.
function writtenProperties(checker, node) {
  if (ts.isJsxAttribute(node)) {
    return [checker.getSymbolAtLocation(node.name)]
  }

  if (ts.isObjectLiteralElementLike(node) && ts.isObjectLiteralExpression(node.parent) && node.name !== undefined) {
    const name = propertyName(node.name)
    const target = literalType(checker, node.parent)

    if (name === undefined || target === undefined) {
      return []
    }

    const literal = checker.getTypeAtLocation(node.parent)

    return members(target)
      .filter((member) => !target.isUnion() || checker.isTypeAssignableTo(literal, member))
      .flatMap((member) => member.getProperty(name) ?? [])
  }

  return []
}

const ZOD_PARSE = new Set(["parse", "safeParse"])

// Typ, w miejsce którego trafia literał obiektu; `zViewTiming.safeParse({ … })` przyjmuje `unknown`, więc literał
// sprawdzany schematem zod ma typ jego kształtu.
function literalType(checker, literal) {
  const call = literal.parent

  if (
    ts.isCallExpression(call) &&
    call.arguments[0] === literal &&
    ts.isPropertyAccessExpression(call.expression) &&
    ZOD_PARSE.has(call.expression.name.text)
  ) {
    const checked = checker.getTypeAtLocation(call.expression.expression).getProperty("shape")

    if (checked !== undefined) {
      return checker.getTypeOfSymbol(checked)
    }
  }

  return checker.getContextualType(literal)
}

// Typ wywnioskowany za parametr typu płynie w jego ograniczenie: `useLiveFile(getKindTable, …)` z
// `T extends LiveFileView` czyta pola odpowiedzi przez `LiveFileView`.
function inferredFlows(checker, node) {
  if (!ts.isCallLikeExpression(node)) {
    return []
  }

  const signature = checker.getResolvedSignature(node)
  const parameters = signature?.getDeclaration()?.typeParameters ?? []
  const inferred = signature === undefined ? [] : (checker.getTypeArgumentsForResolvedSignature(signature) ?? [])

  return parameters.flatMap((parameter, index) => {
    const constraint = checker.getTypeAtLocation(parameter).getConstraint()

    return constraint === undefined || inferred[index] === undefined ? [] : [{ from: inferred[index], to: constraint }]
  })
}

// Wartość, która płynie w miejsce innego typu: argument, atrybut JSX, zwracana wartość, `...x` w literale obiektu.
function flow(checker, node) {
  if (ts.isSpreadAssignment(node) && ts.isObjectLiteralExpression(node.parent)) {
    return { from: checker.getTypeAtLocation(node.expression), to: checker.getContextualType(node.parent) }
  }

  if (!ts.isExpression(node) || ts.isObjectLiteralExpression(node) || ts.isArrayLiteralExpression(node)) {
    return undefined
  }

  return { from: checker.getTypeAtLocation(node), to: checker.getContextualType(node) }
}

const OPAQUE = ts.TypeFlags.Primitive | ts.TypeFlags.Any | ts.TypeFlags.Unknown | ts.TypeFlags.Never

/**
 * Wartość płynie w typ docelowy, więc czytanie pola celu czyta pole tej samej nazwy w źródle (`<RunResultBadge
 * run={pinnable} />` z `run: Pick<ProcessRun, "result">` czyta `PinnableRun.result`), a zapisane pole źródła trafia
 * do pola celu (Uwaga zapisana jako `DadNoteRequest` idzie do serwera jako `DadNoteText`). Krawędzie łączą
 * deklaracje pól w obu kierunkach, w głąb pól i elementów tablic do `MAX_DEPTH`.
 */
class Flows {
  static MAX_DEPTH = 4

  // Deklaracja pola celu → deklaracje pól źródła (czytanie).
  backward = new Map()

  // Deklaracja pola źródła → deklaracje pól celu (zapis).
  forward = new Map()

  related = new Map()

  constructor(checker) {
    this.checker = checker
  }

  relate(from, to, depth = 0) {
    if (from === undefined || to === undefined || from === to || depth > Flows.MAX_DEPTH) {
      return
    }

    const seen = this.related.get(from) ?? new Set()

    if (seen.has(to)) {
      return
    }

    seen.add(to)
    this.related.set(from, seen)

    // Każdy wariant źródła płynie tylko w warianty celu, do których da się go przypisać, a wariant obecny po obu
    // stronach w siebie: `RunInfo | Decision` w `RunInfo | Decision | null` nie łączy `RunInfo.title` z `Decision.title`.
    const targets = members(to)

    for (const origin of members(from).filter((member) => !targets.includes(member))) {
      for (const target of targets.filter((member) => this.checker.isTypeAssignableTo(origin, member))) {
        this.relateMember(origin, target, depth)
      }
    }
  }

  relateMember(from, target, depth) {
    if (target.flags & OPAQUE) {
      return
    }

    // Funkcja płynie w miejsce funkcji: wynik płynie z niej (`open: () => Promise<{ name: string }>` czyta `name`
    // z odpowiedzi), a argumenty do niej (`checks.map(checkRow)` daje `DiagnosisCheck` parametrowi `CheckRow`).
    const signatures = target.getCallSignatures()

    if (signatures.length > 0) {
      for (const called of members(from).flatMap((member) => member.getCallSignatures())) {
        for (const signature of signatures) {
          this.relate(called.getReturnType(), signature.getReturnType(), depth + 1)

          const count = Math.min(called.getParameters().length, signature.getParameters().length)

          for (let position = 0; position < count; position++) {
            this.relate(
              signature.getTypeParameterAtPosition(position),
              called.getTypeParameterAtPosition(position),
              depth + 1
            )
          }
        }
      }

      return
    }

    const awaited = this.checker.getAwaitedType(target)

    if (awaited !== undefined && awaited !== target) {
      this.relate(this.checker.getAwaitedType(from), awaited, depth + 1)

      return
    }

    if (this.checker.isArrayType(target) || this.checker.isTupleType(target)) {
      const element = target.getNumberIndexType()

      for (const origin of members(from)) {
        this.relate(origin.getNumberIndexType(), element, depth + 1)
      }

      return
    }

    for (const property of target.getProperties().filter(isDeclaredInSource)) {
      for (const origin of propertiesNamed(from, property.name)) {
        for (const declaration of property.declarations ?? []) {
          for (const originDeclaration of origin.declarations ?? []) {
            link(this.backward, declaration, originDeclaration)
            link(this.forward, originDeclaration, declaration)
          }
        }

        this.relate(this.checker.getTypeOfSymbol(origin), this.checker.getTypeOfSymbol(property), depth + 1)
      }
    }
  }

  // Deklaracje czytane albo zapisane wprost i przez każdą krawędź od nich w kierunku `edges`.
  static closure(start, edges) {
    const all = new Set(start)
    const pending = [...start]

    while (pending.length > 0) {
      for (const origin of edges.get(pending.pop()) ?? []) {
        if (!all.has(origin)) {
          all.add(origin)
          pending.push(origin)
        }
      }
    }

    return all
  }
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

function location(file, node) {
  const { line } = file.getLineAndCharacterOfPosition(node.getStart(file))

  return `${relative(root, file.fileName).replaceAll("\\", "/")}:${line + 1}: ${node.getText(file)}`
}

// Deklaracje pól, do których sięga kod wartości pliku, przepływy wartości, porównania nazwy procesu i połączenia.
function inspect({ file, checker, flows, names }, { read, written }, comparisons, network) {
  function visit(node) {
    if (!isInType(node)) {
      for (const property of readProperties(checker, node)) {
        property?.declarations?.forEach((declaration) => read.add(declaration))
      }

      for (const property of writtenProperties(checker, node)) {
        property?.declarations?.forEach((declaration) => written.add(declaration))
      }

      for (const { from, to } of [flow(checker, node) ?? [], inferredFlows(checker, node)].flat()) {
        flows.relate(from, to)
      }
    }

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

const checker = program.getTypeChecker()

const { declarations, declared } = contractDeclarations(program, checker, contract)

const names = processNames(contract)

const flows = new Flows(checker)

const reached = { read: new Set(), written: new Set() }

const comparisons = []

const network = []

const connectedFiles = new Set()

for (const file of program.getSourceFiles().filter(isHandWritten)) {
  const key = relative(root, file.fileName).replaceAll("\\", "/")
  const calls = []
  inspect({ file, checker, flows, names }, reached, PROCESS_COMPARISON_FILES.has(key) ? [] : comparisons, calls)

  if (calls.length > 0) {
    connectedFiles.add(key)
  }

  if (!NETWORK_FILES.has(key)) {
    network.push(...calls)
  }
}

const used = new Set(
  [...Flows.closure(reached.read, flows.backward), ...Flows.closure(reached.written, flows.forward)].flatMap(
    (declaration) => declarations.get(declaration) ?? []
  )
)

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
