import type { Lang, UiLang } from './types'

/** Join conditional class names. */
export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ')
}

let counter = 0
export function uid(prefix = 'id'): string {
  counter += 1
  return `${prefix}-${Date.now().toString(36)}-${counter}`
}

export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

const LOCALE: Record<UiLang, string> = { kk: 'kk-KZ', ru: 'ru-RU', en: 'en-GB' }

/**
 * Browsers render Kazakh months as "M09", so month names are supplied here.
 * Russian formatting is left to Intl, which handles it correctly.
 */
const KK_MONTHS = [
  'қаңтар',
  'ақпан',
  'наурыз',
  'сәуір',
  'мамыр',
  'маусым',
  'шілде',
  'тамыз',
  'қыркүйек',
  'қазан',
  'қараша',
  'желтоқсан',
]

export function formatDate(iso: string, lang: UiLang): string {
  const date = new Date(iso)
  if (lang === 'kk') {
    return `${date.getDate()} ${KK_MONTHS[date.getMonth()]} ${date.getFullYear()}`
  }
  return date.toLocaleDateString(LOCALE[lang], {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

export function formatDateTime(iso: string, lang: UiLang): string {
  const date = new Date(iso)
  const time = date.toLocaleTimeString(LOCALE[lang], {
    hour: '2-digit',
    minute: '2-digit',
  })
  if (lang === 'kk') {
    return `${date.getDate()} ${KK_MONTHS[date.getMonth()]}, ${time}`
  }
  return `${date.toLocaleDateString(LOCALE[lang], {
    day: 'numeric',
    month: 'short',
  })}, ${time}`
}

export function formatMoney(amount: number, _lang: UiLang): string {
  // Kazakhstan groups thousands with a space in both languages; the kk-KZ
  // number format is not consistently available, so ru-RU is used for digits.
  const value = new Intl.NumberFormat('ru-RU', {
    maximumFractionDigits: 0,
  }).format(Math.abs(amount))
  return `${amount < 0 ? '−' : ''}${value} ₸`
}

export function formatClock(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds))
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${m}:${s.toString().padStart(2, '0')}`
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

/**
 * Detect the language of a question. Kazakh-specific Cyrillic letters are the
 * strongest signal; otherwise we fall back to a small function-word list.
 */
export function detectLanguage(text: string): Lang {
  if (/[әғқңөұүһі]/i.test(text)) return 'kk'
  const kazakhWords =
    /\b(не|неге|қалай|қандай|себебі|түсіндір|деген|болады|керек|мысал)\b/i
  if (kazakhWords.test(text)) return 'kk'
  if (/[а-яё]/i.test(text)) return 'ru'
  return 'kk'
}

export function initialsOf(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('')
}

export function isValidEmail(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(value.trim())
}
