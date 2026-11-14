import { BellIcon, CheckIcon, CircleAlertIcon, ClockIcon, MailIcon, type LucideIcon } from "lucide-react"
import { cn } from "cn"

import { Badge } from "@/components/ui/badge"
import type { Choice, Status } from "@/pages/worker-reports/day-state"

type Look = {
  label: string
  icon: LucideIcon
  /** Tło i napis kafelka, znaczka w popoverze i pola w liście filtra Status. */
  tile: string
  /** Kolor stanu: pasek w popoverze i kropka przy przycisku Status. */
  color: string
}

/** Stany z wynikiem kliknięcia w kolejności listy filtra Status: najpierw to, co wymaga ręki taty. */
export const STATUSES: ReadonlyArray<Status> = ["problem", "without_report", "waiting", "complete"]

const LOOKS: Readonly<Record<Choice, Look>> = {
  problem: {
    label: "Problem",
    icon: CircleAlertIcon,
    tile: "bg-destructive-tile text-destructive-tile-foreground",
    color: "var(--destructive)",
  },
  without_report: {
    label: "Bez raportu",
    icon: MailIcon,
    tile: "bg-warning-tile text-warning-tile-foreground",
    color: "var(--warning)",
  },
  waiting: { label: "Czeka", icon: ClockIcon, tile: "bg-muted text-muted-foreground", color: "var(--ring)" },
  complete: {
    label: "Komplet",
    icon: CheckIcon,
    tile: "bg-success-tile text-success-tile-foreground",
    color: "var(--success)",
  },
  reminded: {
    label: "Przypomniane",
    icon: BellIcon,
    tile: "bg-reminder-tile text-reminder-tile-foreground",
    color: "var(--reminder)",
  },
}

export function look(choice: Choice): Look {
  return LOOKS[choice]
}

/** Znaczek stanu: nazwa stanu (albo `label`, np. „Wpisane” przy zleceniu) w kolorze kafelka, nigdy sam kolor. */
export function StatusBadge({ status, label = look(status).label }: { status: Status; label?: string }) {
  return <Badge className={cn("rounded-full", look(status).tile)}>{label}</Badge>
}
