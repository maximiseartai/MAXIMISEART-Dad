import { CheckIcon, MinusIcon } from "lucide-react"
import { cn } from "cn"

import type { PeriodRow } from "@/api/centrum"

/**
 * Droga okresu w krokach i stanach z serwera: ikona stanu zamiast zdań. Krok, którego okres zamknięty nie zrobił
 * (`not_done`), ma kreskę zamiast numeru.
 */
export function PeriodPath({ path }: { path: PeriodRow["path"] }) {
  return (
    <ol className="flex flex-wrap items-center gap-2" aria-label="Droga okresu">
      {path.map(({ label, stage }, index) => (
        <li key={label} className="flex items-center gap-2" aria-current={stage === "now" ? "step" : undefined}>
          {index > 0 ? (
            <span aria-hidden className={cn("h-px w-6 bg-border", stage !== "later" && "bg-foreground/40")} />
          ) : null}
          <span
            data-stage={stage}
            className="flex size-6 shrink-0 items-center justify-center rounded-full border text-xs font-medium tabular-nums data-[stage=done]:border-transparent data-[stage=done]:bg-secondary data-[stage=not_done]:border-dashed data-[stage=now]:border-foreground"
          >
            {stage === "done" ? (
              <CheckIcon className="size-3.5 text-success" aria-label="zrobione" />
            ) : stage === "not_done" ? (
              <MinusIcon className="size-3.5 text-muted-foreground" aria-label="niezrobione" />
            ) : (
              index + 1
            )}
          </span>
          <span
            className={cn(
              "text-sm whitespace-nowrap",
              stage === "later" || stage === "not_done" ? "text-muted-foreground" : "font-medium"
            )}
          >
            {label}
          </span>
        </li>
      ))}
    </ol>
  )
}
