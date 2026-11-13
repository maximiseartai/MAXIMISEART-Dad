import type * as React from "react"
import {
  ArchiveRestoreIcon,
  BellIcon,
  FileSpreadsheetIcon,
  FolderIcon,
  HistoryIcon,
  InboxIcon,
  ListChecksIcon,
  MailIcon,
  PaletteIcon,
  RouterIcon,
  UsersIcon,
  WrenchIcon,
  type LucideIcon,
} from "lucide-react"

import { FOLDERS_SECTION } from "@/components/setting-path"
import { AppearanceSection } from "@/pages/settings/appearance-section"
import { FoldersSection } from "@/pages/settings/folders-section"
import { HistorySection } from "@/pages/settings/history-section"
import { InboxSection } from "@/pages/settings/inbox-section"
import { IntermaxCopiesSection } from "@/pages/settings/intermax-copies-section"
import { REMINDERS_SECTION, RemindersSection } from "@/pages/settings/reminders-section"
import { DevicesSection, QuantityRulesSection } from "@/pages/settings/quantity-rules-section"
import { ReportsSection } from "@/pages/settings/reports-section"
import { TemplatesSection } from "@/pages/settings/templates-section"
import { ToolSection } from "@/pages/settings/tool-section"
import { WorkersSection } from "@/pages/settings/workers-section"

/** Grupy sekcji okna Ustawień w kolejności z ADR 0032; grupa bez żadnej sekcji się nie pokazuje. */
const SETTINGS_GROUPS = ["Praca", "Ilości", "Pliki", "Połączenia", "Narzędzie", "Historia"] as const

type SettingsGroup = (typeof SETTINGS_GROUPS)[number]

/**
 * Sekcje okna Ustawień. Nowa sekcja to nowy wpis: lista po lewej, rozwijany wybór na wąskim oknie, adres
 * `#/ustawienia/<id>` i ścieżka „Ustawienia / <title>” biorą się stąd. W grupie sekcje stoją w kolejności wpisów.
 */
export const SETTINGS_SECTIONS = [
  { id: FOLDERS_SECTION, title: "Foldery", group: "Praca", icon: FolderIcon, Content: FoldersSection },
  { id: "wykonawcy", title: "Wykonawcy", group: "Praca", icon: UsersIcon, Content: WorkersSection },
  { id: REMINDERS_SECTION, title: "Przypomnienia", group: "Praca", icon: BellIcon, Content: RemindersSection },
  { id: "reguly-ilosci", title: "Reguły ilości", group: "Ilości", icon: ListChecksIcon, Content: QuantityRulesSection },
  { id: "urzadzenia", title: "Urządzenia", group: "Ilości", icon: RouterIcon, Content: DevicesSection },
  { id: "wzorce", title: "Wzorce", group: "Pliki", icon: FileSpreadsheetIcon, Content: TemplatesSection },
  { id: "kopie-intermax", title: "Kopie INTERMAX", group: "Pliki", icon: ArchiveRestoreIcon, Content: IntermaxCopiesSection },
  { id: "skrzynka-raportow", title: "Skrzynka raportów", group: "Połączenia", icon: MailIcon, Content: InboxSection },
  { id: "zgloszenia", title: "Zgłoszenia", group: "Połączenia", icon: InboxIcon, Content: ReportsSection },
  { id: "narzedzie", title: "Narzędzie", group: "Narzędzie", icon: WrenchIcon, Content: ToolSection },
  { id: "wyglad", title: "Wygląd", group: "Narzędzie", icon: PaletteIcon, Content: AppearanceSection },
  { id: "historia", title: "Historia", group: "Historia", icon: HistoryIcon, Content: HistorySection },
] as const satisfies ReadonlyArray<{
  id: string
  title: string
  group: SettingsGroup
  icon: LucideIcon
  Content: React.ComponentType
}>

export type SettingsSection = (typeof SETTINGS_SECTIONS)[number]

/** Grupy, które mają co najmniej jedną sekcję, każda ze swoimi sekcjami. */
export const SHOWN_GROUPS = SETTINGS_GROUPS.flatMap((group) => {
  const sections = SETTINGS_SECTIONS.filter((section) => section.group === group)

  return sections.length === 0 ? [] : [{ group, sections }]
})

/** Sekcja z członu adresu; nieznany albo pusty człon otwiera pierwszą sekcję. */
export function sectionOf(id: string): SettingsSection {
  return SETTINGS_SECTIONS.find((section) => section.id === id) ?? SETTINGS_SECTIONS[0]
}
