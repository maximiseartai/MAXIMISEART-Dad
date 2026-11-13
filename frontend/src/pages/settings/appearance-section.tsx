import type { Theme } from "@/api/centrum"
import { SegmentedFilter, type FilterOption } from "@/components/segmented-filter"
import { THEME_FIELD, useSettings } from "@/lib/settings"
import { FieldSentence, SettingRow, SettingsPanel } from "@/pages/settings/setting-row"

const THEMES: ReadonlyArray<FilterOption<Theme>> = [
  { value: "light", label: "Jasny" },
  { value: "dark", label: "Ciemny" },
]

/** Motyw Centrum; zmienia się od razu i zapisuje w Ustawieniach Centrum, a zły motyw w pliku ma zdanie pod polem. */
export function AppearanceSection() {
  const { settings, theme, chooseTheme } = useSettings()
  const problem = settings.state === "ready" ? settings.data.folders_problem : null

  return (
    <SettingsPanel label="Wygląd">
      <SettingRow
        title="Motyw"
        description="Jasny albo ciemny."
        below={problem?.field === THEME_FIELD ? <FieldSentence>{problem.message}</FieldSentence> : undefined}
      >
        <SegmentedFilter label="Motyw" options={THEMES} value={theme} onChange={chooseTheme} />
      </SettingRow>
    </SettingsPanel>
  )
}
