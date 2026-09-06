import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Alert,
  Avatar,
  Badge,
  Button,
  Card,
  Field,
  Input,
  Modal,
  SegmentedControl,
  useToast,
} from '../components/ui'
import { useI18n } from '../lib/i18n'
import { useStore, type ThemePreference } from '../lib/store'
import { UI_LANGUAGES } from '../lib/languages'
import type { Lang, UiLang } from '../lib/types'
import { isValidEmail, sleep } from '../lib/utils'

type SectionState = 'idle' | 'saving' | 'saved' | 'error'

interface SectionProps {
  title: string
  description: string
  children: React.ReactNode
  footer?: React.ReactNode
  state?: SectionState
  savedLabel?: string
  errorLabel?: string
}

/** One settings block: heading, description, form, and its own save state. */
function Section({
  title,
  description,
  children,
  footer,
  state = 'idle',
  savedLabel,
  errorLabel,
}: SectionProps) {
  return (
    <Card as="section" elevation="flat" className="settings-section">
      <div className="stack stack-sm">
        <h2 className="card__title">{title}</h2>
        <p className="card__subtitle">{description}</p>
      </div>
      <div className="stack stack-md">{children}</div>
      {state === 'saved' && savedLabel ? (
        <Alert tone="success" live>
          {savedLabel}
        </Alert>
      ) : null}
      {state === 'error' && errorLabel ? <Alert tone="error">{errorLabel}</Alert> : null}
      {footer ? (
        <div className="row row--actions settings-section__footer">{footer}</div>
      ) : null}
    </Card>
  )
}

export function Settings() {
  const { t } = useI18n()
  const { toast } = useToast()
  const navigate = useNavigate()
  const {
    user,
    uiLang,
    explainLang,
    theme,
    setUiLang,
    setExplainLang,
    setTheme,
    updateProfile,
    deleteAccount,
  } = useStore()

  const [name, setName] = useState(user?.name ?? '')
  const [email, setEmail] = useState(user?.email ?? '')
  const [emailError, setEmailError] = useState<string | undefined>()
  const [profileState, setProfileState] = useState<SectionState>('idle')
  const [demoFail, setDemoFail] = useState(false)

  const [deleteOpen, setDeleteOpen] = useState(false)
  const [confirmWord, setConfirmWord] = useState('')
  const [confirmError, setConfirmError] = useState<string | undefined>()

  const deleteWord = t('settings.deleteWord')

  async function saveProfile(event: React.FormEvent) {
    event.preventDefault()
    if (!isValidEmail(email)) {
      setEmailError(t('auth.error.emailInvalid'))
      return
    }
    setEmailError(undefined)
    setProfileState('saving')
    await sleep(800)
    if (demoFail) {
      setProfileState('error')
      return
    }
    updateProfile({ name: name.trim(), email: email.trim() })
    setProfileState('saved')
    toast(t('settings.savedToast'))
  }

  function confirmDelete() {
    if (confirmWord.trim() !== deleteWord) {
      setConfirmError(t('settings.deleteMismatch'))
      return
    }
    deleteAccount()
    setDeleteOpen(false)
    navigate('/', { replace: true })
  }

  return (
    <div className="page page--narrow">
      <header className="page__header">
        <div className="page__heading">
          <h1 className="page__title">{t('settings.title')}</h1>
        </div>
      </header>

      {/* Profile ------------------------------------------------------------ */}
      <form onSubmit={saveProfile}>
        <Section
          title={t('settings.profile')}
          description={t('settings.profileDesc')}
          state={profileState}
          savedLabel={t('settings.savedToast')}
          errorLabel={t('settings.saveError')}
          footer={
            <Button type="submit" variant="primary" loading={profileState === 'saving'}>
              {t('common.save')}
            </Button>
          }
        >
          <div className="row">
            <Avatar name={name || 'Anyq'} size="lg" />
            <div className="stack stack-sm">
              <span className="field__label">{t('settings.avatar')}</span>
              <p className="caption">{t('settings.avatarHint')}</p>
            </div>
          </div>

          <Field label={t('auth.field.name')}>
            {(props) => (
              <Input
                {...props}
                value={name}
                autoComplete="name"
                onChange={(event) => {
                  setName(event.target.value)
                  setProfileState('idle')
                }}
              />
            )}
          </Field>

          <Field label={t('auth.field.email')} error={emailError}>
            {(props) => (
              <Input
                {...props}
                type="email"
                value={email}
                autoComplete="email"
                onChange={(event) => {
                  setEmail(event.target.value)
                  setProfileState('idle')
                }}
              />
            )}
          </Field>

          <label className="demo-bar demo-bar--inline">
            <input
              type="checkbox"
              checked={demoFail}
              onChange={(event) => setDemoFail(event.target.checked)}
            />
            {t('settings.demoFail')}
          </label>
        </Section>
      </form>

      {/* Language ------------------------------------------------------------ */}
      <Section title={t('settings.language')} description={t('settings.languageDesc')}>
        <div className="field">
          <span className="field__label">{t('settings.uiLang')}</span>
          <SegmentedControl
            label={t('settings.uiLang')}
            value={uiLang}
            onChange={(value: UiLang) => setUiLang(value)}
            options={UI_LANGUAGES}
          />
        </div>

        <div className="field">
          <span className="field__label">{t('settings.explainLang')}</span>
          <SegmentedControl
            label={t('settings.explainLang')}
            value={explainLang}
            onChange={(value: Lang) => setExplainLang(value)}
            options={[
              { value: 'kk', label: t('common.kazakh') },
              { value: 'ru', label: t('common.russian') },
            ]}
          />
        </div>
      </Section>

      {/* Theme --------------------------------------------------------------- */}
      <Section title={t('settings.theme')} description={t('settings.themeDesc')}>
        <div className="field">
          <SegmentedControl
            label={t('settings.theme')}
            value={theme}
            onChange={(value: ThemePreference) => setTheme(value)}
            options={[
              { value: 'system', label: t('settings.theme.system') },
              { value: 'light', label: t('settings.theme.light') },
              { value: 'dark', label: t('settings.theme.dark') },
            ]}
          />
        </div>
      </Section>

      {/* Plan ---------------------------------------------------------------- */}
      <Section title={t('settings.plan')} description={t('settings.planDesc')}>
        <div className="row row-between row-wrap plan">
          <div className="stack stack-sm">
            <strong>
              {user?.role === 'teacher'
                ? t('settings.plan.teacher')
                : t('settings.plan.student')}
            </strong>
            <p className="text-sm text-secondary">
              {user?.role === 'teacher'
                ? t('settings.plan.teacherBody')
                : t('settings.plan.studentBody')}
            </p>
          </div>
          <Badge tone={user?.role === 'teacher' ? 'accent' : 'success'}>
            {user ? t(`role.${user.role}`) : ''}
          </Badge>
        </div>
        {user?.role === 'teacher' ? (
          <div className="row row--actions">
            <Button icon="wallet" onClick={() => navigate('/app/billing')}>
              {t('billing.title')}
            </Button>
          </div>
        ) : null}
      </Section>

      {/* Danger zone ---------------------------------------------------------- */}
      <Card
        as="section"
        elevation="flat"
        className="settings-section settings-section--danger"
      >
        <div className="stack stack-sm">
          <h2 className="card__title">{t('settings.danger')}</h2>
          <p className="card__subtitle">{t('settings.dangerDesc')}</p>
        </div>
        <div>
          <Button variant="quietDanger" icon="trash" onClick={() => setDeleteOpen(true)}>
            {t('settings.deleteAccount')}
          </Button>
        </div>
      </Card>

      <Modal
        open={deleteOpen}
        title={t('settings.deleteTitle')}
        description={t('settings.deleteBody', { word: deleteWord })}
        closeLabel={t('common.close')}
        onClose={() => setDeleteOpen(false)}
        footer={
          <>
            <Button onClick={() => setDeleteOpen(false)}>{t('common.cancel')}</Button>
            <Button variant="danger" icon="trash" onClick={confirmDelete}>
              {t('settings.deleteAccount')}
            </Button>
          </>
        }
      >
        <Field label={t('settings.deleteConfirmLabel')} error={confirmError}>
          {(props) => (
            <Input
              {...props}
              value={confirmWord}
              placeholder={deleteWord}
              onChange={(event) => {
                setConfirmWord(event.target.value)
                setConfirmError(undefined)
              }}
            />
          )}
        </Field>
      </Modal>
    </div>
  )
}
