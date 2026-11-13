import * as React from "react"

import { AppSidebar } from "@/components/app-sidebar"
import { CentrumClosed } from "@/components/close-centrum"
import { CurrentPage } from "@/components/page-header"
import { SiteHeader } from "@/components/site-header"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"
import { Toaster } from "@/components/ui/toast"
import { TooltipProvider } from "@/components/ui/tooltip"
import { useHash } from "@/lib/address"
import { DadNoteProvider } from "@/lib/dad-note"
import { RunsProvider } from "@/lib/runs"
import { NotificationsProvider } from "@/lib/notifications"
import { SettingsProvider } from "@/lib/settings"
import { ToolUpdateProvider } from "@/lib/tool-update"
import { useViewTiming } from "@/lib/view-timing"
import { useCurrentPage, type Page } from "@/pages"
import { SettingsDialog } from "@/pages/settings/settings-dialog"

const LAYOUT = {
  "--sidebar-width": "calc(var(--spacing) * 66)",
  "--header-height": "calc(var(--spacing) * 14)",
} satisfies React.CSSProperties

export function App() {
  const page = useCurrentPage()
  const address = useHash()
  const [closed, setClosed] = React.useState(false)

  if (closed) {
    return <CentrumClosed />
  }

  return (
    <SettingsProvider>
      <TooltipProvider>
        <Toaster>
          <RunsProvider>
          <ToolUpdateProvider>
          <NotificationsProvider page={page.id}>
          <DadNoteProvider>
          <SidebarProvider style={LAYOUT}>
            <AppSidebar variant="inset" current={page} onClosed={() => setClosed(true)} />
            <SidebarInset>
              <SiteHeader />
              <div className="@container/main mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-4 pb-10 lg:px-8">
                <CurrentPage value={page}>
                  <page.Content />
                </CurrentPage>
                {/* Każdy adres strony to osobny widok, także w jej obrębie (`#/uzupelnienie/<okres>/<rodzaj>`); okno
                    Ustawień nad stroną nie zmienia jej adresu i mierzy się samo. */}
                <ViewTiming key={address} page={page} />
              </div>
            </SidebarInset>
          </SidebarProvider>
          <SettingsDialog />
          </DadNoteProvider>
          </NotificationsProvider>
          </ToolUpdateProvider>
          </RunsProvider>
        </Toaster>
      </TooltipProvider>
    </SettingsProvider>
  )
}

function ViewTiming({ page }: { page: Page }) {
  useViewTiming(page)

  return null
}
