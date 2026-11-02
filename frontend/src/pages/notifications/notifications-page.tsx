import * as React from "react"
import { cn } from "cn"
import {
  CheckIcon,
  CircleArrowUpIcon,
  CircleCheckIcon,
  ClockIcon,
  EyeIcon,
  LifeBuoyIcon,
  MessageSquareTextIcon,
  ReceiptTextIcon,
  SendIcon,
  type LucideIcon,
} from "lucide-react"

import type { Notification } from "@/api/centrum"
import { LoadFailure } from "@/components/load-failure"
import { PageHeader } from "@/components/page-header"
import { SendProblem, type SendCause } from "@/components/send-problem"
import { ThreePartMessage } from "@/components/three-part-message"
import { ToolUpdateButton, ToolUpdateStatus } from "@/components/tool-update"
import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useContentEntrance } from "@/lib/content-entrance"
import { ago } from "@/lib/format"
import { useNotifications } from "@/lib/notifications"
import { RunCardLink } from "@/pages/runs/run-card-sheet"

type Kind = Notification["kind"]

type Release = Extract<Notification, { kind: "nowa_wersja" }>

type Pricing = Extract<Notification, { kind: "wycena_w_efenix" }>

type Case = Exclude<Notification, Release | Pricing>

type CaseState = Case["state"]

// Kolor rodzaju z palety motywu: zielony nowa wersja, niebieski Uwaga, pomarańczowy Zgłoszenie, żółty Wycena w efenix.
const KINDS: Record<Kind, { tag: string; color: string; icon: LucideIcon }> = {
  nowa_wersja: { tag: "Nowa wersja", color: "var(--chart-3)", icon: CircleArrowUpIcon },
  uwaga: { tag: "Uwaga", color: "var(--chart-1)", icon: MessageSquareTextIcon },
  zgloszenie: { tag: "Zgłoszenie", color: "var(--chart-2)", icon: LifeBuoyIcon },
  wycena_w_efenix: { tag: "Wycena w efenix", color: "var(--chart-4)", icon: ReceiptTextIcon },
}

// Liczby zleceń w Powiadomieniu o Wycenie w efenix, z etykietami kafelków karty Uruchomienia.
const PRICED: ReadonlyArray<{ key: keyof NonNullable<Pricing["orders"]>; label: string }> = [
  { key: "ready", label: "Gotowe do przekazania" },
  { key: "errors", label: "Błędy zleceń" },
  { key: "warnings", label: "Ostrzeżenia Emmetta" },
]

const SOLVED: Record<Release["solved"][number]["kind"], string> = { uwaga: "Uwaga", zgloszenie: "Zgłoszenie" }

// Stany, przy których tata musi skontaktować się z Maksem, mówi wspólny `SendProblem`.
const PROBLEMS = { czeka_na_token: "key", odrzucona: "rejected" } as const satisfies Partial<Record<CaseState, SendCause>>

type ProblemState = keyof typeof PROBLEMS

function isProblem(state: CaseState): state is ProblemState {
  return state in PROBLEMS
}

// Uwaga jest rodzaju żeńskiego, Zgłoszenie nijakiego.
const STATES: Record<
  Exclude<CaseState, ProblemState>,
  { text: Record<Case["kind"], string>; icon: LucideIcon; tone: string }
> = {
  wyslana: {
    text: { uwaga: "Wysłana do Maksa.", zgloszenie: "Wysłane do Maksa." },
    icon: SendIcon,
    tone: "text-muted-foreground",
  },
  czeka_na_internet: {
    text: { uwaga: "Wyślę do Maksa, gdy będzie internet.", zgloszenie: "Wyślę do Maksa, gdy będzie internet." },
    icon: ClockIcon,
    tone: "text-muted-foreground",
  },
  rozwiazana: {
    text: { uwaga: "Rozwiązana. Będzie w następnej wersji.", zgloszenie: "Rozwiązane. Będzie w następnej wersji." },
    icon: CircleCheckIcon,
    tone: "text-success",
  },
  przeczytana: {
    text: { uwaga: "Maks przeczytał.", zgloszenie: "Maks przeczytał." },
    icon: EyeIcon,
    tone: "text-muted-foreground",
  },
}

/**
 * Widok Powiadomienia, otwierany dzwonkiem. Wejście oznacza wszystkie jako przeczytane, więc kropka na dzwonku
 * gaśnie od razu; wiersze, które były nowe, zachowują kropkę i jasne tło do wyjścia z widoku. Nowa wersja, do której
 * Centrum proponuje aktualizację, stoi w osobnej karcie nad listą; po aktualizacji wraca do listy jako historia.
 * Komunikat o pliku stanu, którego Centrum nie może zapisać, stoi nad wszystkim i znika po udanym zapisie.
 */
export function NotificationsPage() {
  const { notifications, markRead, reload } = useNotifications()
  const entrance = useContentEntrance(notifications.state === "loading")
  const data = notifications.state === "ready" ? notifications.data : null
  const unread = React.useMemo(() => data?.items.filter((item) => item.unread).map((item) => item.id) ?? [], [data])

  // Nowe w tej wizycie: każde Powiadomienie, które przyszło nieprzeczytane, zostaje oznaczone do wyjścia z widoku.
  const [visit, setVisit] = React.useState<{ unread: ReadonlyArray<string>; fresh: ReadonlySet<string> }>({
    unread: [],
    fresh: new Set(),
  })

  if (visit.unread !== unread) {
    setVisit({ unread, fresh: new Set([...visit.fresh, ...unread]) })
  }

  React.useEffect(() => {
    if (unread.length > 0) {
      markRead(unread)
    }
  }, [unread, markRead])

  const fresh = visit.fresh
  const pinned = data?.items.find((item): item is Release => item.kind === "nowa_wersja" && item.update_offered)
  const listed = data?.items.filter((item) => item !== pinned) ?? []

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6">
      <PageHeader title="Powiadomienia" />
      {notifications.state === "loading" ? <NotificationsSkeleton /> : null}
      {notifications.state === "failed" ? (
        <LoadFailure what="Powiadomień" message={notifications.message} reload={reload} />
      ) : null}
      {data?.message ? <ThreePartMessage message={data.message} kind="notice" /> : null}
      {pinned === undefined ? null : (
        <Card className={cn(entrance, "gap-0 p-0")} role="region" aria-label={title(pinned)}>
          <Row notification={pinned} fresh={fresh.has(pinned.id)} />
        </Card>
      )}
      {data === null || (pinned !== undefined && listed.length === 0) ? null : (
        <Card className={cn(entrance, "gap-0 p-0")} aria-label="Powiadomienia" role="list">
          {listed.length === 0 ? (
            <p className="px-5 py-4 text-sm text-muted-foreground">
              Tu zobaczysz wynik Wyceny w efenix i to, co Maks zrobił z Twoimi Uwagami i Zgłoszeniami.
            </p>
          ) : (
            listed.map((item) => <Row key={item.id} notification={item} fresh={fresh.has(item.id)} listed />)
          )}
        </Card>
      )}
    </div>
  )
}

function title(notification: Notification): string {
  switch (notification.kind) {
    case "nowa_wersja":
      return `Nowa wersja ${notification.version}`
    case "uwaga":
      return notification.title
    case "zgloszenie":
      return notification.what
    case "wycena_w_efenix":
      return notification.headline
  }
}

function Row({ notification, fresh, listed }: { notification: Notification; fresh: boolean; listed?: boolean }) {
  const kind = KINDS[notification.kind]

  return (
    <article
      role={listed ? "listitem" : undefined}
      aria-label={notification.kind === "nowa_wersja" ? title(notification) : `${kind.tag}: ${title(notification)}`}
      data-fresh={fresh}
      className="grid grid-cols-[auto_1fr_auto] items-start gap-x-4 border-t px-5 py-4 first:border-t-0 data-[fresh=true]:bg-muted/40"
    >
      <span
        className="flex size-9 items-center justify-center rounded-full [&_svg]:size-4"
        style={{ color: kind.color, backgroundColor: `color-mix(in oklab, ${kind.color} 12%, transparent)` }}
        aria-hidden
      >
        <kind.icon />
      </span>
      <div className="flex min-w-0 flex-col gap-1">
        <h2 className="text-sm font-medium text-pretty break-words">
          {title(notification)}
          {fresh ? (
            <span
              className="ml-2 inline-block size-1.5 rounded-full align-middle"
              style={{ backgroundColor: "var(--chart-1)" }}
              aria-label="nowe"
            />
          ) : null}
        </h2>
        <Body notification={notification} />
      </div>
      <div className="flex flex-col items-end gap-1.5 pt-0.5">
        <span className="inline-flex h-5 items-center gap-1.5 rounded-full border px-2 text-xs font-medium whitespace-nowrap">
          <span className="size-1.5 rounded-full" style={{ backgroundColor: kind.color }} aria-hidden />
          {kind.tag}
        </span>
        <time className="text-xs whitespace-nowrap text-muted-foreground tabular-nums" dateTime={notification.at}>
          {ago(notification.at)}
        </time>
      </div>
    </article>
  )
}

function Body({ notification }: { notification: Notification }) {
  switch (notification.kind) {
    case "nowa_wersja":
      return <ReleaseBody release={notification} />
    case "wycena_w_efenix":
      return <PricingBody pricing={notification} />
    default:
      return <CaseState notification={notification} />
  }
}

/**
 * Wynik Wyceny w efenix, która skończyła się, gdy tata patrzył na okno efenix albo odszedł od komputera: okres, liczby
 * zleceń, „Co się stało” Zatrzymania i karta Uruchomienia z błędami i ostrzeżeniami.
 */
function PricingBody({ pricing }: { pricing: Pricing }) {
  const orders = pricing.orders

  return (
    <div className="flex flex-col items-start gap-3">
      <p className="text-sm text-muted-foreground tabular-nums">Okres {pricing.period}</p>
      {orders === null ? null : (
        <dl aria-label="Zlecenia" className="flex flex-wrap gap-x-5 gap-y-1 text-sm">
          {PRICED.map(({ key, label }) => (
            <div key={key} className="flex items-baseline gap-1.5">
              <dt className="text-muted-foreground">{label}</dt>
              <dd className="font-medium tabular-nums">{orders[key]}</dd>
            </div>
          ))}
        </dl>
      )}
      {pricing.stopped === null ? null : <p className="text-sm text-pretty break-words">{pricing.stopped}</p>}
      <RunCardLink runId={pricing.run_id} title={KINDS.wycena_w_efenix.tag} period={pricing.period} />
    </div>
  )
}

function CaseState({ notification }: { notification: Case }) {
  const shown = notification.state

  if (isProblem(shown)) {
    return <SendProblem cause={PROBLEMS[shown]} kind={notification.kind} className="gap-1.5" iconClassName="size-3.5" />
  }

  const state = STATES[shown]

  return (
    <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
      <state.icon className={`size-3.5 shrink-0 ${state.tone}`} aria-hidden />
      {state.text[notification.kind]}
    </p>
  )
}

/**
 * Notka „Co nowego” (zdanie wstępu i punkty jeden pod drugim, jak okienko aktualizacji), sprawy taty, które Wydanie
 * rozwiązuje, i przycisk aktualizacji, gdy Centrum go proponuje (`update_offered`, ta sama reguła co w Konfiguracji)
 * ze stanem aktualizacji pod nim.
 */
function ReleaseBody({ release }: { release: Release }) {
  return (
    <div className="flex flex-col gap-3">
      <section aria-label="Co nowego" className="mt-1 flex flex-col gap-2 text-sm">
        <h3 className="font-medium">Co nowego</h3>
        {release.intro === "" ? null : (
          <p className="text-pretty whitespace-pre-line text-muted-foreground">{release.intro}</p>
        )}
        {release.points.length === 0 ? null : (
          <ul className="flex list-disc flex-col gap-2 pl-5 text-muted-foreground marker:text-muted-foreground/60">
            {release.points.map((point, index) => (
              // Dwa punkty mogą mieć ten sam tekst, a lista z serwera się nie zmienia w trakcie wizyty.
              <li key={index} className="pl-1 text-pretty break-words">
                {point}
              </li>
            ))}
          </ul>
        )}
      </section>
      {release.solved.length === 0 ? null : (
        <ul aria-label="Rozwiązane sprawy" className="flex flex-col gap-1 text-sm">
          {release.solved.map((item, index) => (
            // Dwie Uwagi mogą mieć ten sam tytuł, a lista z serwera się nie zmienia w trakcie wizyty.
            <li key={index} className="flex items-start gap-2 break-words">
              <CheckIcon className="mt-0.5 size-3.5 shrink-0 text-success" aria-hidden />
              {`${SOLVED[item.kind]}: ${item.title}`}
            </li>
          ))}
        </ul>
      )}
      {release.update_offered ? (
        <div className="flex flex-col items-start gap-3">
          <ToolUpdateButton primary size="sm" />
          <ToolUpdateStatus />
        </div>
      ) : null}
    </div>
  )
}

function NotificationsSkeleton() {
  return (
    <Card className="gap-0 p-0" aria-busy="true">
      {[0, 1, 2].map((row) => (
        <div key={row} className="flex items-center gap-4 border-t px-5 py-4 first:border-t-0">
          <Skeleton className="size-9 rounded-full" />
          <div className="flex flex-1 flex-col gap-2">
            <Skeleton className="h-4 w-1/2" />
            <Skeleton className="h-3.5 w-1/3" />
          </div>
        </div>
      ))}
    </Card>
  )
}
