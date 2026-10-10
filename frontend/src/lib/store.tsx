import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react'
import * as api from './api'
import * as saved from './saved'
import type { ApiUser } from './api'
import { buildSubmissions, buildTransactions, PRICES } from './mockData'
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
  /** True until /api/auth/me has answered, so nothing redirects too early. */
  checkingSession: boolean
  uiLang: UiLang
  explainLang: Lang
  theme: ThemePreference
  /** The theme actually in effect once `system` is resolved. */
  resolvedTheme: 'light' | 'dark'
  library: Explanation[]
  /** True until the library has been read once, so the grid can show its skeleton. */
  libraryLoading: boolean
  conversations: Conversation[]
  explanations: Record<string, Explanation>
  balance: number
  transactions: Transaction[]
  submissions: Submission[]
}

interface AppActions {
  /* These four talk to the server and can fail, so they return promises and
     let the caller show the error - the store has no opinion about copy. */
  signUp: (input: {
    name: string
    email: string
    password: string
    role: Role
  }) => Promise<void>
  signIn: (input: { email: string; password: string }) => Promise<void>
  signOut: () => Promise<void>
  updateProfile: (input: { name: string; email: string }) => Promise<void>
  deleteAccount: () => Promise<void>
  setUiLang: (lang: UiLang) => void
  setExplainLang: (lang: Lang) => void
  setTheme: (theme: ThemePreference) => void
  /** Flips between light and dark, starting from whatever is on screen now. */
  toggleTheme: () => void
  recordExplanation: (explanation: Explanation) => void
  /* The library is the server's now, so these can fail and say so. */
  saveToLibrary: (explanation: Explanation) => Promise<void>
  removeFromLibrary: (id: string) => Promise<void>
  renameExplanation: (id: string, question: string) => Promise<void>
  /** Re-read from the server; also the first load. */
  reloadLibrary: () => Promise<void>
  startConversation: (explanation: Explanation) => void
  setBalanceState: (state: BalanceState) => void
  charge: (action: TransactionAction, quantity: number, detail: string) => void
  topUp: (amount: number) => void
  setSubmissions: (next: Submission[] | ((prev: Submission[]) => Submission[])) => void
}

type Store = AppState & AppActions

const StoreContext = createContext<Store | null>(null)

/**
 * The account as the interface uses it.
 *
 * `email` is nullable on the server - accounts made before the new sign-up
 * screen have only a username - but every screen that shows an address treats
 * it as text, so it is flattened here rather than in nine places.
 */
function toUser(found: ApiUser): User {
  return {
    id: found.id,
    username: found.username,
    name: found.name || found.username,
    email: found.email ?? '',
    role: found.role,
  }
}

const PERSIST_KEY = 'anyq.session.v1'

/**
 * The session is deliberately NOT in here.
 *
 * It used to be, and that made the browser the authority on who someone was -
 * including their role, which decides whether the teacher screens appear.
 * Editing one line of local storage was enough to become a teacher. The
 * session now comes from /api/auth/me on every load, against a cookie the
 * page cannot read, so the answer comes from the server or not at all.
 *
 * Language and theme stay: they are preferences, they are read by the inline
 * script in index.html before the first paint, and being wrong about them
 * costs a repaint rather than an access decision.
 */
interface Persisted {
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

  const [user, setUser] = useState<User | null>(null)
  const [checkingSession, setCheckingSession] = useState(true)
  const [uiLang, setUiLangState] = useState<UiLang>(persisted.uiLang ?? 'kk')
  const [explainLang, setExplainLangState] = useState<Lang>(persisted.explainLang ?? 'kk')
  const [theme, setThemeState] = useState<ThemePreference>(persisted.theme ?? 'system')
  const [resolvedTheme, setResolvedTheme] = useState<'light' | 'dark'>(() =>
    document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light',
  )

  const [library, setLibrary] = useState<Explanation[]>([])
  const [libraryLoading, setLibraryLoading] = useState(true)
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [explanations, setExplanations] = useState<Record<string, Explanation>>({})
  const [balance, setBalance] = useState(BALANCE_PRESETS.healthy)
  const [transactions, setTransactions] = useState<Transaction[]>(() =>
    buildTransactions(),
  )
  const [submissions, setSubmissionsState] = useState<Submission[]>([])

  useEffect(() => {
    writePersisted({ uiLang, explainLang, theme })
  }, [uiLang, explainLang, theme])

  /* Ask the server who the cookie belongs to. Runs once, before anything is
     allowed to redirect: without the flag, every reload of a signed-in page
     would bounce to /signin for the length of this request and lose the
     route the person was on. */
  useEffect(() => {
    let cancelled = false
    api
      .currentUser()
      .then((found) => {
        if (!cancelled) setUser(found ? toUser(found) : null)
      })
      .catch(() => {
        // Unreachable server: show the signed-out interface rather than a
        // half-working one. Signing in again is the recovery, and it works
        // the moment the server does.
        if (!cancelled) setUser(null)
      })
      .finally(() => {
        if (!cancelled) setCheckingSession(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

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

  const signUp = useCallback<AppActions['signUp']>(async (input) => {
    setUser(toUser(await api.signUp(input)))
  }, [])

  const signIn = useCallback<AppActions['signIn']>(async (input) => {
    // The role is whatever the account says it is. It used to be guessed from
    // the address - anything containing "teacher" got the teacher shell -
    // which was a demo affordance, not a rule.
    setUser(toUser(await api.signIn(input)))
  }, [])

  const signOut = useCallback(async () => {
    try {
      await api.signOut()
    } finally {
      // Local state goes even if the request failed: staying signed in on
      // screen after someone asked to leave is the worse of the two wrongs,
      // and the cookie is dropped by the response when there is one.
      setUser(null)
      setConversations([])
      setExplanations({})
    }
  }, [])

  const updateProfile = useCallback<AppActions['updateProfile']>(async ({ name, email }) => {
    setUser(toUser(await api.updateProfile({ name, email })))
  }, [])

  const deleteAccount = useCallback(async () => {
    await api.deleteAccount()
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

  const reloadLibrary = useCallback(async () => {
    try {
      setLibrary(await saved.listSaved())
    } finally {
      setLibraryLoading(false)
    }
  }, [])

  const saveToLibrary = useCallback<AppActions['saveToLibrary']>(async (explanation) => {
    if (!explanation.messageId) return
    const stored = await saved.saveExplanation({
      messageId: explanation.messageId,
      question: explanation.question,
      subject: explanation.subject,
      lang: explanation.lang,
    })
    setExplanations((prev) => ({ ...prev, [stored.id]: stored }))
    setLibrary((prev) =>
      prev.some((item) => item.id === stored.id) ? prev : [stored, ...prev],
    )
  }, [])

  const removeFromLibrary = useCallback<AppActions['removeFromLibrary']>(async (id) => {
    await saved.removeSaved(id)
    setLibrary((prev) => prev.filter((item) => item.id !== id))
    setExplanations((prev) =>
      prev[id] ? { ...prev, [id]: { ...prev[id], saved: false } } : prev,
    )
  }, [])

  const renameExplanation = useCallback<AppActions['renameExplanation']>(
    async (id, question) => {
      const renamed = await saved.renameSaved(id, question)
      setLibrary((prev) => prev.map((item) => (item.id === id ? renamed : item)))
      setExplanations((prev) =>
        prev[id] ? { ...prev, [id]: { ...prev[id], question } } : prev,
      )
    },
    [],
  )

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
      checkingSession,
      uiLang,
      explainLang,
      theme,
      resolvedTheme,
      library,
      libraryLoading,
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
      reloadLibrary,
      startConversation,
      setBalanceState,
      charge,
      topUp,
      setSubmissions,
    }),
    [
      user,
      checkingSession,
      uiLang,
      explainLang,
      theme,
      resolvedTheme,
      library,
      libraryLoading,
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
      reloadLibrary,
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
