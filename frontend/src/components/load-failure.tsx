import * as React from "react"
import { cn } from "cn"
import { RotateCwIcon } from "lucide-react"

import { Alert, AlertAction, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"

export function LoadFailure({
  what,
  message,
  reload,
  className,
}: {
  /** Dopełniacz po „Nie udało się odczytać”, np. „okresów”. */
  what: string
  message: string
  reload: () => Promise<void>
  className?: string
}) {
  const [retrying, setRetrying] = React.useState(false)

  const retry = () => {
    setRetrying(true)
    reload().finally(() => setRetrying(false))
  }

  return (
    <Alert variant="destructive" className={cn(className ?? "wejscie", "has-data-[slot=alert-action]:pr-44")}>
      <AlertTitle>Nie udało się odczytać {what}</AlertTitle>
      <AlertDescription>{message}</AlertDescription>
      <AlertAction className="top-1/2 -translate-y-1/2">
        <Button
          variant="outline"
          size="sm"
          className="text-foreground aria-disabled:opacity-50 aria-disabled:active:scale-100"
          disabled={retrying}
          focusableWhenDisabled
          onClick={retry}
        >
          {retrying ? <Spinner data-icon="inline-start" aria-hidden /> : <RotateCwIcon data-icon="inline-start" />}
          Spróbuj ponownie
        </Button>
      </AlertAction>
    </Alert>
  )
}
