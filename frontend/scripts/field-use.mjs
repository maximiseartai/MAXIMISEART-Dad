// Silnik reguły 1 z rules.mjs (każde pole kontraktu użyte w src): które pola kod wartości czyta albo zapisuje według
// typów TypeScriptu. Co reguła łapie, gdzie wraca do nazwy i co zostaje przeglądowi, opisuje nagłówek rules.mjs.
import { join, resolve, sep } from "node:path"
import ts from "typescript"

export const root = resolve(import.meta.dirname, "..")

export const source = join(root, "src")

const generated = join(source, "api", "generated")

// Te same opcje, które sprawdza `tsc -b` (tsconfig.app.json).
export function compilerConfig() {
  return ts.getParsedCommandLineOfConfigFile(
    join(root, "tsconfig.app.json"),
    {},
    {
      ...ts.sys,
      onUnRecoverableConfigFileDiagnostic(diagnostic) {
        throw new Error(ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n"))
      },
    }
  )
}

// TypeScript podaje ścieżki plików z ukośnikiem `/` także na Windows.
function under(directory) {
  return directory.split(sep).join("/") + "/"
}

// Pola typów z src (kontraktu i UI), nie z bibliotek: przepływ do propsów DOM i Reacta nie czyta pól kontraktu.
function isDeclaredInSource(property) {
  return property.declarations?.some((declaration) => declaration.getSourceFile().fileName.startsWith(under(source)))
}

export function isHandWritten(file) {
  return file.fileName.startsWith(under(source)) && !file.fileName.startsWith(under(generated))
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

  for (const [schema, definition] of Object.entries(contract.components.schemas)) {
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

const NAMED = new Map()

// Pole o tej nazwie w wartości, której typu reguła nie prześledziła (`any`, `unknown`): symbol z jedną deklaracją jak
// symbol pola, więc krawędzie i domknięcia biorą je tak samo.
function byName(name) {
  if (!NAMED.has(name)) {
    NAMED.set(name, { name, declarations: [{ name }] })
  }

  return NAMED.get(name)
}

function link(edges, from, to) {
  edges.set(from, (edges.get(from) ?? new Set()).add(to))
}

function members(type) {
  return type.isUnion() ? type.types : [type]
}

const UNTYPED = ts.TypeFlags.Any | ts.TypeFlags.Unknown

const OPAQUE = ts.TypeFlags.Primitive | ts.TypeFlags.Never | UNTYPED

function isUntyped(type) {
  return members(type).some((member) => member.flags & UNTYPED)
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

// Pole `name` odczytane z wartości typu `type`: jego właściwości, a z wartości bez tej właściwości (`any`,
// `"title" in x` w strażniku typu na `unknown`) pole po nazwie.
function readNamed(type, name) {
  const found = propertiesNamed(type, name)

  return found.length > 0 ? found : [byName(name)]
}

// Właściwości (albo pola po nazwie), które węzeł kodu wartości czyta.
function readProperties(checker, node) {
  // `x.pole` bez symbolu: `x` typu `any` albo z sygnaturą indeksu.
  if (ts.isPropertyAccessExpression(node)) {
    return [checker.getSymbolAtLocation(node.name) ?? byName(node.name.text)]
  }

  // `range[key]` z `key: "p50_ms" | "p95_ms"` czyta oba pola.
  if (ts.isElementAccessExpression(node)) {
    const object = checker.getTypeAtLocation(node.expression)

    return members(checker.getTypeAtLocation(node.argumentExpression))
      .filter((key) => key.isStringLiteral())
      .flatMap((key) => readNamed(object, key.value))
  }

  if (ts.isBindingElement(node) && ts.isObjectBindingPattern(node.parent)) {
    const name = propertyName(node.propertyName ?? node.name)

    return name === undefined ? [] : readNamed(checker.getTypeAtLocation(node.parent), name)
  }

  if (
    ts.isBinaryExpression(node) &&
    node.operatorToken.kind === ts.SyntaxKind.InKeyword &&
    ts.isStringLiteralLike(node.left)
  ) {
    return readNamed(checker.getTypeAtLocation(node.right), node.left.text)
  }

  return []
}

// Typ literału obiektu bez świeżości, więc przypisywalność nie sprawdza nadmiarowych kluczy: TypeScript przyjmuje
// `{ title, body, question }` jako `Note | Decision`, gdy klucze wystarczają jednemu wariantowi, a reszta istnieje
// w którymś z wariantów.
function regular(checker, literal) {
  return checker.getWidenedType(literal)
}

// Warianty miejsca `target`, które przyjmują literał; gdy żaden, każdy wariant (po nazwie pola).
function accepting(checker, literal, target) {
  const all = members(target)
  const accepted = all.filter((member) => checker.isTypeAssignableTo(regular(checker, literal), member))

  return accepted.length > 0 ? accepted : all
}

// Właściwości, które węzeł zapisuje: klucz literału obiektu (np. wysyłane ciało) i atrybut JSX. Klucz zapisuje
// własną właściwość literału, którą przepływy niosą dalej (`const body = { name }; send("POST", body)`), i pole
// typu, w miejsce którego literał trafia; w miejscu unii tylko w wariantach, które go przyjmują.
function writtenProperties(checker, node) {
  if (ts.isJsxAttribute(node)) {
    return [checker.getSymbolAtLocation(node.name)]
  }

  if (ts.isObjectLiteralElementLike(node) && ts.isObjectLiteralExpression(node.parent) && node.name !== undefined) {
    const name = propertyName(node.name)

    if (name === undefined) {
      return []
    }

    const literal = checker.getTypeAtLocation(node.parent)
    const own = literal.getProperty(name)
    const target = literalType(checker, node.parent)
    const written = own === undefined ? [] : [own]

    if (target === undefined) {
      return written
    }

    if (isUntyped(target)) {
      return [...written, byName(name)]
    }

    return [...written, ...accepting(checker, literal, target).flatMap((member) => member.getProperty(name) ?? [])]
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
// `T extends LiveFileView` czyta pola odpowiedzi przez `LiveFileView`; bez ograniczenia w `unknown`.
function inferredFlows(checker, node) {
  if (!ts.isCallLikeExpression(node)) {
    return []
  }

  const signature = checker.getResolvedSignature(node)
  const parameters = signature?.getDeclaration()?.typeParameters ?? []
  const inferred = signature === undefined ? [] : (checker.getTypeArgumentsForResolvedSignature(signature) ?? [])

  return parameters.flatMap((parameter, index) => {
    const constraint = checker.getTypeAtLocation(parameter).getConstraint() ?? checker.getUnknownType()

    return inferred[index] === undefined ? [] : [{ from: inferred[index], to: constraint }]
  })
}

function hasRest(signature) {
  const declaration = signature.getDeclaration()

  return declaration !== undefined && ts.hasRestParameter(declaration)
}

// Argument z każdej pozycji sygnatury `outer`, którą widzi wołający, trafia na tę samą pozycję `inner`; parametr
// reszty przyjmuje wszystkie pozycje od swojej.
function parameterFlows(outer, inner) {
  const outerCount = outer.getParameters().length
  const innerCount = inner.getParameters().length
  const restOuter = hasRest(outer)
  const restInner = hasRest(inner)

  const count =
    restOuter && restInner
      ? Math.max(outerCount, innerCount)
      : restOuter
        ? innerCount
        : restInner
          ? outerCount
          : Math.min(outerCount, innerCount)

  return Array.from({ length: count }, (_, position) => ({
    from: outer.getTypeParameterAtPosition(position),
    to: inner.getTypeParameterAtPosition(position),
  }))
}

// Funkcja z przeciążeniami: argumenty przeciążenia płyną w parametry implementacji, a jej wynik w wynik przeciążenia.
function overloadFlows(checker, node) {
  if (!ts.isFunctionLike(node) || node.body === undefined || node.name === undefined) {
    return []
  }

  const implementation = checker.getSignatureFromDeclaration(node)

  const overloads = (checker.getSymbolAtLocation(node.name)?.declarations ?? []).filter(
    (declaration) => declaration !== node && ts.isFunctionLike(declaration) && declaration.body === undefined
  )

  return implementation === undefined
    ? []
    : overloads.flatMap((declaration) => {
        const overload = checker.getSignatureFromDeclaration(declaration)

        return overload === undefined
          ? []
          : [
              ...parameterFlows(overload, implementation),
              { from: implementation.getReturnType(), to: overload.getReturnType() },
            ]
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

/**
 * Wartość płynie w typ docelowy, więc czytanie pola celu czyta pole tej samej nazwy w źródle (`<RunResultBadge
 * run={pinnable} />` z `run: Pick<ProcessRun, "result">` czyta `PinnableRun.result`), a zapisane pole źródła trafia
 * do pola celu (Uwaga zapisana jako `DadNoteRequest` idzie do serwera jako `DadNoteText`). Krawędzie łączą
 * deklaracje pól w obu kierunkach, w głąb pól i elementów tablic; każdą parę typów łączy raz, więc typy rekurencyjne
 * się kończą. Wartość typu `any`/`unknown` łączy się z polem po nazwie (`byName`).
 */
class Flows {
  // Deklaracja pola celu → deklaracje pól źródła (czytanie).
  backward = new Map()

  // Deklaracja pola źródła → deklaracje pól celu (zapis).
  forward = new Map()

  related = new Map()

  constructor(checker) {
    this.checker = checker
  }

  relate(from, to) {
    if (from === undefined || to === undefined || from === to) {
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
    // Wariant, którego żaden nie przyjmuje (`d as T` z `T` węższym niż `Decision`), płynie w każdy.
    const targets = members(to)

    for (const origin of members(from).filter((member) => !targets.includes(member))) {
      const accepted = targets.filter((member) => this.checker.isTypeAssignableTo(origin, member))

      for (const target of accepted.length > 0 ? accepted : targets) {
        this.relateMember(origin, target)
      }
    }
  }

  relateMember(from, target) {
    if (target.flags & UNTYPED) {
      this.intoUntyped(from)

      return
    }

    if (target.flags & OPAQUE) {
      return
    }

    const untyped = Boolean(from.flags & UNTYPED)

    // Funkcja płynie w miejsce funkcji: wynik płynie z niej (`open: () => Promise<{ name: string }>` czyta `name`
    // z odpowiedzi), a argumenty do niej (`checks.map(checkRow)` daje `DiagnosisCheck` parametrowi `CheckRow`).
    const signatures = target.getCallSignatures()

    if (signatures.length > 0) {
      for (const called of untyped ? [] : from.getCallSignatures()) {
        for (const signature of signatures) {
          this.relate(called.getReturnType(), signature.getReturnType())

          for (const parameter of parameterFlows(signature, called)) {
            this.relate(parameter.from, parameter.to)
          }
        }
      }

      return
    }

    const awaited = this.checker.getAwaitedType(target)

    if (awaited !== undefined && awaited !== target) {
      this.relate(untyped ? from : this.checker.getAwaitedType(from), awaited)

      return
    }

    if (this.checker.isArrayType(target) || this.checker.isTupleType(target)) {
      this.relate(untyped ? from : from.getNumberIndexType(), target.getNumberIndexType())

      return
    }

    for (const property of target.getProperties().filter(isDeclaredInSource)) {
      const origins = untyped ? [byName(property.name)] : propertiesNamed(from, property.name)

      for (const origin of origins) {
        for (const declaration of property.declarations ?? []) {
          for (const originDeclaration of origin.declarations ?? []) {
            link(this.backward, declaration, originDeclaration)
            link(this.forward, originDeclaration, declaration)
          }
        }

        this.relate(untyped ? from : this.checker.getTypeOfSymbol(origin), this.checker.getTypeOfSymbol(property))
      }
    }
  }

  // Wartość wpływa w `any`/`unknown`: jej zapisane pola trafiają do pól tej nazwy w typach, w które `any`/`unknown`
  // potem wpływa (`{ name } as unknown as IntermaxRestoreRequest`).
  intoUntyped(from) {
    if (from.flags & OPAQUE) {
      return
    }

    if (this.checker.isArrayType(from) || this.checker.isTupleType(from)) {
      this.relate(from.getNumberIndexType(), this.checker.getUnknownType())

      return
    }

    for (const property of from.getProperties().filter(isDeclaredInSource)) {
      for (const declaration of property.declarations ?? []) {
        link(this.forward, declaration, ...byName(property.name).declarations)
      }

      this.relate(this.checker.getTypeOfSymbol(property), this.checker.getUnknownType())
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

function reach(property) {
  return property?.declarations ?? []
}

/**
 * Pola kontraktu (`Schema.pole`), które mają typ w src/api/generated (`declared`), i te, które kod wartości plików
 * pisanych ręcznie czyta albo zapisuje (`used`).
 */
export function fieldUse(program, contract) {
  const checker = program.getTypeChecker()
  const { declarations, declared } = contractDeclarations(program, checker, contract)
  const flows = new Flows(checker)
  const read = new Set()
  const written = new Set()

  function visit(node) {
    if (!isInType(node)) {
      readProperties(checker, node).flatMap(reach).forEach((declaration) => read.add(declaration))
      writtenProperties(checker, node).flatMap(reach).forEach((declaration) => written.add(declaration))

      const reached = [flow(checker, node) ?? [], inferredFlows(checker, node), overloadFlows(checker, node)]

      for (const { from, to } of reached.flat()) {
        flows.relate(from, to)
      }
    }

    ts.forEachChild(node, visit)
  }

  program.getSourceFiles().filter(isHandWritten).forEach(visit)

  const named = new Map()

  for (const key of declared) {
    const [declaration] = byName(key.slice(key.indexOf(".") + 1)).declarations
    named.set(declaration, [...(named.get(declaration) ?? []), key])
  }

  // Odczyt pola po nazwie czyta każde pole kontraktu tej nazwy; zapis po nazwie idzie tylko krawędziami.
  const used = new Set([
    ...[...Flows.closure(read, flows.backward)].flatMap(
      (declaration) => declarations.get(declaration) ?? named.get(declaration) ?? []
    ),
    ...[...Flows.closure(written, flows.forward)].flatMap((declaration) => declarations.get(declaration) ?? []),
  ])

  return { declared, used }
}

// `class X extends EventSource` dziedziczy wartość, choć TypeScript nazywa ten węzeł typem.
function isClassExtends(node) {
  return (
    ts.isExpressionWithTypeArguments(node) &&
    node.parent.token === ts.SyntaxKind.ExtendsKeyword &&
    ts.isClassLike(node.parent.parent)
  )
}

export function isInType(node) {
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
