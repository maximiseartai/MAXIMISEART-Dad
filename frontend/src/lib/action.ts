import * as React from "react"

import { failureMessage } from "@/api/client"
import { toast } from "@/components/ui/toast"

/** Odmowa albo awaria akcji jako powiadomienie z Komunikatem serwera. */
export function showFailure(failure: Error, title = "Nie udało się") {
  toast.add({ title, description: failureMessage(failure), type: "error" })
}

/** Koniec `run`: akcja się udała, zawiodła (powiadomienie już stoi) albo nic nie wysłała, bo poprzednia jeszcze trwa. */
export type ActionOutcome = "done" | "failed" | "ignored"

/**
 * Akcja taty z serwerem. Tata klika dwa razy z przyzwyczajenia i stuka dwa razy w ekran dotykowy, a odpowiedź
 * przychodzi po chwili: dopóki `act` trwa, kolejne `run` niczego nie wysyła. Akcja, której skutek widać później
 * (np. w strumieniu Uruchomień), kończy `act` dopiero wtedy. Porażka to powiadomienie z tytułem `failureTitle`.
 * `running` to argumenty trwającej akcji, np. który plik wybiera okno wyboru.
 */
export function useAction<Args extends ReadonlyArray<unknown>>(
  act: (...args: Args) => Promise<void>,
  failureTitle?: string
) {
  const latestAct = React.useRef(act)
  const inFlight = React.useRef(false)
  const [running, setRunning] = React.useState<Args | null>(null)

  React.useEffect(() => {
    latestAct.current = act
  })

  const run = React.useCallback(
    (...args: Args): Promise<ActionOutcome> => {
      if (inFlight.current) {
        return Promise.resolve("ignored")
      }

      inFlight.current = true
      setRunning(args)

      return latestAct.current(...args)
        .then(
          (): ActionOutcome => "done",
          (failure: Error): ActionOutcome => {
            showFailure(failure, failureTitle)

            return "failed"
          }
        )
        .finally(() => {
          inFlight.current = false
          setRunning(null)
        })
    },
    [failureTitle]
  )

  return { running, run }
}
