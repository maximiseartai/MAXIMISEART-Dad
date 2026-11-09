import { cn } from "cn"
import { ChevronRightIcon, CircleCheckIcon, CircleDashedIcon, CircleMinusIcon } from "lucide-react"

import { getQuantitiesToFill, type QuantitiesToFill } from "@/api/centrum"
import type { DescriptionColumn, KindToFill, QuantitiesToFillReady, RowState } from "@/api/generated"
import { zFillKind } from "@/api/generated/zod.gen"
import { LoadFailure } from "@/components/load-failure"
import { ThreePartMessage } from "@/components/three-part-message"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { href, usePagePath } from "@/lib/address"
import { useContentEntrance } from "@/lib/content-entrance"
import { plural } from "@/lib/format"
import { useLiveFile } from "@/lib/use-live-file"
import type { Resource } from "@/lib/use-resource"
import { AfterSettlement, afterSettlementHint } from "@/pages/filling/after-settlement"
import { BackLink } from "@/pages/filling/back-link"
import { FillingHeader, KindPage } from "@/pages/filling/kind-page"
import { KIND_TITLES, ROW_STATES } from "@/pages/filling/labels"
import { ReadyForSettlement } from "@/pages/filling/ready-for-settlement"
import { SaveHint } from "@/pages/filling/save-hint"

// Numer wiersza w podsumowaniu po jego stanie z serwera. Numer do uzupełnienia nie ma słowa: zwykły numer to ten,
// który jeszcze czeka.
const CHIPS: Record<RowState, { look: string; spoken: boolean }> = {
  to_fill: { look: "bg-secondary", spoken: false },
  done: { look: "text-muted-foreground line-through decoration-muted-foreground/50", spoken: true },
  without_quantity: { look: "border border-dashed text-muted-foreground", spoken: true },
}

/** Podsumowanie Uzupełnienia pliku zbiorczego okresu z adresu `#/uzupelnienie/<okres>`. */
export function FillingPage() {
  const [token = "", part] = usePagePath()
  const kind = zFillKind.safeParse(part)

  if (kind.success) {
    return (
      <KindPage key={`${token}/${kind.data}`} token={token} kind={kind.data} />
    )
  }

  return (
    <>
      <BackLink to={href("okresy")}>Okresy</BackLink>
      <FillingContent key={token} token={token} />
    </>
  )
}

function FillingContent({ token }: { token: string }) {
  const { resource, reload } = useLiveFile(getQuantitiesToFill, [token])

  return (
    <>
      <FillingHeader token={token} resource={resource} />
      <FillingState token={token} resource={resource} reload={reload} />
    </>
  )
}

function FillingState({
  token,
  resource,
  reload,
}: {
  token: string
  resource: Resource<QuantitiesToFill>
  reload: () => Promise<void>
}) {
  const entrance = useContentEntrance(resource.state === "loading")

  switch (resource.state) {
    case "loading":
      return <FillingSkeleton />
    case "failed":
      return (
        <LoadFailure what="okresu" message={resource.message} reload={reload} />
      )
    case "ready": {
      const found = resource.data

      return found.state === "problem" ? (
        <div className={cn(entrance, "flex flex-col gap-3")}>
          <ThreePartMessage message={found.message} kind="notice" />
          <ReadyForSettlement token={token} />
        </div>
      ) : (
        <div className={cn(entrance, "flex flex-col gap-3")}>
          {found.settled ? <AfterSettlement /> : null}
          <FillingSummary token={token} found={found} />
          {/* Po Przebiegu strona jest podglądem: nikt już nie wpisuje, więc wskazówka o zapisie nie ma sensu. */}
          {found.settled ? null : <SaveHint read={found.read} />}
          {found.settled ? null : <ReadyForSettlement token={token} />}
        </div>
      )
    }

    default: {
      const unhandled: never = resource

      return unhandled
    }
  }
}

/** Podsumowanie: rodzaje z listą i kolumny z opisu technika; pokazuje je też karta wyniku Przygotowania. */
export function FillingSummary({ token, found }: { token: string; found: QuantitiesToFillReady }) {
  return (
    <Card className="py-0">
      <CardContent className="divide-y px-0">
        {found.kinds.map((kind) => (
          <KindSection key={kind.kind} token={token} kind={kind} settled={found.settled} />
        ))}
        <DescriptionColumns columns={found.description_columns} />
      </CardContent>
    </Card>
  )
}

function KindSection({ token, kind, settled }: { token: string; kind: KindToFill; settled: boolean }) {
  const title = KIND_TITLES[kind.kind]
  const doneRows = kind.rows.filter((row) => row.state === "done").length

  return (
    <section aria-label={title} className="flex gap-3 px-6 py-5">
      {kind.done ? (
        <CircleCheckIcon className="mt-0.5 size-5 shrink-0 text-success" aria-label="Zrobione" />
      ) : settled ? (
        <CircleMinusIcon className="mt-0.5 size-5 shrink-0 text-muted-foreground" aria-label="Bez ilości" />
      ) : (
        <CircleDashedIcon className="mt-0.5 size-5 shrink-0 text-muted-foreground" aria-label="Do uzupełnienia" />
      )}
      <div className="flex min-w-0 flex-1 flex-col gap-3">
        <a
          href={kind.rows.length === 0 ? undefined : href("uzupelnienie", token, kind.kind)}
          className="-mx-2 -my-1 flex items-center gap-3 rounded-md px-2 py-1 transition-[background-color,scale] duration-150 ease-out [&[href]]:active:scale-[0.99] [&[href]]:active:bg-muted"
        >
          <div className="flex flex-col gap-0.5">
            <h2 className="font-medium">{title}</h2>
            <p className="text-sm text-muted-foreground">
              {kind.rows.length === 0 ? "Nie ma takich wierszy." : settled ? afterSettlementHint(kind.rows) : kind.hint}
            </p>
          </div>
          {kind.rows.length === 0 ? null : (
            <>
              <span className="ml-auto text-sm font-medium tabular-nums">
                {doneRows} z {kind.rows.length}
              </span>
              <ChevronRightIcon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
            </>
          )}
        </a>
        {kind.rows.length === 0 ? null : (
          <ul aria-label={`Numery wierszy: ${title}`} className="flex flex-wrap gap-1.5">
            {kind.rows.map(({ row, state }) => (
              <li key={row} className={cn("rounded-md px-1.5 py-0.5 font-mono text-xs tabular-nums", CHIPS[state].look)}>
                {row}
                {CHIPS[state].spoken ? (
                  <span className={ROW_STATES[state].shown ? "ml-1 font-sans" : "sr-only"}> {ROW_STATES[state].label}</span>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  )
}

/** Przypomnienie o kolumnach z opisu technika: bez stanu „zrobione”, tylko w ilu wierszach coś wpisano. */
function DescriptionColumns({ columns }: { columns: ReadonlyArray<DescriptionColumn> }) {
  return (
    <section aria-label="Kolumny z opisu technika" className="flex flex-col gap-3 px-6 py-5 pl-14">
      <div className="flex flex-col gap-0.5">
        <h2 className="font-medium">Kolumny z opisu technika</h2>
        <p className="text-sm text-muted-foreground">W każdym wierszu według CZYNNOŚCI ZREALIZOWANE.</p>
      </div>
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
        {columns.map(({ column, rows }) => (
          <div key={column} className="flex flex-col gap-0.5 rounded-md bg-muted/50 px-2.5 py-2">
            <dt className="font-mono text-sm font-medium">{column}</dt>
            <dd className="text-xs text-muted-foreground">{rows === 0 ? "nic nie wpisano" : `wpisane w ${rows} ${plural(rows, { one: "wierszu", few: "wierszach", many: "wierszach" })}`}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

export function FillingSkeleton() {
  return (
    <Card aria-busy="true" aria-label="Wczytywanie Ilości do uzupełnienia">
      <CardContent className="flex flex-col gap-5 py-2">
        {[0, 1].map((kind) => (
          <div key={kind} className="flex flex-col gap-3">
            <Skeleton className="h-5 w-48" />
            <Skeleton className="h-6 w-80" />
          </div>
        ))}
        <Skeleton className="h-14 w-full" />
      </CardContent>
    </Card>
  )
}
