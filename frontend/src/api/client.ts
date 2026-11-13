import type * as z from "zod"

import type { ApiTiming } from "@/api/generated"
import { type OperationData, operations } from "@/api/generated/operations.gen"
import { zProblem, zViewTiming } from "@/api/generated/zod.gen"

/**
 * Odmowa albo awaria z komunikatem, który można pokazać tacie (bez treści błędu technicznego). `field`: pole
 * formularza, którego dotyczy zła wartość (odmowa 422 Ustawień Centrum), żeby zdanie stanęło przy nim.
 */
class CentrumError extends Error {
  readonly field: string | null

  constructor(message: string, field: string | null = null) {
    super(message)
    this.field = field
  }
}

const UNREACHABLE =
  "Centrum rozliczeń nie odpowiada. Zamknij kartę i uruchom Centrum ponownie."

export const UNEXPECTED =
  "Centrum rozliczeń odpowiedziało w nieoczekiwany sposób. Odśwież kartę."

export function failureMessage(failure: Error): string {
  return failure instanceof CentrumError ? failure.message : UNEXPECTED
}

/** Pole, którego dotyczy odmowa serwera; `null` przy odmowie bez pola i przy awarii. */
export function refusedField(failure: Error): string | null {
  return failure instanceof CentrumError ? failure.field : null
}

type Operation = ApiTiming["operation"]

type Reply<O extends Operation> = z.output<(typeof operations)[O]["response"]>

/** Parametry adresu, zapytanie i ciało operacji z jej `…Data`; operacja bez nich nie bierze drugiego argumentu. */
type Request<O extends Operation> = Omit<OperationData[O], "url">

type RequestArgument<O extends Operation> = object extends Request<O> ? [request?: Request<O>] : [request: Request<O>]

/** Ciało zapytania którejkolwiek operacji kontraktu. */
type Body = NonNullable<OperationData[keyof OperationData]["body"]>

type RequestParts = {
  path?: Record<string, string>
  query?: Record<string, string | null | undefined>
  body?: Body
}

/** Zapytanie z ciałem JSON (POST, PUT); bez `body` samo zapytanie bez treści. */
export function jsonRequest(method: string, body?: Body): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  }
}

/** Adres operacji z kontraktu: `{parametr}` z `path`, a z `query` tylko wartości, które są. */
function address(url: string, { path, query }: RequestParts): string {
  const filled = url.replaceAll(/\{(\w+)\}/g, (_, name: string) => encodeURIComponent(path?.[name] ?? ""))
  const given = Object.entries(query ?? {}).filter((entry): entry is [string, string] => entry[1] != null)
  const search = new URLSearchParams(given).toString()

  return search === "" ? filled : `${filled}?${search}`
}

/** Zakończone zapytanie API z czasami do pomiaru widoku (`performance.now()` w milisekundach). */
type TimedRequest = ApiTiming & { started: number; ended: number }

// Zakończone zapytania, których pomiar widoku jeszcze nie zabrał, od najstarszego.
let timedRequests: TimedRequest[] = []

// Pamięć mieści tyle zapytań, ile kontrakt przyjmuje w jednym pomiarze widoku (`ViewTiming.requests`), i ani
// jednego więcej: nowe zapytanie wypycha najstarsze. Widok z większą liczbą zapytań (np. odświeżanie po
// powrocie do karty w trakcie odczytu) trafia więc do dziennika z najnowszymi, a nie przepada w walidacji.
const REMEMBERED_REQUESTS = zViewTiming.shape.requests.toJSONSchema().maxItems ?? 0

/**
 * Zabiera zapytania widoku, rozpoczęte od `start` i zakończone do `ready`, i zapomina wszystkie rozpoczęte
 * przed `start`: należały do poprzedniego widoku albo do powrotu do karty bez nowego widoku.
 */
export function takeRequestsSince(start: number, ready: number): TimedRequest[] {
  const current = timedRequests.filter((request) => request.started >= start)

  timedRequests = current.filter((request) => request.ended > ready)

  return current.filter((request) => request.ended <= ready)
}

/** Czas serwera z nagłówka `Server-Timing` (`centrum;dur=12.3`); `null`, gdy go brak. */
function serverMs(response: Response): number | null {
  const duration = /dur=(\d+(?:\.\d+)?)/.exec(response.headers.get("Server-Timing") ?? "")

  return duration === null ? null : Math.round(Number(duration[1]))
}

/**
 * Droga do serwera każdego zapytania, którego odpowiedź trafia do UI: metoda, adres i schemat odpowiedzi
 * operacji `operation` z tablicy wygenerowanej z kontraktu (`operations.gen.ts`), a `request` niesie jej
 * parametry adresu, zapytanie i ciało. Odmowa serwera (`Problem`) staje się `CentrumError` z jego komunikatem.
 * Czas każdego zapytania trafia do pomiaru widoku pod nazwą `operation` z kontraktu, nie pod adresem.
 *
 * Poza `call` idą tylko dwa wyjątki z `@/api/centrum`: strumień Uruchomień (`watchRunEvents`, EventSource,
 * każde zdarzenie parsowane schematem) i sam pomiar widoku (`recordViewTiming`: odpowiedź 204 bez treści,
 * więc nie ma czego parsować, a wysyłka po pomiarze nie wlicza się do żadnego widoku). Trasy poza pomiarem
 * wymienia z powodem `OUTSIDE_TIMING` w `tests/test_centrum_rozliczen.py`.
 */
export async function call<O extends Operation>(operation: O, ...[request]: RequestArgument<O>): Promise<Reply<O>> {
  const { method, url } = operations[operation]
  const schema: z.ZodType = operations[operation].response
  const parts: RequestParts = request ?? {}
  const init = method === "GET" ? undefined : jsonRequest(method, parts.body)
  let response: Response
  // `Headers` przyjmuje każdą postać nagłówków z `RequestInit`; rozpakowanie `...` gubi obiekt `Headers`.
  const headers = new Headers(init?.headers)
  const started = performance.now()

  headers.set("Accept", "application/json")

  try {
    response = await fetch(address(url, parts), { ...init, headers })
  } catch {
    throw new CentrumError(UNREACHABLE)
  }

  const body: unknown = await response.json().catch(() => null)
  const ended = performance.now()

  if (timedRequests.length >= REMEMBERED_REQUESTS) {
    timedRequests.shift()
  }

  timedRequests.push({
    operation,
    browser_ms: Math.round(ended - started),
    server_ms: serverMs(response),
    started,
    ended,
  })

  if (!response.ok) {
    const problem = zProblem.safeParse(body)

    throw problem.success ? new CentrumError(problem.data.message, problem.data.field ?? null) : new CentrumError(UNEXPECTED)
  }

  const parsed = schema.safeParse(body)

  if (!parsed.success) {
    throw new CentrumError(UNEXPECTED)
  }

  // SAFETY: `schema` to `operations[operation].response`, więc jego wynik ma typ odpowiedzi operacji `operation`.
  return parsed.data as Reply<O>
}
