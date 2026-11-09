import type * as React from "react"
import { ArrowRightIcon, ClipboardPenLineIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { href } from "@/lib/address"

/**
 * „Uzupełnij”: link na podsumowanie Uzupełnienia pliku zbiorczego okresu `token` w wyglądzie przycisku miejsca, w którym
 * stoi.
 */
export function FillLink({
  token,
  arrow = false,
  ...button
}: Omit<React.ComponentProps<typeof Button>, "children" | "nativeButton" | "render"> & { token: string; arrow?: boolean }) {
  return (
    <Button {...button} nativeButton={false} render={<a href={href("uzupelnienie", token)} />}>
      {arrow ? null : <ClipboardPenLineIcon data-icon="inline-start" />}
      Uzupełnij
      {arrow ? <ArrowRightIcon data-icon="inline-end" /> : null}
    </Button>
  )
}
