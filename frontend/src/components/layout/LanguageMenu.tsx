import { useI18n } from '../../lib/i18n'
import { UI_LANGUAGES } from '../../lib/languages'
import { useStore } from '../../lib/store'
import { Menu } from '../ui'

/** Interface-language switcher, available before and after signing in. */
export function LanguageMenu({
  side = 'bottom',
  align = 'end',
}: {
  side?: 'bottom' | 'top'
  align?: 'start' | 'end'
}) {
  const { t } = useI18n()
  const { uiLang, setUiLang } = useStore()
  const current = UI_LANGUAGES.find((item) => item.value === uiLang) ?? UI_LANGUAGES[0]

  return (
    <Menu
      label={t('settings.uiLang')}
      text={current.short}
      side={side}
      align={align}
      selectedKey={uiLang}
      items={UI_LANGUAGES.map((item) => ({
        key: item.value,
        label: item.label,
        onSelect: () => setUiLang(item.value),
      }))}
    />
  )
}
