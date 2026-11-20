import type * as React from "react"
import {
  BellIcon,
  CalendarRangeIcon,
  ChartColumnIcon,
  ClipboardPenLineIcon,
  MailCheckIcon,
  PlayIcon,
  SendIcon,
  type LucideIcon,
} from "lucide-react"

import type { ViewTiming } from "@/api/generated"
import { hashParts, useHash } from "@/lib/address"
import { FillingPage } from "@/pages/filling/filling-page"
import { MetricsPage } from "@/pages/metrics/metrics-page"
import { NotificationsPage } from "@/pages/notifications/notifications-page"
import { PeriodsPage } from "@/pages/periods/periods-page"
import { ReportsPage } from "@/pages/worker-reports/reports-page"
import { RunsPage } from "@/pages/runs/runs-page"
import { MailingPage } from "@/pages/settlement-mailing/mailing-page"

export const NOTIFICATIONS_PAGE = {
  id: "powiadomienia",
  title: "Powiadomienia",
  icon: BellIcon,
  Content: NotificationsPage,
  menu: false,
} as const

export const PAGES = [
  { id: "okresy", title: "Okresy", icon: CalendarRangeIcon, Content: PeriodsPage, menu: true },
  { id: "uruchomienia", title: "Uruchomienia", icon: PlayIcon, Content: RunsPage, menu: true },
  { id: "raporty", title: "Raporty", icon: MailCheckIcon, Content: ReportsPage, menu: true },
  { id: "wysylka", title: "Wysyłka rozliczeń", icon: SendIcon, Content: MailingPage, menu: true },
  { id: "metryki", title: "Metryki", icon: ChartColumnIcon, Content: MetricsPage, menu: true },
  NOTIFICATIONS_PAGE,
  {
    id: "uzupelnienie",
    title: "Uzupełnienie pliku zbiorczego",
    icon: ClipboardPenLineIcon,
    Content: FillingPage,
    menu: false,
    inMenu: "okresy",
  },
] as const satisfies ReadonlyArray<{
  id: ViewTiming["page"]
  title: string
  icon: LucideIcon
  Content: React.ComponentType
  menu: boolean
  inMenu?: ViewTiming["page"]
}>

export type Page = (typeof PAGES)[number]

function pageOf(hash: string): Page {
  const [id] = hashParts(hash)

  return PAGES.find((page) => page.id === id) ?? PAGES[0]
}

export function menuPageId(page: Page): Page["id"] {
  return "inMenu" in page ? page.inMenu : page.id
}

/** Bieżąca strona z adresu (`#/okresy`, `#/uzupelnienie/<okres>`), więc działa Wstecz w przeglądarce i odświeżenie karty. */
export function useCurrentPage(): Page {
  return pageOf(useHash())
}
