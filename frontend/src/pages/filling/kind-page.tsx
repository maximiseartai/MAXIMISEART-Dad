import { cn } from "cn"
import { CalendarRangeIcon } from "lucide-react"
import type * as React from "react"

import {
  getKindTable,
  type FillKind,
  type KindTable,
  type KindTableCell,
  type KindTableRow,
  type PriceListItem,
  type QuantitiesToFill,
} from "@/api/centrum"
import type { RowState } from "@/api/generated"
import { LoadFailure } from "@/components/load-failure"
import { PageHeader } from "@/components/page-header"
import { ThreePartMessage } from "@/components/three-part-message"
import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Skeleton } from "@/components/ui/skeleton"
import { href } from "@/lib/address"
import { useContentEntrance } from "@/lib/content-entrance"
import { useLiveFile } from "@/lib/use-live-file"
import type { Resource } from "@/lib/use-resource"
import { AfterSettlement, afterSettlementHint } from "@/pages/filling/after-settlement"
import { BackLink } from "@/pages/filling/back-link"
import { KINDS, ROW_STATES } from "@/pages/filling/labels"
import { SaveHint } from "@/pages/filling/save-hint"
import { OpenCollectiveFileButton } from "@/pages/periods/open-collective-file"

// Tło wiersza po jego stanie z serwera; tło przypiętych komórek jest kryjące, bo pod nimi przewijają się ilości.
const TINTS: Record<RowState, string> = {
  to_fill: "bg-to-fill",
  done: "bg-[color-mix(in_oklab,var(--success)_14%,var(--card))] dark:bg-[color-mix(in_oklab,var(--success)_20%,var(--card))]",
  without_quantity: "bg-[color-mix(in_oklab,var(--muted-foreground)_18%,var(--card))] text-muted-foreground",
}

type Pinned = { title: string; width: number; left: number }

// Przypięte kolumny w rem: `left` to suma szerokości kolumn przed nią. Razem 22 rem, więc na laptopie taty
// (1280 px z menu) obok mieści się 10 kolumn N:AP.
const NUMBER: Pinned = { title: "Nr", width: 3.5, left: 0 }

const TEXTS: ReadonlyArray<Pinned> = [
  { title: "WYKONAWCA", width: 4.25, left: 3.5 },
  { title: "URZĄDZENIA", width: 4.5, left: 7.75 },
  { title: "CZYNNOŚCI", width: 4.25, left: 12.25 },
  { title: "CZYNNOŚCI ZREALIZOWANE", width: 5.5, left: 16.5 },
]

const PINNED = [NUMBER, ...TEXTS]

const PINNED_WIDTH = PINNED.reduce((sum, { width }) => sum + width, 0)

// Kolumna N:AP w rem. Tabela ma stały układ (`table-fixed`), więc długie słowo nie poszerza kolumny ani nie
// przesuwa przypiętych kolumn.
const QUANTITY_WIDTH = 3.125

function pinnedStyle({ width, left }: Pinned): React.CSSProperties {
  return { width: `${width}rem`, minWidth: `${width}rem`, maxWidth: `${width}rem`, left: `${left}rem` }
}

/**
 * Nagłówek stron Uzupełnienia: okres obok tytułu, a „Otwórz Plik zbiorczy”, gdy Plik zbiorczy jest w Folderze okresu:
 * odczytany albo z Komunikatem, który go nazywa (uszkodzony, bez nagłówka).
 */
export function FillingHeader({ token, resource }: { token: string; resource: Resource<QuantitiesToFill | KindTable> }) {
  const exists = resource.state === "ready" && (resource.data.state === "ready" || resource.data.collective_file_exists)

  return (
    <PageHeader
      badge={
        <Badge variant="outline" className="tabular-nums">
          <CalendarRangeIcon aria-hidden />
          {token}
        </Badge>
      }
      action={exists ? <OpenCollectiveFileButton period={token} size="lg" /> : undefined}
    />
  )
}

/** Strona rodzaju Ilości do uzupełnienia `#/uzupelnienie/<okres>/<rodzaj>`: wiersze rodzaju jak w Excelu, tylko do podglądu. */
export function KindPage({ token, kind }: { token: string; kind: FillKind }) {
  const { resource, reload } = useLiveFile(getKindTable, [token, kind])

  return (
    <>
      <BackLink to={href("uzupelnienie", token)}>Podsumowanie</BackLink>
      <FillingHeader token={token} resource={resource} />
      <KindState resource={resource} reload={reload} heading={KINDS[kind].title} hint={KINDS[kind].hint} />
    </>
  )
}

function KindState({
  resource,
  reload,
  heading,
  hint,
}: {
  resource: Resource<KindTable>
  reload: () => Promise<void>
  heading: string
  hint: string
}) {
  const entrance = useContentEntrance(resource.state === "loading")

  switch (resource.state) {
    case "loading":
      return <TableSkeleton />
    case "failed":
      return (
        <LoadFailure what="okresu" message={resource.message} reload={reload} />
      )
    case "ready": {
      const table = resource.data

      if (table.state === "problem") {
        return (
          <div className={entrance}>
            <ThreePartMessage message={table.message} kind="notice" />
          </div>
        )
      }

      const done = table.rows.filter((row) => row.state === "done").length

      return (
        <div className={cn(entrance, "flex flex-col gap-3")}>
          {table.settled ? <AfterSettlement /> : null}
          <div className="flex items-end gap-3 px-1">
            <div className="flex flex-col gap-0.5">
              <h2 className="font-medium">{heading}</h2>
              <p className="text-sm text-muted-foreground">
                {table.rows.length === 0 ? "Nie ma takich wierszy." : table.settled ? afterSettlementHint(table.rows) : hint}
              </p>
            </div>
            {table.rows.length === 0 ? null : (
              <span className="ml-auto text-sm font-medium tabular-nums">
                {done} z {table.rows.length}
              </span>
            )}
          </div>
          {table.rows.length === 0 ? null : <QuantitiesTable columns={table.columns} rows={table.rows} />}
          {table.settled ? null : <SaveHint read={table.read} />}
        </div>
      )
    }

    default: {
      const unhandled: never = resource

      return unhandled
    }
  }
}

/** Tabela jak w Excelu: numer wiersza i teksty przypięte z lewej, wszystkie kolumny N:AP przewijane w bok. */
function QuantitiesTable({
  columns,
  rows,
}: {
  columns: ReadonlyArray<PriceListItem>
  rows: ReadonlyArray<KindTableRow>
}) {
  return (
    <Card className="overflow-hidden py-0">
      <div className="overflow-x-auto overscroll-x-contain">
        <table
          aria-label="Wiersze Pliku zbiorczego"
          className="table-fixed border-separate border-spacing-0 text-sm"
          style={{ width: `${PINNED_WIDTH + columns.length * QUANTITY_WIDTH}rem` }}
        >
          <thead>
            <tr>
              {PINNED.map((column, index) => (
                <th
                  key={column.title}
                  scope="col"
                  style={pinnedStyle(column)}
                  className={cn(
                    "sticky z-20 overflow-hidden border-b bg-muted px-1.5 py-2 text-left align-bottom text-[0.625rem] leading-tight font-medium text-muted-foreground",
                    index === PINNED.length - 1 && "border-r"
                  )}
                >
                  <span className="line-clamp-2 break-words hyphens-auto">{column.title}</span>
                </th>
              ))}
              {columns.map((column) => (
                <th
                  key={column.column}
                  scope="col"
                  style={{ width: `${QUANTITY_WIDTH}rem` }}
                  className="overflow-hidden border-b border-l bg-muted p-0 align-bottom"
                >
                  <ColumnHeader column={column} />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <Row key={row.row} row={row} />
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

function ColumnHeader({ column }: { column: PriceListItem }) {
  const content = (
    <>
      <span className="font-mono text-xs font-semibold text-foreground">{column.column}</span>
      <span className="line-clamp-2 text-[0.625rem] leading-tight font-normal break-words hyphens-auto text-muted-foreground">{column.name}</span>
    </>
  )

  if (column.name === "") {
    return <div className="flex h-full flex-col items-center justify-end gap-0.5 px-1 py-2">{content}</div>
  }

  return (
    <Popover>
      <PopoverTrigger
        aria-label={`${column.column}: ${column.name}`}
        className="flex w-full flex-col items-center justify-end gap-0.5 px-1 py-2 text-center transition-colors active:bg-foreground/5 data-[popup-open]:bg-foreground/5"
      >
        {content}
      </PopoverTrigger>
      <PopoverContent side="bottom" className="w-64">
        <p>
          <span className="mr-1.5 font-mono font-semibold">{column.column}</span>
          {column.name}
        </p>
      </PopoverContent>
    </Popover>
  )
}

function Row({ row }: { row: KindTableRow }) {
  const tint = TINTS[row.state]
  const { label, shown } = ROW_STATES[row.state]
  const texts = [row.worker, row.devices, row.activities, row.completed]

  return (
    <tr data-state={row.state}>
      <th
        scope="row"
        style={pinnedStyle(NUMBER)}
        className={cn("sticky z-10 h-10 border-b px-1.5 text-left align-middle font-mono text-sm text-muted-foreground tabular-nums", tint)}
      >
        {shown ? (
          <span className="flex flex-col gap-0.5 leading-none">
            <span>{row.row}</span>{" "}
            <span className="font-sans text-[0.625rem] font-normal whitespace-nowrap">{label}</span>
          </span>
        ) : (
          <>
            {row.row}
            <span className="sr-only"> {label}</span>
          </>
        )}
      </th>
      {TEXTS.map((column, index) => (
        <td
          key={column.title}
          style={pinnedStyle(column)}
          className={cn("sticky z-10 h-10 border-b p-0", tint, index === TEXTS.length - 1 && "border-r")}
        >
          <FullText text={texts[index] ?? ""} label={column.title} />
        </td>
      ))}
      {row.cells.map((cell, index) => (
        // Komórki idą po kolei jak kolumny N:AP nagłówka i nigdy się nie przestawiają.
        <QuantityCell key={index} cell={cell} tint={tint} />
      ))}
    </tr>
  )
}

function FullText({ text, label }: { text: string; label: string }) {
  if (text === "") {
    return null
  }

  return (
    <Popover>
      <PopoverTrigger
        aria-label={`${label}: ${text}`}
        className="block h-10 w-full truncate px-1.5 text-left transition-colors active:bg-foreground/5 data-[popup-open]:bg-foreground/5"
      >
        {text}
      </PopoverTrigger>
      <PopoverContent side="bottom" align="start" className="w-80">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="whitespace-pre-line">{text}</p>
      </PopoverContent>
    </Popover>
  )
}

function QuantityCell({ cell, tint }: { cell: KindTableCell; tint: string }) {
  const shown = cell.value === 0 ? "" : cell.value === "nieliczbowa" ? "?" : String(cell.value)

  return (
    <td
      data-source={cell.source}
      className={cn(
        "h-10 border-b border-l px-1 text-center font-mono text-sm tabular-nums",
        cell.source === "tata" ? "bg-success/25 font-semibold text-foreground" : tint,
        cell.source === "tool" && "text-muted-foreground"
      )}
    >
      {shown}
      {cell.value === "nieliczbowa" ? <span className="sr-only"> nieliczbowa</span> : null}
      {cell.source === "tool" && shown !== "" ? <span className="sr-only"> narzędzie</span> : null}
    </td>
  )
}

function TableSkeleton() {
  return (
    <Card aria-busy="true" aria-label="Wczytywanie wierszy" className="gap-3 p-4">
      <Skeleton className="h-10 w-full" />
      {[0, 1, 2].map((row) => (
        <Skeleton key={row} className="h-8 w-full" />
      ))}
    </Card>
  )
}
