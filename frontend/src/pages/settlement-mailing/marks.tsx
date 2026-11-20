import { RefreshCwIcon } from "lucide-react"

import { useChangeEntrance } from "@/lib/content-entrance"
import type { Tally } from "@/pages/settlement-mailing/periods"
import { cn } from "cn"

export function MailingBar({
  tally,
  live,
  glow,
  label,
  mini = false,
}: {
  tally: Tally
  live: boolean
  glow: number
  label: string
  mini?: boolean
}) {
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={tally.of}
      aria-valuenow={tally.sent}
      className={cn("relative shrink-0 overflow-hidden rounded-full bg-muted", mini ? "h-1.5 w-36" : "h-2 w-full")}
    >
      <span
        className="pasek-wysylki absolute inset-0 overflow-hidden rounded-full bg-success"
        style={{ transform: `scaleX(${tally.of === 0 ? 0 : tally.sent / tally.of})` }}
      >
        {live ? <span className="poswiata absolute inset-0" data-petla="" /> : null}
        {!live && glow > 0 ? <span key={glow} className="poswiata absolute inset-0" data-raz="" /> : null}
      </span>
    </div>
  )
}

export type Ring = "waiting" | "skipped" | "sending" | "sent" | "failed"

export function StatusRing({ ring, fresh }: { ring: Ring; fresh: boolean }) {
  return (
    <span className="pierscien" data-ring={ring} data-swieze={fresh ? "" : undefined} aria-hidden>
      <Tick />
    </span>
  )
}

export function RollingNumber({ value, down = false }: { value: number; down?: boolean }) {
  const entrance = useChangeEntrance(value, down ? "liczba liczba-w-dol" : "liczba")

  return (
    <span key={value} className={cn("inline-block tabular-nums", entrance)}>
      {value}
    </span>
  )
}

export function PeriodDot({ tone, remaining, fresh }: { tone: "now" | "done" | "fix" | "open"; remaining: number; fresh: boolean }) {
  return (
    <span className="kropka-okresu relative z-10" data-tone={tone} data-swieze={fresh ? "" : undefined} aria-hidden>
      {tone === "done" ? <Tick className="znacznik" /> : null}
      {tone === "fix" ? <RefreshCwIcon /> : null}
      {tone === "now" || tone === "open" ? <RollingNumber value={remaining} down /> : null}
    </span>
  )
}

function Tick({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden>
      <path d="M6.5 12.5l3.5 3.5 7.5-8" pathLength={1} />
    </svg>
  )
}
