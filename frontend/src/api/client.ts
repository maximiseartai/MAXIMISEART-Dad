import type * as z from "zod"

import type { ApiTiming } from "@/api/generated"
import { zProblem, zViewTiming } from "@/api/generated/zod.gen"

/** Odmowa albo awaria z komunikatem, który można pokazać tacie (bez treści błędu technicznego). */
class CentrumError extends Error {}

const UNREACHABLE =
  "Centrum rozliczeń nie odpowiada. Zamknij kartę i uruchom Centrum ponownie."

export const UNEXPECTED =
  "Centrum rozliczeń odpowiedziało w nieoczekiwany sposób. Odśwież kartę."

export function failureMessage(failure: Error): string {
  return failure instanceof CentrumError ? failure.message : UNEXPECTED
}

type Operation = ApiTiming["operation"]

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
 * Droga do serwera każdego zapytania, którego odpowiedź trafia do UI: odpowiedź jest parsowana schematem
 * wygenerowanym z kontraktu. Odmowa serwera (`Problem`) staje się `CentrumError` z jego komunikatem.
 * Czas każdego zapytania trafia do pomiaru widoku pod nazwą `operation` z kontraktu, nie pod adresem.
 *
 * Poza `call` idą tylko dwa wyjątki z `@/api/centrum`: strumień Uruchomień (`watchRunEvents`, EventSource,
 * każde zdarzenie parsowane schematem) i sam pomiar widoku (`recordViewTiming`: odpowiedź 204 bez treści,
 * więc nie ma czego parsować, a wysyłka po pomiarze nie wlicza się do żadnego widoku). Trasy poza pomiarem
 * wymienia z powodem `OUTSIDE_TIMING` w `tests/test_centrum_rozliczen.py`.
 */
export async function call<T>(
  schema: z.ZodType<T>,
  operation: Operation,
  path: string,
  init?: RequestInit
): Promise<T> {
  let response: Response
  // `Headers` przyjmuje każdą postać nagłówków z `RequestInit`; rozpakowanie `...` gubi obiekt `Headers`.
  const headers = new Headers(init?.headers)
  const started = performance.now()

  headers.set("Accept", "application/json")

  try {
    response = await fetch(path, { ...init, headers })
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

    throw new CentrumError(problem.success ? problem.data.message : UNEXPECTED)
  }

  const parsed = schema.safeParse(body)

  if (!parsed.success) {
    throw new CentrumError(UNEXPECTED)
  }

  return parsed.data
}
