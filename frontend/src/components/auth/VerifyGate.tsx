import { useCallback, useEffect, useState } from 'react'
import { ApiError, resendVerification } from '../../lib/api'
import { useI18n } from '../../lib/i18n'
import { useStore } from '../../lib/store'
import { Logo } from '../layout/Logo'
import { Alert, Button, Card } from '../ui'

const RESEND_AFTER_SEC = 60

/**
 * The whole app, until the address is confirmed - when the server requires it
 * (REQUIRE_VERIFIED_EMAIL=1, sent as `verify_needed`).
 *
 * The server refuses every generation to an unconfirmed account anyway; this
 * is the interface saying so up front instead of letting someone wander a
 * product they cannot use yet. It checks again whenever the tab comes back
 * into view, so confirming on a phone unlocks the laptop without a reload.
 */
export function VerifyGate() {
  const { t } = useI18n()
  const { user, reloadUser, signOut } = useStore()
  const [cooldown, setCooldown] = useState(0)
  const [note, setNote] = useState<{ tone: 'success' | 'warning' | 'error'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (cooldown <= 0) return
    const timer = window.setTimeout(() => setCooldown((s) => s - 1), 1000)
    return () => window.clearTimeout(timer)
  }, [cooldown])

  const recheck = useCallback(() => reloadUser().catch(() => undefined), [reloadUser])

  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === 'visible') void recheck()
    }
    document.addEventListener('visibilitychange', onVisible)
    window.addEventListener('focus', onVisible)
    return () => {
      document.removeEventListener('visibilitychange', onVisible)
      window.removeEventListener('focus', onVisible)
    }
  }, [recheck])

  async function resend() {
    setBusy(true)
    setNote(null)
    try {
      await resendVerification()
      setCooldown(RESEND_AFTER_SEC)
      setNote({ tone: 'success', text: t('verifyBanner.sent') })
    } catch (error) {
      setNote({
        tone: 'error',
        text: error instanceof ApiError && error.status === 429 ? t('verifyGate.tooMany') : t('verifyBanner.failed'),
      })
    } finally {
      setBusy(false)
    }
  }

  async function confirmed() {
    setBusy(true)
    await recheck()
    setBusy(false)
    // Still here: the link has not been opened yet.
    setNote({ tone: 'warning', text: t('verifyGate.notYet') })
  }

  return (
    <main className="auth" id="main">
      <div className="auth__inner">
        <Logo />
        <Card elevation="raised" className="auth__card stack stack-md" as="section">
          <h1 className="page__title">{t('verifyGate.title')}</h1>
          <p>{t('verifyGate.body', { email: user?.email ?? '' })}</p>
          <p className="text-sm text-secondary">{t('verifyGate.spam')}</p>
          {note ? <Alert tone={note.tone}>{note.text}</Alert> : null}
          <Button variant="primary" block loading={busy} onClick={() => void confirmed()}>
            {t('verifyGate.done')}
          </Button>
          <Button block disabled={busy || cooldown > 0} onClick={() => void resend()}>
            {cooldown > 0 ? t('verifyGate.resendIn', { s: cooldown }) : t('verifyBanner.resend')}
          </Button>
          <p className="text-sm text-secondary">{t('verifyGate.wrongAddress')}</p>
          <Button variant="ghost" block onClick={() => void signOut()}>
            {t('common.logOut')}
          </Button>
        </Card>
      </div>
    </main>
  )
}
