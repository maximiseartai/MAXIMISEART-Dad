import { ArrowRightIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { href } from "@/lib/address"

export function ReportsLink() {
  return (
    <Button size="sm" nativeButton={false} render={<a href={href("raporty")} />}>
      Otwórz Raporty
      <ArrowRightIcon data-icon="inline-end" />
    </Button>
  )
}
