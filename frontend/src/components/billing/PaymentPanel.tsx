import { useState } from 'react'
import { cancelOrder, reportPaid, type KaspiDetails, type Payment } from '../../lib/api'
import { useI18n } from '../../lib/i18n'
import { AnchorButton, Alert, Badge, Button, Card } from '../ui'

/**
 * One open order: what to transfer, where, with which code - and the button
 * that tells the team to check. Nothing is switched on from here; the plan
 * starts when someone has seen the money in Kaspi.
 */
export function PaymentPanel({
  payment,
  details,
  onChanged,
}: {
  payment: Payment
  details: KaspiDetails
  onChanged: (next: Payment) => void
}) {
  const { t } = useI18n()
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)

  async function act(action: () => Promise<Payment>) {
    setBusy(true)
    setFailed(false)
    try {
      onChanged(await action())
    } catch {
      setFailed(true)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card as="section" elevation="raised" className="stack stack-md pay-panel">
      <div className="row row-wrap">
        <h2 className="card__title">{t('pay.title')}</h2>
        <Badge tone={payment.status === 'submitted' ? 'info' : 'warning'}>{t(`pay.status.${payment.status}`)}</Badge>
      </div>
      <p>
        <strong>{payment.title}</strong> — {t('pay.amount', { amount: payment.amount.toLocaleString('ru-RU') })}
      </p>
      {details.phone ? <p>{t('pay.to', { phone: details.phone })}</p> : null}
      {details.name ? <p className="text-sm text-secondary">{t('pay.name', { name: details.name })}</p> : null}
      {details.note ? <p className="caption">{details.note}</p> : null}
      <div className="stack stack-sm">
        <span className="text-sm">{t('pay.code')}</span>
        <code className="pay-panel__code">{payment.code}</code>
      </div>
      {payment.status === 'awaiting' ? (
        <>
          <p className="text-sm text-secondary">{t('pay.steps')}</p>
          <div className="row row-wrap">
            {details.link ? (
              <AnchorButton href={details.link} target="_blank" rel="noopener noreferrer">
                {t('pay.link')}
              </AnchorButton>
            ) : null}
            <Button variant="primary" loading={busy} onClick={() => void act(() => reportPaid(payment.id))}>
              {t('pay.done')}
            </Button>
            <Button variant="ghost" disabled={busy} onClick={() => void act(() => cancelOrder(payment.id))}>
              {t('pay.cancel')}
            </Button>
          </div>
        </>
      ) : (
        <Alert tone="info">{t('pay.submittedNote')}</Alert>
      )}
      {failed ? <Alert tone="error">{t('pay.error.generic')}</Alert> : null}
    </Card>
  )
}
