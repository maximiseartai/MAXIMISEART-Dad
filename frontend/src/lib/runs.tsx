import * as React from "react"

import { failureMessage } from "@/api/client"
import {
  decideRun,
  startIntermax,
  startRun,
  watchRunEvents,
  type DecisionAnswer,
  type RunEvent,
  type RunInfo,
  type RunRequest,
  type RunView,
} from "@/api/centrum"
import { toast } from "@/components/ui/toast"

/** Okres i proces wybrane w innym miejscu (np. w Tablicy okresów) do formularza nowego Uruchomienia. */
export type RunDraft = Pick<RunRequest, "process" | "period">

/** Start Uruchomienia: proces z okresem albo Uporządkowanie INTERMAX, które bierze tylko Ustawienia taty. */
export type RunStart = RunRequest | { process: "intermax" }

/** Ten sam proces jeszcze raz: z okresem i trybem `dryRun`, a Uporządkowanie INTERMAX z Ustawień taty. */
export function rerunOf(run: RunInfo, dryRun: boolean): RunStart {
  return run.process === "intermax"
    ? { process: "intermax" }
    : { process: run.process, period: run.period, dry_run: dryRun }
}

type RunsContextValue = {
  /** Bieżące Uruchomienie procesu ze strumienia; `null`, dopóki nie przyjdzie pierwszy widok. */
  view: RunView | null
  /** Połączenie ze strumieniem zerwane; przeglądarka łączy się ponownie sama. */
  disconnected: boolean
  draft: RunDraft | null
  setDraft: (draft: RunDraft | null) => void
  /** Zakończone Uruchomienie, którego wynik tata odłożył przyciskiem „Nowe Uruchomienie procesu”. */
  dismissed: string | null
  newRun: (finishedRunId: string) => void
  /** Start wysłany, a strumień nie pokazał jeszcze nowego Uruchomienia; do tej pory kolejny start nic nie wysyła. */
  starting: boolean
  start: (request: RunStart) => Promise<boolean>
  /**
   * „Uruchom ponownie”: ten sam proces i okres w tym samym trybie podglądu. Wycena w efenix nie startuje od razu, tylko
   * wraca do karty startu z tym okresem, bo tryb Wyceny tata wybiera przy każdym starcie (ADR 0027).
   */
  rerun: (run: RunInfo) => void
  /** Uruchomienie, którego decyzja jest wysłana, a strumień nadal pokazuje, że na nią czeka. */
  deciding: string | null
  decide: (runId: string, answer: DecisionAnswer["answer"]) => void
}

const RunsContext = React.createContext<RunsContextValue | null>(null)

function showFailure(failure: Error) {
  toast.add({ title: "Nie udało się", description: failureMessage(failure), type: "error" })
}

/** Start czekający na strumień: Uruchomienie widoczne przed startem i to, które serwer przyjął (`undefined` przed odpowiedzią). */
type PendingStart = { before: string | null; accepted?: string | null }

function shownRun(view: RunView | null): string | null {
  return view === null || view.state === "idle" ? null : view.run.id
}

function awaitsDecision(view: RunView | null, runId: string): boolean {
  return view?.state === "awaiting_decision" && view.run.id === runId
}

/** Powiadomienie tylko po zakończonym zapisie (RUN), widzianym na żywo; podgląd i zatrzymanie mają baner. */
function announce(event: RunEvent, before: RunView | null) {
  const view = event.view

  if (view.state !== "finished" || view.run.dry_run || view.result.ending !== "finished") {
    return
  }

  if (before === null || before.state === "idle") {
    return
  }

  if (before.run.id !== view.run.id || before.state === "finished") {
    return
  }

  toast.add({
    title: view.result.headline,
    description: `Okres ${view.run.period}`,
    type: view.result.result === "OK" ? "success" : "warning",
  })
}

/**
 * Jeden strumień Uruchomień na kartę, póki jest widoczna: każda strona widzi to samo bieżące Uruchomienie
 * procesu, a zamknięcie karty albo przejście do innej nie przerywa pracy na serwerze.
 */
export function RunsProvider({ children }: { children: React.ReactNode }) {
  const [view, setView] = React.useState<RunView | null>(null)
  const [disconnected, setDisconnected] = React.useState(false)
  const [draft, setDraft] = React.useState<RunDraft | null>(null)
  const [dismissed, setDismissed] = React.useState<string | null>(null)
  const latest = React.useRef<RunView | null>(null)
  // Tata klika dwa razy z przyzwyczajenia i stuka dwa razy w ekran dotykowy, a przycisk startu i okno decyzji
  // znikają dopiero, gdy strumień pokaże zmianę. Do tej pory powtórne kliknięcie niczego nie wysyła: drugi start
  // albo druga decyzja dostałyby odmowę serwera obok udanej pierwszej, a drugi podgląd bez zapisu mógłby się
  // nawet wykonać. Odmowa pierwszego kliknięcia (np. Uruchomienie z innej karty) pokazuje się jak dotąd.
  const pendingStart = React.useRef<PendingStart | null>(null)
  const pendingDecision = React.useRef<string | null>(null)
  const [starting, setStarting] = React.useState(false)
  const [deciding, setDeciding] = React.useState<string | null>(null)

  const settleStart = React.useCallback(() => {
    pendingStart.current = null
    setStarting(false)
  }, [])

  const settleDecision = React.useCallback(() => {
    pendingDecision.current = null
    setDeciding(null)
  }, [])

  React.useEffect(
    () =>
      watchRunEvents(
        (event) => {
          announce(event, latest.current)
          latest.current = event.view
          setView(event.view)

          // Po przyjęciu startu każde Uruchomienie inne niż sprzed startu to już nowe (albo jeszcze późniejsze).
          // `idle` znaczy wtedy, że serwer zgubił Uruchomienie (Centrum uruchomione ponownie, gdy karta była w tle):
          // serwer publikuje widok startu przed odpowiedzią i w jednym procesie nie wraca do `idle`.
          const start = pendingStart.current

          if (
            start?.accepted !== undefined &&
            (shownRun(event.view) !== start.before || event.view.state === "idle")
          ) {
            settleStart()
          }

          const decision = pendingDecision.current

          if (decision !== null && !awaitsDecision(event.view, decision)) {
            settleDecision()
          }
        },
        (connected) => setDisconnected(!connected)
      ),
    [settleStart, settleDecision]
  )

  const start = React.useCallback(
    (request: RunStart) => {
      if (pendingStart.current !== null) {
        return Promise.resolve(false)
      }

      const pending: PendingStart = { before: shownRun(latest.current) }

      pendingStart.current = pending
      setStarting(true)

      return ("period" in request ? startRun(request) : startIntermax()).then(
        (started) => {
          pending.accepted = shownRun(started)

          // Ostatni widok strumienia przyszedł przed tą odpowiedzią: `idle` to w nim zwykły stan świeżo
          // uruchomionego Centrum, a nie zgubione Uruchomienie, więc liczy się tylko przyjęte Uruchomienie.
          if (pending.accepted === null || shownRun(latest.current) === pending.accepted) {
            settleStart()
          }

          setDraft(null)

          return true
        },
        (failure: Error) => {
          settleStart()
          showFailure(failure)

          return false
        }
      )
    },
    [settleStart]
  )

  const value = React.useMemo<RunsContextValue>(
    () => ({
      view,
      disconnected,
      draft,
      setDraft,
      dismissed,
      newRun: setDismissed,
      starting,
      start,
      rerun: (run) => {
        if (run.pricing !== null && run.process !== "intermax") {
          setDraft({ process: run.process, period: run.period })

          return
        }

        start(rerunOf(run, run.dry_run))
      },
      deciding,
      decide: (runId, answer) => {
        if (pendingDecision.current !== null) {
          return
        }

        pendingDecision.current = runId
        setDeciding(runId)
        decideRun(runId, answer).then(
          () => {
            if (!awaitsDecision(latest.current, runId)) {
              settleDecision()
            }
          },
          (failure: Error) => {
            settleDecision()
            showFailure(failure)
          }
        )
      },
    }),
    [view, disconnected, draft, dismissed, starting, start, deciding, settleDecision]
  )

  return <RunsContext.Provider value={value}>{children}</RunsContext.Provider>
}

export function useRuns() {
  const context = React.useContext(RunsContext)

  if (context === null) {
    throw new Error("useRuns działa tylko wewnątrz RunsProvider.")
  }

  return context
}

/** Uruchomienie, które trwa albo czeka na Decyzję taty. */
export type ActiveRunView = Extract<RunView, { state: "running" | "awaiting_decision" }>

/** Uruchomienie trwa (także gdy czeka na decyzję taty). */
export function isActive(view: RunView | null): view is ActiveRunView {
  return view !== null && (view.state === "running" || view.state === "awaiting_decision")
}
