import { FileSpreadsheetIcon, FolderIcon } from "lucide-react"

import { SettingPathItem } from "@/components/setting-path"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ItemGroup } from "@/components/ui/item"

/** Rejestr zleceń i folder okresów wskazane raz; „Zmień” otwiera okno wyboru Windows na komputerze taty. */
export function FileSettingsCard() {
  return (
    <Card>
      <CardHeader>
        <CardTitle id="ustawienia">Ustawienia</CardTitle>
      </CardHeader>
      <CardContent>
        <ItemGroup aria-labelledby="ustawienia">
          <SettingPathItem label="Rejestr zleceń" icon={<FileSpreadsheetIcon />} path="order_register" />
          <SettingPathItem label="Folder okresów" icon={<FolderIcon />} path="periods_directory" />
        </ItemGroup>
      </CardContent>
    </Card>
  )
}
