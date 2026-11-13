import * as React from "react"

import { decideRun, startIntermax, startReportEntering, startRun, watchRunEvents, type RunView } from "@/api/centrum"
import type { DecisionAnswer, RunEvent, RunInfo, RunMode, RunRequest } from "@/api/generated"
import { toast } from "@/components/ui/toast"
import { useAction } from "@/lib/action"

/** Okres i proces wybrane w innym miejscu (np. w Tablicy okresów) do formularza nowego Uruchomienia. */
export type RunDraft = Pick<RunRequest, "process" | "period">

/** Proces bez okresu, który bierze tylko Ustawienia Centrum i startuje własną operacją kontraktu. */
type ProcessWithoutPeriod = "intermax" | "report_entering"

/** Start Uruchomienia: proces z okresem albo proces bez okresu (Uporządkowanie INTERMAX, Wpisanie raportów). */
export type RunStart = RunRequest | { process: ProcessWithoutPeriod }

export function rerunOf(run: RunInfo, mode: RunMode): RunStart {
  switch (run.process) {
    case "intermax":
    case "report_entering":
      return { process: run.process }
    default:
      return { process: run.process, period: run.period, mode }
  }
}

function startWithoutPeriod(process: ProcessWithoutPeriod) {
  return process === "intermax" ? startIntermax() : startReportEntering()
}

type RunsContextValue = {
  /** Bieżące Uruchomienie procesu ze strumienia; `null`, dopóki nie przyjdzie pierwszy widok. */
  view: RunView | null
  /** Połączenie ze strumieniem zerwane; przeglądarka łączy się ponownie sama. */
  disconnected: boolean
  /** Ostatniego zdarzenia strumienia nie dało się odczytać (np. karta ze starszą wersją Centrum), więc widok stoi. */
  unreadable: boolean
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

type Awaited = { shows: (view: RunView) => boolean; resolve: () => void }

function shownRun(view: RunView | null): string | null {
  return view === null || view.state === "idle" ? null : view.run.id
}

function awaitsDecision(view: RunView | null, runId: string): boolean {
  return view?.state === "awaiting_decision" && view.run.id === runId
}

/** Powiadomienie tylko po zakończonym zapisie (RUN), widzianym na żywo; podgląd i zatrzymanie mają baner. */
function announce(event: RunEvent, before: RunView | null) {
  const view = event.view

  if (view.state !== "finished" || view.run.mode === "DRY-RUN" || view.result.ending !== "finished") {
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
  const [unreadable, setUnreadable] = React.useState(false)
  const latest = React.useRef<RunView | null>(null)
  const awaited = React.useRef(new Set<Awaited>())

  const streamShows = React.useCallback(
    (shows: (view: RunView) => boolean) =>
      new Promise<void>((resolve) => {
        awaited.current.add({ shows, resolve })
      }),
    []
  )

  React.useEffect(
    () =>
      watchRunEvents(
        (event) => {
          announce(event, latest.current)
          latest.current = event.view
          setView(event.view)
          setUnreadable(false)

          for (const waiting of awaited.current) {
            if (waiting.shows(event.view)) {
              awaited.current.delete(waiting)
              waiting.resolve()
            }
          }
        },
        (connected) => setDisconnected(!connected),
        () => setUnreadable(true)
      ),
    []
  )

  // Przycisk startu i okno decyzji znikają dopiero, gdy strumień pokaże zmianę, więc start i decyzja trwają do tej
  // chwili: drugi start albo druga decyzja dostałyby odmowę serwera obok udanej pierwszej, a drugi podgląd bez
  // zapisu mógłby się nawet wykonać. Odmowa pierwszego kliknięcia (np. Uruchomienie z innej karty) pokazuje się jak dotąd.
  const starting = useAction(async (request: RunStart) => {
    const before = shownRun(latest.current)
    const accepted = shownRun(await ("period" in request ? startRun(request) : startWithoutPeriod(request.process)))

    setDraft(null)

    // Ostatni widok strumienia przyszedł przed odpowiedzią: `idle` to w nim zwykły stan świeżo uruchomionego
    // Centrum, a nie zgubione Uruchomienie, więc liczy się tylko przyjęte Uruchomienie.
    if (accepted === null || shownRun(latest.current) === accepted) {
      return
    }

    // Po przyjęciu startu każde Uruchomienie inne niż sprzed startu to już nowe (albo jeszcze późniejsze).
    // `idle` znaczy wtedy, że serwer zgubił Uruchomienie (Centrum uruchomione ponownie, gdy karta była w tle):
    // serwer publikuje widok startu przed odpowiedzią i w jednym procesie nie wraca do `idle`.
    await streamShows((next) => shownRun(next) !== before || next.state === "idle")
  })

  const deciding = useAction(async (runId: string, answer: DecisionAnswer["answer"]) => {
    await decideRun(runId, answer)

    if (awaitsDecision(latest.current, runId)) {
      await streamShows((next) => !awaitsDecision(next, runId))
    }
  })

  const startRunning = starting.run

  const start = React.useCallback(
    (request: RunStart) => startRunning(request).then((outcome) => outcome === "done"),
    [startRunning]
  )

  const decide = deciding.run

  const value = React.useMemo<RunsContextValue>(
    () => ({
      view,
      disconnected,
      unreadable,
      draft,
      setDraft,
      dismissed,
      newRun: setDismissed,
      starting: starting.running !== null,
      start,
      rerun: (run) => {
        if (run.pricing !== null && run.process !== "intermax" && run.process !== "report_entering") {
          setDraft({ process: run.process, period: run.period })

          return
        }

        start(rerunOf(run, run.mode))
      },
      deciding: deciding.running?.[0] ?? null,
      decide: (runId, answer) => void decide(runId, answer),
    }),
    [view, disconnected, unreadable, draft, dismissed, starting.running, start, deciding.running, decide]
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

export type ActiveRunView = Extract<RunView, { state: "running" | "awaiting_decision" }>

/** Uruchomienie procesu bez okresu `process` z widoku strumienia, trwające albo zakończone w tej pracy Centrum; inaczej `null`. */
export function runOf(view: RunView | null, process: ProcessWithoutPeriod): Exclude<RunView, { state: "idle" }> | null {
  return view === null || view.state === "idle" || view.run.process !== process ? null : view
}

export function isActive(view: RunView | null): view is ActiveRunView {
  return view !== null && (view.state === "running" || view.state === "awaiting_decision")
}
