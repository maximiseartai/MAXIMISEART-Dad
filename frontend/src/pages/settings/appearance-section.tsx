import type { Theme } from "@/api/centrum"
import { SegmentedFilter, type FilterOption } from "@/components/segmented-filter"
import { useSettings } from "@/lib/settings"
import { SettingRow, SettingsPanel } from "@/pages/settings/setting-row"

const THEMES: ReadonlyArray<FilterOption<Theme>> = [
  { value: "light", label: "Jasny" },
  { value: "dark", label: "Ciemny" },
]

/** Motyw Centrum; zmienia się od razu i zapisuje w Ustawieniach Centrum. */
export function AppearanceSection() {
  const { theme, chooseTheme } = useSettings()

  return (
    <SettingsPanel label="Wygląd">
      <SettingRow title="Motyw" description="Jasny albo ciemny.">
        <SegmentedFilter label="Motyw" options={THEMES} value={theme} onChange={chooseTheme} />
      </SettingRow>
    </SettingsPanel>
  )
}
