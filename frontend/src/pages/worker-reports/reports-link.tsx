import { ArrowRightIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { href } from "@/lib/address"

/** „Otwórz Raporty”: link do widoku Raporty (dziś) w wyglądzie przycisku, przy wyniku Wpisania raportów w Uruchomieniach. */
export function ReportsLink() {
  return (
    <Button size="sm" nativeButton={false} render={<a href={href("raporty")} />}>
      Otwórz Raporty
      <ArrowRightIcon data-icon="inline-end" />
    </Button>
  )
}
