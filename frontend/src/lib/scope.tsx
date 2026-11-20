import * as React from "react"

import { getScope } from "@/api/centrum"
import { failureMessage } from "@/api/client"
import type { CentrumFunction } from "@/api/generated"
import { LoadFailure } from "@/components/load-failure"

export type Declared = { function: CentrumFunction | null }

type ScopeRead =
  | { state: "loading" }
  | { state: "ready"; functions: ReadonlySet<CentrumFunction> }
  | { state: "failed"; message: string }

const Functions = React.createContext<ReadonlySet<CentrumFunction> | null>(null)

export function ScopeProvider({ children }: { children: React.ReactNode }) {
  const [read, setRead] = React.useState<ScopeRead>({ state: "loading" })

  const load = React.useCallback(
    () =>
      getScope().then(
        (scope) => setRead({ state: "ready", functions: new Set(scope.functions) }),
        (failure: Error) => setRead({ state: "failed", message: failureMessage(failure) })
      ),
    []
  )

  React.useEffect(() => {
    void load()
  }, [load])

  switch (read.state) {
    case "loading":
      return null
    case "failed":
      return (
        <div className="mx-auto w-full max-w-2xl px-4 py-10">
          <LoadFailure what="Centrum rozliczeń" message={read.message} reload={load} />
        </div>
      )
    case "ready":
      return <Functions value={read.functions}>{children}</Functions>
    default: {
      const unhandled: never = read

      return unhandled
    }
  }
}

export function useInScope<Entry extends Declared>(entries: ReadonlyArray<Entry>): ReadonlyArray<Entry> {
  const functions = React.useContext(Functions)

  return React.useMemo(() => {
    if (functions === null) {
      throw new Error("useInScope działa tylko pod ScopeProvider.")
    }

    return entries.filter((entry) => entry.function === null || functions.has(entry.function))
  }, [entries, functions])
}
