import * as React from "react"
import {
  ArchiveRestoreIcon,
  BellIcon,
  BookTextIcon,
  FileSpreadsheetIcon,
  FolderIcon,
  HistoryIcon,
  InboxIcon,
  ListChecksIcon,
  MailIcon,
  PaletteIcon,
  RouterIcon,
  SendIcon,
  UsersIcon,
  WrenchIcon,
  type LucideIcon,
} from "lucide-react"

import type { CentrumFunction } from "@/api/generated"
import { FOLDERS_SECTION } from "@/components/setting-path"
import { useInScope } from "@/lib/scope"
import { ActivityLegendSection } from "@/pages/settings/activity-legend-section"
import { AppearanceSection } from "@/pages/settings/appearance-section"
import { DevicesSection } from "@/pages/settings/devices-section"
import { FoldersSection } from "@/pages/settings/folders-section"
import { HistorySection } from "@/pages/settings/history-section"
import { InboxSection } from "@/pages/settings/inbox-section"
import { IntermaxCopiesSection } from "@/pages/settings/intermax-copies-section"
import { QuantityRulesSection } from "@/pages/settings/quantity-rules-section"
import { REMINDERS_SECTION, RemindersSection } from "@/pages/settings/reminders-section"
import { ReportsSection } from "@/pages/settings/reports-section"
import { SETTLEMENT_MAIL_SECTION, SettlementMailSection } from "@/pages/settings/settlement-mail-section"
import { TemplatesSection } from "@/pages/settings/templates-section"
import { ToolSection } from "@/pages/settings/tool-section"
import { WORKERS_SECTION, WorkersSection } from "@/pages/settings/workers-section"

const SETTINGS_GROUPS = ["Praca", "Ilości", "Pliki", "Połączenia", "Narzędzie", "Historia"] as const

type SettingsGroup = (typeof SETTINGS_GROUPS)[number]

const SETTINGS_SECTIONS = [
  { id: FOLDERS_SECTION, title: "Foldery", group: "Praca", icon: FolderIcon, Content: FoldersSection, function: null },
  { id: WORKERS_SECTION, title: "Wykonawcy", group: "Praca", icon: UsersIcon, Content: WorkersSection, function: "workers" },
  {
    id: REMINDERS_SECTION,
    title: "Przypomnienia",
    group: "Praca",
    icon: BellIcon,
    Content: RemindersSection,
    function: "reminders",
  },
  {
    id: SETTLEMENT_MAIL_SECTION,
    title: "Wysyłka rozliczeń",
    group: "Praca",
    icon: SendIcon,
    Content: SettlementMailSection,
    function: "settlement_mailing",
  },
  {
    id: "reguly-ilosci",
    title: "Reguły ilości",
    group: "Ilości",
    icon: ListChecksIcon,
    Content: QuantityRulesSection,
    function: "quantities",
  },
  { id: "urzadzenia", title: "Urządzenia", group: "Ilości", icon: RouterIcon, Content: DevicesSection, function: "quantities" },
  {
    id: "legenda-czynnosci",
    title: "Legenda czynności",
    group: "Ilości",
    icon: BookTextIcon,
    Content: ActivityLegendSection,
    function: "quantities",
  },
  { id: "wzorce", title: "Wzorce", group: "Pliki", icon: FileSpreadsheetIcon, Content: TemplatesSection, function: "templates" },
  {
    id: "kopie-intermax",
    title: "Kopie INTERMAX",
    group: "Pliki",
    icon: ArchiveRestoreIcon,
    Content: IntermaxCopiesSection,
    function: "intermax_copies",
  },
  {
    id: "skrzynka-raportow",
    title: "Skrzynka raportów",
    group: "Połączenia",
    icon: MailIcon,
    Content: InboxSection,
    function: "report_inbox",
  },
  { id: "zgloszenia", title: "Zgłoszenia", group: "Połączenia", icon: InboxIcon, Content: ReportsSection, function: null },
  { id: "narzedzie", title: "Narzędzie", group: "Narzędzie", icon: WrenchIcon, Content: ToolSection, function: null },
  { id: "wyglad", title: "Wygląd", group: "Narzędzie", icon: PaletteIcon, Content: AppearanceSection, function: null },
  { id: "historia", title: "Historia", group: "Historia", icon: HistoryIcon, Content: HistorySection, function: null },
] as const satisfies ReadonlyArray<{
  id: string
  title: string
  group: SettingsGroup
  icon: LucideIcon
  Content: React.ComponentType
  function: CentrumFunction | null
}>

export type SettingsSection = (typeof SETTINGS_SECTIONS)[number]

export type ShownSections = {
  sections: ReadonlyArray<SettingsSection>
  groups: ReadonlyArray<{ group: SettingsGroup; sections: ReadonlyArray<SettingsSection> }>
  sectionOf: (id: string) => SettingsSection
}

export function useShownSections(): ShownSections {
  const sections = useInScope(SETTINGS_SECTIONS)

  return React.useMemo(() => {
    const [first] = sections

    if (first === undefined) {
      throw new Error("Okno Ustawień nie ma żadnej sekcji w Zakresie.")
    }

    return {
      sections,
      groups: SETTINGS_GROUPS.flatMap((group) => {
        const inGroup = sections.filter((section) => section.group === group)

        return inGroup.length === 0 ? [] : [{ group, sections: inGroup }]
      }),
      sectionOf: (id) => sections.find((section) => section.id === id) ?? first,
    }
  }, [sections])
}
