import type { Process } from "@/api/centrum"
import type { Metrics, ProcessRun } from "@/api/generated"
import type { FilterOption } from "@/components/segmented-filter"

export type Mode = ProcessRun["mode"]

/** Filtr procesu: procesy z serwera, w jego kolejności. */
export function processOptions(processes: Metrics["processes"]): Array<FilterOption<Process>> {
  return processes.map(({ process, label }) => ({ value: process, label }))
}

export const MODE_OPTIONS: ReadonlyArray<FilterOption<Mode>> = [
  { value: "RUN", label: "RUN" },
  { value: "DRY-RUN", label: "DRY-RUN" },
]

/** Etapy, które w tych Uruchomieniach procesu trwały (np. DRY-RUN nie ma Zapisywania). */
export function measuredPhases(phases: ReadonlyArray<string>, runs: ReadonlyArray<ProcessRun>): string[] {
  return phases.filter((phase) =>
    runs.some((run) => run.phase_durations.some((entry) => entry.phase === phase && entry.duration_ms > 0))
  )
}

export function phaseDuration(run: ProcessRun, phase: string): number {
  return run.phase_durations.find((entry) => entry.phase === phase)?.duration_ms ?? 0
}

/** Uruchomienie zatrzymane (przerwane): w metrykach ma wynik `BLAD_KRYTYCZNY`, z czasami etapów do zatrzymania. */
export function isStopped(run: ProcessRun): boolean {
  return run.result === "BLAD_KRYTYCZNY"
}
