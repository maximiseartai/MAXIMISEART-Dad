// Prezentacja dat i czasów z kontraktu w zapisie taty. Bez arytmetyki dat: okresy liczy serwer, zakres dni Raportów
// `pages/worker-reports/days.ts`; jedyny rachunek tutaj to odległość chwili od zegara karty w `ago`.

/** `2026-10-06` → `06.10.2026` */
export function fullDate(isoDate: string): string {
  const [year, month, day] = isoDate.split("-")

  return `${day}.${month}.${year}`
}

/** `2026-10-06` → `06.10` */
export function shortDate(isoDate: string): string {
  return fullDate(isoDate).slice(0, 5)
}

const DATE_TIME = new Intl.DateTimeFormat("pl-PL", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
})

/** `2026-10-06T06:21:00Z` → `06.10.2026, 08:21` (czas komputera taty) */
export function dateTime(isoDateTime: string): string {
  return DATE_TIME.format(new Date(isoDateTime))
}

const HOUR_MINUTE = new Intl.DateTimeFormat("pl-PL", { hour: "2-digit", minute: "2-digit" })

/** `2026-10-06T06:21:00Z` → `08:21` (czas komputera taty) */
export function hourMinute(isoDateTime: string): string {
  return HOUR_MINUTE.format(new Date(isoDateTime))
}

/** `2026-10-06T06:21:00Z` → `06.10` (dzień według czasu komputera taty) */
export function dayMonth(isoDateTime: string): string {
  return dateTime(isoDateTime).slice(0, 5)
}

const SECONDS = new Intl.NumberFormat("pl-PL", { minimumFractionDigits: 1, maximumFractionDigits: 1 })

/** `10900` ms → `10,9 s` */
export function seconds(durationMs: number): string {
  // Zaokrąglenie na całych dziesiątych częściach sekundy, w górę od połowy (7250 ms → 7,3 s).
  return `${SECONDS.format(Math.round(durationMs / 100) / 10)} s`
}

const RELATIVE = new Intl.RelativeTimeFormat("pl-PL", { numeric: "auto" })

const MINUTE_MS = 60_000

const HOUR_MS = 60 * MINUTE_MS

const DAY_MS = 24 * HOUR_MS

/** `2026-10-20T09:15:00Z` → `przed chwilą`, `12 minut temu`, `2 godziny temu`, `wczoraj`, `16 dni temu` */
export function ago(isoDateTime: string, now: number = Date.now()): string {
  const past = now - new Date(isoDateTime).getTime()

  if (past < MINUTE_MS) {
    return "przed chwilą"
  }

  if (past < HOUR_MS) {
    return RELATIVE.format(-Math.round(past / MINUTE_MS), "minute")
  }

  if (past < DAY_MS) {
    return RELATIVE.format(-Math.round(past / HOUR_MS), "hour")
  }

  return RELATIVE.format(-Math.round(past / DAY_MS), "day")
}

const PLURAL = new Intl.PluralRules("pl-PL")

/** Forma rzeczownika przy liczbie: `plural(1, …)` → `one`, 2–4 i 22–24 → `few`, 0, 5–21 i 25 → `many`. */
export function plural(count: number, forms: { one: string; few: string; many: string }): string {
  const rule = PLURAL.select(count)

  return rule === "one" || rule === "few" ? forms[rule] : forms.many
}
