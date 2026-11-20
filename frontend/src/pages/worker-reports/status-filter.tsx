import { cn } from "cn"
import { ChevronDownIcon, FilterIcon, FilterXIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Separator } from "@/components/ui/separator"
import type { Choice } from "@/pages/worker-reports/day-state"
import { look, STATUSES } from "@/pages/worker-reports/status"

const CHOICES: ReadonlyArray<Choice> = [...STATUSES, "reminded"]

/**
 * Filtr Status: lista „Pokaż w widoku” ze stanami dni, pod kreską Przypomniane (dni, za które poszło Przypomnienie o
 * raporcie), przy każdej pozycji liczba dni w zakresie, wybór kilku naraz i „Pokaż wszystko”. Przy przycisku kropki
 * wybranych pozycji. Filtr działa od razu, bez animacji.
 */
export function StatusFilter({
  chosen,
  counts,
  onChange,
}: {
  chosen: ReadonlySet<Choice>
  counts: Readonly<Record<Choice, number>>
  onChange: (chosen: ReadonlySet<Choice>) => void
}) {
  const toggled = (choice: Choice) => {
    const next = new Set(chosen)

    if (!next.delete(choice)) {
      next.add(choice)
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
            {CHOICES.flatMap((choice) =>
              chosen.has(choice) ? [<span key={choice} className="size-2 rounded-full" style={{ background: look(choice).color }} />] : []
            )}
          </span>
        )}
        <ChevronDownIcon data-icon="inline-end" className="text-muted-foreground" />
      </PopoverTrigger>
      <PopoverContent align="start" aria-label="Pokaż w widoku" className="w-64 gap-0 p-1.5 duration-150 ease-out">
        <p className="px-2.5 pt-1.5 pb-1 text-xs text-muted-foreground">Pokaż w widoku</p>
        {STATUSES.map((status) => (
          <Option key={status} choice={status} count={counts[status]} pressed={chosen.has(status)} onToggle={toggled} />
        ))}
        <Separator className="my-1.5" />
        <Option choice="reminded" count={counts.reminded} pressed={chosen.has("reminded")} onToggle={toggled} />
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

function Option({
  choice,
  count,
  pressed,
  onToggle,
}: {
  choice: Choice
  count: number
  pressed: boolean
  onToggle: (choice: Choice) => void
}) {
  const { label, icon: Icon, tile } = look(choice)

  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={() => onToggle(choice)}
      className="flex h-9 items-center gap-2.5 rounded-md px-2.5 text-left transition-colors duration-150 ease-out outline-none hover:bg-accent focus-visible:ring-3 focus-visible:ring-ring/50 aria-pressed:bg-accent aria-pressed:font-medium"
    >
      <span className={cn("grid size-6 place-items-center rounded-md", tile)}>
        <Icon className="size-3.5" aria-hidden />
      </span>
      <span className="flex-1">{label}</span>
      <span className="text-muted-foreground tabular-nums">{count}</span>
    </button>
  )
}
