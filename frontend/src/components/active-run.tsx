import type * as React from "react"
import { cn } from "cn"
import { LoaderCircleIcon } from "lucide-react"

import { href } from "@/lib/address"
import { isActive, useRuns, type ActiveRunView } from "@/lib/runs"
import type { Page } from "@/pages"

export const RUNS_PAGE: Page["id"] = "uruchomienia"

/**
 * Jak bieżące Uruchomienie wygląda poza swoją kartą. Czekanie na Decyzję taty woła tatę, bo okno decyzji
 * otwiera się tylko na stronie Uruchomienia.
 */
const SIGNS: Record<ActiveRunView["state"], { label: string; mark: React.ReactNode }> = {
  running: {
    label: "Trwa Uruchomienie",
    mark: <LoaderCircleIcon aria-hidden className="size-3.5 animate-spin text-muted-foreground motion-reduce:animate-none" />,
  },
  awaiting_decision: {
    label: "Czeka na decyzję",
    mark: <span aria-hidden className="size-2 rounded-full bg-warning" />,
  },
}

function useActiveSign() {
  const { view } = useRuns()

  return isActive(view) ? SIGNS[view.state] : null
}

/** Znak przy pozycji „Uruchomienia” w menu, widoczny na każdej stronie. */
export function ActiveRunMark({ className }: { className?: string }) {
  const sign = useActiveSign()

  if (sign === null) {
    return null
  }

  return (
    <span role="img" aria-label={sign.label} className={cn("flex size-4 items-center justify-center", className)}>
      {sign.mark}
    </span>
  )
}

/** Krótki link w nagłówku do trwającego Uruchomienia, gdy tata jest na innej stronie. */
export function ActiveRunLink({ current }: { current: Page["id"] }) {
  const sign = useActiveSign()

  if (sign === null || current === RUNS_PAGE) {
    return null
  }

  return (
    <a
      href={href(RUNS_PAGE)}
      className="wejscie inline-flex h-7 items-center gap-1.5 rounded-lg px-2.5 text-[0.8rem] font-medium outline-none transition-colors hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50"
    >
      <span className="flex size-4 items-center justify-center">{sign.mark}</span>
      {sign.label}
    </a>
  )
}
