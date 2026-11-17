import { createAsyncLogic, setup, types } from "xstate"

import { failureMessage } from "@/api/client"
import { getHealth, getToolUpdate, startToolUpdate, type ToolUpdate } from "@/api/centrum"
import { toast } from "@/components/ui/toast"
import { showFailure } from "@/lib/action"

const RELOADED_AFTER_UPDATE = "centrum-po-aktualizacji"

// Odczyty kontraktu odrzucają tylko błędem (`CentrumError` albo błąd `fetch`), jak `.then(…, (failure: Error) => …)`
// w reszcie karty.
const schemas = { error: types<Error>() }

type Context = {
  /** Aktualizacja narzędzia według serwera; `null`, dopóki nikt jej nie odczytał. */
  update: ToolUpdate | null
  /** Komunikat ostatniego nieudanego odczytu; każdy stan, który serwer podał później, go zastępuje. */
  readFailure: string | null
  /** Tata kliknął `Zaktualizuj narzędzie` od wejścia na stronę. */
  clicked: boolean
  /** Identyfikator startu Centrum sprzed aktualizacji (`health`); inny znaczy, że działa już nowe Centrum. */
  instance: string | null
}

/** Odczyt przy wejściu: stan aktualizacji i, gdy kartę przeładowała udana aktualizacja, commit nowego Centrum. */
const enter = createAsyncLogic({
  schemas,
  run: async () => {
    const reloaded = sessionStorage.getItem(RELOADED_AFTER_UPDATE) !== null

    sessionStorage.removeItem(RELOADED_AFTER_UPDATE)

    const [update, health] = await Promise.all([getToolUpdate(), reloaded ? getHealth() : null])

    return { update, reloadedInto: health }
  },
})

const read = createAsyncLogic({ schemas, run: () => getToolUpdate() })

const start = createAsyncLogic({
  schemas,
  run: async () => {
    const { instance } = await getHealth()

    return { instance, update: await startToolUpdate() }
  },
})

/**
 * Jedno pytanie w trakcie aktualizacji. Centrum o innym `instance` niż przed kliknięciem to już nowa wersja.
 * Centrum, które nie odpowiada, zamknęło się przed ponownym startem: to jest krok `restarting`, którego serwer sam
 * podać nie może.
 */
const poll = createAsyncLogic({
  schemas,
  run: async ({ input }: { input: { instance: string | null } }) => {
    const health = await getHealth()

    if (input.instance !== null && health.instance !== input.instance) {
      return { restarted: true } as const
    }

    return { restarted: false, instance: health.instance, update: await getToolUpdate() } as const
  },
})

const RESTARTING: ToolUpdate = { state: "running", step: "restarting" }

/**
 * Jedna Aktualizacja narzędzia na Centrum. Serwer odpowiada na start od razu pierwszym krokiem i aktualizuje w tle,
 * a karta pyta o krok, aż przyjdzie wynik. Po udanej aktualizacji Centrum startuje od nowa: karta czeka, aż odpowie
 * Centrum o innym identyfikatorze startu niż przed kliknięciem, i przeładowuje stronę, która krótko pokazuje
 * „Zaktualizowano” z commitem nowego Centrum.
 */
export const toolUpdateMachine = setup({
  schemas: {
    context: types<Context>(),
    events: { start: types<object>(), read: types<object>() },
  },
  actors: { enter, read, start, poll },
  actions: {
    announceUpdated: (commit: string | null) => {
      const version = commit === null ? "nowej wersji" : `wersji ${commit}`

      toast.add({ title: "Zaktualizowano", description: `Centrum działa w ${version}.` })
    },
    showStartFailure: (failure: Error) => showFailure(failure, "Nie zaktualizowano narzędzia"),
    reloadIntoNewCentrum: () => {
      sessionStorage.setItem(RELOADED_AFTER_UPDATE, "1")
      window.location.reload()
    },
  },
  delays: { poll: 500 },
}).createMachine({
  id: "toolUpdate",
  context: { update: null, readFailure: null, clicked: false, instance: null },
  initial: "entering",
  states: {
    // Porażkę ponownego startu widać na każdej stronie (`ToolUpdateAfterRestart`), więc stan karta czyta przy
    // każdym wejściu.
    entering: {
      invoke: {
        src: "enter",
        onDone: ({ event, actions }, enq) => {
          const { update, reloadedInto } = event.output

          if (reloadedInto !== null && update.state === "updated") {
            enq(actions.announceUpdated, reloadedInto.commit)
          }

          return { target: "settled", context: { update, readFailure: null } }
        },
        onError: ({ event }) => ({ target: "idle", context: { readFailure: failureMessage(event.error) } }),
      },
      on: { start: { target: "starting" } },
    },
    idle: {
      on: { start: { target: "starting" }, read: { target: "reading" } },
    },
    // Jeden odczyt naraz: kolejne `read` z każdego miejsca z przyciskiem należą do tego samego odczytu.
    reading: {
      invoke: {
        src: "read",
        onDone: ({ event }) => ({ target: "settled", context: { update: event.output, readFailure: null } }),
        onError: ({ event }) => ({ target: "idle", context: { readFailure: failureMessage(event.error) } }),
      },
      // Start przerywa odczyt, więc starszy stan nie nadpisze stanu ze startu.
      on: { start: { target: "starting" } },
    },
    // Dopóki start trwa, kolejne kliknięcie niczego nie wysyła (tata klika dwa razy z przyzwyczajenia).
    starting: {
      entry: () => ({ context: { clicked: true } }),
      invoke: {
        src: "start",
        onDone: ({ event }) => ({
          target: "settled",
          context: { update: event.output.update, instance: event.output.instance, readFailure: null },
        }),
        onError: ({ event, actions }, enq) => {
          enq(actions.showStartFailure, event.error)

          return { target: "idle" }
        },
      },
    },
    settled: {
      type: "choice",
      choice: ({ context }) => (context.update?.state === "running" ? { target: "polling" } : { target: "idle" }),
    },
    // Aktualizacja trwa: każdy przycisk aktualizacji jest wyłączony, a karta pyta o krok co `poll`.
    polling: {
      initial: "waiting",
      states: {
        waiting: { after: { poll: { target: "asking" } } },
        asking: {
          invoke: {
            src: "poll",
            input: ({ context }) => ({ instance: context.instance }),
            onDone: ({ event }) => {
              if (event.output.restarted) {
                return { target: "#toolUpdate.reloading" }
              }

              return {
                target: "#toolUpdate.settled",
                context: { update: event.output.update, instance: event.output.instance, readFailure: null },
              }
            },
            onError: () => ({ target: "waiting", context: { update: RESTARTING, readFailure: null } }),
          },
        },
      },
    },
    reloading: {
      entry: ({ actions }, enq) => enq(actions.reloadIntoNewCentrum),
    },
  },
})
