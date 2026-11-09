import { ArrowRightIcon, EyeIcon, PlayIcon } from "lucide-react"

import type { FillStep, PeriodRow, ProcessStep } from "@/api/centrum"
import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { href } from "@/lib/address"
import { isActive, useRuns } from "@/lib/runs"
import { FillLink } from "@/pages/filling/fill-link"

const PRIMARY_LOOK = { size: "lg", className: "h-11 px-5 text-base" } as const

const SECONDARY_LOOK = { variant: "ghost", className: "text-muted-foreground" } as const

const ROW_LOOK = { variant: "ghost", size: "sm" } as const

const SECONDARY_ROW_LOOK = { ...ROW_LOOK, className: "text-muted-foreground" } as const

type Look = typeof PRIMARY_LOOK | typeof SECONDARY_LOOK | typeof ROW_LOOK | typeof SECONDARY_ROW_LOOK

function showRuns() {
  window.location.hash = href("uruchomienia")
}

/**
 * Akcja karty „Następny krok”: podgląd bez zapisu procesu następnego kroku od razu, a w trakcie Uruchomienia
 * przejście do podglądu na żywo; proces bez podglądu (Wycena w efenix) otwiera nowe Uruchomienie z tym okresem.
 * Główna, chyba że karta ma inną akcję główną (`secondary`).
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
    <DraftButton period={period} step={step} look={look} arrow />
  ) : (
    <PreviewAction period={period} step={step} hint={step.preview_hint} look={look} />
  )
}

export function FillAction({ period, secondary }: { period: PeriodRow; secondary: boolean }) {
  return <FillLink token={period.token} {...(secondary ? SECONDARY_LOOK : PRIMARY_LOOK)} />
}

function PreviewAction({ period, step, hint, look }: { period: PeriodRow; step: ProcessStep; hint: string; look: Look }) {
  const { view, start } = useRuns()

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
              start({ process: step.process, period: period.token, mode: "DRY-RUN" }).then((started) => started && showRuns())
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

function DraftButton({
  period,
  step,
  look,
  arrow,
  label,
}: {
  period: PeriodRow
  step: ProcessStep
  look: Look
  arrow: boolean
  label?: string
}) {
  const { setDraft } = useRuns()

  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            {...look}
            aria-label={label}
            onClick={() => {
              setDraft({ process: step.process, period: period.token })
              showRuns()
            }}
          />
        }
      >
        {step.label}
        {arrow ? <ArrowRightIcon data-icon="inline-end" /> : null}
      </TooltipTrigger>
      <TooltipContent>{step.hint}</TooltipContent>
    </Tooltip>
  )
}

/** Krok w wierszu Tablicy okresów; `secondary` to krok obok następnego. */
export function PrepareLink({ period, step, secondary }: { period: PeriodRow; step: ProcessStep; secondary: boolean }) {
  return (
    <DraftButton
      period={period}
      step={step}
      look={secondary ? SECONDARY_ROW_LOOK : ROW_LOOK}
      arrow={!secondary}
      label={`${step.label}, okres ${period.token}`}
    />
  )
}

export function FillStepLink({ period, step }: { period: PeriodRow; step: FillStep }) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={<FillLink token={period.token} {...ROW_LOOK} aria-label={`Uzupełnij, okres ${period.token}`} arrow />}
      />
      <TooltipContent>{step.hint}</TooltipContent>
    </Tooltip>
  )
}
