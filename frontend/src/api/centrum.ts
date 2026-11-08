import { call } from "@/api/client"
import type {
  DadNoteRequest,
  DadNoteText,
  DecisionAnswer,
  FillKind,
  GetCurrentRunResponse,
  GetIntermaxDaysResponse,
  GetIntermaxSetupResponse,
  IntermaxRestoreRequest,
  GetNotificationsResponse,
  GetPeriodBoardResponse,
  GetQuantitiesToFillResponse,
  GetKindTableResponse,
  GetWithoutQuantityResponse,
  GetToolUpdateResponse,
  NotificationsRead,
  OpenRequest,
  WorkerSettlementRequest,
  RunEvent,
  RunInfo,
  RunOutcome,
  RunRequest,
  SendDadNoteResponse,
  Settings,
  ThemeChange,
  ViewTiming,
} from "@/api/generated"
import {
  zChangeThemeResponse,
  zCloseCentrumResponse,
  zChoosePeriodsDirectoryResponse,
  zChooseRegisterResponse,
  zDecideRunResponse,
  zDiagnoseRunResponse,
  zDraftDadNoteResponse,
  zGetDadNoteRunsResponse,
  zGetConfigurationResponse,
  zGetHealthResponse,
  zGetIntermaxCopiesResponse,
  zGetIntermaxDaysResponse,
  zGetIntermaxSetupResponse,
  zGetMetricsResponse,
  zGetNotificationsResponse,
  zGetPeriodBoardResponse,
  zGetQuantitiesToFillResponse,
  zGetCollectiveFileVersionResponse,
  zGetKindTableResponse,
  zGetRunCardResponse,
  zGetWithoutQuantityResponse,
  zGetRunSetupResponse,
  zGetSettingsResponse,
  zGetToolUpdateResponse,
  zMarkNotificationsReadResponse,
  zOpenPeriodPathResponse,
  zOpenRegisterResponse,
  zOpenWorkerSettlementResponse,
  zReportRunResponse,
  zReportToolUpdateResponse,
  zRestoreIntermaxCopyResponse,
  zRunEvent,
  zSendDadNoteResponse,
  zStartIntermaxResponse,
  zStartRunResponse,
  zStartToolUpdateResponse,
} from "@/api/generated/zod.gen"

export type {
  Choice,
  CollectiveFileRead,
  Configuration,
  Count,
  DadNoteDraft,
  DadNoteRequest,
  Decision,
  DecisionAnswer,
  Diagnosis,
  DescriptionColumn,
  DiagnosisCheck,
  Figure,
  FillKind,
  IntermaxCopy,
  KindToFill,
  QuantitiesToFillReady,
  KindTableCell,
  KindTableRow,
  PriceListItem,
  LoggedOutcome,
  Message,
  Metrics,
  OrderNote,
  OrderNotes,
  Percentiles,
  OpenRequest,
  PeriodChoice,
  PeriodRow,
  PeriodFile,
  PhaseProgress,
  PinnableRun,
  ProcessRun,
  ProcessStep,
  FillStep,
  ProcessSetup,
  Progress,
  ProgressStep,
  ReportDraft,
  ResultCounts,
  RunEvent,
  RunInfo,
  RunInterrupted,
  RunMode,
  RunOutcome,
  RunRequest,
  RunRestored,
  RunSummary,
  Settings,
  TemplateProblem,
  WorkerSettlement,
  WorkerSettlementRequest,
} from "@/api/generated"

export type PeriodBoard = GetPeriodBoardResponse

/** Ilości do uzupełnienia okresu z zapisanego Pliku zbiorczego albo Komunikat o pliku (unia z kontraktu po `state`). */
export type QuantitiesToFill = GetQuantitiesToFillResponse

/** Wiersze jednego rodzaju Ilości do uzupełnienia z komórkami N:AP albo Komunikat o pliku (unia z kontraktu po `state`). */
export type KindTable = GetKindTableResponse

/** Wiersze bez ilości okresu dla okna „Uruchomić z zapisem?” albo „unread”, gdy Pliku zbiorczego nie odczytano. */
export type WithoutQuantity = GetWithoutQuantityResponse

/** Aktualizacja narzędzia: krok albo wynik (unia z kontraktu). */
export type ToolUpdate = GetToolUpdateResponse

export type PathSetting = Settings["order_register"]

export type Theme = ThemeChange["theme"]

export type Process = RunInfo["process"]

/** Proces, którego Uruchomienie tata wybiera z okresem; Uporządkowanie INTERMAX ma własną kartę. */
export type PeriodProcess = RunRequest["process"]

/** Tryb Wyceny w efenix (ADR 0027): bez Przekazania do akceptacji gotowych zleceń albo z nim. */
export type Pricing = NonNullable<RunInfo["pricing"]>

/** Karta „Uporządkuj INTERMAX” poza okresami. */
export type IntermaxSetup = GetIntermaxSetupResponse

/** Dni na karcie „Uporządkuj INTERMAX”, każdy z tym, czy jest uporządkowany. */
export type IntermaxDays = GetIntermaxDaysResponse

/** Wynik przywrócenia Kopii INTERMAX: przywrócona albo odmowa z Komunikatem (unia z kontraktu po `state`). */
export type IntermaxRestore = Awaited<ReturnType<typeof restoreIntermaxCopy>>

export type OpenTarget = OpenRequest["target"]

/** Powiadomienia od najnowszego i liczba nowych (kropka na dzwonku). */
export type Notifications = GetNotificationsResponse

/** Jedno Powiadomienie: Uwaga taty albo Zgłoszenie (unia z kontraktu po `kind`). */
export type Notification = Notifications["items"][number]

/** Uwaga taty po „Wyślij”: skrzynka ją przyjęła albo czeka w kolejce (unia z kontraktu). */
export type DadNoteState = SendDadNoteResponse

/** Widok bieżącego Uruchomienia procesu; jego `state` to stany UI (unia z kontraktu). */
export type RunView = GetCurrentRunResponse

/** Ostatnie Uruchomienie sprzed startu Centrum: karta z Logów, wynik z Historii bez Logów albo Urwane Uruchomienie (unia z kontraktu). */
export type PastRun = NonNullable<Extract<RunView, { state: "idle" }>["previous"]>

/** Akcja, którą Centrum proponuje po wyniku Uruchomienia. */
export type NextAction = RunOutcome["next_action"]

function send(
  method: "POST" | "PUT",
  body?:
    | OpenRequest
    | WorkerSettlementRequest
    | ThemeChange
    | RunRequest
    | DecisionAnswer
    | ViewTiming
    | DadNoteText
    | DadNoteRequest
    | NotificationsRead
    | IntermaxRestoreRequest
): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  }
}

export function getSettings() {
  return call(zGetSettingsResponse, "getSettings", "/api/settings")
}

/** Otwiera natywne okno wyboru na komputerze taty i zapamiętuje wybrany Rejestr zleceń. */
export function chooseOrderRegister() {
  return call(zChooseRegisterResponse, "chooseRegister", "/api/settings/register/choose", send("POST"))
}

/** Otwiera w Excelu Rejestr zleceń, który tata wybrał w Ustawieniach; ścieżkę bierze serwer. */
export function openOrderRegister() {
  return call(zOpenRegisterResponse, "openRegister", "/api/settings/register/open", send("POST"))
}

/** Otwiera natywne okno wyboru folderu i zapamiętuje folder okresów. */
export function choosePeriodsDirectory() {
  return call(
    zChoosePeriodsDirectoryResponse,
    "choosePeriodsDirectory",
    "/api/settings/periods-directory/choose",
    send("POST")
  )
}

export function changeTheme(theme: Theme) {
  return call(zChangeThemeResponse, "changeTheme", "/api/settings/theme", send("PUT", { theme }))
}

export function getPeriodBoard() {
  return call(zGetPeriodBoardResponse, "getPeriodBoard", "/api/periods")
}

/** Serwer sam wylicza ścieżkę z folderu okresów; przeglądarka podaje tylko okres i rodzaj pliku. */
export function openPeriodPath(token: string, target: OpenTarget) {
  return call(
    zOpenPeriodPathResponse,
    "openPeriodPath",
    `/api/periods/${encodeURIComponent(token)}/open`,
    send("POST", { target })
  )
}

/** Ilości do uzupełnienia okresu: serwer przelicza je przy każdym odczycie z zapisanego Pliku zbiorczego. */
export function getQuantitiesToFill(token: string) {
  return call(
    zGetQuantitiesToFillResponse,
    "getQuantitiesToFill",
    `/api/periods/${encodeURIComponent(token)}/quantities-to-fill`
  )
}

/** Znacznik zapisu Pliku zbiorczego okresu: serwer odpowiada z `stat`, bez otwierania skoroszytu. */
export function getCollectiveFileVersion(token: string) {
  return call(
    zGetCollectiveFileVersionResponse,
    "getCollectiveFileVersion",
    `/api/periods/${encodeURIComponent(token)}/collective-file-version`
  )
}

/** Tabela jednego rodzaju Ilości do uzupełnienia, przeliczana przy każdym odczycie z zapisanego Pliku zbiorczego. */
export function getKindTable(token: string, kind: FillKind) {
  return call(zGetKindTableResponse, "getKindTable", `/api/periods/${encodeURIComponent(token)}/quantities-to-fill/${kind}`)
}

/** Wiersze bez ilości okresu dla okna „Uruchomić z zapisem?” Przebiegu rozliczeń, z zapisanego Pliku zbiorczego. */
export function getWithoutQuantity(token: string) {
  return call(
    zGetWithoutQuantityResponse,
    "getWithoutQuantity",
    `/api/periods/${encodeURIComponent(token)}/without-quantity`
  )
}

/** Rozliczenie pracownika jednego Wykonawcy; ścieżkę wylicza serwer z Folderu okresu, przeglądarka podaje Wykonawcę. */
export function openWorkerSettlement(token: string, worker: string) {
  return call(
    zOpenWorkerSettlementResponse,
    "openWorkerSettlement",
    `/api/periods/${encodeURIComponent(token)}/worker-settlements/open`,
    send("POST", { worker })
  )
}

/** Co tata wybiera przed Uruchomieniem procesu: procesy, okresy z preselekcją, przypomnienie, brakujące ustawienia. */
export function getRunSetup() {
  return call(zGetRunSetupResponse, "getRunSetup", "/api/runs/setup")
}

/** Start Uruchomienia procesu; gdy trwa już inne, serwer odmawia z bezpiecznym komunikatem. */
export function startRun(request: RunRequest) {
  return call(zStartRunResponse, "startRun", "/api/runs", send("POST", request))
}

/** Karta „Uporządkuj INTERMAX”: przypomnienie, czego brakuje w Ustawieniach taty, i ostatnie Uporządkowanie z Logów. */
export function getIntermaxSetup() {
  return call(zGetIntermaxSetupResponse, "getIntermaxSetup", "/api/intermax")
}

/** Dziś, 6 dni wstecz i późniejsze Dni uporządkowane INTERMAX ze stanem; serwer czyta INTERMAX tylko po jego zmianie. */
export function getIntermaxDays() {
  return call(zGetIntermaxDaysResponse, "getIntermaxDays", "/api/intermax/days")
}

/** Start Uporządkowania INTERMAX z Rejestrem zleceń z Ustawień taty; gdy trwa inne Uruchomienie, serwer odmawia. */
export function startIntermax() {
  return call(zStartIntermaxResponse, "startIntermax", "/api/intermax/run", send("POST"))
}

/** Kopie INTERMAX w Konfiguracji, od najnowszej. */
export function getIntermaxCopies() {
  return call(zGetIntermaxCopiesResponse, "getIntermaxCopies", "/api/intermax/copies")
}

/** Przywrócenie Kopii INTERMAX `name`; gdy trwa Uruchomienie albo aktualizacja, serwer odmawia. */
export function restoreIntermaxCopy(name: string) {
  return call(
    zRestoreIntermaxCopyResponse,
    "restoreIntermaxCopy",
    "/api/intermax/copies/restore",
    send("POST", { name })
  )
}

/** Decyzja taty o niepełnym okresie dla Uruchomienia `runId`. */
export function decideRun(runId: string, answer: DecisionAnswer["answer"]) {
  return call(
    zDecideRunResponse,
    "decideRun",
    `/api/runs/${encodeURIComponent(runId)}/decision`,
    send("POST", { answer })
  )
}

/** Diagnoza Zatrzymania Uruchomienia `runId`: wyjaśnienie i sprawdzenia; serwer tylko czyta pliki taty. */
export function diagnoseRun(runId: string) {
  return call(zDiagnoseRunResponse, "diagnoseRun", `/api/runs/${encodeURIComponent(runId)}/diagnosis`, send("POST"))
}

/** „Wyślij do Maksa”: serwer wysyła podgląd Zgłoszenia z ostatniej Diagnozy Uruchomienia `runId`. */
export function reportRun(runId: string) {
  return call(zReportRunResponse, "reportRun", `/api/runs/${encodeURIComponent(runId)}/report`, send("POST"))
}

/**
 * Strumień SSE Uruchomień procesu, otwarty tylko w widocznej karcie. Przeglądarka trzyma najwyżej 6 połączeń
 * z Centrum naraz, wspólnie dla wszystkich kart, a każde kliknięcie skrótu otwiera nową kartę: strumienie kart
 * w tle zajęłyby wszystkie połączenia i każde zapytanie Centrum czekałoby bez końca. Karta w tle oddaje więc
 * połączenie, a po powrocie łączy się od nowa. Po połączeniu najpierw przychodzi bieżący widok, potem każda
 * zmiana; po zerwaniu przeglądarka sama łączy się ponownie i znowu dostaje bieżący widok. Każde zdarzenie jest
 * parsowane schematem z kontraktu; zdarzenie, którego nie da się sparsować, dostaje `onUnreadable`.
 */
export function watchRunEvents(
  onEvent: (event: RunEvent) => void,
  onConnection: (connected: boolean) => void,
  onUnreadable: () => void
): () => void {
  let source: EventSource | null = null

  const connect = () => {
    const stream = new EventSource("/api/runs/events")

    stream.addEventListener("open", () => onConnection(true))
    stream.addEventListener("error", () => onConnection(false))
    stream.addEventListener("message", (message: MessageEvent<string>) => {
      let data: unknown

      try {
        data = JSON.parse(message.data)
      } catch {
        onUnreadable()

        return
      }

      const parsed = zRunEvent.safeParse(data)

      if (parsed.success) {
        onEvent(parsed.data)
      } else {
        onUnreadable()
      }
    })

    return stream
  }

  const followVisibility = () => {
    if (document.visibilityState === "visible") {
      source ??= connect()
    } else {
      source?.close()
      source = null
    }
  }

  followVisibility()
  document.addEventListener("visibilitychange", followVisibility)

  return () => {
    document.removeEventListener("visibilitychange", followVisibility)
    source?.close()
  }
}

/** Karta Uruchomienia `runId` z jego Logów Uruchomienia (wiersz Historii); `missing`, gdy karty nie ma. */
export function getRunCard(runId: string) {
  return call(zGetRunCardResponse, "getRunCard", `/api/runs/${encodeURIComponent(runId)}/card`)
}

/** Historia Uruchomień procesu z obu plików metryk, z P50/P95 i rozkładem wyników; serwer czyta pliki przy każdym odczycie. */
export function getMetrics() {
  return call(zGetMetricsResponse, "getMetrics", "/api/metrics")
}

/** Konfiguracja tylko do odczytu: Wzorce, Wykonawcy i wersja narzędzia. */
export function getConfiguration() {
  return call(zGetConfigurationResponse, "getConfiguration", "/api/configuration")
}

/** Aktualizacja narzędzia: serwer odpowiada od razu pierwszym krokiem i aktualizuje w tle; odmawia, gdy coś trwa. */
export function startToolUpdate() {
  return call(zStartToolUpdateResponse, "startToolUpdate", "/api/tool-update", send("POST"))
}

/** Tożsamość Centrum; `instance` jest inny po każdym starcie, więc karta rozpozna po nim Centrum po aktualizacji. */
export function getHealth() {
  return call(zGetHealthResponse, "getHealth", "/api/health")
}

/** Krok trwającej Aktualizacji narzędzia albo jej wynik od startu Centrum. */
export function getToolUpdate() {
  return call(zGetToolUpdateResponse, "getToolUpdate", "/api/tool-update")
}

/** „Wyślij do Maksa” przy nieudanej Aktualizacji narzędzia: serwer wysyła podgląd Zgłoszenia z jej faktami. */
export function reportToolUpdate() {
  return call(zReportToolUpdateResponse, "reportToolUpdate", "/api/tool-update/report", send("POST"))
}

/** Powiadomienia o Uwagach taty i Zgłoszeniach; serwer pyta skrzynkę najwyżej raz na 10 minut, bez sieci po cichu. */
export function getNotifications() {
  return call(zGetNotificationsResponse, "getNotifications", "/api/notifications")
}

/** Tata zobaczył te Powiadomienia (ich `id`); serwer pamięta to także po ponownym starcie Centrum. */
export function markNotificationsRead(ids: ReadonlyArray<string>) {
  return call(
    zMarkNotificationsReadResponse,
    "markNotificationsRead",
    "/api/notifications/read",
    send("POST", { ids: [...ids] })
  )
}

/**
 * Uruchomienia z Centrum, do których tata może przypiąć Uwagę, od najnowszego. `selected` (Uruchomienie, z którego
 * tata otworzył okno) serwer dokłada na jego miejsce w kolejności, gdy jest starsze od ostatnich.
 */
export function getDadNoteRuns(selected: string | null) {
  const query = selected === null ? "" : `?${new URLSearchParams({ selected }).toString()}`

  return call(zGetDadNoteRunsResponse, "getDadNoteRuns", `/api/dad-notes/runs${query}`)
}

/** Dokładnie to, co dostanie Maks z Uwagi taty: tytuł i treść issue składa serwer, przeglądarka je tylko pokazuje. */
export function draftDadNote(text: DadNoteText) {
  return call(zDraftDadNoteResponse, "draftDadNote", "/api/dad-notes/draft", send("POST", text))
}

/** „Wyślij” Uwagi taty; odmawia (`CentrumError`) tylko wtedy, gdy Uwaga nie zapisała się w kolejce. */
export function sendDadNote(note: DadNoteRequest) {
  return call(zSendDadNoteResponse, "sendDadNote", "/api/dad-notes", send("POST", note))
}

/** Serwer kończy pracę po odpowiedzi; odmawia (`CentrumError`), gdy zamknięcie jest teraz zablokowane. */
export function closeCentrum() {
  return call(zCloseCentrumResponse, "closeCentrum", "/api/shutdown", send("POST"))
}

/**
 * Pomiar gotowego widoku do dziennika Centrum, jawny wyjątek od `call` (opisany przy `call`). Porażka
 * wysyłki (także odmowa serwera) przechodzi po cichu: pomiar nigdy nie zmienia UI.
 */
export function recordViewTiming(timing: ViewTiming) {
  fetch("/api/view-timings", { ...send("POST", timing), keepalive: true }).catch(() => undefined)
}
