import { RefreshCwIcon } from "lucide-react"

import { useChangeEntrance } from "@/lib/content-entrance"
import type { Tally } from "@/pages/settlement-mailing/periods"
import { cn } from "cn"

/**
 * Pasek „X z Y wysłane”: wypełnienie rośnie (`scaleX`, 1,1 s), poświata przechodzi przez nie w pętli, póki `live`, i raz
 * przy każdym wzroście `glow`. Pasek, który staje na stronie z `glow` 0, stoi bez poświaty.
 */
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

/** Stan pierścienia przy Wykonawcy w karcie okresu. */
export type Ring = "waiting" | "skipped" | "sending" | "sent" | "failed"

/** Pierścień stanu: znacznik rysuje się, gdy mail poszedł; `fresh`: poszedł w tej wizycie, więc pierścień podskakuje. */
export function StatusRing({ ring, fresh }: { ring: Ring; fresh: boolean }) {
  return (
    <span className="pierscien" data-ring={ring} data-swieze={fresh ? "" : undefined} aria-hidden>
      <Tick />
    </span>
  )
}

/** Liczba, która wjeżdża od dołu (albo od góry, `down`), gdy się zmieni; ta zastana przy wejściu na stronę stoi. */
export function RollingNumber({ value, down = false }: { value: number; down?: boolean }) {
  const entrance = useChangeEntrance(value, down ? "liczba liczba-w-dol" : "liczba")

  return (
    <span key={value} className={cn("inline-block tabular-nums", entrance)}>
      {value}
    </span>
  )
}

/**
 * Kropka okresu na osi: `now` odlicza maile do wysłania, `done` to zielony znacznik (rysuje się i podskakuje, gdy okres
 * skończył się w tej wizycie, `fresh`), `fix` bursztynowa przy poprawionym rozliczeniu, `open` szara z liczbą.
 */
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
