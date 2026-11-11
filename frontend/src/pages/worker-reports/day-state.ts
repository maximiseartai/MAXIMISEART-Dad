import type { ReportsDay, ReportsWorkerDay } from "@/api/generated"
import { addDays, weekdayIndex } from "@/pages/worker-reports/days"

/** Stan dnia, który tata wybiera filtrem Status: dzień z wynikiem ostatniego kliknięcia. */
export type Status = "problem" | "without_report" | "waiting" | "complete"

/**
 * Stan dnia Wykonawcy na Mapie cieplnej (#1319), jedyne miejsce, z którego UI wie, jak pokazać kafelek, popover,
 * linię Wykonawcy, pierścień i filtr Status:
 * - `problem`: dzień ma problem, którego tata nie zostawił „Zostaw moją”;
 * - `waiting` (Czeka): wczoraj albo dziś zlecenia bez raportu i żadnego maila od Wykonawcy, bo raport może jeszcze
 *   przyjść; starszy taki dzień to `without_report`;
 * - `without_report` (Bez raportu): zlecenia bez żadnego Wpisu;
 * - `complete` (Komplet): każde zlecenie ma Wpis;
 * - `future`: dzień po dziś z liczbą zleceń, bez stanu raportu;
 * - `holiday`, `sunday`, `empty`: dzień bez zleceń i problemów (także z samym mailem Wykonawcy, bo nie ma czego
 *   wpisać): święto, niedziela, zwykły dzień.
 */
export type DayState =
  | { kind: Status; day: ReportsWorkerDay }
  | { kind: "future"; orders: number }
  | { kind: "holiday" | "sunday" | "empty" }

/**
 * Stan dnia `column` Wykonawcy, którego dzień z odpowiedzi serwera to `found` (`undefined`: Wykonawca nie ma tego
 * dnia), przy dzisiejszym dniu `today` z zegara Centrum.
 */
export function dayState(found: ReportsWorkerDay | undefined, column: ReportsDay, today: string): DayState {
  if (found !== undefined && column.day > today && found.orders > 0) {
    return { kind: "future", orders: found.orders }
  }

  if (found !== undefined && column.day <= today && (found.orders > 0 || found.problems.length > 0)) {
    return { kind: status(found, column.day, today), day: found }
  }

  if (column.holiday !== null) {
    return { kind: "holiday" }
  }

  return { kind: weekdayIndex(column.day) === 6 ? "sunday" : "empty" }
}

function status(found: ReportsWorkerDay, day: string, today: string): Status {
  if (found.problems.length > 0) {
    return "problem"
  }

  if (found.without_report.length === 0) {
    return "complete"
  }

  const recent = day === today || day === addDays(today, -1)

  return recent && found.mails === 0 ? "waiting" : "without_report"
}

/** Stan z wynikiem kliknięcia, czyli dzień, który ma kafelek z popoverem. */
export function hasStatus(state: DayState): state is Extract<DayState, { kind: Status }> {
  return state.kind === "problem" || state.kind === "without_report" || state.kind === "waiting" || state.kind === "complete"
}
