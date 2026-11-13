import * as React from "react"

import { getSettingsHistory, undoSettingsChange } from "@/api/centrum"
import { failureMessage } from "@/api/client"
import type { HistoryChange, HistoryRow } from "@/api/generated"
import { LoadFailure } from "@/components/load-failure"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useAction } from "@/lib/action"
import { dateTime, plural } from "@/lib/format"
import { useSettings } from "@/lib/settings"
import { useResource } from "@/lib/use-resource"
import { FieldSentence, SettingRow, SettingsPanel } from "@/pages/settings/setting-row"

const THEMES = new Map([
  ["dark", "Ciemny"],
  ["light", "Jasny"],
])

/** Nazwa ścieżki: ostatni człon, pełna ścieżka w podpowiedzi. */
function pathName(value: string): string {
  return value.split(/[\\/]/).findLast((part) => part !== "") ?? value
}

type Key = { label: string; shown: (value: string) => string }

/** Klucze Historii (`sekcja.pole`) z nazwą dla taty i zapisem wartości; nieznany klucz pokazuje się wprost. */
const KEYS = new Map<string, Key>([
  ["foldery.rejestr_zlecen", { label: "Rejestr zleceń", shown: pathName }],
  ["foldery.folder_okresow", { label: "Folder okresów", shown: pathName }],
  ["wyglad.motyw", { label: "Motyw", shown: (value) => THEMES.get(value) ?? value }],
])

function keyOf(change: HistoryChange): Key {
  return KEYS.get(change.key) ?? { label: change.key, shown: (value) => value }
}

/**
 * Historia Ustawień: każda zmiana od najnowszej, z wartością przed i po, kiedy i skąd, i „Cofnij” przy zmianie, którą
 * da się cofnąć. Cofnięcie jest nową zmianą na górze listy, a jego odmowa to jedno zdanie pod wierszem.
 */
export function HistorySection() {
  const { changes } = useSettings()
  const { resource: history, reload } = useResource(getSettingsHistory, [], { fromDadFiles: false })
  const seen = React.useRef(changes)

  // Każda przyjęta zmiana (także z „Zapisano · Cofnij” w powiadomieniu) czyta Historię od nowa, bez szkieletu.
  React.useEffect(() => {
    if (seen.current !== changes) {
      seen.current = changes
      void reload()
    }
  }, [changes, reload])

  switch (history.state) {
    case "loading":
      return <Skeleton className="h-36 w-full rounded-xl" aria-label="Wczytywanie Historii" />
    case "failed":
      return <LoadFailure what="Historii Ustawień" message={history.message} reload={reload} />
    case "ready": {
      const { rows, skipped } = history.data

      return (
        <>
          {rows.length === 0 ? (
            <p className="text-sm text-muted-foreground">Nie ma jeszcze żadnej zmiany.</p>
          ) : (
            <SettingsPanel label="Zmiany">
              {rows.map((row) => (
                <Row key={row.id} row={row} />
              ))}
            </SettingsPanel>
          )}
          {skipped === 0 ? null : (
            <p className="text-sm text-muted-foreground">
              {skipped} {plural(skipped, { one: "wpisu", few: "wpisów", many: "wpisów" })} Historii nie da się odczytać.
            </p>
          )}
        </>
      )
    }

    default: {
      const unhandled: never = history

      return unhandled
    }
  }
}

function Row({ row }: { row: HistoryRow }) {
  const { undone } = useSettings()
  const [refusal, setRefusal] = React.useState<string | null>(null)

  const undoing = useAction(async () => {
    setRefusal(null)
    await undoSettingsChange(row.id).then(undone, (failure: Error) => setRefusal(failureMessage(failure)))
  })

  const title = row.changes.length === 0 ? row.file : row.changes.map((change) => keyOf(change).label).join(", ")

  return (
    <SettingRow
      title={title}
      description={
        <span className="flex flex-col gap-0.5">
          {row.refused ? (
            <span className="text-foreground">Nie przyjęto: {row.reason}</span>
          ) : (
            row.changes.map((change) => (
              <span key={change.key} className="text-foreground">
                {row.changes.length > 1 ? `${keyOf(change).label}: ` : null}
                <Values change={change} secret={row.secret} />
              </span>
            ))
          )}
          <span>{meta(row).join(" · ")}</span>
        </span>
      }
      below={refusal === null ? undefined : <FieldSentence>{refusal}</FieldSentence>}
    >
      {row.undoable ? (
        <Button
          variant="ghost"
          size="sm"
          aria-label={`Cofnij: ${title}`}
          disabled={undoing.running !== null}
          onClick={() => void undoing.run()}
        >
          {undoing.running === null ? null : <Spinner data-icon="inline-start" />}
          Cofnij
        </Button>
      ) : null}
    </SettingRow>
  )
}

/** Kiedy i skąd: zapis taty bez znacznika, cofnięcie, zmiana spoza Centrum, usunięty plik. */
function meta(row: HistoryRow): string[] {
  return [
    dateTime(row.at),
    ...(row.undoes === null ? [] : ["cofnięcie"]),
    ...sourceOf(row),
    ...(row.removed ? ["plik usunięty"] : []),
  ]
}

function sourceOf(row: HistoryRow): string[] {
  switch (row.source) {
    case "tata":
      return []
    case "outside":
      return ["spoza Centrum"]
    default: {
      const unhandled: never = row.source

      return unhandled
    }
  }
}

/** Przed → po; sekret tylko „zmieniono”, ścieżka nazwą z pełną ścieżką w podpowiedzi. */
function Values({ change, secret }: { change: HistoryChange; secret: boolean }) {
  if (secret) {
    return <>zmieniono</>
  }

  return (
    <>
      <Value value={change.before} shown={keyOf(change).shown} />
      <span className="text-muted-foreground">{" → "}</span>
      <Value value={change.after} shown={keyOf(change).shown} />
    </>
  )
}

function Value({ value, shown }: { value: string | null; shown: (value: string) => string }) {
  if (value === null) {
    return <span className="text-muted-foreground">nie ustawiono</span>
  }

  const text = shown(value)

  if (text === value) {
    return <span>{text}</span>
  }

  return (
    <Tooltip>
      <TooltipTrigger render={<span tabIndex={0} className="rounded-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50" />}>
        {text}
      </TooltipTrigger>
      <TooltipContent>{value}</TooltipContent>
    </Tooltip>
  )
}
