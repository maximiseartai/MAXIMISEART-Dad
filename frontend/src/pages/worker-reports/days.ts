// Rachunek dni widoku Raporty (#1319): zakres dni, który tata ogląda na Mapie cieplnej, liczy przeglądarka z dni okna,
// które podaje serwer (`ReportsView.days`, od najstarszego). Dzień to zawsze `RRRR-MM-DD`, liczony w UTC, więc strefa
// komputera taty nie przesuwa dnia.

const DAY_MS = 24 * 60 * 60 * 1000

/** Zakres dni widoku: pierwszy i ostatni dzień, oba z listy dni okna, `from <= to`. */
export type DayRange = { from: string; to: string }

function utc(day: string): number {
  return Date.parse(`${day}T00:00:00Z`)
}

function isoOf(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10)
}

/** `2026-11-11`, `-1` → `2026-11-10` */
export function addDays(day: string, count: number): string {
  return isoOf(utc(day) + count * DAY_MS)
}

/** Dzień tygodnia od poniedziałku: `0` poniedziałek … `6` niedziela. */
export function weekdayIndex(day: string): number {
  return (new Date(utc(day)).getUTCDay() + 6) % 7
}

/** Dni okna w zakresie, od najstarszego: kolumny Mapy cieplnej. */
export function daysIn(days: ReadonlyArray<string>, range: DayRange): ReadonlyArray<string> {
  return days.filter((day) => day >= range.from && day <= range.to)
}

/**
 * Domyślny zakres: poniedziałek poprzedniego tygodnia do niedzieli bieżącego (dwa tygodnie wokół `today`), przycięty
 * do dni okna. Okno ma zawsze dziś, więc zakres nigdy nie jest pusty.
 */
export function defaultRange(days: ReadonlyArray<string>, today: string): DayRange {
  const from = addDays(today, -weekdayIndex(today) - 7)

  return edges(daysIn(days, { from, to: addDays(from, 13) })) ?? { from: today, to: today }
}

/**
 * Zakres z adresu `#/raporty/<od>/<do>` (sam `<dzień>`: ten jeden dzień), przycięty do dni okna; adres bez zakresu,
 * z zakresem poza oknem albo nie do odczytania daje zakres domyślny.
 */
export function rangeFromPath(path: ReadonlyArray<string>, days: ReadonlyArray<string>, today: string): DayRange {
  const [from, to = from] = path

  if (from === undefined || to === undefined || !isDay(from) || !isDay(to) || from > to) {
    return defaultRange(days, today)
  }

  return edges(daysIn(days, { from, to })) ?? defaultRange(days, today)
}

/** Czy strzałka w stronę `direction` ma jeszcze dni okna przed sobą. */
export function canShift(days: ReadonlyArray<string>, range: DayRange, direction: -1 | 1): boolean {
  return direction === -1 ? days[0] !== range.from : days.at(-1) !== range.to
}

/** Strzałka zakresu: tyle samo dni okna wcześniej (`-1`) albo później (`1`), zatrzymane na krańcu okna. */
export function shifted(days: ReadonlyArray<string>, range: DayRange, direction: -1 | 1): DayRange {
  const first = days.indexOf(range.from)
  const last = days.indexOf(range.to)
  const length = last - first + 1

  const start =
    direction === -1 ? Math.max(0, first - length) : Math.max(0, Math.min(days.length - 1, last + length) - length + 1)

  return edges(days.slice(start, start + length)) ?? range
}

/** Zakres od `one` do `other` (dni okna, w dowolnej kolejności), przycięty do dni okna. */
export function rangeOf(days: ReadonlyArray<string>, one: string, other: string): DayRange {
  const [from, to] = one < other ? [one, other] : [other, one]

  return edges(daysIn(days, { from, to })) ?? { from, to }
}

function edges(days: ReadonlyArray<string>): DayRange | null {
  const [from] = days
  const to = days.at(-1)

  return from === undefined || to === undefined ? null : { from, to }
}

function isDay(part: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(part) && !Number.isNaN(utc(part))
}

const MONTHS = ["sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź", "lis", "gru"]

const WEEKDAYS = ["pn", "wt", "śr", "cz", "pt", "sb", "nd"]

function dayOfMonth(day: string): number {
  return Number(day.slice(8, 10))
}

function month(day: string): string {
  return MONTHS[Number(day.slice(5, 7)) - 1] ?? ""
}

function weekday(day: string): string {
  return WEEKDAYS[weekdayIndex(day)] ?? ""
}

/** Napis zakresu: `2–15 lis`, `28 paź – 3 lis`, jeden dzień `11 lis`. */
export function rangeLabel(from: string, to: string): string {
  if (from === to) {
    return `${dayOfMonth(from)} ${month(from)}`
  }

  if (from.slice(0, 7) === to.slice(0, 7)) {
    return `${dayOfMonth(from)}–${dayOfMonth(to)} ${month(to)}`
  }

  return `${dayOfMonth(from)} ${month(from)} – ${dayOfMonth(to)} ${month(to)}`
}

/** Nagłówek kolumny dnia: numer dnia miesiąca i skrót dnia tygodnia (`11`, `śr`). */
export function columnLabel(day: string) {
  return { number: dayOfMonth(day), weekday: weekday(day) }
}

/** Skrót dnia tygodnia dnia kalendarza (lokalnej daty): `pn` … `nd`. */
export function weekdayOfDate(date: Date): string {
  return WEEKDAYS[(date.getDay() + 6) % 7] ?? ""
}

/** `2026-11-05` → `cz. 05.11` */
export function shortDay(day: string): string {
  return `${weekday(day)}. ${day.slice(8, 10)}.${day.slice(5, 7)}`
}
