// Reguły frontendu, których Oxlint nie wyraża (brak no-restricted-syntax w Oxlint 1.88):
// 1. Każda właściwość schematów kontraktu (src/api/openapi.json) jest użyta w src poza generated/:
//    jej nazwa występuje jako identyfikator (dostęp, destrukturyzacja, klucz obiektu) albo tekst literału. Pole
//    odpowiedzi operacji GET (pierwszy poziom schematu 200, każdego wariantu unii i elementu tablicy) liczy się, gdy kontroler
//    typów rozwiązuje dostęp albo destrukturyzację w src do deklaracji tego pola w zod.gen.ts albo types.gen.ts, wprost albo
//    przez typ, do którego src podaje wartość z tym polem (argument, atrybut JSX, inicjalizator, wynik funkcji, przypisanie;
//    typ strukturalny jak `Pick<ProcessRun, "tone">`, ograniczenie parametru typu jak `T extends LiveFileView`, wynik
//    funkcji i `Promise`), a src czyta pole tej nazwy na samym tamtym typie. Ta sama nazwa w innej odpowiedzi go nie
//    zastępuje (#1577 W2: `unread` podpowiedzi Urządzeń bez zdania w sekcji, a nazwę `unread` czytały inne sekcje), także
//    gdy typ celu powstał z innego schematu: `Pick<IntermaxSetup, "last">`, którego nikt nie czyta, nie liczy
//    `ReportEnteringSetup.last`, choć `IntermaxSetup.last` czyta inna karta (#1932 W1 r1). Granica: przejście liczy pole
//    celu czytane gdziekolwiek w src, nie tylko dla tej wartości, odczyt pola przez `Pick<X, "pole">` liczy też `X.pole`,
//    a warianty unii źródła i celu łączy po nazwie pola każdy z każdym; wartość podana przez rozwinięcie (`{ ...x }`) albo
//    rzutowanie (`as`) nie przechodzi, więc jej pole liczy się jako nieużyte; pola schematów zagnieżdżonych i ciał
//    zapytań reguła zna tylko z nazwy.
// 2. Przeglądarka nie porównuje nazwy procesu: żadnego `=== "settlement"` ani `case "preparation":`. Granica: reguła
//    łapie tylko porównanie i `case`; `["settlement", "preparation"].includes(nazwa)`, odczyt z obiektu po nazwie
//    (`({ settlement: 1 })[nazwa]`) i inne rozgałęzienia na nazwie procesu łapie tylko przegląd.
// 3. Sieć (fetch, EventSource, WebSocket, XMLHttpRequest, sendBeacon) i JSON.parse tylko w plikach z NETWORK_FILES,
//    które parsują każdą odpowiedź serwera schematem z kontraktu. Wpis w NETWORK_FILES ma powód, a zbędny wpis
//    wywraca regułę. Granica: destrukturyzację (`const { parse } = JSON`), `JSON["parse"]`, `Reflect.get`,
//    `Response.json()` i to, czy plik z NETWORK_FILES parsuje odpowiedź schematem, łapie tylko przegląd.
// 4. Przeglądarka woła przez `call` (src/api/client.ts) dokładnie operacje pomiaru widoku (`ApiTiming.operation`
//    kontraktu): każdą z nich i żadnej innej, a nazwa operacji to literał pierwszego argumentu `call`; metodę, adres
//    i schemat odpowiedzi `call` bierze z wygenerowanej tablicy operacji. Granica: `call` pod inną nazwą (alias
//    importu, `const f = call`) reguła pomija; to łapie tylko przegląd.
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
  [
    "src/lib/runs.tsx",
    "ponowne Uruchomienie: Uporządkowanie INTERMAX i Wpisanie raportów startują bez okresu własną operacją kontraktu",
  ],
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

// `call("operacja", …)`: nazwa operacji albo `null`, gdy pierwszy argument nie jest literałem.
function calledOperation(node) {
  if (!ts.isCallExpression(node) || !ts.isIdentifier(node.expression) || node.expression.text !== "call") {
    return undefined
  }

  const operation = node.arguments[0]

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

// Schematy odpowiedzi: `$ref`, każdy wariant unii (`oneOf`, `anyOf`) i element tablicy (`items`).
function responseSchemas(schema) {
  if (schema === undefined) {
    return []
  }

  if (schema.$ref !== undefined) {
    return [schema.$ref.split("/").pop()]
  }

  return [...(schema.oneOf ?? []), ...(schema.anyOf ?? []), ...(schema.items ? [schema.items] : [])].flatMap(responseSchemas)
}

// Pola pierwszego poziomu schematów odpowiedzi 200 operacji GET (każdego wariantu unii): "Schemat.pole".
function responseFields(api) {
  const schemas = new Set(
    Object.values(api.paths).flatMap((methods) =>
      responseSchemas(methods.get?.responses?.["200"]?.content?.["application/json"]?.schema),
    ),
  )

  return new Set(
    [...schemas].flatMap((schema) =>
      Object.keys(api.components.schemas[schema].properties ?? {}).map((field) => `${schema}.${field}`),
    ),
  )
}

// Deklaracje pól pierwszego poziomu schematu → "Schemat.pole": `pole: …` w `export const zSchemat = z.object({ … })`
// pliku zod.gen.ts i w `export type Schemat = { … }` pliku types.gen.ts (odpowiedź bywa typowana jednym albo drugim).
function declaredFields(files, wanted) {
  const fields = new Map()

  for (const file of files) {
    for (const statement of file.statements) {
      const declarations = ts.isVariableStatement(statement)
        ? statement.declarationList.declarations.map((declaration) => [declaration.name, declaration.initializer])
        : ts.isTypeAliasDeclaration(statement)
          ? [[statement.name, statement.type]]
          : []

      for (const [name, value] of declarations) {
        const schema = ts.isVariableStatement(statement) ? name.getText(file).replace(/^z/, "") : name.getText(file)

        const members =
          value !== undefined && ts.isCallExpression(value) ? value.arguments[0] : value

        if (members === undefined || !(ts.isObjectLiteralExpression(members) || ts.isTypeLiteralNode(members))) {
          continue
        }

        for (const property of ts.isTypeLiteralNode(members) ? members.members : members.properties) {
          const key = `${schema}.${property.name?.getText(file)}`

          if (wanted.has(key)) {
            fields.set(property, key)
          }
        }
      }
    }
  }

  return fields
}

// Czy wyrażenie `node` src podaje dalej do miejsca z własnym typem: argument wywołania, atrybut JSX, inicjalizator
// zmiennej i pola obiektu, wynik funkcji albo prawa strona przypisania.
function flowsOn(node) {
  const parent = node.parent

  return (
    ((ts.isCallExpression(parent) || ts.isNewExpression(parent)) && (parent.arguments ?? []).includes(node)) ||
    (ts.isJsxExpression(parent) && parent.expression === node) ||
    ((ts.isVariableDeclaration(parent) || ts.isPropertyAssignment(parent)) && parent.initializer === node) ||
    ts.isReturnStatement(parent) ||
    (ts.isArrowFunction(parent) && parent.body === node) ||
    (ts.isBinaryExpression(parent) && parent.right === node && parent.operatorToken.kind === ts.SyntaxKind.EqualsToken)
  )
}

// Pola z `fields`, które src czyta przez kontroler typów: dostęp (`x.pole`) albo destrukturyzacja (`{ pole }`)
// rozwiązuje się do deklaracji pola wprost albo przez typ, do którego src podaje wartość z tym polem (argument,
// atrybut JSX, typ strukturalny jak `Pick<ProcessRun, "tone">`, ograniczenie parametru typu jak `T extends LiveFileView`,
// także przez wynik funkcji i `Promise`), gdy src czyta to pole na samym tamtym typie, nie na schemacie, z którego powstał.
function readBySymbol(fields) {
  const configPath = join(root, "tsconfig.app.json")
  const config = ts.parseJsonConfigFileContent(ts.readConfigFile(configPath, ts.sys.readFile).config, ts.sys, root)
  const program = ts.createProgram({ rootNames: config.fileNames, options: config.options })
  const checker = program.getTypeChecker()

  const declared = declaredFields(
    ["zod.gen.ts", "types.gen.ts"].map((name) => program.getSourceFile(join(generated, name))),
    fields,
  )

  // Symbole pól, które src czyta, z ich źródłami, i przejścia pola typu źródła do pola tej samej nazwy typu celu.
  const read = new Set()
  const passes = []

  // Symbol pola i jego źródła: alias importu, pole typu generycznego za jego wystąpieniem, pole za `Pick` i typem
  // mapowanym (aż do deklaracji w zod.gen.ts albo types.gen.ts) i pola wariantów za polem unii.
  function sources(symbol, seen = new Set()) {
    if (symbol === undefined || seen.has(symbol)) {
      return []
    }

    seen.add(symbol)
    const links = symbol.links ?? {}
    const aliased = symbol.flags & ts.SymbolFlags.Alias ? checker.getAliasedSymbol(symbol) : undefined
    const variants =
      (links.checkFlags ?? 0) & ts.CheckFlags.Synthetic
        ? links.containingType.types.map((type) => type.getProperty(symbol.name))
        : []

    return [
      symbol,
      ...sources(aliased, seen),
      ...sources(links.syntheticOrigin, seen),
      ...sources(links.target, seen),
      ...variants.flatMap((variant) => sources(variant, seen)),
    ]
  }

  // Pole typu celu samo, z polem typu generycznego za jego wystąpieniem, bez źródeł za `Pick` i typem mapowanym:
  // `Pick<IntermaxSetup, "last">` dzieli z `IntermaxSetup` deklarację pola, ale nie jego odczyty (#1932 W1 r1).
  function instances(symbol) {
    return symbol === undefined ? [] : [symbol, ...instances(symbol.links?.target)]
  }

  function pass(from, to, depth = 0) {
    const target = to !== undefined && to.flags & ts.TypeFlags.TypeParameter ? checker.getBaseConstraintOfType(to) : to

    if (target === undefined || from === target || depth > 4) {
      return
    }

    for (const member of from.isUnion() ? from.types : [from]) {
      for (const goal of target.isUnion() ? target.types : [target]) {
        const [awaited, awaitedGoal] = [checker.getAwaitedType(member) ?? member, checker.getAwaitedType(goal) ?? goal]

        if (awaited !== member || awaitedGoal !== goal) {
          pass(awaited, awaitedGoal, depth + 1)
          continue
        }

        for (const property of member.getProperties()) {
          const counterpart = goal.getProperty(property.name)

          if (counterpart !== undefined) {
            passes.push([sources(property), instances(counterpart)])
          }
        }

        const [call, goalCall] = [member.getCallSignatures()[0], goal.getCallSignatures()[0]]

        if (call !== undefined && goalCall !== undefined) {
          pass(call.getReturnType(), goalCall.getReturnType(), depth + 1)
        }
      }
    }
  }

  // Typ parametru z deklaracji wywołanej funkcji, przed podstawieniem parametrów typu (`T extends LiveFileView`).
  function declaredParameter(call, node) {
    const parameters = checker.getResolvedSignature(call)?.getDeclaration()?.parameters ?? []
    const index = call.arguments.indexOf(node)
    const parameter = parameters[Math.min(index, parameters.length - 1)]

    return parameter?.type === undefined ? undefined : checker.getTypeFromTypeNode(parameter.type)
  }

  for (const file of program.getSourceFiles()) {
    if (file.isDeclarationFile || !file.fileName.startsWith(source) || file.fileName.startsWith(generated)) {
      continue
    }

    const visit = (node) => {
      const symbol = ts.isPropertyAccessExpression(node)
        ? checker.getSymbolAtLocation(node.name)
        : ts.isBindingElement(node) && ts.isObjectBindingPattern(node.parent)
          ? checker.getTypeAtLocation(node.parent).getProperty((node.propertyName ?? node.name).getText(file))
          : undefined

      for (const source of sources(symbol)) {
        read.add(source)
      }

      if (node.parent !== undefined && flowsOn(node)) {
        const type = checker.getTypeAtLocation(node)
        pass(type, checker.getContextualType(node))

        if (ts.isCallExpression(node.parent)) {
          pass(type, declaredParameter(node.parent, node))
        }
      }

      ts.forEachChild(node, visit)
    }

    visit(file)
  }

  for (let grown = true; grown; ) {
    grown = false

    for (const [from, to] of passes) {
      if (to.some((symbol) => read.has(symbol)) && from.some((symbol) => !read.has(symbol))) {
        from.forEach((symbol) => read.add(symbol))
        grown = true
      }
    }
  }

  const reached = new Set([...read].flatMap((symbol) => symbol.declarations ?? []))

  return new Set([...declared].flatMap(([declaration, key]) => (reached.has(declaration) ? [key] : [])))
}

const answered = responseFields(contract)

const readFields = readBySymbol(answered)

function isUsed(key) {
  return answered.has(key) ? readFields.has(key) : used.has(fieldName(key))
}

const unused = contractFields(contract).filter((key) => !FIELDS_OUTSIDE_UI.has(key) && !isUsed(key))

const staleExceptions = [...FIELDS_OUTSIDE_UI.keys()].filter((key) => isUsed(key))

const staleNetworkFiles = [...NETWORK_FILES.keys()].filter((key) => !connectedFiles.has(key))

const timed = timedOperations(contract)

const called = new Set(operationCalls.map(({ operation }) => operation))

const problems = [
  ...unused.map((key) =>
    answered.has(key)
      ? `Pole odpowiedzi ${key} nie jest czytane w src przez swój typ (ta sama nazwa w innym schemacie się nie liczy): ` +
        `pokaż je w UI tam, gdzie przychodzi ta odpowiedź, albo usuń z kontraktu.`
      : `Pole kontraktu ${key} nie jest użyte w src: pokaż je w UI albo usuń z kontraktu.`,
  ),
  ...staleExceptions.map((key) => `Wyjątek ${key} jest zbędny: pole jest już użyte w src.`),
  ...comparisons.map(
    (place) =>
      `Porównanie nazwy procesu w przeglądarce: ${place}. UI nie rozgałęzia się na nazwie procesu: weź z kontraktu ` +
      `pole, które niesie tę różnicę (albo dodaj je na serwerze), a plik, który musi porównać nazwę, wpisz do ` +
      `PROCESS_COMPARISON_FILES z powodem.`,
  ),
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
    operation === null ? [`\`call\` bez literału nazwy operacji w pierwszym argumencie: ${place}`] : [],
  ),
]

for (const problem of problems) {
  console.error(problem)
}

if (problems.length > 0) {
  process.exit(1)
}

console.log("Reguły frontendu: OK")
