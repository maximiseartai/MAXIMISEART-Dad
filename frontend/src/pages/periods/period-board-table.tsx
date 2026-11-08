import * as React from "react"
import { FileSpreadsheetIcon, FileTextIcon, FolderOpenIcon, UsersIcon } from "lucide-react"

import type { OpenTarget, PeriodRow } from "@/api/centrum"
import { PeriodStatusBadge } from "@/components/period-status-badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { shortDate } from "@/lib/format"
import { openAndConfirm } from "@/pages/periods/open-period-path"
import { FillLink } from "@/pages/filling/fill-link"
import { FillStepLink, PrepareLink } from "@/pages/periods/prepare-actions"

/** Tablica okresów: od najnowszego, ostatni pełny okres wyróżniony tłem. */
export function PeriodBoardTable({
  periods,
  onStale,
}: {
  periods: ReadonlyArray<PeriodRow>
  onStale: () => void
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle id="tablica-okresow">Tablica okresów</CardTitle>
      </CardHeader>
      <CardContent>
        <Table aria-labelledby="tablica-okresow">
          <TableHeader>
            <TableRow>
              <TableHead>Okres</TableHead>
              <TableHead>Status okresu</TableHead>
              <TableHead>Pliki</TableHead>
              <TableHead className="text-right">Następny krok</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {periods.map((period) => (
              <PeriodBoardRow key={period.token} period={period} onStale={onStale} />
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

function PeriodBoardRow({ period, onStale }: { period: PeriodRow; onStale: () => void }) {
  const step = period.next_step

  return (
    <TableRow data-state={period.last_complete ? "selected" : undefined}>
      <TableCell>
        <div className="flex flex-col">
          <span className="font-medium tabular-nums">{period.token}</span>
          <span className="text-xs text-muted-foreground tabular-nums">
            {shortDate(period.tuesday)} – {shortDate(period.monday)}
            {period.last_complete ? <span className="sr-only">, ostatni pełny okres</span> : null}
          </span>
        </div>
      </TableCell>
      <TableCell>
        <PeriodStatusBadge period={period} />
      </TableCell>
      <TableCell>
        <PeriodFiles period={period} onStale={onStale} />
      </TableCell>
      <TableCell className="text-right">
        {/* Okres z Plikiem zbiorczym przygotowanym po Uzupełnieniu w Excelu nadal prowadzi na jego podsumowanie. */}
        {period.fillable && step.action !== "fill_collective_file" ? (
          <FillLink token={period.token} variant="ghost" size="sm" aria-label={`Uzupełnij, okres ${period.token}`} />
        ) : null}
        {period.secondary_step === null ? null : (
          <PrepareLink period={period} step={period.secondary_step} secondary />
        )}
        {step.action === "fill_collective_file" ? (
          <>
            <PrepareLink period={period} step={step.then} secondary />
            <FillStepLink period={period} step={step} />
          </>
        ) : step.action !== "none" ? (
          <PrepareLink period={period} step={step} secondary={false} />
        ) : (
          <Tooltip>
            <TooltipTrigger
              render={
                <span
                  tabIndex={0}
                  className="rounded-md text-sm text-muted-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
                />
              }
            >
              Zamknięty
            </TooltipTrigger>
            <TooltipContent>{step.hint}</TooltipContent>
          </Tooltip>
        )}
      </TableCell>
    </TableRow>
  )
}

function PeriodFiles({ period, onStale }: { period: PeriodRow; onStale: () => void }) {
  const open = (target: OpenTarget) => openAndConfirm(period.token, { target }, onStale)

  return (
    <div className="flex items-center gap-0.5">
      <FileButton
        label="Rozliczenie wewnętrzne"
        token={period.token}
        icon={<FileTextIcon />}
        exists={period.internal_settlement_exists}
        onOpen={() => open("internal_settlement")}
      />
      <FileButton
        label="Plik zbiorczy"
        token={period.token}
        icon={<FileSpreadsheetIcon />}
        exists={period.collective_file_exists}
        onOpen={() => open("collective_file")}
      />
      <FileButton
        label="Folder okresu"
        token={period.token}
        icon={<FolderOpenIcon />}
        exists={period.period_folder_exists}
        onOpen={() => open("period_folder")}
      />
      <FileButton
        label="Rozliczenia pracowników"
        token={period.token}
        icon={<UsersIcon data-icon="inline-start" />}
        exists={period.worker_settlements_folder_exists}
        count={period.worker_settlements_folder_exists ? period.worker_settlement_count : undefined}
        onOpen={() => open("worker_settlements_folder")}
      />
    </div>
  )
}

/**
 * Przycisk pliku albo folderu okresu. Brakujący plik niczego nie otwiera, ale przycisk zostaje w zasięgu myszy,
 * klawiatury i palca (`aria-disabled` zamiast `disabled`), żeby podpowiedź „jeszcze nie ma” dało się zobaczyć:
 * kliknięcie albo stuknięcie w niego pokazuje ją jak najechanie.
 */
function FileButton({
  label,
  token,
  icon,
  exists,
  count,
  onOpen,
}: {
  label: string
  token: string
  icon: React.ReactNode
  exists: boolean
  count?: number
  onOpen: () => void
}) {
  const [hinted, setHinted] = React.useState(false)
  const description = count === undefined ? label : `${label}: ${count}`

  return (
    <Tooltip
      open={hinted}
      onOpenChange={(open, details) => {
        // Kliknięcie w brakujący plik nie chowa podpowiedzi: to ona jest odpowiedzią na nie.
        if (open || exists || details.reason !== "trigger-press") {
          setHinted(open)
        }
      }}
    >
      <TooltipTrigger
        render={
          <Button
            variant="ghost"
            size={count === undefined ? "icon-sm" : "sm"}
            aria-disabled={!exists}
            aria-label={`${description}, okres ${token}`}
            className="aria-disabled:cursor-default aria-disabled:opacity-50 aria-disabled:hover:bg-transparent aria-disabled:active:scale-100"
            onClick={exists ? onOpen : () => setHinted(true)}
          />
        }
      >
        {icon}
        {count === undefined ? null : <span className="tabular-nums">{count}</span>}
      </TooltipTrigger>
      <TooltipContent>{exists ? description : `${label}: jeszcze nie ma`}</TooltipContent>
    </Tooltip>
  )
}
