import { cn } from "cn"
import { EyeIcon } from "lucide-react"

import type { PinnableRun } from "@/api/generated"
import { LoadFailure } from "@/components/load-failure"
import { RunResultBadge } from "@/components/run-result-badge"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import { Skeleton } from "@/components/ui/skeleton"
import { dateTime } from "@/lib/format"
import type { Resource } from "@/lib/use-resource"

const SKELETON_ROWS = 3

const NOT_IN_HISTORY = "Tego Uruchomienia nie ma w historii Centrum."

const ROW = "flex items-center gap-3 border-b px-3 py-2 text-sm last:border-b-0"

// Najwyżej cztery i pół wiersza: połowa wiersza mówi, że lista przewija się dalej. Na niskim ekranie lista oddaje
// wysokość aż do jednego wiersza, żeby „Wyślij” został na ekranie.
const LIST_HEIGHT = "max-h-63 min-h-14"

/**
 * Uruchomienia do przypięcia Uwagi. Gdy Uruchomienia, z którego tata otworzył okno (`openedFrom`), nie ma w liście
 * (jego metryki się nie zapisały), zdanie nad listą mówi, dlaczego nic nie jest zaznaczone. Zależy od `openedFrom`, nie
 * od zaznaczenia, żeby lista nie podskoczyła pod kursorem, gdy tata wybierze inne.
 */
export function DadNoteRuns({
  runs,
  reload,
  openedFrom,
  checked,
  onCheck,
}: {
  runs: Resource<ReadonlyArray<PinnableRun>>
  reload: () => Promise<void>
  openedFrom: string | null
  checked: string | null
  onCheck: (runId: string) => void
}) {
  switch (runs.state) {
    case "loading":
      return (
        <div aria-label="Wczytywanie Uruchomień" className="mt-1 overflow-hidden rounded-lg border">
          {Array.from({ length: SKELETON_ROWS }, (_, row) => (
            <div key={row} className={ROW}>
              <Skeleton className="size-4 rounded-full" />
              <span className="flex flex-1 flex-col gap-1.5 py-0.5">
                <Skeleton className="h-3.5 w-40" />
                <Skeleton className="h-3 w-56" />
              </span>
            </div>
          ))}
        </div>
      )
    case "failed":
      return <LoadFailure what="Uruchomień" message={runs.message} reload={reload} className="wejscie mt-1" />
    case "ready": {
      const missing = openedFrom !== null && !runs.data.some((run) => run.run_id === openedFrom)

      if (runs.data.length === 0) {
        return (
          <p className="wejscie mt-1 rounded-lg border px-3 py-4 text-center text-sm text-muted-foreground">
            {missing ? `${NOT_IN_HISTORY} Wyślij Uwagę ogólną.` : "Nie ma jeszcze Uruchomień z Centrum."}
          </p>
        )
      }

      return (
        <>
          {missing ? (
            <p className="wejscie mt-1 text-sm text-muted-foreground">
              {NOT_IN_HISTORY} Wybierz inne albo wyślij Uwagę ogólną.
            </p>
          ) : null}
          <RadioGroup
            aria-label="Uruchomienie"
            value={checked}
            onValueChange={onCheck}
            ref={keepCheckedInView}
            className={cn(
              "wejscie relative content-start gap-0 overflow-y-auto overscroll-contain rounded-lg border",
              !missing && "mt-1",
              LIST_HEIGHT
            )}
          >
            {runs.data.map((run) => (
              <label key={run.run_id} className={cn(ROW, "cursor-pointer has-data-checked:bg-muted/60")}>
                <RadioGroupItem value={run.run_id} />
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="flex items-center gap-1.5 truncate">
                    {run.process_label}
                    {run.mode === "DRY-RUN" ? (
                      <EyeIcon className="size-3.5 text-muted-foreground" aria-label="podgląd" />
                    ) : null}
                  </span>
                  <span className="text-xs text-muted-foreground tabular-nums">
                    {run.period} · {run.mode_word} · {dateTime(run.started_at)}
                  </span>
                </span>
                <RunResultBadge run={run} />
              </label>
            ))}
          </RadioGroup>
        </>
      )
    }

    default: {
      const unhandled: never = runs

      return unhandled
    }
  }
}

/** Bez `scrollIntoView`: przewija każdego przewijalnego przodka, także okno dialogu. */
function keepCheckedInView(list: HTMLElement | null) {
  if (list === null) {
    return
  }

  const observer = new ResizeObserver(() => {
    const row = list.querySelector("[data-checked]")?.closest("label")

    if (row) {
      const shown = Math.max(list.scrollTop, row.offsetTop + row.offsetHeight - list.clientHeight)

      list.scrollTop = Math.min(shown, row.offsetTop)
    }
  })

  observer.observe(list)

  return () => observer.disconnect()
}
