import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Logo } from '../components/layout/Logo'
import { Alert, Card, LinkButton, Spinner } from '../components/ui'
import { ApiError, verifyEmail } from '../lib/api'
import { useI18n } from '../lib/i18n'
import { useStore } from '../lib/store'

/**
 * Where the confirmation link lands.
 *
 * The link only opens this page; the token is sent from here by POST. Mail
 * scanners open links to check them, and a link that confirmed on GET would
 * be spent by the scanner before the person ever clicked it.
 */
export function VerifyEmail() {
  const { t } = useI18n()
  const { user, reloadUser } = useStore()
  const [params] = useSearchParams()
  const token = params.get('token') ?? ''
  const [state, setState] = useState<'working' | 'done' | 'failed' | 'stale'>('working')
  const [email, setEmail] = useState('')
  const sent = useRef(false)

  useEffect(() => {
    if (sent.current) return // StrictMode runs effects twice; a token is spent once
    sent.current = true
    if (!token) {
      setState('failed')
      return
    }
    verifyEmail(token)
      .then((result) => {
        setEmail(result.email)
        setState('done')
        // Signed in here too? Then the banner should go without a reload.
        void reloadUser().catch(() => undefined)
      })
      .catch((error) => {
        setState(error instanceof ApiError && error.reason === 'link_stale' ? 'stale' : 'failed')
      })
  }, [token, reloadUser])

  return (
    <main className="auth" id="main">
      <div className="auth__inner">
        <Logo />
        <Card elevation="raised" className="auth__card" as="section">
          <h1 className="page__title">{t('verify.title')}</h1>
          {state === 'working' ? (
            <div className="row" role="status">
              <Spinner />
              <span className="text-secondary">{t('verify.working')}</span>
            </div>
          ) : state === 'done' ? (
            <Alert tone="success">{t('verify.done', { email })}</Alert>
          ) : (
            <Alert tone="error">{t(state === 'stale' ? 'verify.stale' : 'verify.failed')}</Alert>
          )}
          {state !== 'working' ? (
            <LinkButton to={user ? '/app/explain' : '/signin'} variant="primary" block>
              {t('verify.toApp')}
            </LinkButton>
          ) : null}
        </Card>
      </div>
    </main>
  )
}
