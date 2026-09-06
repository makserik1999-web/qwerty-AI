import { createContext, useCallback, useContext, useMemo } from 'react'
import { en, kk, ru, type StringKey } from './strings'
import type { UiLang } from './types'

const TABLES: Record<UiLang, Record<StringKey, string>> = { kk, ru, en }

export type Translate = (
  key: StringKey,
  params?: Record<string, string | number>,
) => string

interface I18nValue {
  lang: UiLang
  t: Translate
}

const I18nContext = createContext<I18nValue | null>(null)

export function I18nProvider({
  lang,
  children,
}: {
  lang: UiLang
  children: React.ReactNode
}) {
  const t = useCallback<Translate>(
    (key, params) => {
      const template = TABLES[lang][key] ?? key
      if (!params) return template
      return template.replace(/\{(\w+)\}/g, (match, name: string) =>
        name in params ? String(params[name]) : match,
      )
    },
    [lang],
  )

  const value = useMemo(() => ({ lang, t }), [lang, t])
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n(): I18nValue {
  const ctx = useContext(I18nContext)
  if (!ctx) throw new Error('useI18n must be used inside <I18nProvider>')
  return ctx
}
