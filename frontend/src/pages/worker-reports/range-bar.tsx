import * as React from "react"
import { CalendarIcon, ChevronLeftIcon, ChevronRightIcon } from "lucide-react"
import { pl } from "react-day-picker/locale"

import { Button } from "@/components/ui/button"
import { ButtonGroup } from "@/components/ui/button-group"
import { Calendar } from "@/components/ui/calendar"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { plural } from "@/lib/format"
import {
  canShift,
  type DayRange,
  daysIn,
  defaultRange,
  rangeLabel,
  rangeOf,
  shifted,
  weekdayOfDate,
} from "@/pages/worker-reports/days"

type Props = {
  /** Dni okna z odpowiedzi serwera, od najstarszego. */
  days: ReadonlyArray<string>
  today: string
  range: DayRange
  onRange: (range: DayRange) => void
}

/**
 * Zakres dni Mapy cieplnej: `‹ 2–15 lis ›` (strzałki przesuwają o długość zakresu, napis otwiera kalendarz) i osobny
 * przycisk kalendarza. Zakres zmienia się od razu, bez animacji.
 */
export function RangeBar({ days, today, range, onRange }: Props) {
  const [open, setOpen] = React.useState(false)

  return (
    <div className="flex items-center gap-2">
      <ButtonGroup aria-label="Zakres dni">
        <Button
          variant="outline"
          size="icon"
          aria-label="Wcześniejsze dni"
          disabled={!canShift(days, range, -1)}
          onClick={() => onRange(shifted(days, range, -1))}
        >
          <ChevronLeftIcon />
        </Button>
        <Button variant="outline" className="min-w-36 tabular-nums" onClick={() => setOpen(true)}>
          {rangeLabel(range.from, range.to)}
        </Button>
        <Button
          variant="outline"
          size="icon"
          aria-label="Późniejsze dni"
          disabled={!canShift(days, range, 1)}
          onClick={() => onRange(shifted(days, range, 1))}
        >
          <ChevronRightIcon />
        </Button>
      </ButtonGroup>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger render={<Button variant="outline" size="icon" aria-label="Wybierz dni w kalendarzu" />}>
          <CalendarIcon />
        </PopoverTrigger>
        <PopoverContent align="end" aria-label="Kalendarz dni" className="w-auto gap-0 p-3 duration-150 ease-out">
          <RangeCalendar
            days={days}
            today={today}
            range={range}
            onRange={(chosen) => {
              setOpen(false)
              onRange(chosen)
            }}
          />
        </PopoverContent>
      </Popover>
    </div>
  )
}

/** `2026-11-11` → dzień kalendarza (lokalna północ, jak liczy go kalendarz). */
function dateOf(day: string): Date {
  const [year = 0, month = 1, date = 1] = day.split("-").map(Number)

  return new Date(year, month - 1, date)
}

const MONTH = new Intl.DateTimeFormat("pl-PL", { month: "long", year: "numeric" })

/** Podpis miesiąca kalendarza: `Listopad 2026`. */
function caption(month: Date): string {
  const text = MONTH.format(month)

  return text.charAt(0).toLocaleUpperCase("pl") + text.slice(1)
}

function dayOf(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`
}

/**
 * Kalendarz przedziału z dni okna (inne dni są wyłączone): pierwszy klik to początek, drugi koniec, a do drugiego
 * kliknięcia przedział podąża za wskaźnikiem. „Bieżące dwa tygodnie” wraca do zakresu domyślnego.
 */
function RangeCalendar({ days, today, range, onRange }: Props) {
  const [start, setStart] = React.useState<string | null>(null)
  const [hovered, setHovered] = React.useState<string | null>(null)
  const allowed = React.useMemo(() => new Set(days), [days])
  const shown = start === null ? range : rangeOf(days, start, hovered ?? start)
  const length = daysIn(days, range).length

  return (
    <div className="flex flex-col gap-3">
      <Calendar
        mode="range"
        locale={pl}
        weekStartsOn={1}
        formatters={{ formatCaption: caption, formatWeekdayName: weekdayOfDate }}
        className="p-0 [--cell-size:--spacing(9)]"
        today={dateOf(today)}
        defaultMonth={dateOf(range.to)}
        startMonth={dateOf(days[0] ?? range.from)}
        endMonth={dateOf(days.at(-1) ?? range.to)}
        selected={{ from: dateOf(shown.from), to: dateOf(shown.to) }}
        disabled={(date) => !allowed.has(dayOf(date))}
        onDayMouseEnter={(date) => setHovered(start === null ? null : dayOf(date))}
        onSelect={(_, clicked) => {
          const day = dayOf(clicked)

          if (start === null) {
            setStart(day)
            setHovered(day)
          } else {
            onRange(rangeOf(days, start, day))
          }
        }}
      />
      <div className="flex items-center justify-between gap-2 border-t pt-3 text-xs text-muted-foreground">
        <span aria-live="polite">
          {start === null ? `${length} ${plural(length, { one: "dzień", few: "dni", many: "dni" })}` : "Kliknij ostatni dzień"}
        </span>
        <Button size="sm" variant="outline" onClick={() => onRange(defaultRange(days, today))}>
          Bieżące dwa tygodnie
        </Button>
      </div>
    </div>
  )
}
