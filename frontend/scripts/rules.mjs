// Reguły frontendu, których Oxlint nie wyraża (brak no-restricted-syntax w Oxlint 1.88):
// 1. Każda właściwość schematów kontraktu (src/api/openapi.json) jest użyta w src poza generated/:
//    jej nazwa występuje jako identyfikator (dostęp, destrukturyzacja, klucz obiektu) albo tekst literału. Pole
//    odpowiedzi operacji GET (pierwszy poziom schematu 200, każdego wariantu unii i elementu tablicy) liczy się, gdy src
//    je odczytuje (`x.pole`, `x?.pole`, `x!.pole`, `x["pole"]`, `{ pole }`; zapis to odniesienie oznaczone przez kompilator
//    `isWriteAccess`), a to, że odczyt dotyczy tego pola, mówi findReferences kompilatora: (a) odczyt przez typ tego
//    schematu albo typ z niego (`Pick<S, …>`, alias, `T extends S`, `z.output`); (b) odczyt na wiązaniu (prop
//    komponentu, parametr, zmienna), do którego src podaje wartość z tym polem w atrybucie JSX, argumencie albo
//    inicjalizatorze, także przez kolejne wiązania, bez względu na typ wiązania;
//    (c) odczyt pola zadeklarowanego w src w typie, który przyjmuje wynik funkcji podanej jako argument
//    (`read: () => Promise<T>` z `T extends LiveFileView`). Ta sama nazwa w innym schemacie go nie zastępuje (#1577 W2:
//    `unread` podpowiedzi Urządzeń bez zdania w sekcji, a nazwę `unread` czytały inne sekcje), także gdy wartość trafia
//    do typu z innego schematu, który pola nie czyta (`Pick<IntermaxSetup, "last">`, #1932 W1 r1). Granica: (a) liczy
//    odczyt przez typ ze schematu S także dla wartości innego schematu (zna tożsamość deklaracji, nie wartości), a (c)
//    odczyt pola typu z src także dla innej wartości tego typu; wartość w kontenerze (tablica, `Resource`) wchodząca do
//    typu innego schematu, rozwinięcie (`{ ...x }`), rzutowanie (`as`), przypisanie po deklaracji, wartość zwrócona jako
//    typ innego schematu i komponent bez deklaracji w src (biblioteka, `memo`) nie przenoszą odczytu, więc pole liczy się
//    jako nieużyte, tak samo odczyt przez odbicie (`Object.entries(x)`, `Object.keys(x)`, `for (const k in x)`), w którym
//    findReferences nie ma odniesienia pola; zapis `x["pole"] = …` kompilator zostawia bez `isWriteAccess`, więc liczy się
//    jako odczyt; pola schematów zagnieżdżonych i ciał zapytań reguła zna tylko z nazwy.
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

// Węzeł pliku, w którym zaczyna się odniesienie findReferences (najgłębszy węzeł zawierający pozycję).
function nodeAt(file, node, position) {
  const child = node.getChildren(file).find((part) => part.getStart(file) <= position && position < part.getEnd())

  return child === undefined ? node : nodeAt(file, child, position)
}

// Odczyt pola w odniesieniu findReferences (`node` to węzeł nazwy): `{ pole } = x` i `{ pole: y } = x` oraz `x.pole`
// i `x["pole"]`, których kompilator nie oznacza jako zapis (`isWriteAccess`: `x.pole = …`, `[x.pole] = …`,
// `({ pole: x.pole } = …)`, `for (x.pole of …)`, `x.pole++`). Wzorzec deklaracji kompilator oznacza jako zapis zmiennej,
// więc jego odczyt mówi kształt. Klucz w typie (`Pick<X, "pole">`), pole literału obiektu i atrybut JSX to dla
// findReferences też odniesienia, nie odczyty.
function readsField({ node, write }) {
  const parent = node.parent

  if (ts.isBindingElement(parent)) {
    return (parent.propertyName ?? parent.name) === node
  }

  const accessed =
    (ts.isPropertyAccessExpression(parent) && parent.name === node) ||
    (ts.isElementAccessExpression(parent) && parent.argumentExpression === node)

  return accessed && !write
}

function isOwn(fileName) {
  return fileName.startsWith(source) && !fileName.startsWith(generated)
}

// Wiązanie, które przyjmuje wartość: nazwa (`run`, `props`) z drogą pól, które trzeba z niej jeszcze odczytać, albo wzorzec
// destrukturyzacji; `undefined`, gdy wzorzec pomija pole z drogi.
function binding(name, path) {
  if (ts.isIdentifier(name)) {
    return { name, path }
  }

  if (!ts.isObjectBindingPattern(name)) {
    return undefined
  }

  if (path.length === 0) {
    return { name, path }
  }

  const element = name.elements.find((part) => (part.propertyName ?? part.name).getText() === path[0] && !part.dotDotDotToken)
  const rest = name.elements.find((part) => part.dotDotDotToken)

  return element !== undefined ? binding(element.name, path.slice(1)) : rest && binding(rest.name, path)
}

function variants(type) {
  return type.isUnion() ? type.types : [type]
}

// Pola z `fields` ("Schemat.pole"), które src czyta według reguły 1: tożsamość pola zawsze podaje findReferences
// kompilatora, a reguła wskazuje tylko granicę, na której wartość wchodzi do nowej zmiennej (mechanizmy (a)–(c)).
function readBySymbol(fields) {
  const config = ts.parseJsonConfigFileContent(
    ts.readConfigFile(join(root, "tsconfig.app.json"), ts.sys.readFile).config,
    ts.sys,
    root,
  )

  const service = ts.createLanguageService(
    {
      getScriptFileNames: () => config.fileNames,
      getScriptVersion: () => "0",
      getScriptSnapshot: (name) => {
        const text = ts.sys.readFile(name)

        return text === undefined ? undefined : ts.ScriptSnapshot.fromString(text)
      },
      getCurrentDirectory: () => root,
      getCompilationSettings: () => config.options,
      getDefaultLibFileName: ts.getDefaultLibFilePath,
      fileExists: ts.sys.fileExists,
      readFile: ts.sys.readFile,
      readDirectory: ts.sys.readDirectory,
      directoryExists: ts.sys.directoryExists,
      getDirectories: ts.sys.getDirectories,
    },
    ts.createDocumentRegistry(),
  )

  const program = service.getProgram()
  const checker = program.getTypeChecker()

  const declared = declaredFields(
    ["zod.gen.ts", "types.gen.ts"].map((name) => program.getSourceFile(join(generated, name))),
    fields,
  )

  // Odniesienia w src, które findReferences wiąże z deklaracją `name`, bez samej deklaracji: węzeł nazwy i `isWriteAccess`.
  function references(name) {
    const file = name.getSourceFile()

    return (service.findReferences(file.fileName, name.getStart(file)) ?? [])
      .flatMap((symbol) => symbol.references)
      .filter((reference) => !reference.isDefinition && isOwn(reference.fileName))
      .map((reference) => {
        const place = program.getSourceFile(reference.fileName)

        return { node: nodeAt(place, place, reference.textSpan.start), write: reference.isWriteAccess === true }
      })
  }

  // Odniesienie findReferences w miejscu węzła nazwy `name` (dostęp do pola na wiązaniu (b)).
  function referenceAt(name) {
    const file = name.getSourceFile()
    const start = name.getStart(file)

    const entry = (service.findReferences(file.fileName, start) ?? [])
      .flatMap((symbol) => symbol.references)
      .find((reference) => reference.fileName === file.fileName && reference.textSpan.start === start)

    return { node: name, write: entry?.isWriteAccess === true }
  }

  // (a) Odczyt, który findReferences wiąże z deklaracją pola w generated/.
  const read = new Set(
    [...declared].flatMap(([property, key]) => (references(property.name).some(readsField) ? [key] : [])),
  )

  const waiting = new Map([...declared].filter(([, key]) => !read.has(key)))

  // Pola z `waiting`, które niesie typ: jego właściwość (każdego wariantu unii) prowadzi do ich deklaracji.
  function carried(type) {
    return variants(type).flatMap((variant) =>
      variant.getProperties().flatMap((property) =>
        checker.getRootSymbols(property).flatMap((origin) => (origin.declarations ?? []).flatMap((node) => waiting.get(node) ?? [])),
      ),
    )
  }

  // Deklaracja funkcji albo komponentu, który wywołuje `call` (wywołanie, `new`, element JSX), gdy leży w src.
  function calledDeclaration(call) {
    const declaration = checker.getResolvedSignature(call)?.getDeclaration()

    return declaration !== undefined && isOwn(declaration.getSourceFile().fileName) ? declaration : undefined
  }

  // Wiązania, do których wchodzi wartość wyrażenia `node` z drogą `path`: prop komponentu z atrybutu JSX, parametr
  // wywołanej funkcji z argumentu, zmienna z inicjalizatora.
  function receivers(node, path) {
    const parent = node.parent

    if (ts.isJsxExpression(parent) && ts.isJsxAttribute(parent.parent)) {
      const attribute = parent.parent
      const props = calledDeclaration(attribute.parent.parent)?.parameters[0]

      return props === undefined ? [] : [binding(props.name, [attribute.name.getText(), ...path])]
    }

    if ((ts.isCallExpression(parent) || ts.isNewExpression(parent)) && (parent.arguments ?? []).includes(node)) {
      const parameter = calledDeclaration(parent)?.parameters[parent.arguments.indexOf(node)]

      return parameter === undefined || parameter.dotDotDotToken ? [] : [binding(parameter.name, path)]
    }

    return ts.isVariableDeclaration(parent) && parent.initializer === node ? [binding(parent.name, path)] : []
  }

  // Czy wiązanie odczytuje `field`: wzorzec go wymienia, a nazwę findReferences wiąże z `.pole`, `?.pole`, `!.pole`,
  // `["pole"]` albo z podaniem do następnego wiązania (najwyżej `depth` kroków).
  function bindingReads(target, field, depth) {
    if (target === undefined || depth < 0) {
      return false
    }

    // Wzorzec czyta pole, gdy je wymienia; bez tego `...rest` niesie je dalej pod swoją nazwą.
    if (!ts.isIdentifier(target.name)) {
      const element = binding(target.name, [field])

      return element !== undefined && (element.path.length === 0 || bindingReads({ name: element.name, path: [] }, field, depth))
    }

    return references(target.name).some((reference) => valueReads(reference.node, target.path, field, depth))
  }

  function valueReads(node, path, field, depth) {
    const value = ts.isParenthesizedExpression(node.parent) || ts.isNonNullExpression(node.parent) ? node.parent : node

    if (value !== node) {
      return valueReads(value, path, field, depth)
    }

    const parent = value.parent
    const access = ts.isPropertyAccessExpression(parent) && parent.expression === value ? parent.name : undefined

    if (access !== undefined && path.length > 0) {
      return access.text === path[0] && valueReads(parent, path.slice(1), field, depth)
    }

    if (access !== undefined) {
      return access.text === field && readsField(referenceAt(access))
    }

    if (ts.isElementAccessExpression(parent) && parent.expression === value && path.length === 0) {
      return (
        ts.isStringLiteralLike(parent.argumentExpression) &&
        parent.argumentExpression.text === field &&
        readsField(referenceAt(parent.argumentExpression))
      )
    }

    return receivers(value, path).some((target) => bindingReads(target, field, depth - 1))
  }

  // Warianty typu, który według deklaracji wywołanej funkcji przyjmuje wynik funkcji podanej jako argument `node`
  // (po `Promise`; za parametrem typu jego ograniczenie).
  function resultConstraint(node) {
    const call = node.parent
    const parameter = calledDeclaration(call)?.parameters[call.arguments.indexOf(node)]
    const expected = parameter?.type === undefined ? undefined : checker.getTypeFromTypeNode(parameter.type).getCallSignatures()[0]

    if (expected === undefined) {
      return []
    }

    const result = checker.getAwaitedType(expected.getReturnType()) ?? expected.getReturnType()
    const target = result.flags & ts.TypeFlags.TypeParameter ? checker.getBaseConstraintOfType(result) : result

    return target === undefined ? [] : variants(target)
  }

  function resultReads(node, field) {
    return resultConstraint(node).some((variant) =>
      (variant.getProperty(field)?.declarations ?? []).some(
        (declaration) => isOwn(declaration.getSourceFile().fileName) && references(declaration.name).some(readsField),
      ),
    )
  }

  // (b) i (c) tylko dla pól bez (a): wyrażenie w atrybucie JSX, argumencie albo inicjalizatorze niesie pole wprost
  // (wiązanie, które je przyjmuje) albo w wyniku funkcji podanej jako argument (typ, który ten wynik przyjmuje).
  for (const file of waiting.size === 0 ? [] : program.getSourceFiles()) {
    if (file.isDeclarationFile || !isOwn(file.fileName)) {
      continue
    }

    const visit = (node) => {
      const parent = node.parent
      const argument = (ts.isCallExpression(parent) || ts.isNewExpression(parent)) && (parent.arguments ?? []).includes(node)

      if (
        argument ||
        (ts.isJsxExpression(parent) && ts.isJsxAttribute(parent.parent)) ||
        (ts.isVariableDeclaration(parent) && parent.initializer === node)
      ) {
        const type = checker.getTypeAtLocation(node)
        const result = argument ? type.getCallSignatures()[0]?.getReturnType() : undefined

        for (const key of carried(type)) {
          if (!read.has(key) && receivers(node, []).some((target) => bindingReads(target, fieldName(key), 4))) {
            read.add(key)
          }
        }

        for (const key of result === undefined ? [] : carried(checker.getAwaitedType(result) ?? result)) {
          if (!read.has(key) && resultReads(node, fieldName(key))) {
            read.add(key)
          }
        }
      }

      ts.forEachChild(node, visit)
    }

    ts.forEachChild(file, visit)
  }

  return read
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
