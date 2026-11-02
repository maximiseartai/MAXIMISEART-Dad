import type { Process, ProcessRun } from "@/api/centrum"
import { isFailure } from "@/components/run-result-badge"
import type { FilterOption } from "@/components/segmented-filter"

export type Mode = ProcessRun["mode"]

export const PROCESS_OPTIONS: ReadonlyArray<FilterOption<Process>> = [
  { value: "preparation", label: "Przygotowanie" },
  { value: "settlement", label: "Przebieg" },
  { value: "efenix", label: "efenix" },
  { value: "intermax", label: "INTERMAX" },
]

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

/** Słowo przerwanego: `błąd` przy Zatrzymaniu „do Maksa”, `zatrzymano` przy każdym innym, także bez rodzaju. */
export function stopWord(run: ProcessRun): string {
  return isFailure(run) ? "błąd" : "zatrzymano"
}
