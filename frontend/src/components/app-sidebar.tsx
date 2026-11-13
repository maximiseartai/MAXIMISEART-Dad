import type * as React from "react"
import { ReceiptTextIcon, SettingsIcon } from "lucide-react"

import { ActiveRunMark, RUNS_PAGE } from "@/components/active-run"
import { CloseCentrumButton } from "@/components/close-centrum"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar"
import { href, settingsHref } from "@/lib/address"
import { menuPageId, PAGES, type Page } from "@/pages"

export function AppSidebar({
  current,
  onClosed,
  ...props
}: React.ComponentProps<typeof Sidebar> & { current: Page; onClosed: () => void }) {
  return (
    <Sidebar collapsible="offcanvas" {...props}>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" render={<a href={href(PAGES[0].id)} />}>
              <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                <ReceiptTextIcon className="size-4" />
              </span>
              <span className="text-base font-semibold">Centrum rozliczeń</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu aria-label="Sekcje Centrum rozliczeń">
              {PAGES.filter((page) => page.menu).map((page) => (
                <SidebarMenuItem key={page.id}>
                  <SidebarMenuButton
                    isActive={page.id === menuPageId(current)}
                    tooltip={page.title}
                    render={
                      <a
                        href={href(page.id)}
                        aria-current={page.id === current.id ? "page" : undefined}
                      />
                    }
                  >
                    <page.icon />
                    <span>{page.title}</span>
                  </SidebarMenuButton>
                  {/* Obok linku, nie w nim: nazwa pozycji menu zostaje „Uruchomienia”. */}
                  {page.id === RUNS_PAGE ? (
                    <ActiveRunMark className="pointer-events-none absolute top-1/2 right-2 -translate-y-1/2" />
                  ) : null}
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter className="gap-0">
        {/* Nad „Zamknij Centrum rozliczeń”: okno Ustawień otwiera się nad bieżącą stroną (ADR 0032). */}
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton tooltip="Ustawienia" render={<a href={settingsHref()} />}>
              <SettingsIcon />
              <span>Ustawienia</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
        <CloseCentrumButton onClosed={onClosed} />
      </SidebarFooter>
    </Sidebar>
  )
}
