import { createContext, useCallback, useContext, useMemo, useState } from 'react'
import { cx, uid } from '../../lib/utils'
import { Icon, type IconName } from './Icon'

type ToastTone = 'info' | 'success' | 'error' | 'warning'

interface ToastItem {
  id: string
  tone: ToastTone
  message: string
}

interface ToastApi {
  toast: (message: string, tone?: ToastTone) => void
}

const ToastContext = createContext<ToastApi | null>(null)

const TONE_ICON: Record<ToastTone, IconName> = {
  info: 'info',
  success: 'checkCircle',
  error: 'alert',
  warning: 'warning',
}

const DURATION = 4000

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])

  const toast = useCallback<ToastApi['toast']>((message, tone = 'success') => {
    const id = uid('toast')
    setItems((prev) => [...prev, { id, tone, message }])
    window.setTimeout(() => {
      setItems((prev) => prev.filter((item) => item.id !== id))
    }, DURATION)
  }, [])

  const value = useMemo(() => ({ toast }), [toast])

  return (
    <ToastContext.Provider value={value}>
      {children}
      {/* Announced politely so it never interrupts what is being read. */}
      <div className="toast-region" role="status" aria-live="polite">
        {items.map((item) => (
          <div key={item.id} className={cx('toast', `toast--${item.tone}`)}>
            <span className="toast__icon">
              <Icon name={TONE_ICON[item.tone]} size={18} />
            </span>
            <span>{item.message}</span>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used inside <ToastProvider>')
  return ctx
}
