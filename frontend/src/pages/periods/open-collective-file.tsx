import type * as React from "react"
import { FileSpreadsheetIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { openAndConfirm } from "@/pages/periods/open-period-path"

export function OpenCollectiveFileButton({
  period,
  ...button
}: Omit<React.ComponentProps<typeof Button>, "children" | "onClick"> & { period: string }) {
  return (
    <Button {...button} onClick={() => openAndConfirm(period, { target: "collective_file" })}>
      <FileSpreadsheetIcon data-icon="inline-start" />
      Otwórz Plik zbiorczy
    </Button>
  )
}
