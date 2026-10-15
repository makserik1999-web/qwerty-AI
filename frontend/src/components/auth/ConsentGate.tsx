import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useI18n } from '../../lib/i18n'
import { useStore } from '../../lib/store'
import { Alert, Button, Modal } from '../ui'

/**
 * Asks once for agreement to the privacy policy, before the app is used.
 *
 * For whoever has not agreed to the current version: accounts from before the
 * policy, an account made through Google from the sign-in page (no box to
 * tick there), everyone after the policy changes. New sign-ups agree on the
 * form and never see this.
 *
 * It cannot be dismissed - the choice is to agree or to sign out.
 */
export function ConsentGate() {
  const { t } = useI18n()
  const { user, giveConsent, signOut } = useStore()
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)

  if (!user?.consentNeeded) return null

  async function agree() {
    setBusy(true)
    setFailed(false)
    try {
      await giveConsent()
    } catch {
      setFailed(true)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open
      title={t('consent.title')}
      onClose={() => undefined}
      closeLabel={t('common.close')}
      hideClose
      footer={
        <>
          <Button variant="ghost" disabled={busy} onClick={() => void signOut()}>
            {t('common.logOut')}
          </Button>
          <Button variant="primary" loading={busy} onClick={() => void agree()}>
            {t('consent.agree')}
          </Button>
        </>
      }
    >
      <div className="stack stack-sm">
        <p>{t('consent.body')}</p>
        <p>
          <Link to="/privacy" target="_blank" rel="noopener">
            {t('consent.read')}
          </Link>
        </p>
        {failed ? <Alert tone="error">{t('auth.error.unknown')}</Alert> : null}
      </div>
    </Modal>
  )
}
