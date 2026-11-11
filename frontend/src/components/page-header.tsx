import * as React from "react"

import { ToolUpdateAfterRestart } from "@/components/tool-update"
import type { Page } from "@/pages"

/** Bieżąca strona z adresu; daje ją `App`, a tytuł strony bierze się z jej wpisu w `PAGES`. */
export const CurrentPage = React.createContext<Page | null>(null)

// Duży tytuł strony, obok najwyżej jedna odznaka, po prawej najwyżej jedna akcja, na wąskim ekranie pod tytułem. Bez akapitu pod spodem poza
// `ToolUpdateAfterRestart`. `data-page` mówi pomiarowi widoku, że stoi nagłówek tej strony.
export function PageHeader({ badge, action }: { badge?: React.ReactNode; action?: React.ReactNode }) {
  const page = React.useContext(CurrentPage)

  if (page === null) {
    throw new Error("PageHeader działa tylko na stronie z PAGES.")
  }

  return (
    <>
      <div className="flex min-h-10 flex-wrap items-center gap-3">
        <h1 data-page={page.id} className="text-2xl font-semibold tracking-tight">
          {page.title}
        </h1>
        {badge}
        {action === undefined ? null : <div className="ml-auto flex max-w-full items-center gap-2">{action}</div>}
      </div>
      <ToolUpdateAfterRestart />
    </>
  )
}
