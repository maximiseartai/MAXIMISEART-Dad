import { ArrowRightIcon, EyeIcon, PlayIcon } from "lucide-react"

import type { PeriodProcess, PeriodRow, ProcessStep } from "@/api/centrum"
import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { isActive, useRuns } from "@/lib/runs"
import type { PageHref } from "@/pages"

const RUNS_PAGE: PageHref = "#/uruchomienia"

/** Proces, który robi krok okresu; „none” (okres zamknięty) nie ma procesu. */
const STEP_PROCESSES: Record<ProcessStep["action"], PeriodProcess> = {
  prepare_collective_file: "preparation",
  price_in_efenix: "efenix",
  create_worker_settlements: "settlement",
}

const PRIMARY_LOOK = { size: "lg", className: "h-11 px-5 text-base" } as const

const SECONDARY_LOOK = { variant: "ghost", className: "text-muted-foreground" } as const

function showRuns() {
  window.location.hash = RUNS_PAGE
}

/**
 * Akcja karty „Następny krok”: podgląd bez zapisu procesu następnego kroku od razu, a w trakcie Uruchomienia
 * przejście do podglądu na żywo; proces bez podglądu (Wycena w efenix) otwiera nowe Uruchomienie z tym okresem.
 * Podpowiedź podglądu przychodzi z krokiem. Główna, chyba że karta ma inną akcję główną (`secondary`).
 */
export function StepAction({
  period,
  step,
  secondary,
}: {
  period: PeriodRow
  step: ProcessStep
  secondary: boolean
}) {
  const look = secondary ? SECONDARY_LOOK : PRIMARY_LOOK

  return step.preview_hint === null ? (
    <DraftButton period={period} step={step} look={look} />
  ) : (
    <PreviewAction period={period} step={step} hint={step.preview_hint} look={look} />
  )
}

type Look = typeof PRIMARY_LOOK | typeof SECONDARY_LOOK

function PreviewAction({ period, step, hint, look }: { period: PeriodRow; step: ProcessStep; hint: string; look: Look }) {
  const { view, start } = useRuns()
  const process = STEP_PROCESSES[step.action]

  if (isActive(view)) {
    return (
      <Button {...look} onClick={showRuns}>
        <PlayIcon data-icon="inline-start" />
        Pokaż podgląd na żywo
      </Button>
    )
  }

  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            {...look}
            onClick={() =>
              start({ process, period: period.token, dry_run: true }).then((started) => started && showRuns())
            }
          />
        }
      >
        <EyeIcon data-icon="inline-start" />
        Podgląd bez zapisu
      </TooltipTrigger>
      <TooltipContent>{hint}</TooltipContent>
    </Tooltip>
  )
}

/** Przycisk kroku, który otwiera nowe Uruchomienie z procesem kroku i tym okresem do wybrania. */
function DraftButton({ period, step, look }: { period: PeriodRow; step: ProcessStep; look: Look }) {
  const { setDraft } = useRuns()

  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            {...look}
            onClick={() => {
              setDraft({ process: STEP_PROCESSES[step.action], period: period.token })
              showRuns()
            }}
          />
        }
      >
        {step.label}
        <ArrowRightIcon data-icon="inline-end" />
      </TooltipTrigger>
      <TooltipContent>{step.hint}</TooltipContent>
    </Tooltip>
  )
}

/**
 * Krok w wierszu Tablicy okresów: przejście do Uruchomień z tym procesem i okresem do wybrania. Krok obok
 * następnego (`secondary`) jest stonowany i bez strzałki.
 */
export function PrepareLink({ period, step, secondary }: { period: PeriodRow; step: ProcessStep; secondary: boolean }) {
  const { setDraft } = useRuns()

  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            variant="ghost"
            size="sm"
            className={secondary ? "text-muted-foreground" : undefined}
            aria-label={`${step.label}, okres ${period.token}`}
            onClick={() => {
              setDraft({ process: STEP_PROCESSES[step.action], period: period.token })
              showRuns()
            }}
          />
        }
      >
        {step.label}
        {secondary ? null : <ArrowRightIcon data-icon="inline-end" />}
      </TooltipTrigger>
      <TooltipContent>{step.hint}</TooltipContent>
    </Tooltip>
  )
}
