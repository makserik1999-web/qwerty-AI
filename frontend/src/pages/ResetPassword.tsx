import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { Logo } from '../components/layout/Logo'
import { Alert, Button, Card, Field, Input } from '../components/ui'
import { ApiError, resetPassword } from '../lib/api'
import { describeAuthError } from '../lib/authErrors'
import { useI18n } from '../lib/i18n'
import { useStore } from '../lib/store'

/** Set a new password from the emailed link, and land signed in. */
export function ResetPassword() {
  const { t } = useI18n()
  const { acceptUser } = useStore()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const token = params.get('token') ?? ''

  const [password, setPassword] = useState('')
  const [repeat, setRepeat] = useState('')
  const [errors, setErrors] = useState<{ password?: string; repeat?: string }>({})
  const [formError, setFormError] = useState<string | null>(token ? null : t('reset.noToken'))
  const [linkDead, setLinkDead] = useState(!token)
  const [submitting, setSubmitting] = useState(false)

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault()
    const next: { password?: string; repeat?: string } = {}
    if (!password) next.password = t('auth.error.passwordRequired')
    else if (password.length < 8) next.password = t('auth.error.passwordShort')
    if (password && repeat !== password) next.repeat = t('reset.mismatch')
    setErrors(next)
    if (Object.keys(next).length > 0) return

    setFormError(null)
    setSubmitting(true)
    try {
      acceptUser(await resetPassword(token, password))
      navigate('/app/explain', { replace: true })
    } catch (failure) {
      if (failure instanceof ApiError && failure.reason === 'link_invalid') {
        setLinkDead(true)
        setFormError(t('reset.failed'))
      } else {
        const described = describeAuthError(failure, 'auth.error.unknown')
        setFormError(described.detail ?? t(described.key))
      }
      setSubmitting(false)
    }
  }

  return (
    <main className="auth" id="main">
      <div className="auth__inner">
        <Logo />
        <Card elevation="raised" className="auth__card" as="section">
          <h1 className="page__title">{t('reset.title')}</h1>
          {linkDead ? (
            <>
              {formError ? <Alert tone="error">{formError}</Alert> : null}
              <p className="text-sm auth__foot">
                <Link to="/forgot-password">{t('reset.again')}</Link>
              </p>
            </>
          ) : (
            <form className="stack stack-md" onSubmit={onSubmit} noValidate>
              <Field label={t('auth.field.password')} hint={t('auth.password.hint')} error={errors.password}>
                {(props) => (
                  <Input
                    {...props}
                    type="password"
                    value={password}
                    autoComplete="new-password"
                    onChange={(event) => setPassword(event.target.value)}
                  />
                )}
              </Field>
              <Field label={t('reset.confirm')} error={errors.repeat}>
                {(props) => (
                  <Input
                    {...props}
                    type="password"
                    value={repeat}
                    autoComplete="new-password"
                    onChange={(event) => setRepeat(event.target.value)}
                  />
                )}
              </Field>
              {formError ? <Alert tone="error">{formError}</Alert> : null}
              <Button type="submit" variant="primary" block loading={submitting}>
                {t('reset.submit')}
              </Button>
            </form>
          )}
        </Card>
      </div>
    </main>
  )
}
