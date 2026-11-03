import { CalendarRangeIcon, CircleCheckIcon, FolderXIcon } from "lucide-react"

import type { FillStep, PeriodRow, ProcessStep } from "@/api/centrum"
import { PeriodPath } from "@/components/period-path"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { fullDate } from "@/lib/format"
import { FillAction, StepAction } from "@/pages/periods/prepare-actions"

/**
 * „Następny krok” zawsze dla ostatniego pełnego okresu: tytuł bieżącego kroku Drogi okresu, fakty z ikonami i Droga
 * okresu. Gdy okres ma następny krok, jedyną akcją główną strony jest akcja tego kroku: „Uzupełnij” (podsumowanie
 * Uzupełnienia pliku zbiorczego) z Wyceną w efenix obok jako drugą, „Podgląd bez zapisu” procesu albo, dla Wyceny
 * w efenix bez podglądu, nowe Uruchomienie z tym okresem.
 */
export function NextStepCard({ period }: { period: PeriodRow }) {
  const step = period.next_step

  return (
    <Card className="bg-linear-to-br from-muted/60 to-card" role="region" aria-label="Następny krok">
      <CardContent className="relative flex flex-col gap-4 py-2">
        {step.action === "none" ? null : (
          <div className="absolute top-1/2 right-4 flex -translate-y-1/2 flex-col items-end gap-1.5">
            <StepActions period={period} step={step} />
          </div>
        )}
        <Badge variant="outline">Następny krok</Badge>
        <h2 className="flex items-center gap-3 text-3xl font-semibold tracking-tight">
          {step.action === "none" ? <CircleCheckIcon className="size-7 text-success" aria-hidden /> : null}
          {step.label}
        </h2>
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-muted-foreground [&_svg]:size-4">
          <span className="flex items-center gap-1.5 font-medium text-foreground tabular-nums">
            <CalendarRangeIcon aria-hidden />
            {period.token}
          </span>
          <span className="tabular-nums">
            wt {fullDate(period.tuesday)} – pon {fullDate(period.monday)}
          </span>
          {period.period_folder_exists ? null : (
            <span className="flex items-center gap-1.5">
              <FolderXIcon aria-hidden />
              Brak Folderu okresu
            </span>
          )}
        </div>
        <PeriodPath path={period.path} />
        <p className="text-sm text-muted-foreground">{step.hint}</p>
      </CardContent>
    </Card>
  )
}

/** Akcja główna kroku i druga pod nią: pod „Uzupełnij” Wycena w efenix, a później „Uzupełnij” pod akcją kroku. */
function StepActions({ period, step }: { period: PeriodRow; step: ProcessStep | FillStep }) {
  if (step.action === "fill_collective_file") {
    return (
      <>
        <FillAction period={period} secondary={false} />
        <StepAction period={period} step={step.then} secondary />
      </>
    )
  }

  return (
    <>
      <StepAction period={period} step={step} secondary={false} />
      {period.status === "collective_file_prepared" ? <FillAction period={period} secondary /> : null}
    </>
  )
}
