import * as React from "react"

import { getCollectiveFileVersion } from "@/api/centrum"
import { useResource, type Resource } from "@/lib/use-resource"

// Pomiar `--feature wydajnosc` (#419): pytanie o znacznik kosztuje kartę i serwer kilka milisekund, a pełny odczyt
// po zmianie biegnie tylko wtedy, gdy Autozapis zmienił plik.
const POLL_MS = 3000

/** Widok strony Uzupełnienia: odczyt Pliku zbiorczego z jego znacznikiem zapisu albo Komunikat ze znacznikiem. */
export type LiveFileView =
  | { state: "ready"; read: { version: string | null; retrying: boolean } }
  | { state: "problem"; version: string | null }

/**
 * Następne pytanie strony: `compare` porównuje znacznik zapisu z tym, z którego jest widok, i czyta plik dopiero
 * po zmianie; `retry` czyta od razu, bo ostatni odczyt się nie udał; `wait` czeka na pierwszy odczyt.
 */
type Watch = { next: "compare"; version: string | null } | { next: "retry" } | { next: "wait" }

function watchOf(resource: Resource<LiveFileView>): Watch {
  switch (resource.state) {
    case "loading":
      return { next: "wait" }
    case "failed":
      return { next: "retry" }
    case "ready": {
      const view = resource.data

      if (view.state === "problem") {
        return { next: "compare", version: view.version }
      }

      return view.read.retrying ? { next: "retry" } : { next: "compare", version: view.read.version }
    }

    default: {
      const unhandled: never = resource

      return unhandled
    }
  }
}

async function shouldRead(token: string, watch: Watch): Promise<boolean> {
  switch (watch.next) {
    case "wait":
      return false
    case "retry":
      return true
    case "compare":
      try {
        return (await getCollectiveFileVersion(token)).version !== watch.version
      } catch {
        // Bez odpowiedzi nie ma czego porównać; zapyta znów za POLL_MS.
        return false
      }

    default: {
      const unhandled: never = watch

      return unhandled
    }
  }
}

/**
 * `useResource` dla widoku, który pokazuje Plik zbiorczy okresu na żywo (okres to pierwszy argument odczytu): gdy
 * karta jest widoczna, co POLL_MS pyta serwer o znacznik zapisu i czyta widok od nowa dopiero po jego zmianie albo
 * po nieudanym odczycie.
 */
export function useLiveFile<Args extends readonly [string, ...ReadonlyArray<string>], T extends LiveFileView>(
  read: (...args: Args) => Promise<T>,
  args: Args,
  options: { fresh?: boolean } = {}
) {
  const [token] = args
  const live = useResource(read, args, options)
  const { resource, reload } = live
  const watch = React.useRef<Watch>({ next: "wait" })

  React.useEffect(() => {
    watch.current = watchOf(resource)
  }, [resource])

  React.useEffect(() => {
    let timer: number | undefined
    let asking = false
    let stopped = false

    const schedule = () => {
      window.clearTimeout(timer)

      if (!stopped && !asking && document.visibilityState === "visible") {
        timer = window.setTimeout(() => void ask(), POLL_MS)
      }
    }

    const ask = async () => {
      asking = true

      if (await shouldRead(token, watch.current)) {
        await reload()
      }

      asking = false
      schedule()
    }

    schedule()
    document.addEventListener("visibilitychange", schedule)

    return () => {
      stopped = true
      window.clearTimeout(timer)
      document.removeEventListener("visibilitychange", schedule)
    }
  }, [token, reload])

  return live
}
