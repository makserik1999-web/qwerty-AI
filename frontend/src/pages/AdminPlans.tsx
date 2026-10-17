/**
 * Plans in the admin panel: one account's plan with the actions on it, and
 * the plans themselves - limits and prices, edited without a deploy.
 *
 * Russian only, like the rest of the panel. Every action needs a reason; the
 * server refuses without one and writes it to the audit log.
 */
import { useEffect, useState } from 'react'
import { Alert, Badge, Button, Card, CardHeader, Input, Select, Table } from '../components/ui'
import * as adminApi from '../lib/admin'
import type { AdminPlan, AdminUserDetail } from '../lib/admin'
import { ApiError, type PlanSummary } from '../lib/api'

const RESOURCE_LABEL: Record<string, string> = {
  videos: 'Видео',
  assessments: 'БЖБ/ТЖБ',
  quiz_drafts: 'Квизы (ИИ)',
  lesson_plans: 'Планы',
}

export const PLAN_LABEL: Record<string, string> = {
  free: '—',
  trial: 'Сынақ',
  ustaz_month: 'Ұстаз · месяц',
  ustaz_year: 'Ұстаз · год',
  paused: 'пауза',
}

function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.reason === 'reason_required') return 'Укажите причину — она попадёт в журнал.'
    if (error.reason === 'target_is_staff') return 'Сотрудника нельзя заблокировать из панели. Сначала снимите роль на сервере.'
    return error.detail || `Ошибка ${error.status}`
  }
  return 'Что-то пошло не так.'
}

function day(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString('ru-RU') : '—'
}

function describePlan(plan: PlanSummary): string {
  if (plan.kind === 'ustaz') return `${plan.title ?? 'Ұстаз'} до ${day(plan.subscription?.expires_at ?? null)}`
  if (plan.kind === 'trial') return 'Сынақ (пробный пакет)'
  if (plan.subscription?.status === 'paused') return `Ұстаз на паузе до ${day(plan.subscription.pause_until)}`
  if (plan.trial_used_up) return 'Тегін — пробный пакет израсходован'
  const why: Record<string, string> = {
    phone_required: 'нет подтверждённого телефона',
    phone_used: 'на этот номер пробный пакет уже был',
    teacher_only: 'ученик',
  }
  return `Тегін${plan.trial_unavailable ? ` — ${why[plan.trial_unavailable] ?? plan.trial_unavailable}` : ''}`
}

/* One account ---------------------------------------------------------------- */

export function UserPlanPanel({
  detail,
  isAdmin,
  onChanged,
}: {
  detail: AdminUserDetail
  isAdmin: boolean
  onChanged: () => void
}) {
  const plan = detail.plan_detail
  const [reason, setReason] = useState('')
  const [planId, setPlanId] = useState('ustaz_month')
  const [months, setMonths] = useState('1')
  const [until, setUntil] = useState('')
  const [extra, setExtra] = useState('10')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState('')

  async function run(label: string, action: () => Promise<unknown>) {
    setBusy(true)
    setError('')
    setDone('')
    try {
      await action()
      setDone(label)
      setReason('')
      onChanged()
    } catch (failure) {
      setError(errorText(failure))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="admin__stack">
      <h3 className="admin__subhead">Тариф</h3>
      <p>
        <strong>{describePlan(plan)}</strong>
        {detail.blocked ? <Badge tone="error"> заблокирован</Badge> : null}
      </p>
      {detail.blocked && detail.blocked_reason ? (
        <p className="caption">Причина блокировки: {detail.blocked_reason}</p>
      ) : null}
      {plan.kind !== 'free' ? (
        <ul className="admin__events">
          {Object.keys(RESOURCE_LABEL).map((key) => {
            const left = plan.available[key as keyof typeof plan.available]
            return (
              <li key={key}>
                {RESOURCE_LABEL[key]}: использовано {plan.used[key as keyof typeof plan.used]},
                осталось {left === null ? 'без лимита' : left}
              </li>
            )
          })}
          {plan.carryover ? <li>Перенос видео с прошлого месяца: {plan.carryover}</li> : null}
          {plan.carried?.assessments ? <li>Перенос БЖБ/ТЖБ с прошлого месяца: {plan.carried.assessments}</li> : null}
          {plan.fair_use?.quiz_drafts ? (
            <li>Квизы: потолок честного использования — {plan.fair_use.quiz_drafts} в месяц</li>
          ) : null}
          {plan.extra_videos ? <li>Докупленные видео: {plan.extra_videos}</li> : null}
        </ul>
      ) : null}

      <label className="field">
        <span className="field__label">Причина (обязательно, попадёт в журнал)</span>
        <Input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Например: пилот в школе №12" />
      </label>

      {isAdmin ? (
        <div className="admin__actions">
          <div className="admin__action">
            <label className="field">
              <span className="field__label">План</span>
              <Select
                value={planId}
                onChange={(event) => setPlanId(event.target.value)}
                options={[
                  { value: 'ustaz_month', label: 'Ұстаз · месяц' },
                  { value: 'ustaz_year', label: 'Ұстаз · учебный год' },
                ]}
              />
            </label>
            {planId === 'ustaz_month' ? (
              <label className="field">
                <span className="field__label">Месяцев</span>
                <Input type="number" min={1} max={12} value={months} onChange={(e) => setMonths(e.target.value)} />
              </label>
            ) : null}
            <label className="field">
              <span className="field__label">Или до даты</span>
              <Input type="date" value={until} onChange={(e) => setUntil(e.target.value)} />
            </label>
            <Button
              variant="primary"
              loading={busy}
              onClick={() =>
                void run('Подписка выдана', () =>
                  adminApi.grantSubscription(detail.id, {
                    plan_id: planId,
                    reason,
                    ...(until ? { until } : planId === 'ustaz_month' ? { months: Number(months) || 1 } : {}),
                  }),
                )
              }
            >
              Выдать или продлить
            </Button>
          </div>

          <div className="admin__action">
            <label className="field">
              <span className="field__label">Добавить видео</span>
              <Input type="number" min={1} max={100} value={extra} onChange={(e) => setExtra(e.target.value)} />
            </label>
            <Button
              loading={busy}
              onClick={() => void run('Видео добавлены', () => adminApi.addExtraVideos(detail.id, Number(extra) || 0, reason))}
            >
              Добавить
            </Button>
          </div>

          {plan.kind === 'ustaz' ? (
            <Button
              variant="quietDanger"
              loading={busy}
              onClick={() => void run('Подписка завершена', () => adminApi.endSubscription(detail.id, reason))}
            >
              Завершить подписку сейчас
            </Button>
          ) : null}
        </div>
      ) : null}

      <div className="row row-wrap">
        <Button loading={busy} onClick={() => void run('Пробный пакет сброшен', () => adminApi.resetTrial(detail.id, reason))}>
          Сбросить пробный пакет
        </Button>
        {detail.blocked ? (
          <Button loading={busy} onClick={() => void run('Разблокирован', () => adminApi.unblockUser(detail.id, reason))}>
            Разблокировать
          </Button>
        ) : (
          <Button
            variant="quietDanger"
            loading={busy}
            onClick={() => void run('Заблокирован', () => adminApi.blockUser(detail.id, reason))}
          >
            Заблокировать
          </Button>
        )}
        {/* For somebody who picked the wrong role at sign-up. */}
        <Button
          loading={busy}
          onClick={() =>
            void run(detail.role === 'teacher' ? 'Теперь ученик' : 'Теперь учитель', () =>
              adminApi.changeRole(detail.id, detail.role === 'teacher' ? 'student' : 'teacher', reason),
            )
          }
        >
          {detail.role === 'teacher' ? 'Сделать учеником' : 'Сделать учителем'}
        </Button>
      </div>

      {error ? <Alert tone="error">{error}</Alert> : null}
      {done ? <Alert tone="success">{done}</Alert> : null}
    </section>
  )
}

/* The plans themselves ------------------------------------------------------- */

export function PlansSection() {
  const [items, setItems] = useState<AdminPlan[] | null>(null)
  const [error, setError] = useState('')

  async function load() {
    try {
      setItems((await adminApi.listPlans()).items)
    } catch (failure) {
      setError(errorText(failure))
    }
  }

  useEffect(() => {
    void load()
  }, [])

  if (error) return <Alert tone="error">{error}</Alert>
  if (!items) return <p className="caption">Загрузка…</p>

  return (
    <div className="admin__stack">
      <p className="caption">
        Новые цифры действуют со следующего запроса. Пустое поле лимита — без лимита. Уже посчитанное остаётся посчитанным.
      </p>
      {items.map((plan) => (
        <PlanEditor key={plan.id} plan={plan} onSaved={load} />
      ))}
    </div>
  )
}

function PlanEditor({ plan, onSaved }: { plan: AdminPlan; onSaved: () => void }) {
  const [title, setTitle] = useState(plan.title)
  const [price, setPrice] = useState(String(plan.price ?? 0))
  const [limits, setLimits] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      Object.keys(RESOURCE_LABEL).map((k) => [k, plan.limits?.[k] == null ? '' : String(plan.limits[k])]),
    ),
  )
  const [carry, setCarry] = useState(String(plan.carryover_cap ?? ''))
  const [carryPapers, setCarryPapers] = useState(String(plan.carryover_caps?.assessments ?? ''))
  const [fairQuizzes, setFairQuizzes] = useState(String(plan.fair_use?.quiz_drafts ?? ''))
  const [effort, setEffort] = useState(plan.max_effort ?? 'high')
  const [videos, setVideos] = useState(String(plan.videos ?? ''))
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ tone: 'success' | 'error'; text: string } | null>(null)

  async function save() {
    setBusy(true)
    setMessage(null)
    const changes: Partial<AdminPlan> & { reason: string } = { reason, title, price: Number(price) || 0 }
    if (plan.kind !== 'addon') {
      changes.limits = Object.fromEntries(
        Object.entries(limits).map(([k, v]) => [k, v.trim() === '' ? null : Number(v)]),
      )
      changes.max_effort = effort
    }
    if (plan.kind === 'subscription' && carry.trim() !== '') changes.carryover_cap = Number(carry)
    if (plan.kind === 'subscription') {
      // Empty takes it away: no carry-over of papers, no ceiling on quizzes.
      changes.carryover_caps = { assessments: carryPapers.trim() === '' ? null : Number(carryPapers) }
      changes.fair_use = { quiz_drafts: fairQuizzes.trim() === '' ? null : Number(fairQuizzes) }
    }
    if (plan.kind === 'addon') changes.videos = Number(videos) || 0
    try {
      await adminApi.editPlan(plan.id, changes)
      setMessage({ tone: 'success', text: 'Сохранено' })
      setReason('')
      onSaved()
    } catch (failure) {
      setMessage({ tone: 'error', text: errorText(failure) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card as="section" className="admin__stack">
      <CardHeader title={`${plan.title} (${plan.id})`} level={3} />
      <div className="admin__actions">
        <label className="field">
          <span className="field__label">Название</span>
          <Input value={title} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <label className="field">
          <span className="field__label">Цена, ₸</span>
          <Input type="number" min={0} value={price} onChange={(e) => setPrice(e.target.value)} />
        </label>
        {plan.kind === 'addon' ? (
          <label className="field">
            <span className="field__label">Видео в пакете</span>
            <Input type="number" min={1} value={videos} onChange={(e) => setVideos(e.target.value)} />
          </label>
        ) : null}
      </div>
      {plan.kind !== 'addon' ? (
        <>
          <Table caption={`Лимиты: ${plan.title}`}>
            <thead>
              <tr>
                {Object.values(RESOURCE_LABEL).map((label) => (
                  <th key={label}>{label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr>
                {Object.keys(RESOURCE_LABEL).map((key) => (
                  <td key={key}>
                    <Input
                      aria-label={RESOURCE_LABEL[key]}
                      type="number"
                      min={0}
                      value={limits[key]}
                      placeholder="без лимита"
                      onChange={(e) => setLimits((prev) => ({ ...prev, [key]: e.target.value }))}
                    />
                  </td>
                ))}
              </tr>
            </tbody>
          </Table>
          <div className="admin__actions">
            <label className="field">
              <span className="field__label">Максимальное качество</span>
              <Select
                value={effort}
                onChange={(e) => setEffort(e.target.value as 'low' | 'medium' | 'high')}
                options={[
                  { value: 'low', label: '480p' },
                  { value: 'medium', label: '720p' },
                  { value: 'high', label: '1080p' },
                ]}
              />
            </label>
            {plan.kind === 'subscription' ? (
              <label className="field">
                <span className="field__label">Потолок переноса видео</span>
                <Input type="number" min={0} value={carry} onChange={(e) => setCarry(e.target.value)} />
              </label>
            ) : null}
            {plan.kind === 'subscription' ? (
              <label className="field">
                <span className="field__label">Потолок переноса БЖБ/ТЖБ</span>
                <Input
                  type="number"
                  min={0}
                  value={carryPapers}
                  placeholder="без переноса"
                  onChange={(e) => setCarryPapers(e.target.value)}
                />
              </label>
            ) : null}
            {plan.kind === 'subscription' ? (
              <label className="field">
                <span className="field__label">Квизы: потолок честного использования в месяц</span>
                <Input
                  type="number"
                  min={0}
                  value={fairQuizzes}
                  placeholder="без потолка"
                  onChange={(e) => setFairQuizzes(e.target.value)}
                />
              </label>
            ) : null}
          </div>
        </>
      ) : null}
      <div className="admin__actions">
        <label className="field admin__grow">
          <span className="field__label">Причина изменения</span>
          <Input value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
        <Button variant="primary" loading={busy} onClick={() => void save()}>
          Сохранить
        </Button>
      </div>
      {message ? <Alert tone={message.tone}>{message.text}</Alert> : null}
    </Card>
  )
}
