import type { CollectiveFileRead } from "@/api/generated"
import { hourMinute } from "@/lib/format"

/** Wskazówka pod treścią stron Uzupełnienia. */
export function SaveHint({ read }: { read: CollectiveFileRead }) {
  return (
    <p className="px-1 text-sm text-muted-foreground">
      {/* Odczyt się nie udał (OneDrive, zapis Excela): serwer niesie ostatni dobry stan, strona ponawia. */}
      {read.retrying ? <span role="status">Stan z {hourMinute(read.read_at)}. </span> : null}
      Nie widzisz zmian? Zapisz w Excelu (Ctrl+S).
    </p>
  )
}
