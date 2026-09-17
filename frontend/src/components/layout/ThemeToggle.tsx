import { useI18n } from '../../lib/i18n'
import { useStore } from '../../lib/store'
import { IconButton } from '../ui'

/**
 * Flips between light and dark. The full three-way choice, including
 * "match system", lives in Settings.
 */
export function ThemeToggle() {
  const { t } = useI18n()
  const { resolvedTheme, toggleTheme } = useStore()
  const goingDark = resolvedTheme === 'light'

  return (
    <IconButton
      icon={goingDark ? 'moon' : 'sun'}
      label={goingDark ? t('theme.toDark') : t('theme.toLight')}
      onClick={toggleTheme}
    />
  )
}
