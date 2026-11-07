import { cn } from "cn"
import {
  CircleCheckIcon,
  FileSpreadsheetIcon,
  LockIcon,
  TriangleAlertIcon,
  UserIcon,
} from "lucide-react"

import { getConfiguration, type Configuration, type TemplateProblem } from "@/api/centrum"
import { PageHeader } from "@/components/page-header"
import { LoadFailure } from "@/components/load-failure"
import { ThreePartMessage, type MessageKind } from "@/components/three-part-message"
import { Badge } from "@/components/ui/badge"
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Item, ItemActions, ItemContent, ItemMedia, ItemTitle } from "@/components/ui/item"
import { Skeleton } from "@/components/ui/skeleton"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useContentEntrance } from "@/lib/content-entrance"
import { useResource } from "@/lib/use-resource"
import { IntermaxCopiesCard } from "@/pages/configuration/intermax-copies-card"
import { ToolCard } from "@/pages/configuration/tool-card"

/**
 * Konfiguracja tylko do odczytu: czy Wzorce są gotowe, kto jest Wykonawcą i jaka jest wersja narzędzia (z jej
 * aktualizacją). Jedyną zmianą pliku taty stąd jest przywrócenie Kopii INTERMAX.
 */
export function ConfigurationPage() {
  const { resource: configuration, reload } = useResource(getConfiguration, [])
  const entrance = useContentEntrance(configuration.state === "loading")

  return (
    <>
      <PageHeader
        badge={<ReadOnlyBadge />}
        action={
          configuration.state === "ready" ? (
            <span className="text-sm text-muted-foreground">{REPORT_KEY_LABELS[configuration.data.reports]}</span>
          ) : undefined
        }
      />
      {configuration.state === "loading" ? <ConfigurationSkeleton /> : null}
      {configuration.state === "failed" ? (
        <LoadFailure what="konfiguracji" message={configuration.message} reload={reload} />
      ) : null}
      {configuration.state === "ready" ? (
        <div className={cn(entrance, "grid grid-cols-1 items-start gap-6 @4xl/main:grid-cols-2")}>
          <ToolCard
            version={configuration.data.version}
            freshness={configuration.data.freshness}
            offered={configuration.data.update_offered}
            onFinished={reload}
          />
          <TemplatesCard templates={configuration.data.templates} />
          <WorkersCard workers={configuration.data.workers} />
          <IntermaxCopiesCard />
        </div>
      ) : null}
    </>
  )
}

/** Czy na tym komputerze jest Token do Zgłoszeń i czy Skrzynka go przyjmuje; wartości tokenu serwer nigdy nie wysyła. */
const REPORT_KEY_LABELS: Record<Configuration["reports"], string> = {
  ready: "Zgłoszenia: gotowe",
  missing_key: "Zgłoszenia: brak tokenu",
  refused_key: "Zgłoszenia: token odrzucony",
}

function ReadOnlyBadge() {
  return (
    <Tooltip>
      <TooltipTrigger render={<Badge variant="outline" tabIndex={0} />}>
        <LockIcon data-icon="inline-start" />
        Tylko do odczytu
      </TooltipTrigger>
      <TooltipContent>Zmiany robi osoba utrzymująca narzędzie.</TooltipContent>
    </Tooltip>
  )
}

const PROBLEM_LABELS: Record<TemplateProblem["problem"], string> = {
  missing: "Brak pliku",
  open_in_excel: "Otwarty w Excelu",
  unreadable: "Nie przechodzi sprawdzenia",
}

const PROBLEM_KINDS: Record<TemplateProblem["problem"], MessageKind> = {
  missing: "stop",
  open_in_excel: "warning",
  unreadable: "stop",
}

function TemplatesCard({ templates }: { templates: Configuration["templates"] }) {
  const ready = templates.filter((template) => template.state === "ready").length
  const allReady = ready === templates.length

  return (
    <Card>
      <CardHeader>
        <CardTitle id="wzorce">Wzorce</CardTitle>
        <CardAction>
          <Badge variant={allReady ? "secondary" : "outline"} className="tabular-nums">
            {allReady ? (
              <CircleCheckIcon data-icon="inline-start" className="text-success" />
            ) : (
              <TriangleAlertIcon data-icon="inline-start" className="text-warning" />
            )}
            {ready} z {templates.length}
          </Badge>
        </CardAction>
      </CardHeader>
      <CardContent>
        <ul aria-labelledby="wzorce" className="flex flex-col gap-2">
          {templates.map((template) => (
            <li key={template.file_name} className="flex flex-col gap-2">
              <Item variant="muted" size="sm" role="group" aria-label={template.label}>
                <ItemMedia variant="icon">
                  <FileSpreadsheetIcon />
                </ItemMedia>
                <ItemContent>
                  <ItemTitle>{template.label}</ItemTitle>
                </ItemContent>
                <ItemActions>
                  {template.state === "ready" ? (
                    <Tooltip>
                      <TooltipTrigger
                        render={
                          <span
                            tabIndex={0}
                            className="rounded-full outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
                          />
                        }
                      >
                        <CircleCheckIcon
                          className="size-5 text-success"
                          role="img"
                          aria-label="Na miejscu i czytelny"
                        />
                      </TooltipTrigger>
                      <TooltipContent>Na miejscu i czytelny: {template.file_name}</TooltipContent>
                    </Tooltip>
                  ) : (
                    <Badge variant="outline">
                      <TriangleAlertIcon
                        data-icon="inline-start"
                        className={PROBLEM_KINDS[template.problem] === "warning" ? "text-warning" : "text-destructive"}
                      />
                      {PROBLEM_LABELS[template.problem]}
                    </Badge>
                  )}
                </ItemActions>
              </Item>
              {template.state === "problem" ? (
                <ThreePartMessage
                  message={template.message}
                  kind={PROBLEM_KINDS[template.problem]}
                />
              ) : null}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}

function WorkersCard({ workers }: { workers: Configuration["workers"] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle id="wykonawcy">Wykonawcy</CardTitle>
        {workers.state === "ready" ? (
          <CardAction>
            <Badge variant="secondary" className="tabular-nums">
              {workers.names.length}
            </Badge>
          </CardAction>
        ) : null}
      </CardHeader>
      <CardContent>
        {workers.state === "ready" ? (
          <ul aria-labelledby="wykonawcy" className="flex flex-wrap gap-2">
            {workers.names.map((name) => (
              <li key={name}>
                <Badge variant="outline" className="h-8 px-3 text-sm">
                  <UserIcon data-icon="inline-start" />
                  {name}
                </Badge>
              </li>
            ))}
          </ul>
        ) : (
          <ThreePartMessage message={workers.message} kind="stop" />
        )}
      </CardContent>
    </Card>
  )
}

function ConfigurationSkeleton() {
  return (
    <div
      className="grid grid-cols-1 gap-6 @4xl/main:grid-cols-2"
      aria-busy="true"
      aria-label="Wczytywanie konfiguracji"
    >
      <Skeleton className="h-20 rounded-xl @4xl/main:col-span-2" />
      <Skeleton className="h-64 rounded-xl" />
      <Skeleton className="h-64 rounded-xl" />
    </div>
  )
}
