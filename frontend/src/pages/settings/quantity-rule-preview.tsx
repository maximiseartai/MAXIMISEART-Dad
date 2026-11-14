import * as React from "react"
import { cn } from "cn"

import { previewQuantityRules } from "@/api/centrum"
import { failureMessage } from "@/api/client"
import type { PreviewQuantityRulesData, PreviewQuantityRulesResponse, PreviewReady, PreviewRow } from "@/api/generated"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { plural } from "@/lib/format"
import { columnLabel, Sentence } from "@/pages/settings/rule-sentence"
import { SettingsPanel } from "@/pages/settings/setting-row"

type Edit = PreviewQuantityRulesData["body"]

/** Podgląd czeka tyle po ostatniej zmianie formularza, żeby nie liczyć przy każdym znaku. */
const PAUSE_MS = 400

type Answer = { state: "refused"; message: string } | { state: "ready"; preview: PreviewQuantityRulesResponse }

/** Ostatnia odpowiedź podglądu; `refreshing`: formularz zmienił się od niej, a nowa jeszcze nie przyszła. */
type Shown = { state: "waiting" } | (Answer & { refreshing: boolean })

const ROWS = { one: "wiersz", few: "wiersze", many: "wierszy" }

/**
 * Skutek zmiany reguły na ostatnich Plikach zbiorczych po Przebiegu rozliczeń, liczony przez serwer tym samym
 * rachunkiem co Kontrola ilości: ile wierszy się zmieni, w ilu będzie tak, jak wpisał tata, i wiersze z różnicą, bez
 * adresu i numerów. Liczy się od nowa chwilę po każdej zmianie formularza; do odpowiedzi stoi poprzedni wynik.
 */
export function RulePreview({ edit }: { edit: Edit }) {
  const shown = usePreview(edit)

  return (
    <section aria-label="Podgląd" className="flex flex-col gap-2">
      <p aria-hidden className="flex items-center gap-2 px-1 text-xs font-medium text-muted-foreground">
        Podgląd na ostatnich okresach
        {shown.state !== "waiting" && shown.refreshing ? <Spinner className="size-3" /> : null}
      </p>
      <SettingsPanel label="Podgląd" className="bg-muted/30">
        <PreviewBody shown={shown} />
      </SettingsPanel>
    </section>
  )
}

function usePreview(edit: Edit): Shown {
  const key = JSON.stringify(edit)
  const latestEdit = React.useRef(edit)
  const latest = React.useRef(0)
  const [answered, setAnswered] = React.useState<{ key: string; answer: Answer } | null>(null)

  React.useEffect(() => {
    latestEdit.current = edit
  })

  React.useEffect(() => {
    const asked = ++latest.current

    const timer = window.setTimeout(() => {
      previewQuantityRules(latestEdit.current).then(
        (preview) => {
          if (asked === latest.current) {
            setAnswered({ key, answer: { state: "ready", preview } })
          }
        },
        (failure: Error) => {
          if (asked === latest.current) {
            setAnswered({ key, answer: { state: "refused", message: failureMessage(failure) } })
          }
        }
      )
    }, PAUSE_MS)

    return () => window.clearTimeout(timer)
  }, [key])

  return answered === null ? { state: "waiting" } : { ...answered.answer, refreshing: answered.key !== key }
}

function PreviewBody({ shown }: { shown: Shown }) {
  switch (shown.state) {
    case "waiting":
      return (
        <div role="listitem" className="px-4 py-3">
          <Skeleton className="h-5 w-2/3" aria-label="Wczytywanie podglądu" />
        </div>
      )
    case "refused":
      return (
        <p role="listitem" className="px-4 py-3 text-sm text-pretty text-muted-foreground">
          {shown.message}
        </p>
      )
    case "ready":
      return <Preview preview={shown.preview} />
    default: {
      const unhandled: never = shown

      return unhandled
    }
  }
}

function Preview({ preview }: { preview: PreviewQuantityRulesResponse }) {
  const sentence =
    preview.sentence === null ? null : (
      <p role="listitem" aria-label="Reguła" className="px-4 py-3 text-sm leading-7 text-pretty">
        <Sentence parts={preview.sentence} />
      </p>
    )

  switch (preview.state) {
    case "no_periods_directory":
      return (
        <>
          {sentence}
          <Note>Wskaż folder okresów w sekcji Foldery, żeby zobaczyć skutek na ostatnich okresach.</Note>
        </>
      )
    case "no_settled_periods":
      return (
        <>
          {sentence}
          <Note>Żaden okres nie ma jeszcze Rozliczeń pracowników, więc nie ma z czym porównać.</Note>
        </>
      )
    case "ready":
      return (
        <>
          {sentence}
          <Summary preview={preview} />
          {preview.rows.map((row) => (
            <Row key={`${row.period}-${row.row}`} row={row} />
          ))}
          {preview.more === 0 ? null : (
            <Note>
              I jeszcze {preview.more} {plural(preview.more, ROWS)} z różnicą.
            </Note>
          )}
        </>
      )
    default: {
      const unhandled: never = preview

      return unhandled
    }
  }
}

function Note({ children }: { children: React.ReactNode }) {
  return (
    <p role="listitem" className="px-4 py-3 text-sm text-pretty text-muted-foreground">
      {children}
    </p>
  )
}

function Summary({ preview }: { preview: PreviewReady }) {
  const files = preview.files.length

  return (
    <div role="listitem" aria-label="Skutek" className="flex flex-col gap-1 px-4 py-3">
      <p className="text-sm font-medium tabular-nums">
        {preview.changed === 0
          ? "Żaden wiersz się nie zmieni."
          : `Zmieni się ${preview.changed} ${plural(preview.changed, ROWS)}, w ${preview.changed_as_tata} będzie tak, jak wpisałeś.`}
      </p>
      <p className="text-sm text-muted-foreground tabular-nums">
        {files} {plural(files, { one: "ostatni Plik zbiorczy", few: "ostatnie Pliki zbiorcze", many: "ostatnich Plików zbiorczych" })}
        {" · "}różnice z Kontroli ilości: {preview.differences_before} → {preview.differences_after}
      </p>
      <UnreadPeriods periods={preview.unread} />
    </div>
  )
}

/**
 * Okresy po Przebiegu rozliczeń, których Pliku zbiorczego nie dało się przeczytać: jedno zdanie, bez okresów nic. Mówi
 * je podgląd zmiany reguły i podpowiedzi sekcji Urządzenia, bo oba czytają ostatnie Pliki zbiorcze.
 */
export function UnreadPeriods({ periods, className }: { periods: ReadonlyArray<string>; className?: string }) {
  if (periods.length === 0) {
    return null
  }

  return <p className={cn("text-sm text-muted-foreground", className)}>Nie dało się przeczytać Pliku zbiorczego okresu {periods.join(", ")}.</p>
}

function Row({ row }: { row: PreviewRow }) {
  return (
    <div role="listitem" aria-label={`Wiersz ${row.row}`} className="flex flex-col gap-2 px-4 py-3 text-sm">
      <p className="text-muted-foreground tabular-nums">
        {row.period} · wiersz {row.row} · {row.when}
      </p>
      <p className="text-pretty">
        <span className="text-muted-foreground">URZĄDZENIA </span>
        {row.devices === "" ? "(puste)" : row.devices}
        {row.activities === "" ? null : (
          <>
            <span className="text-muted-foreground"> · CZYNNOŚCI </span>
            {row.activities}
          </>
        )}
      </p>
      <ul className="flex flex-col gap-1">
        {row.cells.map((cell) => (
          <li key={cell.column} className="flex flex-wrap items-center gap-x-2 tabular-nums">
            <Badge variant="secondary" className="font-mono" aria-label={`kolumna ${cell.column}`}>
              {cell.column}
            </Badge>
            <span>
              {cell.before} → {cell.after}
            </span>
            <span className="text-muted-foreground">· wpisałeś {cell.tata}</span>
          </li>
        ))}
      </ul>
      {row.sums.map((sum) => (
        <div key={sum.column} className="flex flex-col gap-1 rounded-lg bg-muted/50 px-3 py-2">
          <p className="tabular-nums">
            {columnLabel({ letter: sum.column, name: sum.name })} = {sum.total}, bo reguły:
          </p>
          <ul className="flex list-disc flex-col gap-1 pl-5 text-muted-foreground">
            {sum.rules.map((rule) => (
              <li key={rule.id}>
                <Sentence parts={rule.sentence} />
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  )
}
