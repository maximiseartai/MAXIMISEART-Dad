// Reguła 1 (field-use.mjs) na sondach przeglądów #1098: każda sonda to plik src, który `tsc` przyjmuje, z kontraktem
// `Decision` i `RunInfo`; test sprawdza, czy reguła liczy `Decision.title` jako użyte. „Użyte” tam, gdzie kod czyta
// albo zapisuje pole (inaczej reguła żąda usunięcia pola, którego UI potrzebuje), „nieużyte” tam, gdzie typy są
// pewne, a kod pola nie dotyka.
import assert from "node:assert/strict"
import { join } from "node:path"
import { test } from "node:test"
import ts from "typescript"
import { compilerConfig, fieldUse, source } from "./field-use.mjs"

const TYPES = `export type Decision = { title: string; question: string; message: string | null; counts: number[] }
export type RunInfo = { title: string; process: string }
`

const CONTRACT = {
  components: {
    schemas: {
      Decision: { properties: { title: {}, question: {}, message: {}, counts: {} } },
      RunInfo: { properties: { title: {}, process: {} } },
    },
  },
}

const D = 'import type { Decision } from "./api/generated/types.gen"\n'

const DR = 'import type { Decision, RunInfo } from "./api/generated/types.gen"\n'

const NOTE = "type Note = { title: string; body: string }\n"

const POST = "export function post(body: Note | Decision): string { return JSON.stringify(body) }\n"

const FULL = 'title: "t", question: "q", message: null, counts: []'

// [nazwa, czy Decision.title użyte, treść pliku src/probe.tsx]
const PROBES = [
  // r1: odczyty
  ["R1 optional chaining", true, D + "export const f = (d: Decision | null) => d?.title\n"],
  ["R2 as do własnego typu", true, D + "type T = { title: string }\nexport const f = (d: Decision) => (d as T).title\n"],
  ["R3 satisfies", true, D + "type T = { title: string }\nexport const f = (d: Decision) => (d satisfies T).title\n"],
  ["R4 alias typu", true, D + "type A = Decision\nexport const f = (d: A) => d.title\n"],
  ["R5 map z lambdą", true, D + "export const f = (ds: Decision[]) => ds.map((d) => d.title)\n"],
  ["R7 spread i odczyt", true, D + "export const f = (d: Decision) => ({ ...d, x: 1 }).title\n"],
  [
    "R8 rest destrukturyzacji",
    true,
    D + "export const f = (d: Decision) => { const { question, ...rest } = d; return question + rest.title }\n",
  ],
  ["R9 parametr destrukturyzowany", true, D + "export const f = ({ title }: Decision) => title\n"],
  ["R10 przekazanie do funkcji", true, D + "const t = (x: { title: string }) => x.title\nexport const f = (d: Decision) => t(d)\n"],
  [
    "R11 callback jako argument",
    true,
    D + "const each = (cb: (x: Decision) => string) => cb\nexport const f = each((x: { title: string }) => x.title)\n",
  ],
  ["R13 krotka", true, D + "export const f = (ds: [Decision]) => { const [a] = ds; return a.title }\n"],
  [
    "R14 generyk z ograniczeniem",
    true,
    D + "function t<T extends { title: string }>(x: T) { return x.title }\nexport const f = (d: Decision) => t(d)\n",
  ],
  [
    "R15 zmienna lokalnego typu",
    true,
    D + "type T = { title: string }\nexport const f = (d: Decision) => { const x: T = d; return x.title }\n",
  ],
  [
    "R16 przypisanie do let",
    true,
    D + "type T = { title: string }\nexport const f = (d: Decision) => { let x: T | undefined; x = d; return x.title }\n",
  ],
  ["R17 element przez indeks", true, D + "export const f = (ds: Decision[]) => ds[0]?.title\n"],
  [
    "R18 wynik funkcji",
    true,
    D + "type T = { title: string }\nconst g = (d: Decision): T => d\nexport const f = (d: Decision) => g(d).title\n",
  ],
  // r1: bez odczytu
  ["U1 spread bez odczytu", false, D + "export const f = (d: Decision) => ({ ...d }).question\n"],
  [
    "U2 obiekt do funkcji czytającej question",
    false,
    D + "const q = (x: { question: string; title?: string }) => x.question\nexport const f = (d: Decision) => q(d)\n",
  ],
  // `as unknown` gubi typ: odczyt `title` po rzutowaniu wraca do nazwy.
  ["U3 as unknown as T", true, D + "export const f = (d: Decision) => (d as unknown as { title: string }).title\n"],
  ["U4 wzmianka w typie", false, D + 'export type T = Decision["title"]\n'],
  // Granica: literał typu odpowiedzi zapisuje pole, choć UI go nie czyta.
  ["U5 literał typu odpowiedzi", true, D + `export const d: Decision = { ${FULL} }\n`],
  ["U6 in jako warunek", true, DR + 'export const f = (d: Decision | RunInfo) => ("title" in d ? 1 : 2)\n'],
  // Granica: wartości, które płyną w jeden typ, łączą się przez niego, choć `Decision` z `b` nikt nie czyta.
  [
    "U7 RunInfo.title przez wspólny typ",
    true,
    DR +
      "type T = { title: string }\nconst show = (x: T) => x.title\nexport const a = (r: RunInfo) => show(r)\n" +
      "export const b = (d: Decision): T[] => [d]\n",
  ],
  [
    "U7b RunInfo.title przez wspólny typ, Decision poza nim",
    false,
    DR +
      "type T = { title: string }\nconst show = (x: T) => x.title\nexport const a = (r: RunInfo) => show(r)\n" +
      "export const b = (d: Decision): unknown[] => [d]\n",
  ],
  ["U8 JSON.stringify (granica)", false, D + "export const f = (d: Decision) => JSON.stringify(d)\n"],
  ["U9 klucz przez indeks", false, D + 'export const f = (d: Decision, k: "question") => d[k]\n'],
  ["R12 Object.entries (granica)", false, D + "export const f = (d: Decision) => Object.entries(d).map(([k]) => k)\n"],
  // r2: callback podany bez lambdy
  ["C1 map(fn)", true, D + "const t = (x: { title: string }) => x.title\nexport const f = (ds: Decision[]) => ds.map(t)\n"],
  [
    "C2 then(setX) z useState",
    true,
    D +
      'import { useState } from "react"\ntype Row = { title: string }\n' +
      "export function useF(p: Promise<Decision>) { const [r, setR] = useState<Row | null>(null); void p.then(setR); return r?.title }\n",
  ],
  [
    "C3 forEach(fn)",
    true,
    D +
      "const out: string[] = []\nconst t = (x: { title: string }) => { out.push(x.title) }\n" +
      "export const f = (ds: Decision[]) => ds.forEach(t)\n",
  ],
  [
    "C4 metoda obiektu",
    true,
    D + "const o = { t(x: { title: string }) { return x.title } }\nexport const f = (ds: Decision[]) => ds.map(o.t)\n",
  ],
  [
    "C5 funkcja generyczna",
    true,
    D + "function t<T extends { title: string }>(x: T) { return x.title }\nexport const f = (ds: Decision[]) => ds.map(t)\n",
  ],
  [
    "C6 przeciążenia, wspólny typ",
    true,
    D +
      "type T = { title: string }\nfunction t(x: T): string\nfunction t(x: number): string\n" +
      'function t(x: T | number) { return typeof x === "number" ? "" : x.title }\nexport const f = (ds: Decision[]) => ds.map(t)\n',
  ],
  [
    "C7 przeciążenia, własny typ implementacji",
    true,
    D +
      "function t(x: { title: string }): string\nfunction t(x: number): string\n" +
      'function t(x: { title: string } | number) { return typeof x === "number" ? "" : x.title }\n' +
      "export const f = (ds: Decision[]) => ds.map(t)\n",
  ],
  [
    "C8 prop JSX render={fn}",
    true,
    D +
      "const show = (x: { title: string }) => x.title\n" +
      "function List({ items, render }: { items: Decision[]; render: (d: Decision) => string }) {\n" +
      "  return <ul>{items.map((d) => <li key={d.question}>{render(d)}</li>)}</ul>\n}\n" +
      "export const C = (p: { ds: Decision[] }) => <List items={p.ds} render={show} />\n",
  ],
  [
    "C9 drugi parametr reduce",
    true,
    D + 'const acc = (s: string, x: { title: string }) => s + x.title\nexport const f = (ds: Decision[]) => ds.reduce(acc, "")\n',
  ],
  [
    "C10 sort(komparator)",
    true,
    D +
      "type T = { title: string }\nconst by = (a: T, b: T) => a.title.localeCompare(b.title)\n" +
      "export const f = (ds: Decision[]) => [...ds].sort(by)\n",
  ],
  [
    "C11 useCallback potem map(cb)",
    true,
    D +
      'import { useCallback } from "react"\n' +
      "export function useF(ds: Decision[]) { const cb = useCallback((x: { title: string }) => x.title, []); return ds.map(cb) }\n",
  ],
  ["C12 Array.from(ds, fn)", true, D + "const t = (x: { title: string }) => x.title\nexport const f = (ds: Decision[]) => Array.from(ds, t)\n"],
  [
    "C13 apply<T>(x, f)",
    true,
    D +
      "const apply = <T,>(x: T, f: (v: T) => string) => f(x)\nconst t = (x: { title: string }) => x.title\n" +
      "export const f = (d: Decision) => apply(d, t)\n",
  ],
  [
    "C14 parametr reszty celu",
    true,
    D +
      "const each = (cb: (...xs: Decision[]) => string) => cb\n" +
      "const t = (a: { question: string }, b: { title: string }) => a.question + b.title\nexport const f = each(t)\n",
  ],
  [
    "C15 zagnieżdżony typ",
    true,
    D + "type W = { inner: { title: string } }\nconst t = (x: W) => x.inner.title\nexport const f = (ws: { inner: Decision }[]) => ws.map(t)\n",
  ],
  [
    "C24 głęboko zagnieżdżone pole",
    true,
    D +
      "type Deep = { a: { b: { c: { d: { e: { title: string } }[] } } } }\nconst t = (x: Deep) => x.a.b.c.d[0]?.e.title\n" +
      "export const f = (ws: { a: { b: { c: { d: { e: Decision }[] } } } }[]) => ws.map(t)\n",
  ],
  [
    "C25 Promise w miejscu Promise",
    true,
    D + "const show = async (p: Promise<{ title: string }>) => (await p).title\nexport const f = (p: Promise<Decision>) => show(p)\n",
  ],
  [
    "C16 filter(predykat)",
    true,
    D + 'const has = (x: { title: string }): boolean => x.title !== ""\nexport const f = (ds: Decision[]) => ds.filter(has)\n',
  ],
  ["C17 then(fn)", true, D + "const t = (x: { title: string }) => x.title\nexport const f = (p: Promise<Decision>) => p.then(t)\n"],
  ["C18 zmienna typu funkcji", true, D + "const t = (x: { title: string }) => x.title\nexport const g: (d: Decision) => string = t\n"],
  [
    "C19 parametr reszty źródła",
    true,
    D +
      "const each = (cb: (a: Decision, b: Decision) => string) => cb\n" +
      "const t = (...xs: { title: string }[]) => xs.map((x) => x.title).join()\nexport const f = each(t)\n",
  ],
  [
    "C19b parametr reszty źródła, różne pozycje",
    true,
    DR +
      "const each = (cb: (a: RunInfo, b: Decision) => string) => cb\n" +
      "const t = (...xs: { title: string }[]) => xs.map((x) => x.title).join()\nexport const f = each(t)\n",
  ],
  [
    "C22 generyk przekazuje wartość dalej",
    true,
    D +
      "const show = (y: { title: string }) => y.title\nfunction pass<T extends { title: string }>(x: T) { return show(x) }\n" +
      "export const f = (d: Decision) => pass(d)\n",
  ],
  [
    "C20 generyczny komparator",
    true,
    D +
      "function byTitle<T extends { title: string }>(a: T, b: T) { return a.title.localeCompare(b.title) }\n" +
      "export const f = (ds: Decision[]) => [...ds].sort(byTitle)\n",
  ],
  [
    "C21 funkcja w miejscu funkcji: wynik",
    true,
    D + "const show = (get: () => { title: string }) => get().title\nexport const f = (get: () => Decision) => show(get)\n",
  ],
  [
    "C23 przeciążony typ callbacku",
    true,
    DR +
      "type Show = { (x: RunInfo): string; (x: Decision): string }\nconst each = (cb: Show) => cb\n" +
      "const t = (x: { title: string }) => x.title\nexport const f = each(t)\n",
  ],
  [
    "F1 callback czyta tylko question",
    false,
    D + "const t = (x: { question: string; title?: string }) => x.question\nexport const f = (ds: Decision[]) => ds.map(t)\n",
  ],
  ["F2 callback z parametrem object", false, D + "const t = (x: object) => String(x)\nexport const f = (ds: Decision[]) => ds.map(t)\n"],
  [
    "F3 then(setX) bez odczytu title",
    false,
    D +
      'import { useState } from "react"\ntype Row = { title: string; question: string }\n' +
      "export function useF(p: Promise<Decision>) { const [r, setR] = useState<Row | null>(null); void p.then(setR); return r?.question }\n",
  ],
  [
    "F4 callback innej tablicy",
    false,
    D + "const t = (x: { title: string }) => x.title\nexport const f = (ds: { title: string }[], d: Decision) => [ds.map(t), d.question]\n",
  ],
  // r2: literał w unii i bez typu kontekstowego
  ["W1 literał Note w Note | Decision", false, D + NOTE + POST + 'export const sent = post({ title: "x", body: "y" })\n'],
  [
    "W2 dyskryminator, wariant a",
    false,
    D +
      'type A = { kind: "a"; title: string }\ntype B = Decision & { kind: "b" }\n' +
      'export const post = (b: A | B) => JSON.stringify(b)\nexport const s = post({ kind: "a", title: "x" })\n',
  ],
  [
    "W3 dyskryminator, wariant b",
    true,
    D +
      'type A = { kind: "a"; title: string }\ntype B = Decision & { kind: "b" }\n' +
      `export const post = (b: A | B) => JSON.stringify(b)\nexport const s = post({ kind: "b", ${FULL} })\n`,
  ],
  [
    "W4 pole opcjonalne",
    false,
    D +
      "type Opt = { title?: string; body?: string }\nexport const post = (b: Opt | Decision) => JSON.stringify(b)\n" +
      'export const s = post({ title: "x" })\n',
  ],
  ["W5 literał z kluczami obu wariantów", true, D + NOTE + POST + `export const s = post({ body: "y", ${FULL} })\n`],
  ["W6 literał Decision w unii", true, D + NOTE + POST + `export const s = post({ ${FULL} })\n`],
  ["W7 as Note | Decision z literałem Note", false, D + NOTE + 'export const x = { title: "x", body: "y" } as Note | Decision\n'],
  ["W8 as Decision | Note z częścią Decision", true, D + NOTE + 'export const x = { title: "x", question: "q" } as Decision | Note\n'],
  [
    "W24 generyk z ograniczeniem unii przekazuje wartość dalej",
    false,
    D +
      NOTE +
      'const show = (n: Note | Decision) => ("body" in n ? n.title : n.question)\n' +
      "function pass<T extends Note | Decision>(x: T) { return show(x) }\nexport const f = (n: Note) => pass(n)\n",
  ],
  [
    "W9 generyk z ograniczeniem unii",
    false,
    D + NOTE + 'export const post = <T extends Note | Decision>(b: T) => JSON.stringify(b)\nexport const s = post({ title: "x", body: "y" })\n',
  ],
  ["W10 zagnieżdżony literał", false, D + NOTE + 'type Wrap = { item: Note | Decision }\nexport const w: Wrap = { item: { title: "x", body: "y" } }\n'],
  ["W11 tablica unii", false, D + NOTE + 'export const xs: (Note | Decision)[] = [{ title: "x", body: "y" }]\n'],
  [
    "W12 Decision | null w useState",
    true,
    D + `import { useState } from "react"\nexport function useF() { const [d] = useState<Decision | null>({ ${FULL} }); return d?.question }\n`,
  ],
  ["W13 spread Note w unii", false, D + NOTE + POST + 'export const s = (n: Note) => post({ ...n, title: "x" })\n'],
  [
    "W14 Partial<Decision> | Note",
    true,
    D + NOTE + 'export const post = (b: Partial<Decision> | Note) => JSON.stringify(b)\nexport const s = post({ title: "x", question: "q" })\n',
  ],
  ["W15 funkcja zwracająca literał Note", false, D + NOTE + 'export const g: () => Note | Decision = () => ({ title: "x", body: "y" })\n'],
  [
    "W16 dwa warianty bez nadmiaru",
    true,
    D +
      "type Loose = { title: string; question: string; message?: unknown; counts?: unknown }\n" +
      `export const post = (b: Loose | Decision) => JSON.stringify(b)\nexport const s = post({ ${FULL} })\n`,
  ],
  [
    "W17 klucze obu wariantów z wartościami",
    true,
    D + NOTE + POST + 'export const s = (d: Decision) => post({ title: "x", body: "y", question: "q", message: d.message, counts: d.counts })\n',
  ],
  ["W18 zmienna z kluczami obu wariantów", true, D + NOTE + POST + `export const s = () => { const v = { body: "y", ${FULL} }; return post(v) }\n`],
  [
    "W19 literał bez typu, potem zmienna Decision",
    true,
    D + `export const s = () => { const v = { ${FULL} }; const x: Decision = v; return x.question }\n`,
  ],
  [
    "W20 literał bez typu do post(Decision)",
    true,
    D + `const post = (b: Decision) => JSON.stringify(b)\nexport const s = () => { const v = { ${FULL} }; return post(v) }\n`,
  ],
  [
    "W21 literał Note z kluczem question w Note | Decision",
    false,
    D + NOTE + POST + 'export const s = post({ title: "x", body: "y", question: "q" })\n',
  ],
  [
    "W22 zapis przez unknown",
    true,
    D + `const post = (b: Decision) => JSON.stringify(b)\nexport const s = post({ ${FULL} } as unknown as Decision)\n`,
  ],
  [
    "W23 zmienna rzutowana przez unknown",
    true,
    D + `const post = (b: Decision) => JSON.stringify(b)\nexport const s = () => { const v = { ${FULL} }; return post(v as unknown as Decision) }\n`,
  ],
  [
    "R19 as do węższego typu",
    true,
    D +
      "type T = { title: string; question: string; message: string | null; counts: number[]; extra: number }\n" +
      "export const f = (d: Decision) => (d as T).title\n",
  ],
  ["A3 odczyt pola wartości any", true, "export const f = (x: string): unknown => JSON.parse(x).title\n"],
  ["A4 in na wartości any", true, 'export const f = (x: string) => "title" in JSON.parse(x)\n'],
  [
    "A5 strażnik typu na unknown",
    true,
    'export const f = (x: unknown) => typeof x === "object" && x !== null && "title" in x ? String(x.title) : ""\n',
  ],
  [
    "W25 literał do parametru typu bez ograniczenia",
    true,
    D +
      "const post = (b: Decision) => JSON.stringify(b)\nfunction send<T>(body: T) { return post(body as unknown as Decision) }\n" +
      `export const s = send({ ${FULL} })\n`,
  ],
  [
    "W26 zmienna do parametru typu bez ograniczenia",
    true,
    D +
      "const post = (b: Decision) => JSON.stringify(b)\nfunction send<T>(body: T) { return post(body as unknown as Decision) }\n" +
      `export const s = () => { const v = { ${FULL} }; return send(v) }\n`,
  ],
  ["A1 odczyt wprost na any", true, "export const f = (x: string) => (JSON.parse(x) as { title: string }).title\n"],
  ["A2 any w parametrze callbacku", true, "const t = (x: { title: string }) => x.title\nexport const f = (xs: any[]) => xs.map(t)\n"],
]

const config = compilerConfig()

const types = join(source, "api", "generated", "types.gen.ts")

const zod = join(source, "api", "generated", "zod.gen.ts")

const probe = join(source, "probe.tsx")

const cache = new Map()

function host(text) {
  const files = new Map([
    [types, TYPES],
    [zod, "export {}\n"],
    [probe, text],
  ])

  const base = ts.createCompilerHost(config.options)

  return {
    ...base,
    fileExists: (name) => files.has(name) || base.fileExists(name),
    readFile: (name) => files.get(name) ?? base.readFile(name),
    getSourceFile(name, language) {
      if (files.has(name)) {
        return ts.createSourceFile(name, files.get(name), language, true)
      }

      if (!cache.has(name)) {
        cache.set(name, base.getSourceFile(name, language))
      }

      return cache.get(name)
    },
  }
}

for (const [name, expected, text] of PROBES) {
  test(name, () => {
    const program = ts.createProgram({ rootNames: [probe, types, zod], options: config.options, host: host(text) })

    const errors = ts
      .getPreEmitDiagnostics(program, program.getSourceFile(probe))
      .map((diagnostic) => ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n"))

    assert.deepEqual(errors, [])
    assert.equal(fieldUse(program, CONTRACT).used.has("Decision.title"), expected)
  })
}
