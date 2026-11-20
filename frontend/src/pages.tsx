import * as React from "react"
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

import type { CentrumFunction, ViewTiming } from "@/api/generated"
import { hashParts, useHash } from "@/lib/address"
import { useInScope } from "@/lib/scope"
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
  function: null,
} as const

const PAGES = [
  { id: "okresy", title: "Okresy", icon: CalendarRangeIcon, Content: PeriodsPage, menu: true, function: "periods" },
  { id: "uruchomienia", title: "Uruchomienia", icon: PlayIcon, Content: RunsPage, menu: true, function: null },
  { id: "raporty", title: "Raporty", icon: MailCheckIcon, Content: ReportsPage, menu: true, function: "report_entering" },
  {
    id: "wysylka",
    title: "Wysyłka rozliczeń",
    icon: SendIcon,
    Content: MailingPage,
    menu: true,
    function: "settlement_mailing",
  },
  { id: "metryki", title: "Metryki", icon: ChartColumnIcon, Content: MetricsPage, menu: true, function: "metrics" },
  NOTIFICATIONS_PAGE,
  {
    id: "uzupelnienie",
    title: "Uzupełnienie pliku zbiorczego",
    icon: ClipboardPenLineIcon,
    Content: FillingPage,
    menu: false,
    inMenu: "okresy",
    function: "filling",
  },
] as const satisfies ReadonlyArray<{
  id: ViewTiming["page"]
  title: string
  icon: LucideIcon
  Content: React.ComponentType
  menu: boolean
  inMenu?: ViewTiming["page"]
  function: CentrumFunction | null
}>

export type Page = (typeof PAGES)[number]

export function useMenuPages(): ReadonlyArray<Page> {
  const pages = useInScope(PAGES)

  return React.useMemo(() => pages.filter((page) => page.menu), [pages])
}

export function useStartPage(): Page {
  const [start] = useMenuPages()

  if (start === undefined) {
    throw new Error("Menu Centrum rozliczeń nie ma żadnej strony w Zakresie.")
  }

  return start
}

export function menuPageId(page: Page): Page["id"] {
  return "inMenu" in page ? page.inMenu : page.id
}

/** Bieżąca strona z adresu (`#/okresy`, `#/uzupelnienie/<okres>`), więc działa Wstecz w przeglądarce i odświeżenie karty. */
export function useCurrentPage(): Page {
  const [id] = hashParts(useHash())
  const pages = useInScope(PAGES)
  const start = useStartPage()

  return pages.find((page) => page.id === id) ?? start
}
