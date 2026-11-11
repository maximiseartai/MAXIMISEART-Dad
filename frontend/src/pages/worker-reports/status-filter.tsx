import { cn } from "cn"
import { ChevronDownIcon, FilterIcon, FilterXIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Separator } from "@/components/ui/separator"
import type { Status } from "@/pages/worker-reports/day-state"
import { look, STATUSES } from "@/pages/worker-reports/status"

/**
 * Filtr Status: lista „Pokaż w widoku” ze stanami dni i liczbą dni w zakresie, wybór kilku naraz i „Pokaż wszystko”.
 * Przy przycisku kropki wybranych stanów. Filtr działa od razu, bez animacji.
 */
export function StatusFilter({
  chosen,
  counts,
  onChange,
}: {
  chosen: ReadonlySet<Status>
  counts: Readonly<Record<Status, number>>
  onChange: (chosen: ReadonlySet<Status>) => void
}) {
  const toggled = (status: Status) => {
    const next = new Set(chosen)

    if (!next.delete(status)) {
      next.add(status)
    }

    onChange(next)
  }

  return (
    <Popover>
      <PopoverTrigger render={<Button variant="outline" />}>
        <FilterIcon data-icon="inline-start" />
        Status
        {chosen.size === 0 ? null : (
          <span className="flex gap-0.5" aria-hidden>
            {STATUSES.filter((status) => chosen.has(status)).map((status) => (
              <span key={status} className="size-2 rounded-full" style={{ background: look(status).color }} />
            ))}
          </span>
        )}
        <ChevronDownIcon data-icon="inline-end" className="text-muted-foreground" />
      </PopoverTrigger>
      <PopoverContent align="start" aria-label="Pokaż w widoku" className="w-64 gap-0 p-1.5 duration-150 ease-out">
        <p className="px-2.5 pt-1.5 pb-1 text-xs text-muted-foreground">Pokaż w widoku</p>
        {STATUSES.map((status) => {
          const { label, icon: Icon, tile } = look(status)

          return (
            <button
              key={status}
              type="button"
              aria-pressed={chosen.has(status)}
              onClick={() => toggled(status)}
              className="flex h-9 items-center gap-2.5 rounded-md px-2.5 text-left transition-colors duration-150 ease-out outline-none hover:bg-accent focus-visible:ring-3 focus-visible:ring-ring/50 aria-pressed:bg-accent aria-pressed:font-medium"
            >
              <span className={cn("grid size-6 place-items-center rounded-md", tile)}>
                <Icon className="size-3.5" aria-hidden />
              </span>
              <span className="flex-1">{label}</span>
              <span className="text-muted-foreground tabular-nums">{counts[status]}</span>
            </button>
          )
        })}
        <Separator className="my-1.5" />
        <div className="flex justify-end px-1 pb-0.5">
          <Button size="sm" variant="outline" disabled={chosen.size === 0} onClick={() => onChange(new Set())}>
            <FilterXIcon data-icon="inline-start" />
            Pokaż wszystko
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  )
}
