import type { UiLang } from './types'

/** Interface languages, in the order they are offered everywhere. */
export const UI_LANGUAGES: Array<{ value: UiLang; label: string; short: string }> = [
  { value: 'kk', label: 'Қазақша', short: 'ҚАЗ' },
  { value: 'ru', label: 'Русский', short: 'РУС' },
  { value: 'en', label: 'English', short: 'ENG' },
]
