import { useEffect, useState } from 'react'
import { Alert, Badge, Card, ProgressBar, Skeleton } from '../components/ui'
import { getQuota, type Quota } from '../lib/api'
import { useI18n } from '../lib/i18n'

/**
 * The plan, as it actually is.
 *
 * This page used to show a balance of 18 400 ₸, a top-up button, invented
 * transactions and spending charts - all of it numbers in the browser that
 * never reached a server. Nothing is charged yet, so it says that, and shows
 * the one limit that is real: the video quota the server enforces.
 *
 * Plans and payment replace the pilot card when they exist.
 */
export function Billing() {
  const { t } = useI18n()
  const [quota, setQuota] = useState<Quota | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let active = true
    getQuota()
      .then((found) => {
        if (active) setQuota(found)
      })
      .catch(() => {
        if (active) setFailed(true)
      })
    return () => {
      active = false
    }
  }, [])

  return (
    <div className="page page--narrow">
      <header className="page__header">
        <div className="page__heading">
          <h1 className="page__title">{t('billing.title')}</h1>
          <p className="page__subtitle">{t('billing.subtitle')}</p>
        </div>
      </header>

      <Card as="section" elevation="raised" className="stack stack-sm">
        <div className="row row-wrap">
          <h2 className="card__title">{t('billing.pilotTitle')}</h2>
          <Badge tone="success">{t('settings.plan.teacher')}</Badge>
        </div>
        <p className="text-sm text-secondary">{t('billing.pilotBody')}</p>
      </Card>

      <Card as="section" elevation="raised" className="stack stack-sm">
        <h2 className="card__title">{t('billing.today')}</h2>
        {failed ? (
          <Alert tone="error">{t('billing.loadFailed')}</Alert>
        ) : quota ? (
          <>
            <p className="balance__value">
              {quota.used_day} / {quota.limit_day}
            </p>
            <ProgressBar
              value={quota.limit_day ? (quota.used_day / quota.limit_day) * 100 : 0}
              label={t('billing.today')}
            />
            <p className="text-sm text-secondary">
              {t('billing.limitsNote', { hour: quota.limit_hour, day: quota.limit_day })}
            </p>
          </>
        ) : (
          <>
            <Skeleton width="30%" height="40px" />
            <Skeleton height="8px" />
          </>
        )}
      </Card>
    </div>
  )
}
