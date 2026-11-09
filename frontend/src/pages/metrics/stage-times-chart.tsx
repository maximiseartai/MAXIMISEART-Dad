import * as React from "react"

import type { ProcessRun } from "@/api/generated"
import { dateTime, dayMonth, seconds } from "@/lib/format"
import { isStopped, phaseDuration, stopWord } from "@/pages/metrics/process-runs"

// Cztery sloty palety wykresu sprawdzone w prototypie (#95), po jednym na etap.
const PHASE_COLORS = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)"]

// Układ w pikselach: pole słupków, pod nim podpisy dat.
const PLOT_TOP = 8

const PLOT_HEIGHT = 238

const PLOT_BOTTOM = PLOT_TOP + PLOT_HEIGHT

const DATE_GAP = 8

const CHART_HEIGHT = PLOT_BOTTOM + 30

// Słupek ma najwyżej 28 px, a gdy miejsca brak, 80% swojej części szerokości (jak `maxBarSize`), więc słupki
// nigdy na siebie nie nachodzą. Szerokość liczy CSS (`cqw` pola słupków), także w SVG, bez mierzenia w skrypcie.
const BAR_WIDTH = 28

const BAR_SHARE_PERCENT = 80

const BAR_RADIUS = 4

const BAR: React.CSSProperties = { x: "calc(var(--bar-width) / -2)", width: "var(--bar-width)" }

const TOP_SEGMENT: React.CSSProperties = { ...BAR, clipPath: `inset(0 round ${BAR_RADIUS}px ${BAR_RADIUS}px 0 0)` }

const FOCUS_RING: React.CSSProperties = { x: "calc(var(--bar-width) / -2 - 3px)", width: "calc(var(--bar-width) + 6px)" }

// Podziałki osi czasu: najmniejszy krok z tych (×10ⁿ, od 0,1 s), przy którym wystarczą cztery przedziały.
const STEP_FACTORS = [1, 2, 2.5, 3, 5]

const AXIS_INTERVALS = 4

const SMALLEST_STEP_MS = 100

/** Słupki skumulowane czasów etapów: najstarsze Uruchomienie procesu z lewej; szczegóły po najechaniu, stuknięciu albo fokusie. */
export function StageTimesChart({
  phases,
  shown,
  runs,
}: {
  phases: ReadonlyArray<string>
  shown: ReadonlyArray<string>
  runs: ReadonlyArray<ProcessRun>
}) {
  const [active, setActive] = React.useState<number | null>(null)
  const bars = React.useRef<HTMLDivElement>(null)
  const colorOf = (phase: string) => PHASE_COLORS[phases.indexOf(phase)]
  const ticks = axisTicks(Math.max(...runs.map((run) => totalOf(run, shown))))
  const top = ticks.at(-1) ?? SMALLEST_STEP_MS
  const yOf = (durationMs: number) => PLOT_BOTTOM - (durationMs / top) * PLOT_HEIGHT
  const centerOf = (index: number) => ((index + 0.5) / runs.length) * 100
  // Klawiatura wchodzi na wykres na otwartym słupku, a bez niego na najnowszym.
  const tabStop = active ?? runs.length - 1
  const activeRun = active === null ? undefined : runs[active]

  React.useEffect(() => {
    if (active === null) {
      return undefined
    }

    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setActive(null)
      }
    }

    document.addEventListener("keydown", closeOnEscape)

    return () => document.removeEventListener("keydown", closeOnEscape)
  }, [active])

  const focusBar = (index: number) => {
    const target = bars.current?.querySelectorAll<SVGGElement>("[role=button]")[index]

    target?.focus()
  }

  const onKeyDown = (index: number) => (event: React.KeyboardEvent) => {
    const next = movedTo(event.key, index, runs.length - 1)

    if (next !== undefined) {
      event.preventDefault()
      focusBar(next)
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault()
      setActive(index)
    }
  }

  return (
    <figure aria-label="Wykres czasów etapów" className="flex flex-col text-xs">
      <div
        ref={bars}
        className="@container relative ml-14 mr-2"
        style={{
          height: CHART_HEIGHT,
          "--bar-width": `min(${BAR_WIDTH}px, ${BAR_SHARE_PERCENT / runs.length}cqw)`,
        }}
        onPointerLeave={(event) => {
          if (event.pointerType === "mouse") {
            setActive(null)
          }
        }}
        onBlur={(event) => {
          // Stuknięcie obok wykresu albo Tab dalej zabiera fokus ze słupków i zamyka szczegóły.
          if (!event.currentTarget.contains(event.relatedTarget)) {
            setActive(null)
          }
        }}
      >
        <svg role="presentation" className="absolute inset-0 size-full overflow-visible">
          <g aria-hidden className="fill-muted-foreground">
            {ticks.map((tick) => (
              <React.Fragment key={tick}>
                <line x1="0" x2="100%" y1={yOf(tick)} y2={yOf(tick)} className="stroke-border/50" />
                <text x={-12} y={yOf(tick)} dy="0.355em" textAnchor="end">
                  {seconds(tick)}
                </text>
              </React.Fragment>
            ))}
          </g>
          {runs.map((run, index) => (
            <svg key={run.started_at} role="presentation" x={`${centerOf(index)}%`} className="overflow-visible">
              <text aria-hidden x={0} y={PLOT_BOTTOM + DATE_GAP} dy="0.71em" textAnchor="middle" className="fill-muted-foreground">
                {dateLabel(run)}
              </text>
              <g
                role="button"
                tabIndex={index === tabStop ? 0 : -1}
                aria-label={barName(run, shown)}
                className="group outline-none"
                onPointerEnter={(event) => {
                  if (event.pointerType === "mouse") {
                    setActive(index)
                  }
                }}
                onFocus={() => setActive(index)}
                onClick={() => setActive(index)}
                onKeyDown={onKeyDown(index)}
              >
                <rect
                  x={`${-50 / runs.length}%`}
                  width={`${100 / runs.length}%`}
                  y={PLOT_TOP}
                  height={PLOT_HEIGHT}
                  fill="transparent"
                />
                {segmentsOf(run, shown, yOf).map((segment) => (
                  <rect
                    key={segment.phase}
                    data-phase={segment.phase}
                    style={segment.rounded ? TOP_SEGMENT : BAR}
                    y={segment.top}
                    height={segment.bottom - segment.top}
                    fill={colorOf(segment.phase)}
                    strokeWidth={2}
                    className="stroke-card"
                  />
                ))}
                <rect
                  style={FOCUS_RING}
                  y={yOf(totalOf(run, shown)) - 3}
                  height={PLOT_BOTTOM - yOf(totalOf(run, shown)) + 6}
                  rx={BAR_RADIUS + 2}
                  fill="none"
                  strokeWidth={2}
                  className="stroke-ring opacity-0 group-focus-visible:opacity-100"
                />
              </g>
            </svg>
          ))}
        </svg>
        {active === null || activeRun === undefined ? null : (
          <BarDetails run={activeRun} shown={shown} center={centerOf(active)} />
        )}
      </div>
      <ul aria-label="Etapy" className="flex items-center justify-center gap-4 pt-3">
        {shown.map((phase) => (
          <li key={phase} className="flex items-center gap-1.5">
            <span aria-hidden className="size-2 shrink-0 rounded-[2px]" style={{ backgroundColor: colorOf(phase) }} />
            {phase}
          </li>
        ))}
      </ul>
    </figure>
  )
}

/** Szczegóły słupka obok niego: po prawej, a w prawej połowie wykresu po lewej (`--bar-width` z pola słupków). */
function BarDetails({
  run,
  shown,
  center,
}: {
  run: ProcessRun
  shown: ReadonlyArray<string>
  center: number
}) {
  const offset = "calc(var(--bar-width) / 2 + 8px)"

  return (
    <div
      role="tooltip"
      className="pointer-events-none absolute grid w-max min-w-32 items-start gap-1.5 rounded-lg border border-border/50 bg-background px-2.5 py-1.5 text-xs shadow-xl"
      style={{
        left: `${center}%`,
        top: PLOT_TOP + PLOT_HEIGHT / 2,
        transform: center > 50 ? `translate(calc(-100% - ${offset}), -50%)` : `translate(${offset}, -50%)`,
      }}
    >
      <div className="font-medium">{barTitle(run)}</div>
      <div className="grid gap-1.5">
        {shown.map((phase) => (
          <div key={phase} className="flex w-full justify-between gap-4">
            <span className="text-muted-foreground">{phase}</span>
            <span className="font-medium tabular-nums">{seconds(phaseDuration(run, phase))}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

type Segment = { phase: string; top: number; bottom: number; rounded: boolean }

function segmentsOf(run: ProcessRun, shown: ReadonlyArray<string>, yOf: (durationMs: number) => number): Segment[] {
  const lasting = shown.filter((phase) => phaseDuration(run, phase) > 0)
  let below = 0

  return lasting.map((phase, index) => {
    const bottom = yOf(below)

    below += phaseDuration(run, phase)

    return { phase, top: yOf(below), bottom, rounded: index === lasting.length - 1 }
  })
}

function axisTicks(maxMs: number): number[] {
  for (let magnitude = SMALLEST_STEP_MS; ; magnitude *= 10) {
    for (const factor of STEP_FACTORS) {
      const step = factor * magnitude

      // Krok 0,25 s dałby podpisy zaokrąglone do dziesiątych (0,3 s, 0,5 s, 0,8 s).
      if (step % SMALLEST_STEP_MS === 0 && maxMs <= step * AXIS_INTERVALS) {
        const intervals = Math.max(1, Math.ceil(maxMs / step))

        return Array.from({ length: intervals + 1 }, (_, index) => index * step)
      }
    }
  }
}

function movedTo(key: string, index: number, last: number): number | undefined {
  switch (key) {
    case "ArrowLeft":
      return Math.max(index - 1, 0)
    case "ArrowRight":
      return Math.min(index + 1, last)
    case "Home":
      return 0
    case "End":
      return last
    default:
      return undefined
  }
}

function totalOf(run: ProcessRun, shown: ReadonlyArray<string>): number {
  return shown.reduce((sum, phase) => sum + phaseDuration(run, phase), 0)
}

function dateLabel(run: ProcessRun): string {
  return `${dayMonth(run.started_at)}${isStopped(run) ? " ✕" : ""}`
}

function barTitle(run: ProcessRun): string {
  return `${dateTime(run.started_at)} · okres ${run.period}${isStopped(run) ? ` · ${stopWord(run)}` : ""}`
}

function barName(run: ProcessRun, shown: ReadonlyArray<string>): string {
  const times = shown.map((phase) => `${phase} ${seconds(phaseDuration(run, phase))}`).join(", ")

  return `${barTitle(run)}. ${times}`
}
