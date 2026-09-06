import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react'
import { buildLibrary, buildSubmissions, buildTransactions, PRICES } from './mockData'
import type {
  Conversation,
  Explanation,
  Lang,
  Role,
  Submission,
  Transaction,
  TransactionAction,
  UiLang,
  User,
} from './types'
import { uid } from './utils'

export type ThemePreference = 'light' | 'dark' | 'system'
export type BalanceState = 'healthy' | 'low' | 'zero'

const BALANCE_PRESETS: Record<BalanceState, number> = {
  healthy: 18400,
  low: 640,
  zero: 0,
}

interface AppState {
  user: User | null
  uiLang: UiLang
  explainLang: Lang
  theme: ThemePreference
  /** The theme actually in effect once `system` is resolved. */
  resolvedTheme: 'light' | 'dark'
  library: Explanation[]
  conversations: Conversation[]
  explanations: Record<string, Explanation>
  balance: number
  transactions: Transaction[]
  submissions: Submission[]
}

interface AppActions {
  signUp: (input: { name: string; email: string; role: Role }) => void
  signIn: (input: { email: string }) => void
  signOut: () => void
  updateProfile: (input: { name: string; email: string }) => void
  deleteAccount: () => void
  setUiLang: (lang: UiLang) => void
  setExplainLang: (lang: Lang) => void
  setTheme: (theme: ThemePreference) => void
  /** Flips between light and dark, starting from whatever is on screen now. */
  toggleTheme: () => void
  recordExplanation: (explanation: Explanation) => void
  saveToLibrary: (explanation: Explanation) => void
  removeFromLibrary: (id: string) => void
  renameExplanation: (id: string, question: string) => void
  resetLibrary: () => void
  clearLibrary: () => void
  startConversation: (explanation: Explanation) => void
  setBalanceState: (state: BalanceState) => void
  charge: (action: TransactionAction, quantity: number, detail: string) => void
  topUp: (amount: number) => void
  setSubmissions: (next: Submission[] | ((prev: Submission[]) => Submission[])) => void
}

type Store = AppState & AppActions

const StoreContext = createContext<Store | null>(null)

const PERSIST_KEY = 'anyq.session.v1'

interface Persisted {
  user: User | null
  uiLang: UiLang
  explainLang: Lang
  theme: ThemePreference
}

function readPersisted(): Partial<Persisted> {
  try {
    const raw = window.localStorage.getItem(PERSIST_KEY)
    return raw ? (JSON.parse(raw) as Partial<Persisted>) : {}
  } catch {
    return {}
  }
}

function writePersisted(value: Persisted): void {
  try {
    window.localStorage.setItem(PERSIST_KEY, JSON.stringify(value))
  } catch {
    /* storage unavailable — the prototype still works in-memory */
  }
}

export function StoreProvider({ children }: { children: React.ReactNode }) {
  const persisted = useMemo(readPersisted, [])

  const [user, setUser] = useState<User | null>(persisted.user ?? null)
  const [uiLang, setUiLangState] = useState<UiLang>(persisted.uiLang ?? 'kk')
  const [explainLang, setExplainLangState] = useState<Lang>(persisted.explainLang ?? 'kk')
  const [theme, setThemeState] = useState<ThemePreference>(persisted.theme ?? 'system')
  const [resolvedTheme, setResolvedTheme] = useState<'light' | 'dark'>(() =>
    document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light',
  )

  const [library, setLibrary] = useState<Explanation[]>(() => buildLibrary())
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [explanations, setExplanations] = useState<Record<string, Explanation>>({})
  const [balance, setBalance] = useState(BALANCE_PRESETS.healthy)
  const [transactions, setTransactions] = useState<Transaction[]>(() =>
    buildTransactions(),
  )
  const [submissions, setSubmissionsState] = useState<Submission[]>([])

  useEffect(() => {
    writePersisted({ user, uiLang, explainLang, theme })
  }, [user, uiLang, explainLang, theme])

  /* Theme is applied to the document root so tokens.css can switch palettes. */
  useEffect(() => {
    const root = document.documentElement
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const apply = () => {
      const resolved = theme === 'system' ? (media.matches ? 'dark' : 'light') : theme
      root.dataset.theme = resolved
      setResolvedTheme(resolved)
    }
    apply()
    media.addEventListener('change', apply)
    return () => media.removeEventListener('change', apply)
  }, [theme])

  useEffect(() => {
    document.documentElement.lang = uiLang
  }, [uiLang])

  const toggleTheme = useCallback(() => {
    setResolvedTheme((current) => {
      const next = current === 'dark' ? 'light' : 'dark'
      setThemeState(next)
      return next
    })
  }, [])

  const signUp = useCallback<AppActions['signUp']>(({ name, email, role }) => {
    setUser({ name, email, role })
  }, [])

  const signIn = useCallback<AppActions['signIn']>(({ email }) => {
    // Demo sign-in: the role is inferred from the address so both variants of
    // the shell are reachable without a backend.
    const role: Role = /teacher|mugalim|ustaz/i.test(email) ? 'teacher' : 'student'
    const name = email.split('@')[0].replace(/[._-]+/g, ' ')
    setUser({ name: name.charAt(0).toUpperCase() + name.slice(1), email, role })
  }, [])

  const signOut = useCallback(() => setUser(null), [])

  const updateProfile = useCallback<AppActions['updateProfile']>(({ name, email }) => {
    setUser((prev) => (prev ? { ...prev, name, email } : prev))
  }, [])

  const deleteAccount = useCallback(() => {
    setUser(null)
    setLibrary([])
    setConversations([])
    setExplanations({})
  }, [])

  const recordExplanation = useCallback<AppActions['recordExplanation']>(
    (explanation) => {
      setExplanations((prev) => ({ ...prev, [explanation.id]: explanation }))
    },
    [],
  )

  const startConversation = useCallback<AppActions['startConversation']>(
    (explanation) => {
      setExplanations((prev) => ({ ...prev, [explanation.id]: explanation }))
      setConversations((prev) => [
        {
          id: uid('conv'),
          title: explanation.question,
          createdAt: explanation.createdAt,
          explanationId: explanation.id,
        },
        ...prev,
      ])
    },
    [],
  )

  const saveToLibrary = useCallback<AppActions['saveToLibrary']>((explanation) => {
    const saved = { ...explanation, saved: true }
    setExplanations((prev) => ({ ...prev, [saved.id]: saved }))
    setLibrary((prev) =>
      prev.some((item) => item.id === saved.id) ? prev : [saved, ...prev],
    )
  }, [])

  const removeFromLibrary = useCallback<AppActions['removeFromLibrary']>((id) => {
    setLibrary((prev) => prev.filter((item) => item.id !== id))
    setExplanations((prev) =>
      prev[id] ? { ...prev, [id]: { ...prev[id], saved: false } } : prev,
    )
  }, [])

  const renameExplanation = useCallback<AppActions['renameExplanation']>(
    (id, question) => {
      setLibrary((prev) =>
        prev.map((item) => (item.id === id ? { ...item, question } : item)),
      )
      setExplanations((prev) =>
        prev[id] ? { ...prev, [id]: { ...prev[id], question } } : prev,
      )
    },
    [],
  )

  const resetLibrary = useCallback(() => setLibrary(buildLibrary()), [])
  const clearLibrary = useCallback(() => setLibrary([]), [])

  const setBalanceState = useCallback<AppActions['setBalanceState']>((state) => {
    setBalance(BALANCE_PRESETS[state])
    setTransactions(state === 'zero' ? [] : buildTransactions())
  }, [])

  const charge = useCallback<AppActions['charge']>((action, quantity, detail) => {
    const unit =
      action === 'explanation'
        ? PRICES.explanation
        : action === 'assessment'
          ? PRICES.assessment
          : PRICES.grading
    const amount = -unit * quantity
    setBalance((prev) => Math.max(0, prev + amount))
    setTransactions((prev) => [
      {
        id: uid('tx'),
        date: new Date().toISOString(),
        action,
        detail,
        quantity,
        amount,
      },
      ...prev,
    ])
  }, [])

  const topUp = useCallback<AppActions['topUp']>((amount) => {
    setBalance((prev) => prev + amount)
    setTransactions((prev) => [
      {
        id: uid('tx'),
        date: new Date().toISOString(),
        action: 'topup',
        detail: 'Kaspi',
        quantity: 1,
        amount,
      },
      ...prev,
    ])
  }, [])

  const setSubmissions = useCallback<AppActions['setSubmissions']>((next) => {
    setSubmissionsState((prev) => (typeof next === 'function' ? next(prev) : next))
  }, [])

  const value = useMemo<Store>(
    () => ({
      user,
      uiLang,
      explainLang,
      theme,
      resolvedTheme,
      library,
      conversations,
      explanations,
      balance,
      transactions,
      submissions,
      signUp,
      signIn,
      signOut,
      updateProfile,
      deleteAccount,
      setUiLang: setUiLangState,
      setExplainLang: setExplainLangState,
      setTheme: setThemeState,
      toggleTheme,
      recordExplanation,
      saveToLibrary,
      removeFromLibrary,
      renameExplanation,
      resetLibrary,
      clearLibrary,
      startConversation,
      setBalanceState,
      charge,
      topUp,
      setSubmissions,
    }),
    [
      user,
      uiLang,
      explainLang,
      theme,
      resolvedTheme,
      library,
      conversations,
      explanations,
      balance,
      transactions,
      submissions,
      signUp,
      signIn,
      signOut,
      updateProfile,
      deleteAccount,
      toggleTheme,
      recordExplanation,
      saveToLibrary,
      removeFromLibrary,
      renameExplanation,
      resetLibrary,
      clearLibrary,
      startConversation,
      setBalanceState,
      charge,
      topUp,
      setSubmissions,
    ],
  )

  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>
}

export function useStore(): Store {
  const ctx = useContext(StoreContext)
  if (!ctx) throw new Error('useStore must be used inside <StoreProvider>')
  return ctx
}

export { buildSubmissions, PRICES }
