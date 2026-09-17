import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Logo } from '../components/layout/Logo'
import { Alert, Button, Card, Field, Icon, Input, RadioCard } from '../components/ui'
import { describeAuthError } from '../lib/authErrors'
import { useI18n } from '../lib/i18n'
import { useStore } from '../lib/store'
import type { Role } from '../lib/types'
import { isValidEmail } from '../lib/utils'

interface Errors {
  role?: string
  name?: string
  email?: string
  password?: string
}

export function SignUp() {
  const { t } = useI18n()
  const { signUp } = useStore()
  const navigate = useNavigate()

  const [role, setRole] = useState<Role | ''>('')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [errors, setErrors] = useState<Errors>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  function validate(): Errors {
    const next: Errors = {}
    if (!role) next.role = t('auth.signup.roleError')
    if (!name.trim()) next.name = t('auth.error.nameRequired')
    if (!email.trim()) next.email = t('auth.error.emailRequired')
    else if (!isValidEmail(email)) next.email = t('auth.error.emailInvalid')
    if (!password) next.password = t('auth.error.passwordRequired')
    else if (password.length < 8) next.password = t('auth.error.passwordShort')
    return next
  }

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault()
    const found = validate()
    setErrors(found)
    if (Object.keys(found).length > 0) {
      setFormError(t('auth.error.form'))
      return
    }
    setFormError(null)
    setSubmitting(true)
    try {
      await signUp({
        name: name.trim(),
        email: email.trim(),
        password,
        role: role as Role,
      })
      navigate('/app/explain', { replace: true })
    } catch (error) {
      const failure = describeAuthError(error, 'auth.error.unknown')
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
            <h1 className="page__title">{t('auth.signup.title')}</h1>
            <p className="text-secondary text-sm">{t('auth.signup.subtitle')}</p>
          </div>

          <form className="stack stack-md" onSubmit={onSubmit} noValidate>
            <fieldset className="fieldset">
              <legend className="field__label">{t('auth.signup.roleLabel')}</legend>
              <div className="stack stack-sm">
                <RadioCard
                  name="role"
                  value="student"
                  checked={role === 'student'}
                  onChange={(value) => setRole(value as Role)}
                  title={t('role.student')}
                  description={t('role.studentDesc')}
                  icon="book"
                />
                <RadioCard
                  name="role"
                  value="teacher"
                  checked={role === 'teacher'}
                  onChange={(value) => setRole(value as Role)}
                  title={t('role.teacher')}
                  description={t('role.teacherDesc')}
                  icon="clipboard"
                />
              </div>
              {errors.role ? (
                <p className="field__error" role="alert">
                  <Icon name="alert" size={15} />
                  {errors.role}
                </p>
              ) : null}
            </fieldset>

            <Field label={t('auth.field.name')} error={errors.name}>
              {(props) => (
                <Input
                  {...props}
                  value={name}
                  autoComplete="name"
                  onChange={(event) => setName(event.target.value)}
                />
              )}
            </Field>

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

            <Field
              label={t('auth.field.password')}
              hint={t('auth.password.hint')}
              error={errors.password}
            >
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

            {formError ? <Alert tone="error">{formError}</Alert> : null}

            <Button type="submit" variant="primary" block loading={submitting}>
              {t('auth.signup.submit')}
            </Button>
          </form>

          <p className="text-sm text-secondary auth__foot">
            {t('auth.signup.haveAccount')} <Link to="/signin">{t('common.signIn')}</Link>
          </p>
        </Card>
      </div>
    </main>
  )
}
