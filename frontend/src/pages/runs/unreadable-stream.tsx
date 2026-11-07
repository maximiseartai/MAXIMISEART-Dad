import { TriangleAlertIcon } from "lucide-react"

import { UNEXPECTED } from "@/api/client"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { useRuns } from "@/lib/runs"

/** Zdarzenia strumienia Uruchomień nie dało się odczytać, więc podgląd stoi na ostatnim odczytanym widoku. */
export function UnreadableStream() {
  const { unreadable } = useRuns()

  if (!unreadable) {
    return null
  }

  return (
    <Alert variant="destructive" className="wejscie">
      <TriangleAlertIcon />
      <AlertTitle>Podgląd przestał się aktualizować</AlertTitle>
      <AlertDescription>{UNEXPECTED}</AlertDescription>
    </Alert>
  )
}
