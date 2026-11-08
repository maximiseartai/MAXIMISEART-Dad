import { cn } from "cn"
import { ClipboardPenLineIcon } from "lucide-react"

import { getQuantitiesToFill } from "@/api/centrum"
import { LoadFailure } from "@/components/load-failure"
import { ThreePartMessage } from "@/components/three-part-message"
import { Button } from "@/components/ui/button"
import { href } from "@/lib/address"
import { useContentEntrance } from "@/lib/content-entrance"
import { useLiveFile } from "@/lib/use-live-file"
import { FillingSkeleton, FillingSummary } from "@/pages/filling/filling-page"
import { SaveHint } from "@/pages/filling/save-hint"

/**
 * Na karcie wyniku Przygotowania: to samo podsumowanie Uzupełnienia co jego strona, z tego samego odczytu i tak samo
 * na żywo, bo tata wpisuje w Excelu obok Centrum zaraz po „Otwórz Plik zbiorczy”.
 */
export function FillingOnResult({ token }: { token: string }) {
  // Karta powstaje, gdy Uruchomienie zmieniło pliki okresu, więc kopia sprzed niego byłaby nieaktualna.
  const { resource, reload } = useLiveFile(getQuantitiesToFill, [token], { fresh: true })
  const entrance = useContentEntrance(resource.state === "loading")

  return (
    <section aria-label="Uzupełnienie pliku zbiorczego" className="flex flex-col gap-3">
      <div className="flex min-h-8 items-center gap-3">
        <h3 className="text-sm font-medium">Do uzupełnienia w Excelu</h3>
        <Button
          variant="outline"
          size="sm"
          className="ml-auto"
          nativeButton={false}
          render={<a href={href("uzupelnienie", token)} />}
        >
          <ClipboardPenLineIcon data-icon="inline-start" />
          Uzupełnij
        </Button>
      </div>
      {resource.state === "loading" ? (
        <FillingSkeleton />
      ) : resource.state === "failed" ? (
        <LoadFailure what="Pliku zbiorczego" message={resource.message} reload={reload} />
      ) : (
        <div className={cn(entrance, "flex flex-col gap-3")}>
          {resource.data.state === "ready" ? (
            <>
              <FillingSummary token={token} found={resource.data} />
              {resource.data.settled ? null : <SaveHint read={resource.data.read} />}
            </>
          ) : (
            <ThreePartMessage message={resource.data.message} kind="notice" />
          )}
        </div>
      )}
    </section>
  )
}
