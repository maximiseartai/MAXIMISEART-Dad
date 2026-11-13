import * as React from "react"

import { getSettingsHistory, undoSettingsChange } from "@/api/centrum"
import { failureMessage } from "@/api/client"
import type { HistoryChange, HistoryRow, HistoryRuleChange } from "@/api/generated"
import { LoadFailure } from "@/components/load-failure"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useAction } from "@/lib/action"
import { dateTime, fullDate, plural } from "@/lib/format"
import { useReloadOnChange, useSettings } from "@/lib/settings"
import { useResource } from "@/lib/use-resource"
import { Sentence } from "@/pages/settings/rule-sentence"
import { FieldSentence, SettingRow, SettingsPanel } from "@/pages/settings/setting-row"

const THEMES = new Map([
  ["dark", "Ciemny"],
  ["light", "Jasny"],
])

const AUTOSTART = new Map([
  ["wlaczony", "Włączony"],
  ["wylaczony", "Wyłączony"],
])

const REMINDERS_ON = new Map([
  ["tak", "Włączone"],
  ["nie", "Wyłączone"],
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
  ["skrzynka.haslo", { label: "Hasło skrzynki raportów", shown: (value) => value }],
  ["skrzynka.dostep", { label: "Dostęp do skrzynki raportów", shown: (value) => value }],
  ["narzedzie.autostart", { label: "Start razem z Windows", shown: (value) => AUTOSTART.get(value) ?? value }],
  ["przypomnienia.wlaczone", { label: "Przypomnienia o raporcie", shown: (value) => REMINDERS_ON.get(value) ?? value }],
  ["przypomnienia.wlaczone_od", { label: "Przypomnienia od", shown: fullDate }],
  ["przypomnienia.pora_poranna", { label: "Pora poranna", shown: (value) => value }],
  ["przypomnienia.pora_wieczorna", { label: "Pora wieczorna", shown: (value) => value }],
  ["przypomnienia.pierwsze_przypomnienie", { label: "Pierwsze przypomnienie", shown: (value) => value }],
  ["przypomnienia.tresc", { label: "Treść przypomnienia", shown: (value) => value }],
  ["przypomnienia.stopka", { label: "Stopka przypomnienia", shown: (value) => value }],
])

function keyOf(change: HistoryChange): Key {
  return KEYS.get(change.key) ?? { label: change.key, shown: (value) => value }
}

/** Nazwa zmiany ze zdaniem przed i po po kluczu Historii: składnik, wyjątek Kontroli ilości albo reguła. */
function ruleLabel(key: string): string {
  if (key.startsWith("urzadzenia.")) return "Lista Urządzeń"
  return key.startsWith("wyjatki.") ? "Wyjątek Kontroli ilości" : "Reguła ilości"
}

/**
 * Historia Ustawień: każda zmiana od najnowszej, z wartością przed i po, kiedy i skąd, i „Cofnij” przy zmianie, którą
 * da się cofnąć. Cofnięcie jest nową zmianą na górze listy, a jego odmowa to jedno zdanie pod wierszem.
 */
export function HistorySection() {
  const { resource: history, reload } = useResource(getSettingsHistory, [], { fromDadFiles: false })

  useReloadOnChange(reload)

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

  // Reguła ilości, składnik Listy Urządzeń i wyjątek Kontroli ilości mają w wierszu zdanie przed i po zamiast zapisu z pliku.
  const rules = new Map(row.rules.map((rule) => [rule.key, rule]))

  const label = (change: HistoryChange) => (rules.has(change.key) ? ruleLabel(change.key) : keyOf(change).label)

  const title = row.changes.length === 0 ? row.file : [...new Set(row.changes.map(label))].join(", ")

  return (
    <SettingRow
      title={title}
      description={
        <span className="flex flex-col gap-0.5">
          {row.refused ? (
            <span className="text-foreground">Nie przyjęto: {row.reason}</span>
          ) : (
            row.changes.map((change) => {
              const rule = rules.get(change.key)

              return rule === undefined ? (
                <span key={change.key} className="text-foreground">
                  {row.changes.length > 1 ? `${label(change)}: ` : null}
                  <Values change={change} secret={row.secret} />
                </span>
              ) : (
                <RuleValues key={change.key} rule={rule} />
              )
            })
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

/** Kiedy i skąd: zapis taty bez znacznika, cofnięcie, zmiana spoza Centrum albo z Wydania, usunięty plik. */
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
    case "release":
      return [row.release?.version == null ? "Wydanie" : `Wydanie ${row.release.version}`]
    default: {
      const unhandled: never = row.source

      return unhandled
    }
  }
}

/**
 * Reguła ilości, składnik albo wyjątek Kontroli ilości przed i po jako zdania; nowy ma tylko „Dodano”, usunięty tylko
 * „Usunięto”.
 */
function RuleValues({ rule }: { rule: HistoryRuleChange }) {
  const lines: ReadonlyArray<[string, HistoryRuleChange["before"]]> =
    rule.before === null
      ? [["Dodano", rule.after]]
      : rule.after === null
        ? [["Usunięto", rule.before]]
        : [
            ["Przed", rule.before],
            ["Po", rule.after],
          ]

  return lines.map(([shown, parts]) => (
    <span key={shown} className="text-pretty text-foreground">
      <span className="text-muted-foreground">{shown}: </span>
      {parts === null ? null : <Sentence parts={parts} />}
    </span>
  ))
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
