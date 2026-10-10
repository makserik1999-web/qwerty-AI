import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Logo } from '../components/layout/Logo'
import { Alert, Button, Card, Field, Input } from '../components/ui'
import { describeAuthError } from '../lib/authErrors'
import { useI18n } from '../lib/i18n'
import { useStore } from '../lib/store'
import { isValidEmail } from '../lib/utils'

export function SignIn() {
  const { t } = useI18n()
  const { signIn } = useStore()
  const navigate = useNavigate()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [errors, setErrors] = useState<{ email?: string; password?: string }>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault()
    const next: { email?: string; password?: string } = {}
    if (!email.trim()) next.email = t('auth.error.emailRequired')
    else if (!isValidEmail(email)) next.email = t('auth.error.emailInvalid')
    if (!password) next.password = t('auth.error.passwordRequired')
    setErrors(next)
    if (Object.keys(next).length > 0) return

    setFormError(null)
    setSubmitting(true)
    try {
      await signIn({ email: email.trim(), password })
      navigate('/app/explain', { replace: true })
    } catch (error) {
      // A wrong password and an address nobody has registered both answer 401,
      // deliberately: saying which one was wrong tells a stranger whether an
      // address has an account here.
      const failure = describeAuthError(error, 'auth.signin.invalid')
      setFormError(failure.detail ?? t(failure.key))
      setSubmitting(false)
    }
  }

  return (
    <main className="auth" id="main">
      <div className="auth__inner">
        <Logo />

        <Card elevation="raised" className="auth__card" as="section">
          <div className="stack stack-sm auth__head">
            <h1 className="page__title">{t('auth.signin.title')}</h1>
            <p className="text-secondary text-sm">{t('auth.signin.subtitle')}</p>
          </div>

          <form className="stack stack-md" onSubmit={onSubmit} noValidate>
            <Field label={t('auth.field.email')} error={errors.email}>
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

            <Field label={t('auth.field.password')} error={errors.password}>
              {(props) => (
                <Input
                  {...props}
                  type="password"
                  value={password}
                  autoComplete="current-password"
                  onChange={(event) => setPassword(event.target.value)}
                />
              )}
            </Field>

            <div className="row row-between">
              <a href="#reset" className="text-sm">
                {t('auth.signin.forgot')}
              </a>
            </div>

            {formError ? <Alert tone="error">{formError}</Alert> : null}

            <Button type="submit" variant="primary" block loading={submitting}>
              {t('auth.signin.submit')}
            </Button>
          </form>


          <p className="text-sm text-secondary auth__foot">
            {t('auth.signin.noAccount')} <Link to="/signup">{t('common.signUp')}</Link>
          </p>
        </Card>
      </div>
    </main>
  )
}
