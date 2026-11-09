import { cn } from "cn"
import { CircleAlertIcon, CircleCheckIcon, ClockIcon, EyeIcon, SendIcon, type LucideIcon } from "lucide-react"

import type { DadNoteNotification, SolvedCase } from "@/api/generated"

/** Stan sprawy taty: stan jej wysyłki w Kolejce wysyłki, a po wysłaniu to, co zrobił z nią Maks (unia z kontraktu). */
type CaseState = DadNoteNotification["state"]

type Kind = SolvedCase["kind"]

/** `problem`: tata nic tu nie poprawi i ma skontaktować się z Maksem, bez obietnicy, że wiadomość wyjdzie sama. */
type Line = { icon: LucideIcon; tone: string; text: Record<Kind, string>; problem?: true }

type LineKey = Exclude<CaseState["state"], "queued"> | Extract<CaseState, { state: "queued" }>["waits_for"]

const TOKEN = "Token do Zgłoszeń nie działa. Skontaktuj się z Maksem."

const INTERNET = "Wyślę do Maksa, gdy będzie internet."

// Uwaga taty jest rodzaju żeńskiego, Zgłoszenie nijakiego. Zielony znaczek ma tylko to, co rozwiązał Maks.
const LINES: Record<LineKey, Line> = {
  sent: {
    icon: SendIcon,
    tone: "text-muted-foreground",
    text: { uwaga: "Uwaga wysłana do Maksa.", zgloszenie: "Zgłoszenie wysłane do Maksa. Poczekaj na naprawę." },
  },
  internet: { icon: ClockIcon, tone: "text-muted-foreground", text: { uwaga: INTERNET, zgloszenie: INTERNET } },
  key: { icon: CircleAlertIcon, tone: "text-destructive", text: { uwaga: TOKEN, zgloszenie: TOKEN }, problem: true },
  rejected: {
    icon: CircleAlertIcon,
    tone: "text-destructive",
    text: {
      uwaga: "Tej Uwagi nie da się wysłać. Skontaktuj się z Maksem.",
      zgloszenie: "Tego Zgłoszenia nie da się wysłać. Skontaktuj się z Maksem.",
    },
    problem: true,
  },
  resolved: {
    icon: CircleCheckIcon,
    tone: "text-success",
    text: { uwaga: "Rozwiązana. Będzie w następnej wersji.", zgloszenie: "Rozwiązane. Będzie w następnej wersji." },
  },
  read: { icon: EyeIcon, tone: "text-muted-foreground", text: { uwaga: "Maks przeczytał.", zgloszenie: "Maks przeczytał." } },
}

/**
 * Jedno zdanie o stanie sprawy taty dla okna Uwagi taty, Zgłoszenia i Powiadomień: ikona, jej ton i tekst. Miejsce
 * wybiera tylko wielkość, układ i kolor zdania, który przy problemie zawsze jest pełny.
 */
export function CaseStateLine({
  state,
  kind,
  className,
  iconClassName,
  role,
}: {
  state: CaseState
  kind: Kind
  className?: string
  iconClassName?: string
  role?: "status"
}) {
  const line = LINES[state.state === "queued" ? state.waits_for : state.state]

  return (
    <p role={role} className={cn("flex items-center gap-2 text-sm", className, line.problem && "text-foreground")}>
      <line.icon className={cn("size-4 shrink-0", line.tone, iconClassName)} aria-hidden />
      {line.text[kind]}
    </p>
  )
}
