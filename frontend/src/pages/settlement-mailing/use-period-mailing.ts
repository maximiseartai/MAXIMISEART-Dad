import * as React from "react"

import { sendSettlementMail } from "@/api/centrum"
import type { MailingPeriod, MailingRow } from "@/api/generated"
import { useAction } from "@/lib/action"
import type { ShownState } from "@/pages/settlement-mailing/periods"

type Visit = {
  shown: Readonly<Record<string, ShownState>>
  sent: ReadonlySet<string>
  failed: ReadonlySet<string>
  round: { at: number; of: number; failed: boolean } | null
  glows: number
}

type Step =
  | { kind: "start"; of: number }
  | { kind: "sending"; worker: string; at: number }
  | { kind: "answer"; worker: string; state: ShownState; sentNow: boolean }
  | { kind: "end" }
  | { kind: "read" }

const NOTHING_YET: Visit = { shown: {}, sent: new Set(), failed: new Set(), round: null, glows: 0 }

function next(visit: Visit, step: Step): Visit {
  switch (step.kind) {
    case "start":
      return { ...visit, round: { at: 0, of: step.of, failed: false } }
    case "sending":
      return {
        ...visit,
        shown: { ...visit.shown, [step.worker]: { state: "sending" } },
        round: visit.round === null ? null : { ...visit.round, at: step.at },
      }
    case "answer": {
      const failed = step.state.state === "not_sent"

      return {
        ...visit,
        shown: { ...visit.shown, [step.worker]: step.state },
        sent: step.sentNow ? plus(visit.sent, step.worker) : visit.sent,
        failed: failed ? plus(visit.failed, step.worker) : minus(visit.failed, step.worker),
        round: visit.round === null ? null : { ...visit.round, failed: visit.round.failed || failed },
      }
    }

    case "end":
      return { ...visit, round: null, glows: visit.round === null || visit.round.failed ? visit.glows : visit.glows + 1 }
    case "read":
      return { ...visit, shown: {} }
    default: {
      const unhandled: never = step

      return unhandled
    }
  }
}

function plus(set: ReadonlySet<string>, worker: string): ReadonlySet<string> {
  return new Set([...set, worker])
}

function minus(set: ReadonlySet<string>, worker: string): ReadonlySet<string> {
  return new Set([...set].filter((found) => found !== worker))
}

/**
 * Wysyłka maili okresu po kolei, jedno zapytanie na mail: częściowa porażka nie psuje reszty, a podwójne kliknięcie
 * odrzuca serwer, który zna „Wysłane”. Po ostatnim mailu strona czyta się od nowa; nowy odczyt zna już stan po
 * wysyłce, więc stany z odpowiedzi ustępują mu, gdy nic nie wychodzi. Zapytanie, które nie doszło do Centrum, kończy
 * wysyłkę powiadomieniem o porażce.
 */
export function usePeriodMailing(period: MailingPeriod, reload: () => Promise<void>) {
  const [visit, step] = React.useReducer(next, NOTHING_YET)
  const [shownFor, setShownFor] = React.useState(period)

  const { running, run } = useAction(async (workers: ReadonlyArray<string>) => {
    step({ kind: "start", of: workers.length })

    try {
      await mailEach(period, workers, step)
    } finally {
      step({ kind: "end" })
    }

    await reload()
  }, "Nie udało się wysłać rozliczenia")

  const busy = running !== null

  if (shownFor !== period && !busy) {
    setShownFor(period)
    step({ kind: "read" })
  }

  const state = (row: MailingRow): ShownState => visit.shown[row.worker] ?? row.state

  return { visit, busy, state, send: run }
}

export type PeriodMailing = ReturnType<typeof usePeriodMailing>

async function mailEach(period: MailingPeriod, workers: ReadonlyArray<string>, step: (step: Step) => void) {
  for (const [at, worker] of workers.entries()) {
    const row = period.rows.find((found) => found.worker === worker)

    if (row === undefined) {
      continue
    }

    step({ kind: "sending", worker, at })

    try {
      const result = await sendSettlementMail(period.token, worker, row.resend)

      step({ kind: "answer", worker, state: result.row.state, sentNow: result.sent_now })
    } catch (failure) {
      step({ kind: "answer", worker, state: row.state, sentNow: false })

      throw failure
    }
  }
}
