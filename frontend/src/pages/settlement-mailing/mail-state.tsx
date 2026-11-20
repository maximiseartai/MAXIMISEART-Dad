import {
  CheckIcon,
  CircleDashedIcon,
  CircleHelpIcon,
  CircleXIcon,
  FilePenLineIcon,
  MinusIcon,
  SendIcon,
  UserXIcon,
  type LucideIcon,
} from "lucide-react"

import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Badge } from "@/components/ui/badge"
import { dateTime } from "@/lib/format"
import type { ShownState } from "@/pages/settlement-mailing/periods"
import { initials } from "@/pages/settlement-mailing/words"
import { cn } from "cn"

type Tone = "sent" | "by_hand" | "changed" | "failed" | "plain" | "off"

const LOOK: Record<ShownState["state"], { words: string; icon: LucideIcon; tone: Tone }> = {
  sending: { words: "Wysyłam…", icon: SendIcon, tone: "plain" },
  to_send: { words: "Do wysłania", icon: CircleDashedIcon, tone: "plain" },
  sent: { words: "Wysłane", icon: CheckIcon, tone: "sent" },
  sent_by_hand: { words: "Wysłane ręcznie", icon: CheckIcon, tone: "by_hand" },
  changed: { words: "Zmienione po wysłaniu", icon: FilePenLineIcon, tone: "changed" },
  no_address: { words: "Brak adresu", icon: UserXIcon, tone: "off" },
  without_orders: { words: "Bez zleceń", icon: MinusIcon, tone: "off" },
  not_listed: { words: "Nie ma w Liście Wykonawców", icon: UserXIcon, tone: "off" },
  not_sent: { words: "Nie wyszło", icon: CircleXIcon, tone: "failed" },
  unknown: { words: "Nie wiadomo", icon: CircleHelpIcon, tone: "off" },
}

const BADGE: Record<Tone, string> = {
  sent: "bg-success-tile text-success-tile-foreground",
  by_hand: "bg-success-tile text-success-tile-foreground",
  changed: "bg-warning-tile text-warning-tile-foreground",
  failed: "bg-destructive-tile text-destructive-tile-foreground",
  plain: "bg-muted text-foreground",
  off: "border-border text-muted-foreground",
}

const DOT: Record<Tone, string> = {
  sent: "bg-success",
  by_hand: "bg-card shadow-[inset_0_0_0_1.5px_var(--success)]",
  changed: "bg-warning",
  failed: "bg-destructive",
  plain: "bg-border",
  off: "bg-border",
}

export function stateWords(state: ShownState): string {
  const { words } = LOOK[state.state]

  return state.state === "sent" || state.state === "sent_by_hand" ? `${words} ${dateTime(state.at)}` : words
}

/** Odznaka stanu Rozliczenia pracownika, zawsze z ikoną i słowami, nigdy samym kolorem. */
export function MailStateBadge({ state }: { state: ShownState }) {
  const { icon: Icon, tone } = LOOK[state.state]

  return (
    <Badge variant="outline" className={cn("tabular-nums", BADGE[tone], tone === "off" ? null : "border-transparent")}>
      <Icon data-icon="inline-start" />
      {stateWords(state)}
    </Badge>
  )
}

export function WorkerAvatar({ worker, state, size = "sm" }: { worker: string; state?: ShownState; size?: "sm" | "default" }) {
  return (
    <Avatar size={size} role={state === undefined ? undefined : "img"} aria-label={state === undefined ? undefined : `${worker}: ${stateWords(state)}`}>
      <AvatarFallback className="text-[0.6rem] font-semibold">{initials(worker)}</AvatarFallback>
      {state === undefined ? null : (
        <span
          aria-hidden
          className={cn(
            "absolute -right-0.5 -bottom-0.5 size-2.5 rounded-full border-2 border-background transition-colors duration-200",
            DOT[LOOK[state.state].tone]
          )}
        />
      )}
    </Avatar>
  )
}
