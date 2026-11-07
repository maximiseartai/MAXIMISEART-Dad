import { TriangleAlertIcon } from "lucide-react"

import { Alert, AlertTitle } from "@/components/ui/alert"

/** Żółty baner ze zdaniami z serwera, które mówią, czemu przycisk procesu jest wyłączony i co zrobić; bez zdań go nie ma. */
export function WarningSentences({ sentences }: { sentences: ReadonlyArray<string> }) {
  if (sentences.length === 0) {
    return null
  }

  return (
    <Alert className="wejscie">
      <TriangleAlertIcon className="text-warning!" />
      <AlertTitle className="flex flex-col gap-0.5">
        {sentences.map((sentence) => (
          <span key={sentence}>{sentence}</span>
        ))}
      </AlertTitle>
    </Alert>
  )
}
