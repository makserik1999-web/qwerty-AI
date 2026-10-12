import { useCallback, useEffect, useState } from 'react'
import { PaymentPanel } from '../components/billing/PaymentPanel'
import { ReferralCard } from '../components/billing/ReferralCard'
import { PhoneSection } from '../components/settings/PhoneSection'
import { Alert, Badge, Button, Card, ProgressBar, Skeleton } from '../components/ui'
import {
  ApiError,
  getPayments,
  getPlan,
  getQuota,
  orderPlan,
  pausePlan,
  resumePlan,
  type KaspiDetails,
  type Payment,
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
 * The plans are a choice and the button under them is the action - pay,
 * extend, or switch. Until Kaspi is connected there is no button: a plan is
 * switched on by the team by hand, and the page says so, naming the plan that
 * was chosen, instead of offering a button that does nothing.
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
  const [kaspi, setKaspi] = useState<KaspiDetails | null>(null)
  const [orders, setOrders] = useState<Payment[]>([])
  const [orderError, setOrderError] = useState<string | null>(null)
  // Which subscription the teacher is looking at. Nothing is bought by
  // choosing: the cards are a choice, the button under them is the action.
  const [chosen, setChosen] = useState<string | null>(null)

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
    getPayments()
      .then((found) => {
        setKaspi(found.enabled ? found.details : null)
        setOrders(found.items)
      })
      .catch(() => undefined)
  }, [])

  async function buy(planId: string) {
    setOrderError(null)
    try {
      const made = await orderPlan(planId)
      setOrders((prev) => [made, ...prev.filter((o) => o.id !== made.id)])
    } catch (error) {
      const code = error instanceof ApiError ? error.reason : ''
      setOrderError(
        code === 'addon_needs_ustaz' || code === 'too_many_open'
          ? t(`pay.error.${code}` as StringKey)
          : t('pay.error.generic'),
      )
    }
  }

  function changed(next: Payment) {
    setOrders((prev) => prev.map((o) => (o.id === next.id ? next : o)))
  }

  const open = orders.filter((o) => o.status === 'awaiting' || o.status === 'submitted')

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
  const subscriptions = offers.filter((o) => o.kind === 'subscription')
  const addons = offers.filter((o) => o.kind === 'addon')
  const currentId = plan?.kind === 'ustaz' ? plan.plan_id : null
  // The current plan first, so "extend" is one press; otherwise the main one.
  const selected =
    subscriptions.find((o) => o._id === chosen) ??
    subscriptions.find((o) => o._id === currentId) ??
    yearOffer ??
    subscriptions[0]
  const price = (amount: number) => amount.toLocaleString('ru-RU')
  const action = !selected
    ? null
    : selected._id === currentId
      ? t('pay.extend')
      : currentId
        ? t('pay.switch')
        : t('pay.buy')

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

      {kaspi
        ? open.map((payment) => (
            <PaymentPanel key={payment.id} payment={payment} details={kaspi} onChanged={changed} />
          ))
        : null}

      {/* A free teacher's next step is the phone: confirming it starts the trial. */}
      {plan?.kind === 'free' && plan.trial_unavailable === 'phone_required' ? <PhoneSection /> : null}

      {offers.length && user?.role === 'teacher' ? (
        <Card as="section" elevation="raised" className="stack stack-md">
          <h2 className="card__title">{t('plan.offers.title')}</h2>
          <div className="plan-offers" role="radiogroup" aria-label={t('plan.choose')}>
            {subscriptions.map((offer) => {
              const isSelected = offer._id === selected?._id
              return (
                <button
                  key={offer._id}
                  type="button"
                  role="radio"
                  aria-checked={isSelected}
                  className={isSelected ? 'plan-offer is-selected' : 'plan-offer'}
                  onClick={() => setChosen(offer._id)}
                >
                  <span className="plan-offer__head">
                    <span className="plan-offer__radio" aria-hidden="true" />
                    <strong>{offer.title}</strong>
                    {offer._id === currentId ? <Badge tone="success">{t('plan.current')}</Badge> : null}
                  </span>
                  <span>
                    {offer.period === 'school_year'
                      ? t('plan.offer.year', { price: price(offer.price) })
                      : t('plan.offer.month', { price: price(offer.price) })}
                  </span>
                  {offer.period === 'school_year' ? <span className="caption">{t('plan.offer.yearNote')}</span> : null}
                  {offer.limits ? (
                    <span className="caption">
                      {t('plan.offer.limits', {
                        videos: offer.limits.videos ?? 0,
                        assessments: offer.limits.assessments ?? 0,
                        plans: offer.limits.lesson_plans ?? 0,
                      })}
                    </span>
                  ) : null}
                </button>
              )
            })}
          </div>

          {selected ? (
            <div className="stack stack-sm">
              {currentId && selected._id !== currentId ? (
                <p className="text-sm text-secondary">{t('plan.switchNote')}</p>
              ) : null}
              {kaspi ? (
                <div>
                  <Button variant="primary" onClick={() => void buy(selected._id)}>
                    {action} — {price(selected.price)} ₸
                  </Button>
                </div>
              ) : (
                <p className="text-sm text-secondary">
                  {t('plan.chosen', { title: selected.title, price: price(selected.price) })} {t('plan.buySoon')}{' '}
                  <a href={CONTACT.phoneHref}>{CONTACT.phone}</a>, <a href={CONTACT.emailHref}>{CONTACT.email}</a>
                </p>
              )}
            </div>
          ) : null}

          {addons.map((offer) => (
            <div key={offer._id} className="plan-addon">
              {/* The add-on's own line already says what it is, in the reader's language. */}
              <span>{t('plan.offer.addon', { n: offer.videos ?? 0, price: price(offer.price) })}</span>
              {kaspi && plan?.kind === 'ustaz' ? (
                <Button size="sm" onClick={() => void buy(offer._id)}>
                  {t('pay.buy')}
                </Button>
              ) : null}
            </div>
          ))}
          {orderError ? <Alert tone="error">{orderError}</Alert> : null}
        </Card>
      ) : null}

      {orders.length ? (
        <Card as="section" elevation="flat" className="stack stack-sm">
          <h2 className="card__title">{t('pay.history')}</h2>
          <ul className="pay-history">
            {orders.map((o) => (
              <li key={o.id}>
                <span>
                  {o.title} · {o.amount.toLocaleString('ru-RU')} ₸ · <code>{o.code}</code>
                </span>
                <Badge tone={o.status === 'confirmed' ? 'success' : o.status === 'rejected' ? 'error' : 'neutral'}>
                  {t(`pay.status.${o.status}` as StringKey)}
                </Badge>
                {o.reason ? <span className="caption">{o.reason}</span> : null}
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      {user?.role === 'teacher' ? <ReferralCard /> : null}

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
