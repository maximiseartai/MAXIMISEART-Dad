import { CircleCheckIcon, CircleDashedIcon, CircleHelpIcon, CircleXIcon, FilePenLineIcon, MinusIcon, UserXIcon } from "lucide-react"

import type { MailingRow } from "@/api/generated"
import { Badge } from "@/components/ui/badge"
import { Spinner } from "@/components/ui/spinner"
import { settingsHref } from "@/lib/address"
import { dateTime } from "@/lib/format"
import { WORKERS_SECTION } from "@/pages/settings/workers-section"

/** Stan wiersza na ekranie: stan Rozliczenia pracownika z serwera albo „wysyłam”, dopóki jego mail jest w drodze. */
export type ShownState = MailingRow["state"] | { state: "sending" }

/**
 * Odznaka stanu Rozliczenia pracownika w Wysyłce, zawsze z ikoną i słowami, nigdy samym kolorem. Każdy stan to nowy
 * element (`key` w wierszu), więc zmiana w trakcie wysyłki wchodzi przejściem `podmiana`.
 */
export function MailStateBadge({ state }: { state: ShownState }) {
  switch (state.state) {
    case "sending":
      return (
        <Badge variant="outline">
          <Spinner data-icon="inline-start" />
          Wysyłam…
        </Badge>
      )
    case "to_send":
      return (
        <Badge variant="outline">
          <CircleDashedIcon data-icon="inline-start" />
          Do wysłania
        </Badge>
      )
    case "sent":
      return (
        <Badge variant="secondary" className="tabular-nums">
          <CircleCheckIcon data-icon="inline-start" className="text-success" />
          Wysłane {dateTime(state.at)}
        </Badge>
      )
    case "sent_by_hand":
      return (
        <Badge variant="secondary" className="tabular-nums">
          <CircleCheckIcon data-icon="inline-start" className="text-success" />
          Wysłane ręcznie {dateTime(state.at)}
        </Badge>
      )
    case "changed":
      return (
        <Badge variant="outline" title={`Wysłane ${dateTime(state.at)}`}>
          <FilePenLineIcon data-icon="inline-start" className="text-warning" />
          Zmienione po wysłaniu
        </Badge>
      )
    case "no_address":
      return (
        <Badge variant="outline">
          <UserXIcon data-icon="inline-start" />
          Brak adresu
        </Badge>
      )
    case "without_orders":
      return (
        <Badge variant="outline" className="text-muted-foreground">
          <MinusIcon data-icon="inline-start" />
          Bez zleceń
        </Badge>
      )
    case "not_listed":
      return (
        <Badge variant="outline" className="text-muted-foreground">
          <UserXIcon data-icon="inline-start" />
          Nie ma w Liście Wykonawców
        </Badge>
      )
    case "not_sent":
      return (
        <Badge variant="destructive">
          <CircleXIcon data-icon="inline-start" />
          Nie wyszło
        </Badge>
      )
    case "unknown":
      return (
        <Badge variant="outline" className="text-muted-foreground">
          <CircleHelpIcon data-icon="inline-start" />
          Nie wiadomo
        </Badge>
      )
    default: {
      const unhandled: never = state

      return unhandled
    }
  }
}

/** Zdanie albo link pod odznaką: co zrobić z plikiem, który nie idzie, i dlaczego mail nie wyszedł. */
export function MailStateNote({ state }: { state: ShownState }) {
  switch (state.state) {
    case "no_address":
      return <SettingsLink>Dodaj adres w Ustawieniach</SettingsLink>
    case "not_listed":
      return <SettingsLink>Dodaj Wykonawcę w Ustawieniach</SettingsLink>
    case "not_sent":
      return <p className="max-w-64 text-xs text-destructive">{state.message}</p>
    default:
      return null
  }
}

function SettingsLink({ children }: { children: string }) {
  return (
    <a href={settingsHref(WORKERS_SECTION)} className="text-xs underline underline-offset-4 hover:text-foreground">
      {children}
    </a>
  )
}
