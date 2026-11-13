import * as React from "react"
import { XIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog"
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue } from "@/components/ui/select"
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
} from "@/components/ui/sidebar"
import { closeSettings, settingsHref, showSection, useSettingsAddress } from "@/lib/address"
import { useViewTiming } from "@/lib/view-timing"
import { ConfigurationProvider } from "@/pages/settings/configuration"
import { sectionOf, SETTINGS_SECTIONS, SHOWN_GROUPS, type SettingsSection } from "@/pages/settings/sections"

/** Okno Ustawień mierzy się jak strona (pomiar u taty), pod identyfikatorem z kontraktu. */
const SETTINGS_VIEW = { id: "ustawienia" } as const

const SIDEBAR = { "--sidebar-width": "15rem" } satisfies React.CSSProperties

const SECTION_ITEMS = SETTINGS_SECTIONS.map((section) => ({ value: section.id, label: section.title }))

/**
 * Okno Ustawień nad rozmytym Centrum (ADR 0032, wzór: ustawienia T3 Code). Otwiera je adres `#/ustawienia/<sekcja>`,
 * a Esc, ✕ i klik w tło zamykają je bez zmiany strony pod spodem. Po lewej sekcje w grupach, u góry ścieżka
 * „Ustawienia / <sekcja>”; na wąskim oknie przeglądarki okno zajmuje cały ekran, a sekcje są rozwijanym wyborem.
 */
export function SettingsDialog() {
  const address = useSettingsAddress()
  const open = address !== null
  // Okno zamyka się z animacją, więc do jej końca pokazuje ostatnią sekcję, zamiast znikać z pustą treścią.
  const [shown, setShown] = React.useState<SettingsSection>(() => sectionOf(address ?? ""))
  const section = open ? sectionOf(address) : shown

  if (section !== shown) {
    setShown(section)
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          closeSettings()
        }
      }}
    >
      <DialogContent
        showCloseButton={false}
        className="top-0 left-0 h-dvh max-h-none w-dvw max-w-none translate-x-0 translate-y-0 gap-0 overflow-hidden rounded-none p-0 sm:max-w-none md:top-1/2 md:left-1/2 md:h-[min(44rem,calc(100dvh-4rem))] md:w-[min(60rem,calc(100%-4rem))] md:-translate-x-1/2 md:-translate-y-1/2 md:rounded-xl"
      >
        {open ? <SettingsTiming /> : null}
        <ConfigurationProvider>
          <SidebarProvider className="h-full min-h-0 items-stretch" style={SIDEBAR}>
            <Sidebar collapsible="none" className="hidden border-r md:flex">
              <SidebarContent className="py-2">
                {SHOWN_GROUPS.map(({ group, sections }) => (
                  <SidebarGroup key={group} className="py-1">
                    <SidebarGroupLabel id={`ustawienia-${group}`}>{group}</SidebarGroupLabel>
                    <SidebarGroupContent>
                      <SidebarMenu aria-labelledby={`ustawienia-${group}`}>
                        {sections.map((item) => (
                          <SidebarMenuItem key={item.id}>
                            <SidebarMenuButton
                              isActive={item.id === section.id}
                              render={
                                <a
                                  href={settingsHref(item.id)}
                                  aria-current={item.id === section.id ? "page" : undefined}
                                  onClick={(event) => {
                                    event.preventDefault()
                                    showSection(item.id)
                                  }}
                                />
                              }
                            >
                              <item.icon />
                              <span>{item.title}</span>
                            </SidebarMenuButton>
                          </SidebarMenuItem>
                        ))}
                      </SidebarMenu>
                    </SidebarGroupContent>
                  </SidebarGroup>
                ))}
              </SidebarContent>
            </Sidebar>
            <div className="flex min-w-0 flex-1 flex-col">
              <div className="flex h-14 shrink-0 items-center gap-2 border-b px-4 md:px-6">
                <DialogTitle
                  data-page={SETTINGS_VIEW.id}
                  className="flex min-w-0 items-center gap-2 text-sm font-normal text-muted-foreground"
                >
                  Ustawienia
                  <span aria-hidden>/</span>
                  <span className="truncate font-medium text-foreground">{section.title}</span>
                </DialogTitle>
                <Button variant="ghost" size="icon-sm" className="ml-auto" aria-label="Zamknij Ustawienia" onClick={closeSettings}>
                  <XIcon />
                </Button>
              </div>
              <div className="border-b px-4 py-3 md:hidden">
                <SectionSelect section={section} />
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto px-4 py-6 md:px-10">
                <div data-slot="settings-section" className="mx-auto flex w-full max-w-2xl flex-col gap-4">
                  <section.Content />
                </div>
              </div>
            </div>
          </SidebarProvider>
        </ConfigurationProvider>
      </DialogContent>
    </Dialog>
  )
}

/** Wybór sekcji na wąskim oknie przeglądarki, w tych samych grupach co lista po lewej. */
function SectionSelect({ section }: { section: SettingsSection }) {
  return (
    <Select items={SECTION_ITEMS} value={section.id} onValueChange={(value) => (value === null ? null : showSection(value))}>
      <SelectTrigger className="w-full" aria-label="Sekcja Ustawień">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {SHOWN_GROUPS.map(({ group, sections }) => (
          <SelectGroup key={group}>
            <SelectLabel>{group}</SelectLabel>
            {sections.map((item) => (
              <SelectItem key={item.id} value={item.id}>
                {item.title}
              </SelectItem>
            ))}
          </SelectGroup>
        ))}
      </SelectContent>
    </Select>
  )
}

/** Jeden pomiar na otwarcie okna: zimny start na adresie okna albo przejście z otwartej strony. */
function SettingsTiming() {
  useViewTiming(SETTINGS_VIEW)

  return null
}
