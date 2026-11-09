import { TriangleAlertIcon } from "lucide-react"

import type { Count, Figure } from "@/api/centrum"
import { seconds } from "@/lib/format"

/** Liczby z etykietami jako kafelki (np. Zlecenia na dzień); zero, które ostrzega, ma ikonę, nie tylko kolor. */
export function CountTiles({
  title,
  counts,
  zeroWarns = true,
}: {
  title: string
  counts: ReadonlyArray<Count>
  zeroWarns?: boolean
}) {
  return (
    <section className="flex flex-col gap-2" aria-label={title}>
      <h3 className="text-sm font-medium">{title}</h3>
      <ul className="grid grid-cols-7 gap-2">
        {counts.map((count) => (
          <li
            key={count.label}
            aria-label={`${count.label}: ${count.count}`}
            data-zero={zeroWarns && count.count === 0}
            className="flex flex-col items-center gap-1 rounded-lg bg-muted/60 px-1 py-2 data-[zero=true]:bg-warning/10"
          >
            <CountLabel label={count.label} />
            <span className="flex items-center gap-1 text-lg font-semibold tabular-nums">
              {zeroWarns && count.count === 0 ? <TriangleAlertIcon className="size-3.5 text-warning" aria-hidden /> : null}
              {count.count}
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}

/**
 * Etykieta kafelka w dwóch wierszach, np. „wt” i „06.10.2026”: kafelki mają wtedy równą wysokość
 * w wąskim oknie decyzji. Sama prezentacja tekstu z serwera.
 */
function CountLabel({ label }: { label: string }) {
  const [first, ...rest] = label.split(" ")

  return (
    <span className="flex flex-col items-center text-xs leading-tight text-muted-foreground tabular-nums">
      <span>{first}</span>
      {rest.length === 0 ? null : <span>{rest.join(" ")}</span>}
    </span>
  )
}

// Etykieta liczby stoi w jednym wierszu (`min-w-fit`), a gdy kolumny się nie mieszczą (np. w panelu z boku), liczby
// przechodzą do następnego wiersza paska. Ujemny margines kładzie lewą i górną kreskę liczby na kresce sąsiada, a
// `overflow-hidden` paska ucina te przy krawędzi.
export function NumberStrip({ figures, name }: { figures: ReadonlyArray<Figure>; name?: string }) {
  return (
    <dl className="flex flex-wrap overflow-hidden rounded-lg border" aria-label={name}>
      {figures.map((figure) => (
        <div key={figure.label} className="-mt-px -ml-px flex min-w-fit flex-1 flex-col gap-1 border-t border-l px-4 py-3">
          <dt className="text-xs text-muted-foreground">{figure.label}</dt>
          <dd className="text-2xl font-semibold tabular-nums">
            {figure.unit === "ms" ? seconds(figure.value) : figure.value}
          </dd>
        </div>
      ))}
    </dl>
  )
}
