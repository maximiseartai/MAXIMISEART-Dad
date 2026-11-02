import { CalendarRangeIcon, CircleCheckIcon, ClipboardPenLineIcon, FolderXIcon } from "lucide-react"

import type { PeriodRow } from "@/api/centrum"
import { PeriodPath } from "@/components/period-path"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { href } from "@/lib/address"
import { fullDate } from "@/lib/format"
import { StepAction } from "@/pages/periods/prepare-actions"

/**
 * „Następny krok” zawsze dla ostatniego pełnego okresu: krótki tytuł, fakty z ikonami i Droga okresu.
 * Gdy okres ma następny krok, jedyną akcją główną strony jest akcja tego kroku: „Podgląd bez zapisu” procesu
 * albo, dla Wyceny w efenix bez podglądu, nowe Uruchomienie z tym okresem. Przy przygotowanym Pliku zbiorczym
 * akcją główną jest „Uzupełnij” (podsumowanie Uzupełnienia pliku zbiorczego), a akcja kroku zostaje obok jako druga.
 */
export function NextStepCard({ period }: { period: PeriodRow }) {
  const step = period.next_step
  const filling = period.status === "collective_file_prepared"

  return (
    <Card className="bg-linear-to-br from-muted/60 to-card" role="region" aria-label="Następny krok">
      <CardContent className="relative flex flex-col gap-4 py-2">
        {step.action === "none" ? null : (
          <div className="absolute top-1/2 right-4 flex -translate-y-1/2 flex-col items-end gap-1.5">
            {filling ? (
              <Button
                size="lg"
                className="h-11 px-5 text-base"
                nativeButton={false}
                render={<a href={href("uzupelnienie", period.token)} />}
              >
                <ClipboardPenLineIcon data-icon="inline-start" />
                Uzupełnij
              </Button>
            ) : null}
            <StepAction period={period} step={step} secondary={filling} />
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
