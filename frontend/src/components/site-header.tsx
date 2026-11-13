import { ActiveRunLink } from "@/components/active-run"
import { SidebarTrigger } from "@/components/ui/sidebar"
import { NotificationsBell } from "@/components/notifications-bell"
import { WriteToMaks } from "@/components/write-to-maks"
import { NOTIFICATIONS_PAGE, useCurrentPage } from "@/pages"

// Nagłówek bez tytułu: tytuł jest w treści strony (`PageHeader`). Motyw zmienia się w oknie Ustawień (sekcja Wygląd).
export function SiteHeader() {
  const page = useCurrentPage()

  return (
    <header className="flex h-(--header-height) shrink-0 items-center gap-2 px-4 lg:px-6">
      <SidebarTrigger className="-ml-1" aria-label="Pokaż lub ukryj menu" />
      <div className="ml-auto flex items-center gap-1">
        <ActiveRunLink current={page.id} />
        <WriteToMaks />
        <NotificationsBell current={page.id === NOTIFICATIONS_PAGE.id} />
      </div>
    </header>
  )
}
