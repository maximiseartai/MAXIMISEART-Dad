import * as React from "react"
import { EyeIcon, FileSpreadsheetIcon, FolderIcon, InfoIcon, ReceiptTextIcon, TriangleAlertIcon, UsersIcon } from "lucide-react"

import type { PeriodProcess, Pricing } from "@/api/centrum"
import type { PeriodChoice, ProcessSetup, RunRequest } from "@/api/generated"
import { SettingPath } from "@/components/setting-path"
import { Alert, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldGroup,
  FieldLabel,
  FieldTitle,
} from "@/components/ui/field"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { WarningSentences } from "@/components/warning-sentences"
import { shortDate } from "@/lib/format"
import { PRICING } from "@/lib/pricing"
import { useRuns, type RunDraft } from "@/lib/runs"
import { useSettings } from "@/lib/settings"
import { ConfirmRunDialog } from "@/pages/runs/run-dialogs"

/** Okres zawsze zaczyna się we wtorek i kończy w poniedziałek, więc dni tygodnia są stałe. */
function PeriodLabel({ choice }: { choice: PeriodChoice }) {
  return (
    <>
      <span>
        wt {shortDate(choice.tuesday)} – pon {shortDate(choice.monday)} ·{" "}
        {choice.last_complete ? "ostatni pełny" : choice.status_label}
      </span>
      <span className="ml-auto pl-3 text-muted-foreground">
        <span className="sr-only"> · </span>
        {choice.token}
      </span>
    </>
  )
}

const PROCESS_ICONS: Record<PeriodProcess, React.ReactNode> = {
  preparation: <FileSpreadsheetIcon aria-hidden />,
  settlement: <UsersIcon aria-hidden />,
  efenix: <ReceiptTextIcon aria-hidden />,
}

/**
 * Nowe Uruchomienie procesu: proces (kafelki), okres z preselekcją ostatniego pełnego okresu, pliki
 * z ustawień i jedna akcja główna „Podgląd bez zapisu”. „Uruchom” zapisuje po potwierdzeniu. Wycena w efenix nie ma
 * podglądu, a zamiast „Uruchom” ma przycisk każdego swojego trybu obok siebie, równej wagi i bez domyślnego, bo tata
 * wybiera tryb przy każdym starcie (ADR 0027). Przebieg rozliczeń i
 * Wycena w efenix nie mają wyboru pliku: Plik zbiorczy wynika z okresu. Plik wejściowy otwarty w Excelu
 * wyłącza „Uruchom”; podgląd zostaje, bo przy blokadzie po awarii Excela jego Zatrzymanie mówi, co zrobić.
 */
export function RunSetupCard({ processes }: { processes: ReadonlyArray<ProcessSetup> }) {
  const { draft, setDraft, starting, start } = useRuns()
  const { settings } = useSettings()
  const [confirming, setConfirming] = React.useState(false)
  // Tryb przycisku, który otworzył potwierdzenie; zostaje po zamknięciu, żeby okno nie zmieniało treści, gdy znika.
  const [pricing, setPricing] = React.useState<Pricing | null>(null)
  const chosen = processes.find((setup) => setup.process === draft?.process) ?? processes[0]

  if (chosen === undefined) {
    return null
  }

  const period =
    draft !== null && chosen.periods.some((choice) => choice.token === draft.period)
      ? draft.period
      : chosen.preselected_period

  const selection: RunDraft = { process: chosen.process, period }
  const chosenPeriod = chosen.periods.find((choice) => choice.token === period)

  // Okres przyniesiony spoza formularza (np. „Gotowe” Uzupełnienia), którego proces nie oferuje: inny wybór na głos.
  // Bez okresu do wyboru mówi już blokada.
  const passedOver =
    draft !== null && draft.process === chosen.process && draft.period !== period && chosenPeriod !== undefined ? draft.period : null

  const blocked = chosen.blocker !== null
  const openInExcel = chosenPeriod?.open_in_excel ?? []
  const reminder = chosenPeriod === undefined ? chosen.reminder : chosenPeriod.reminder

  const choices = chosen.periods.map((choice) => ({ value: choice.token, label: <PeriodLabel choice={choice} /> }))

  const run = (dryRun: boolean, chosenPricing: Pricing | null) => {
    const request: RunRequest = { ...selection, mode: dryRun ? "DRY-RUN" : "RUN" }

    if (chosenPricing !== null) {
      request.pricing = chosenPricing
    }

    return start(request)
  }

  const confirm = (chosenPricing: Pricing | null) => {
    setPricing(chosenPricing)
    setConfirming(true)
  }

  const previewHint = chosen.preview_hint
  const runBlocked = blocked || openInExcel.length > 0 || starting

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">Nowe Uruchomienie procesu</CardTitle>
      </CardHeader>
      <CardContent>
        <FieldGroup>
          <RadioGroup
            aria-label="Proces"
            value={chosen.process}
            onValueChange={(value) => {
              const next = processes.find((setup) => setup.process === value)

              if (next !== undefined) {
                setDraft({ process: next.process, period: next.preselected_period })
              }
            }}
            className="grid-cols-3"
          >
            {processes.map((setup) => (
              <FieldLabel key={setup.process} htmlFor={`proces-${setup.process}`}>
                <Field orientation="horizontal">
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-muted [&_svg]:size-4">
                    {PROCESS_ICONS[setup.process]}
                  </span>
                  <FieldContent>
                    <FieldTitle>{setup.title}</FieldTitle>
                    <FieldDescription>{setup.creates}</FieldDescription>
                  </FieldContent>
                  <RadioGroupItem value={setup.process} id={`proces-${setup.process}`} />
                </Field>
              </FieldLabel>
            ))}
          </RadioGroup>
          <div className="grid grid-cols-2 gap-4">
            <Field>
              <FieldLabel htmlFor="okres">Okres</FieldLabel>
              <Select
                items={choices}
                disabled={choices.length === 0}
                value={period}
                onValueChange={(value) => {
                  const choice = chosen.periods.find((candidate) => candidate.token === value)

                  if (choice !== undefined) {
                    setDraft({ process: chosen.process, period: choice.token })
                  }
                }}
              >
                <SelectTrigger id="okres" className="w-full tabular-nums">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="w-auto min-w-(--anchor-width)">
                  <SelectGroup>
                    {choices.map((choice) => (
                      <SelectItem key={choice.value} value={choice.value} className="tabular-nums">
                        {choice.label}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
            <Field>
              <FieldLabel>Pliki</FieldLabel>
              {settings.state === "ready" ? (
                <div className="flex flex-col gap-1">
                  {chosen.reads === "collective_file" ? (
                    <CollectiveFile choice={chosenPeriod} />
                  ) : (
                    <SettingPath label="Rejestr zleceń" icon={<FileSpreadsheetIcon />} path="order_register" />
                  )}
                  <SettingPath label="Folder okresów" icon={<FolderIcon />} path="periods_directory" />
                </div>
              ) : null}
            </Field>
          </div>
          <WarningSentences sentences={chosen.blocker === null ? [] : [chosen.blocker]} />
          {passedOver === null ? null : (
            <Alert className="wejscie">
              <TriangleAlertIcon className="text-warning!" />
              <AlertTitle>
                Okresu {passedOver} nie ma do wyboru, więc wybrany jest {period}.
              </AlertTitle>
            </Alert>
          )}
          <WarningSentences sentences={openInExcel} />
        </FieldGroup>
      </CardContent>
      <CardFooter className="gap-2">
        {reminder === null ? null : (
          <span className="flex items-center gap-2 text-sm text-muted-foreground">
            <InfoIcon className="size-4" aria-hidden />
            {reminder}
          </span>
        )}
        {chosen.pricing_modes.length > 0 ? (
          <div className="ml-auto flex items-start gap-3">
            {chosen.pricing_modes.map((mode) => (
              <PricingButton key={mode} pricing={mode} disabled={runBlocked} onClick={() => confirm(mode)} />
            ))}
          </div>
        ) : (
          <>
            <Button
              variant="ghost"
              size="lg"
              className="ml-auto"
              disabled={runBlocked}
              onClick={() => confirm(null)}
            >
              Uruchom
            </Button>
            <Tooltip>
              <TooltipTrigger
                render={
                  <Button size="lg" className="h-10 px-4" disabled={blocked || starting} onClick={() => run(true, null)} />
                }
              >
                <EyeIcon data-icon="inline-start" />
                Podgląd bez zapisu
              </TooltipTrigger>
              <TooltipContent>{previewHint}</TooltipContent>
            </Tooltip>
          </>
        )}
      </CardFooter>
      <ConfirmRunDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={chosen.title}
        period={period}
        reminder={chosen.reminder}
        confirmsReadiness={chosen.confirms_readiness}
        // Bez podglądu bez zapisu w procesie nie ma czego uprzedzać.
        previewed={previewHint === null || (chosenPeriod?.previewed ?? false)}
        pricing={pricing}
        onConfirm={() => run(false, pricing)}
      />
    </Card>
  )
}

/** Przycisk trybu Wyceny w efenix z podpisem pod nim, który mówi, kto klika zielony „Zapisz” w efenix. */
function PricingButton({ pricing, disabled, onClick }: { pricing: Pricing; disabled: boolean; onClick: () => void }) {
  const mode = PRICING[pricing]
  const hintId = React.useId()

  return (
    <div className="flex w-72 flex-col gap-1.5">
      <Button variant="outline" size="lg" className="h-10 px-4" disabled={disabled} aria-describedby={hintId} onClick={onClick}>
        <mode.icon data-icon="inline-start" />
        {mode.label}
      </Button>
      <p id={hintId} className="text-center text-xs text-pretty text-muted-foreground">
        {mode.hint}
      </p>
    </div>
  )
}

/** Plik zbiorczy wybranego okresu: tylko nazwa, bo wynika z okresu i folderu okresów. */
function CollectiveFile({ choice }: { choice: PeriodChoice | undefined }) {
  return (
    <div className="flex items-center gap-2 text-sm" role="group" aria-label="Plik zbiorczy">
      <span className="text-muted-foreground [&_svg]:size-4" aria-hidden>
        <FileSpreadsheetIcon />
      </span>
      {choice === undefined || choice.collective_file === null ? (
        <span className="text-muted-foreground">Plik zbiorczy: brak okresu do wyboru</span>
      ) : (
        <span className="truncate tabular-nums">{choice.collective_file}</span>
      )}
    </div>
  )
}
