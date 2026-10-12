import { useEffect, useState } from 'react'
import { ApiError, startPhone, verifyPhone } from '../../lib/api'
import { describeAuthError } from '../../lib/authErrors'
import { useI18n } from '../../lib/i18n'
import { useStore } from '../../lib/store'
import { formatLocal, formatPhone, isKzMobile, looksWrong, pastedDigits } from '../../lib/phone'
import type { StringKey } from '../../lib/strings'
import { Alert, Badge, Button, Card, Field, Input, useToast } from '../ui'

const PHONE_ERRORS = new Set([
  'phone_invalid', 'phone_taken', 'sms_wait', 'sms_limit', 'sms_paused', 'sms_failed',
  'code_wrong', 'code_expired', 'code_attempts',
])

function display(phone: string): string {
  return phone.length === 11 ? `+7 ${phone.slice(1, 4)} ${phone.slice(4, 7)} ${phone.slice(7, 9)} ${phone.slice(9)}` : phone
}

/**
 * Confirm a mobile number with a code by SMS. One number, one account - the
 * trial plan will hang off it, so it has to be proven rather than typed.
 */
export function PhoneSection() {
  const { t } = useI18n()
  const { toast } = useToast()
  const { user, acceptUser } = useStore()

  const [editing, setEditing] = useState(!user?.phoneVerified)
  const [phone, setPhone] = useState(user?.phone ? display(user.phone) : '+7 ')
  const [code, setCode] = useState('')
  const [step, setStep] = useState<'phone' | 'code'>('phone')
  const [cooldown, setCooldown] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (cooldown <= 0) return
    const timer = window.setTimeout(() => setCooldown((s) => s - 1), 1000)
    return () => window.clearTimeout(timer)
  }, [cooldown])

  function describe(failure: unknown): string {
    if (failure instanceof ApiError && PHONE_ERRORS.has(failure.reason)) {
      if (failure.reason === 'sms_wait' && typeof failure.data.retry_after === 'number') {
        setCooldown(failure.data.retry_after)
      }
      return t(`phone.error.${failure.reason}` as StringKey, {
        n: Number(failure.data.attempts_left ?? 0),
      })
    }
    const described = describeAuthError(failure, 'auth.error.unknown')
    return described.detail ?? t(described.key)
  }

  async function send() {
    setBusy(true)
    setError(null)
    try {
      const result = await startPhone(phone)
      if (result.already) {
        setEditing(false)
      } else {
        setStep('code')
        setCode('')
        setCooldown(result.retry_after ?? 60)
      }
    } catch (failure) {
      setError(describe(failure))
    } finally {
      setBusy(false)
    }
  }

  async function confirm(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      acceptUser(await verifyPhone(phone, code))
      toast(t('settings.phoneSaved'))
      setEditing(false)
      setStep('phone')
    } catch (failure) {
      setError(describe(failure))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card as="section" elevation="flat" className="settings-section">
      <div className="stack stack-sm">
        <h2 className="card__title">{t('settings.phone')}</h2>
        <p className="card__subtitle">{t('settings.phoneDesc')}</p>
      </div>

      {!editing && user?.phone ? (
        <div className="row row-between row-wrap">
          <span className="row">
            <strong>{display(user.phone)}</strong>
            <Badge tone="success">{t('settings.phoneVerified')}</Badge>
          </span>
          <Button size="sm" onClick={() => setEditing(true)}>
            {t('settings.phoneChange')}
          </Button>
        </div>
      ) : (
        <form className="stack stack-md" onSubmit={confirm} noValidate>
          <Field
            label={t('settings.phoneLabel')}
            error={looksWrong(phone) ? t('phone.error.phone_invalid') : undefined}
          >
            {(props) => (
              <Input
                {...props}
                type="tel"
                inputMode="tel"
                autoComplete="tel"
                placeholder="+7 7__ ___ __ __"
                value={phone}
                disabled={step === 'code'}
                // Only digits, grouped as they are read, ten after +7 at most.
                onChange={(event) => setPhone(formatPhone(event.target.value))}
                onPaste={(event) => {
                  event.preventDefault()
                  setPhone(formatLocal(pastedDigits(event.clipboardData.getData('text'))))
                }}
              />
            )}
          </Field>

          {step === 'code' ? (
            <Field label={t('settings.phoneCodeLabel')}>
              {(props) => (
                <Input
                  {...props}
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={6}
                  value={code}
                  onChange={(event) => setCode(event.target.value.replace(/\D/g, ''))}
                />
              )}
            </Field>
          ) : null}

          {error ? <Alert tone="error">{error}</Alert> : null}

          <div className="row row-wrap">
            {step === 'code' ? (
              <Button type="submit" variant="primary" loading={busy} disabled={code.length !== 6}>
                {t('settings.phoneConfirm')}
              </Button>
            ) : null}
            <Button
              variant={step === 'code' ? 'ghost' : 'primary'}
              loading={busy && step === 'phone'}
              disabled={cooldown > 0 || !isKzMobile(phone)}
              onClick={() => void send()}
            >
              {cooldown > 0 ? t('settings.phoneResendIn', { s: cooldown }) : t('settings.phoneSend')}
            </Button>
          </div>
        </form>
      )}
    </Card>
  )
}
