import * as React from "react"

import { failureMessage } from "@/api/client"
import { getHealth, getToolUpdate, startToolUpdate, type ToolUpdate } from "@/api/centrum"
import { toast } from "@/components/ui/toast"
import { useAction } from "@/lib/action"

const POLL_MS = 500

const RELOADED_AFTER_UPDATE = "centrum-po-aktualizacji"

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

/**
 * Stan Aktualizacji narzędzia i nieudany odczyt razem: każdy stan, który serwer podał później (start, krok w trakcie,
 * odczyt), zastępuje nieudany odczyt, bo inaczej rada „Centrum nie odpowiada” zasłoniłaby Komunikat porażki Aktualizacji.
 */
type Shown = Pick<ToolUpdateContextValue, "update" | "readFailure">

const ToolUpdateContext = React.createContext<ToolUpdateContextValue | null>(null)

/**
 * Jedna Aktualizacja narzędzia na Centrum, wspólna dla każdego miejsca z przyciskiem `Zaktualizuj narzędzie`.
 * Serwer odpowiada od razu pierwszym krokiem i aktualizuje w tle, a karta odczytuje krok, aż przyjdzie wynik.
 * Po udanej aktualizacji Centrum startuje od nowa: karta czeka, aż odpowie Centrum o innym identyfikatorze
 * startu niż przed kliknięciem, przeładowuje stronę i krótko pokazuje „Zaktualizowano” z commitem, w którym
 * działa nowe Centrum.
 */
export function ToolUpdateProvider({ children }: { children: React.ReactNode }) {
  const [{ update, readFailure }, setShown] = React.useState<Shown>({ update: null, readFailure: null })
  const [clicked, setClicked] = React.useState(false)
  // Identyfikator startu Centrum sprzed kliknięcia (`health`); inny znaczy, że działa już nowe Centrum.
  const instance = React.useRef<string | null>(null)
  const running = update?.state === "running"
  const restarted = update?.state === "failed" && update.after_restart && !clicked

  const show = React.useCallback((result: ToolUpdate) => setShown({ update: result, readFailure: null }), [])

  const failRead = React.useCallback(
    (failure: Error) => setShown((shown) => ({ ...shown, readFailure: failureMessage(failure) })),
    []
  )

  const read = React.useCallback(() => {
    getToolUpdate().then(show, failRead)
  }, [show, failRead])

  // Porażkę ponownego startu widać na każdej stronie (`ToolUpdateAfterRestart`), więc stan aktualizacji karta czyta
  // przy każdym wejściu.
  React.useEffect(() => {
    const reloaded = sessionStorage.getItem(RELOADED_AFTER_UPDATE) !== null

    sessionStorage.removeItem(RELOADED_AFTER_UPDATE)
    Promise.all([getToolUpdate(), reloaded ? getHealth() : null]).then(([result, health]) => {
      show(result)

      if (health !== null && result.state === "updated") {
        const version = health.commit === null ? "nowej wersji" : `wersji ${health.commit}`
        toast.add({ title: "Zaktualizowano", description: `Centrum działa w ${version}.` })
      }
    }, failRead)
  }, [show, failRead])

  // Centrum nie odpowiada w trakcie aktualizacji tylko wtedy, gdy zamknęło się przed ponownym startem: karta pokazuje
  // ten krok.
  React.useEffect(() => {
    if (update?.state !== "running") {
      return
    }

    const timer = window.setTimeout(() => {
      getHealth()
        .then((health) => {
          instance.current ??= health.instance

          if (health.instance !== instance.current) {
            sessionStorage.setItem(RELOADED_AFTER_UPDATE, "1")
            window.location.reload()

            return
          }

          return getToolUpdate().then(show)
        })
        .catch(() => show({ state: "running", step: "restarting" }))
    }, POLL_MS)

    return () => window.clearTimeout(timer)
  }, [update, show])

  const starting = useAction(() => {
    setClicked(true)

    return getHealth()
      .then((health) => {
        instance.current = health.instance

        return startToolUpdate()
      })
      .then(show)
  }, "Nie zaktualizowano narzędzia")

  const run = starting.run
  const start = React.useCallback(() => void run(), [run])
  const busy = starting.running !== null || running

  const value = React.useMemo<ToolUpdateContextValue>(
    () => ({ update, readFailure, busy, restarted, start, read }),
    [update, readFailure, busy, restarted, start, read]
  )

  return <ToolUpdateContext.Provider value={value}>{children}</ToolUpdateContext.Provider>
}

export function useToolUpdate() {
  const context = React.useContext(ToolUpdateContext)

  if (context === null) {
    throw new Error("useToolUpdate działa tylko wewnątrz ToolUpdateProvider.")
  }

  return context
}
