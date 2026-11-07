import { BellIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useNotifications } from "@/lib/notifications"
import { href } from "@/lib/address"
import { NOTIFICATIONS_PAGE } from "@/pages"

/** Dzwonek w nagłówku: prowadzi do widoku Powiadomienia, czerwona kropka znaczy nowe Powiadomienia. */
export function NotificationsBell({ current }: { current: boolean }) {
  const { notifications } = useNotifications()
  const unread = notifications.state === "ready" && notifications.data.unread > 0

  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            variant="ghost"
            size="icon"
            nativeButton={false}
            aria-label={unread ? "Powiadomienia, są nowe" : "Powiadomienia"}
            aria-current={current ? "page" : undefined}
            className="relative aria-[current=page]:bg-muted"
            render={<a href={href(NOTIFICATIONS_PAGE.id)} />}
          />
        }
      >
        <BellIcon />
        {unread ? (
          <span className="absolute top-1.5 right-1.5 size-2 rounded-full bg-destructive ring-2 ring-background" aria-hidden />
        ) : null}
      </TooltipTrigger>
      <TooltipContent>Powiadomienia</TooltipContent>
    </Tooltip>
  )
}
