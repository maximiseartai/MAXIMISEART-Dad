import * as React from "react"
import { EyeIcon, FileSpreadsheetIcon, FolderIcon, InfoIcon, PlayIcon, ReceiptTextIcon, TriangleAlertIcon, UsersIcon } from "lucide-react"

import type { PathSetting, PeriodChoice, PeriodProcess, ProcessSetup } from "@/api/centrum"
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
import { shortDate } from "@/lib/format"
import { useRuns, type RunDraft } from "@/lib/runs"
import { useSettings } from "@/lib/settings"
import { ConfirmRunDialog } from "@/pages/runs/run-dialogs"

/**
 * Okres w wyborze: dni od wtorku do poniedziałku i Status okresu, a ciszej token, którym nazywa się Folder okresu.
 * Okres zawsze zaczyna się we wtorek i kończy w poniedziałek, więc dni tygodnia są stałe.
 */
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
 * z ustawień i jedna akcja główna „Podgląd bez zapisu”. „Uruchom” zapisuje po potwierdzeniu, a w procesie bez
 * podglądu (Wycena w efenix) jest akcją główną. Przebieg rozliczeń i Wycena w efenix nie mają wyboru pliku: Plik
 * zbiorczy wynika z okresu. Plik wejściowy otwarty w Excelu
 * wyłącza „Uruchom”; podgląd zostaje, bo przy blokadzie po awarii Excela jego Zatrzymanie mówi, co zrobić.
 */
export function RunSetupCard({ processes }: { processes: ReadonlyArray<ProcessSetup> }) {
  const { draft, setDraft, starting, start } = useRuns()
  const { settings, picker, choose } = useSettings()
  const [confirming, setConfirming] = React.useState(false)
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

  const run = (dryRun: boolean) => start({ ...selection, dry_run: dryRun })
  const previewHint = chosen.preview_hint

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
                  {chosen.process !== "preparation" ? (
                    <CollectiveFile choice={chosenPeriod} />
                  ) : (
                    <SettingPath
                      label="Rejestr zleceń"
                      icon={<FileSpreadsheetIcon />}
                      setting={settings.data.order_register}
                      disabled={picker !== null}
                      onChoose={() => choose("order_register")}
                    />
                  )}
                  <SettingPath
                    label="Folder okresów"
                    icon={<FolderIcon />}
                    setting={settings.data.periods_directory}
                    disabled={picker !== null}
                    onChoose={() => choose("periods_directory")}
                  />
                </div>
              ) : null}
            </Field>
          </div>
          {chosen.blocker === null ? null : (
            <Alert className="wejscie">
              <TriangleAlertIcon className="text-warning!" />
              <AlertTitle>{chosen.blocker}</AlertTitle>
            </Alert>
          )}
          {passedOver === null ? null : (
            <Alert className="wejscie">
              <TriangleAlertIcon className="text-warning!" />
              <AlertTitle>
                Okresu {passedOver} nie ma do wyboru, więc wybrany jest {period}.
              </AlertTitle>
            </Alert>
          )}
          {openInExcel.length === 0 ? null : (
            <Alert className="wejscie">
              <TriangleAlertIcon className="text-warning!" />
              <AlertTitle className="flex flex-col gap-0.5">
                {openInExcel.map((sentence) => (
                  <span key={sentence}>{sentence}</span>
                ))}
              </AlertTitle>
            </Alert>
          )}
        </FieldGroup>
      </CardContent>
      <CardFooter className="gap-2">
        {reminder === null ? null : (
          <span className="flex items-center gap-2 text-sm text-muted-foreground">
            <InfoIcon className="size-4" aria-hidden />
            {reminder}
          </span>
        )}
        {previewHint === null ? (
          <Button
            size="lg"
            className="ml-auto h-10 px-4"
            disabled={blocked || openInExcel.length > 0 || starting}
            onClick={() => setConfirming(true)}
          >
            <PlayIcon data-icon="inline-start" />
            Uruchom
          </Button>
        ) : (
          <>
            <Button
              variant="ghost"
              size="lg"
              className="ml-auto"
              disabled={blocked || openInExcel.length > 0 || starting}
              onClick={() => setConfirming(true)}
            >
              Uruchom
            </Button>
            <Tooltip>
              <TooltipTrigger
                render={
                  <Button size="lg" className="h-10 px-4" disabled={blocked || starting} onClick={() => run(true)} />
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
        onConfirm={() => run(false)}
      />
    </Card>
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

export function SettingPath({
  label,
  icon,
  setting,
  disabled,
  onChoose,
}: {
  label: string
  icon: React.ReactNode
  setting: PathSetting
  /** Okno wyboru jest już otwarte; drugie by się tylko na nie nałożyło. */
  disabled: boolean
  onChoose: () => void
}) {
  const verb = setting.state === "not_set" ? "Wskaż" : "Zmień"

  return (
    <div className="flex items-center gap-2 text-sm" role="group" aria-label={label}>
      <span className="text-muted-foreground [&_svg]:size-4" aria-hidden>
        {icon}
      </span>
      {setting.state === "not_set" ? (
        <span className="text-muted-foreground">{label}: nie wskazano</span>
      ) : (
        <Tooltip>
          <TooltipTrigger
            render={
              <span
                tabIndex={0}
                className="truncate rounded-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
              />
            }
          >
            {setting.state === "missing" ? `Nie ma już: ${setting.name}` : setting.name}
          </TooltipTrigger>
          <TooltipContent>
            {label}: {setting.path}
          </TooltipContent>
        </Tooltip>
      )}
      <Button
        variant="link"
        size="sm"
        className="ml-auto h-auto px-0"
        disabled={disabled}
        aria-label={`${verb} ${label}`}
        onClick={onChoose}
      >
        {verb}
      </Button>
    </div>
  )
}
