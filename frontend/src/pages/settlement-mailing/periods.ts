import type { MailingPeriod, MailingRow } from "@/api/generated"

export type ShownState = MailingRow["state"] | { state: "sending" }

/**
 * Miejsce stanu w liczniku okresu „X z Y wysłane”: `done` liczy się do X i Y, `open` tylko do Y, a `aside` stoi poza
 * licznikiem, bo taki plik nie ma maila (bez adresu, bez zleceń, spoza Listy). Zmienione po wysłaniu jest `open`: czeka
 * na ponowną wysyłkę, więc okres z nim nie jest skończony.
 */
const PLACE = {
  to_send: "open",
  not_sent: "open",
  changed: "open",
  sending: "open",
  unknown: "open",
  sent: "done",
  sent_by_hand: "done",
  no_address: "aside",
  without_orders: "aside",
  not_listed: "aside",
} as const satisfies Record<ShownState["state"], "done" | "open" | "aside">

export function counted(state: ShownState): boolean {
  return PLACE[state.state] !== "aside"
}

export function delivered(state: ShownState): boolean {
  return PLACE[state.state] === "done"
}

export type Tally = { sent: number; of: number }

export function tally(states: ReadonlyArray<ShownState>): Tally {
  const mailed = states.filter(counted)

  return { sent: mailed.filter(delivered).length, of: mailed.length }
}

export function lastSent(states: ReadonlyArray<ShownState>): string | null {
  const moments = states.flatMap((state) => (state.state === "sent" || state.state === "sent_by_hand" ? [state.at] : []))

  return moments.reduce<string | null>((latest, at) => (latest === null || Date.parse(at) > Date.parse(latest) ? at : latest), null)
}

/**
 * Co okres pokazuje na osi: `send` pełną kartę z Wykonawcami (ma plik, który jeszcze nie poszedł albo nie wyszedł),
 * `fix` pytanie o poprawione rozliczenie (do wysłania są tylko pliki zmienione po wysłaniu), `settled` jeden wiersz.
 * Bez czytelnych „Wysłanych” nic nie da się wysłać, więc każdy okres to jeden wiersz.
 */
export type PeriodKind = "send" | "fix" | "settled"

export function periodKind(period: MailingPeriod, readable: boolean): PeriodKind {
  if (!readable) {
    return "settled"
  }

  if (period.rows.some((row) => row.sendable && !row.resend)) {
    return "send"
  }

  return period.rows.some((row) => row.sendable) ? "fix" : "settled"
}

export function waiting(period: MailingPeriod, readable: boolean): boolean {
  return !readable || periodKind(period, readable) !== "settled"
}
