import { ArrowRightIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { href } from "@/lib/address"

/** „Otwórz Raporty”: link do widoku Raporty (dziś) w wyglądzie przycisku, przy wyniku i na karcie Wpisania raportów. */
export function ReportsLink({ variant = "default" }: { variant?: "default" | "outline" }) {
  return (
    <Button size="sm" variant={variant} nativeButton={false} render={<a href={href("raporty")} />}>
      Otwórz Raporty
      <ArrowRightIcon data-icon="inline-end" />
    </Button>
  )
}
