import { call, jsonRequest } from "@/api/client"
import type {
  DadNoteRequest,
  DadNoteText,
  DecisionAnswer,
  FillKind,
  GetCurrentRunResponse,
  GetIntermaxDaysResponse,
  GetIntermaxSetupResponse,
  GetNotificationsResponse,
  GetReportEnteringSetupResponse,
  GetReportsViewResponse,
  KeptCell,
  GetPeriodBoardResponse,
  GetQuantitiesToFillResponse,
  GetKindTableResponse,
  GetWithoutQuantityResponse,
  GetToolUpdateResponse,
  OpenRequest,
  RunEvent,
  RunInfo,
  RunOutcome,
  RunRequest,
  SendDadNoteResponse,
  Settings,
  ThemeChange,
  ViewTiming,
} from "@/api/generated"
import { operations } from "@/api/generated/operations.gen"
import { zRunEvent } from "@/api/generated/zod.gen"


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

/** Proces, którego Uruchomienie tata wybiera z okresem; Uporządkowanie INTERMAX i Wpisanie raportów mają własne karty. */
export type PeriodProcess = RunRequest["process"]

/** Tryb Wyceny w efenix (ADR 0027): bez Przekazania do akceptacji gotowych zleceń albo z nim. */
export type Pricing = NonNullable<RunInfo["pricing"]>

/** Karta „Uporządkuj INTERMAX” poza okresami. */
export type IntermaxSetup = GetIntermaxSetupResponse

/** Dni na karcie „Uporządkuj INTERMAX”, każdy z tym, czy jest uporządkowany. */
export type IntermaxDays = GetIntermaxDaysResponse

/** Karta „Wpisz raporty z maili” poza okresami (ADR 0028). */
export type ReportEnteringSetup = GetReportEnteringSetupResponse

/** Widok Raporty: wynik ostatniego kliknięcia „Wpisz raporty z maili” dla całego okna dni. */
export type ReportsView = GetReportsViewResponse

/** Wynik przywrócenia Kopii INTERMAX: przywrócona albo odmowa z Komunikatem (unia z kontraktu po `state`). */
export type IntermaxRestore = Awaited<ReturnType<typeof restoreIntermaxCopy>>

export type OpenTarget = OpenRequest["target"]

/** Powiadomienia od najnowszego i liczba nowych (kropka na dzwonku). */
export type Notifications = GetNotificationsResponse

/** Jedno Powiadomienie (unia z kontraktu po `kind`). */
export type Notification = Notifications["items"][number]

/** Uwaga taty po „Wyślij”: skrzynka ją przyjęła albo czeka w kolejce (unia z kontraktu). */
export type DadNoteState = SendDadNoteResponse

/** Widok bieżącego Uruchomienia procesu; jego `state` to stany UI (unia z kontraktu). */
export type RunView = GetCurrentRunResponse

/** Ostatnie Uruchomienie sprzed startu Centrum: karta z Logów, wynik z Historii bez Logów albo Urwane Uruchomienie (unia z kontraktu). */
export type PastRun = NonNullable<Extract<RunView, { state: "idle" }>["previous"]>

/** Akcja, którą Centrum proponuje po wyniku Uruchomienia. */
export type NextAction = RunOutcome["next_action"]

export function getSettings() {
  return call("getSettings")
}

/** Otwiera natywne okno wyboru na komputerze taty i zapamiętuje wybrany Rejestr zleceń. */
export function chooseOrderRegister() {
  return call("chooseRegister")
}

/** Otwiera w Excelu Rejestr zleceń, który tata wybrał w Ustawieniach; ścieżkę bierze serwer. */
export function openOrderRegister() {
  return call("openRegister")
}

/** Otwiera natywne okno wyboru folderu i zapamiętuje folder okresów. */
export function choosePeriodsDirectory() {
  return call("choosePeriodsDirectory")
}

export function changeTheme(theme: Theme) {
  return call("changeTheme", { body: { theme } })
}

export function getPeriodBoard() {
  return call("getPeriodBoard")
}

/** Serwer sam wylicza ścieżkę z folderu okresów; przeglądarka podaje tylko okres i rodzaj pliku. */
export function openPeriodPath(token: string, target: OpenTarget) {
  return call("openPeriodPath", { path: { token }, body: { target } })
}

/** Ilości do uzupełnienia okresu: serwer przelicza je przy każdym odczycie z zapisanego Pliku zbiorczego. */
export function getQuantitiesToFill(token: string) {
  return call("getQuantitiesToFill", { path: { token } })
}

/** Znacznik zapisu Pliku zbiorczego okresu: serwer odpowiada z `stat`, bez otwierania skoroszytu. */
export function getCollectiveFileVersion(token: string) {
  return call("getCollectiveFileVersion", { path: { token } })
}

/** Tabela jednego rodzaju Ilości do uzupełnienia, przeliczana przy każdym odczycie z zapisanego Pliku zbiorczego. */
export function getKindTable(token: string, kind: FillKind) {
  return call("getKindTable", { path: { token, kind } })
}

/** Wiersze bez ilości okresu dla okna „Uruchomić z zapisem?” Przebiegu rozliczeń, z zapisanego Pliku zbiorczego. */
export function getWithoutQuantity(token: string) {
  return call("getWithoutQuantity", { path: { token } })
}

/** Rozliczenie pracownika jednego Wykonawcy; ścieżkę wylicza serwer z Folderu okresu, przeglądarka podaje Wykonawcę. */
export function openWorkerSettlement(token: string, worker: string) {
  return call("openWorkerSettlement", { path: { token }, body: { worker } })
}

/** Co tata wybiera przed Uruchomieniem procesu: procesy, okresy z preselekcją, przypomnienie, brakujące ustawienia. */
export function getRunSetup() {
  return call("getRunSetup")
}

/** Start Uruchomienia procesu; gdy trwa już inne, serwer odmawia z bezpiecznym komunikatem. */
export function startRun(request: RunRequest) {
  return call("startRun", { body: request })
}

/** Karta „Uporządkuj INTERMAX”: przypomnienie, czego brakuje w Ustawieniach taty, i ostatnie Uporządkowanie z Logów. */
export function getIntermaxSetup() {
  return call("getIntermaxSetup")
}

/** Dziś, 6 dni wstecz i późniejsze Dni uporządkowane INTERMAX ze stanem; serwer czyta INTERMAX tylko po jego zmianie. */
export function getIntermaxDays() {
  return call("getIntermaxDays")
}

/** Start Uporządkowania INTERMAX z Rejestrem zleceń z Ustawień taty; gdy trwa inne Uruchomienie, serwer odmawia. */
export function startIntermax() {
  return call("startIntermax")
}

/** Karta „Wpisz raporty z maili”: przypomnienie, czego brakuje w Ustawieniach taty, i ostatnie Wpisanie raportów. */
export function getReportEnteringSetup() {
  return call("getReportEnteringSetup")
}

/** Start Wpisania raportów z INTERMAX z Ustawień taty; gdy trwa inne Uruchomienie, serwer odmawia. */
export function startReportEntering() {
  return call("startReportEntering")
}

/** Widok Raporty całego okna z pliku wyniku ostatniego kliknięcia; serwer nie czyta przy tym skrzynki. */
export function getReportsView() {
  return call("getReportsView")
}

/** „Zostaw moją” przy różnicy `cell`: serwer zapisuje decyzję poza INTERMAX i oddaje cały widok bez tej różnicy. */
export function keepManualValue(cell: KeptCell) {
  return call("keepManualValue", { body: cell })
}

/** Kopie INTERMAX w Konfiguracji, od najnowszej. */
export function getIntermaxCopies() {
  return call("getIntermaxCopies")
}

/** Przywrócenie Kopii INTERMAX `name`; gdy trwa Uruchomienie albo aktualizacja, serwer odmawia. */
export function restoreIntermaxCopy(name: string) {
  return call("restoreIntermaxCopy", { body: { name } })
}

/** Decyzja taty o niepełnym okresie dla Uruchomienia `runId`. */
export function decideRun(runId: string, answer: DecisionAnswer["answer"]) {
  return call("decideRun", { path: { run_id: runId }, body: { answer } })
}

/** Diagnoza Zatrzymania Uruchomienia `runId`: wyjaśnienie i sprawdzenia; serwer tylko czyta pliki taty. */
export function diagnoseRun(runId: string) {
  return call("diagnoseRun", { path: { run_id: runId } })
}

/** „Wyślij do Maksa”: serwer wysyła podgląd Zgłoszenia z ostatniej Diagnozy Uruchomienia `runId`. */
export function reportRun(runId: string) {
  return call("reportRun", { path: { run_id: runId } })
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
    const stream = new EventSource(operations.streamRunEvents.url)

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
  return call("getRunCard", { path: { run_id: runId } })
}

/** Historia Uruchomień procesu z obu plików metryk, z P50/P95 i rozkładem wyników; serwer czyta pliki przy każdym odczycie. */
export function getMetrics() {
  return call("getMetrics")
}

/** Konfiguracja tylko do odczytu: Wzorce, Wykonawcy i wersja narzędzia. */
export function getConfiguration() {
  return call("getConfiguration")
}

/** Aktualizacja narzędzia: serwer odpowiada od razu pierwszym krokiem i aktualizuje w tle; odmawia, gdy coś trwa. */
export function startToolUpdate() {
  return call("startToolUpdate")
}

/** Tożsamość Centrum; `instance` jest inny po każdym starcie, więc karta rozpozna po nim Centrum po aktualizacji. */
export function getHealth() {
  return call("getHealth")
}

/** Krok trwającej Aktualizacji narzędzia albo jej wynik od startu Centrum. */
export function getToolUpdate() {
  return call("getToolUpdate")
}

/** „Wyślij do Maksa” przy nieudanej Aktualizacji narzędzia: serwer wysyła podgląd Zgłoszenia z jej faktami. */
export function reportToolUpdate() {
  return call("reportToolUpdate")
}

/** Powiadomienia o Uwagach taty i Zgłoszeniach; serwer pyta skrzynkę najwyżej raz na 10 minut, bez sieci po cichu. */
export function getNotifications() {
  return call("getNotifications")
}

/** Tata zobaczył te Powiadomienia (ich `id`); serwer pamięta to także po ponownym starcie Centrum. */
export function markNotificationsRead(ids: ReadonlyArray<string>) {
  return call("markNotificationsRead", { body: { ids: [...ids] } })
}

/**
 * Uruchomienia z Centrum, do których tata może przypiąć Uwagę, od najnowszego. `selected` (Uruchomienie, z którego
 * tata otworzył okno) serwer dokłada na jego miejsce w kolejności, gdy jest starsze od ostatnich.
 */
export function getDadNoteRuns(selected: string | null) {
  return call("getDadNoteRuns", { query: { selected } })
}

/** Dokładnie to, co dostanie Maks z Uwagi taty: tytuł i treść issue składa serwer, przeglądarka je tylko pokazuje. */
export function draftDadNote(text: DadNoteText) {
  return call("draftDadNote", { body: text })
}

/** „Wyślij” Uwagi taty; odmawia (`CentrumError`) tylko wtedy, gdy Uwaga nie zapisała się w kolejce. */
export function sendDadNote(note: DadNoteRequest) {
  return call("sendDadNote", { body: note })
}

/** Serwer kończy pracę po odpowiedzi; odmawia (`CentrumError`), gdy zamknięcie jest teraz zablokowane. */
export function closeCentrum() {
  return call("closeCentrum")
}

/**
 * Pomiar gotowego widoku do dziennika Centrum, jawny wyjątek od `call` (opisany przy `call`). Porażka
 * wysyłki (także odmowa serwera) przechodzi po cichu: pomiar nigdy nie zmienia UI.
 */
export function recordViewTiming(timing: ViewTiming) {
  fetch(operations.recordViewTiming.url, { ...jsonRequest(operations.recordViewTiming.method, timing), keepalive: true }).catch(() => undefined)
}
