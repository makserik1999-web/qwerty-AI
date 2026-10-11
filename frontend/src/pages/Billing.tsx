import { useCallback, useEffect, useState } from 'react'
import { PhoneSection } from '../components/settings/PhoneSection'
import { Alert, Badge, Button, Card, ProgressBar, Skeleton } from '../components/ui'
import {
  getPlan,
  getQuota,
  pausePlan,
  resumePlan,
  type PlanOffer,
  type PlanResource,
  type PlanSummary,
  type Quota,
} from '../lib/api'
import { useI18n } from '../lib/i18n'
import { CONTACT } from '../lib/mockData'
import { useStore } from '../lib/store'
import type { StringKey } from '../lib/strings'
import { formatDate } from '../lib/utils'

const RESOURCES: PlanResource[] = ['videos', 'assessments', 'quiz_drafts', 'lesson_plans']

/**
 * The plan, as it actually is: what the account is on, what is left, and what
 * it could move to.
 *
 * There is no payment form here yet. Until Kaspi is connected, a plan is
 * switched on by the team by hand, and the page says so instead of offering a
 * button that does nothing.
 */
export function Billing() {
  const { t, lang } = useI18n()
  const { user } = useStore()
  const [plan, setPlan] = useState<PlanSummary | null>(null)
  const [offers, setOffers] = useState<PlanOffer[]>([])
  const [trialLimits, setTrialLimits] = useState<Record<string, number | null>>({})
  const [quota, setQuota] = useState<Quota | null>(null)
  const [failed, setFailed] = useState(false)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      const found = await getPlan()
      setPlan(found.plan)
      setOffers(found.offers)
      setTrialLimits((found.trial_limits ?? {}) as Record<string, number | null>)
      setFailed(false)
    } catch {
      setFailed(true)
    }
    getQuota().then(setQuota).catch(() => undefined)
  }, [])

  // The phone section confirms a number, which is what starts the trial.
  useEffect(() => {
    void load()
  }, [load, user?.phoneVerified])

  async function act(action: () => Promise<{ plan: PlanSummary }>) {
    setBusy(true)
    try {
      setPlan((await action()).plan)
    } catch {
      setFailed(true)
    } finally {
      setBusy(false)
    }
  }

  const date = (iso: string | null) => (iso ? formatDate(iso, lang) : '')
  const yearOffer = offers.find((o) => o.period === 'school_year')

  return (
    <div className="page page--narrow">
      <header className="page__header">
        <div className="page__heading">
          <h1 className="page__title">{t('billing.title')}</h1>
        </div>
      </header>

      {failed ? <Alert tone="error">{t('billing.loadFailed')}</Alert> : null}
      {!plan && !failed ? (
        <Card elevation="raised" className="stack stack-sm">
          <Skeleton width="40%" height="24px" />
          <Skeleton height="60px" />
        </Card>
      ) : null}

      {plan ? (
        <Card as="section" elevation="raised" className="stack stack-md">
          <div className="row row-wrap">
            <h2 className="card__title">
              {plan.kind === 'ustaz'
                ? plan.title
                : plan.kind === 'trial'
                  ? t('plan.trial.title')
                  : t('plan.free.title')}
            </h2>
            {plan.kind === 'ustaz' && plan.subscription ? (
              <Badge tone="success">{t('plan.ustaz.until', { date: date(plan.subscription.expires_at) })}</Badge>
            ) : null}
          </div>

          {plan.kind === 'free' ? (
            <>
              <p className="text-sm text-secondary">{t('plan.free.body')}</p>
              {plan.trial_used_up ? (
                <Alert tone="info">{t('plan.trial.usedUp')}</Alert>
              ) : plan.trial_unavailable === 'phone_used' ? (
                <Alert tone="warning">{t('plan.trial.phoneUsed')}</Alert>
              ) : plan.trial_unavailable === 'phone_required' ? (
                <Alert tone="info">
                  {t('plan.trial.offer', {
                    videos: trialLimits.videos ?? 0,
                    assessments: trialLimits.assessments ?? 0,
                    quizzes: trialLimits.quiz_drafts ?? 0,
                    plans: trialLimits.lesson_plans ?? 0,
                  })}
                </Alert>
              ) : null}
              {plan.subscription?.status === 'expired' ? (
                <p className="text-sm text-secondary">{t('plan.ustaz.expired')}</p>
              ) : null}
            </>
          ) : (
            <ul className="plan-meters">
              {RESOURCES.map((resource) => {
                const left = plan.available[resource]
                const limit = plan.limits[resource]
                const total =
                  limit == null
                    ? null
                    : limit + (resource === 'videos' ? plan.carryover + plan.extra_videos : 0)
                return (
                  <li key={resource} className="plan-meter">
                    <span className="plan-meter__label">{t(`plan.left.${resource}` as StringKey)}</span>
                    {left === null || total === null ? (
                      <span className="plan-meter__value">{t('plan.unlimited')}</span>
                    ) : (
                      <>
                        <span className="plan-meter__value">{t('plan.leftOf', { left, total })}</span>
                        <ProgressBar
                          value={total ? (left / total) * 100 : 0}
                          label={t(`plan.left.${resource}` as StringKey)}
                        />
                      </>
                    )}
                  </li>
                )
              })}
            </ul>
          )}

          {plan.kind === 'trial' ? <p className="caption">{t('plan.trial.notes')}</p> : null}

          {plan.kind === 'ustaz' && plan.subscription ? (
            <div className="stack stack-sm">
              {plan.subscription.period_end ? (
                <p className="caption">{t('plan.ustaz.periodEnd', { date: date(plan.subscription.period_end) })}</p>
              ) : null}
              {plan.carryover ? <p className="caption">{t('plan.ustaz.carryover', { n: plan.carryover })}</p> : null}
              {plan.extra_videos ? <p className="caption">{t('plan.ustaz.extra', { n: plan.extra_videos })}</p> : null}
              {plan.subscription.suggest_year && yearOffer ? (
                <Alert tone="info">{t('plan.suggestYear', { price: yearOffer.price.toLocaleString('ru-RU') })}</Alert>
              ) : null}
              {plan.subscription.can_pause ? (
                <div className="stack stack-sm">
                  <p className="text-sm text-secondary">{t('plan.pauseBody')}</p>
                  <div>
                    <Button loading={busy} onClick={() => void act(pausePlan)}>
                      {t('plan.pause')}
                    </Button>
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}

          {plan.subscription?.status === 'paused' ? (
            <div className="stack stack-sm">
              <Alert tone="info">{t('plan.paused', { date: date(plan.subscription.pause_until) })}</Alert>
              <div>
                <Button loading={busy} onClick={() => void act(resumePlan)}>
                  {t('plan.resume')}
                </Button>
              </div>
            </div>
          ) : null}
        </Card>
      ) : null}

      {/* A free teacher's next step is the phone: confirming it starts the trial. */}
      {plan?.kind === 'free' && plan.trial_unavailable === 'phone_required' ? <PhoneSection /> : null}

      {offers.length && user?.role === 'teacher' ? (
        <Card as="section" elevation="raised" className="stack stack-md">
          <h2 className="card__title">{t('plan.offers.title')}</h2>
          <ul className="plan-offers">
            {offers.map((offer) => (
              <li key={offer._id} className={offer.period === 'school_year' ? 'plan-offer is-main' : 'plan-offer'}>
                {/* The add-on's own line already says what it is, in the reader's language. */}
                {offer.kind !== 'addon' ? <strong>{offer.title}</strong> : null}
                <span>
                  {offer.kind === 'addon'
                    ? t('plan.offer.addon', { n: offer.videos ?? 0, price: offer.price.toLocaleString('ru-RU') })
                    : offer.period === 'school_year'
                      ? t('plan.offer.year', { price: offer.price.toLocaleString('ru-RU') })
                      : t('plan.offer.month', { price: offer.price.toLocaleString('ru-RU') })}
                </span>
                {offer.period === 'school_year' ? <span className="caption">{t('plan.offer.yearNote')}</span> : null}
                {offer.kind === 'subscription' && offer.limits ? (
                  <span className="caption">
                    {t('plan.offer.limits', {
                      videos: offer.limits.videos ?? 0,
                      assessments: offer.limits.assessments ?? 0,
                      plans: offer.limits.lesson_plans ?? 0,
                    })}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
          <p className="text-sm text-secondary">
            {t('plan.buySoon')} <a href={CONTACT.phoneHref}>{CONTACT.phone}</a>,{' '}
            <a href={CONTACT.emailHref}>{CONTACT.email}</a>
          </p>
        </Card>
      ) : null}

      <Card as="section" elevation="flat" className="stack stack-sm">
        <h2 className="card__title">{t('plan.quotaTitle')}</h2>
        {quota ? (
          <>
            <p className="text-sm">
              {t('billing.today')}: {quota.used_day} / {quota.limit_day}
            </p>
            <p className="caption">{t('billing.limitsNote', { hour: quota.limit_hour, day: quota.limit_day })}</p>
          </>
        ) : (
          <Skeleton height="16px" />
        )}
      </Card>
    </div>
  )
}
