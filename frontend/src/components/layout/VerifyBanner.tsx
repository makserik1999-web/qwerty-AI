import { useState } from 'react'
import { resendVerification } from '../../lib/api'
import { useI18n } from '../../lib/i18n'
import { useStore } from '../../lib/store'
import { Button } from '../ui'

/**
 * Shown while the account's address is unconfirmed: where the link went, and
 * a way to get it again. Nothing else asks for this, so without it a person
 * whose first email went to spam has no way forward.
 */
export function VerifyBanner() {
  const { t } = useI18n()
  const { user } = useStore()
  const [state, setState] = useState<'idle' | 'sending' | 'sent' | 'failed'>('idle')

  if (!user?.email || user.emailVerified) return null

  async function resend() {
    setState('sending')
    try {
      await resendVerification()
      setState('sent')
    } catch {
      setState('failed')
    }
  }

  return (
    <div className="verify-banner" role="status">
      <span>{t('verifyBanner.text', { email: user.email })}</span>
      {state === 'sent' ? (
        <span className="verify-banner__note">{t('verifyBanner.sent')}</span>
      ) : state === 'failed' ? (
        <span className="verify-banner__note">{t('verifyBanner.failed')}</span>
      ) : (
        <Button size="sm" variant="ghost" loading={state === 'sending'} onClick={() => void resend()}>
          {t('verifyBanner.resend')}
        </Button>
      )}
    </div>
  )
}
