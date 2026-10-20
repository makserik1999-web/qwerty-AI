import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Logo } from '../components/layout/Logo'
import { Alert, Button, Card, Field, Input } from '../components/ui'
import { forgotPassword } from '../lib/api'
import { describeAuthError } from '../lib/authErrors'
import { useI18n } from '../lib/i18n'
import { isValidEmail } from '../lib/utils'

/**
 * Ask for a reset link. The answer is the same whether or not the address has
 * an account - saying otherwise would tell a stranger who is registered.
 */
export function ForgotPassword() {
  const { t } = useI18n()
  const [email, setEmail] = useState('')
  const [error, setError] = useState<string | undefined>()
  const [formError, setFormError] = useState<string | null>(null)
  const [sent, setSent] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (!email.trim()) return setError(t('auth.error.emailRequired'))
    if (!isValidEmail(email)) return setError(t('auth.error.emailInvalid'))
    setError(undefined)
    setFormError(null)
    setSubmitting(true)
    try {
      await forgotPassword(email.trim())
      setSent(true)
    } catch (failure) {
      const described = describeAuthError(failure, 'auth.error.unknown')
      setFormError(described.detail ?? t(described.key))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="auth" id="main">
      <div className="auth__inner">
        <Logo />
        <Card elevation="raised" className="auth__card" as="section">
          <div className="stack stack-sm auth__head">
            <h1 className="page__title">{t('forgot.title')}</h1>
            <p className="text-secondary text-sm">{t('forgot.subtitle')}</p>
          </div>
          {sent ? (
            <Alert tone="success">{t('forgot.sent')}</Alert>
          ) : (
            <form className="stack stack-md" onSubmit={onSubmit} noValidate>
              <Field label={t('auth.field.email')} error={error}>
                {(props) => (
                  <Input
                    {...props}
                    type="email"
                    value={email}
                    autoComplete="email"
                    onChange={(event) => setEmail(event.target.value)}
                  />
                )}
              </Field>
              {formError ? <Alert tone="error">{formError}</Alert> : null}
              <Button type="submit" variant="primary" block loading={submitting}>
                {t('forgot.submit')}
              </Button>
            </form>
          )}
          <p className="text-sm text-secondary auth__foot">
            <Link to="/signin">{t('forgot.back')}</Link>
          </p>
        </Card>
      </div>
    </main>
  )
}
