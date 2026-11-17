import * as React from "react"
import { useActorRef, useSelector } from "@xstate/react"
import type { SnapshotFrom } from "xstate"

import type { ToolUpdate } from "@/api/centrum"
import { toolUpdateMachine } from "@/lib/tool-update-machine"

type ToolUpdateContextValue = {
  /** Aktualizacja narzędzia według serwera; `null`, dopóki nikt jej nie odczytał. */
  update: ToolUpdate | null
  /** Komunikat ostatniego nieudanego odczytu Aktualizacji narzędzia; `null`, gdy serwer potem podał jej stan. */
  readFailure: string | null
  /** Start wysłany albo aktualizacja trwa: każdy przycisk aktualizacji jest wtedy wyłączony. */
  busy: boolean
  /**
   * Aktualizacja zawiodła przy ponownym starcie Centrum, a tata od wejścia na stronę nie kliknął aktualizacji.
   * Komunikat porażki pokazuje wtedy `ToolUpdateAfterRestart`, nie przycisk.
   */
  restarted: boolean
  start: () => void
  read: () => void
}

type Shown = Omit<ToolUpdateContextValue, "start" | "read">

function shownOf(snapshot: SnapshotFrom<typeof toolUpdateMachine>): Shown {
  const { update, readFailure, clicked } = snapshot.context

  return {
    update,
    readFailure,
    busy: snapshot.matches("starting") || snapshot.matches("polling") || snapshot.matches("reloading"),
    restarted: update?.state === "failed" && update.after_restart && !clicked,
  }
}

function sameShown(a: Shown, b: Shown): boolean {
  return a.update === b.update && a.readFailure === b.readFailure && a.busy === b.busy && a.restarted === b.restarted
}

const ToolUpdateContext = React.createContext<ToolUpdateContextValue | null>(null)

/** Jedna Aktualizacja narzędzia na Centrum, wspólna dla każdego miejsca z przyciskiem `Zaktualizuj narzędzie`. */
export function ToolUpdateProvider({ children }: { children: React.ReactNode }) {
  const actor = useActorRef(toolUpdateMachine)
  const shown = useSelector(actor, shownOf, sameShown)
  const start = React.useCallback(() => actor.send({ type: "start" }), [actor])
  const read = React.useCallback(() => actor.send({ type: "read" }), [actor])
  const value = React.useMemo<ToolUpdateContextValue>(() => ({ ...shown, start, read }), [shown, start, read])

  return <ToolUpdateContext.Provider value={value}>{children}</ToolUpdateContext.Provider>
}

export function useToolUpdate() {
  const context = React.useContext(ToolUpdateContext)

  if (context === null) {
    throw new Error("useToolUpdate działa tylko wewnątrz ToolUpdateProvider.")
  }

  return context
}
