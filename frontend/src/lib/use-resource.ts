import * as React from "react"

import { failureMessage } from "@/api/client"

/** Stan odczytu z serwera. Ponowny odczyt zostawia poprzednie dane, więc widok nie miga szkieletem. */
export type Resource<T> =
  | { state: "loading" }
  | { state: "ready"; data: T }
  | { state: "failed"; message: string }

/** Argument odczytu: okres, rodzaj, identyfikator Uruchomienia. Razem z funkcją odczytu wyznacza, co jest „tym samym odczytem”. */
type ReadArgument = string | null

type LastRead = { data: unknown; read: number }

/** Funkcja odczytu z `@/api/centrum`: pod nią pamięć trzyma ostatnie dane jej odczytów. */
type Read<Args extends ReadonlyArray<ReadArgument>, T> = (...args: Args) => Promise<T>

/**
 * Numer plików taty, z których serwer czyta strony (folder okresów i Rejestr zleceń, bez motywu). Rośnie przy
 * wskazaniu innych plików (`SettingsProvider`); inny numer to inny odczyt każdej strony, która z nich czyta.
 */
export const DadFilesVersion = React.createContext(0)

// Ostatnie dane każdego odczytu, pod funkcją odczytu z `@/api/centrum` i kluczem z argumentów i numeru plików taty.
// To tylko kopia ostatniej odpowiedzi serwera w pamięci karty (odświeżenie karty ją czyści); źródłem Statusu okresu
// nadal jest serwer (ADR 0004).
const lastReads = new Map<Read<never, unknown>, Map<string, LastRead>>()

// Numer każdego odczytu i każdej podmiany: kopię nadpisuje tylko nowszy, także z innej strony.
let reads = 0

function readsOf<Args extends ReadonlyArray<ReadArgument>, T>(read: Read<Args, T>): Map<string, LastRead> {
  let found = lastReads.get(read)

  if (found === undefined) {
    found = new Map()
    lastReads.set(read, found)
  }

  return found
}

function lastData<Args extends ReadonlyArray<ReadArgument>, T>(read: Read<Args, T>, key: string): Resource<T> {
  const last = lastReads.get(read)?.get(key)

  if (last === undefined) {
    return { state: "loading" }
  }

  // SAFETY: wpis pod funkcją `read` zapisuje tylko `remember` z danymi, które zwróciła ta sama funkcja.
  return { state: "ready", data: last.data as T }
}

function remember<Args extends ReadonlyArray<ReadArgument>, T>(
  read: Read<Args, T>,
  key: string,
  request: number,
  next: Resource<T>
) {
  const kept = readsOf(read)
  const last = kept.get(key)

  if (last !== undefined && last.read > request) {
    return
  }

  // Nieudany odczyt usuwa kopię: przy następnym wejściu tata zobaczy szkielet, a nie dane sprzed porażki.
  if (next.state === "ready") {
    kept.set(key, { data: next.data, read: request })
  } else {
    kept.delete(key)
  }
}

type Shown<T> = { key: string; resource: Resource<T> }

/**
 * Odczyt `read(...args)` z serwera z ponowieniem na żądanie i po powrocie do karty: Status okresu wylicza serwer
 * z plików przy każdym odczycie, więc po zmianach w Eksploratorze wystarczy wrócić do karty. Strona, na której
 * tata już był, od razu pokazuje ostatnie dane tego samego odczytu i czyta od nowa w tle. Inne argumenty albo
 * inne pliki taty to inny odczyt: widok pokazuje jego ostatnie dane albo szkielet. Z `fresh` pierwszy widok czeka
 * na odczyt zamiast pokazać ostatnie dane, bo mogą być sprzed zmiany plików. `fromDadFiles: false` dla odczytu,
 * którego nie zmieniają pliki taty. Liczy się tylko najnowszy odczyt.
 */
export function useResource<Args extends ReadonlyArray<ReadArgument>, T>(
  read: Read<Args, T>,
  args: Args,
  { fresh = false, fromDadFiles = true }: { fresh?: boolean; fromDadFiles?: boolean } = {}
) {
  const files = React.useContext(DadFilesVersion)
  const key = JSON.stringify(fromDadFiles ? [files, args] : [args])
  const start = (): Shown<T> => ({ key, resource: fresh ? { state: "loading" } : lastData(read, key) })
  const [shown, setShown] = React.useState<Shown<T>>(start)
  const latest = React.useRef(0)
  const latestArgs = React.useRef(args)
  let resource = shown.resource

  if (shown.key !== key) {
    const next = start()

    setShown(next)
    resource = next.resource
  }

  React.useEffect(() => {
    latestArgs.current = args
  })

  const show = React.useCallback(
    (request: number, next: Resource<T>) => {
      remember(read, key, request, next)
      setShown({ key, resource: next })
    },
    [read, key]
  )

  const reload = React.useCallback(() => {
    const request = ++reads

    latest.current = request

    return read(...latestArgs.current).then(
      (data) => {
        if (request === latest.current) {
          show(request, { state: "ready", data })
        }
      },
      (failure: Error) => {
        if (request === latest.current) {
          show(request, { state: "failed", message: failureMessage(failure) })
        }
      }
    )
  }, [read, show])

  React.useEffect(() => {
    // Powrót do karty daje `visibilitychange` i `focus`, w dowolnej kolejności. Gdy odczyt po jednym z nich
    // jest jeszcze w drodze, drugi należy do tego samego powrotu i nie czyta drugi raz.
    let returning: { signal: "focus" | "visible"; read: Promise<void> } | undefined

    const readOnReturn = (signal: "focus" | "visible") => {
      if (returning !== undefined && returning.signal !== signal) {
        return
      }

      const current = { signal, read: reload() }

      returning = current
      current.read.finally(() => {
        if (returning === current) {
          returning = undefined
        }
      })
    }

    const reloadOnFocus = () => readOnReturn("focus")

    const reloadWhenVisible = () => {
      if (document.visibilityState === "visible") {
        readOnReturn("visible")
      } else {
        returning = undefined
      }
    }

    reload()
    window.addEventListener("focus", reloadOnFocus)
    document.addEventListener("visibilitychange", reloadWhenVisible)

    return () => {
      window.removeEventListener("focus", reloadOnFocus)
      document.removeEventListener("visibilitychange", reloadWhenVisible)
    }
  }, [reload])

  // Wynik akcji (np. wybór w oknie) zastępuje odczyt, który był jeszcze w drodze, także w kopii.
  const replace = React.useCallback(
    (next: Resource<T>) => {
      const request = ++reads

      latest.current = request
      show(request, next)
    },
    [show]
  )

  return { resource, reload, replace }
}
