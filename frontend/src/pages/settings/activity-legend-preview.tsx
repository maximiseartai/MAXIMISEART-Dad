import { previewActivityLegend } from "@/api/centrum"
import type { LegendPreviewRow, PreviewActivityLegendData, PreviewActivityLegendResponse } from "@/api/generated"
import { Badge } from "@/components/ui/badge"
import { MoreRows, PreviewPanel, Summary, usePreview, WithoutFiles } from "@/pages/settings/quantity-rule-preview"

type Edit = PreviewActivityLegendData["body"]

/**
 * Skutek zmiany Kodu czynności na ostatnich Plikach zbiorczych po Przebiegu rozliczeń, liczony przez serwer tym samym
 * rachunkiem wiersza co Kontrola ilości: ile wierszy się zmieni, w ilu będzie tak, jak wpisał tata, i wiersze z różnicą
 * z opisem technika, bez adresu i numerów. Zapis jest możliwy także przy różnicach.
 */
export function LegendPreview({ edit }: { edit: Edit }) {
  const shown = usePreview(edit, previewActivityLegend)

  return <PreviewPanel shown={shown}>{shown.state === "ready" ? <Preview preview={shown.preview} /> : null}</PreviewPanel>
}

function Preview({ preview }: { preview: PreviewActivityLegendResponse }) {
  if (preview.state !== "ready") {
    return <WithoutFiles state={preview.state} />
  }

  const rows = preview.rows.map((row) => <Row key={`${row.period}-${row.row}`} row={row} />)

  return (
    <>
      <Summary preview={preview} differences="różnice legendy z Kontroli ilości" />
      {rows}
      <MoreRows more={preview.more} />
    </>
  )
}

function Row({ row }: { row: LegendPreviewRow }) {
  return (
    <div role="listitem" aria-label={`Wiersz ${row.row}`} className="flex flex-col gap-2 px-4 py-3 text-sm">
      <p className="text-muted-foreground tabular-nums">
        {row.period} · wiersz {row.row}
        {row.codes.length === 0 ? " · bez kodu" : ` · ${row.codes.join(", ")}`}
      </p>
      <p className="text-pretty">
        <span className="text-muted-foreground">CZYNNOŚCI ZREALIZOWANE </span>
        <span className="font-mono">{row.description}</span>
      </p>
      <ul className="flex flex-col gap-1">
        {row.cells.map((cell) => (
          <li key={`${cell.kind}-${cell.column}`} className="flex flex-wrap items-center gap-x-2 tabular-nums">
            <Badge variant="secondary" className="font-mono" aria-label={`kolumna ${cell.column}`}>
              {cell.kind === "fill" ? `${cell.column} kolor` : cell.column}
            </Badge>
            <span>
              {cell.name === null ? null : `${cell.name} · `}legenda {shownValue(cell.legend)}
            </span>
            <span className="text-muted-foreground">· wpisałeś {shownValue(cell.tata)}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function shownValue(value: number | string | null) {
  return value === null ? "brak" : String(value)
}
