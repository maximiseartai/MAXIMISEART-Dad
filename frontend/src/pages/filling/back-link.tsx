import type * as React from "react"
import { ArrowLeftIcon } from "lucide-react"

import type { Href } from "@/lib/address"

export function BackLink({ to, children }: { to: Href; children: React.ReactNode }) {
  return (
    <a
      href={to}
      className="-mb-4 flex w-fit items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
    >
      <ArrowLeftIcon className="size-4" aria-hidden />
      {children}
    </a>
  )
}
