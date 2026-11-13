import type * as React from "react"
import { cn } from "cn"

/** Karta sekcji Ustawień: wiersze jeden pod drugim, oddzielone cienką linią (wzór: ustawienia T3 Code). */
export function SettingsPanel({ label, className, children }: { label: string; className?: string; children: React.ReactNode }) {
  return (
    <div
      role="list"
      aria-label={label}
      className={cn("divide-y overflow-hidden rounded-xl border bg-card text-card-foreground", className)}
    >
      {children}
    </div>
  )
}

/**
 * Jedno ustawienie: nazwa, najwyżej jedno zdanie opisu i wybór albo stan po prawej; pod spodem (`below`) Komunikat,
 * gdy coś jest nie tak. Na wąskim oknie wybór schodzi pod nazwę.
 */
export function SettingRow({
  title,
  description,
  below,
  children,
}: {
  title: string
  description?: React.ReactNode
  below?: React.ReactNode
  children?: React.ReactNode
}) {
  return (
    <div role="listitem" aria-label={title} className="flex flex-col gap-3 px-4 py-3.5">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <div className="flex min-w-0 flex-1 basis-56 flex-col gap-0.5">
          <span className="text-sm font-medium">{title}</span>
          {description === undefined ? null : (
            <span className="text-sm text-pretty text-muted-foreground">{description}</span>
          )}
        </div>
        {children === undefined ? null : <div className="flex shrink-0 items-center gap-2">{children}</div>}
      </div>
      {below}
    </div>
  )
}
