import { CircleCheckIcon, TriangleAlertIcon } from "lucide-react"

import type { Configuration, TemplateProblem } from "@/api/generated"
import { ThreePartMessage } from "@/components/three-part-message"
import { Badge } from "@/components/ui/badge"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { WithConfiguration } from "@/pages/settings/configuration"
import { SettingRow, SettingsPanel } from "@/pages/settings/setting-row"

const PROBLEM_LABELS: Record<TemplateProblem["problem"], string> = {
  missing: "Brak pliku",
  open_in_excel: "Otwarty w Excelu",
  unreadable: "Nie przechodzi sprawdzenia",
}

/** Stan każdego Wzorca: gotowy albo problem z Komunikatem pod spodem. Wzorce tata zmienia w Excelu, nie tutaj. */
export function TemplatesSection() {
  return <WithConfiguration>{(configuration) => <Templates templates={configuration.templates} />}</WithConfiguration>
}

function Templates({ templates }: { templates: Configuration["templates"] }) {
  return (
    <SettingsPanel label="Wzorce">
      {templates.map((template) => (
        <SettingRow
          key={template.file_name}
          title={template.label}
          below={template.state === "problem" ? <ThreePartMessage message={template.message} kind={template.level} /> : null}
        >
          {template.state === "ready" ? (
            <Tooltip>
              <TooltipTrigger
                render={
                  <span tabIndex={0} className="rounded-full outline-none focus-visible:ring-3 focus-visible:ring-ring/50" />
                }
              >
                <CircleCheckIcon className="size-5 text-success" role="img" aria-label="Na miejscu i czytelny" />
              </TooltipTrigger>
              <TooltipContent>Na miejscu i czytelny: {template.file_name}</TooltipContent>
            </Tooltip>
          ) : (
            <Badge variant="outline">
              <TriangleAlertIcon
                data-icon="inline-start"
                className={template.level === "warning" ? "text-warning" : "text-destructive"}
              />
              {PROBLEM_LABELS[template.problem]}
            </Badge>
          )}
        </SettingRow>
      ))}
    </SettingsPanel>
  )
}
