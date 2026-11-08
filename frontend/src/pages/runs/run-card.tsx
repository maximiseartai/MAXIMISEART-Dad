import * as React from "react"
import { cn } from "cn"
import {
  ArchiveIcon,
  CircleCheckIcon,
  CircleDashedIcon,
  CircleXIcon,
  EyeIcon,
  FileSpreadsheetIcon,
  FileTextIcon,
  FolderOpenIcon,
  HistoryIcon,
  InfoIcon,
  PlayIcon,
  PlusIcon,
  RotateCcwIcon,
  TriangleAlertIcon,
  WifiOffIcon,
} from "lucide-react"

import type {
  LoggedOutcome,
  Message,
  NextAction,
  OrderNote,
  OrderNotes,
  PastRun,
  PeriodFile,
  PhaseProgress,
  Pricing,
  Progress as RunProgress,
  ProgressStep,
  RunInfo,
  RunInterrupted,
  RunOutcome,
  RunRestored,
  RunSummary,
  RunView,
  WorkerSettlement,
} from "@/api/centrum"
import { Alert, AlertAction, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress, ProgressLabel, ProgressValue } from "@/components/ui/progress"
import { Spinner } from "@/components/ui/spinner"
import { Table, TableBody, TableCell, TableRow } from "@/components/ui/table"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { Disclosure } from "@/components/disclosure"
import { StopMessage, ThreePartMessage } from "@/components/three-part-message"
import { WriteAboutRun } from "@/components/write-to-maks"
import { useChangeEntrance } from "@/lib/content-entrance"
import { dateTime, plural, seconds } from "@/lib/format"
import { PRICING } from "@/lib/pricing"
import { rerunOf, useRuns } from "@/lib/runs"
import { FillingOnResult } from "@/pages/filling/filling-on-result"
import { OpenCollectiveFileButton } from "@/pages/periods/open-collective-file"
import { openAndConfirm, openOrderRegisterAndConfirm, type OpenedInPeriod } from "@/pages/periods/open-period-path"
import { CountTiles, NumberStrip } from "@/pages/runs/count-tiles"
import { useStopDiagnosis } from "@/pages/runs/diagnosis"
import { ConfirmRunDialog } from "@/pages/runs/run-dialogs"
import { UnreadableStream } from "@/pages/runs/unreadable-stream"

type LiveRun = Exclude<RunView, { state: "idle" }>

type RunRecorded = Extract<PastRun, { state: "recorded" }>

const PHASE_ICONS: Record<PhaseProgress["state"], React.ReactNode> = {
  pending: <CircleDashedIcon className="text-muted-foreground" aria-hidden />,
  running: <Spinner />,
  completed: <CircleCheckIcon className="text-success" aria-hidden />,
  failed: <CircleXIcon className="text-destructive" aria-hidden />,
}

const PHASE_STATE_LABELS: Record<PhaseProgress["state"], string> = {
  pending: "oczekuje",
  running: "trwa",
  completed: "zakończony",
  failed: "przerwany",
}

// Etap, który trwa, ma pasek nieokreślony (`null`): czasu etapu nie znamy z góry.
const PHASE_VALUES: Record<PhaseProgress["state"], number | null> = {
  pending: 0,
  running: null,
  completed: 100,
  failed: 100,
}

/** Podgląd na żywo bieżącego Uruchomienia procesu i jego wynik; wszystko z widoku serwera. */
export function RunCard({
  view,
  reminder,
  onNewRun,
}: {
  view: LiveRun
  reminder: string
  onNewRun: () => void
}) {
  const { disconnected } = useRuns()
  const run = view.run
  const stale = view.state !== "awaiting_decision" && view.progress_stale

  return (
    <Card role="region" aria-label="Podgląd na żywo">
      <RunHeader
        run={run}
        actions={
          view.state === "finished" ? (
            <>
              <NewRunButton onNewRun={onNewRun} />
              <WriteAboutRun runId={run.id} />
            </>
          ) : null
        }
      />
      <CardContent className="flex flex-col gap-6">
        <PhaseList phases={view.progress.phases} />
        {view.state === "finished" ? null : <NumberStrip name="Liczniki" figures={view.progress.figures} />}
        {view.state !== "finished" && view.progress.template_total > 0 ? (
          <TemplateProgress progress={view.progress} />
        ) : null}
        {view.state !== "finished" && view.progress.step != null ? <StepProgress step={view.progress.step} /> : null}
        {stale && view.state === "running" ? (
          <Alert className="wejscie">
            <WifiOffIcon />
            <AlertTitle>Podgląd przestał się aktualizować</AlertTitle>
            <AlertDescription>Uruchomienie trwa dalej. Wynik pojawi się tutaj.</AlertDescription>
          </Alert>
        ) : null}
        <UnreadableStream />
        {disconnected && view.state !== "finished" ? (
          <Alert className="wejscie">
            <WifiOffIcon />
            <AlertTitle>Brak połączenia z Centrum rozliczeń</AlertTitle>
            <AlertDescription>Łączę ponownie. Uruchomienie trwa dalej na komputerze.</AlertDescription>
          </Alert>
        ) : null}
        {view.state === "awaiting_decision" ? (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <InfoIcon className="size-4" aria-hidden />
            Czeka na Twoją decyzję.
          </p>
        ) : null}
        {view.state === "finished" ? (
          <RunOutcomeSection key={run.id} run={run} result={view.result} reminder={reminder} />
        ) : null}
      </CardContent>
    </Card>
  )
}

/**
 * Ostatnie Uruchomienie sprzed startu Centrum, z dysku: karta z Logów Uruchomienia, wynik z Historii, gdy Centrum
 * zamknęło się przed zapisem Logów, albo Uruchomienie, w którego trakcie Centrum się zamknęło. Wygląda jak wynik na
 * żywo, z dopiskiem, skąd jest.
 */
export function PastRunCard({ past, reminder, onNewRun }: { past: PastRun; reminder: string; onNewRun: () => void }) {
  switch (past.state) {
    case "restored":
      return <RestoredRunCard past={past} reminder={reminder} onNewRun={onNewRun} />
    case "recorded":
      return <RecordedRunCard past={past} reminder={reminder} onNewRun={onNewRun} />
    case "interrupted":
      return <InterruptedRunCard past={past} onNewRun={onNewRun} />
    default: {
      const unhandled: never = past

      return unhandled
    }
  }
}

function RestoredRunCard({ past, reminder, onNewRun }: { past: RunRestored; reminder: string; onNewRun: () => void }) {
  const { run, result } = past
  const next = useNextAction(run, result.next_action, reminder)

  return (
    <FinishedPastCard run={run} onNewRun={onNewRun}>
      <PastNote>Ostatnie Uruchomienie · {dateTime(past.started_at)} · Centrum było od tego czasu zamknięte</PastNote>
      <PhaseList phases={past.phases} />
      <OutcomeBody run={run} result={result} action={next.button} filling />
      {next.dialog}
    </FinishedPastCard>
  )
}

/** Wynik z Historii bez szczegółów: Centrum zamknęło się tuż po wyniku, zanim zapisało resztę karty. */
function RecordedRunCard({ past, reminder, onNewRun }: { past: RunRecorded; reminder: string; onNewRun: () => void }) {
  const { run } = past
  const next = useNextAction(run, past.next_action, reminder)

  return (
    <FinishedPastCard run={run} onNewRun={onNewRun}>
      <PastNote>
        Ostatnie Uruchomienie · {dateTime(past.started_at)} · Centrum zamknęło się tuż po wyniku, więc szczegółów nie ma
      </PastNote>
      <ResultAlert result={past.result} headline={past.headline} action={next.button} />
      {next.dialog}
    </FinishedPastCard>
  )
}

/** Karta skończonego Uruchomienia sprzed startu Centrum: można zacząć nowe albo napisać o nim do Maksa. */
function FinishedPastCard({ run, onNewRun, children }: { run: RunInfo; onNewRun: () => void; children: React.ReactNode }) {
  return (
    <Card role="region" aria-label="Ostatnie Uruchomienie">
      <RunHeader
        run={run}
        actions={
          <>
            <NewRunButton onNewRun={onNewRun} />
            <WriteAboutRun runId={run.id} />
          </>
        }
      />
      <CardContent className="flex flex-col gap-6">{children}</CardContent>
    </Card>
  )
}

function InterruptedRunCard({ past, onNewRun }: { past: RunInterrupted; onNewRun: () => void }) {
  const { rerun } = useRuns()
  const run = past.run

  return (
    <Card role="region" aria-label="Ostatnie Uruchomienie">
      <RunHeader run={run} actions={<NewRunButton onNewRun={onNewRun} />} />
      <CardContent className="flex flex-col gap-6">
        <PastNote>Ostatnie Uruchomienie · {dateTime(past.started_at)} · Centrum zamknęło się w trakcie</PastNote>
        <ThreePartMessage
          message={past.advice}
          kind="warning"
          action={<RerunButton onRerun={() => rerun(run)} />}
        />
        {past.orders == null ? null : (
          <CountTiles title={past.orders.title} counts={past.orders.counts} zeroWarns={past.orders.zero_warns} />
        )}
      </CardContent>
    </Card>
  )
}

/**
 * Karta Uruchomienia z wiersza Historii, tylko do odczytu: tryb, etapy i wynik z Logów Uruchomienia, bez akcji.
 * Plakietka trybu stoi tu, a nie w nagłówku panelu, bo tryb Wyceny w efenix znają tylko Logi.
 */
export function HistoryRunCard({ card }: { card: RunRestored }) {
  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-3">
        <PastNote>Uruchomienie z {dateTime(card.started_at)}</PastNote>
        <ModeBadge dryRun={card.run.mode === "DRY-RUN"} pricing={card.run.pricing} />
      </div>
      <PhaseList phases={card.phases} />
      <OutcomeBody run={card.run} result={card.result} action={null} />
    </div>
  )
}

/** Okres, proces, tryb i akcje karty Uruchomienia. */
function RunHeader({ run, actions }: { run: RunInfo; actions: React.ReactNode }) {
  return (
    <CardHeader>
      <CardDescription className="tabular-nums">Okres {run.period}</CardDescription>
      <CardTitle className="text-lg">{run.title}</CardTitle>
      <CardAction className="flex items-center gap-2">
        <ModeBadge dryRun={run.mode === "DRY-RUN"} pricing={run.pricing} />
        {actions}
      </CardAction>
    </CardHeader>
  )
}

/**
 * Tryb Uruchomienia: podgląd bez zapisu albo zapis plików, a w Wycenie w efenix (`pricing`) zielony „Zapisz” w efenix.
 * Wycena nie ma podglądu, więc jej plakietka mówi tylko o zielonym „Zapisz”: na karcie „zapis” znaczy jedno.
 */
export function ModeBadge({ dryRun, pricing }: { dryRun: boolean; pricing: Pricing | null }) {
  if (pricing !== null) {
    return <Badge variant={pricing === "z Przekazaniem" ? "default" : "outline"}>{PRICING[pricing].badge}</Badge>
  }

  return (
    <Badge variant={dryRun ? "outline" : "default"}>
      {dryRun ? <EyeIcon data-icon="inline-start" /> : null}
      {dryRun ? "Bez zapisu" : "Z zapisem"}
    </Badge>
  )
}

function PastNote({ children }: { children: React.ReactNode }) {
  return (
    <p className="flex items-center gap-2 text-sm text-muted-foreground tabular-nums">
      <HistoryIcon className="size-4" aria-hidden />
      {children}
    </p>
  )
}

function NewRunButton({ onNewRun }: { onNewRun: () => void }) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={<Button variant="ghost" size="icon-sm" aria-label="Nowe Uruchomienie procesu" onClick={onNewRun} />}
      >
        <PlusIcon />
      </TooltipTrigger>
      <TooltipContent>Nowe Uruchomienie procesu</TooltipContent>
    </Tooltip>
  )
}

function PhaseList({ phases }: { phases: ReadonlyArray<PhaseProgress> }) {
  return (
    <ol className="grid grid-cols-4 gap-4" aria-label="Etapy">
      {phases.map((phase) => (
        <li
          key={phase.phase}
          className="flex flex-col gap-2"
          aria-label={`${phase.phase}: ${PHASE_STATE_LABELS[phase.state]}`}
        >
          <span className="flex items-center gap-2 text-sm font-medium [&_svg]:size-4">
            <PhaseIcon state={phase.state} />
            <span data-pending={phase.state === "pending"} className="data-[pending=true]:text-muted-foreground">
              {phase.phase}
            </span>
          </span>
          <Progress
            value={PHASE_VALUES[phase.state]}
            aria-label={phase.phase}
            className={phase.state === "failed" ? "**:data-[slot=progress-indicator]:bg-destructive" : undefined}
          />
          <span className="h-4 text-xs text-muted-foreground tabular-nums">
            {phase.state === "completed" || phase.state === "failed" ? seconds(phase.duration_ms) : null}
          </span>
        </li>
      ))}
    </ol>
  )
}

/** Ikona stanu etapu. Ikona stanu, który zmienił się na oczach taty, wchodzi `podmiana`; zastana stoi. */
function PhaseIcon({ state }: { state: PhaseProgress["state"] }) {
  const entrance = useChangeEntrance(state, "podmiana")

  return (
    <span key={state} className={cn("flex", entrance)}>
      {PHASE_ICONS[state]}
    </span>
  )
}

function RunOutcomeSection({ run, result, reminder }: { run: RunInfo; result: RunOutcome; reminder: string }) {
  const { rerun } = useRuns()
  const next = useNextAction(run, result.next_action, reminder)
  // Czy i jak proponować Diagnozę, mówi serwer: przy niej przycisk „Diagnoza” zastępuje następną akcję.
  const offersDiagnosis = result.diagnosis !== null

  const diagnosis = useStopDiagnosis(run.id, result.diagnosis, result.report, () => rerun(run))

  return (
    <>
      <OutcomeBody
        run={run}
        result={result}
        action={offersDiagnosis ? diagnosis.action : next.button}
        live={{ filesUnchanged: result.files_unchanged, opens: result.opens, openFirst: !offersDiagnosis }}
        below={offersDiagnosis ? diagnosis.result : null}
        notes={result.order_notes ?? null}
        filling
      />
      {next.dialog}
    </>
  )
}

type StopKind = NonNullable<RunOutcome["stop_kind"]>

type DadFile = NonNullable<RunOutcome["opens"]>

/** To, co przy Zatrzymaniu wie tylko bieżące Uruchomienie, a Logi Uruchomienia nie: notka o plikach i plik taty. */
type LiveStop = { filesUnchanged: boolean; opens: DadFile | null; openFirst: boolean }

/**
 * Wynik: liczby, tytuł albo Zatrzymanie z akcją, ostrzeżenia, uwagi techniczne i szczegóły podsumowania.
 * Z `filling` przygotowany Plik zbiorczy ma pod wynikiem podsumowanie Uzupełnienia pliku zbiorczego, w stanie z pliku.
 */
function OutcomeBody({
  run,
  result,
  action,
  live = null,
  below = null,
  notes = null,
  filling = false,
}: {
  run: RunInfo
  result: LoggedOutcome
  action: React.ReactNode
  live?: LiveStop | null
  below?: React.ReactNode
  /** Zlecenia, które zostały tacie, Zlecenia przekazane i rozliczone, z numerami i Wykonawcami: zastępują ostrzeżenia w trzech częściach. */
  notes?: ReadonlyArray<OrderNotes> | null
  filling?: boolean
}) {
  const [stop] = result.stops

  // Wynik bez Zatrzymania, który proponuje otworzyć Plik zbiorczy zapisany jako plik okresu, to Plik zbiorczy przygotowany
  // (Wycena w efenix też proponuje Plik zbiorczy, ale go nie tworzy).
  const prepared =
    filling &&
    result.next_action === "open_collective_file" &&
    stop === undefined &&
    (result.summary?.files.some((file) => file.kind === "collective_file") ?? false)

  return (
    <>
      {result.summary === null ? null : <NumberStrip figures={result.summary.figures} />}
      {stop === undefined || result.stop_kind === null ? (
        <ResultAlert result={result.result} headline={result.headline} action={action} />
      ) : (
        <RunStop
          stop={stop}
          kind={result.stop_kind}
          headline={result.headline}
          run={run}
          action={action}
          live={live}
        />
      )}
      {below}
      {prepared ? <FillingOnResult token={run.period} /> : null}
      {notes === null ? (
        result.warnings.map((warning) => <ThreePartMessage key={warning.what} message={warning} kind="warning" />)
      ) : (
        <>
          {notes.map((group) => (
            <OrderNoteList key={group.title} title={group.title} notes={group.notes} done={group.done} />
          ))}
        </>
      )}
      {result.technical_notes.map((note) => (
        <p key={note} className="flex items-center gap-2 text-sm text-muted-foreground">
          <InfoIcon className="size-4" aria-hidden />
          {note}
        </p>
      ))}
      {result.summary === null ? null : <SummaryDetails summary={result.summary} run={run} />}
    </>
  )
}

/** Wynik bez Zatrzymania: ikona wyniku, tytuł i akcja po nim. */
function ResultAlert({
  result,
  headline,
  action,
}: {
  result: LoggedOutcome["result"]
  headline: string
  action: React.ReactNode
}) {
  return (
    <Alert className="wejscie p-4" aria-label="Wynik">
      {result === "OK" ? <CircleCheckIcon className="text-success!" /> : <TriangleAlertIcon className="text-warning!" />}
      <AlertTitle className="text-base">{headline}</AlertTitle>
      {action === null ? null : <AlertAction className="top-3 right-3">{action}</AlertAction>}
    </Alert>
  )
}

/** Akcja po wyniku, którą proponuje serwer, z potwierdzeniem zapisu przy „Uruchom”. */
function useNextAction(run: RunInfo, action: NextAction, reminder: string) {
  const { start, rerun } = useRuns()
  const [confirming, setConfirming] = React.useState(false)

  return {
    button: (
      <NextActionButton
        action={action}
        run={run}
        onRun={() => setConfirming(true)}
        onRerun={() => rerun(run)}
      />
    ),
    dialog: (
      <ConfirmRunDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={run.title}
        period={run.period}
        reminder={reminder}
        confirmsReadiness={run.confirms_readiness}
        // „Uruchom” przy wyniku jest tylko po udanym podglądzie bez zapisu tego okresu.
        previewed
        onConfirm={() => start(rerunOf(run, "RUN"))}
      />
    ),
  }
}

const FILES_UNCHANGED = "Nic nie zapisano, Twoje pliki są bez zmian."

// Zatrzymanie według Rodzaju Zatrzymania, spójnie z plakietką w Historii: czerwony błąd tylko „do Maksa”.
const STOPS: Record<StopKind, { kind: "stop" | "to_fix" | "declined"; note: string | null }> = {
  for_tata: { kind: "to_fix", note: null },
  repeated: { kind: "to_fix", note: null },
  for_maks: { kind: "stop", note: "To nie wynika z Twoich plików." },
  declined: { kind: "declined", note: null },
}

type DadFileLook = "default" | "outline"

// Przycisk pliku taty przy Zatrzymaniu i po wyniku. Rejestr zleceń nosi nazwę z Komunikatów procesu (`register_name`),
// np. „INTERMAX” w Uporządkowaniu INTERMAX.
const DAD_FILES: Record<DadFile, (run: RunInfo, look: DadFileLook) => React.ReactNode> = {
  order_register: (run, look) => (
    <Button size="sm" variant={look} onClick={openOrderRegisterAndConfirm}>
      <FileSpreadsheetIcon data-icon="inline-start" />
      {`Otwórz ${run.register_name}`}
    </Button>
  ),
  collective_file: (run, look) => <OpenCollectiveFileButton period={run.period} size="sm" variant={look} />,
}

/** Zatrzymanie na karcie wyniku: obok akcji z serwera przycisk pliku taty, w którym jest poprawka. */
function RunStop({
  stop,
  kind,
  headline,
  run,
  action,
  live,
}: {
  stop: Message
  kind: StopKind
  headline: string
  run: RunInfo
  action: React.ReactNode
  live: LiveStop | null
}) {
  const look = STOPS[kind]
  const notes = [live?.filesUnchanged ? FILES_UNCHANGED : null, look.note].filter((note) => note !== null)
  const file = live?.opens == null ? null : DAD_FILES[live.opens]

  return (
    <StopMessage
      message={stop}
      kind={look.kind}
      title={headline}
      notes={notes}
      actions={
        <>
          {file === null ? null : file(run, live?.openFirst ? "default" : "outline")}
          {action}
        </>
      }
    />
  )
}

/** Jedyna akcja przy wyniku; którą pokazać, mówi serwer. */
function NextActionButton({
  action,
  run,
  onRun,
  onRerun,
}: {
  action: NextAction
  run: RunInfo
  onRun: () => void
  onRerun: () => void
}) {
  switch (action) {
    case "run":
      return (
        <Button size="sm" onClick={onRun}>
          <PlayIcon data-icon="inline-start" />
          Uruchom
        </Button>
      )
    case "rerun":
      return <RerunButton onRerun={onRerun} />
    case "open_collective_file":
      return DAD_FILES.collective_file(run, "default")
    case "open_worker_settlements_folder":
      return (
        <Button size="sm" onClick={() => openAndConfirm(run.period, { target: "worker_settlements_folder" })}>
          <FolderOpenIcon data-icon="inline-start" />
          Otwórz folder rozliczeń pracowników
        </Button>
      )
    case "open_order_register":
      return DAD_FILES.order_register(run, "default")
    default: {
      const unhandled: never = action

      return unhandled
    }
  }
}

function RerunButton({ onRerun }: { onRerun: () => void }) {
  return (
    <Button size="sm" variant="outline" onClick={onRerun}>
      <RotateCcwIcon data-icon="inline-start" />
      Uruchom ponownie
    </Button>
  )
}

/** Postęp Szablonów pracowników z projekcji: bieżący Wykonawca i „x z y”. */
function TemplateProgress({ progress }: { progress: RunProgress }) {
  const counted = `${progress.templates_completed} z ${progress.template_total}`

  return (
    <Progress
      value={(progress.templates_completed / progress.template_total) * 100}
      getAriaValueText={() => counted}
      aria-label="Szablony pracowników"
    >
      <ProgressLabel>
        Szablony pracowników
        {progress.current_worker === null ? null : (
          <span className="font-normal text-muted-foreground"> · {progress.current_worker}</span>
        )}
      </ProgressLabel>
      <ProgressValue>{() => counted}</ProgressValue>
    </Progress>
  )
}

/**
 * Krok Zapisywania procesu bez Szablonów pracowników: z liczeniem pasek „n z m” z bieżącym Wykonawcą, bez niego
 * jedno zdanie, co teraz trwa (np. „Zaloguj się w oknie efenix”).
 */
function StepProgress({ step }: { step: ProgressStep }) {
  if (step.total === 0) {
    return (
      <p className="wejscie flex items-center gap-2 text-sm font-medium" role="status" aria-label="Krok">
        <Spinner />
        {step.label}
      </p>
    )
  }

  const counted = `${step.done} z ${step.total}`

  return (
    <Progress value={(step.done / step.total) * 100} getAriaValueText={() => counted} aria-label={step.label}>
      <ProgressLabel>
        {step.label}
        {step.worker === null ? null : <span className="font-normal text-muted-foreground"> · {step.worker}</span>}
      </ProgressLabel>
      <ProgressValue>{() => counted}</ProgressValue>
    </Progress>
  )
}

/** Zlecenia Wyceny w efenix: wiersz Pliku zbiorczego, numer zlecenia, Wykonawca i co się stało (gdy zostały tacie); puste znika. */
function OrderNoteList({
  title,
  notes,
  done,
}: {
  title: string
  notes: ReadonlyArray<OrderNote>
  /** Zlecenia przekazane i rozliczone w efenix: tata nie ma nic do zrobienia, więc bez ostrzeżenia i bez zdania. */
  done: boolean
}) {
  if (notes.length === 0) {
    return null
  }

  return (
    <section className="flex flex-col gap-2" aria-label={title}>
      <h3 className="flex items-center gap-2 text-sm font-medium">
        {done ? (
          <CircleCheckIcon className="size-4 text-muted-foreground" aria-hidden />
        ) : (
          <TriangleAlertIcon className="size-4 text-warning" aria-hidden />
        )}
        {title} ({notes.length})
      </h3>
      <Table aria-label={title}>
        <TableBody>
          {notes.map((note) => (
            <TableRow key={note.row}>
              <TableCell className="w-24 text-muted-foreground tabular-nums">wiersz {note.row}</TableCell>
              <TableCell className="w-32 font-medium tabular-nums">{note.order ?? "bez numeru"}</TableCell>
              <TableCell className="w-40 text-muted-foreground">{note.worker}</TableCell>
              {/* Zlecenie przekazane i rozliczone nie ma zdania, ale pusta komórka trzyma kolumny w linii z Błędami. */}
              <TableCell className="whitespace-normal">{note.what}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </section>
  )
}

/** Szczegóły wyniku z serwera: kafelki liczb (np. Zlecenia na dzień), pliki okresu i Rozliczenia pracowników. */
function SummaryDetails({ summary, run }: { summary: RunSummary; run: RunInfo }) {
  // Po podglądzie bez zapisu pliki są tylko planem: jeszcze ich nie ma, więc nie ma czego otwierać.
  const open = run.mode === "DRY-RUN" ? undefined : (what: OpenedInPeriod) => openAndConfirm(run.period, what)

  return (
    <>
      {summary.counts === null ? null : (
        <CountTiles title={summary.counts.title} counts={summary.counts.counts} zeroWarns={summary.counts.zero_warns} />
      )}
      {summary.files.length === 0 ? null : <PeriodFiles files={summary.files} onOpen={open} />}
      {summary.intermax_copy == null ? null : (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <ArchiveIcon className="size-4 shrink-0" aria-hidden />
          <span className="min-w-0 truncate">Kopia sprzed zapisu: {summary.intermax_copy}</span>
        </p>
      )}
      {summary.worker_settlements === null ? null : open === undefined ? (
        <FilePlan settlements={summary.worker_settlements} />
      ) : (
        <WorkerSettlements settlements={summary.worker_settlements} onOpen={open} />
      )}
    </>
  )
}

const PERIOD_FILE_ICONS: Record<PeriodFile["kind"], React.ReactNode> = {
  internal_settlement: <FileTextIcon className="size-4 text-muted-foreground" aria-hidden />,
  collective_file: <FileSpreadsheetIcon className="size-4 text-muted-foreground" aria-hidden />,
}

function PeriodFiles({
  files,
  onOpen,
}: {
  files: ReadonlyArray<PeriodFile>
  onOpen: ((what: OpenedInPeriod) => void) | undefined
}) {
  return (
    <ul className="flex flex-wrap gap-x-6 gap-y-2 text-sm" aria-label="Pliki okresu">
      {files.map((file) => (
        <li key={file.name} className="flex items-center gap-2">
          {onOpen === undefined ? (
            <>
              {PERIOD_FILE_ICONS[file.kind]}
              {file.name}
            </>
          ) : (
            <Button variant="ghost" size="sm" className="-ml-2 text-sm font-normal" onClick={() => onOpen({ target: file.kind })}>
              {PERIOD_FILE_ICONS[file.kind]}
              {file.name}
            </Button>
          )}
        </li>
      ))}
    </ul>
  )
}

/** Plan plików po podglądzie: każdy Wykonawca, nazwa jego pliku i liczba zleceń; rozwinięty od razu. */
function FilePlan({ settlements }: { settlements: ReadonlyArray<WorkerSettlement> }) {
  return (
    <Disclosure label={`Plan plików (${settlements.length})`} defaultOpen>
      <Table aria-label="Plan plików">
        <TableBody>
          {settlements.map((settlement) => (
            <TableRow key={settlement.file}>
              <TableCell className="font-medium">{settlement.worker}</TableCell>
              <TableCell className="text-muted-foreground">{settlement.file}</TableCell>
              <TableCell className="text-right">
                <OrderCount settlement={settlement} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Disclosure>
  )
}

/** Zapisane Rozliczenia pracowników: Wykonawca, liczba zleceń i otwarcie jego pliku jednym kliknięciem. */
function WorkerSettlements({
  settlements,
  onOpen,
}: {
  settlements: ReadonlyArray<WorkerSettlement>
  onOpen: (what: OpenedInPeriod) => void
}) {
  const title = `Rozliczenia pracowników (${settlements.length})`

  return (
    <section className="flex flex-col gap-2" aria-label="Rozliczenia pracowników">
      <h3 className="text-sm font-medium">{title}</h3>
      <Table aria-label="Rozliczenia pracowników">
        <TableBody>
          {settlements.map((settlement) => (
            <TableRow key={settlement.file}>
              <TableCell className="font-medium">{settlement.worker}</TableCell>
              <TableCell>
                <OrderCount settlement={settlement} />
              </TableCell>
              <TableCell className="text-right">
                <Tooltip>
                  <TooltipTrigger
                    render={
                      <Button
                        variant="outline"
                        size="sm"
                        aria-label={`Otwórz ${settlement.file}`}
                        onClick={() => onOpen({ worker: settlement.worker })}
                      />
                    }
                  >
                    <FileSpreadsheetIcon data-icon="inline-start" />
                    Otwórz
                  </TooltipTrigger>
                  <TooltipContent>{settlement.file}</TooltipContent>
                </Tooltip>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </section>
  )
}

/** „1 zlecenie”, „2 zlecenia”, „5 zleceń”, „22 zlecenia”; pusty szablon ma oznaczenie, nie tylko zero. */
function OrderCount({ settlement }: { settlement: WorkerSettlement }) {
  if (settlement.empty) {
    return (
      <span className="inline-flex items-center gap-2 text-muted-foreground">
        <Badge variant="outline">pusty</Badge> 0 zleceń w tym tygodniu
      </span>
    )
  }

  return (
    <span className="tabular-nums">
      {settlement.orders} {plural(settlement.orders, { one: "zlecenie", few: "zlecenia", many: "zleceń" })}
    </span>
  )
}
